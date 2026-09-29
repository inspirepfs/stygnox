from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SOURCE_ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_rejection_recovery", MODULE_PATH)
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


class RejectionRecoveryTests(unittest.TestCase):
    def propose(self, name: str, plan: dict, *, from_rejection: str | None = None) -> dict:
        with (
            mock.patch.object(ralph, "query_codex_rate_limits", return_value={}),
            mock.patch.object(ralph, "codex_usage_guard", return_value=("SAFE", [])),
            mock.patch.object(ralph, "run_codex", return_value=plan),
        ):
            self.assertEqual(0, ralph.cmd_propose(proposal_args(name, from_rejection=from_rejection)))
        return ralph.load_state()

    def reject(self, state: dict, reason: str) -> dict:
        self.assertEqual(
            0,
            ralph.cmd_reject(argparse.Namespace(plan_hash=state["plan_hash"], reason=reason)),
        )
        return ralph.load_state()

    def reject_a(self) -> tuple[dict, str]:
        proposed = self.propose("propose A", candidate("A"))
        return self.reject(proposed, "A requires durable replacement coverage"), proposed["plan_hash"]

    def test_validate_replacement_acknowledgements_enforces_cases_provider_cannot(self) -> None:
        with RepoHarness():
            rejected_a, _ = self.reject_a()
            proposed_b = self.propose(
                "propose B",
                candidate("B", [acknowledgement("RJ-00000001")]),
            )
            rejected_b = self.reject(proposed_b, "B adds a second durable directive")
            valid = candidate(
                "C",
                [acknowledgement("RJ-00000001"), acknowledgement("RJ-00000002")],
            )
            valid["rejection_lineage"] = ralph.rejection_lineage_binding(
                ralph.resolve_rejection_lineage(rejected_b)
            )
            acknowledgement_schema = ralph.build_proposal_schema(
                5, 10, rejection_ids=valid["rejection_lineage"]["rejection_ids"]
            )["properties"]["rejection_acknowledgements"]
            self.assertNotIn("uniqueItems", acknowledgement_schema)
            self.assertNotIn("uniqueItems", acknowledgement_schema["items"]["properties"]["scope"]["properties"]["steps"])

            cases: list[tuple[str, str, callable]] = [
                ("duplicate acknowledgement scope step", "scope is invalid", lambda plan: plan["rejection_acknowledgements"][0]["scope"].update(steps=[1, 1])),
                ("duplicate rejection ID", "duplicate or foreign", lambda plan: plan["rejection_acknowledgements"][1].update(rejection_id="RJ-00000001")),
                ("foreign rejection ID", "duplicate or foreign", lambda plan: plan["rejection_acknowledgements"][1].update(rejection_id="RJ-99999999")),
                ("invalid disposition", "disposition is invalid", lambda plan: plan["rejection_acknowledgements"][0].update(disposition="ignored")),
                ("missing acknowledgement", "must acknowledge every inherited rejection", lambda plan: plan["rejection_acknowledgements"].pop()),
                ("non-existent step", "scope is invalid", lambda plan: plan["rejection_acknowledgements"][0]["scope"].update(steps=[99])),
                ("meaningless scope", "scope is invalid", lambda plan: plan["rejection_acknowledgements"][0]["scope"].update(plan=False, steps=[])),
                ("stale binding", "binding is stale or altered", lambda plan: plan["rejection_lineage"].update(lineage_digest="0" * 64)),
            ]
            for label, error, mutate in cases:
                with self.subTest(label=label):
                    invalid = copy.deepcopy(valid)
                    mutate(invalid)
                    with self.assertRaisesRegex(RuntimeError, error):
                        ralph.validate_replacement_acknowledgements(rejected_b, invalid)

            self.assertEqual("RJ-00000001", rejected_a["active_rejection_id"])

    def test_failed_replacement_generation_keeps_r1_and_idle_recovery_state(self) -> None:
        with RepoHarness():
            rejected, rejected_hash = self.reject_a()
            record_id = rejected["active_rejection_id"]
            artifact = ralph.STATE.parent / "rejections" / f"{record_id}.json"
            artifact_bytes = artifact.read_bytes()
            indexed_digest = rejected["rejection_lineage_index"]["records"][0]["digest"]

            with (
                mock.patch.object(ralph, "query_codex_rate_limits", return_value={}),
                mock.patch.object(ralph, "codex_usage_guard", return_value=("SAFE", [])),
                mock.patch.object(ralph, "run_codex", side_effect=RuntimeError("injected replacement generation failure")),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected replacement generation failure"):
                    ralph.cmd_propose(proposal_args("failed replacement", from_rejection=rejected_hash))

            recovered = ralph.load_state()
            self.assertEqual("IDLE", recovered["status"])
            self.assertIsNone(recovered["plan"])
            self.assertIsNone(recovered["plan_hash"])
            self.assertEqual(record_id, recovered["active_rejection_id"])
            self.assertEqual(artifact_bytes, artifact.read_bytes())
            self.assertEqual(indexed_digest, recovered["rejection_lineage_index"]["records"][0]["digest"])
            self.assertEqual(record_id, ralph.resolve_rejection_lineage(recovered)["active_rejection_id"])

            replacement = self.propose(
                "retry selected by RJ ID",
                candidate("replacement", [acknowledgement(record_id)]),
                from_rejection=record_id,
            )
            self.assertEqual([record_id], replacement["plan"]["rejection_lineage"]["rejection_ids"])
            self.assertEqual(record_id, replacement["plan"]["rejection_acknowledgements"][0]["rejection_id"])

    def test_rejected_plan_hash_selector_can_retry_against_the_same_r1(self) -> None:
        with RepoHarness():
            rejected, rejected_hash = self.reject_a()
            record_id = rejected["active_rejection_id"]
            replacement = self.propose(
                "retry selected by rejected SHA",
                candidate("replacement", [acknowledgement(record_id)]),
                from_rejection=rejected_hash,
            )
            self.assertEqual(record_id, replacement["plan"]["rejection_lineage"]["selected_rejection_id"])
            self.assertEqual(record_id, replacement["plan"]["rejection_acknowledgements"][0]["rejection_id"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
