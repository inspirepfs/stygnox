"""D8.7 release packaging and exact-artifact qualification characterization."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import sys
from unittest import TestCase, mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
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
            "docs/web-ui-retirement.md",
            "scripts/build_d8_7_release.py",
            "scripts/qualify_d8_7_release.py",
            "scripts/stygnox_qualification_artifact.py",
            "tests/test_stygnox_release.py",
            "tests/test_stygnox_presentation_boundary.py",
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
        for retired in (
            "src/stygnox/web.py",
            "src/stygnox/web_brand.py",
            "scripts/stygnox_web.py",
            "scripts/qualify_d8_6a_web.py",
            "tests/test_stygnox_web.py",
            "tests/test_stygnox_web_lifecycle.py",
        ):
            self.assertNotIn(retired, names)
        self.assertFalse(any(name.startswith("src/stygnox/web_assets/") for name in names))

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

    def test_release_qualifiers_enforce_retired_web_boundary(self) -> None:
        d87 = (SCRIPTS / "qualify_d8_7_release.py").read_text(encoding="utf-8")
        d9 = (SCRIPTS / "qualify_d9_release_review.py").read_text(encoding="utf-8")
        self.assertNotIn('("D8.6A", "qualify_d8_6a_web.py")', d87)
        self.assertIn("retired installed Web surface leaked into wheel", d87)
        self.assertIn("docs/web-ui-retirement.md", d87)
        self.assertIn("unknown installed Stygnox command", d9)
        self.assertIn('("web", "serve", "web-auth")', d9)
        self.assertIn("retired installed Web surface leaked into wheel", d9)

    def test_d85_fake_provider_tracks_current_metadata_and_result_contract(self) -> None:
        qualifier = load_script("qualify_d8_5_controller.py")
        with tempfile.TemporaryDirectory(prefix="stygnox-d85-fake-contract-") as td:
            root = Path(td)
            fakebin = root / "bin"
            log = root / "fake-codex.jsonl"
            codex = qualifier.make_fake_codex(fakebin, log)
            env = os.environ.copy()
            env["STYGNOX_FAKE_CODEX_LOG"] = str(log)

            proc = subprocess.Popen(
                [str(codex), "app-server", "--stdio"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, env=env,
            )
            try:
                assert proc.stdin is not None and proc.stdout is not None
                for rid, method, params in (
                    (1, "initialize", {"clientInfo": {"name": "test"}}),
                    (2, "model/list", {"limit": 100, "cursor": None, "includeHidden": False}),
                    (3, "account/rateLimits/read", None),
                ):
                    request = {"jsonrpc": "2.0", "id": rid, "method": method}
                    if params is not None:
                        request["params"] = params
                    proc.stdin.write(json.dumps(request) + "\n")
                    proc.stdin.flush()
                    response = json.loads(proc.stdout.readline())
                    self.assertEqual(rid, response["id"])
                    result = response["result"]
                    if method == "model/list":
                        models = {row["model"]: row for row in result["data"]}
                        self.assertIn("gpt-5.6-terra", models)
                        efforts = {row["reasoningEffort"] for row in models["gpt-5.6-terra"]["supportedReasoningEfforts"]}
                        self.assertIn("high", efforts)
                    elif method == "account/rateLimits/read":
                        self.assertIs(result["ordinaryUsageAllowed"], True)
                        self.assertIn("codex", result["rateLimitsByLimitId"])
                proc.stdin.close()
                proc.wait(timeout=3)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=3)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()

            output = root / "result.json"
            subprocess.run(
                [str(codex), "exec", "--model", "gpt-5.6-terra", "-o", str(output), "qualification"],
                env=env, check=True, text=True, capture_output=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                {"status", "summary", "blocker_class", "blockers", "validation_notes", "files_inspected"},
                set(payload),
            )
            self.assertEqual("PASS", payload["status"])
            self.assertEqual("none", payload["blocker_class"])
