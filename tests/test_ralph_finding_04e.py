"""Regression coverage for retirement of current-step pending provenance."""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_finding_04e_module", MODULE_PATH)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


def valid_plan(goal: str) -> dict:
    return {
        "goal": goal,
        "repository_authority": "write",
        "steps": [
            {
                "id": number,
                "title": f"Step {number}",
                "objective": f"Objective {number}",
                "acceptance": [f"Acceptance {number}"],
                "test_change_policy": "modify",
            }
            for number in range(1, 6)
        ],
    }


class RepoHarness:
    """The existing lifecycle suite's isolated Git-repository harness pattern."""

    PATH_NAMES = (
        "ROOT", "RALPH", "STATE", "PLAN", "IDEAS", "JOURNAL", "POLICY", "LIVE", "CONTEXT",
        "EVENTS", "RECOVERY", "REPORTS", "RETIREMENTS", "USAGE_LEDGER", "USAGE_STATS_RESET",
    )

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {name: getattr(ralph, name) for name in self.PATH_NAMES}

    def __enter__(self):
        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                args, cwd=self.root, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, check=True,
            )

        run("git", "init", "-q")
        run("git", "config", "user.email", "ralph@example.invalid")
        run("git", "config", "user.name", "RALPH Test")
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".ralph").mkdir()
        (self.root / ".ralph" / "policy.md").write_text("# policy\n", encoding="utf-8")
        run("git", "add", "app.py", ".ralph/policy.md")
        run("git", "commit", "-qm", "baseline")

        ralph.ROOT = self.root
        ralph.RALPH = self.root / ".ralph"
        ralph.STATE = ralph.RALPH / "state.json"
        ralph.PLAN = ralph.RALPH / "plan.md"
        ralph.IDEAS = ralph.RALPH / "ideas.md"
        ralph.JOURNAL = ralph.RALPH / "journal.md"
        ralph.POLICY = ralph.RALPH / "policy.md"
        ralph.LIVE = ralph.RALPH / "live.log"
        ralph.CONTEXT = ralph.RALPH / "context.json"
        ralph.EVENTS = ralph.RALPH / "events.jsonl"
        ralph.RECOVERY = ralph.RALPH / "recovery"
        ralph.REPORTS = ralph.RALPH / "reports"
        ralph.RETIREMENTS = ralph.RALPH / "retirements"
        ralph.USAGE_LEDGER = ralph.RALPH / "usage-ledger.jsonl"
        ralph.USAGE_STATS_RESET = ralph.RALPH / "usage-stats-reset.json"
        ralph.init_files()
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.saved.items():
            setattr(ralph, name, value)
        self.tmp.cleanup()


