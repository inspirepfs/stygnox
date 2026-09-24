"""Installed D8.2 bootstrap/admission and tracked/runtime boundary.

This module is deliberately independent of the legacy Ralph controller.  It
implements only the pre-controller bootstrap authority boundary: read-only
preview, explicit confirmation bound to an exact preview, exact tracked policy
material, and ignored controller-owned runtime evidence.

D8.3 owns transactional controller execution and clean/dirty recovery.  For a
dirty repository D8.2 therefore accepts only operator-owned recovery evidence
created outside Stygnox authority; it never creates, owns, or restores that
capture itself.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from typing import Any

from .product import PRODUCT


CONFIG_NAME = "stygnox.toml"
POLICY_NAME = "stygnox.policy.md"
RUNTIME_NAME = ".stygnox"
RUNTIME_IGNORE = "/.stygnox/"
PREVIEW_SCHEMA = "stygnox_adoption_preview_v1"
HANDOFF_SCHEMA = "stygnox_adoption_handoff_v1"
DIRTY_EVIDENCE_SCHEMA = "stygnox_dirty_recovery_attestation_v1"
CONFIG_SCHEMA = "stygnox_project_config_v1"
POLICY_SCHEMA = "stygnox_project_policy_v1"
_RUNTIME_WRITE_ACTOR = "controller"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AdoptionError(RuntimeError):
    """Fail-closed admission error."""


@dataclass(frozen=True, slots=True)
class CommandIdentity:
    executable: Path
    package_file: Path
    version: str


@dataclass(frozen=True, slots=True)
class GitBaseline:
    worktree: Path
    journey: str
    head: str | None
    branch: str
    status: str
    index_sha256: str
    staged_sha256: str
    unstaged_sha256: str
    untracked: tuple[dict[str, str], ...]
    dirty_categories: tuple[str, ...]
    sha256: str

    def public(self) -> dict[str, Any]:
        return {
            "worktree": str(self.worktree),
            "journey": self.journey,
            "head": self.head,
            "branch": self.branch,
            "status": self.status,
            "index_sha256": self.index_sha256,
            "staged_sha256": self.staged_sha256,
            "unstaged_sha256": self.unstaged_sha256,
            "untracked": list(self.untracked),
            "dirty_categories": list(self.dirty_categories),
            "sha256": self.sha256,
        }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _git_env() -> dict[str, str]:
    environment = os.environ.copy()
    # Read-only admission must not opportunistically refresh/write the index.
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _git(candidate: Path, *args: str, check: bool = True, text: bool = False) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        ["git", "-C", str(candidate), *args],
        env=_git_env(),
        capture_output=True,
        text=text,
        check=False,
    )
    if check and result.returncode != 0:
        stdout = result.stdout if text else result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr if text else result.stderr.decode("utf-8", errors="replace")
        raise AdoptionError(
            f"git {' '.join(args)} failed for {candidate} ({result.returncode}): "
            f"{(stderr or stdout).strip()}"
        )
    return result


def resolve_worktree(candidate: Path) -> Path:
    requested = candidate.expanduser().resolve()
    result = _git(requested, "rev-parse", "--show-toplevel", text=True)
    root = Path(result.stdout.strip()).resolve()
    if not root.is_dir():
        raise AdoptionError(f"Git worktree does not exist: {root}")
    return root


def _file_record(path: Path, relative: str) -> dict[str, str]:
    info = path.lstat()
    mode = f"{stat.S_IMODE(info.st_mode):04o}"
    if stat.S_ISLNK(info.st_mode):
        return {"path": relative, "type": "symlink", "mode": mode, "sha256": _sha256_bytes(os.readlink(path).encode())}
    if not stat.S_ISREG(info.st_mode):
        raise AdoptionError(f"unsupported untracked object in baseline: {relative}")
    return {"path": relative, "type": "file", "mode": mode, "sha256": sha256_file(path)}


def _status_categories(status: str) -> tuple[str, ...]:
    categories: set[str] = set()
    for line in status.splitlines():
        if len(line) < 2:
            continue
        code = line[:2]
        if code == "??":
            categories.add("untracked")
            continue
        if code[0] not in {" ", "?"}:
            categories.add("staged")
        if code[1] != " ":
            categories.add("unstaged")
        if "R" in code:
            categories.add("renamed")
        if "D" in code:
            categories.add("deleted")
    return tuple(sorted(categories))


def capture_baseline(candidate: Path) -> GitBaseline:
    root = resolve_worktree(candidate)
    head_result = _git(root, "rev-parse", "--verify", "HEAD", check=False, text=True)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    branch_result = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False, text=True)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "(detached)"
    status_result = _git(root, "status", "--porcelain=v1", "--untracked-files=all", text=True)
    status = status_result.stdout
    index_bytes = _git(root, "ls-files", "-s", "-z").stdout
    staged_bytes = _git(root, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv").stdout
    unstaged_bytes = _git(root, "diff", "--binary", "--no-ext-diff", "--no-textconv").stdout
    untracked_bytes = _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    untracked_paths = [item.decode("utf-8", errors="surrogateescape") for item in untracked_bytes.split(b"\0") if item]
    untracked = tuple(_file_record(root / relative, relative) for relative in sorted(untracked_paths))
    dirty_categories = _status_categories(status)
    if head is None:
        journey = "new-unborn"
    elif status:
        journey = "dirty"
    else:
        journey = "clean"
    payload = {
        "worktree": str(root),
        "journey": journey,
        "head": head,
        "branch": branch,
        "status": status,
        "index_sha256": _sha256_bytes(index_bytes),
        "staged_sha256": _sha256_bytes(staged_bytes),
        "unstaged_sha256": _sha256_bytes(unstaged_bytes),
        "untracked": list(untracked),
        "dirty_categories": list(dirty_categories),
    }
    return GitBaseline(
        worktree=root,
        journey=journey,
        head=head,
        branch=branch,
        status=status,
        index_sha256=payload["index_sha256"],
        staged_sha256=payload["staged_sha256"],
        unstaged_sha256=payload["unstaged_sha256"],
        untracked=untracked,
        dirty_categories=dirty_categories,
        sha256=_sha256_bytes(_canonical_json(payload)),
    )


def resolve_installed_command(worktree: Path) -> CommandIdentity:
    resolved = shutil.which(PRODUCT.command)
    if not resolved:
        raise AdoptionError("installed stygnox command is not resolvable on PATH")
    executable = Path(resolved).resolve()
    package_file = Path(__file__).resolve()
    if _is_within(executable, worktree):
        raise AdoptionError(f"installed stygnox executable resolves inside adopting worktree: {executable}")
    if _is_within(package_file, worktree):
        raise AdoptionError(f"stygnox package import resolves from adopting worktree: {package_file}")
    return CommandIdentity(executable=executable, package_file=package_file, version=PRODUCT.version)


def _validated_operator(value: str) -> str:
    operator = str(value or "").strip()
    if not operator or len(operator) > 128 or any(ord(char) < 32 for char in operator):
        raise AdoptionError("--operator must be 1-128 printable characters")
    return operator


def render_config() -> str:
    return (
        f'schema = "{CONFIG_SCHEMA}"\n'
        f'runtime_directory = "{RUNTIME_NAME}"\n'
        f'policy_file = "{POLICY_NAME}"\n'
        "\n[defaults]\n"
        'provider = ""\n'
        'model = ""\n'
        'effort = ""\n'
        "\n[authority]\n"
        'stage = "bootstrap-policy-runtime-boundary"\n'
        "controller_execution = false\n"
    )


def render_policy(operator: str) -> str:
    return f"""# Stygnox Project Policy

