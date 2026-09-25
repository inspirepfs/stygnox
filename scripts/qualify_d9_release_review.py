#!/usr/bin/env python3
"""Independent D9 qualification for the Stygnox 0.1.0 release artifact."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / "src/stygnox/_version.py"))["__version__"]
SCHEMA = "stygnox_d9_final_release_qualification_v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(argv: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def release_digests(directory: Path) -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(directory.iterdir(), key=lambda p: p.name)
        if path.is_file()
    }


def main() -> int:
    if VERSION != "0.1.0":
        raise RuntimeError(f"D9 final release qualification expects 0.1.0, got {VERSION}")

    with tempfile.TemporaryDirectory(prefix="stygnox-d9-review-") as td:
        root = Path(td)
        first = root / "release-a"
        second = root / "release-b"
        run([sys.executable, str(ROOT / "scripts/build_d8_7_release.py"), "--output-dir", str(first)])
        run([sys.executable, str(ROOT / "scripts/build_d8_7_release.py"), "--output-dir", str(second)])
        if release_digests(first) != release_digests(second):
            raise RuntimeError("canonical release set is not byte reproducible on the review host")

        manifest = json.loads((first / "release-manifest.json").read_text(encoding="utf-8"))
        build = manifest.get("wheel_build") or {}
        if build.get("method") != "canonical-stdlib-wheel":
            raise RuntimeError(f"unexpected wheel build method: {build!r}")
        if build.get("host_setuptools_dependency") is not False or build.get("host_wheel_dependency") is not False:
            raise RuntimeError("canonical release still declares a host setuptools/wheel dependency")

        wheel = first / f"stygnox-{VERSION}-py3-none-any.whl"
        if not wheel.is_file():
            raise RuntimeError("canonical release wheel is missing")
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            wheel_member = next((n for n in names if n.endswith(".dist-info/WHEEL")), None)
            if not wheel_member or "Generator: stygnox-release-builder/1" not in archive.read(wheel_member).decode("utf-8"):
                raise RuntimeError("canonical wheel generator marker is missing")
            if any(n.startswith(("scripts/", "tests/", "branding/", "provenance/")) for n in names):
                raise RuntimeError("repository-only material leaked into installed wheel")

        # Install the exact local wheel into an isolated venv and exercise it
        # from an unrelated repository with the source checkout absent from PATH.
        venv = root / "venv"
        run([sys.executable, "-m", "venv", str(venv)])
        python = venv / "bin/python"
        stygnox = venv / "bin/stygnox"
        run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)])
        unrelated = root / "unrelated"
        unrelated.mkdir()
        run(["git", "init", "-q"], cwd=unrelated)
        env = os.environ.copy()
        env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
        env.pop("PYTHONPATH", None)
        version_out = run([str(stygnox), "--version"], cwd=unrelated, env=env).stdout.strip()
        help_out = run([str(stygnox), "--help"], cwd=unrelated, env=env).stdout
        web_help = run([str(stygnox), "web", "--help"], cwd=unrelated, env=env).stdout
        tui_help = run([str(stygnox), "tui", "--help"], cwd=unrelated, env=env).stdout
        combined = "\n".join([help_out, web_help, tui_help])
        if version_out != f"stygnox {VERSION}":
            raise RuntimeError(f"installed candidate reports unexpected version: {version_out!r}")
        if "D8.6" in combined or "D8.7 release packaging" in combined:
            raise RuntimeError("installed operator help leaks stale D8 stage wording")

        source = first / f"stygnox-{VERSION}-source.tar.gz"
        report = {
            "schema": SCHEMA,
            "version": VERSION,
            "release_decision": "QUALIFIED_FOR_TAGGING",
            "cross_host_requirement": "PENDING_INDEPENDENT_HOST_DIGEST_MATCH",
            "wheel": wheel.name,
            "wheel_sha256": sha256(wheel),
            "source_archive": source.name,
            "source_archive_sha256": sha256(source),
            "same_host_reproducibility": "PASS",
            "canonical_wheel_generator": "PASS",
            "host_setuptools_dependency": False,
            "host_wheel_dependency": False,
            "independent_install": "PASS",
            "unrelated_repository": "PASS",
            "operator_stage_hygiene": "PASS",
            "next_action": "reproduce this 0.1.0 wheel digest on an independent supported host before tagging v0.1.0",
        }
        print("D9 FINAL RELEASE QUALIFICATION PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
