"""External-worktree regressions for the installed-native command boundary."""
from __future__ import annotations

import os
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CLI = ROOT / "scripts" / "stygnox_cli.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import cli  # noqa: E402


class ExternalProjectExecutionTests(unittest.TestCase):
    def invoke_wrapper(self, caller: Path, environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments], cwd=caller, env=environment,
            text=True, capture_output=True, check=False,
        )

    def test_clean_source_tree_and_external_worktree_never_become_installed_authority(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            external = workspace / "external-project"
            external.mkdir()
            sentinel = workspace / "decoy-executed"
            (external / "ralph.py").write_text(
                f"from pathlib import Path; Path({str(sentinel)!r}).write_text('captured')\n",
                encoding="utf-8",
            )
            fakebin = workspace / "fakebin"
            fakebin.mkdir()
            fake = fakebin / "stygnox"
            fake.write_text(f"#!/bin/sh\ntouch {str(sentinel)!r}\n", encoding="utf-8")
            fake.chmod(0o755)
            environment = dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ.get("PATH", ""))

            for caller, arguments in (
                (ROOT, ("bootstrap", "--project", str(external))),
                (external, ("controller", "status", "--project", str(external))),
            ):
                with self.subTest(caller=caller, arguments=arguments):
                    result = self.invoke_wrapper(caller, environment, *arguments)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("source-tree wrapper is retired", result.stderr)

            self.assertFalse(sentinel.exists(), "a PATH or target-local decoy captured retired authority")

    def test_installed_native_cli_remains_lifecycle_authority_and_refuses_web(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            target = workspace / "target"
            target.mkdir()
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            installed_bin = workspace / "installed-bin"
            installed_bin.mkdir()
            installed_command = installed_bin / "stygnox"
            installed_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            installed_command.chmod(0o755)
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as refused:
                cli.main(["serve"])
            self.assertEqual(2, refused.exception.code)
            self.assertIn("unknown installed Stygnox command", stderr.getvalue())
            environment = dict(os.environ, PATH=str(installed_bin) + os.pathsep + os.environ.get("PATH", ""))
            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(
                    0,
                    cli.main([
                        "adopt", "preview", "--project", str(target), "--operator", "native-authority",
                    ]),
                )

    def test_retired_wrapper_refuses_web_from_an_external_worktree(self) -> None:
        with TemporaryDirectory() as temporary:
            external = Path(temporary) / "external-project"
            external.mkdir()
            result = self.invoke_wrapper(external, dict(os.environ), "serve", "--project", str(external))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("refuses serve/Web", result.stderr)


if __name__ == "__main__":
    unittest.main()
