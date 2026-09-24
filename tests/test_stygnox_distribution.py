"""D8.1 package/product identity characterization tests."""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import runpy
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE = SRC / "stygnox"
PYPROJECT = ROOT / "pyproject.toml"
VERSION = runpy.run_path(str(PACKAGE / "_version.py"))["__version__"]


class StygnoxDistributionTests(TestCase):
    def test_pyproject_defines_neutral_installed_command_and_dynamic_version(self) -> None:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        self.assertEqual("stygnox", project["project"]["name"])
        self.assertEqual(["version"], project["project"]["dynamic"])
        self.assertEqual("stygnox.cli:main", project["project"]["scripts"]["stygnox"])
        self.assertEqual(">=3.11,<3.14", project["project"]["requires-python"])
        self.assertEqual(
            "stygnox._version.__version__",
            project["tool"]["setuptools"]["dynamic"]["version"]["attr"],
        )

    def test_installed_package_has_no_legacy_ralph_import(self) -> None:
        offenders: list[str] = []
        for path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                if any(name == "ralph" or name.startswith("ralph_") or name.startswith("ralph.") for name in names):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], offenders)

    def test_source_package_version_and_help_are_neutral(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        version = subprocess.run(
            [sys.executable, "-m", "stygnox", "--version"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertRegex(version.stdout.strip(), rf"^stygnox {re.escape(VERSION)}$")
        self.assertNotIn("RALPH", version.stdout.upper())
        self.assertNotIn("ZEN CONTROL", version.stdout.upper())

        help_result = subprocess.run(
            [sys.executable, "-m", "stygnox", "--help"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, help_result.returncode, help_result.stderr)
        self.assertIn("Stygnox installed product", help_result.stdout)
        self.assertNotIn("RALPH-Lite", help_result.stdout)

    def test_controller_command_fails_closed_without_importing_decoy_ralph(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d81-decoy-") as temp:
            temp_root = Path(temp)
            sentinel = temp_root / "ralph-imported"
            (temp_root / "ralph.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('imported', encoding='utf-8')\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join((str(SRC), str(temp_root)))
            result = subprocess.run(
                [sys.executable, "-m", "stygnox", "status"],
                cwd=temp_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("not enabled by the D8.4", result.stderr)
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
