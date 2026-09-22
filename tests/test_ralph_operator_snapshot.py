from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_operator_snapshot", MODULE_PATH)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


class OperatorSnapshotTests(unittest.TestCase):
    def test_json_snapshot_is_passive_and_web_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            events_path = root / "events.jsonl"
            live_path = root / "live.log"
            reports = root / "reports"
            recovery = root / "recovery"
            reports.mkdir()
            state = ralph.default_state()
            state.update({
                "status": "BLOCKED_HUMAN",
                "plan_hash": "a" * 64,
                "current_step": 2,
                "loop_count": 7,
                "block_reason": "operator evidence required",
                "plan": {"steps": [{"id": 1}, {"id": 2}]},
                "pending_step_delta_paths": {"step": 2, "paths": ["scripts/ralph.py"]},
            })
            state_path.write_text(json.dumps(state), encoding="utf-8")
            events_path.write_text('{"category": "GATE", "message": "review"}\n', encoding="utf-8")
            live_path.write_text("controller waiting\n", encoding="utf-8")
            (reports / f"{'a' * 16}-summary.json").write_text('{"status": "PASS"}', encoding="utf-8")
            watched = (state_path, events_path, live_path, reports / f"{'a' * 16}-summary.json")
            before = {path: path.read_bytes() for path in watched}
            policy = ralph.efficiency_policy.defaults()

            with (
                mock.patch.object(ralph, "STATE", state_path),
                mock.patch.object(ralph, "EVENTS", events_path),
                mock.patch.object(ralph, "LIVE", live_path),
                mock.patch.object(ralph, "REPORTS", reports),
                mock.patch.object(ralph, "RECOVERY", recovery),
                mock.patch.object(ralph.efficiency_policy, "load_policy", return_value=policy),
                mock.patch.object(ralph, "init_files", side_effect=AssertionError("must not initialize")),
                mock.patch.object(ralph, "save_state", side_effect=AssertionError("must not save")) as save,
                mock.patch.object(ralph, "live_write", side_effect=AssertionError("must not write live output")),
                mock.patch.object(ralph, "plan_control_event", side_effect=AssertionError("must not write events")),
                mock.patch.object(ralph, "_register_controller_runtime", side_effect=AssertionError("must not register runtime")),
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), mock.patch.object(
                    ralph.sys, "argv", ["ralph.py", "operator-snapshot", "--json"]
                ):
                    self.assertEqual(0, ralph.main())

            snapshot = json.loads(output.getvalue())
            self.assertEqual("stygnox_operator_snapshot_v1", snapshot["schema"])
            self.assertEqual(1, snapshot["version"])
            self.assertEqual("BLOCKED_HUMAN", snapshot["controller"]["status"])
            self.assertEqual(["scripts/ralph.py"], snapshot["pending_paths"])
            self.assertEqual("HG-0007-02", snapshot["gate"]["id"])
            self.assertEqual({"status": "PASS"}, snapshot["report"]["completion"])
            self.assertEqual([{"category": "GATE", "message": "review"}], snapshot["events"])
            self.assertEqual(["controller waiting"], snapshot["live_output"])
            self.assertFalse(save.called)
            self.assertEqual(before, {path: path.read_bytes() for path in watched})
            self.assertNotIn("ralph_web", ralph.__dict__)
            self.assertNotIn("ralph_web", ralph.cmd_operator_snapshot.__code__.co_names)

    def test_operator_snapshot_requires_json(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ralph.build_parser().parse_args(["operator-snapshot"])
        with self.assertRaisesRegex(RuntimeError, "requires --json"):
            ralph.cmd_operator_snapshot(argparse.Namespace(json=False))


if __name__ == "__main__":
    unittest.main()
