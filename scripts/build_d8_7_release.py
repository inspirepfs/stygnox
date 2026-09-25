#!/usr/bin/env python3
"""Build the deterministic Stygnox D9 release-candidate set.

The supported installation medium is the wheel. The wheel is assembled by
Stygnox itself using only the Python standard library so its bytes do not
depend on the host setuptools/wheel implementation. The source tarball is a
review/rebuild artifact containing product source, tests, qualification tools,
operator docs, branding authority, provenance, and project governance.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "stygnox" / "_version.py"
SOURCE_DATE_EPOCH = 946684800  # 2000-01-01T00:00:00Z; stable and ZIP-safe.
ZIP_DATE_TIME = (2000, 1, 1, 0, 0, 0)
RELEASE_MANIFEST_SCHEMA = "stygnox_d8_7_release_manifest_v1"
WHEEL_GENERATOR = "stygnox-release-builder/1"

ROOT_FILES = (
    ".gitignore",
    ".ralph/policy.md",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "CLA.md",
    "COMMERCIAL-LICENSING.md",
    "CONTRIBUTING-LICENSING.md",
    "CONTRIBUTORS.md",
    "CREDITS.md",
    "LICENSING.md",
    "NOTICE.md",
    "RECOGNITION.md",
    "TRADEMARK.md",
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
    "LICENSING.md": "LICENSING.md",
    "COMMERCIAL-LICENSING.md": "COMMERCIAL-LICENSING.md",
    "CONTRIBUTING-LICENSING.md": "CONTRIBUTING-LICENSING.md",
    "CLA.md": "CLA.md",
    "RECOGNITION.md": "RECOGNITION.md",
    "CONTRIBUTORS.md": "CONTRIBUTORS.md",
    "CREDITS.md": "CREDITS.md",
    "NOTICE.md": "NOTICE.md",
    "TRADEMARK.md": "TRADEMARK.md",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_bytes(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def version() -> str:
    namespace: dict[str, object] = {}
    exec(VERSION_FILE.read_text(encoding="utf-8"), namespace)
    value = str(namespace.get("__version__") or "")
    if not value:
        raise RuntimeError("canonical version is missing")
    return value


def _excluded(path: Path) -> bool:
    return (
        any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in path.parts)
        or path.suffix in {".pyc", ".pyo"}
    )


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
            relative = path.relative_to(root)
            if _excluded(relative):
                continue
            if path.is_file() and not path.is_symlink():
                files.add(path)
            elif path.is_symlink():
                raise RuntimeError(f"release source symlink is unsupported: {relative}")
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


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
        with raw_path.open("rb") as source_stream, output.open("wb") as target:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=target, compresslevel=9, mtime=SOURCE_DATE_EPOCH
            ) as gz:
                shutil.copyfileobj(source_stream, gz)
    finally:
        raw_path.unlink(missing_ok=True)
    return sha256(output), len(files)


def _zipinfo(name: str, *, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_DATE_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
    info.extra = b""
    info.comment = b""
    return info


def _metadata(release_version: str) -> bytes:
    classifiers = [
        "Development Status :: 2 - Pre-Alpha",
        "Environment :: Console",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ]
    rows = [
        "Metadata-Version: 2.1",
        "Name: stygnox",
        f"Version: {release_version}",
        "Summary: Stygnox autonomous development-loop controller",
        "Author: Stygnox contributors",
        "Requires-Python: >=3.11,<3.14",
        "License-File: LICENSE",
        "License-File: NOTICE",
        "License-File: TRADEMARK",
    ]
    rows.extend(f"Classifier: {item}" for item in classifiers)
    rows.extend(["", (ROOT / "README.md").read_text(encoding="utf-8"), ""])
    return "\n".join(rows).encode("utf-8")


def _wheel_members(release_version: str) -> dict[str, bytes]:
    package_root = ROOT / "src" / "stygnox"
    members: dict[str, bytes] = {}
    for path in package_root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(package_root)
        if _excluded(relative):
            continue
        members[f"stygnox/{relative.as_posix()}"] = path.read_bytes()

    dist_info = f"stygnox-{release_version}.dist-info"
    members[f"{dist_info}/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    members[f"{dist_info}/NOTICE"] = (ROOT / "NOTICE.md").read_bytes()
    members[f"{dist_info}/TRADEMARK"] = (ROOT / "TRADEMARK.md").read_bytes()
    members[f"{dist_info}/METADATA"] = _metadata(release_version)
    members[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\n"
        f"Generator: {WHEEL_GENERATOR}\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    members[f"{dist_info}/entry_points.txt"] = b"[console_scripts]\nstygnox = stygnox.cli:main\n"
    members[f"{dist_info}/top_level.txt"] = b"stygnox\n"
    return members


def _record_bytes(members: dict[str, bytes], record_name: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(members):
        data = members[name]
        writer.writerow([name, f"sha256={_digest_bytes(data)}", str(len(data))])
    writer.writerow([record_name, "", ""])
    return output.getvalue().encode("utf-8")


def build_wheel(output_dir: Path, release_version: str) -> tuple[Path, str]:
    """Assemble the official wheel without setuptools/wheel host dependencies."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"stygnox-{release_version}-py3-none-any.whl"
    if target.exists():
        raise RuntimeError(f"release wheel already exists: {target}")

    members = _wheel_members(release_version)
    dist_info = f"stygnox-{release_version}.dist-info"
    record_name = f"{dist_info}/RECORD"
    record = _record_bytes(members, record_name)

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        package_names = sorted(name for name in members if not name.startswith(dist_info + "/"))
        metadata_names = sorted(name for name in members if name.startswith(dist_info + "/"))
        for name in [*package_names, *metadata_names]:
            archive.writestr(_zipinfo(name), members[name])
        archive.writestr(_zipinfo(record_name), record)

    transcript = (
        "canonical Stygnox wheel assembled\n"
        f"generator={WHEEL_GENERATOR}\n"
        "compression=stored\n"
        "host_setuptools_dependency=false\n"
        "host_wheel_dependency=false\n"
    )
    return target, transcript


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
            raise RuntimeError(f"required release document is missing: {relative}")
        target = output_dir / target_name
        shutil.copyfile(source_doc, target)
        visible.append({
            "name": target.name,
            "role": "operator-documentation" if target_name in {
                "OPERATOR-GUIDE.md", "RELEASE-CANDIDATE.md", "POST-EXTRACTION-REPORT.md"
            } else "project-governance",
            "sha256": sha256(target),
            "size": target.stat().st_size,
        })

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
        "wheel_build": {
            "method": "canonical-stdlib-wheel",
            "generator": WHEEL_GENERATOR,
            "compression": "stored",
            "host_setuptools_dependency": False,
            "host_wheel_dependency": False,
        },
        "artifacts": artifacts,
        "qualification": {
            "exact_wheel_environment": "STYGNOX_QUALIFICATION_WHEEL",
            "release_gate": "scripts/qualify_d8_7_release.py",
            "independent_review_gate": "scripts/qualify_d9_release_review.py",
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
