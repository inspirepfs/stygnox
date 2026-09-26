"""D8.6A installed neutral Web-surface characterization tests."""
from __future__ import annotations

import base64
import hashlib
import io
import os
from contextlib import redirect_stdout
from http.cookiejar import CookieJar
from pathlib import Path
import subprocess
import tempfile
import threading
import sys
from unittest import TestCase, mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import web  # noqa: E402


def make_git_repo() -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "stygnox-tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Stygnox Tests"], check=True)
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "fixture"], check=True)
    return temp


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StygnoxWebTests(TestCase):
    def test_packaged_brand_assets_match_authoritative_branding_sources(self) -> None:
        text_pairs = {
            "design-tokens.css": ROOT / "branding/css/design-tokens.css",
            "components.css": ROOT / "branding/css/components.css",
        }
        for name, source in text_pairs.items():
            packaged = SRC / "stygnox/web_assets" / name
            self.assertEqual(sha(source), sha(packaged), name)
        binary_pairs = {
            "stygnox-icon-128.png": ROOT / "branding/assets/brand/stygnox-icon-128.png",
            "stygnox-logo-800x300.png": ROOT / "branding/assets/brand/stygnox-logo-800x300.png",
        }
        for name, source in binary_pairs.items():
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), hashlib.sha256(web._asset(name)).hexdigest(), name)

    def test_page_uses_brand_tokens_accessible_state_and_explicit_reconciliation_language(self) -> None:
        page = web._index_html("csrf-token").decode("utf-8")
        self.assertIn("/assets/design-tokens.css", page)
        self.assertIn("/assets/components.css", page)
        self.assertIn("/assets/stygnox-logo-800x300.png", page)
        self.assertIn('role="status"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn("No automatic adoption or reattribution", page)
        self.assertIn("Operator baseline", (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8"))
        self.assertNotIn("RALPH-Lite", page)
        self.assertNotIn("Zen Control", page)
        self.assertNotIn("D8.6A", page)
        self.assertNotIn("D8.6 cross-surface gate", (SRC / "stygnox/web.py").read_text(encoding="utf-8"))

    def test_non_loopback_binding_requires_authentication_instead_of_being_forbidden(self) -> None:
        self.assertTrue(web._loopback("127.0.0.1"))
        self.assertTrue(web._loopback("::1"))
        self.assertTrue(web._loopback("localhost"))
        self.assertFalse(web._loopback("0.0.0.0"))
        self.assertFalse(web._loopback("192.168.1.10"))
        self.assertTrue(web._remote_bind_allowed("127.0.0.1", None))
        self.assertFalse(web._remote_bind_allowed("0.0.0.0", None))
        self.assertFalse(web._remote_bind_allowed("192.168.1.10", None))
        self.assertTrue(web._remote_bind_allowed("0.0.0.0", {"username": "operator"}))
        parsed = web.build_parser().parse_args(["--host", "0.0.0.0", "--port", "9123"])
        self.assertEqual("0.0.0.0", parsed.host)
        self.assertEqual(9123, parsed.port)
        auth_args = web.build_auth_parser().parse_args(["set", "--username", "peter", "--project", "/tmp/project"])
        self.assertEqual("set", auth_args.action)
        self.assertEqual("peter", auth_args.username)
        self.assertEqual(Path("/tmp/project"), auth_args.project)

    def test_web_auth_setup_stores_only_hash_and_verifies_basic_credentials(self) -> None:
        temp = make_git_repo()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        record_path = web.set_web_auth(root, "peter", "correct horse battery staple")
        self.assertEqual(0o600, record_path.stat().st_mode & 0o777)
        text = record_path.read_text(encoding="utf-8")
        self.assertNotIn("correct horse battery staple", text)
        resolved, record = web.load_web_auth(root)
        self.assertEqual(root.resolve(), resolved)
        self.assertIsNotNone(record)
        assert record is not None
        good = base64.b64encode(b"peter:correct horse battery staple").decode("ascii")
        bad = base64.b64encode(b"peter:wrong").decode("ascii")
        self.assertTrue(web._authorization_matches(record, f"Basic {good}"))
        self.assertFalse(web._authorization_matches(record, f"Basic {bad}"))
        self.assertFalse(web._authorization_matches(record, None))

    def test_authenticated_web_server_shows_login_and_keeps_basic_api_auth(self) -> None:
        temp = make_git_repo()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        web.set_web_auth(root, "peter", "lab-password")
        _root, record = web.load_web_auth(root)
        server = web.OperatorServer(("127.0.0.1", 0), root, auth_record=record)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/", timeout=3) as response:
            login = response.read().decode("utf-8")
        self.assertEqual(200, response.status)
        self.assertIn("Stygnox Login", login)
        with self.assertRaises(HTTPError) as ctx:
            urlopen(base + "/api/snapshot", timeout=3)
        self.assertEqual(401, ctx.exception.code)
        self.assertIn("Basic", ctx.exception.headers.get("WWW-Authenticate", ""))
        token = base64.b64encode(b"peter:lab-password").decode("ascii")
        request = Request(base + "/", headers={"Authorization": f"Basic {token}"})
        with urlopen(request, timeout=3) as response:
            page = response.read().decode("utf-8")
        self.assertEqual(200, response.status)
        self.assertIn("Stygnox Operator Console", page)

    def test_browser_login_form_sets_session_cookie_and_serves_console(self) -> None:
        temp = make_git_repo()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        web.set_web_auth(root, "peter", "lab-password")
        _root, record = web.load_web_auth(root)
        server = web.OperatorServer(("127.0.0.1", 0), root, auth_record=record)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))
        body = urlencode({"username": "peter", "password": "lab-password"}).encode("utf-8")
        request = Request(base + "/login", data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with opener.open(request, timeout=3) as response:
            page = response.read().decode("utf-8")
        self.assertEqual(200, response.status)
        self.assertEqual(base + "/", response.geturl())
        self.assertIn("Stygnox Operator Console", page)
        self.assertTrue(any(cookie.name == "StygnoxSession" for cookie in jar))

    def test_web_auth_clear_removes_remote_bind_authority(self) -> None:
        temp = make_git_repo()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        web.set_web_auth(root, "operator", "password")
        _root, record = web.load_web_auth(root)
        self.assertTrue(web._remote_bind_allowed("0.0.0.0", record))
        self.assertTrue(web.clear_web_auth(root))
        _root, record = web.load_web_auth(root)
        self.assertIsNone(record)
        self.assertFalse(web._remote_bind_allowed("0.0.0.0", record))

    def test_web_auth_cli_set_status_and_clear(self) -> None:
        temp = make_git_repo()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        with mock.patch.object(web.getpass, "getpass", side_effect=["lab-password", "lab-password"]):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, web.auth_cli_main(["set", "--username", "peter", "--project", str(root)]))
        self.assertIn("authentication configured", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, web.auth_cli_main(["status", "--project", str(root)]))
        self.assertIn("username=peter", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, web.auth_cli_main(["clear", "--project", str(root)]))
        self.assertIn("authentication cleared", output.getvalue())


    def test_web_exposes_tui_state_sections_and_all_operator_actions(self) -> None:
        page = web._index_html("csrf-token").decode("utf-8")
        script = (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8")
        for section in ("Operator state", "Execution policy", "Change attribution", "Evidence", "Recent authority evidence", "Authority actions"):
            with self.subTest(section=section):
                self.assertIn(section, page)
        for field_id in (
            "product-name", "product-version", "profile-name", "project-path", "authority-summary",
            "transaction-summary", "provider", "policy-model", "policy-effort", "efficiency",
            "reserve", "wait-limits", "usage-poll", "max-loops", "policy-reviewer",
            "policy-catalog", "policy-supported-efforts", "policy-model-options", "policy-effort-options",
            "runtime-directory", "runtime-count", "controller-receipts", "source-tree-fallback",
            "legacy-delegate", "authority-evidence",
        ):
            with self.subTest(field_id=field_id):
                self.assertIn(f'id="{field_id}"', page)
        for action in (
            "adopt.preview", "adopt.abort", "adopt.handoff",
            "transaction.begin", "transaction.stop",
            "recovery.preview", "recovery.restore",
            "policy.catalog", "policy.preview", "policy.set", "policy.reset",
            "controller.activate", "controller.deactivate", "controller.run-preview", "controller.run",
        ):
            with self.subTest(action=action):
                self.assertIn(action, script)

    def test_web_preview_actions_capture_confirmation_digests(self) -> None:
        script = (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8")
        self.assertIn("preview-input", script)
        self.assertIn("recovery-preview-input", script)
        self.assertIn("policy-preview-input", script)
        self.assertIn("run-preview-input", script)
        self.assertIn("capturePreview", script)

    def test_static_asset_allowlist_refuses_arbitrary_package_paths(self) -> None:
        with self.assertRaisesRegex(web.WebError, "unknown packaged Web asset"):
            web._asset("../controller.py")


if __name__ == "__main__":
    import unittest
    unittest.main()
