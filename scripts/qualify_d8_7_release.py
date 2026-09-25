#!/usr/bin/env python3
"""D8.7 build-once release-set and exact installed-artifact qualification."""
from __future__ import annotations

import argparse
import ast
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = runpy.run_path(str(ROOT / "src/stygnox/_version.py"))["__version__"]
SCHEMA = "stygnox_d8_7_release_qualification_v1"
WHEEL_ENV = "STYGNOX_QUALIFICATION_WHEEL"
QUALIFIERS = [
    ("D8.1", "qualify_d8_1_installed.py"),
    ("D8.2", "qualify_d8_2_bootstrap.py"),
    ("D8.3", "qualify_d8_3_transactions.py"),
    ("D8.4", "qualify_d8_4_lifecycle.py"),
    ("D8.5", "qualify_d8_5_controller.py"),
    ("D8.6A", "qualify_d8_6a_web.py"),
    ("D8.6B", "qualify_d8_6b_tui.py"),
]
REQUIRED_RELEASE_FILES = {
    "OPERATOR-GUIDE.md",
    "RELEASE-CANDIDATE.md",
    "POST-EXTRACTION-REPORT.md",
    "LICENSE",
    "NOTICE.md",
    "TRADEMARK.md",
    "LICENSING.md",
    "CLA.md",
    "release-manifest.json",
    "SHA256SUMS",
}
REQUIRED_SOURCE_MEMBERS = {
    "README.md",
    "pyproject.toml",
    "docs/d8-7-operator-guide.md",
    "docs/d8-7-release-candidate.md",
    "docs/d8-7-post-extraction-report.md",
    "scripts/build_d8_7_release.py",
    "scripts/qualify_d8_7_release.py",
    "scripts/stygnox_qualification_artifact.py",
    "branding/docs/STYLE_GUIDE.md",
    "provenance/stygnox-extraction-seed.json",
    "tests/test_stygnox_release.py",
    "CLA.md",
    "COMMERCIAL-LICENSING.md",
    "CONTRIBUTING-LICENSING.md",
    "CONTRIBUTORS.md",
    "CREDITS.md",
    "LICENSING.md",
    "NOTICE.md",
    "RECOGNITION.md",
    "TRADEMARK.md",
    "docs/legal/LICENSING-FRAMEWORK-NOTES.md",
    "docs/d9-independent-release-review.md",
    "scripts/qualify_d9_release_review.py",
}


def run(argv: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_first_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise RuntimeError("qualifier output contained no JSON report")
    value, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise RuntimeError("qualifier report is not a JSON object")
    return value


def verify_sha256s(release_dir: Path) -> None:
    sums = release_dir / "SHA256SUMS"
    if not sums.is_file():
        raise RuntimeError("release SHA256SUMS is missing")
    seen: set[str] = set()
    for raw in sums.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        digest, separator, name = raw.partition("  ")
        if not separator or len(digest) != 64 or not name:
            raise RuntimeError(f"invalid SHA256SUMS row: {raw!r}")
        target = release_dir / name
        if not target.is_file() or sha256(target) != digest:
            raise RuntimeError(f"release checksum mismatch: {name}")
        seen.add(name)
    expected = {p.name for p in release_dir.iterdir() if p.is_file() and p.name != "SHA256SUMS"}
    if seen != expected:
        raise RuntimeError(f"SHA256SUMS inventory mismatch: seen={sorted(seen)} expected={sorted(expected)}")


def release_file_digests(release_dir: Path) -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(release_dir.iterdir(), key=lambda p: p.name)
        if path.is_file()
    }


def verify_source_archive(source: Path) -> dict[str, object]:
    prefix = f"stygnox-{VERSION}-source/"
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        names = {m.name for m in members if m.isfile()}
        unsafe = [m.name for m in members if m.name.startswith("/") or "../" in m.name or m.name == ".."]
        if unsafe:
            raise RuntimeError(f"unsafe source archive members: {unsafe}")
    missing = sorted(prefix + rel for rel in REQUIRED_SOURCE_MEMBERS if prefix + rel not in names)
    if missing:
        raise RuntimeError(f"source-review archive misses required release material: {missing}")
    forbidden_generated = [
        name for name in names
        if "/build/" in name or "/dist/" in name or "/.stygnox/" in name or "/__pycache__/" in name or ".egg-info/" in name
    ]
    if forbidden_generated:
        raise RuntimeError(f"source-review archive contains generated/runtime material: {forbidden_generated[:8]}")
    if prefix + "APPLY.md" in names:
        raise RuntimeError("source-review archive contains obsolete one-time licensing application scaffolding")
    return {
        "file_count": len(names),
        "required_material": "PASS",
        "generated_material_excluded": "PASS",
        "governance_material": "PASS",
        "apply_scaffolding": "ABSENT",
    }


