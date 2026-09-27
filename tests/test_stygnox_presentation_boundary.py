"""13D-R2 retirement boundary for the removed legacy Web UI."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import cli, operator  # noqa: E402


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Presentation Boundary Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=path, check=True)


class StygnoxPresentationBoundaryTests(TestCase):
    def test_retired_web_commands_fail_closed(self) -> None:
        for command in ("web", "serve", "web-auth"):
            with self.subTest(command=command):
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                    cli.main([command])
                self.assertEqual(2, raised.exception.code)
                self.assertIn("unknown installed Stygnox command", stderr.getvalue())

    def test_successor_frontend_contract_remains_presentation_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, operator.cli_main(["snapshot", "--project", str(repo)]))
            snapshot = json.loads(output.getvalue())
            self.assertEqual("stygnox_operator_surface_v1", snapshot["schema"])
            self.assertEqual("Stygnox", snapshot["identity"])
            self.assertEqual(["adopt.preview"], [row["action"] for row in snapshot["next_actions"]])

            bin_dir = Path(td) / "bin"
            bin_dir.mkdir()
            stygnox = bin_dir / "stygnox"
            stygnox.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stygnox.chmod(0o755)

            output = io.StringIO()
            payload = json.dumps({"operator": "Boundary Test"})
            previous_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(bin_dir) + os.pathsep + previous_path
            try:
                with redirect_stdout(output):
                    self.assertEqual(
                        0,
                        operator.cli_main([
                            "action", "--project", str(repo), "--name", "adopt.preview", "--payload-json", payload,
                        ]),
                    )
            finally:
                os.environ["PATH"] = previous_path
            action = json.loads(output.getvalue())
            self.assertEqual("stygnox_operator_action_v1", action["schema"])
            self.assertEqual("adopt.preview", action["action"])
            self.assertIn("preview_sha256", action["result"])

    def test_authoritative_branding_sources_survive_web_retirement(self) -> None:
        required = (
            ROOT / "branding/design-tokens.json",
            ROOT / "branding/css/design-tokens.css",
            ROOT / "branding/css/components.css",
            ROOT / "branding/assets/brand/stygnox-logo-800x300.png",
            ROOT / "branding/assets/brand/stygnox-icon-128.png",
            ROOT / "branding/assets/ascii/stygnox-ascii.txt",
            ROOT / "branding/assets/ascii/stygnox-ascii-ansi.txt",
            ROOT / "branding/docs/STYLE_GUIDE.md",
        )
        for path in required:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)
