#!/usr/bin/env python3
"""Qualify the exact D8.1 wheel from an isolated installed environment.

The script is intentionally source-side qualification tooling.  It builds one
wheel, records its digest, installs that exact wheel into a fresh venv, and
runs help/version from new, clean, and dirty Git fixtures containing hostile
legacy-Ralph decoys.  The installed command must resolve outside every fixture
and must not execute a decoy or mutate fixture content/runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import runpy


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = runpy.run_path(str(ROOT / "src" / "stygnox" / "_version.py"))["__version__"]


def run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        if path.is_symlink():
            rows.append(("link", relative, os.readlink(path)))
        elif path.is_dir():
            rows.append(("dir", relative, ""))
        elif path.is_file():
            rows.append(("file", relative, sha256(path)))
    return tuple(rows)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd)


def init_repo(path: Path, *, commit: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.1 Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")
    (path / "README.fixture").write_text("fixture\n", encoding="utf-8")
    git(path, "add", "README.fixture")
    if commit:
        git(path, "commit", "-q", "-m", "fixture baseline")


def add_decoys(path: Path) -> Path:
    scripts = path / "scripts"
    scripts.mkdir(exist_ok=True)
    sentinel = path / "RALPH_DECOY_EXECUTED"
    payload = (
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
        "raise RuntimeError('D8.1 decoy Ralph module executed')\n"
    )
    (scripts / "ralph.py").write_text(payload, encoding="utf-8")
    (scripts / "ralph_profile.py").write_text(payload, encoding="utf-8")
    return sentinel


def dirty_repo(path: Path) -> None:
    (path / "README.fixture").write_text("fixture\nunstaged\n", encoding="utf-8")
    (path / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(path, "add", "staged.txt")
    (path / "untracked.txt").write_text("untracked\n", encoding="utf-8")


def venv_bin(venv_root: Path, name: str) -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_root / bindir / f"{name}{suffix}"


def qualify_fixture(name: str, fixture: Path, stygnox: Path, source_scripts: Path) -> dict[str, str]:
    sentinel = add_decoys(fixture)
    before = tree_snapshot(fixture)
    resolved = stygnox.resolve()
    try:
        resolved.relative_to(fixture.resolve())
    except ValueError:
        pass
    else:
        raise RuntimeError(f"{name}: installed executable resolved inside fixture: {resolved}")

    env = os.environ.copy()
    # Hostile source/decoy path: an installed command must not use these Ralph modules.
    env["PYTHONPATH"] = os.pathsep.join((str(fixture / "scripts"), str(source_scripts)))

    version = run([str(stygnox), "--version"], cwd=fixture, env=env)
    help_result = run([str(stygnox), "--help"], cwd=fixture, env=env)
    if version.stdout.strip() != f"stygnox {EXPECTED_VERSION}":
        raise RuntimeError(f"{name}: unexpected version output: {version.stdout!r}")
    if "Stygnox installed product" not in help_result.stdout:
        raise RuntimeError(f"{name}: installed help did not expose neutral Stygnox identity")
    combined = (version.stdout + version.stderr + help_result.stdout + help_result.stderr).upper()
    if "RALPH-LITE" in combined or "ZEN CONTROL" in combined:
        raise RuntimeError(f"{name}: legacy product identity leaked into installed help/version")
    if sentinel.exists():
        raise RuntimeError(f"{name}: legacy Ralph decoy was executed")
    if tree_snapshot(fixture) != before:
        raise RuntimeError(f"{name}: help/version mutated fixture content")
    return {
        "fixture": name,
        "executable": str(resolved),
        "version": version.stdout.strip(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "retain the exact qualified wheel and qualification.json outside the "
            "source tree; the directory must not already contain files"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for variable in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
        if variable in os.environ:
            raise SystemExit(f"refusing qualification with ambient {variable} set")

    with tempfile.TemporaryDirectory(prefix="stygnox-d81-qualification-") as temp:
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
        pip = [str(python), "-m", "pip"]
        install = run(
            [*pip, "install", "--disable-pip-version-check", "--no-deps", str(wheel)],
            cwd=work,
        )
        stygnox = venv_bin(environment, "stygnox")
        if not stygnox.is_file():
            raise RuntimeError(f"installed stygnox executable missing: {stygnox}")

        fixtures = work / "fixtures"
        new = fixtures / "new-unborn"
        clean = fixtures / "clean"
        dirty = fixtures / "dirty"
        init_repo(new, commit=False)
        init_repo(clean, commit=True)
        init_repo(dirty, commit=True)
        dirty_repo(dirty)

        source_scripts = ROOT / "scripts"
        results = [
            qualify_fixture("new-unborn", new, stygnox, source_scripts),
            qualify_fixture("clean", clean, stygnox, source_scripts),
            qualify_fixture("dirty", dirty, stygnox, source_scripts),
        ]

        installed = run([str(python), "-c", "import stygnox; print(stygnox.__version__)"], cwd=work)
        if installed.stdout.strip() != EXPECTED_VERSION:
            raise RuntimeError(f"installed package version mismatch: {installed.stdout!r}")

        evidence = {
            "schema": "stygnox_d8_1_installed_qualification_v1",
            "wheel": wheel.name,
            "wheel_sha256": wheel_digest,
            "version": EXPECTED_VERSION,
            "fixtures": results,
        }
        rendered_evidence = json.dumps(evidence, indent=2, sort_keys=True)
        if evidence_path is not None:
            evidence_path.write_text(rendered_evidence + "\n", encoding="utf-8")
        print("D8.1 INSTALLED ARTIFACT QUALIFICATION PASS")
        print(rendered_evidence)
        if evidence_path is not None:
            print(f"retained evidence: {evidence_path}")
        if build.stdout.strip():
            print("\nBUILD TRANSCRIPT\n" + build.stdout.strip())
        if install.stdout.strip():
            print("\nINSTALL TRANSCRIPT\n" + install.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
