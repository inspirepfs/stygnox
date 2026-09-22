"""Read-only equivalence coverage at the RALPH controller consumer boundary."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from scripts import ralph, ralph_profile, stygnox_project_equivalence, stygnox_zen


class StygnoxControllerAdapterEquivalenceTests(unittest.TestCase):
    """The compatibility facade and direct adapter must look identical to RALPH."""

    def _observe_controller(self, profile: object) -> dict[str, object]:
        original_profile = ralph.PROJECT_PROFILE
        policy = ralph.efficiency_policy.normalize_policy({"normal_prompt_command_budget": 1})
        state = {
            "plan_hash": "c" * 64,
            "human_steering": [],
            "controller_runtime": {"pid": 0, "command": "test", "started_at": "now", "plan_hash": "c" * 64},
        }
        step = {
            "id": 2,
            "title": "Adapter equivalence",
            "objective": "Compare controller consumers without durable state.",
            "acceptance": ["same controller result"],
            "test_change_policy": "add-only",
        }
        with (
            mock.patch.object(ralph, "PROJECT_PROFILE", profile),
            mock.patch.object(ralph.efficiency_policy, "load_policy", return_value=policy),
            mock.patch.object(ralph, "context_handoff", return_value={"last_step": 1, "last_result": "PASS"}),
        ):
            default_state = ralph.default_state()
            default_state.pop("updated_at")
            observed = {
                "state_schema": default_state,
                "runtime_policy": {
                    "runtime_status": ralph.controller_runtime_status(state),
                    "policy_storage": ralph._project_policy_kwargs(),
                    "runtime_path": ralph._is_runtime_authority_path(".ralph/state.json"),
                    "recoverable_validation": ralph.is_recoverable_validation_block("python validation failed"),
                    "nonrecoverable_validation": ralph.is_recoverable_validation_block("credential policy violation"),
                },
                "protected_tooling": {
                    "protected": {path: ralph.is_protected_path(path) for path in ("secrets/value", ".envrc", "app/main.py")},
                    "tooling": {path: ralph.is_tooling_path(path) for path in ("scripts/ralph.py", "tests/test_ralph_lite.py", "app/main.py")},
                },
                "recovery_validation": self._recovery_outcome(ralph.validate_recovery_paths, ["app/main.py"], step),
                "qualification": ralph.qualification_gates(),
                "final_qualification": ralph.final_qualification_gates(),
                "commit_metadata": ralph._default_commit_message({"plan": {"goal": "Controller adapter equivalence"}}),
                "guidance": {
                    "plan": ralph.plan_prompt("Compare facade and adapter"),
                    "step": ralph.step_prompt(state, step, None, 0),
                },
            }
        self.assertIs(
            original_profile,
            ralph.PROJECT_PROFILE,
            "controller PROJECT_PROFILE was not restored after scoped comparison",
        )
        return stygnox_project_equivalence.canonical(observed, root=ralph.ROOT)

    @staticmethod
    def _recovery_outcome(callable_: object, *args: object) -> dict[str, str]:
        try:
            callable_(*args)
        except (RuntimeError, TypeError, ValueError) as exc:
            return {"result": "rejected", "exception": type(exc).__name__, "message": str(exc)}
        return {"result": "accepted"}

    def test_facade_and_direct_adapter_have_equivalent_controller_consumers(self):
        facade = self._observe_controller(ralph_profile.PROJECT_PROFILE)
        adapter = self._observe_controller(stygnox_zen.PROJECT_PROFILE)
        differences = stygnox_project_equivalence.differences(facade, adapter)
        self.assertEqual(
            [],
            differences,
            "RALPH controller consumer mismatch (bounded normalized differences): "
            + json.dumps(differences, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
