"""D8.7 release packaging and exact-artifact qualification characterization."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import runpy
import tempfile
from unittest import TestCase, mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VERSION = runpy.run_path(str(ROOT / "src/stygnox/_version.py"))["__version__"]


def load_script(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StygnoxReleaseTests(TestCase):
    def test_product_identity_marks_independent_release(self) -> None:
        namespace = runpy.run_path(str(ROOT / "src/stygnox/product.py"), run_name="stygnox.product")
        product = namespace["PRODUCT"]
        self.assertEqual("0.1.0", VERSION)
        self.assertEqual(VERSION, product.version)
        self.assertEqual("independent release", product.stage)

    def test_release_source_selection_includes_closure_material_and_excludes_generated_state(self) -> None:
        builder = load_script("build_d8_7_release.py")
        names = {path.relative_to(ROOT).as_posix() for path in builder.source_files()}
        required = {
            "docs/d8-7-operator-guide.md",
            "docs/d8-7-release-candidate.md",
            "docs/d8-7-post-extraction-report.md",
            "scripts/build_d8_7_release.py",
            "scripts/qualify_d8_7_release.py",
            "scripts/stygnox_qualification_artifact.py",
            "tests/test_stygnox_release.py",
            "branding/docs/STYLE_GUIDE.md",
            "provenance/stygnox-extraction-seed.json",
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
        self.assertTrue(required.issubset(names), sorted(required - names))
        self.assertFalse(any("/__pycache__/" in f"/{name}/" for name in names))
        self.assertFalse(any("/.stygnox/" in f"/{name}/" for name in names))
        self.assertFalse(any("/dist/" in f"/{name}/" or "/build/" in f"/{name}/" for name in names))
        self.assertFalse(any(".egg-info/" in name for name in names))
        self.assertNotIn("APPLY.md", names)

    def test_source_review_archive_is_deterministic(self) -> None:
        builder = load_script("build_d8_7_release.py")
        with tempfile.TemporaryDirectory(prefix="stygnox-d87-source-test-") as td:
            root = Path(td)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            first_sha, first_count = builder.build_source_archive(first, VERSION)
            second_sha, second_count = builder.build_source_archive(second, VERSION)
            self.assertEqual(first_count, second_count)
            self.assertEqual(first_sha, second_sha)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_exact_wheel_helper_is_opt_in_and_rejects_non_wheel_artifacts(self) -> None:
        helper = load_script("stygnox_qualification_artifact.py")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(helper.ENV_NAME, None)
            self.assertIsNone(helper.provided_wheel())
        with tempfile.TemporaryDirectory(prefix="stygnox-d87-wheel-helper-") as td:
            root = Path(td)
            good = root / "stygnox-0.1.0-py3-none-any.whl"
            bad = root / "stygnox-0.1.0.tar.gz"
            good.write_bytes(b"wheel-placeholder")
            bad.write_bytes(b"source-placeholder")
            with mock.patch.dict(os.environ, {helper.ENV_NAME: str(good)}, clear=False):
                self.assertEqual(good.resolve(), helper.provided_wheel())
            with mock.patch.dict(os.environ, {helper.ENV_NAME: str(bad)}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "Stygnox .whl"):
                    helper.provided_wheel()

    def test_predecessor_qualifiers_accept_external_wheel_and_d86b_is_not_version_pinned(self) -> None:
        qualifier_names = [
            "qualify_d8_1_installed.py",
            "qualify_d8_2_bootstrap.py",
            "qualify_d8_3_transactions.py",
            "qualify_d8_4_lifecycle.py",
            "qualify_d8_5_controller.py",
            "qualify_d8_6a_web.py",
            "qualify_d8_6b_tui.py",
        ]
        for name in qualifier_names:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("provided_wheel", text)
                self.assertIn("stygnox_qualification_artifact", text)
        d86b = (SCRIPTS / "qualify_d8_6b_tui.py").read_text(encoding="utf-8")
        self.assertIn("_version.py", d86b)
        self.assertNotIn('VERSION = "0.1.0.dev7"', d86b)
