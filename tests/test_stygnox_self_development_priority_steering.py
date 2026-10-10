import unittest
from pathlib import Path
from unittest.mock import patch

from stygnox import controller, self_development as sd


class PrioritySteeringTests(unittest.TestCase):
    def test_grant_priority_reaches_controller_prompt_without_expanding_scope(self):
        paths = [
            "src/stygnox/transactions.py",
            "tests/test_stygnox_transaction_renewal.py",
        ]
        priority = (
            "Implement executable read-only transaction renew-preview "
            "before adding any further standalone validation helpers."
        )

        preview = {
            "worktree": "/tmp/stygnox-priority-test",
            "preview_sha256": "b" * 64,
            "gate_sha256": "a" * 64,
            "gate_id": "HG-0007-02",
            "plan_hash": "c" * 64,
            "step": 2,
            "operator": "pfsykes",
            "transaction_id": "TX-test",
            "controller_record_sha256": "d" * 64,
            "tracked_config_sha256": "e" * 64,
            "review_sha256": None,
            "authority_baseline_sha256": "f" * 64,
            "repository_mutation_scope": paths,
            "repository_mutation_scope_sha256": "a" * 64,
            "paths": paths,
            "candidates": [],
            "reason": priority,
        }

        state = {
            "active_gate": {"gate_sha256": "a" * 64},
            "self_development_grant_history": [],
            "human_gate_history": [],
        }

        with (
            patch.object(sd, "build_authorize_preview", return_value=preview),
            patch.object(sd.planning, "_record", return_value=state),
            patch.object(
                sd.human_control,
                "_validate_gate_object",
                return_value={"gate_sha256": "a" * 64},
            ),
            patch.object(
                sd.planning,
                "_write",
                return_value={"record_sha256": "d" * 64},
            ) as writer,
            patch.object(sd.adoption, "write_runtime_record"),
        ):
            receipt = sd.authorize(
                Path("/tmp/stygnox-priority-test"),
                "pfsykes",
                preview["plan_hash"],
                preview["gate_id"],
                paths,
                priority,
                preview["preview_sha256"],
                "AUTHORIZE",
            )

        self.assertEqual(
            receipt["result"], "SELF_DEVELOPMENT_AUTHORIZED"
        )

        saved = writer.call_args.args[1]

        self.assertEqual(saved["status"], "APPROVED")
        self.assertEqual(
            saved["self_development_grant"]["paths"], paths
        )
        self.assertEqual(
            saved["self_development_grant"]["repository_mutation_scope"],
            paths,
        )
        self.assertIn(priority, saved["step_resume"]["direction"])

        binding = {
            "plan_hash": preview["plan_hash"],
            "current_step": 2,
            "total_steps": 4,
            "step_title": "Native renewal",
            "acceptance": [],
            "test_change_policy": "add-only",
            "repository_mutation_scope": paths,
            "repository_mutation_scope_sha256": "a" * 64,
            "human_direction": saved["step_resume"]["direction"],
            "self_development_grant": saved["self_development_grant"],
        }

        prompt = controller._prompt({
            "repository_authority": "write",
            "execution_controls": {},
            "plan_binding": binding,
            "objective": "Implement native transaction renewal",
        })

        self.assertIn(priority, prompt)
        self.assertIn(
            "Bounded human direction for this retry:", prompt
        )
        self.assertIn(
            "Exact supervised Stygnox self-development paths",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
