"""CAP-016 canonical lifecycle TUI parity tests."""
from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import operator, tui  # noqa: E402


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "CAP016 Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=path, check=True)


class StygnoxTuiLifecycleTests(TestCase):
    def test_unadopted_snapshot_renders_canonical_phase_and_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = operator.operator_snapshot(repo)
            rendered = tui.render_snapshot(snapshot, color_mode="never", width=100, stream=io.StringIO())
            self.assertIn("LIFECYCLE", rendered)
            self.assertIn("Phase      UNADOPTED", rendered)
            self.assertIn("NEXT ACTIONS", rendered)
            self.assertIn("adopt.preview", rendered)
            self.assertEqual(snapshot["next_actions"], snapshot["lifecycle"]["next_actions"])

    def test_render_uses_only_canonical_lifecycle_for_phase_blockers_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = operator.operator_snapshot(repo)
            snapshot["lifecycle"] = {
                **snapshot["lifecycle"],
                "phase": "BLOCKED_HUMAN",
                "attention_required": True,
                "progress": {"completed_steps": 2, "total_steps": 5, "percent_complete": 40, "current_step": 3, "current": {"title": "Repair authority"}},
                "blockers": [{"code": "HUMAN_GATE", "gate_id": "HG-0003-03", "detail": "review exact tooling path"}],
                "next_actions": [{"action": "self-development.authorize-preview", "reason": "exact Stygnox tooling paths require supervised authority"}],
                "human_gate": {"available": True, "open": True, "gate": {"gate_id": "HG-0003-03", "kind": "self-development"}},
                "recovery": {"required": False, "transaction_state": "ACTIVE"},
                "reconciliation": {"pending_paths": [], "stale_paths": []},
                "self_development": {"active_grant": None, "grant_history_count": 1},
                "qualification": {"available": True, "plan_status": "BLOCKED_HUMAN", "qualified_current_repository": False},
                "finalization": {"available": True, "plan_status": "BLOCKED_HUMAN", "commit_sha": None},
                "efficiency": {"mode": "normal", "latest": {"status": "PASS"}},
                "usage": {"summary": {"turn_count": 4, "input_tokens": 100, "output_tokens": 20}},
            }
            snapshot["next_actions"] = list(snapshot["lifecycle"]["next_actions"])
            rendered = tui.render_snapshot(snapshot, color_mode="never", width=100, stream=io.StringIO())
            for value in ("BLOCKED_HUMAN", "2/5 · 40%", "HG-0003-03", "HUMAN_GATE", "self-development.authorize-preview", "AUTHORITY & RECOVERY", "QUALIFICATION / FINALIZATION"):
                self.assertIn(value, rendered)

    def test_narrow_render_preserves_lifecycle_blocker_and_action_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = operator.operator_snapshot(repo)
            snapshot["lifecycle"]["phase"] = "READY_TO_COMMIT"
            snapshot["lifecycle"]["blockers"] = [{"code": "REQUALIFICATION_REQUIRED", "detail": "repository changed after qualification"}]
            snapshot["lifecycle"]["attention_required"] = True
            snapshot["lifecycle"]["next_actions"] = [{"action": "qualification.requalify-preview", "reason": "repository changed"}]
            snapshot["next_actions"] = list(snapshot["lifecycle"]["next_actions"])
            rendered = tui.render_snapshot(snapshot, color_mode="never", width=55, stream=io.StringIO())
            self.assertIn("READY_TO_COMMIT", rendered)
            self.assertIn("REQUALIFICATION_REQUIRED", rendered)
            self.assertIn("qualification.requalify-preview", rendered)

    def test_terminal_completion_has_no_invented_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = operator.operator_snapshot(repo)
            snapshot["lifecycle"]["phase"] = "PUSHED"
            snapshot["lifecycle"]["blockers"] = []
            snapshot["lifecycle"]["attention_required"] = False
            snapshot["lifecycle"]["next_actions"] = []
            snapshot["next_actions"] = []
            rendered = tui.render_snapshot(snapshot, color_mode="never", width=100, stream=io.StringIO())
            self.assertIn("Phase      PUSHED", rendered)
            self.assertIn("[NONE] no authority-valid next action", rendered)

    def test_shared_operator_dispatch_routes_all_new_lifecycle_action_families(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            cases = [
                ("plan.propose-preview", "stygnox.planning.build_proposal_preview", {"operator": "Op", "goal": "g", "repository_authority": "write"}),
                ("gate.steer-preview", "stygnox.human_control.build_steer_preview", {"operator": "Op", "plan_hash": "p", "gate_id": "g", "direction": "d"}),
                ("scheduler.run-preview", "stygnox.scheduler.build_schedule_preview", {"operator": "Op"}),
                ("self-development.authorize-preview", "stygnox.self_development.build_authorize_preview", {"operator": "Op", "plan_hash": "p", "gate_id": "g", "paths": ["src/stygnox/x.py"], "reason": "r"}),
                ("qualification.preview", "stygnox.qualification.build_preview", {"operator": "Op", "plan_hash": "p"}),
                ("qualification.requalify-preview", "stygnox.qualification.build_requalify_preview", {"operator": "Op", "plan_hash": "p"}),
                ("finalization.commit-preview", "stygnox.finalization.build_commit_preview", {"operator": "Op", "plan_hash": "p", "message": "m"}),
                ("finalization.push-preview", "stygnox.finalization.build_push_preview", {"operator": "Op", "plan_hash": "p"}),
            ]
            for action, target, payload in cases:
                with self.subTest(action=action), mock.patch(target, return_value={"marker": action}) as called:
                    result = operator.dispatch_action(repo, action, payload)
                    self.assertEqual(action, result["action"])
                    self.assertEqual({"marker": action}, result["result"])
                    called.assert_called_once()

    def test_tui_action_uses_shared_operator_dispatch_not_backend_directly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            with mock.patch("stygnox.tui.operator.dispatch_action", return_value={"schema": "stygnox_operator_action_v1", "action": "qualification.preview", "result": {"ok": True}}) as dispatched:
                out = io.StringIO()
                with mock.patch("sys.stdout", out):
                    code = tui.cli_main(["action", "--project", str(repo), "--name", "qualification.preview", "--payload-json", '{"operator":"Op","plan_hash":"p"}', "--json"])
                self.assertEqual(0, code)
                dispatched.assert_called_once_with(repo, "qualification.preview", {"operator": "Op", "plan_hash": "p"})
                self.assertIn('"qualification.preview"', out.getvalue())


if __name__ == "__main__":
    import unittest
    unittest.main()
