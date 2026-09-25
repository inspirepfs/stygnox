#!/usr/bin/env python3
"""Build the deterministic D8.7 Stygnox release set from explicit source inputs.

The supported install medium is the wheel.  The source tarball is a review and
rebuild artifact containing product source, tests, qualification tooling,
operator documentation, branding authority, and extraction provenance.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "stygnox" / "_version.py"
SOURCE_DATE_EPOCH = 946684800  # 2000-01-01T00:00:00Z; stable and ZIP-safe.
RELEASE_MANIFEST_SCHEMA = "stygnox_d8_7_release_manifest_v1"

ROOT_FILES = (
    ".gitignore",
    ".ralph/policy.md",
    "LICENSE",
    "README.md",
    "pyproject.toml",
)
SOURCE_DIRS = ("branding", "docs", "provenance", "scripts", "src", "tests")
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", ".stygnox",
}
VISIBLE_DOCS = {
    "OPERATOR-GUIDE.md": "docs/d8-7-operator-guide.md",
    "RELEASE-CANDIDATE.md": "docs/d8-7-release-candidate.md",
    "POST-EXTRACTION-REPORT.md": "docs/d8-7-post-extraction-report.md",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version() -> str:
    namespace: dict[str, object] = {}
    exec(VERSION_FILE.read_text(encoding="utf-8"), namespace)
    value = str(namespace.get("__version__") or "")
    if not value:
        raise RuntimeError("canonical version is missing")
    return value


def _excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in path.parts) or path.suffix in {".pyc", ".pyo"}


def source_files(root: Path = ROOT) -> list[Path]:
    files: set[Path] = set()
    for name in ROOT_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"required release source file missing or unsupported: {name}")
        files.add(path)
    for dirname in SOURCE_DIRS:
        base = root / dirname
        if not base.is_dir() or base.is_symlink():
            raise RuntimeError(f"required release source directory missing or unsupported: {dirname}")
        for path in base.rglob("*"):
            if _excluded(path.relative_to(root)):
                continue
            if path.is_file() and not path.is_symlink():
                files.add(path)
            elif path.is_symlink():
                raise RuntimeError(f"release source symlink is unsupported: {path.relative_to(root)}")
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def copy_source_tree(destination: Path) -> list[str]:
    rows: list[str] = []
    for source in source_files():
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rows.append(relative.as_posix())
    return rows


def _tarinfo(name: str, source: Path | None, *, directory: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = SOURCE_DATE_EPOCH
    if directory:
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.size = 0
    else:
        assert source is not None
        mode = stat.S_IMODE(source.stat().st_mode)
        info.mode = 0o755 if mode & 0o111 else 0o644
        info.size = source.stat().st_size
    return info


def build_source_archive(output: Path, release_version: str) -> tuple[str, int]:
    prefix = f"stygnox-{release_version}-source"
    files = source_files()
    directories: set[str] = {prefix}
    for source in files:
        relative = source.relative_to(ROOT)
        parent = relative.parent
        while str(parent) not in {"", "."}:
            directories.add(f"{prefix}/{parent.as_posix()}")
            parent = parent.parent

    with tempfile.NamedTemporaryFile(prefix="stygnox-source-", suffix=".tar", delete=False) as raw:
        raw_path = Path(raw.name)
    try:
        with tarfile.open(raw_path, "w", format=tarfile.GNU_FORMAT) as archive:
            for name in sorted(directories, key=lambda x: (x.count("/"), x)):
                archive.addfile(_tarinfo(name + "/", None, directory=True))
            for source in files:
                relative = source.relative_to(ROOT).as_posix()
                info = _tarinfo(f"{prefix}/{relative}", source)
                with source.open("rb") as stream:
                    archive.addfile(info, stream)
        with raw_path.open("rb") as source, output.open("wb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=9, mtime=SOURCE_DATE_EPOCH) as gz:
                shutil.copyfileobj(source, gz)
    finally:
        raw_path.unlink(missing_ok=True)
    return sha256(output), len(files)


def build_wheel(output_dir: Path, release_version: str) -> tuple[Path, str]:
    with tempfile.TemporaryDirectory(prefix="stygnox-d87-wheel-input-") as td:
        build_root = Path(td)
        copy_source_tree(build_root)
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = str(SOURCE_DATE_EPOCH)
        env["PYTHONHASHSEED"] = "0"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        command = [
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(output_dir), ".",
        ]
        result = subprocess.run(command, cwd=build_root, env=env, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"wheel build failed ({result.returncode})\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    wheels = sorted(output_dir.glob(f"stygnox-{release_version}-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one release wheel, found {wheels}")
    return wheels[0], result.stdout + result.stderr


def write_release(output_dir: Path) -> dict[str, object]:
    release_version = version()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"refusing non-empty release output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    wheel, build_transcript = build_wheel(output_dir, release_version)
    source = output_dir / f"stygnox-{release_version}-source.tar.gz"
    source_sha, source_count = build_source_archive(source, release_version)

    visible: list[dict[str, object]] = []
    for target_name, relative in VISIBLE_DOCS.items():
        source_doc = ROOT / relative
        if not source_doc.is_file():
            raise RuntimeError(f"required D8.7 release document is missing: {relative}")
        target = output_dir / target_name
        shutil.copyfile(source_doc, target)
        visible.append({"name": target.name, "role": "operator-documentation", "sha256": sha256(target), "size": target.stat().st_size})
    license_target = output_dir / "LICENSE"
    shutil.copyfile(ROOT / "LICENSE", license_target)
    visible.append({"name": "LICENSE", "role": "license", "sha256": sha256(license_target), "size": license_target.stat().st_size})

    artifacts: list[dict[str, object]] = [
        {"name": wheel.name, "role": "supported-install-wheel", "sha256": sha256(wheel), "size": wheel.stat().st_size},
        {"name": source.name, "role": "deterministic-source-review-archive", "sha256": source_sha, "size": source.stat().st_size},
        *visible,
    ]
    manifest: dict[str, object] = {
        "schema": RELEASE_MANIFEST_SCHEMA,
        "version": release_version,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "supported_install_media": ["wheel"],
        "source_file_count": source_count,
        "artifacts": artifacts,
        "qualification": {
            "exact_wheel_environment": "STYGNOX_QUALIFICATION_WHEEL",
            "release_gate": "scripts/qualify_d8_7_release.py",
        },
    }
    manifest_path = output_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sums = []
    for path in sorted(output_dir.iterdir(), key=lambda p: p.name):
        if path.name == "SHA256SUMS" or not path.is_file():
            continue
        sums.append(f"{sha256(path)}  {path.name}")
    (output_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    manifest["wheel"] = wheel.name
    manifest["wheel_sha256"] = sha256(wheel)
    manifest["source_archive"] = source.name
    manifest["source_archive_sha256"] = source_sha
    manifest["build_transcript"] = build_transcript
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = write_release(args.output_dir)
    printable = dict(result)
    printable.pop("build_transcript", None)
    print("D8.7 RELEASE BUILD PASS")
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
