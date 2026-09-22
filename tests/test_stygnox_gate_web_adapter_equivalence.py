"""Read-only facade/direct-adapter equivalence at the gate and Web seams."""
from __future__ import annotations

import copy
import html
import json
import subprocess
import unittest
from unittest import mock

from scripts import ralph_gate, ralph_profile, ralph_web, stygnox_project_equivalence, stygnox_zen


class StygnoxGateWebAdapterEquivalenceTests(unittest.TestCase):
    """Keep gate and Web profile consumption equivalent without durable effects."""

    _GATE_STATES = (
        {
            "status": "BLOCKED_HUMAN",
            "plan_hash": "a" * 64,
            "loop_count": 7,
            "current_step": 1,
            "block_reason": "incident diagnostic evidence is required",
            "plan": {"steps": [{"title": "Incident evidence", "acceptance": ["Provide runtime evidence"]}]},
        },
        {
            "status": "BLOCKED_HUMAN",
            "plan_hash": "b" * 64,
            "loop_count": 8,
            "current_step": 1,
            "block_reason": "performance acceptance evidence is incomplete",
            "plan": {"steps": [{"title": "Performance evidence", "acceptance": ["Provide validation evidence"]}]},
        },
        {
            "status": "BLOCKED_HUMAN",
            "plan_hash": "c" * 64,
            "loop_count": 9,
            "current_step": 1,
            "block_reason": "policy violation: protected path",
            "plan": {"steps": [{"title": "Policy review", "test_change_policy": "add-only"}]},
        },
    )

    @staticmethod
    def _controller_snapshot() -> dict[str, object]:
        return {
            "schema": "stygnox_operator_snapshot_v1",
            "version": 1,
            "controller": {"status": "BLOCKED_HUMAN", "plan_hash": "d" * 64, "loop_count": 10, "block_reason": "incident evidence is required"},
            "progress": {"current_step": 1, "total_steps": 1},
            "efficiency_model": {"policy": {"mode": "NORMAL"}, "last_efficiency": {"status": "PASS"}},
            "gate": {"open": True, "id": "HG-0010-01"},
            "recovery": {}, "retirement": {}, "reconciliation": {"state": "not-applicable"},
            "pending_paths": [], "events": [], "live_output": [],
        }

    def _observe_gate(self, profile: object) -> list[dict[str, object]]:
        original = ralph_gate.PROJECT_PROFILE
        with (
            mock.patch.object(ralph_gate, "PROJECT_PROFILE", profile),
            mock.patch.object(ralph_gate.subprocess, "run", side_effect=AssertionError("gate must not invoke Git")) as git_run,
            mock.patch.object(ralph_gate, "_checkpoint", side_effect=AssertionError("gate must not read recovery state")) as checkpoint,
        ):
            observed = []
            for state in self._GATE_STATES:
                gate = ralph_gate.build_gate(copy.deepcopy(state))
                observed.append({
                    "class": gate["class"],
                    "guidance": {
                        "actions": gate["human_actions"],
                        "success": gate["success_criteria"],
                        "forbidden": gate["forbidden_shortcuts"],
                    },
                    "summary": gate["summary"],
                    "sources": gate["sources"],
                    "commands": ralph_gate._command_lines(gate),
                    "gate_output": gate,
                    "rendered": ralph_gate.render_gate(gate, details=True),
                })
            self.assertEqual(
                ["runtime_evidence", "validation_evidence", "policy_review"],
                [item["class"] for item in observed],
            )
            self.assertIn("perf_acceptance.py ../zen-performance.json", "\n".join(observed[1]["guidance"]["actions"]))
            self.assertTrue(all("python3 scripts/ralph.py" in "\n".join(item["commands"]) for item in observed))
            self.assertFalse(git_run.called)
            self.assertFalse(checkpoint.called)
        self.assertIs(original, ralph_gate.PROJECT_PROFILE, "gate PROJECT_PROFILE was not restored after scoped comparison")
        return observed

    def _observe_web(self, profile: object) -> dict[str, object]:
        original = ralph_web.PROJECT_PROFILE
        completed = (
            subprocess.CompletedProcess([], 0, stdout="main\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="origin/main\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=" M app/main.py\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="0123456789abcdef\n", stderr=""),
        )
        with (
            mock.patch.object(ralph_web, "PROJECT_PROFILE", profile),
            mock.patch.object(ralph_web, "controller_snapshot", return_value=self._controller_snapshot()) as controller,
            mock.patch.object(ralph_web, "web_job_status", return_value={"active": False}) as job,
            mock.patch.object(ralph_web, "_git", side_effect=completed) as git,
        ):
            snapshot = ralph_web.snapshot(usage_report={})
            observed = {
                "project": snapshot["project"],
                "git": snapshot["git"],
                "controller_command": ralph_web._controller_command("operator-snapshot", "--json"),
                "login": ralph_web.LOGIN_PAGE.replace("__PROJECT_LOGIN_SUBTITLE__", html.escape(profile.web_login_subtitle)),
                "console": ralph_web.PAGE.replace("__PROJECT_WEB_TITLE__", html.escape(profile.web_title)).replace(
                    "__PROJECT_WEB_CONSOLE_SUBTITLE__", html.escape(profile.web_console_subtitle)
                ),
            }
            self.assertEqual(profile.project_metadata(ralph_web.ROOT), observed["project"])
            self.assertIn(profile.web_login_subtitle, observed["login"])
            self.assertIn(profile.web_title, observed["console"])
            self.assertIn(profile.web_console_subtitle, observed["console"])
            self.assertEqual(1, controller.call_count)
            self.assertEqual(1, job.call_count)
            self.assertEqual(4, git.call_count)
        self.assertIs(original, ralph_web.PROJECT_PROFILE, "Web PROJECT_PROFILE was not restored after scoped comparison")
        return observed

    def test_facade_and_direct_adapter_have_equivalent_gate_and_web_consumers(self):
        facade = {
            "gates": self._observe_gate(ralph_profile.PROJECT_PROFILE),
            "web": self._observe_web(ralph_profile.PROJECT_PROFILE),
        }
        adapter = {
            "gates": self._observe_gate(stygnox_zen.PROJECT_PROFILE),
            "web": self._observe_web(stygnox_zen.PROJECT_PROFILE),
        }
        differences = stygnox_project_equivalence.differences(facade, adapter)
        self.assertEqual(
            [], differences,
            "RALPH gate/Web consumer mismatch (bounded normalized differences): "
            + json.dumps(differences, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
