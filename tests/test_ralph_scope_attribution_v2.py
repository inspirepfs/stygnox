from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RALPH_PATH = ROOT / "scripts" / "ralph.py"


def load_ralph():
    spec = importlib.util.spec_from_file_location("ralph_scope_attribution_v2", RALPH_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ralph = load_ralph()


class RepoHarness:
    PATH_NAMES = (
        "ROOT", "RALPH", "STATE", "PLAN", "IDEAS", "JOURNAL", "POLICY", "LIVE", "CONTEXT",
        "EVENTS", "RECOVERY", "REPORTS", "RETIREMENTS", "USAGE_LEDGER", "USAGE_STATS_RESET",
    )

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {name: getattr(ralph, name) for name in self.PATH_NAMES}
        self.saved_gate_live = ralph.ralph_gate.LIVE

        def run(*args: str) -> None:
            subprocess.run(args, cwd=self.root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        run("git", "init", "-q")
        run("git", "config", "user.email", "ralph@example.invalid")
        run("git", "config", "user.name", "RALPH Test")
        for path, content in {
            "app.py": "value = 1\n",
            "scripts/ralph.py": "controller = 'baseline'\n",
            "tests/test_existing.py": "assert True\n",
            ".ralph/policy.md": "# policy\n",
        }.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        run("git", "add", "app.py", "scripts/ralph.py", "tests/test_existing.py", ".ralph/policy.md")
        run("git", "commit", "-qm", "baseline")
        ralph.bind_controller_root(self.root)
        ralph.init_files()
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.saved.items():
            setattr(ralph, name, value)
        ralph.ralph_gate.LIVE = self.saved_gate_live
        self.tmp.cleanup()


def approved_state(scope: list[str]) -> tuple[dict, dict]:
    plan = {
        "schema": "zen_ralph_plan_v2",
        "repository_mutation_scope": scope,
        "goal": "Reject checkpoint deltas before attribution.",
        "repository_authority": "write",
        "planning": {"min_steps": 1, "max_steps": 1},
        "steps": [{
            "id": 1,
            "title": "Enforce scope",
            "objective": "Reject paths outside the approved scope.",
            "acceptance": ["Scope is enforced before attribution."],
            "test_change_policy": "add-only",
        }],
    }
    state = ralph.default_state()
    state.update({"status": "APPROVED", "plan": plan, "plan_hash": ralph.plan_hash(plan), "current_step": 1})
    ralph.PLAN.write_text(ralph.render_plan(plan), encoding="utf-8")
    ralph.bind_approved_plan_artifact(state)
    checkpoint = ralph.create_recovery_checkpoint(state)
    state["recovery_checkpoint"] = checkpoint["id"]
    state["approval_repository_evidence"] = checkpoint["repository_evidence"]
    return state, plan["steps"][0]


class ScopeAttributionV2Tests(unittest.TestCase):
    def test_out_of_scope_checkpoint_delta_refuses_before_recorded_pending_or_attribution_handling(self):
        with RepoHarness() as repo:
            state, step = approved_state(["app.py"])
            # A malformed record would fail if record validation ran first;
            # pending data similarly cannot conceal the live out-of-scope path.
            state["operation_attributions"] = [{"schema": "untrusted"}]
            state["pending_step_delta_paths"] = {"step": 1, "paths": ["outside.py"]}
            (repo.root / "outside.py").write_text("outside = True\n", encoding="utf-8")

            verification = ralph.record_post_turn_repository_verification(
                state, step, "workspace-write", ["outside.py"], loop=1,
            )

            self.assertEqual("REFUSED", verification["state"])
            self.assertEqual("CHECKPOINT_REPOSITORY_SCOPE_DELTA: ['outside.py']", verification["error"])

    def test_scope_membership_does_not_satisfy_add_only_test_policy(self):
        with RepoHarness() as repo:
            state, step = approved_state(["tests/test_existing.py"])
            (repo.root / "tests" / "test_existing.py").write_text("assert False\n", encoding="utf-8")

            verification = ralph.record_post_turn_repository_verification(
                state, step, "workspace-write", ["tests/test_existing.py"], loop=1,
            )

            self.assertEqual("REFUSED", verification["state"])
            self.assertIn("CHECKPOINT_TEST_POLICY_DELTA", verification["error"])
            self.assertIn("tests/test_existing.py", verification["error"])

    def test_self_hosting_grant_cannot_expand_repository_mutation_scope(self):
        with RepoHarness() as repo:
            state, step = approved_state(["app.py"])
            state["self_hosting_grant"] = {
                "plan_hash": state["plan_hash"], "step": 1, "gate_id": "HG-0000-01",
                "paths": ["scripts/ralph.py"],
            }
            (repo.root / "scripts" / "ralph.py").write_text("controller = 'changed'\n", encoding="utf-8")

            verification = ralph.record_post_turn_repository_verification(
                state, step, "workspace-write", ["scripts/ralph.py"], loop=1,
            )

            self.assertEqual("REFUSED", verification["state"])
            self.assertEqual("CHECKPOINT_REPOSITORY_SCOPE_DELTA: ['scripts/ralph.py']", verification["error"])


if __name__ == "__main__":
    unittest.main()
