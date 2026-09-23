from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


MODULE = Path(__file__).resolve().parents[1] / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_controller_project_root", MODULE)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


PATH_GLOBALS = (
    "ROOT", "RALPH", "STATE", "PLAN", "IDEAS", "JOURNAL", "POLICY", "LIVE",
    "CONTEXT", "EVENTS", "RECOVERY", "REPORTS", "RETIREMENTS", "USAGE_LEDGER",
    "USAGE_STATS_RESET",
)


class ControllerProjectRootBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_bindings = {name: getattr(ralph, name) for name in PATH_GLOBALS}
        self.source_paths = (ralph._SCRIPT_DIR, Path(ralph.__file__).resolve())

    def tearDown(self) -> None:
        for name, value in self.original_bindings.items():
            setattr(ralph, name, value)

    def test_rebinds_every_controller_artifact_without_moving_source_paths(self) -> None:
        with TemporaryDirectory() as temporary:
            external_root = Path(temporary).resolve()
            ralph.bind_controller_root(external_root)

            self.assertEqual(external_root, ralph.ROOT)
            self.assertEqual(external_root / ".ralph", ralph.RALPH)
            for name in PATH_GLOBALS[2:]:
                self.assertEqual(
                    ralph.PROJECT_PROFILE.artifact(external_root, name.lower()),
                    getattr(ralph, name),
                )
            self.assertEqual(self.source_paths, (ralph._SCRIPT_DIR, Path(ralph.__file__).resolve()))

    def test_failed_replacement_map_leaves_all_bindings_unchanged(self) -> None:
        profile = mock.Mock(wraps=ralph.PROJECT_PROFILE)
        profile.artifact.side_effect = RuntimeError("artifact failure")

        with mock.patch.object(ralph, "PROJECT_PROFILE", profile):
            with self.assertRaisesRegex(RuntimeError, "artifact failure"):
                ralph.bind_controller_root(Path("/external-root"))

        self.assertEqual(self.original_bindings, {name: getattr(ralph, name) for name in PATH_GLOBALS})
        self.assertEqual(self.source_paths, (ralph._SCRIPT_DIR, Path(ralph.__file__).resolve()))


if __name__ == "__main__":
    unittest.main()
