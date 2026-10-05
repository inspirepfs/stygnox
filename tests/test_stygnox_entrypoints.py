from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_entrypoint(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StygnoxEntrypointTests(unittest.TestCase):
    def test_installed_console_script_is_the_only_supported_command_identity(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual("stygnox.cli:main", project["project"]["scripts"]["stygnox"])

    def test_retired_wrapper_never_delegates_or_mutates_process_arguments(self) -> None:
        entrypoint = load_entrypoint("stygnox_cli.py")
        arguments = ["controller", "status", "--project", "/external/project"]
        with self.assertRaisesRegex(SystemExit, "will not execute commands"):
            entrypoint.main(arguments)
        self.assertEqual(["controller", "status", "--project", "/external/project"], arguments)

    def test_script_execution_emits_only_migration_instruction(self) -> None:
        with self.assertRaisesRegex(SystemExit, "install Stygnox independently"):
            runpy.run_path(str(SCRIPTS / "stygnox_cli.py"), run_name="__main__")


if __name__ == "__main__":
    unittest.main()
