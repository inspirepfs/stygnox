"""Installed approved-plan execution binding regression tests."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, planning, provider_codex, transactions  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Plan Execution Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "baseline")


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev5")


def active_reviewed(repo: Path, external: Path) -> None:
    resolved = identity(external)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(
            repo,
            "Operator One",
            provider="codex",
            model="gpt-test",
            effort="high",
            reviewer="Reviewer One",
        )
        adoption.handoff_adoption(
            repo,
            "Operator One",
            preview["preview_sha256"],
            "HANDOFF",
            provider="codex",
            model="gpt-test",
            effort="high",
            reviewer="Reviewer One",
        )
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


def proposal_result() -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "read-only",
        "payload": {
            "steps": [
                {
                    "id": 1,
                    "title": "Implement bounded change",
                    "objective": "Implement the exact approved first step",
                    "acceptance": ["The exact first step is implemented", "Regression evidence is retained"],
                    "test_change_policy": "add-only",
                }
            ],
            "files_inspected": ["README.md"],
        },
        "metrics": {
            "commands_executed": 1,
            "input_tokens": 10,
            "cached_input_tokens": 5,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "codex_seconds": 0.1,
        },
    }


def approved_plan(repo: Path) -> dict:
    preview = planning.build_proposal_preview(
        repo,
        "Operator One",
        "Restore plan-bound execution",
        "write",
        min_steps=1,
        max_steps=1,
    )
    with mock.patch.object(provider_codex, "execute_structured", return_value=proposal_result()):
        candidate = planning.propose_plan(
            repo,
            "Operator One",
            "Restore plan-bound execution",
            "write",
            preview["preview_sha256"],
            "PROPOSE",
            min_steps=1,
            max_steps=1,
        )
    return planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")


def implementation_result() -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "workspace-write",
        "status": "PASS",
        "summary": "bounded step complete",
        "metrics": {
            "commands_executed": 1,
            "input_tokens": 20,
            "cached_input_tokens": 10,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "codex_seconds": 0.2,
            "files_inspected": 1,
        },
    }


class StygnoxPlanExecutionBindingTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_awaiting_candidate_blocks_direct_controller_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            preview = planning.build_proposal_preview(repo, "Operator One", "Plan me", "write", min_steps=1, max_steps=1)
            with mock.patch.object(provider_codex, "execute_structured", return_value=proposal_result()):
                planning.propose_plan(
                    repo, "Operator One", "Plan me", "write", preview["preview_sha256"], "PROPOSE", min_steps=1, max_steps=1
                )
            with self.assertRaisesRegex(controller.ControllerError, "awaiting approval"):
                controller.build_run_preview(repo, "Operator One", "arbitrary bypass", "write")

    def test_approved_plan_binds_exact_current_step_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approved_plan(repo)
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")
            binding = preview["plan_binding"]
            self.assertEqual(approved["plan_hash"], binding["plan_hash"])
            self.assertEqual(approved["record_sha256"], binding["plan_record_sha256"])
            self.assertEqual(1, binding["current_step"])
            self.assertEqual(1, binding["total_steps"])
            self.assertEqual("add-only", binding["test_change_policy"])
            self.assertEqual(approved["plan"]["steps"][0]["acceptance"], binding["acceptance"])
            with self.assertRaisesRegex(controller.ControllerError, "exactly match the current approved plan step"):
                controller.build_run_preview(repo, "Operator One", "different objective", "write")
            with self.assertRaisesRegex(controller.ControllerError, "exactly match the approved plan authority"):
                controller.build_run_preview(repo, "Operator One", objective, "read-only")

    def test_plan_bound_turn_records_binding_and_does_not_advance_step(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approved_plan(repo)
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")
            with mock.patch.object(provider_codex, "execute", return_value=implementation_result()) as execute:
                result = controller.run_controller(
                    repo,
                    "Operator One",
                    objective,
                    "write",
                    preview["preview_sha256"],
                    "RUN",
                )
            state = planning.plan_status(repo)["plan"]
            self.assertEqual(preview["plan_binding"], result["plan_binding"])
            self.assertEqual(approved["plan_hash"], result["plan_binding"]["plan_hash"])
            self.assertEqual(1, state["current_step"])
            self.assertEqual("APPROVED", state["status"])
            prompt = execute.call_args.kwargs["prompt"]
            self.assertIn(f"approved plan {approved['plan_hash']}", prompt)
            self.assertIn("step 1 of 1", prompt)
            self.assertIn("test-change policy is add-only", prompt)
            self.assertIn("Regression evidence is retained", prompt)

    def test_approved_plan_refuses_execution_after_baseline_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approved_plan(repo)
            objective = approved["plan"]["steps"][0]["objective"]
            (repo / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(controller.ControllerError, "baseline changed"):
                controller.build_run_preview(repo, "Operator One", objective, "write")

    def test_direct_one_turn_controller_remains_available_without_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            preview = controller.build_run_preview(repo, "Operator One", "Direct inspection", "read-only")
            self.assertIsNone(preview["plan_binding"])
            self.assertEqual("Direct inspection", preview["objective"])


if __name__ == "__main__":
    import unittest
    unittest.main()
