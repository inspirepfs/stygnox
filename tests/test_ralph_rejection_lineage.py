from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SOURCE_ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_rejection_lineage", MODULE_PATH)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


class RepoHarness:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous_root = ralph.ROOT

    def __enter__(self) -> "RepoHarness":
        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=self.root, check=True, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )

        git("init", "-q")
        git("config", "user.email", "ralph@example.invalid")
        git("config", "user.name", "RALPH Test")
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".ralph").mkdir()
        (self.root / ".ralph" / "policy.md").write_text("# temporary test policy\n", encoding="utf-8")
        git("add", "app.py", ".ralph/policy.md")
        git("commit", "-qm", "baseline")
        ralph.bind_controller_root(self.root)
        ralph.init_files()
        return self

    def __exit__(self, *_args: object) -> None:
        ralph.bind_controller_root(self.previous_root)
        self.temporary.cleanup()


def candidate(name: str, acknowledgements: list[dict] | None = None) -> dict:
    plan = {
        "goal": f"{name} controller behavior",
        "steps": [
            {
                "id": number,
                "title": f"{name} step {number}",
                "objective": f"Exercise {name} step {number}",
                "acceptance": [f"{name} durable outcome {number}"],
                "test_change_policy": "add-only",
            }
            for number in range(1, 6)
        ],
    }
    if acknowledgements is not None:
        plan["rejection_acknowledgements"] = acknowledgements
    return plan


def acknowledgement(record_id: str) -> dict:
    return {
        "rejection_id": record_id,
        "disposition": "addressed",
        "scope": {"plan": True, "steps": [1]},
    }


def proposal_args(goal: str, *, from_rejection: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        goal=goal,
        from_rejection=from_rejection,
        from_retirement=None,
        repository_authority="write",
        min_steps=5,
        max_steps=10,
    )


