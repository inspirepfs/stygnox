"""Scoped Stygnox self-development authority.

Self-development authority is intentionally narrower than ordinary repository
write authority.  Stygnox implementation/tooling changes are restored unless a
human has granted one exact retry scope for the current approved plan, step and
controller-derived gate candidates.  Runtime state, Git internals and likely
secret material are never eligible for this authority.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence

from . import adoption, human_control, planning
from .product import PRODUCT

GRANT_SCHEMA = "stygnox_self_development_grant_v1"
GRANT_PREVIEW_SCHEMA = "stygnox_self_development_grant_preview_v1"
GRANT_RECEIPT_SCHEMA = "stygnox_self_development_grant_receipt_v1"
GATE_KIND = "self-development-authority"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_BASENAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "credentials", "credentials.json", "secrets", "secrets.json",
}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")


class SelfDevelopmentError(RuntimeError):
    """Fail-closed scoped self-development authority error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SelfDevelopmentError(f"invalid self-development path: {value!r}")
    return path.as_posix()


def is_runtime_or_protected(path: str) -> bool:
    path = normalize_path(path)
    return (
        path in {".git", adoption.RUNTIME_NAME, adoption.CONFIG_NAME, adoption.POLICY_NAME, ".ralph"}
        or path.startswith(".git/")
        or path.startswith(f"{adoption.RUNTIME_NAME}/")
        or path.startswith(".ralph/")
    )


def is_secret_path(path: str) -> bool:
    path = normalize_path(path)
    base = PurePosixPath(path).name.lower()
    stem = PurePosixPath(base).stem.lower()
    lower = path.lower()
    if base in _SECRET_BASENAMES or stem in {"secret", "secrets", "credential", "credentials"} or any(base.endswith(suffix) for suffix in _SECRET_SUFFIXES):
        return True
    return any(part in {"secret", "secrets", "credential", "credentials"} for part in lower.split("/"))


def is_self_development_path(root: Path, path: str) -> bool:
    """Return whether a repository path is Stygnox implementation/tooling authority."""
    normalized = normalize_path(path)
    # Only claim the namespace in a Stygnox source tree.  This prevents generic
    # projects with coincidental src/stygnox names from acquiring special rules.
    if not (root / "src" / "stygnox" / "product.py").is_file():
        return False
    return (
        normalized == "pyproject.toml"
        or normalized.startswith("src/stygnox/")
        or normalized.startswith("tests/test_stygnox_")
        or normalized.startswith("tests/test_ralph_")
        or normalized == "scripts/ralph.py"
        or normalized.startswith("scripts/stygnox")
    )


def _file_state(path: Path) -> dict[str, Any]:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    mode = stat.S_IMODE(st.st_mode)
    if path.is_symlink():
        return {"kind": "symlink", "mode": mode, "target": os.readlink(path)}
    if path.is_file():
        return {"kind": "file", "mode": mode, "content": path.read_bytes()}
    return {"kind": "other", "mode": mode}


def authority_snapshot(root: Path) -> dict[str, dict[str, Any]]:
    """Capture exact pre-turn content/mode for every current Stygnox authority path."""
    result = adoption._git(root, "ls-files", "-co", "--exclude-standard", "-z")
    paths = sorted({item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item})
    return {path: _file_state(root / path) for path in paths if is_self_development_path(root, path)}


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        # A self-development candidate is file-oriented; remove a directory only
        # when it is empty so unrelated content can never be erased implicitly.
        try:
            path.rmdir()
        except OSError:
            pass


def _prune_empty_parents(root: Path, path: Path) -> None:
    parent = path.parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def restore_authority_snapshot(root: Path, snapshot: Mapping[str, Mapping[str, Any]], changed_paths: Iterable[str]) -> list[str]:
    """Restore attempted unauthorized Stygnox authority changes to exact pre-turn state."""
    restored: list[str] = []
    for raw in sorted(set(changed_paths)):
        path = normalize_path(raw)
        if not is_self_development_path(root, path):
            continue
        target = root / path
        state = snapshot.get(path, {"kind": "missing"})
        kind = str(state.get("kind") or "missing")
        _remove_path(target)
        if kind == "missing":
            _prune_empty_parents(root, target)
        elif kind == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(state.get("content") or b""))
            os.chmod(target, int(state.get("mode") or 0o644))
        elif kind == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(str(state.get("target") or ""))
        else:
            raise SelfDevelopmentError(f"cannot safely restore non-file authority path: {path}")
        restored.append(path)
    return restored


