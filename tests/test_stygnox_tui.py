"""D8.6B installed TUI, terminal identity, and parity characterization tests."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import operator, tui  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "D8.6B TUI Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=path, check=True)


class StygnoxTuiTests(TestCase):
    def test_packaged_terminal_identity_matches_authoritative_branding(self) -> None:
        pairs = {
            "stygnox-ascii.txt": ROOT / "branding/assets/ascii/stygnox-ascii.txt",
            "stygnox-ascii-ansi.txt": ROOT / "branding/assets/ascii/stygnox-ascii-ansi.txt",
        }
        for name, source in pairs.items():
            packaged = SRC / "stygnox/terminal_assets" / name
            self.assertEqual(sha(source), sha(packaged), name)

    def test_render_uses_exact_plain_and_ansi_brand_at_normal_width(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = operator.operator_snapshot(repo)
            plain = tui.render_snapshot(snapshot, color_mode="never", width=100, stream=io.StringIO())
            self.assertTrue(plain.startswith(tui._asset("stygnox-ascii.txt").rstrip("\n")))
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NO_COLOR", None)
                ansi = tui.render_snapshot(snapshot, color_mode="always", width=100, stream=io.StringIO())
            self.assertTrue(ansi.startswith(tui._asset("stygnox-ascii-ansi.txt").rstrip("\n")))
            self.assertNotIn("RALPH-Lite", plain)
            self.assertNotIn("ZEN Control", plain)

    def test_narrow_terminal_uses_compact_identity_and_preserves_non_colour_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            (repo / "external.txt").write_text("external\n", encoding="utf-8")
            snapshot = operator.operator_snapshot(repo)
            rendered = tui.render_snapshot(snapshot, color_mode="never", width=55, stream=io.StringIO())
            self.assertTrue(rendered.startswith("Stygnox "))
            self.assertNotIn("AUTONOMOUS DEVELOPMENT-LOOP PLATFORM", rendered)
            self.assertIn("[HUMAN]", rendered)
            self.assertIn("Auto-adopt NO", rendered)

    def test_no_color_overrides_forced_colour(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = operator.operator_snapshot(repo)
            with mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
                rendered = tui.render_snapshot(snapshot, color_mode="always", width=100, stream=io.StringIO())
            self.assertNotIn("\x1b[", rendered)
            self.assertTrue(rendered.startswith(tui._asset("stygnox-ascii.txt").rstrip("\n")))

    def test_operator_and_tui_json_snapshots_are_semantically_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            direct = operator.operator_snapshot(repo)
            # PID is presentation-instance metadata, not authority semantics.
            direct["server"]["pid"] = 0
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SRC)
            result = subprocess.run(
                [sys.executable, "-m", "stygnox", "tui", "--project", str(repo), "--json"],
                cwd=repo, env=env, text=True, capture_output=True, check=True,
            )
            through_tui = json.loads(result.stdout)
            through_tui["server"]["pid"] = 0
            self.assertEqual(direct, through_tui)


    def test_render_exposes_operator_state_policy_attribution_and_evidence_sections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            rendered = tui.render_snapshot(operator.operator_snapshot(repo), color_mode="never", width=100, stream=io.StringIO())
            for section in ("OPERATOR STATE", "EXECUTION POLICY", "CHANGE ATTRIBUTION", "EVIDENCE"):
                with self.subTest(section=section):
                    self.assertIn(section, rendered)

    def test_tui_refuses_unknown_action_without_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SRC)
            result = subprocess.run(
                [sys.executable, "-m", "stygnox", "tui", "action", "--project", str(repo), "--name", "legacy.ralph.run", "--json"],
                cwd=repo, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("unsupported installed operator action", result.stderr)
            self.assertFalse((repo / ".stygnox").exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