class Finding04ELifecycleTests(unittest.TestCase):
    def _plan_a_with_pending_step_three_witness(self, repo: RepoHarness) -> tuple[dict, dict]:
        plan_a = valid_plan("Plan A pending-provenance regression")
        state = ralph.default_state()
        state.update({
            "status": "APPROVED",
            "plan_hash": ralph.plan_hash(plan_a),
            "plan": plan_a,
            "current_step": 1,
        })
        ralph.PLAN.write_text(ralph.render_plan(plan_a), encoding="utf-8")
        ralph.bind_approved_plan_artifact(state)
        checkpoint = ralph.create_recovery_checkpoint(state)
        state["recovery_checkpoint"] = checkpoint["id"]
        state["approval_repository_evidence"] = checkpoint["repository_evidence"]

        state["current_step"] = 3
        state["loop_count"] = 7
        (repo.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        step = plan_a["steps"][2]
        verification = ralph.record_post_turn_repository_verification(
            state, step, "workspace-write", ["app.py"], loop=7,
        )
        self.assertEqual("PASS", verification["state"])
        ralph._persist_pending_recovery_evidence(state, step, verification)
        pending = ralph._persist_pending_current_step_provenance(
            state, step, verification, ["app.py"], loop=7,
        )
        state["pending_step_delta_paths"] = {
            "step": 3, "paths": ["app.py"], "updated_at": ralph.utc_now(),
        }
        state["plan_changed_files"] = ["app.py"]
        state["status"] = "BLOCKED_HUMAN"
        ralph.save_state(state)
        return state, pending

    def _retire_plan_a(self, state: dict) -> dict:
        preview_args = argparse.Namespace(
            plan_hash=state["plan_hash"], reason="Plan B supersedes Plan A",
            rollback=True, carry_forward=False, confirm=None, preview_sha=None,
            reconcile_restored=False,
        )
        self.assertEqual(0, ralph.cmd_retire_plan(preview_args))
        preview = ralph.load_state()["retirement_rollback_preview"]
        self.assertEqual(0, ralph.cmd_retire_plan(argparse.Namespace(
            plan_hash=state["plan_hash"], reason="Plan B supersedes Plan A",
            rollback=True, carry_forward=False, confirm="ROLLBACK",
            preview_sha=preview["sha256"], reconcile_restored=False,
        )))
        return ralph.load_state()

    def _propose_plan_b(self, plan_b: dict) -> dict:
        model_plan = copy.deepcopy(plan_b)
        model_plan.pop("repository_authority")
        with (
            mock.patch.object(ralph, "query_codex_rate_limits", return_value={}),
            mock.patch.object(ralph, "codex_usage_guard", return_value=("SAFE", [])),
            mock.patch.object(ralph, "run_codex", return_value=model_plan),
        ):
            self.assertEqual(0, ralph.cmd_propose(type("Args", (), {
                "goal": plan_b["goal"], "from_retirement": None,
                "repository_authority": "write",
            })()))
        return ralph.load_state()

    def test_retirement_preserves_step_three_witness_before_clearing_transients(self):
        with RepoHarness() as repo:
            plan_a_state, pending = self._plan_a_with_pending_step_three_witness(repo)
            retired = self._retire_plan_a(plan_a_state)

            record_id = retired["retired_plans"][-1]["record_id"]
            manifest_path = ralph.RETIREMENTS / f"{record_id}.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = next(item for item in manifest["paths"] if item["path"] == "app.py")
            attribution = record["attribution"]
            generation = attribution["current_step_pending_generation"]
            self.assertEqual(plan_a_state["plan_hash"], generation["plan_hash"])
            self.assertEqual(pending["generation"], generation["generation"])
            self.assertEqual(3, generation["step"])
            self.assertEqual(
                pending["path_evidence"][0],
                attribution["current_step_pending_path_evidence"],
            )
            self.assertEqual("IDLE", retired["status"])
            self.assertEqual([], retired["pending_current_step_provenance"])
            self.assertEqual([], retired["pending_step_delta_paths"])
            self.assertEqual([], retired["pending_retirement_recovery_evidence"])

    def test_plan_b_approval_clears_foreign_plan_a_witness_and_rejects_active_injection(self):
        with RepoHarness() as repo:
            plan_a_state, plan_a_pending = self._plan_a_with_pending_step_three_witness(repo)
            plan_a_recovery = copy.deepcopy(plan_a_state["pending_retirement_recovery_evidence"])
            retired = self._retire_plan_a(plan_a_state)

            plan_b = valid_plan("Plan B replacement after retirement")
            proposed = self._propose_plan_b(plan_b)
            plan_b_hash = proposed["plan_hash"]
            self.assertEqual("AWAITING_APPROVAL", proposed["status"])
            self.assertEqual(1, proposed["current_step"])
            self.assertEqual([], proposed["pending_current_step_provenance"])
            self.assertEqual([], proposed["pending_step_delta_paths"])
            self.assertEqual([], proposed["pending_retirement_recovery_evidence"])

            # Hostile retirement-era witnesses cannot survive the approval boundary.
            proposed.update({
                "pending_current_step_provenance": copy.deepcopy(plan_a_pending),
                "pending_step_delta_paths": {"step": 3, "paths": ["app.py"]},
                "pending_retirement_recovery_evidence": plan_a_recovery,
            })
            ralph.save_state(proposed)

            self.assertEqual(0, ralph.cmd_approve(argparse.Namespace(plan_hash=plan_b_hash)))
            approved = ralph.load_state()
            self.assertEqual("APPROVED", approved["status"])
            self.assertEqual(1, approved["current_step"])
            self.assertEqual([], approved["pending_current_step_provenance"])
            self.assertEqual([], approved["pending_step_delta_paths"])
            self.assertEqual([], approved["pending_retirement_recovery_evidence"])

            approved["pending_current_step_provenance"] = copy.deepcopy(plan_a_pending)
            with self.assertRaisesRegex(RuntimeError, "does not match active authority"):
                ralph._validated_pending_current_step_provenance(approved, plan_b["steps"][0])