def candidate_evidence(root: Path, before_manifest: Mapping[str, str], attempted_manifest: Mapping[str, str]) -> list[dict[str, Any]]:
    changed = sorted(path for path in set(before_manifest) | set(attempted_manifest) if before_manifest.get(path) != attempted_manifest.get(path))
    rows: list[dict[str, Any]] = []
    for raw in changed:
        path = normalize_path(raw)
        if not is_self_development_path(root, path):
            continue
        restricted = is_runtime_or_protected(path) or is_secret_path(path)
        body = {
            "path": path,
            "before_fingerprint": str(before_manifest.get(path, "missing")),
            "attempted_fingerprint": str(attempted_manifest.get(path, "missing")),
            "approval_presence": "absent" if before_manifest.get(path, "missing") == "missing" else "present",
            "grantable": not restricted,
            "restriction": "protected-or-secret" if restricted else None,
        }
        body["candidate_sha256"] = _digest(body)
        rows.append(body)
    return rows


def _validate_grant(grant: object) -> dict[str, Any]:
    if not isinstance(grant, Mapping) or grant.get("schema") != GRANT_SCHEMA:
        raise SelfDevelopmentError("active self-development grant is missing or malformed")
    value = dict(grant)
    digest = str(value.get("grant_sha256") or "")
    body = dict(value)
    body.pop("grant_sha256", None)
    if not _HEX64.fullmatch(digest) or digest != _digest(body):
        raise SelfDevelopmentError("active self-development grant integrity check failed")
    return value


def active_grant_for_context(root: Path, state: Mapping[str, Any], *, plan_hash: str, step: int, baseline_sha256: str) -> dict[str, Any] | None:
    raw = state.get("self_development_grant")
    if raw is None:
        return None
    grant = _validate_grant(raw)
    if grant.get("plan_hash") != plan_hash:
        raise SelfDevelopmentError("self-development grant belongs to another plan")
    if int(grant.get("step") or 0) != int(step):
        raise SelfDevelopmentError("self-development grant belongs to another plan step")
    if grant.get("authority_baseline_sha256") != baseline_sha256:
        raise SelfDevelopmentError("self-development grant baseline is stale")
    if grant.get("operator") != state.get("operator") or grant.get("transaction_id") != state.get("transaction_id"):
        raise SelfDevelopmentError("self-development grant operator/transaction authority changed")
    if grant.get("controller_record_sha256") != state.get("controller_record_sha256"):
        raise SelfDevelopmentError("self-development grant controller authority changed")
    if grant.get("tracked_config_sha256") != state.get("tracked_config_sha256") or grant.get("review_sha256") != state.get("review_sha256"):
        raise SelfDevelopmentError("self-development grant execution policy changed")
    resume = state.get("step_resume") if isinstance(state.get("step_resume"), Mapping) else {}
    if resume.get("self_development_grant_sha256") != grant.get("grant_sha256") or resume.get("gate_id") != grant.get("gate_id"):
        raise SelfDevelopmentError("self-development grant is stale for the current gate/authority epoch")
    paths = [normalize_path(str(path)) for path in grant.get("paths") or []]
    if not paths or any(not is_self_development_path(root, path) for path in paths):
        raise SelfDevelopmentError("self-development grant contains non-tooling paths")
    if any(is_runtime_or_protected(path) or is_secret_path(path) for path in paths):
        raise SelfDevelopmentError("self-development grant contains non-grantable paths")
    return grant


def grant_allows_paths(root: Path, state: Mapping[str, Any], *, plan_hash: str, step: int, baseline_sha256: str, paths: Iterable[str]) -> tuple[bool, str, dict[str, Any] | None]:
    requested = sorted({normalize_path(path) for path in paths})
    if not requested:
        return False, "no self-development paths changed", None
    try:
        grant = active_grant_for_context(root, state, plan_hash=plan_hash, step=step, baseline_sha256=baseline_sha256)
    except SelfDevelopmentError as exc:
        return False, str(exc), None
    if grant is None:
        return False, "no active self-development grant", None
    allowed = set(str(path) for path in grant.get("paths") or [])
    extra = sorted(set(requested) - allowed)
    if extra:
        return False, f"self-development changes exceed exact grant: {extra}", grant
    return True, f"exact self-development grant permits {requested}", grant


