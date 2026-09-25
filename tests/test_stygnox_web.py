"""D8.6A installed neutral Web-surface characterization tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import web  # noqa: E402


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

    def test_non_loopback_binding_is_explicitly_unsupported(self) -> None:
        self.assertTrue(web._loopback("127.0.0.1"))
        self.assertTrue(web._loopback("::1"))
        self.assertTrue(web._loopback("localhost"))
        self.assertFalse(web._loopback("0.0.0.0"))
        self.assertFalse(web._loopback("192.168.1.10"))

    def test_static_asset_allowlist_refuses_arbitrary_package_paths(self) -> None:
        with self.assertRaisesRegex(web.WebError, "unknown packaged Web asset"):
            web._asset("../controller.py")


if __name__ == "__main__":
    import unittest
    unittest.main()
