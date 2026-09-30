from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_bootstrap_dispatch_module", MODULE_PATH)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


def legacy_plan(schema: str | None = None) -> dict:
    plan = {
        "goal": "Bootstrap approval dispatch",
        "repository_authority": "write",
        "planning": {"min_steps": 1, "max_steps": 1},
        "steps": [{
            "id": 1,
            "title": "Preserve legacy identity",
            "objective": "Dispatch only after approval evidence",
            "acceptance": ["The approved legacy plan executes."],
            "test_change_policy": "add-only",
        }],
    }
    if schema is not None:
        plan["schema"] = schema
    return plan


class RepoHarness:
    PATH_NAMES = (
        "ROOT", "RALPH", "STATE", "PLAN", "IDEAS", "JOURNAL", "POLICY", "LIVE", "CONTEXT",
        "EVENTS", "RECOVERY", "REPORTS", "RETIREMENTS", "USAGE_LEDGER", "USAGE_STATS_RESET",
    )

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {name: getattr(ralph, name) for name in self.PATH_NAMES}
        self.saved_gate_live = ralph.ralph_gate.LIVE

    def __enter__(self):
        def run(*args: str) -> None:
            subprocess.run(args, cwd=self.root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        run("git", "init", "-q")
        run("git", "config", "user.email", "ralph@example.invalid")
        run("git", "config", "user.name", "RALPH Test")
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".ralph").mkdir()
        (self.root / ".ralph" / "policy.md").write_text("# policy\n", encoding="utf-8")
        run("git", "add", "app.py", ".ralph/policy.md")
        run("git", "commit", "-qm", "baseline")
        ralph.bind_controller_root(self.root)
        ralph.init_files()
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.saved.items():
            setattr(ralph, name, value)
        ralph.ralph_gate.LIVE = self.saved_gate_live
        self.tmp.cleanup()


def native_approved_state(schema: str | None = None) -> dict:
    plan = legacy_plan(schema)
    state = ralph.default_state()
    state.update({"status": "APPROVED", "plan": plan, "plan_hash": ralph.plan_hash(plan), "current_step": 1})
    ralph.PLAN.write_text(ralph.render_plan(plan), encoding="utf-8")
    ralph.bind_approved_plan_artifact(state)
    checkpoint = ralph.create_recovery_checkpoint(state)
    state["recovery_checkpoint"] = checkpoint["id"]
    state["approval_repository_evidence"] = checkpoint["repository_evidence"]
    ralph.save_state(state)
    return state


class BootstrapDispatchTests(unittest.TestCase):
    def test_approved_unversioned_legacy_plan_dispatches_as_v1(self):
        with RepoHarness():
            state = native_approved_state()
            checkpoint, version, sandbox = ralph.verified_approved_plan_dispatch(state)
            self.assertEqual(state["recovery_checkpoint"], checkpoint["id"])
            self.assertEqual("v1", version)
            self.assertEqual("workspace-write", sandbox)

    def test_named_v1_and_v2_dispatch_without_v2_only_fields(self):
        with RepoHarness():
            v1 = native_approved_state("zen_ralph_plan_v1")
            self.assertEqual("v1", ralph.verified_approved_plan_dispatch(v1)[1])

            v2 = native_approved_state("zen_ralph_plan_v2")
            self.assertEqual("v2", ralph.verified_approved_plan_dispatch(v2)[1])

    def test_artifact_and_checkpoint_evidence_refuse_before_schema_dispatch(self):
        with RepoHarness():
            state = native_approved_state()
            state["plan"].pop("repository_authority")
            state.pop("approved_plan_artifact")
            with self.assertRaisesRegex(RuntimeError, "artifact binding is missing"):
                ralph.verified_approved_plan_dispatch(state)

        with RepoHarness():
            state = native_approved_state()
            state["plan"].pop("repository_authority")
            state.pop("recovery_checkpoint")
            with self.assertRaisesRegex(RuntimeError, "recovery checkpoint is missing or invalid"):
                ralph.verified_approved_plan_dispatch(state)

        with RepoHarness():
            state = native_approved_state()
            state["plan"].pop("repository_authority")
            ralph.PLAN.write_text("altered approved artifact\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "approved plan file changed"):
                ralph.verified_approved_plan_dispatch(state)

        with RepoHarness():
            state = native_approved_state()
            state["plan"].pop("repository_authority")
            state["approval_repository_evidence"] = {"schema": "inconsistent"}
            with self.assertRaisesRegex(RuntimeError, "does not match the approval checkpoint"):
                ralph.verified_approved_plan_dispatch(state)

    def test_all_execution_and_recovery_paths_share_the_evidence_first_dispatcher(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        for name in (
            "_interrupted_run_recovery_evidence",
            "cmd_run",
            "cmd_recover_self_upgrade",
            "cmd_recover_validation_block",
        ):
            start = source.index(f"def {name}")
            next_def = source.find("\ndef ", start + 1)
            body = source[start: next_def if next_def != -1 else None]
            self.assertIn("verified_approved_plan_dispatch(state)", body)
            self.assertNotIn("validate_complete_plan(state[\"plan\"]", body)


if __name__ == "__main__":
    unittest.main()
