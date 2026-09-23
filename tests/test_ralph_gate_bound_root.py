from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE = SOURCE_ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_gate_bound_root_controller", MODULE)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)
ralph_gate = sys.modules["ralph_gate"]


class GateHistoryBoundRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = ralph.ROOT

    def tearDown(self) -> None:
        ralph.bind_controller_root(self.original_root)

    def test_history_uses_live_bound_by_production_controller(self) -> None:
        self.assertIs(ralph_gate, ralph.ralph_gate)
        self.assertIsNone(inspect.signature(ralph_gate.gate_history).parameters["path"].default)

        with TemporaryDirectory() as temporary:
            stygnox_root = Path(temporary, "stygnox").resolve()
            external_root = Path(temporary, "external").resolve()
            stygnox_live = self._write_history(stygnox_root, "Stygnox history")
            external_live = self._write_history(external_root, "External history")

            ralph.bind_controller_root(stygnox_root)
            self.assertEqual("Stygnox history", ralph_gate.gate_history()[0]["title"])

            ralph.bind_controller_root(external_root)

            self.assertEqual("External history", ralph_gate.gate_history()[0]["title"])
            self.assertEqual("Stygnox history", ralph_gate.gate_history(stygnox_live)[0]["title"])
            self.assertEqual("External history", ralph_gate.gate_history(external_live)[0]["title"])

    @staticmethod
    def _write_history(root: Path, title: str) -> Path:
        live = ralph.PROJECT_PROFILE.artifact(root, "live")
        live.parent.mkdir(parents=True)
        live.write_text(
            "\n".join(
                (
                    f"[10:00:00] RALPH    loop=0001 step=1/3 phase=implement repair=0 title={title}",
                    "[10:01:00] SUMMARY  BLOCKED_HUMAN: distinct history",
                )
            ),
            encoding="utf-8",
        )
        return live


if __name__ == "__main__":
    unittest.main()
