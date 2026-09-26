"""Canonical unified operator lifecycle projection regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import sys
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, finalization, operator, planning, provider_codex  # noqa: E402
from tests.test_stygnox_finalization import ready_repo
from tests.test_stygnox_human_control import active_reviewed as gate_active, approve as gate_approve, init_repo as gate_init, open_provider_gate, step
from tests.test_stygnox_qualification import active_reviewed, approve, execute_step, init_repo, qualify
from tests.test_stygnox_scheduler import implementation_result as scheduler_result
from tests.provider_catalog_fixture import test_catalog


class StygnoxOperatorStateTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_unadopted_snapshot_is_passive_and_exposes_canonical_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            before = adoption.capture_baseline(repo).public()["sha256"]
            value = operator.operator_snapshot(repo, server_pid=42)
            after = adoption.capture_baseline(repo).public()["sha256"]
            self.assertEqual(before, after)
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists())
            self.assertEqual(2, value["snapshot_version"])
            self.assertEqual("stygnox_operator_lifecycle_v1", value["lifecycle"]["schema"])
            self.assertEqual("UNADOPTED", value["lifecycle"]["phase"])
            self.assertEqual(["adopt.preview"], [row["action"] for row in value["next_actions"]])
            for section in ("plan", "scheduler", "human_gate", "recovery", "reconciliation", "self_development", "qualification", "finalization", "efficiency", "usage"):
                self.assertIn(section, value["lifecycle"])

    def test_approved_turn_requiring_qualification_projects_exact_next_action_usage_and_efficiency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/work.txt", content="done\n")
            value = operator.operator_snapshot(repo)
            life = value["lifecycle"]
            self.assertEqual("APPROVED", life["phase"])
            self.assertEqual(1, life["progress"]["current_step"])
            self.assertEqual("qualification-required", life["latest_controller_turn"]["next_action"])
            self.assertEqual("PASS", life["efficiency"]["latest"]["status"])
            self.assertGreater(life["usage"]["all_time"]["total_tokens"], 0)
            self.assertEqual(["qualification.preview"], [row["action"] for row in life["next_actions"]])

    def test_blocked_human_gate_projects_gate_and_only_bounded_human_actions(self) -> None:
        delegated = step(1, acceptance=["If runtime evidence is absent, stop at BLOCKED_HUMAN for operator evidence."])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            gate_init(repo)
            gate_active(repo, root / "external")
            approved = gate_approve(repo, [delegated])
            result = open_provider_gate(repo, approved, summary="BLOCKED_HUMAN: operator runtime evidence is required")
            value = operator.operator_snapshot(repo)
            life = value["lifecycle"]
            self.assertEqual("BLOCKED_HUMAN", life["phase"])
            self.assertTrue(life["attention_required"])
            self.assertEqual(result["human_gate"]["gate_id"], life["human_gate"]["gate"]["gate_id"])
            actions = [row["action"] for row in life["next_actions"]]
            self.assertIn("gate.steer-preview", actions)
            self.assertIn("gate.resume-preview", actions)
            self.assertIn("gate.resolve-preview", actions)
            self.assertNotIn("controller.run-preview", actions)

    def test_ready_to_commit_projects_qualification_and_controlled_git_actions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            value = operator.operator_snapshot(repo)
            life = value["lifecycle"]
            self.assertEqual("READY_TO_COMMIT", life["phase"])
            self.assertEqual(1, life["progress"]["completed_steps"])
            self.assertEqual(100, life["progress"]["percent_complete"])
            self.assertTrue(life["qualification"]["qualified_current_repository"])
            self.assertEqual("READY_TO_COMMIT", life["finalization"]["plan_status"])
            self.assertEqual(["finalization.commit-preview", "qualification.requalify-preview", "plan.retire-preview"], [row["action"] for row in life["next_actions"]])

    def test_committed_and_pushed_phases_project_exact_git_closure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td), remote=True)
            cp = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: operator state")
            committed = finalization.commit(repo, "Operator One", approved["plan_hash"], "test: operator state", cp["preview_sha256"], "COMMIT")
            after_commit = operator.operator_snapshot(repo)["lifecycle"]
            self.assertEqual("COMMITTED", after_commit["phase"])
            self.assertEqual(committed["commit_sha"], after_commit["finalization"]["commit_sha"])
            self.assertEqual(["finalization.push-preview"], [row["action"] for row in after_commit["next_actions"]])
            pp = finalization.build_push_preview(repo, "Operator One", approved["plan_hash"])
            finalization.push(repo, "Operator One", approved["plan_hash"], pp["preview_sha256"], "PUSH")
            pushed = operator.operator_snapshot(repo)["lifecycle"]
            self.assertEqual("PUSHED", pushed["phase"])
            self.assertEqual([], pushed["next_actions"])
            self.assertIsNotNone(pushed["finalization"]["push_record"])

    def test_reconciliation_pending_paths_override_execution_as_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "external.txt").write_text("external\n", encoding="utf-8")
            value = operator.operator_snapshot(repo)
            life = value["lifecycle"]
            self.assertIn("external.txt", life["reconciliation"]["pending_paths"])
            self.assertEqual(["reconciliation.inspect"], [row["action"] for row in life["next_actions"]])
            self.assertTrue(any(row["code"] == "RECONCILIATION_REQUIRED" for row in life["blockers"]))

    def test_invalid_plan_evidence_is_exposed_and_grants_no_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            path = repo / adoption.RUNTIME_NAME / planning.PLAN_RECORD
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["current_step"] = 999
            path.write_text(json.dumps(raw), encoding="utf-8")
            value = operator.operator_snapshot(repo)
            life = value["lifecycle"]
            self.assertTrue(life["attention_required"])
            self.assertEqual([], life["next_actions"])
            self.assertTrue(any(row["code"] == "INVALID_EVIDENCE" and row["section"] == "plan" for row in life["blockers"]))


    def test_latest_controller_turn_uses_runtime_record_mtime_not_preview_hash_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            runtime = repo / adoption.RUNTIME_NAME
            runtime.mkdir()
            old_path = runtime / "controller-run-ffffffffffffffff.json"
            new_path = runtime / "controller-run-0000000000000000.json"
            def receipt(preview: str, next_action: str) -> dict:
                return {
                    "schema": "stygnox_controller_run_result_v1",
                    "preview_sha256": preview,
                    "record_sha256": preview[::-1],
                    "next_action": next_action,
                    "project_changed": False,
                    "plan_binding": None,
                    "efficiency": {"status": "PASS"},
                    "change_attribution": {
                        "controller_native_paths": [], "operator_baseline_paths": [],
                        "overlap_unresolved_paths": [], "removed_preexisting_paths": [],
                    },
                }
            old_path.write_text(json.dumps(receipt("f" * 64, "turn-complete")), encoding="utf-8")
            new_path.write_text(json.dumps(receipt("0" * 64, "qualification-required")), encoding="utf-8")
            os.utime(old_path, ns=(1_000_000_000, 1_000_000_000))
            os.utime(new_path, ns=(2_000_000_000, 2_000_000_000))
            life = operator.operator_snapshot(repo)["lifecycle"]
            self.assertEqual("0" * 64, life["latest_controller_turn"]["preview_sha256"] )
            self.assertEqual("qualification-required", life["latest_controller_turn"]["next_action"])

    def test_snapshot_is_transport_neutral_and_does_not_invoke_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/work.txt", content="done\n")
            before = adoption.capture_baseline(repo).public()["sha256"]
            with mock.patch.object(provider_codex, "execute", side_effect=AssertionError("snapshot must not invoke provider")), mock.patch.object(provider_codex, "execute_structured", side_effect=AssertionError("snapshot must not invoke provider")):
                value = operator.operator_snapshot(repo)
            after = adoption.capture_baseline(repo).public()["sha256"]
            self.assertEqual(before, after)
            self.assertEqual("stygnox_operator_lifecycle_v1", value["lifecycle"]["schema"])
