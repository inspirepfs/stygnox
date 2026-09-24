#!/usr/bin/env python3
"""Qualify D8.2 from one exact installed Stygnox wheel.

The qualifier builds one wheel, installs that exact artifact into a fresh
virtual environment, and exercises the installed bootstrap/admission surface
from new/unborn, clean, and fully dirty Git fixtures.  It proves read-only
preview, no-change abort, explicit handoff, stale-confirmation invalidation,
tracked policy/config review, ignored controller runtime, agent runtime-write
refusal, command resolution outside the project, and external dirty-recovery
evidence custody.

D8.3 recovery implementation is deliberately not claimed here.  The dirty
fixture uses an independently created external capture and restoration
rehearsal; D8.2 only verifies and binds the operator-owned attestation.
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
import sys
import tarfile
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = runpy.run_path(str(ROOT / "src" / "stygnox" / "_version.py"))["__version__"]


def run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_snapshot(root: Path) -> tuple[tuple[str, str, str, str], ...]:
    rows: list[tuple[str, str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        mode = f"{path.lstat().st_mode & 0o7777:04o}"
        if path.is_symlink():
            rows.append(("link", relative, mode, os.readlink(path)))
        elif path.is_dir():
            rows.append(("dir", relative, mode, ""))
        elif path.is_file():
            rows.append(("file", relative, mode, sha256(path)))
    return tuple(rows)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd, check=check)


def init_repo(path: Path, *, commit: bool, decoy: bool) -> Path | None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.2 Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")
    sentinel: Path | None = None
    if commit:
        (path / "README.fixture").write_text("fixture\n", encoding="utf-8")
        (path / "rename-me.txt").write_text("rename baseline\n", encoding="utf-8")
        (path / "delete-me.txt").write_text("delete baseline\n", encoding="utf-8")
        (path / "staged-mod.txt").write_text("staged baseline\n", encoding="utf-8")
        (path / "unstaged-mod.txt").write_text("unstaged baseline\n", encoding="utf-8")
        if decoy:
            scripts = path / "scripts"
            scripts.mkdir()
            sentinel = path / "RALPH_DECOY_EXECUTED"
            payload = (
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
                "raise RuntimeError('D8.2 target-local Ralph decoy executed')\n"
            )
            (scripts / "ralph.py").write_text(payload, encoding="utf-8")
            (scripts / "ralph_profile.py").write_text(payload, encoding="utf-8")
        git(path, "add", ".")
        git(path, "commit", "-q", "-m", "fixture baseline")
    return sentinel


def make_dirty(path: Path) -> None:
    (path / "staged-mod.txt").write_text("staged changed\n", encoding="utf-8")
    git(path, "add", "staged-mod.txt")
    (path / "unstaged-mod.txt").write_text("unstaged changed\n", encoding="utf-8")
    git(path, "mv", "rename-me.txt", "renamed.txt")
    (path / "delete-me.txt").unlink()
    (path / "untracked.txt").write_text("untracked baseline\n", encoding="utf-8")


def venv_bin(venv_root: Path, name: str) -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_root / bindir / f"{name}{suffix}"


def installed_env(venv_root: Path, hostile_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    bindir = str(venv_bin(venv_root, "python").parent)
    env["PATH"] = os.pathsep.join((bindir, env.get("PATH", "")))
    env["PYTHONPATH"] = str(hostile_path)
    return env


def parse_json(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"expected JSON output, got:\n{result.stdout}\nstderr:\n{result.stderr}") from exc


def adopt(stygnox: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(
        [str(stygnox), "adopt", action, "--project", str(fixture), "--operator", "D8.2 Operator", *args],
        cwd=fixture,
        env=env,
        check=check,
    )


def assert_no_bootstrap_mutation(fixture: Path) -> None:
    for name in ("stygnox.toml", "stygnox.policy.md", ".stygnox"):
        if (fixture / name).exists():
            raise RuntimeError(f"pre-handoff project mutation detected: {fixture / name}")


def assert_command_outside(preview: dict, fixture: Path, stygnox: Path) -> None:
    resolved = Path(preview["command"]["executable"]).resolve()
    if resolved != stygnox.resolve():
        raise RuntimeError(f"preview resolved unexpected executable: {resolved} != {stygnox.resolve()}")
    try:
        resolved.relative_to(fixture.resolve())
    except ValueError:
        return
    raise RuntimeError(f"installed executable resolved inside fixture: {resolved}")


def assert_boundary_after_handoff(fixture: Path, python: Path, env: dict[str, str]) -> None:
    if not (fixture / "stygnox.toml").is_file() or not (fixture / "stygnox.policy.md").is_file():
        raise RuntimeError("tracked policy/config were not materialized at handoff")
    runtime = fixture / ".stygnox"
    if not (runtime / "adoption.json").is_file():
        raise RuntimeError("controller adoption runtime record missing")
    if git(fixture, "check-ignore", "-q", "--no-index", ".stygnox/adoption.json", check=False).returncode != 0:
        raise RuntimeError("Stygnox runtime is not ignored")
    normal_status = git(fixture, "status", "--short", "--untracked-files=all").stdout
    if ".stygnox" in normal_status:
        raise RuntimeError("ignored runtime leaked into normal Git delta")
    ignored_status = git(fixture, "status", "--short", "--ignored", "--untracked-files=all").stdout
    if ".stygnox" not in ignored_status:
        raise RuntimeError("runtime did not appear as ignored evidence")
    code = (
        "from pathlib import Path\n"
        "from stygnox.adoption import write_runtime_record\n"
        f"root=Path({str(fixture)!r})\n"
        "try:\n"
        "    write_runtime_record(root, 'agent-probe.json', {'agent': True}, actor='agent')\n"
        "except PermissionError:\n"
        "    print('AGENT_RUNTIME_WRITE_REFUSED')\n"
        "else:\n"
        "    raise SystemExit('agent runtime write unexpectedly accepted')\n"
    )
    refused = run([str(python), "-c", code], cwd=fixture, env=env)
    if refused.stdout.strip() != "AGENT_RUNTIME_WRITE_REFUSED":
        raise RuntimeError("agent runtime-write refusal proof missing")
    if (runtime / "agent-probe.json").exists():
        raise RuntimeError("agent probe modified runtime")


def external_capture_and_attestation(fixture: Path, preview: dict, evidence_root: Path) -> tuple[Path, dict[str, str]]:
    evidence_root.mkdir(parents=True, exist_ok=True)
    capture = evidence_root / "dirty-baseline.tar.gz"
    with tarfile.open(capture, "w:gz") as archive:
        archive.add(fixture, arcname="repo", recursive=True)
    capture_sha = sha256(capture)

    rehearsal_root = evidence_root / "rehearsal"
    rehearsal_root.mkdir()
    with tarfile.open(capture, "r:gz") as archive:
        if sys.version_info >= (3, 12):
            # This archive was created by this qualification process immediately
            # above.  Preserve its exact captured permission bits so the recovery
            # rehearsal validates modes as well as content; the Python 3.12+
            # ``data`` filter deliberately normalises group/other write bits.
            archive.extractall(rehearsal_root, filter="fully_trusted")
        else:
            archive.extractall(rehearsal_root)  # self-generated qualification archive
    restored = rehearsal_root / "repo"
    if git(restored, "status", "--porcelain=v1", "--untracked-files=all").stdout != git(
        fixture, "status", "--porcelain=v1", "--untracked-files=all"
    ).stdout:
        raise RuntimeError("external dirty-capture rehearsal did not reproduce Git status")
    if tree_snapshot(restored) != tree_snapshot(fixture):
        raise RuntimeError("external dirty-capture rehearsal did not reproduce worktree content/modes")

    attestation = evidence_root / "attestation.json"
    body = {
        "schema": "stygnox_dirty_recovery_attestation_v1",
        "worktree": str(fixture.resolve()),
        "baseline_sha256": preview["baseline"]["sha256"],
        "capture_path": str(capture.resolve()),
        "capture_sha256": capture_sha,
        "verified": True,
        "restoration_rehearsed": True,
        "verified_by": "D8.2 external qualification operator",
        "categories": preview["baseline"]["dirty_categories"],
    }
    attestation.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return attestation, {"capture_sha256": capture_sha, "attestation_sha256": sha256(attestation)}


def qualify_new_or_clean(name: str, fixture: Path, stygnox: Path, python: Path, env: dict[str, str], sentinel: Path | None) -> dict:
    before_tree = tree_snapshot(fixture)
    before_status = git(fixture, "status", "--porcelain=v1", "--untracked-files=all").stdout
    preview = parse_json(adopt(stygnox, fixture, env, "preview"))
    assert_command_outside(preview, fixture, stygnox)
    if not preview["admissible"] or preview["baseline"]["journey"] != name:
        raise RuntimeError(f"{name}: unexpected preview admission: {preview}")
    if tree_snapshot(fixture) != before_tree or git(fixture, "status", "--porcelain=v1", "--untracked-files=all").stdout != before_status:
        raise RuntimeError(f"{name}: preview mutated project")
    assert_no_bootstrap_mutation(fixture)

    aborted = parse_json(adopt(stygnox, fixture, env, "abort", "--preview", preview["preview_sha256"]))
    if aborted["result"] != "ABORTED_NO_CHANGE" or tree_snapshot(fixture) != before_tree:
        raise RuntimeError(f"{name}: no-change abort failed")

    # A changed baseline or reserved tracked policy must invalidate confirmation.
    if name == "new-unborn":
        changed_path = fixture / "operator-change.tmp"
        changed_path.write_text("changed after preview\n", encoding="utf-8")
    else:
        changed_path = fixture / "stygnox.toml"
        changed_path.write_text("operator policy change\n", encoding="utf-8")
    stale = adopt(
        stygnox,
        fixture,
        env,
        "handoff",
        "--preview",
        preview["preview_sha256"],
        "--confirm",
        "HANDOFF",
        check=False,
    )
    if stale.returncode == 0 or "preview is stale" not in stale.stderr:
        raise RuntimeError(f"{name}: stale confirmation was not refused: {stale.stdout} {stale.stderr}")
    if name == "clean" and changed_path.read_text(encoding="utf-8") != "operator policy change\n":
        raise RuntimeError("clean: controller altered the operator-created stale policy file")
    changed_path.unlink()
    assert_no_bootstrap_mutation(fixture)

    fresh = parse_json(adopt(stygnox, fixture, env, "preview"))
    handoff = parse_json(
        adopt(
            stygnox,
            fixture,
            env,
            "handoff",
            "--preview",
            fresh["preview_sha256"],
            "--confirm",
            "HANDOFF",
        )
    )
    if handoff["result"] != "HANDOFF_RECORDED" or handoff["controller_execution"] is not False:
        raise RuntimeError(f"{name}: unexpected handoff result")
    assert_boundary_after_handoff(fixture, python, env)
    if sentinel is not None and sentinel.exists():
        raise RuntimeError(f"{name}: target-local Ralph decoy executed")
    return {
        "fixture": name,
        "preview_sha256": fresh["preview_sha256"],
        "baseline_sha256": fresh["baseline"]["sha256"],
        "executable": fresh["command"]["executable"],
        "abort": "PASS",
        "stale_confirmation_refusal": "PASS",
        "handoff": "PASS",
        "tracked_runtime_boundary": "PASS",
        "agent_runtime_write_refusal": "PASS",
    }


def qualify_dirty(fixture: Path, stygnox: Path, python: Path, env: dict[str, str], sentinel: Path, evidence_root: Path) -> dict:
    before_tree = tree_snapshot(fixture)
    before_status = git(fixture, "status", "--porcelain=v1", "--untracked-files=all").stdout
    preview = parse_json(adopt(stygnox, fixture, env, "preview"))
    assert_command_outside(preview, fixture, stygnox)
    if preview["baseline"]["journey"] != "dirty" or preview["admissible"]:
        raise RuntimeError("dirty: handoff should require external recovery evidence")
    aborted = parse_json(adopt(stygnox, fixture, env, "abort", "--preview", preview["preview_sha256"]))
    if aborted["result"] != "ABORTED_NO_CHANGE":
        raise RuntimeError("dirty: no-change abort failed")
    if tree_snapshot(fixture) != before_tree or git(fixture, "status", "--porcelain=v1", "--untracked-files=all").stdout != before_status:
        raise RuntimeError("dirty: preview/abort mutated project")

    attestation, evidence = external_capture_and_attestation(fixture, preview, evidence_root)
    with_evidence = parse_json(
        adopt(stygnox, fixture, env, "preview", "--dirty-recovery-evidence", str(attestation))
    )
    if not with_evidence["admissible"]:
        raise RuntimeError(f"dirty: valid external recovery evidence was refused: {with_evidence}")

    untracked = fixture / "untracked.txt"
    original = untracked.read_text(encoding="utf-8")
    untracked.write_text(original + "changed after preview\n", encoding="utf-8")
    stale = adopt(
        stygnox,
        fixture,
        env,
        "handoff",
        "--dirty-recovery-evidence",
        str(attestation),
        "--preview",
        with_evidence["preview_sha256"],
        "--confirm",
        "HANDOFF",
        check=False,
    )
    if stale.returncode == 0 or "preview is stale" not in stale.stderr:
        raise RuntimeError("dirty: changed baseline did not invalidate confirmation")
    assert_no_bootstrap_mutation(fixture)
    untracked.write_text(original, encoding="utf-8")

    fresh = parse_json(
        adopt(stygnox, fixture, env, "preview", "--dirty-recovery-evidence", str(attestation))
    )
    handoff = parse_json(
        adopt(
            stygnox,
            fixture,
            env,
            "handoff",
            "--dirty-recovery-evidence",
            str(attestation),
            "--preview",
            fresh["preview_sha256"],
            "--confirm",
            "HANDOFF",
        )
    )
    if handoff["result"] != "HANDOFF_RECORDED":
        raise RuntimeError("dirty: handoff failed")
    assert_boundary_after_handoff(fixture, python, env)
    if sentinel.exists():
        raise RuntimeError("dirty: target-local Ralph decoy executed")
    return {
        "fixture": "dirty",
        "preview_sha256": fresh["preview_sha256"],
        "baseline_sha256": fresh["baseline"]["sha256"],
        "dirty_categories": fresh["baseline"]["dirty_categories"],
        "executable": fresh["command"]["executable"],
        "external_recovery_capture": evidence,
        "abort": "PASS",
        "stale_confirmation_refusal": "PASS",
        "handoff": "PASS",
        "tracked_runtime_boundary": "PASS",
        "agent_runtime_write_refusal": "PASS",
    }



def qualify_local_command_decoy(fixture: Path, stygnox: Path, env: dict[str, str]) -> dict[str, str]:
    local = fixture / "stygnox"
    local.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    local.chmod(0o755)
    git(fixture, "add", "stygnox")
    git(fixture, "commit", "-q", "-m", "local command decoy")
    hostile_env = env.copy()
    hostile_env["PATH"] = os.pathsep.join((str(fixture), hostile_env.get("PATH", "")))
    before = tree_snapshot(fixture)
    refused = adopt(stygnox, fixture, hostile_env, "preview", check=False)
    if refused.returncode == 0 or "inside adopting worktree" not in refused.stderr:
        raise RuntimeError(f"local stygnox command decoy was not refused: {refused.stdout} {refused.stderr}")
    if tree_snapshot(fixture) != before:
        raise RuntimeError("local command-decoy refusal mutated fixture")
    return {"fixture": "local-command-decoy", "result": "PASS", "diagnostic": "installed command resolution inside worktree refused"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="retain the exact qualified wheel and qualification.json outside the source tree",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for variable in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
        if variable in os.environ:
            raise SystemExit(f"refusing qualification with ambient {variable} set")

    with tempfile.TemporaryDirectory(prefix="stygnox-d82-qualification-") as temp:
        work = Path(temp)
        if args.output_dir is None:
            dist = work / "dist"
            dist.mkdir()
            evidence_path = None
        else:
            dist = args.output_dir.expanduser().resolve()
            dist.mkdir(parents=True, exist_ok=True)
            if any(dist.iterdir()):
                raise SystemExit(f"refusing non-empty --output-dir: {dist}")
            evidence_path = dist / "qualification.json"

        build = run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(dist),
                ".",
            ],
            cwd=ROOT,
        )
        wheels = sorted(dist.glob("stygnox-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected exactly one Stygnox wheel, found: {wheels}")
        wheel = wheels[0]
        wheel_digest = sha256(wheel)

        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = venv_bin(environment, "python")
        install = run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(wheel)],
            cwd=work,
        )
        stygnox = venv_bin(environment, "stygnox")
        if not stygnox.is_file():
            raise RuntimeError(f"installed stygnox executable missing: {stygnox}")

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
        assert clean_sentinel is not None and dirty_sentinel is not None
        make_dirty(dirty)

        results = [
            qualify_new_or_clean("new-unborn", new, stygnox, python, env, None),
            qualify_new_or_clean("clean", clean, stygnox, python, env, clean_sentinel),
            qualify_dirty(dirty, stygnox, python, env, dirty_sentinel, work / "operator-evidence"),
        ]
        command_decoy = fixtures / "command-decoy"
        init_repo(command_decoy, commit=True, decoy=False)
        command_resolution_negative = qualify_local_command_decoy(command_decoy, stygnox, env)
        if external_sentinel.exists():
            raise RuntimeError("hostile external Ralph PYTHONPATH decoy executed")

        installed = run([str(python), "-c", "import stygnox; print(stygnox.__version__)"], cwd=work, env=env)
        if installed.stdout.strip() != EXPECTED_VERSION:
            raise RuntimeError(f"installed package version mismatch: {installed.stdout!r}")

        evidence = {
            "schema": "stygnox_d8_2_bootstrap_qualification_v1",
            "version": EXPECTED_VERSION,
            "wheel": wheel.name,
            "wheel_sha256": wheel_digest,
            "fixtures": results,
            "legacy_ralph_decoy_isolation": "PASS",
            "local_command_decoy_refusal": command_resolution_negative,
            "controller_execution_enabled": False,
            "next_stage": "D8.3 clean/dirty transaction and recovery semantics",
        }
        rendered = json.dumps(evidence, indent=2, sort_keys=True)
        if evidence_path is not None:
            evidence_path.write_text(rendered + "\n", encoding="utf-8")
        print("D8.2 BOOTSTRAP / TRACKED-POLICY-RUNTIME QUALIFICATION PASS")
        print(rendered)
        if evidence_path is not None:
            print(f"retained evidence: {evidence_path}")
        if build.stdout.strip():
            print("\nBUILD TRANSCRIPT\n" + build.stdout.strip())
        if install.stdout.strip():
            print("\nINSTALL TRANSCRIPT\n" + install.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