def _test_policy_allows_candidates(state: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> None:
    plan = planning._validate_plan(state.get("plan"))
    step = plan["steps"][int(state.get("current_step") or 0) - 1]
    policy = str(step.get("test_change_policy") or "none")
    test_rows = [row for row in candidates if str(row.get("path") or "").startswith("tests/")]
    if not test_rows or policy == "modify":
        return
    if policy == "none":
        raise SelfDevelopmentError("current step test_change_policy=none cannot authorize self-development test changes")
    if policy == "add-only":
        existing = [str(row.get("path")) for row in test_rows if row.get("approval_presence") != "absent"]
        if existing:
            raise SelfDevelopmentError(f"current step add-only policy cannot authorize existing self-development tests: {existing}")
        return
    raise SelfDevelopmentError(f"unsupported test change policy for self-development authority: {policy}")


def _gate_context(project: Path, operator: str, plan_hash: str, gate_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], str]:
    try:
        root, state, gate, current, name = human_control._active_gate_context(project, operator, plan_hash, gate_id)
    except human_control.HumanControlError as exc:
        raise SelfDevelopmentError(str(exc)) from exc
    if gate.get("kind") != GATE_KIND:
        raise SelfDevelopmentError("self-development authorization is valid only for the current tooling authority gate")
    candidates = gate.get("self_development_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SelfDevelopmentError("self-development gate has no controller-derived candidates")
    _test_policy_allows_candidates(state, [dict(row) for row in candidates if isinstance(row, Mapping)])
    return root, state, gate, current, name


def build_authorize_preview(project: Path, operator: str, plan_hash: str, gate_id: str, paths: Iterable[str], reason: str) -> dict[str, Any]:
    root, state, gate, current, name = _gate_context(project, operator, plan_hash, gate_id)
    reason_value = " ".join(str(reason or "").split())[:1200]
    if not reason_value:
        raise SelfDevelopmentError("self-development authorization requires a non-empty --reason")
    requested = sorted({normalize_path(path) for path in paths})
    if not requested:
        raise SelfDevelopmentError("self-development authorization requires at least one exact --path")
    candidates = [dict(row) for row in gate.get("self_development_candidates") or [] if isinstance(row, Mapping)]
    candidate_paths = sorted(str(row.get("path") or "") for row in candidates)
    for path in requested:
        if is_runtime_or_protected(path):
            raise SelfDevelopmentError(f"self-development grant refuses runtime/protected path: {path}")
        if is_secret_path(path):
            raise SelfDevelopmentError(f"self-development grant refuses secret/credential path: {path}")
        if not is_self_development_path(root, path):
            raise SelfDevelopmentError(f"self-development grant requires exact Stygnox tooling path: {path}")
    if requested != candidate_paths:
        raise SelfDevelopmentError(f"self-development paths must exactly match the controller-derived candidate: {candidate_paths}")
    body: dict[str, Any] = {
        "schema": GRANT_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "step": int(state["current_step"]),
        "gate_id": gate["gate_id"],
        "gate_sha256": gate["gate_sha256"],
        "transaction_id": state["transaction_id"],
        "controller_record_sha256": state["controller_record_sha256"],
        "tracked_config_sha256": state["tracked_config_sha256"],
        "review_sha256": state.get("review_sha256"),
        "authority_baseline_sha256": current["sha256"],
        "paths": requested,
        "candidates": candidates,
        "reason": reason_value,
        "requires_explicit_confirmation": True,
        "confirmation": "AUTHORIZE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def authorize(project: Path, operator: str, plan_hash: str, gate_id: str, paths: Iterable[str], reason: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "AUTHORIZE":
        raise SelfDevelopmentError("explicit confirmation required: --confirm AUTHORIZE")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise SelfDevelopmentError("--preview must be the exact 64-character preview SHA-256")
    preview = build_authorize_preview(project, operator, plan_hash, gate_id, paths, reason)
    if preview["preview_sha256"] != expected:
        raise SelfDevelopmentError("self-development authorization preview is stale; gate, authority, candidates, or baseline changed")
    root = Path(preview["worktree"])
    state = planning._record(root)
    assert state is not None
    gate = human_control._validate_gate_object(state.get("active_gate"))
    if gate.get("gate_sha256") != preview["gate_sha256"]:
        raise SelfDevelopmentError("self-development gate changed before authorization")
    now = _utc_now()
    grant_body: dict[str, Any] = {
        "schema": GRANT_SCHEMA,
        "plan_hash": preview["plan_hash"],
        "step": preview["step"],
        "gate_id": preview["gate_id"],
        "gate_sha256": preview["gate_sha256"],
        "operator": preview["operator"],
        "transaction_id": preview["transaction_id"],
        "controller_record_sha256": preview["controller_record_sha256"],
        "tracked_config_sha256": preview["tracked_config_sha256"],
        "review_sha256": preview["review_sha256"],
        "authority_baseline_sha256": preview["authority_baseline_sha256"],
        "paths": list(preview["paths"]),
        "candidates": list(preview["candidates"]),
        "reason": preview["reason"],
        "granted_at": now,
    }
    grant_body["grant_sha256"] = _digest(grant_body)
    history = list(state.get("self_development_grant_history") or [])
    gate_history = list(state.get("human_gate_history") or [])
    step_resume = {
        "step": preview["step"],
        "gate_id": preview["gate_id"],
        "reason": f"supervised self-development authority granted for: {', '.join(preview['paths'])}",
        "direction": f"Modify only these exact Stygnox authority paths: {', '.join(preview['paths'])}",
        "allowed_new_tests": [],
        "self_development_grant_sha256": grant_body["grant_sha256"],
        "recorded_at": now,
    }
    updated = dict(state)
    updated.update({
        "status": "APPROVED",
        "execution_authority_granted": True,
        "active_gate": None,
        "step_authority_baseline_sha256": preview["authority_baseline_sha256"],
        "step_resume": step_resume,
        "self_development_grant": grant_body,
        "self_development_grant_history": [*history[-49:], grant_body],
        "human_gate_history": [*gate_history[-49:], {**gate, "state": "SELF_DEVELOPMENT_AUTHORIZED", "grant_sha256": grant_body["grant_sha256"], "decided_at": now}],
    })
    written = planning._write(root, updated)
    receipt = {
        "schema": GRANT_RECEIPT_SCHEMA,
        "product_version": PRODUCT.version,
        "plan_hash": preview["plan_hash"],
        "step": preview["step"],
        "gate_id": preview["gate_id"],
        "gate_sha256": preview["gate_sha256"],
        "grant_sha256": grant_body["grant_sha256"],
        "preview_sha256": expected,
        "paths": list(preview["paths"]),
        "reason": preview["reason"],
        "granted_at": now,
    }
    receipt["record_sha256"] = _digest(receipt)
    adoption.write_runtime_record(root, f"self-development-grant-{preview['gate_id'].lower()}.json", receipt, actor="controller")
    return {**receipt, "result": "SELF_DEVELOPMENT_AUTHORIZED", "plan_record_sha256": written["record_sha256"]}


def expire_active_grant(project: Path, operator: str, *, expected_grant_sha256: str | None, reason: str) -> dict[str, Any] | None:
    if not expected_grant_sha256:
        return None
    root = adoption.resolve_worktree(project)
    state = planning._record(root)
    assert state is not None
    raw = state.get("self_development_grant")
    if raw is None:
        return None
    grant = _validate_grant(raw)
    if grant.get("grant_sha256") != expected_grant_sha256:
        raise SelfDevelopmentError("active self-development grant changed before expiry")
    now = _utc_now()
    expiration = {
        "grant_sha256": grant["grant_sha256"],
        "plan_hash": grant["plan_hash"],
        "step": grant["step"],
        "gate_id": grant["gate_id"],
        "reason": " ".join(str(reason or "").split())[:1200],
        "expired_at": now,
    }
    expiration["record_sha256"] = _digest(expiration)
    expirations = list(state.get("self_development_expirations") or [])
    updated = dict(state)
    updated["self_development_grant"] = None
    updated["self_development_expirations"] = [*expirations[-49:], expiration]
    # Do not carry grant-specific steering into another controller turn.
    resume = updated.get("step_resume") if isinstance(updated.get("step_resume"), Mapping) else None
    if resume and resume.get("self_development_grant_sha256") == expected_grant_sha256:
        updated["step_resume"] = None
    written = planning._write(root, updated)
    return {**expiration, "plan_record_sha256": written["record_sha256"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox self-development", description="Exact one-retry Stygnox self-development authority for a controller-derived tooling gate.")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status", help="show current active self-development authority")
    status.add_argument("--project", type=Path, default=Path.cwd())
    for action in ("authorize-preview", "authorize"):
        command = sub.add_parser(action)
        command.add_argument("plan_hash")
        command.add_argument("--gate", required=True)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--operator", required=True)
        command.add_argument("--path", action="append", required=True)
        command.add_argument("--reason", required=True)
        if action == "authorize":
            command.add_argument("--preview", required=True)
            command.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            root = adoption.resolve_worktree(args.project)
            state = planning._record(root, required=False)
            result = {
                "schema": "stygnox_self_development_status_v1",
                "product_version": PRODUCT.version,
                "worktree": str(root),
                "grant": state.get("self_development_grant") if state else None,
                "grant_history": list(state.get("self_development_grant_history") or []) if state else [],
                "expirations": list(state.get("self_development_expirations") or []) if state else [],
            }
        elif args.action == "authorize-preview":
            result = build_authorize_preview(args.project, args.operator, args.plan_hash, args.gate, args.path, args.reason)
        else:
            result = authorize(args.project, args.operator, args.plan_hash, args.gate, args.path, args.reason, args.preview, args.confirm)
    except (SelfDevelopmentError, human_control.HumanControlError, planning.PlanningError, adoption.AdoptionError, OSError, ValueError) as exc:
        print(f"stygnox: self-development refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
