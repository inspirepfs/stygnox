#!/usr/bin/env python3
"""Qualify D8.3 transaction/safe-stop/recovery using one installed wheel.

This qualifier independently creates dirty recovery material outside the
adopted worktree.  Stygnox only verifies and consumes that operator-owned
capture; it never creates or becomes sole custodian of it.
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
from stygnox_qualification_artifact import provided_build_result, provided_wheel

EXPECTED_VERSION = runpy.run_path(str(ROOT / "src" / "stygnox" / "_version.py"))["__version__"]
OPERATOR_MANIFEST_SCHEMA = "stygnox_operator_recovery_manifest_v1"
ATTESTATION_SCHEMA = "stygnox_dirty_recovery_attestation_v1"


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
    index = root / ".git" / "index"
    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else "(detached)",
        "status": git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout,
        "index_file_sha256": sha256(index) if index.is_file() else None,
        "index_identity_sha256": sha256_bytes(subprocess.run(["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True, check=True).stdout),
        "staged_sha256": sha256_bytes(subprocess.run(["git", "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"], cwd=root, capture_output=True, check=True).stdout),
        "unstaged_sha256": sha256_bytes(subprocess.run(["git", "diff", "--binary", "--no-ext-diff", "--no-textconv"], cwd=root, capture_output=True, check=True).stdout),
        "tree": tree_snapshot(root),
    }


def assert_state_equal(before: dict[str, object], after: dict[str, object], label: str) -> None:
    for key in ("head", "branch", "status", "index_identity_sha256", "staged_sha256", "unstaged_sha256", "tree"):
        if before[key] != after[key]:
            raise RuntimeError(f"{label}: restored {key} differs from pre-authority baseline")


def init_repo(path: Path, *, commit: bool, decoy: bool) -> Path | None:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.3 Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")
    sentinel: Path | None = None
    if commit:
        for name, content in {
            "README.fixture": "fixture\n",
            "rename-me.txt": "rename baseline\n",
            "delete-me.txt": "delete baseline\n",
            "staged-mod.txt": "staged baseline\n",
            "unstaged-mod.txt": "unstaged baseline\n",
        }.items():
            (path / name).write_text(content, encoding="utf-8")
        if decoy:
            scripts = path / "scripts"
            scripts.mkdir()
            sentinel = path / "RALPH_DECOY_EXECUTED"
            payload = (
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
                "raise RuntimeError('target-local Ralph decoy executed')\n"
            )
            (scripts / "ralph.py").write_text(payload, encoding="utf-8")
            (scripts / "ralph_profile.py").write_text(payload, encoding="utf-8")
        git(path, "add", ".")
        git(path, "commit", "-q", "-m", "fixture baseline")
    else:
        (path / "initial.txt").write_text("initial unborn content\n", encoding="utf-8")
        (path / "initial-empty").mkdir()
    return sentinel


def make_dirty(path: Path) -> None:
    (path / "staged-mod.txt").write_text("staged changed\n", encoding="utf-8")
    git(path, "add", "staged-mod.txt")
    (path / "unstaged-mod.txt").write_text("unstaged changed\n", encoding="utf-8")
    git(path, "mv", "rename-me.txt", "renamed.txt")
    (path / "delete-me.txt").unlink()
    (path / "untracked.txt").write_text("untracked baseline\n", encoding="utf-8")
    (path / "untracked.txt").chmod(0o664)
    (path / "empty-untracked-dir").mkdir()


def venv_bin(root: Path, name: str) -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return root / bindir / f"{name}{suffix}"


def installed_env(environment: Path, hostile: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(venv_bin(environment, "python").parent), env.get("PATH", "")))
    env["PYTHONPATH"] = str(hostile)
    return env


def parse_json(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"expected JSON output:\n{result.stdout}\nstderr:\n{result.stderr}") from exc


def stygnox(stygnox_bin: Path, fixture: Path, env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([str(stygnox_bin), *args], cwd=fixture, env=env, check=check)


def adopt(stygnox_bin: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return stygnox(stygnox_bin, fixture, env, "adopt", action, "--project", str(fixture), "--operator", "D8.3 Operator", *args, check=check)


def tx(stygnox_bin: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    base = ["transaction", action, "--project", str(fixture)]
    if action != "status":
        base += ["--operator", "D8.3 Operator"]
    return stygnox(stygnox_bin, fixture, env, *base, *args, check=check)


def independent_manifest_entries(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for kind, relative, mode, value in tree_snapshot(root):
        if kind == "file":
            rows.append({"path": relative, "type": "file", "mode": mode, "sha256": value})
        elif kind == "dir":
            rows.append({"path": relative, "type": "dir", "mode": mode, "sha256": ""})
        else:
            rows.append({"path": relative, "type": "symlink", "mode": mode, "sha256": sha256_bytes(value.encode()), "target": value})
    return sorted(rows, key=lambda item: item["path"])


def manifest_digest(entries: list[dict[str, str]]) -> str:
    return sha256_bytes(json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def external_capture(fixture: Path, preview: dict, evidence_root: Path) -> Path:
    evidence_root.mkdir(parents=True)
    capture = evidence_root / "dirty-baseline.tar.gz"
    with tarfile.open(capture, "w:gz") as archive:
        archive.add(fixture, arcname="repo", recursive=True)
    entries = independent_manifest_entries(fixture)
    index = fixture / ".git" / "index"
    manifest = {
        "schema": OPERATOR_MANIFEST_SCHEMA,
        "baseline_sha256": preview["baseline"]["sha256"],
        "head": preview["baseline"]["head"],
        "branch": preview["baseline"]["branch"],
        "status": preview["baseline"]["status"],
        "index_file_sha256": sha256(index) if index.is_file() else None,
        "worktree_manifest": entries,
        "worktree_manifest_sha256": manifest_digest(entries),
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
        "verified_by": "Independent D8.3 qualification operator",
        "categories": preview["baseline"]["dirty_categories"],
    }
    attestation_path = evidence_root / "attestation.json"
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return attestation_path


def assert_runtime_retained_and_ignored(fixture: Path) -> None:
    result = git(fixture, "check-ignore", "-q", "--no-index", ".stygnox/recovery-result.json", check=False)
    if result.returncode != 0:
        raise RuntimeError("retained Stygnox runtime is not ignored after baseline restoration")
    if not (fixture / ".stygnox/recovery-result.json").is_file():
        raise RuntimeError("recovery result evidence was not retained")


def qualify_journey(name: str, fixture: Path, stygnox_bin: Path, env: dict[str, str], evidence_root: Path | None = None) -> dict:
    before = git_state(fixture)
    initial = parse_json(adopt(stygnox_bin, fixture, env, "preview"))
    evidence: Path | None = None
    if name == "dirty":
        if initial["admissible"]:
            raise RuntimeError("dirty journey admitted without external recovery evidence")
        assert evidence_root is not None
        evidence = external_capture(fixture, initial, evidence_root)
        preview = parse_json(adopt(stygnox_bin, fixture, env, "preview", "--dirty-recovery-evidence", str(evidence)))
    else:
        preview = initial
    if not preview["admissible"]:
        raise RuntimeError(f"{name}: admissible preview expected")

    # Pre-handoff interruption is a no-op: re-preview must bind the same baseline.
    if name == "dirty":
        resumed = parse_json(adopt(stygnox_bin, fixture, env, "preview", "--dirty-recovery-evidence", str(evidence)))
    else:
        resumed = parse_json(adopt(stygnox_bin, fixture, env, "preview"))
    if resumed["preview_sha256"] != preview["preview_sha256"]:
        raise RuntimeError(f"{name}: no-change pre-handoff interruption changed preview binding")

    handoff_args = ["--preview", resumed["preview_sha256"], "--confirm", "HANDOFF"]
    if evidence is not None:
        handoff_args = ["--dirty-recovery-evidence", str(evidence), *handoff_args]
    handoff = parse_json(adopt(stygnox_bin, fixture, env, "handoff", *handoff_args))
    if handoff["controller_execution"] is not False:
        raise RuntimeError(f"{name}: D8.3 unexpectedly enabled autonomous controller execution")

    # Dirty transaction begin must fail if the independent manifest changes.
    dirty_manifest_refusal = None
    dirty_attestation_refusal = None
    if evidence is not None:
        original_attestation = evidence.read_bytes()
        attestation = json.loads(original_attestation)
        changed = dict(attestation)
        changed["verified_by"] = "Changed after handoff"
        evidence.write_text(json.dumps(changed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        refused = tx(stygnox_bin, fixture, env, "begin", "--confirm", "BEGIN", check=False)
        if refused.returncode == 0 or "attestation changed" not in refused.stderr:
            raise RuntimeError("dirty: changed attestation did not invalidate transaction authority")
        evidence.write_bytes(original_attestation)
        dirty_attestation_refusal = "PASS"

        manifest_path = Path(attestation["manifest_path"])
        original = manifest_path.read_bytes()
        manifest_path.write_text("{}\n", encoding="utf-8")
        refused = tx(stygnox_bin, fixture, env, "begin", "--confirm", "BEGIN", check=False)
        if refused.returncode == 0 or "manifest digest" not in refused.stderr:
            raise RuntimeError("dirty: tampered external recovery manifest did not block transaction begin")
        manifest_path.write_bytes(original)
        dirty_manifest_refusal = "PASS"

    transaction = parse_json(tx(stygnox_bin, fixture, env, "begin", "--confirm", "BEGIN"))
    if transaction["result"] != "TRANSACTION_ACTIVE" or transaction["authority"]["controller_execution"] is not False:
        raise RuntimeError(f"{name}: transaction authority result invalid")

    # Simulate post-handoff work without using a controller execution path that D8.3 intentionally keeps disabled.
    if name == "new-unborn":
        (fixture / "initial.txt").write_text("post handoff overwrite\n", encoding="utf-8")
        shutil.rmtree(fixture / "initial-empty")
    else:
        target = fixture / ("staged-mod.txt" if name == "dirty" else "README.fixture")
        target.write_text("post handoff overlap\n", encoding="utf-8")
        git(fixture, "add", target.name)
    (fixture / "post-handoff-new.txt").write_text("post handoff\n", encoding="utf-8")

    stopped = parse_json(tx(stygnox_bin, fixture, env, "stop", "--reason", "interrupted", "--confirm", "STOP"))
    if stopped["result"] != "SAFE_STOP_RECORDED" or not stopped["safe_stop"]["authority_revoked"]:
        raise RuntimeError(f"{name}: safe stop evidence missing")

    recovery_preview = parse_json(tx(stygnox_bin, fixture, env, "recover-preview", "--post-handoff-disposition", "discard"))
    stale_probe = fixture / "stale-after-recovery-preview.txt"
    stale_probe.write_text("operator changed after recovery preview\n", encoding="utf-8")
    stale = tx(
        stygnox_bin,
        fixture,
        env,
        "restore",
        "--preview",
        recovery_preview["preview_sha256"],
        "--confirm",
        "RESTORE",
        "--post-handoff-disposition",
        "discard",
        check=False,
    )
    if stale.returncode == 0 or "stale" not in stale.stderr:
        raise RuntimeError(f"{name}: stale recovery preview did not fail closed")
    stale_probe.unlink()

    recovery_preview = parse_json(tx(stygnox_bin, fixture, env, "recover-preview", "--post-handoff-disposition", "discard"))
    restored = parse_json(
        tx(
            stygnox_bin,
            fixture,
            env,
            "restore",
            "--preview",
            recovery_preview["preview_sha256"],
            "--confirm",
            "RESTORE",
            "--post-handoff-disposition",
            "discard",
        )
    )
    if restored["result"] != "BASELINE_RESTORED" or not restored["verified"]:
        raise RuntimeError(f"{name}: restoration result invalid")
    assert_state_equal(before, git_state(fixture), name)
    assert_runtime_retained_and_ignored(fixture)
    return {
        "fixture": name,
        "pre_handoff_interruption_revalidation": "PASS",
        "handoff": "PASS",
        "transaction_begin": "PASS",
        "safe_stop": "PASS",
        "stale_recovery_preview_refusal": "PASS",
        "operator_approved_restore": "PASS",
        "exact_baseline_comparison": "PASS",
        "runtime_evidence_retained_ignored": "PASS",
        "dirty_attestation_change_refusal": dirty_attestation_refusal,
        "dirty_manifest_tamper_refusal": dirty_manifest_refusal,
        "controller_execution_enabled": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="retain exact wheel and qualification.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="stygnox-d83-qualification-") as temp:
        work = Path(temp)
        dist = work / "dist" if args.output_dir is None else args.output_dir.expanduser().resolve()
        dist.mkdir(parents=True, exist_ok=True)
        if args.output_dir is not None and any(dist.iterdir()):
            raise SystemExit(f"refusing non-empty --output-dir: {dist}")
        wheel = provided_wheel()
        if wheel is None:
            build = run(
                [sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps", "--no-build-isolation", "--wheel-dir", str(dist), "."],
                cwd=ROOT,
            )
            wheels = sorted(dist.glob("stygnox-*.whl"))
            if len(wheels) != 1:
                raise RuntimeError(f"expected one wheel, found {wheels}")
            wheel = wheels[0]
        else:
            build = provided_build_result(wheel)
        wheel_sha = sha256(wheel)

        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = venv_bin(environment, "python")
        install = run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(wheel)], cwd=work)
        stygnox_bin = venv_bin(environment, "stygnox")
        if not stygnox_bin.is_file():
            raise RuntimeError("installed stygnox executable missing")

        hostile = work / "hostile-pythonpath"
        hostile.mkdir()
        external_sentinel = work / "EXTERNAL_RALPH_DECOY_EXECUTED"
        payload = (
            "from pathlib import Path\n"
            f"Path({str(external_sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            "raise RuntimeError('external Ralph decoy executed')\n"
        )
        (hostile / "ralph.py").write_text(payload, encoding="utf-8")
        (hostile / "ralph_profile.py").write_text(payload, encoding="utf-8")
        env = installed_env(environment, hostile)

        fixtures = work / "fixtures"
        new = fixtures / "new-unborn"
        clean = fixtures / "clean"
        dirty = fixtures / "dirty"
        init_repo(new, commit=False, decoy=False)
        clean_sentinel = init_repo(clean, commit=True, decoy=True)
        dirty_sentinel = init_repo(dirty, commit=True, decoy=True)
        make_dirty(dirty)

        results = [
            qualify_journey("new-unborn", new, stygnox_bin, env),
            qualify_journey("clean", clean, stygnox_bin, env),
            qualify_journey("dirty", dirty, stygnox_bin, env, work / "operator-evidence"),
        ]
        if external_sentinel.exists() or (clean_sentinel and clean_sentinel.exists()) or (dirty_sentinel and dirty_sentinel.exists()):
            raise RuntimeError("Ralph decoy executed during D8.3 installed qualification")

        installed = run([str(python), "-c", "import stygnox; print(stygnox.__version__)"], cwd=work, env=env)
        if installed.stdout.strip() != EXPECTED_VERSION:
            raise RuntimeError("installed version mismatch")

        evidence = {
            "schema": "stygnox_d8_3_transaction_recovery_qualification_v1",
            "version": EXPECTED_VERSION,
            "wheel": wheel.name,
            "wheel_sha256": wheel_sha,
            "fixtures": results,
            "legacy_ralph_decoy_isolation": "PASS",
            "controller_execution_enabled": False,
            "next_stage": "D8.4 migration, extraction, upgrade, and uninstall",
        }
        rendered = json.dumps(evidence, indent=2, sort_keys=True)
        if args.output_dir is not None:
            (dist / "qualification.json").write_text(rendered + "\n", encoding="utf-8")
        print("D8.3 CLEAN/DIRTY TRANSACTION AND RECOVERY QUALIFICATION PASS")
        print(rendered)
        if build.stdout.strip():
            print("\nBUILD TRANSCRIPT\n" + build.stdout.strip())
        if install.stdout.strip():
            print("\nINSTALL TRANSCRIPT\n" + install.stdout.strip())
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