def _legacy_imports(source: str, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    findings: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        for name in names:
            if name == "ralph" or name.startswith("ralph_") or name.startswith("ralph."):
                findings.append(f"{filename}:{getattr(node, 'lineno', '?')}:{name}")
    return findings


def verify_wheel(wheel: Path) -> dict[str, object]:
    forbidden_paths: list[str] = []
    legacy_imports: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in names:
            lower = name.lower()
            if name.startswith(("scripts/", "tests/", "branding/", "provenance/")):
                forbidden_paths.append(name)
            if "/ralph" in lower or lower.startswith("ralph"):
                forbidden_paths.append(name)
            if name.endswith(".py") and name.startswith("stygnox/"):
                legacy_imports.extend(_legacy_imports(archive.read(name).decode("utf-8"), name))
        entry_points = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entry_points) != 1:
            raise RuntimeError(f"wheel entry-point metadata is ambiguous: {entry_points}")
        entry_text = archive.read(entry_points[0]).decode("utf-8")
        if "stygnox = stygnox.cli:main" not in entry_text:
            raise RuntimeError("wheel does not expose the neutral installed stygnox command")
        wheel_meta = [name for name in names if name.endswith(".dist-info/WHEEL")]
        if len(wheel_meta) != 1:
            raise RuntimeError(f"wheel metadata is ambiguous: {wheel_meta}")
        wheel_text = archive.read(wheel_meta[0]).decode("utf-8")
        if "Generator: stygnox-release-builder/1" not in wheel_text:
            raise RuntimeError("wheel was not produced by the canonical Stygnox release builder")
        dist_prefix = wheel_meta[0].rsplit("/", 1)[0] + "/"
        required_legal = {
            dist_prefix + "LICENSE": ROOT / "LICENSE",
            dist_prefix + "NOTICE": ROOT / "NOTICE.md",
            dist_prefix + "TRADEMARK": ROOT / "TRADEMARK.md",
        }
        for member, authority in required_legal.items():
            if member not in names or archive.read(member) != authority.read_bytes():
                raise RuntimeError(f"wheel legal metadata mismatch: {member}")
        required_assets = {
            "stygnox/terminal_assets/stygnox-ascii.txt": ROOT / "branding/assets/ascii/stygnox-ascii.txt",
            "stygnox/terminal_assets/stygnox-ascii-ansi.txt": ROOT / "branding/assets/ascii/stygnox-ascii-ansi.txt",
            "stygnox/web_assets/design-tokens.css": ROOT / "branding/css/design-tokens.css",
            "stygnox/web_assets/components.css": ROOT / "branding/css/components.css",
        }
        for member, authority in required_assets.items():
            if member not in names or archive.read(member) != authority.read_bytes():
                raise RuntimeError(f"wheel asset does not match branding authority: {member}")
    if forbidden_paths:
        raise RuntimeError(f"legacy/source-only paths leaked into installed wheel: {sorted(set(forbidden_paths))[:12]}")
    if legacy_imports:
        raise RuntimeError(f"installed wheel imports legacy Ralph modules: {legacy_imports}")
    return {
        "neutral_entry_point": "PASS",
        "legacy_source_paths": "ABSENT",
        "legacy_ralph_imports": "ABSENT",
        "branding_assets": "PASS",
        "canonical_generator": "PASS",
        "legal_metadata": "PASS",
    }


def verify_docs(release_dir: Path) -> dict[str, str]:
    missing = sorted(name for name in REQUIRED_RELEASE_FILES if not (release_dir / name).is_file())
    if missing:
        raise RuntimeError(f"release documentation/material missing: {missing}")
    guide = (release_dir / "OPERATOR-GUIDE.md").read_text(encoding="utf-8")
    required_phrases = [
        "Supported environment",
        "Adoption journeys",
        "Transaction authority, safe stop, and exact recovery",
        "Migration from supported legacy RALPH state",
        "Upgrade and uninstall",
        "Web, TUI, and operator surfaces",
        "Release qualification",
    ]
    absent = [phrase for phrase in required_phrases if phrase not in guide]
    if absent:
        raise RuntimeError(f"operator guide is incomplete: {absent}")
    if "python3 scripts/ralph.py" in guide:
        raise RuntimeError("operator guide exposes legacy python3 scripts/ralph.py as a normal-path command")
    return {"operator_guide": "PASS", "release_candidate_map": "PASS", "post_extraction_report": "PASS"}


