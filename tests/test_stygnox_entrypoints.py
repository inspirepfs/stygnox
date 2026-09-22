from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


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
    def test_cli_loads_and_delegates_with_process_arguments_unchanged(self):
        entrypoint = load_entrypoint("stygnox_cli.py")
        delegate = mock.Mock(return_value=17)
        observed_argv: list[str] = []
        delegate.side_effect = lambda: observed_argv.extend(sys.argv) or 17

        with mock.patch.dict(sys.modules, {"ralph": SimpleNamespace(main=delegate)}), mock.patch.object(
            sys, "argv", ["stygnox_cli.py", "status", "--json"]
        ):
            self.assertEqual(17, entrypoint.main())

        delegate.assert_called_once_with()
        self.assertEqual(["stygnox_cli.py", "status", "--json"], observed_argv)

    def test_web_loads_and_forwards_arguments(self):
        entrypoint = load_entrypoint("stygnox_web.py")
        delegate = mock.Mock(return_value=19)

        with mock.patch.dict(sys.modules, {"ralph_web": SimpleNamespace(main=delegate)}), mock.patch.object(
            sys, "argv", ["stygnox_web.py", "--host", "127.0.0.1", "--port", "8765", "--allow-lan"]
        ):
            self.assertEqual(19, entrypoint.main())

        delegate.assert_called_once_with(["--host", "127.0.0.1", "--port", "8765", "--allow-lan"])

    def test_script_execution_uses_delegate_exit_code(self):
        delegate = mock.Mock(return_value=23)

        with mock.patch.dict(sys.modules, {"ralph": SimpleNamespace(main=delegate)}):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(SCRIPTS / "stygnox_cli.py"), run_name="__main__")

        self.assertEqual(23, raised.exception.code)
        delegate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
