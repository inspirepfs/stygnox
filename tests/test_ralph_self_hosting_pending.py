from __future__ import annotations

import json
import unittest
from unittest import mock

from test_ralph_lifecycle import (
    RepoHarness,
    RunLoopSandboxVerificationTests,
    ralph,
    valid_plan,
)


class SelfHostingPendingRegressionTests(unittest.TestCase):
    def test_mixed_turn_restores_controller_leaves_sibling_pending_then_accepts_retry(self):
        """A protected controller edit must not absorb a surviving product sibling."""
        with RepoHarness(self) as repo:
            plan = valid_plan()
            plan["repository_authority"] = "write"
            RunLoopSandboxVerificationTests._approved_state(self, plan)

            controller = repo.root / "scripts" / "ralph.py"
            app = repo.root / "app.py"

            def ungranted_turn(*_args, **_kwargs):
                controller.parent.mkdir(parents=True, exist_ok=True)
                controller.write_text("ungranted controller change\n", encoding="utf-8")
                app.write_text("pending product sibling\n", encoding="utf-8")
                return RunLoopSandboxVerificationTests._result()

            with (
                mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
                mock.patch.object(ralph, "run_codex", side_effect=ungranted_turn),
                mock.patch.object(ralph, "run_gates") as gates,
            ):
                self.assertEqual(2, ralph.cmd_run(RunLoopSandboxVerificationTests._args()))

            gates.assert_not_called()
            self.assertFalse(controller.exists())
            blocked = ralph.load_state()
            self.assertEqual("BLOCKED_HUMAN", blocked["status"])
            self.assertEqual(1, blocked["current_step"])
            self.assertEqual([], blocked["operation_attributions"])
            self.assertEqual({"step": 1, "paths": ["app.py"]}, {
                key: blocked["pending_step_delta_paths"][key]
                for key in ("step", "paths")
            })
            candidate = blocked["self_hosting_candidate"]
            self.assertEqual(
                {
                    "plan_hash": blocked["plan_hash"],
                    "step": 1,
                    "gate_id": ralph.gate_id_for_state(blocked),
                    "paths": ["scripts/ralph.py"],
                },
                {key: candidate[key] for key in ("plan_hash", "step", "gate_id", "paths")},
            )

            authorize = type("Args", (), {
                "plan_hash": blocked["plan_hash"],
                "gate": candidate["gate_id"],
                "path": list(candidate["paths"]),
                "reason": "approve the exact derived controller candidate for retry",
            })()
            self.assertEqual(0, ralph.cmd_authorize_self_hosting(authorize))
            granted = ralph.load_state()
            self.assertEqual(["scripts/ralph.py"], granted["self_hosting_grant"]["paths"])
            self.assertEqual(1, granted["self_hosting_grant"]["step"])

            def granted_retry(*_args, **_kwargs):
                controller.write_text("granted controller change\n", encoding="utf-8")
                app.write_text("accepted product sibling\n", encoding="utf-8")
                return RunLoopSandboxVerificationTests._result()

            with (
                mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
                mock.patch.object(ralph, "run_codex", side_effect=granted_retry),
                mock.patch.object(ralph, "codex_requests_continuation", return_value=(False, "")),
                mock.patch.object(ralph, "run_gates", return_value=(True, ["unit-tests=PASS"], None, "", {})) as gates,
            ):
                self.assertEqual(0, ralph.cmd_run(RunLoopSandboxVerificationTests._args()))

            gates.assert_called_once()
            accepted = ralph.load_state()
            self.assertEqual("PASS", accepted["last_post_turn_verification"]["state"])
            self.assertEqual(["app.py", "scripts/ralph.py"], accepted["last_post_turn_verification"]["new_project_delta"])
            self.assertEqual(
                {"app.py", "scripts/ralph.py"},
                {item["path"] for item in accepted["operation_attributions"]},
            )
            self.assertEqual([], accepted["pending_step_delta_paths"])
            self.assertEqual("PASS", accepted["step_results"][-1]["result"])
            self.assertNotIn("UNATTRIBUTED_CHECKPOINT_DELTA", json.dumps(accepted, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
