from __future__ import annotations

import argparse
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RALPH_PATH = ROOT / "scripts" / "ralph.py"


def load_ralph():
    spec = importlib.util.spec_from_file_location("ralph_scoped_terminal_provenance_v2", RALPH_PATH)
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
            ".ralph/policy.md": "# policy\n",
        }.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
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


def approved_state() -> tuple[dict, dict]:
    plan = {
        "schema": "zen_ralph_plan_v2",
        "repository_mutation_scope": ["app.py"],
        "goal": "Bind terminal provenance to the scoped checkpoint delta.",
        "repository_authority": "write",
        "planning": {"min_steps": 1, "max_steps": 1},
        "steps": [{
            "id": 1,
            "title": "Bind terminal provenance",
            "objective": "Prove the current scoped delta.",
            "acceptance": ["Terminal provenance is current and scoped."],
            "test_change_policy": "modify",
        }],
    }
    state = ralph.default_state()
    state.update({"status": "APPROVED", "plan": plan, "plan_hash": ralph.plan_hash(plan), "current_step": 1})
    ralph.PLAN.write_text(ralph.render_plan(plan), encoding="utf-8")
    ralph.bind_approved_plan_artifact(state)
    checkpoint = ralph.create_recovery_checkpoint(state)
    state["recovery_checkpoint"] = checkpoint["id"]
    state["approval_repository_evidence"] = checkpoint["repository_evidence"]
    ralph.save_state(state)
    return state, plan["steps"][0]


def accept_current_app_delta(state: dict) -> dict:
    path = "app.py"
    verification = {
        "schema": "zen_ralph_post_turn_repository_verification_v1",
        "state": "PASS",
        "sandbox": "workspace-write",
        "checkpoint": state["recovery_checkpoint"],
        "plan_hash": state["plan_hash"],
        "new_project_delta": [path],
        "changed_approval_residue": [],
        "current_fingerprints": {path: ralph.retirement_path_fingerprint(path)},
        "loop": 1,
        "step": 1,
    }
    attribution = ralph.verified_attribution_result(
        state, state["plan"]["steps"][0], verification, [path], loop=1, phase="implement",
    )
    ralph.record_accepted_operations(state, attribution)
    return ralph.strict_native_provenance(state, "test setup", require_current_delta=True, require_write=True)


class ScopedTerminalProvenanceV2Tests(unittest.TestCase):
    def test_ready_to_commit_refuses_an_out_of_scope_current_delta(self):
        with RepoHarness() as repo:
            state, _step = approved_state()
            (repo.root / "app.py").write_text("value = 2\n", encoding="utf-8")
            accept_current_app_delta(state)
            (repo.root / "outside.py").write_text("outside = True\n", encoding="utf-8")

            with mock.patch.object(ralph, "run_final_qualification", return_value=(True, ["unit=PASS"], {}, "")):
                self.assertEqual(2, ralph.finalize_completed_plan(state))

            blocked = ralph.load_state()
            self.assertEqual("BLOCKED_HUMAN", blocked["status"])
            self.assertIn("CHECKPOINT_REPOSITORY_SCOPE_DELTA: ['outside.py']", blocked["block_reason"])

    def test_requalification_refreshes_current_native_and_delta_bindings(self):
        with RepoHarness() as repo:
            state, _step = approved_state()
            (repo.root / "app.py").write_text("value = 2\n", encoding="utf-8")
            current = accept_current_app_delta(state)
            state["status"] = "READY_TO_COMMIT"
            state["final_qualification"] = {
                "state": "PASS", "delta_fingerprint": "0" * 64, "native_provenance_sha256": "1" * 64,
            }
            ralph.save_state(state)

            with (
                mock.patch.object(ralph, "run_final_qualification", return_value=(True, ["unit=PASS"], {}, "")),
                mock.patch.object(ralph, "build_completion_report"),
                mock.patch.object(ralph, "live_write"),
            ):
                self.assertEqual(0, ralph.cmd_requalify(argparse.Namespace(plan_hash=state["plan_hash"])))

            refreshed = ralph.load_state()["final_qualification"]
            self.assertEqual(current["current_sha256"], refreshed["delta_fingerprint"])
            self.assertEqual(current["binding_sha256"], refreshed["native_provenance_sha256"])
            self.assertNotEqual("0" * 64, refreshed["delta_fingerprint"])
            self.assertNotEqual("1" * 64, refreshed["native_provenance_sha256"])

    def test_finalization_preserves_stale_native_provenance_refusal(self):
        with RepoHarness() as repo:
            state, _step = approved_state()
            (repo.root / "app.py").write_text("value = 2\n", encoding="utf-8")
            current = accept_current_app_delta(state)
            state.update({
                "status": "READY_TO_COMMIT",
                "final_qualification": {
                    "state": "PASS",
                    "delta_fingerprint": current["current_sha256"],
                    "native_provenance_sha256": "0" * 64,
                },
            })
            ralph.save_state(state)

            args = argparse.Namespace(plan_hash=state["plan_hash"], commit=False, push=False, message=None)
            with self.assertRaisesRegex(RuntimeError, "native provenance binding is missing, stale, or altered"):
                ralph.cmd_finalize(args)


if __name__ == "__main__":
    unittest.main()