def run_predecessor_gates(wheel: Path, log_dir: Path | None) -> dict[str, dict[str, object]]:
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
        env.pop(name, None)
    env[WHEEL_ENV] = str(wheel.resolve())
    wheel_sha = sha256(wheel)
    reports: dict[str, dict[str, object]] = {}
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
    for stage, filename in QUALIFIERS:
        result = run([sys.executable, str(ROOT / "scripts" / filename)], env=env)
        report = parse_first_json(result.stdout)
        if report.get("version") != VERSION:
            raise RuntimeError(f"{stage} qualified unexpected version: {report.get('version')!r}")
        if report.get("wheel_sha256") != wheel_sha:
            raise RuntimeError(
                f"{stage} did not qualify the exact release wheel: "
                f"{report.get('wheel_sha256')} != {wheel_sha}"
            )
        reports[stage] = {
            "schema": report.get("schema"),
            "version": report.get("version"),
            "wheel_sha256": report.get("wheel_sha256"),
            "result": "PASS",
        }
        if log_dir is not None:
            stem = stage.lower().replace(".", "-")
            (log_dir / f"{stem}.stdout.txt").write_text(result.stdout, encoding="utf-8")
            (log_dir / f"{stem}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    return reports


def qualify_pre_d9_findings(log_dir: Path | None) -> dict[str, str]:
    tests = [
        "tests.test_ralph_lifecycle.RunLoopSandboxVerificationTests.test_mixed_tooling_and_product_pass_records_only_verified_attribution",
        "tests.test_ralph_replacement_inventory.ReplacementInventoryTests.test_records_manifest_bound_and_snapshot_only_dirty_paths",
        "tests.test_ralph_lite.ControllerQualificationAuthorityTests.test_explicit_blocked_human_summary_cannot_be_laundered_into_pass",
        "tests.test_ralph_carry_forward_reconciliation.CarryForwardReconciliationTests.test_rejects_expired_self_hosting_and_records_nonabsorption_dispositions",
    ]
    result = run([sys.executable, "-m", "unittest", *tests, "-v"])
    if log_dir is not None:
        (log_dir / "pre-d9-findings.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (log_dir / "pre-d9-findings.stderr.txt").write_text(result.stderr, encoding="utf-8")
    return {
        "D8-FINDING-02": "PASS",
        "D8-FINDING-03": "PASS",
        "D8-FINDING-05": "PASS",
        "D8-FINDING-06": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="retain release set and qualification evidence; must be empty")
    args = parser.parse_args()

    retained = args.output_dir.expanduser().resolve() if args.output_dir else None
    if retained is not None:
        if retained.exists() and any(retained.iterdir()):
            raise SystemExit(f"refusing non-empty --output-dir: {retained}")
        retained.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="stygnox-d87-qualification-") as td:
        temporary = Path(td)
        release_dir = retained if retained is not None else temporary / "release"
        build = run([sys.executable, str(ROOT / "scripts/build_d8_7_release.py"), "--output-dir", str(release_dir)])
        manifest = json.loads((release_dir / "release-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("version") != VERSION:
            raise RuntimeError(f"release manifest version mismatch: {manifest.get('version')!r}")
        wheels = sorted(release_dir.glob(f"stygnox-{VERSION}-*.whl"))
        sources = sorted(release_dir.glob(f"stygnox-{VERSION}-source.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise RuntimeError(f"release set artifact count invalid: wheels={wheels} sources={sources}")
        wheel, source = wheels[0], sources[0]
        wheel_sha = sha256(wheel)

        verify_sha256s(release_dir)
        docs = verify_docs(release_dir)
        source_report = verify_source_archive(source)
        wheel_report = verify_wheel(wheel)

        # Rebuild only for reproducibility comparison. The first wheel remains
        # the sole artifact supplied to every predecessor qualification gate.
        second = temporary / "reproducibility"
        run([sys.executable, str(ROOT / "scripts/build_d8_7_release.py"), "--output-dir", str(second)])
        first_digests = release_file_digests(release_dir)
        second_digests = release_file_digests(second)
        if first_digests != second_digests:
            raise RuntimeError(f"release set is not reproducible: first={first_digests} second={second_digests}")

        qualification_dir = retained / "qualification" if retained is not None else None
        logs = qualification_dir / "logs" if qualification_dir is not None else None
        predecessor = run_predecessor_gates(wheel, logs)
        findings = qualify_pre_d9_findings(logs)

        report = {
            "schema": SCHEMA,
            "version": VERSION,
            "wheel": wheel.name,
            "wheel_sha256": wheel_sha,
            "source_archive": source.name,
            "source_archive_sha256": sha256(source),
            "release_manifest_sha256": sha256(release_dir / "release-manifest.json"),
            "release_checksums": "PASS",
            "release_set_reproducible": "PASS",
            "wheel_scan": wheel_report,
            "source_review_archive": source_report,
            "documentation": docs,
            "exact_artifact_predecessor_gates": predecessor,
            "all_predecessor_gates_same_wheel": "PASS",
            "post_extraction_legacy_quarantine": "PASS",
            "pre_d9_findings": findings,
            "supported_install_media": ["wheel"],
            "next_stage": "D9 first independent release review and release decision",
        }
        rendered = json.dumps(report, indent=2, sort_keys=True)
        if qualification_dir is not None:
            qualification_dir.mkdir(parents=True, exist_ok=True)
            (qualification_dir / "d8-7-qualification.json").write_text(rendered + "\n", encoding="utf-8")
            (qualification_dir / "release-build.stdout.txt").write_text(build.stdout, encoding="utf-8")
            (qualification_dir / "release-build.stderr.txt").write_text(build.stderr, encoding="utf-8")
        print("D8.7 RELEASE PACKAGING / DOCUMENTATION / EXACT-ARTIFACT QUALIFICATION PASS")
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
