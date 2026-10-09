"""Regression: a failed qualification gate must not consume a completed controller turn."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, planning, provider_codex, qualification  # noqa: E402
from tests.provider_catalog_fixture import safe_rate_limits, test_catalog  # noqa: E402
from tests.test_stygnox_qualification import (  # noqa: E402
    active_reviewed, approve, execute_step, implementation_result, init_repo, qualify,
)


class QualificationFailureRetryTests(TestCase):
    def setUp(self) -> None:
        p = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(provider_codex, "rate_limits", return_value=safe_rate_limits())
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def gate_fails_n_times(number: int):
        original = qualification._run_gates
        count = 0

        def simulate(root, gates):
            nonlocal count
            count += 1
            if count > number:
                return original(root, gates)
            first = gates[0]
            row = {
                "name": first["name"], "command": list(first["command"]),
                "timeout_seconds": first["timeout_seconds"], "returncode": 1,
                "status": "FAIL", "duration_seconds": 0.0,
                "output": "ModuleNotFoundError: No module named 'pytest'",
            }
            row["result_sha256"] = qualification._digest(row)
            return False, [row]

        return simulate

    def test_failed_gate_can_retry_unchanged_evidence_only_turn(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "installed")
            approved = approve(repo, steps=2)
            objective = approved["plan"]["steps"][0]["objective"]
            turn_preview = controller.build_run_preview(repo, "Operator One", objective, "write")
            with mock.patch.object(provider_codex, "execute", return_value=implementation_result("inspection done")) as provider:
                receipt = controller.run_controller(repo, "Operator One", objective, "write", turn_preview["preview_sha256"], "RUN")
            self.assertEqual("turn-complete", receipt["next_action"])
            self.assertFalse(receipt["project_changed"])
            old_digest = planning.plan_status(repo)["plan"]["record_sha256"]
            before = adoption.capture_baseline(repo).public()["sha256"]
            with mock.patch.object(qualification, "_run_gates", side_effect=self.gate_fails_n_times(1)):
                failed = qualify(repo, approved["plan_hash"])
                self.assertEqual("QUALIFICATION_FAILED", failed["result"])
                self.assertNotEqual(old_digest, planning.plan_status(repo)["plan"]["record_sha256"])
                self.assertEqual(before, adoption.capture_baseline(repo).public()["sha256"])
                passed = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("STEP_QUALIFIED", passed["result"])
            self.assertEqual(2, state["current_step"])
            self.assertEqual(receipt["record_sha256"], state["step_results"][0]["controller_receipt_sha256"])
            self.assertEqual(1, provider.call_count)
            self.assertIsNone(state["last_qualification_failure"])

    def test_mutating_completed_turn_can_retry_twice_without_provider_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "installed")
            approved = approve(repo, steps=2)
            receipt = execute_step(repo, approved, filename="src/one.txt", content="done\n")
            with mock.patch.object(qualification, "_run_gates", side_effect=self.gate_fails_n_times(2)):
                self.assertEqual("QUALIFICATION_FAILED", qualify(repo, approved["plan_hash"])["result"])
                self.assertEqual("QUALIFICATION_FAILED", qualify(repo, approved["plan_hash"])["result"])
                passed = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("STEP_QUALIFIED", passed["result"])
            self.assertEqual(2, state["current_step"])
            self.assertEqual(1, len(state["step_results"]))
            self.assertEqual(receipt["record_sha256"], state["step_results"][0]["controller_receipt_sha256"])

    def test_final_step_retry_reaches_ready_to_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "installed")
            approved = approve(repo)
            receipt = execute_step(repo, approved, filename="src/final.txt", content="final\n")
            with mock.patch.object(qualification, "_run_gates", side_effect=self.gate_fails_n_times(1)):
                self.assertEqual("QUALIFICATION_FAILED", qualify(repo, approved["plan_hash"])["result"])
                passed = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("READY_TO_COMMIT", passed["result"])
            self.assertEqual("READY_TO_COMMIT", state["status"])
            self.assertEqual(receipt["record_sha256"], state["step_results"][0]["controller_receipt_sha256"])

    def test_unrelated_plan_state_rewrite_cannot_resurrect_stale_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "installed")
            approved = approve(repo, steps=2)
            execute_step(repo, approved, filename="src/one.txt", content="done\n")
            with mock.patch.object(qualification, "_run_gates", side_effect=self.gate_fails_n_times(1)):
                qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            amended = dict(state)
            amended["continuation_history"] = [*state.get("continuation_history", []), {"unexpected": "controller rewrite"}]
            planning._write(repo, amended)
            with self.assertRaisesRegex(qualification.QualificationError, "no exact completed controller turn"):
                qualification.build_preview(repo, "Operator One", approved["plan_hash"])

    def test_rewritten_failure_history_is_not_a_retry_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "installed")
            approved = approve(repo, steps=2)
            execute_step(repo, approved, filename="src/one.txt", content="done\n")
            with mock.patch.object(qualification, "_run_gates", side_effect=self.gate_fails_n_times(1)):
                qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            amended = dict(state)
            fake = dict(amended["last_qualification_failure"])
            fake["completed_at"] = "2000-01-01T00:00:00+00:00"
            amended["last_qualification_failure"] = fake
            amended["qualification_history"] = [fake]
            planning._write(repo, amended)
            with self.assertRaisesRegex(qualification.QualificationError, "no exact completed controller turn"):
                qualification.build_preview(repo, "Operator One", approved["plan_hash"])

    def test_repository_drift_still_refuses_qualification_retry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "installed")
            approved = approve(repo, steps=2)
            execute_step(repo, approved, filename="src/one.txt", content="done\n")
            with mock.patch.object(qualification, "_run_gates", side_effect=self.gate_fails_n_times(1)):
                qualify(repo, approved["plan_hash"])
            (repo / "src" / "one.txt").write_text("external edit\n", encoding="utf-8")
            with self.assertRaises(qualification.QualificationError):
                qualification.build_preview(repo, "Operator One", approved["plan_hash"])


if __name__ == "__main__":
    import unittest
    unittest.main()