class RejectionLineageTests(unittest.TestCase):
    def propose(self, name: str, plan: dict, *, from_rejection: str | None = None) -> dict:
        with (
            mock.patch.object(ralph, "query_codex_rate_limits", return_value={}),
            mock.patch.object(ralph, "codex_usage_guard", return_value=("SAFE", [])),
            mock.patch.object(ralph, "run_codex", return_value=plan),
        ):
            self.assertEqual(0, ralph.cmd_propose(proposal_args(f"propose {name}", from_rejection=from_rejection)))
        return ralph.load_state()

    def reject(self, state: dict, reason: str) -> dict:
        self.assertEqual(
            0,
            ralph.cmd_reject(argparse.Namespace(plan_hash=state["plan_hash"], reason=reason)),
        )
        return ralph.load_state()

    def reject_a(self) -> tuple[dict, str]:
        proposed = self.propose("A", candidate("A"))
        reason = "legacy pre-scope/new-schema rejection text:\nretain exactly — α→β"
        return self.reject(proposed, reason), reason

    def test_r1_artifact_preserves_text_and_acknowledgement_gates_approval(self) -> None:
        with RepoHarness():
            rejected, reason = self.reject_a()
            artifact = ralph.STATE.parent / "rejections" / "RJ-00000001.json"
            record = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertEqual("RJ-00000001", record["id"])
            self.assertEqual(reason, record["reason"])
            self.assertIsNone(record["predecessor_rejection_id"])
            self.assertEqual(rejected["active_rejection_id"], record["id"])

            proposed_b = self.propose("B", candidate("B", [acknowledgement(record["id"])]))
            self.assertEqual([record["id"]], proposed_b["plan"]["rejection_lineage"]["rejection_ids"])
            self.assertEqual(record["id"], proposed_b["plan"]["rejection_acknowledgements"][0]["rejection_id"])

            valid_plan = proposed_b["plan"]
            proposed_b["plan"] = {key: value for key, value in valid_plan.items() if key != "rejection_acknowledgements"}
            proposed_b["plan_hash"] = ralph.plan_hash(proposed_b["plan"])
            ralph.PLAN.write_text(ralph.render_plan(proposed_b["plan"]), encoding="utf-8")
            ralph.save_state(proposed_b)
            with self.assertRaisesRegex(RuntimeError, "must acknowledge every inherited rejection"):
                ralph.cmd_approve(argparse.Namespace(plan_hash=proposed_b["plan_hash"]))
            self.assertEqual("AWAITING_APPROVAL", ralph.load_state()["status"])

            proposed_b["plan"] = valid_plan
            proposed_b["plan_hash"] = ralph.plan_hash(valid_plan)
            ralph.PLAN.write_text(ralph.render_plan(valid_plan), encoding="utf-8")
            ralph.save_state(proposed_b)
            self.assertEqual(0, ralph.cmd_approve(argparse.Namespace(plan_hash=proposed_b["plan_hash"])))
            self.assertEqual("APPROVED", ralph.load_state()["status"])

    def test_b_inherits_r1_and_c_inherits_r1_and_r2_after_b_rejection(self) -> None:
        with RepoHarness():
            rejected_a, _ = self.reject_a()
            proposed_b = self.propose("B", candidate("B", [acknowledgement("RJ-00000001")]))
            self.assertEqual(["RJ-00000001"], proposed_b["plan"]["rejection_lineage"]["rejection_ids"])
            rejected_b = self.reject(proposed_b, "B requires an additional durable directive")
            r2 = json.loads((ralph.STATE.parent / "rejections" / "RJ-00000002.json").read_text(encoding="utf-8"))
            self.assertEqual(rejected_a["active_rejection_id"], r2["predecessor_rejection_id"])
            self.assertEqual(rejected_a["active_rejection_id"], r2["replacement_rejection_id"])

            proposed_c = self.propose(
                "C",
                candidate("C", [acknowledgement("RJ-00000001"), acknowledgement("RJ-00000002")]),
            )
            self.assertEqual("RJ-00000002", rejected_b["active_rejection_id"])
            self.assertEqual(["RJ-00000001", "RJ-00000002"], proposed_c["plan"]["rejection_lineage"]["rejection_ids"])
            self.assertEqual(
                ["RJ-00000001", "RJ-00000002"],
                [item["rejection_id"] for item in proposed_c["plan"]["rejection_acknowledgements"]],
            )

    def test_lineage_refuses_tampering_and_explicit_recovery_uses_valid_artifacts(self) -> None:
        with RepoHarness():
            rejected_a, _ = self.reject_a()
            with self.assertRaisesRegex(RuntimeError, "selector does not name an indexed rejection"):
                ralph.resolve_rejection_lineage(rejected_a, "RJ-99999999")
            with self.assertRaisesRegex(RuntimeError, "selector must be a rejection ID"):
                ralph.resolve_rejection_lineage(rejected_a, "not-a-rejection")

            recovered_state = ralph.load_state()
            recovered_state["active_rejection_id"] = "RJ-99999999"
            ralph.save_state(recovered_state)
            with self.assertRaisesRegex(RuntimeError, "selection is malformed"):
                ralph.resolve_rejection_lineage(recovered_state)
            recovered = self.propose(
                "recovered B",
                candidate("recovered B", [acknowledgement("RJ-00000001")]),
                from_rejection="RJ-00000001",
            )
            self.assertEqual("RJ-00000001", recovered["plan"]["rejection_lineage"]["selected_rejection_id"])

        with RepoHarness():
            rejected_a, _ = self.reject_a()
            artifact = ralph.STATE.parent / "rejections" / "RJ-00000001.json"
            forged = json.loads(artifact.read_text(encoding="utf-8"))
            forged["reason"] = "tampered directive"
            artifact.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "integrity digest is malformed or mismatched"):
                ralph.resolve_rejection_lineage(rejected_a)

        with RepoHarness():
            independent_x = self.propose("X", candidate("X"))
            self.assertNotIn("rejection_lineage", independent_x["plan"])
            self.assertNotIn("rejection_acknowledgements", independent_x["plan"])
            self.assertEqual("AWAITING_APPROVAL", independent_x["status"])


if __name__ == "__main__":
    unittest.main()
