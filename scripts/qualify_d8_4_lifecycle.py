#!/usr/bin/env python3
"""Qualify D8.4 legacy migration, upgrade compatibility, and uninstall safety.

The qualifier builds one wheel, installs that exact artifact in a fresh venv,
then drives only the installed ``stygnox`` command against isolated Git
fixtures.  It covers fresh pre-change refusal, clean and dirty legacy
migration/rollback, D8.3 runtime compatibility, retained evidence, and actual
pip uninstall with no tracked project mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = runpy.run_path(str(ROOT / "src" / "stygnox" / "_version.py"))["__version__"]
ATTESTATION_SCHEMA = "stygnox_dirty_recovery_attestation_v1"
OPERATOR_MANIFEST_SCHEMA = "stygnox_operator_recovery_manifest_v1"
OPERATOR = "D8.4 Operator"


def run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=root, check=check)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def parse_json(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"expected JSON output:\n{result.stdout}\nstderr:\n{result.stderr}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("expected JSON object output")
    return value


def venv_bin(root: Path, name: str) -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return root / bindir / f"{name}{suffix}"


def tree_snapshot(root: Path) -> tuple[tuple[str, str, str, str], ...]:
    rows: list[tuple[str, str, str, str]] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        rel_dir = current.relative_to(root)
        kept: list[str] = []
        for name in sorted(dirnames):
            path = current / name
            relative = (rel_dir / name).as_posix()
            if relative == ".git" or relative.startswith(".git/") or relative == ".stygnox" or relative.startswith(".stygnox/"):
                continue
            if path.is_symlink():
                rows.append(("symlink", relative, f"{path.lstat().st_mode & 0o7777:04o}", os.readlink(path)))
            else:
                kept.append(name)
                rows.append(("dir", relative, f"{path.lstat().st_mode & 0o7777:04o}", ""))
        dirnames[:] = kept
        for name in sorted(filenames):
            path = current / name
            relative = (rel_dir / name).as_posix()
            if relative.startswith(".git/") or relative.startswith(".stygnox/"):
                continue
            mode = f"{path.lstat().st_mode & 0o7777:04o}"
            if path.is_symlink():
                rows.append(("symlink", relative, mode, os.readlink(path)))
            else:
                rows.append(("file", relative, mode, sha256(path)))
    return tuple(sorted(rows))


def git_state(root: Path) -> dict[str, object]:
    head = git(root, "rev-parse", "--verify", "HEAD", check=False)
    branch = git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else "(detached)",
        "status": git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout,
        "index": sha256_bytes(subprocess.run(["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True, check=True).stdout),
        "staged": sha256_bytes(subprocess.run(["git", "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"], cwd=root, capture_output=True, check=True).stdout),
        "unstaged": sha256_bytes(subprocess.run(["git", "diff", "--binary", "--no-ext-diff", "--no-textconv"], cwd=root, capture_output=True, check=True).stdout),
        "tree": tree_snapshot(root),
    }


def assert_state(before: dict[str, object], after: dict[str, object], label: str) -> None:
    for key in ("head", "branch", "status", "index", "staged", "unstaged", "tree"):
        if before[key] != after[key]:
            raise RuntimeError(f"{label}: {key} changed")


def installed_env(environment: Path, hostile: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(venv_bin(environment, "python").parent), env.get("PATH", "")))
    env["PYTHONPATH"] = str(hostile)
    return env


def sx(binary: Path, fixture: Path, env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([str(binary), *args], cwd=fixture, env=env, check=check)


def adopt(binary: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sx(binary, fixture, env, "adopt", action, "--project", str(fixture), "--operator", OPERATOR, *args, check=check)


def tx(binary: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    base = ["transaction", action, "--project", str(fixture)]
    if action != "status":
        base += ["--operator", OPERATOR]
    return sx(binary, fixture, env, *base, *args, check=check)


def migrate(binary: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sx(binary, fixture, env, "migrate", action, "--project", str(fixture), "--operator", OPERATOR, *args, check=check)


def upgrade(binary: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sx(binary, fixture, env, "upgrade", action, "--project", str(fixture), "--operator", OPERATOR, *args, check=check)


def uninstall(binary: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return sx(binary, fixture, env, "uninstall", action, "--project", str(fixture), "--operator", OPERATOR, *args, check=check)


def init_repo(root: Path, *, legacy: bool) -> None:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.name", "D8.4 Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    for name, content in {
        "README.fixture": "fixture\n",
        "rename-me.txt": "rename baseline\n",
        "delete-me.txt": "delete baseline\n",
        "staged-mod.txt": "staged baseline\n",
        "unstaged-mod.txt": "unstaged baseline\n",
    }.items():
        (root / name).write_text(content, encoding="utf-8")
    if legacy:
        (root / ".gitignore").write_text(".ralph/*\n!.ralph/policy.md\n", encoding="utf-8")
        legacy_root = root / ".ralph"
        (legacy_root / "reports").mkdir(parents=True)
        (legacy_root / "policy.md").write_text("legacy tracked policy\n", encoding="utf-8")
        (legacy_root / "journal.md").write_text("legacy journal\n", encoding="utf-8")
        (legacy_root / "reports" / "summary.json").write_text('{"legacy": true}\n', encoding="utf-8")
        (legacy_root / "state.json").write_text(
            json.dumps(
                {
                    "schema": "zen_ralph_lite_state_v1",
                    "status": "IDLE",
                    "controller_runtime": None,
                    "updated_at": "2026-09-24T10:46:45+00:00",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "fixture baseline")


def make_dirty(root: Path) -> None:
    (root / "staged-mod.txt").write_text("staged changed\n", encoding="utf-8")
    git(root, "add", "staged-mod.txt")
    (root / "unstaged-mod.txt").write_text("unstaged changed\n", encoding="utf-8")
    git(root, "mv", "rename-me.txt", "renamed.txt")
    (root / "delete-me.txt").unlink()
    (root / "untracked.txt").write_text("untracked baseline\n", encoding="utf-8")
    (root / "untracked.txt").chmod(0o664)
    (root / "empty-untracked-dir").mkdir()
    # Exercise migration index preservation with a staged + unstaged legacy policy.
    policy = root / ".ralph" / "policy.md"
    policy.write_text("legacy staged policy\n", encoding="utf-8")
    git(root, "add", ".ralph/policy.md")
    policy.write_text("legacy unstaged policy after staged version\n", encoding="utf-8")


def manifest_entries(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for kind, relative, mode, value in tree_snapshot(root):
        if kind == "file":
            rows.append({"path": relative, "type": "file", "mode": mode, "sha256": value})
        elif kind == "dir":
            rows.append({"path": relative, "type": "dir", "mode": mode, "sha256": ""})
        else:
            rows.append({"path": relative, "type": "symlink", "mode": mode, "sha256": sha256_bytes(value.encode()), "target": value})
    return sorted(rows, key=lambda item: item["path"])


def external_capture(fixture: Path, preview: dict, evidence_root: Path) -> Path:
    evidence_root.mkdir(parents=True)
    capture = evidence_root / "dirty-baseline.tar.gz"
    with tarfile.open(capture, "w:gz") as archive:
        archive.add(fixture, arcname="repo", recursive=True)
    entries = manifest_entries(fixture)
    index = fixture / ".git" / "index"
    manifest = {
        "schema": OPERATOR_MANIFEST_SCHEMA,
        "baseline_sha256": preview["baseline"]["sha256"],
        "head": preview["baseline"]["head"],
        "branch": preview["baseline"]["branch"],
        "status": preview["baseline"]["status"],
        "index_file_sha256": sha256(index) if index.is_file() else None,
        "worktree_manifest": entries,
        "worktree_manifest_sha256": canonical_digest(entries),
    }
    manifest_path = evidence_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    attestation = {
        "schema": ATTESTATION_SCHEMA,
        "worktree": str(fixture.resolve()),
        "baseline_sha256": preview["baseline"]["sha256"],
        "capture_path": str(capture.resolve()),
        "capture_sha256": sha256(capture),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path),
        "verified": True,
        "restoration_rehearsed": True,
        "verified_by": "Independent D8.4 qualification operator",
        "categories": preview["baseline"]["dirty_categories"],
    }
    attestation_path = evidence_root / "attestation.json"
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return attestation_path


def handoff_and_begin(binary: Path, fixture: Path, env: dict[str, str], evidence_root: Path | None = None) -> None:
    initial = parse_json(adopt(binary, fixture, env, "preview"))
    evidence: Path | None = None
    if initial["baseline"]["journey"] == "dirty":
        if initial["admissible"]:
            raise RuntimeError("dirty fixture admitted without operator recovery evidence")
        if evidence_root is None:
            raise RuntimeError("dirty fixture requires evidence root")
        evidence = external_capture(fixture, initial, evidence_root)
        preview = parse_json(adopt(binary, fixture, env, "preview", "--dirty-recovery-evidence", str(evidence)))
    else:
        preview = initial
    if not preview["admissible"]:
        raise RuntimeError(f"adoption refused unexpectedly: {preview.get('blockers') or preview.get('conflicts')}")
    args = ["--preview", preview["preview_sha256"], "--confirm", "HANDOFF"]
    if evidence is not None:
        args = ["--dirty-recovery-evidence", str(evidence), *args]
    handoff = parse_json(adopt(binary, fixture, env, "handoff", *args))
    if handoff["controller_execution"] is not False:
        raise RuntimeError("D8.4 handoff unexpectedly enabled controller execution")
    begun = parse_json(tx(binary, fixture, env, "begin", "--confirm", "BEGIN"))
    if begun["state"] != "ACTIVE":
        raise RuntimeError("transaction did not become ACTIVE")


def qualify_fresh(binary: Path, fixture: Path, env: dict[str, str]) -> dict:
    handoff_and_begin(binary, fixture, env)
    before = git_state(fixture)
    preview = parse_json(migrate(binary, fixture, env, "preview"))
    if preview["admissible"] or not any("migration is not required" in item for item in preview["blockers"]):
        raise RuntimeError("fresh migration path did not produce clear pre-change refusal")
    after = git_state(fixture)
    assert_state(before, after, "fresh pre-change migration refusal")
    parse_json(tx(binary, fixture, env, "stop", "--reason", "qualification", "--confirm", "STOP"))
    return {"fixture": "fresh", "migration": "REFUSED_NO_CHANGE", "reason": "legacy runtime absent"}


def qualify_migration_roundtrip(name: str, binary: Path, fixture: Path, env: dict[str, str], evidence_root: Path | None = None) -> dict:
    handoff_and_begin(binary, fixture, env, evidence_root)
    before = git_state(fixture)
    preview = parse_json(migrate(binary, fixture, env, "preview"))
    if not preview["admissible"]:
        raise RuntimeError(f"{name}: migration preview refused: {preview['blockers']}")
    applied = parse_json(migrate(binary, fixture, env, "apply", "--preview", preview["preview_sha256"], "--confirm", "MIGRATE"))
    if applied["state"] != "APPLIED" or (fixture / ".ralph").exists():
        raise RuntimeError(f"{name}: legacy runtime remained authoritative after migration")
    if git(fixture, "ls-files", "--", ".ralph").stdout.strip():
        raise RuntimeError(f"{name}: legacy tracked index entries remain after migration")
    if any(".ralph" in line and not line.lstrip().startswith("#") for line in (fixture / ".gitignore").read_text().splitlines()):
        raise RuntimeError(f"{name}: legacy ignore authority remains after migration")
    archive = fixture / applied["archive"]
    if not archive.is_file() or sha256(archive) != applied["archive_sha256"]:
        raise RuntimeError(f"{name}: retained legacy archive is unreadable or changed")
    parse_json(tx(binary, fixture, env, "stop", "--reason", "qualification", "--confirm", "STOP"))
    rollback_preview = parse_json(migrate(binary, fixture, env, "rollback-preview"))
    parse_json(migrate(binary, fixture, env, "rollback", "--preview", rollback_preview["preview_sha256"], "--confirm", "ROLLBACK"))
    after = git_state(fixture)
    assert_state(before, after, f"{name} migration rollback")
    if not (fixture / ".ralph" / "state.json").is_file():
        raise RuntimeError(f"{name}: legacy state was not restored by rollback")
    record = json.loads((fixture / ".stygnox" / "migration.json").read_text())
    if record.get("state") != "ROLLED_BACK":
        raise RuntimeError(f"{name}: rollback evidence not retained")
    return {
        "fixture": name,
        "migration": "PASS",
        "rollback": "PASS",
        "legacy_inventory_sha256": applied["legacy_inventory_sha256"],
        "archive_sha256": applied["archive_sha256"],
    }


def rewrite_runtime_version(path: Path, version: str) -> None:
    value = json.loads(path.read_text())
    value["product_version"] = version
    if "record_sha256" in value:
        value.pop("record_sha256", None)
        value["record_sha256"] = canonical_digest(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qualify_upgrade(binary: Path, fixture: Path, env: dict[str, str]) -> dict:
    handoff_and_begin(binary, fixture, env)
    active = parse_json(upgrade(binary, fixture, env, "preview"))
    if active["admissible"] or not any("ACTIVE transaction" in item for item in active["blockers"]):
        raise RuntimeError("upgrade did not refuse ACTIVE transaction")
    parse_json(tx(binary, fixture, env, "stop", "--reason", "qualification", "--confirm", "STOP"))
    # Simulate authentic D8.3 project-state versions without rewriting schemas/evidence.
    rewrite_runtime_version(fixture / ".stygnox" / "adoption.json", "0.1.0.dev3")
    rewrite_runtime_version(fixture / ".stygnox" / "transaction.json", "0.1.0.dev3")
    before = git_state(fixture)
    preview = parse_json(upgrade(binary, fixture, env, "preview"))
    if not preview["admissible"] or "0.1.0.dev3" not in preview["detected_runtime_versions"]:
        raise RuntimeError(f"D8.3 runtime compatibility was not accepted: {preview['blockers']}")
    accepted = parse_json(upgrade(binary, fixture, env, "accept", "--preview", preview["preview_sha256"], "--confirm", "UPGRADE"))
    if accepted["result"] != "UPGRADE_COMPATIBILITY_ACCEPTED":
        raise RuntimeError("upgrade compatibility acceptance failed")
    assert_state(before, git_state(fixture), "upgrade compatibility acceptance")
    return {"fixture": "upgrade-dev3-runtime", "from": "0.1.0.dev3", "to": EXPECTED_VERSION, "result": "PASS"}


def qualify_uninstall(binary: Path, fixture: Path, env: dict[str, str], evidence_root: Path) -> tuple[dict, dict[str, object]]:
    # Use an extracted legacy fixture so uninstall must retain migration archives as well.
    handoff_and_begin(binary, fixture, env)
    mig_preview = parse_json(migrate(binary, fixture, env, "preview"))
    if not mig_preview["admissible"]:
        raise RuntimeError(f"uninstall fixture migration refused: {mig_preview['blockers']}")
    parse_json(migrate(binary, fixture, env, "apply", "--preview", mig_preview["preview_sha256"], "--confirm", "MIGRATE"))
    parse_json(tx(binary, fixture, env, "stop", "--reason", "qualification", "--confirm", "STOP"))
    upgrade_preview = parse_json(upgrade(binary, fixture, env, "preview"))
    if not upgrade_preview["admissible"]:
        raise RuntimeError(f"uninstall fixture upgrade refused: {upgrade_preview['blockers']}")
    parse_json(upgrade(binary, fixture, env, "accept", "--preview", upgrade_preview["preview_sha256"], "--confirm", "UPGRADE"))

    before = git_state(fixture)
    preview = parse_json(uninstall(binary, fixture, env, "preview"))
    if not preview["admissible"]:
        raise RuntimeError(f"uninstall preview refused: {preview['blockers']}")
    prepared = parse_json(uninstall(binary, fixture, env, "prepare", "--preview", preview["preview_sha256"], "--confirm", "UNINSTALL"))
    preview2 = parse_json(uninstall(binary, fixture, env, "preview"))
    prepared2 = parse_json(uninstall(binary, fixture, env, "prepare", "--preview", preview2["preview_sha256"], "--confirm", "UNINSTALL"))
    if prepared["result"] != "UNINSTALL_PREPARED" or prepared2["result"] != "UNINSTALL_ALREADY_PREPARED":
        raise RuntimeError("uninstall preparation is not idempotent")
    assert_state(before, git_state(fixture), "uninstall prepare")
    migration_archives = list((fixture / ".stygnox" / "migrations").rglob("legacy-ralph.tar"))
    if not migration_archives:
        raise RuntimeError("uninstall did not retain migration evidence")
    for archive in migration_archives:
        with tarfile.open(archive, "r") as handle:
            if not handle.getmembers():
                raise RuntimeError("retained migration archive is unreadable")
    return {
        "fixture": "uninstall-after-migration",
        "prepare": "PASS",
        "idempotent": "PASS",
        "tracked_project_mutation": prepared["tracked_project_mutation"],
        "retained_evidence_deleted": prepared["retained_evidence_deleted"],
        "migration_archives": len(migration_archives),
    }, before


def build_wheel(python: Path, dist: Path) -> tuple[Path, str]:
    dist.mkdir(parents=True, exist_ok=True)
    result = run(
        [str(python), "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps", "--no-build-isolation", "--wheel-dir", str(dist), "."],
        cwd=ROOT,
    )
    wheels = sorted(dist.glob("stygnox-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one Stygnox wheel, found {wheels}")
    return wheels[0], result.stdout + result.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()
    work_context = tempfile.TemporaryDirectory(prefix="stygnox-d84-qualification-")
    work = Path(work_context.name)
    try:
        dist = work / "dist"
        wheel, build_transcript = build_wheel(Path(os.sys.executable), dist)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = venv_bin(environment, "python")
        pip = [str(python), "-m", "pip"]
        install = run([*pip, "install", "--disable-pip-version-check", "--no-deps", str(wheel)], cwd=work)
        stygnox_bin = venv_bin(environment, "stygnox")
        if not stygnox_bin.is_file():
            raise RuntimeError("installed stygnox executable is missing")
        version = run([str(stygnox_bin), "--version"], cwd=work).stdout.strip()
        if version != f"stygnox {EXPECTED_VERSION}":
            raise RuntimeError(f"unexpected installed version: {version}")

        hostile = work / "hostile"
        hostile.mkdir()
        sentinel = hostile / "RALPH_IMPORTED"
        (hostile / "ralph.py").write_text(
            "from pathlib import Path\n" + f"Path({str(sentinel)!r}).write_text('imported', encoding='utf-8')\n",
            encoding="utf-8",
        )
        env = installed_env(environment, hostile)
        support = parse_json(sx(stygnox_bin, work, env, "support"))
        if not support["supported"] or support["install_media"]["source_tree_dependency"]:
            raise RuntimeError(f"support policy is not satisfied: {support}")

        fresh = work / "fresh"
        init_repo(fresh, legacy=False)
        fresh_result = qualify_fresh(stygnox_bin, fresh, env)

        clean = work / "clean-legacy"
        init_repo(clean, legacy=True)
        clean_result = qualify_migration_roundtrip("clean", stygnox_bin, clean, env)

        dirty = work / "dirty-legacy"
        init_repo(dirty, legacy=True)
        make_dirty(dirty)
        dirty_result = qualify_migration_roundtrip("dirty", stygnox_bin, dirty, env, work / "operator-evidence")

        upgrade_fixture = work / "upgrade"
        init_repo(upgrade_fixture, legacy=False)
        upgrade_result = qualify_upgrade(stygnox_bin, upgrade_fixture, env)

        uninstall_fixture = work / "uninstall"
        init_repo(uninstall_fixture, legacy=True)
        uninstall_result, uninstall_before = qualify_uninstall(stygnox_bin, uninstall_fixture, env, work / "unused")

        if sentinel.exists():
            raise RuntimeError("legacy Ralph decoy was imported during D8.4 installed qualification")

        uninstall_transcript = run([*pip, "uninstall", "-y", "stygnox"], cwd=work)
        if stygnox_bin.exists():
            raise RuntimeError("pip uninstall left the stygnox console executable installed")
        assert_state(uninstall_before, git_state(uninstall_fixture), "actual pip uninstall")
        retained = uninstall_fixture / ".stygnox" / "uninstall.json"
        if not retained.is_file() or json.loads(retained.read_text()).get("activity_disabled") is not True:
            raise RuntimeError("uninstall retained-evidence record is missing/unreadable after package removal")

        result = {
            "schema": "stygnox_d8_4_lifecycle_qualification_v1",
            "version": EXPECTED_VERSION,
            "wheel": wheel.name,
            "wheel_sha256": sha256(wheel),
            "support_policy": "PASS",
            "fixtures": [fresh_result, clean_result, dirty_result, upgrade_result, uninstall_result],
            "legacy_ralph_decoy_isolation": "PASS",
            "actual_pip_uninstall": "PASS",
            "retained_evidence_readable_after_uninstall": "PASS",
            "controller_execution_enabled": False,
            "next_stage": "D8.5 neutral authority, profile, controller, and model-effort compatibility",
        }
        print("D8.4 MIGRATION / UPGRADE / UNINSTALL QUALIFICATION PASS")
        print(json.dumps(result, indent=2, sort_keys=True))
        print("\nBUILD TRANSCRIPT")
        print(build_transcript.rstrip())
        print("\nINSTALL TRANSCRIPT")
        print((install.stdout + install.stderr).rstrip())
        print("\nUNINSTALL TRANSCRIPT")
        print((uninstall_transcript.stdout + uninstall_transcript.stderr).rstrip())
        return 0
    finally:
        if args.keep_work:
            print(f"qualification work retained at {work}", file=os.sys.stderr)
            work_context.cleanup = lambda: None  # type: ignore[method-assign]
        work_context.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
