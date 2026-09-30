from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ralph_reconcile_restored_v2", ROOT / "scripts" / "ralph.py")
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


class RepoHarness:
    PATH_NAMES = (
        "ROOT", "RALPH", "STATE", "PLAN", "IDEAS", "JOURNAL", "POLICY", "LIVE", "CONTEXT",
        "EVENTS", "RECOVERY", "REPORTS", "RETIREMENTS", "USAGE_LEDGER", "USAGE_STATS_RESET",
    )

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {name: getattr(ralph, name) for name in self.PATH_NAMES}

    def __enter__(self):
        def run(*command: str) -> None:
            subprocess.run(command, cwd=self.root, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

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
        for name, filename in {
            "STATE": "state.json", "PLAN": "plan.md", "IDEAS": "ideas.md", "JOURNAL": "journal.md",
            "POLICY": "policy.md", "LIVE": "live.log", "CONTEXT": "context.json", "EVENTS": "events.jsonl",
            "USAGE_LEDGER": "usage-ledger.jsonl", "USAGE_STATS_RESET": "usage-stats-reset.json",
        }.items():
            setattr(ralph, name, ralph.RALPH / filename)
        ralph.RECOVERY = ralph.RALPH / "recovery"
        ralph.REPORTS = ralph.RALPH / "reports"
        ralph.RETIREMENTS = ralph.RALPH / "retirements"
        ralph.init_files()
        return self

    def __exit__(self, *_args):
        for name, value in self.saved.items():
            setattr(ralph, name, value)
        self.tmp.cleanup()


def approved_state() -> tuple[dict, dict]:
    plan = {
        "goal": "Reconcile an already restored operation",
        "repository_authority": "write",
        "steps": [{
            "id": number,
            "title": f"Step {number}",
            "objective": "Exercise native retirement evidence.",
            "acceptance": ["Native evidence remains exact."],
            "test_change_policy": "modify",
        } for number in range(1, 6)],
    }
    state = ralph.default_state()
    state.update({"status": "APPROVED", "plan": plan, "plan_hash": ralph.plan_hash(plan), "current_step": 1})
    ralph.PLAN.write_text(ralph.render_plan(plan), encoding="utf-8")
    ralph.bind_approved_plan_artifact(state)
    checkpoint = ralph.create_recovery_checkpoint(state)
    state["recovery_checkpoint"] = checkpoint["id"]
    state["approval_repository_evidence"] = checkpoint["repository_evidence"]
    return state, checkpoint


def record_app_change(state: dict) -> None:
    (ralph.ROOT / "app.py").write_text("value = 2\n", encoding="utf-8")
    verification = {
        "schema": "zen_ralph_post_turn_repository_verification_v1", "state": "PASS",
        "sandbox": "workspace-write", "checkpoint": state["recovery_checkpoint"], "plan_hash": state["plan_hash"],
        "new_project_delta": ["app.py"], "changed_approval_residue": [], "loop": 1, "step": 1,
        "current_fingerprints": {"app.py": ralph.retirement_path_fingerprint("app.py")},
    }
    attribution = ralph.verified_attribution_result(state, state["plan"]["steps"][0], verification, ["app.py"], loop=1, phase="implement")
    ralph.record_accepted_operations(state, attribution)
    ralph.save_state(state)


def args(state: dict):
    return type("Args", (), {
        "plan_hash": state["plan_hash"], "reason": "operator restored the native change",
        "rollback": True, "carry_forward": False, "preview_sha": None, "confirm": None,
        "reconcile_restored": True,
    })()


class ReconcileRestoredV2Tests(unittest.TestCase):
    def _restored_state(self) -> tuple[dict, dict]:
        state, checkpoint = approved_state()
        record_app_change(state)
        (ralph.ROOT / "app.py").write_text("value = 1\n", encoding="utf-8")
        return state, checkpoint

    def test_exact_no_op_retires_without_restoration_mutations(self):
        with RepoHarness():
            state, checkpoint = self._restored_state()
            before = ralph.repo_snapshot()
            self.assertEqual(0, ralph.cmd_retire_plan(args(state)))
            self.assertEqual(before, ralph.repo_snapshot())
            manifest = ralph.load_retirement_manifest(ralph.load_state()["retired_plans"][-1]["record_id"])
            self.assertEqual("ROLLED_BACK", manifest["disposition"])
            self.assertEqual({"restore": [], "delete": [], "preserved": []}, manifest["operations"])
            self.assertEqual({"disposition": "reconciled", "action": "none", "checkpoint": checkpoint["id"]}, manifest["paths"][0]["restoration"])

    def test_refuses_changed_or_missing_recorded_path(self):
        for mutation in ("changed", "missing"):
            with self.subTest(mutation=mutation), RepoHarness():
                state, _checkpoint = self._restored_state()
                path = ralph.ROOT / "app.py"
                if mutation == "changed":
                    path.write_text("value = changed\n", encoding="utf-8")
                else:
                    path.unlink()
                with self.assertRaisesRegex(RuntimeError, "changed or missing recorded path"):
                    ralph.cmd_retire_plan(args(state))

    def test_refuses_extra_changed_path(self):
        with RepoHarness():
            state, _checkpoint = self._restored_state()
            (ralph.ROOT / "extra.py").write_text("extra = True\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "extra changed path"):
                ralph.cmd_retire_plan(args(state))

    def test_refuses_changed_approval_residue(self):
        with RepoHarness() as repo:
            (repo.root / "residue.py").write_text("value = 'baseline'\n", encoding="utf-8")
            subprocess.run(["git", "add", "residue.py"], cwd=repo.root, check=True)
            subprocess.run(["git", "commit", "-qm", "residue baseline"], cwd=repo.root, check=True)
            (repo.root / "residue.py").write_text("value = 'approval'\n", encoding="utf-8")
            state, _checkpoint = self._restored_state()
            (repo.root / "residue.py").write_text("value = 'changed'\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "changed approval residue"):
                ralph.cmd_retire_plan(args(state))

    def test_refuses_unverified_native_delta(self):
        with RepoHarness():
            state, _checkpoint = self._restored_state()
            state["operation_attributions"][0]["record_sha256"] = "0" * 64
            ralph.save_state(state)
            with self.assertRaisesRegex(RuntimeError, "unverified native delta"):
                ralph.cmd_retire_plan(args(state))


if __name__ == "__main__":
    unittest.main()