Schema: `{POLICY_SCHEMA}`
Runtime: `{RUNTIME_NAME}/`
Named operator / human decision maker: `{operator}`

## D8.2 bootstrap authority

- This tracked file and `stygnox.toml` are project material and remain subject
  to normal Git review. Ignored runtime material never substitutes for them.
- `{RUNTIME_NAME}/` is controller-owned runtime. Agents and implementation
  workers must not create, edit, delete, rename, or adopt content there.
- Provider, model, and effort defaults are neutral. A later reviewed stage must
  explicitly authorize any non-neutral selection before controller execution.
- The D8.2 handoff grants only the exact bootstrap writes previewed by the
  installed command. It does **not** grant autonomous controller execution.
- A changed baseline, changed tracked policy/configuration, changed external
  dirty-recovery evidence, or expanded scope invalidates confirmation and
  requires a fresh preview and explicit handoff.
- D8.3 owns transaction, interruption, rollback, and restoration behavior.
"""


def _proposed_gitignore(root: Path) -> tuple[str, str, str]:
    path = root / ".gitignore"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise AdoptionError("refusing non-regular .gitignore")
        before = path.read_text(encoding="utf-8")
    else:
        before = ""
    normalized = {line.strip() for line in before.splitlines()}
    if RUNTIME_IGNORE in normalized or ".stygnox/" in normalized:
        return before, before, "unchanged"
    suffix = "" if not before or before.endswith("\n") else "\n"
    after = before + suffix + "\n# Stygnox controller-owned runtime\n" + RUNTIME_IGNORE + "\n"
    return before, after, "create" if not path.exists() else "modify"


def _planned_tracked_files(root: Path, operator: str) -> tuple[list[dict[str, Any]], list[str]]:
    conflicts: list[str] = []
    plans: list[dict[str, Any]] = []
    for name, content in ((CONFIG_NAME, render_config()), (POLICY_NAME, render_policy(operator))):
        path = root / name
        if path.exists() or path.is_symlink():
            conflicts.append(name)
        plans.append(
            {
                "path": name,
                "action": "create",
                "sha256": _sha256_bytes(content.encode("utf-8")),
                "content": content,
            }
        )
    before, after, action = _proposed_gitignore(root)
    plans.insert(
        0,
        {
            "path": ".gitignore",
            "action": action,
            "before_sha256": _sha256_bytes(before.encode("utf-8")),
            "sha256": _sha256_bytes(after.encode("utf-8")),
            "content": after,
        },
    )
    return plans, conflicts


def _parse_dirty_evidence(path: Path, baseline: GitBaseline) -> dict[str, Any]:
    evidence_path = path.expanduser().resolve()
    if _is_within(evidence_path, baseline.worktree):
        raise AdoptionError("dirty recovery attestation must be outside the adopting worktree")
    if evidence_path.is_symlink() or not evidence_path.is_file():
        raise AdoptionError("dirty recovery attestation must be a regular external file")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdoptionError(f"invalid dirty recovery attestation: {exc}") from exc
    if evidence.get("schema") != DIRTY_EVIDENCE_SCHEMA:
        raise AdoptionError("unsupported dirty recovery attestation schema")
    if Path(str(evidence.get("worktree", ""))).expanduser().resolve() != baseline.worktree:
        raise AdoptionError("dirty recovery attestation worktree does not match current worktree")
    if evidence.get("baseline_sha256") != baseline.sha256:
        raise AdoptionError("dirty recovery attestation does not match current baseline")
    if evidence.get("verified") is not True or evidence.get("restoration_rehearsed") is not True:
        raise AdoptionError("dirty recovery attestation must record verified=true and restoration_rehearsed=true")
    verified_by = str(evidence.get("verified_by") or "").strip()
    if not verified_by:
        raise AdoptionError("dirty recovery attestation requires verified_by")
    capture_text = str(evidence.get("capture_path") or "")
    if not capture_text:
        raise AdoptionError("dirty recovery attestation requires capture_path")
    capture = Path(capture_text).expanduser().resolve()
    if _is_within(capture, baseline.worktree):
        raise AdoptionError("dirty recovery capture must remain outside the adopting worktree")
    if capture.is_symlink() or not capture.is_file():
        raise AdoptionError("dirty recovery capture must be an existing regular external file")
    capture_sha = str(evidence.get("capture_sha256") or "")
    if not _HEX64.fullmatch(capture_sha) or sha256_file(capture) != capture_sha:
        raise AdoptionError("dirty recovery capture digest verification failed")
    categories = {str(item) for item in evidence.get("categories") or []}
    missing = set(baseline.dirty_categories) - categories
    if missing:
        raise AdoptionError(f"dirty recovery attestation misses baseline categories: {sorted(missing)}")
    return {
        "attestation_path": str(evidence_path),
        "attestation_sha256": sha256_file(evidence_path),
        "capture_path": str(capture),
        "capture_sha256": capture_sha,
        "verified_by": verified_by,
        "verified": True,
        "restoration_rehearsed": True,
        "categories": sorted(categories),
    }


def build_preview(project: Path, operator: str, *, dirty_evidence: Path | None = None) -> dict[str, Any]:
    baseline = capture_baseline(project)
    operator_name = _validated_operator(operator)
    command = resolve_installed_command(baseline.worktree)
    tracked, conflicts = _planned_tracked_files(baseline.worktree, operator_name)
    dirty: dict[str, Any] = {"required": baseline.journey == "dirty", "evidence": None}
    evidence_error: str | None = None
    if baseline.journey == "dirty" and dirty_evidence is not None:
        try:
            dirty["evidence"] = _parse_dirty_evidence(dirty_evidence, baseline)
        except AdoptionError as exc:
            evidence_error = str(exc)
    elif baseline.journey != "dirty" and dirty_evidence is not None:
        evidence_error = "dirty recovery evidence is only valid for a dirty journey"
    admissible = not conflicts and evidence_error is None and (baseline.journey != "dirty" or dirty["evidence"] is not None)
    authority_paths = [item["path"] for item in tracked if item["action"] != "unchanged"]
    authority_paths.append(f"{RUNTIME_NAME}/adoption.json")
    body: dict[str, Any] = {
        "schema": PREVIEW_SCHEMA,
        "product": {"name": PRODUCT.name, "version": PRODUCT.version, "stage": PRODUCT.stage},
        "command": {
            "executable": str(command.executable),
            "package_file": str(command.package_file),
            "outside_worktree": True,
        },
        "operator": operator_name,
        "baseline": baseline.public(),
        "tracked_review": tracked,
        "runtime": {
            "path": RUNTIME_NAME,
            "ignored_pattern": RUNTIME_IGNORE,
            "owner": "controller",
            "agent_writable": False,
            "native_delta": False,
        },
        "defaults": {"provider": None, "model": None, "effort": None},
        "authority": {
            "scope": "bootstrap-policy-runtime-boundary-only",
            "paths": authority_paths,
            "controller_execution": False,
        },
        "dirty_recovery": dirty,
        "conflicts": conflicts,
        "evidence_error": evidence_error,
        "admissible": admissible,
        "requires_explicit_confirmation": True,
    }
    body["preview_sha256"] = _sha256_bytes(_canonical_json(body))
    return body


def _require_preview_digest(value: str) -> str:
    digest = str(value or "").strip().lower()
    if not _HEX64.fullmatch(digest):
        raise AdoptionError("--preview must be the exact 64-character preview SHA-256")
    return digest


def _render_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, content: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.stygnox-tmp-{os.getpid()}")
    if temporary.exists():
        raise AdoptionError(f"temporary bootstrap path already exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_runtime_record(
    root: Path,
    name: str,
    payload: Mapping[str, Any],
    *,
    actor: str,
) -> Path:
    if actor != _RUNTIME_WRITE_ACTOR:
        raise PermissionError("Stygnox runtime is controller-owned; agent/runtime writes are refused")
    if not name or Path(name).name != name or name in {".", ".."}:
        raise AdoptionError("runtime record name must be one plain filename")
    runtime = root.resolve() / RUNTIME_NAME
    runtime.mkdir(mode=0o700, parents=False, exist_ok=True)
    os.chmod(runtime, 0o700)
    target = runtime / name
    _atomic_write(target, _render_json(dict(payload)), mode=0o600)
    return target


def abort_adoption(project: Path, operator: str, preview_sha256: str, *, dirty_evidence: Path | None = None) -> dict[str, Any]:
    expected = _require_preview_digest(preview_sha256)
    preview = build_preview(project, operator, dirty_evidence=dirty_evidence)
    if preview["preview_sha256"] != expected:
        raise AdoptionError("preview is stale: baseline, policy/configuration, command, or recovery evidence changed; preview again")
    return {
        "schema": "stygnox_adoption_abort_v1",
        "result": "ABORTED_NO_CHANGE",
        "preview_sha256": expected,
        "worktree": preview["baseline"]["worktree"],
        "project_mutation": False,
        "authority_granted": False,
    }


def handoff_adoption(
    project: Path,
    operator: str,
    preview_sha256: str,
    confirmation: str,
    *,
    dirty_evidence: Path | None = None,
) -> dict[str, Any]:
    if confirmation != "HANDOFF":
        raise AdoptionError("explicit confirmation required: --confirm HANDOFF")
    expected = _require_preview_digest(preview_sha256)
    preview = build_preview(project, operator, dirty_evidence=dirty_evidence)
    if preview["preview_sha256"] != expected:
        raise AdoptionError("preview is stale: baseline, policy/configuration, command, or recovery evidence changed; preview again")
    if not preview["admissible"]:
        details = preview.get("evidence_error") or ", ".join(preview.get("conflicts") or []) or "admission requirements incomplete"
        raise AdoptionError(f"handoff refused: {details}")

    root = Path(preview["baseline"]["worktree"])
    # The confirmation authorizes exactly this rendered tracked material.  Refuse
    # any pre-existing reserved policy/config rather than overwriting it.
    for name in (CONFIG_NAME, POLICY_NAME):
        if (root / name).exists() or (root / name).is_symlink():
            raise AdoptionError(f"handoff refused because reserved tracked path appeared after preview: {name}")

    plans = {item["path"]: item for item in preview["tracked_review"]}

    recovery_source: dict[str, Any]
    if preview["baseline"]["journey"] == "dirty":
        evidence = preview["dirty_recovery"].get("evidence")
        if not isinstance(evidence, dict):
            raise AdoptionError("dirty handoff requires bound operator recovery evidence")
        recovery_source = {
            "kind": "operator-external",
            "attestation_path": evidence["attestation_path"],
            "attestation_sha256": evidence["attestation_sha256"],
            "capture_path": evidence["capture_path"],
            "capture_sha256": evidence["capture_sha256"],
            "baseline_sha256": preview["baseline"]["sha256"],
        }
    else:
        try:
            from .recovery import create_internal_checkpoint

            recovery_source = create_internal_checkpoint(root, preview["baseline"])
        except Exception as exc:
            raise AdoptionError(f"cannot create pre-authority recovery checkpoint: {exc}") from exc

    if plans[".gitignore"]["action"] != "unchanged":
        _atomic_write(root / ".gitignore", plans[".gitignore"]["content"])
    _atomic_write(root / CONFIG_NAME, plans[CONFIG_NAME]["content"])
    _atomic_write(root / POLICY_NAME, plans[POLICY_NAME]["content"])

    # Verify the runtime ignore boundary before controller bookkeeping appears.
    ignored = _git(root, "check-ignore", "-q", "--no-index", f"{RUNTIME_NAME}/probe", check=False)
    if ignored.returncode != 0:
        raise AdoptionError("tracked ignore policy did not exclude the Stygnox runtime")

    authority_baseline = capture_baseline(root).public()
    handoff = {
        "schema": HANDOFF_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "preview_sha256": expected,
        "baseline_sha256": preview["baseline"]["sha256"],
        "baseline": preview["baseline"],
        "authority_baseline": authority_baseline,
        "journey": preview["baseline"]["journey"],
        "command": preview["command"],
        "authority": preview["authority"],
        "tracked_files": {
            path: plans[path]["sha256"] for path in (".gitignore", CONFIG_NAME, POLICY_NAME)
        },
        "dirty_recovery": preview["dirty_recovery"],
        "recovery_source": recovery_source,
        "controller_execution": False,
        "next_stage": "D8.3 transaction/recovery qualification before autonomous controller execution",
    }
    runtime_record = write_runtime_record(root, "adoption.json", handoff, actor=_RUNTIME_WRITE_ACTOR)
    return {
        **handoff,
        "result": "HANDOFF_RECORDED",
        "runtime_record": str(runtime_record.relative_to(root)),
        "runtime_ignored": True,
        "tracked_review_required": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox adopt",
        description=(
            "D8.2 installed bootstrap/admission surface. Preview is read-only; "
            "handoff requires an exact preview digest and explicit HANDOFF confirmation."
        ),
    )
    sub = parser.add_subparsers(dest="action", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--project", type=Path, default=Path.cwd(), help="Git worktree or path inside it")
        command.add_argument("--operator", required=True, help="named human operator / decision maker")
        command.add_argument(
            "--dirty-recovery-evidence",
            type=Path,
            help="external operator-owned D8.2 recovery attestation for a dirty journey",
        )

    preview = sub.add_parser("preview", help="produce a no-change adoption preview")
    common(preview)

    abort = sub.add_parser("abort", help="record a no-change abort against an exact preview")
    common(abort)
    abort.add_argument("--preview", required=True, help="exact preview SHA-256")

    handoff = sub.add_parser("handoff", help="perform the exact confirmed bootstrap handoff")
    common(handoff)
    handoff.add_argument("--preview", required=True, help="exact preview SHA-256")
    handoff.add_argument("--confirm", required=True, help="must be HANDOFF")
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview":
            result = build_preview(args.project, args.operator, dirty_evidence=args.dirty_recovery_evidence)
        elif args.action == "abort":
            result = abort_adoption(
                args.project,
                args.operator,
                args.preview,
                dirty_evidence=args.dirty_recovery_evidence,
            )
        else:
            result = handoff_adoption(
                args.project,
                args.operator,
                args.preview,
                args.confirm,
                dirty_evidence=args.dirty_recovery_evidence,
            )
    except AdoptionError as exc:
        print(f"stygnox: adoption refused: {exc}", file=sys.stderr)
        return 2
    print(_render_json(result), end="")
    return 0
