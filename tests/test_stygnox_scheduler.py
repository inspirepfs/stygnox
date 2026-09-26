"""Installed bounded scheduler and interrupted same-step recovery regressions."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, cli, controller, planning, provider_codex, scheduler, transactions  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Scheduler Test")
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


def active_reviewed(repo: Path, external: Path, *, max_loops: int = 3, efficiency_mode: str = "RELAXED") -> None:
    resolved = identity(external)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(
            repo,
            "Operator One",
            provider="codex",
            model="gpt-test",
            effort="high",
            reviewer="Reviewer One",
            max_loops=max_loops,
            efficiency_mode=efficiency_mode,
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
            max_loops=max_loops,
            efficiency_mode=efficiency_mode,
        )
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


def planning_result(*, test_policy: str = "add-only", delegated: bool = False) -> dict:
    objective = "Implement the exact approved scheduler step"
    acceptance = ["The bounded scheduler step is complete"]
    if delegated:
        acceptance.append("If operator runtime evidence is missing, return BLOCKED_HUMAN for human-owned evidence")
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "read-only",
        "payload": {
            "steps": [{
                "id": 1,
                "title": "Bounded scheduler step",
                "objective": objective,
                "acceptance": acceptance,
                "test_change_policy": test_policy,
            }],
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


def approve(repo: Path, *, test_policy: str = "add-only", delegated: bool = False) -> dict:
    preview = planning.build_proposal_preview(
        repo,
        "Operator One",
        "Restore bounded scheduler semantics",
        "write",
        min_steps=1,
        max_steps=1,
    )
    with mock.patch.object(provider_codex, "execute_structured", return_value=planning_result(test_policy=test_policy, delegated=delegated)):
        candidate = planning.propose_plan(
            repo,
            "Operator One",
            "Restore bounded scheduler semantics",
            "write",
            preview["preview_sha256"],
            "PROPOSE",
            min_steps=1,
            max_steps=1,
        )
    return planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")


def implementation_result(
    summary: str,
    *,
    blocker_class: str = "none",
    status: str = "PASS",
    input_tokens: int = 20,
) -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "workspace-write",
        "status": status,
        "summary": summary,
        "blocker_class": blocker_class,
        "blockers": [] if status == "PASS" else [summary],
        "validation_notes": [],
        "files_inspected": ["README.md"],
        "metrics": {
            "commands_executed": 1,
            "input_tokens": input_tokens,
            "cached_input_tokens": 10,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "codex_seconds": 0.2,
            "files_inspected": 1,
        },
    }


class StygnoxSchedulerTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_scheduler_runs_only_explicit_same_step_continuation_and_stops_for_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=3)
            approved = approve(repo)
            calls = 0

            def execute(**kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    (repo / "src").mkdir(exist_ok=True)
                    (repo / "src" / "work.txt").write_text("partial\n", encoding="utf-8")
                    return implementation_result("more bounded work remains", blocker_class="continuation")
                return implementation_result("step work complete")

            preview = scheduler.build_schedule_preview(repo, "Operator One")
            with mock.patch.object(provider_codex, "execute", side_effect=execute):
                result = scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")

            state = planning.plan_status(repo)["plan"]
            self.assertEqual(2, calls)
            self.assertEqual(2, result["loops_completed"])
            self.assertEqual("STOPPED_QUALIFICATION", result["status"])
            self.assertEqual("qualification-required", result["stop_reason"])
            self.assertEqual("APPROVED", state["status"])
            self.assertEqual(1, state["current_step"])
            self.assertEqual(1, len(state["continuation_history"]))
            self.assertEqual(approved["plan_hash"], result["plan_hash"])

    def test_scheduler_honours_max_loops_and_refuses_direct_controller_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=1)
            approved = approve(repo)
            objective = approved["plan"]["steps"][0]["objective"]
            preview = scheduler.build_schedule_preview(repo, "Operator One")
            original_execute = provider_codex.execute

            def execute(**kwargs):
                with self.assertRaisesRegex(controller.ControllerError, "scheduler owns controller execution"):
                    controller.build_run_preview(repo, "Operator One", objective, "write")
                return implementation_result("continue within approved scope", blocker_class="continuation")

            with mock.patch.object(provider_codex, "execute", side_effect=execute):
                result = scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")
            self.assertEqual("PAUSED_MAX_LOOPS", result["status"])
            self.assertEqual(1, result["loops_completed"])
            self.assertEqual("max-loops", result["stop_reason"])
            self.assertIsNotNone(original_execute)

    def test_scheduler_stops_for_efficiency_review_and_human_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=4, efficiency_mode="NORMAL")
            approve(repo)
            preview = scheduler.build_schedule_preview(repo, "Operator One")
            with mock.patch.object(provider_codex, "execute", return_value=implementation_result(
                "continuation requested but resource budget exceeded",
                blocker_class="continuation",
                input_tokens=700_000,
            )):
                result = scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")
            self.assertEqual("STOPPED_EFFICIENCY", result["status"])
            self.assertEqual(1, result["loops_completed"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=4)
            approved = approve(repo, delegated=True)
            preview = scheduler.build_schedule_preview(repo, "Operator One")
            with mock.patch.object(provider_codex, "execute", return_value=implementation_result(
                "BLOCKED_HUMAN: operator runtime evidence required",
                blocker_class="human-decision",
                status="BLOCKED",
            )):
                result = scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")
            plan_state = planning.plan_status(repo)["plan"]
            self.assertEqual("STOPPED_HUMAN_GATE", result["status"])
            self.assertEqual("BLOCKED_HUMAN", plan_state["status"])
            self.assertEqual(approved["plan_hash"], plan_state["active_gate"]["plan_hash"])

    def test_partial_interruption_requires_exact_pending_paths_and_recovers_same_step(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=3)
            approved = approve(repo)
            preview = scheduler.build_schedule_preview(repo, "Operator One")

            def interrupted(**kwargs):
                (repo / "src").mkdir(exist_ok=True)
                (repo / "src" / "partial.py").write_text("partial = True\n", encoding="utf-8")
                raise provider_codex.ProviderError("simulated provider interruption")

            with mock.patch.object(provider_codex, "execute", side_effect=interrupted):
                with self.assertRaisesRegex(scheduler.SchedulerError, "interrupted during controller turn"):
                    scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")
            self.assertEqual("INTERRUPTED", scheduler.scheduler_status(repo)["scheduler"]["status"])
            with self.assertRaisesRegex(scheduler.SchedulerError, "exact pending paths"):
                scheduler.build_recovery_preview(repo, "Operator One", [])
            recovery_preview = scheduler.build_recovery_preview(repo, "Operator One", ["src/partial.py"])
            recovered = scheduler.recover_interrupted(
                repo,
                "Operator One",
                ["src/partial.py"],
                recovery_preview["preview_sha256"],
                "RECOVER",
            )
            plan_state = planning.plan_status(repo)["plan"]
            self.assertEqual("RECOVERED_PARTIAL_TURN", recovered["status"])
            self.assertEqual("APPROVED", plan_state["status"])
            self.assertEqual(1, plan_state["current_step"])
            self.assertEqual(["src/partial.py"], plan_state["interrupted_recoveries"][-1]["pending_paths"])
            objective = approved["plan"]["steps"][0]["objective"]
            turn = controller.build_run_preview(repo, "Operator One", objective, "write")
            self.assertEqual(plan_state["step_authority_baseline_sha256"], turn["project_baseline"]["sha256"])

    def test_interrupted_recovery_does_not_launder_test_policy_violation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=2)
            approve(repo, test_policy="none")
            preview = scheduler.build_schedule_preview(repo, "Operator One")

            def interrupted(**kwargs):
                (repo / "tests").mkdir(exist_ok=True)
                (repo / "tests" / "test_partial.py").write_text("pass\n", encoding="utf-8")
                raise provider_codex.ProviderError("simulated provider interruption")

            with mock.patch.object(provider_codex, "execute", side_effect=interrupted):
                with self.assertRaises(scheduler.SchedulerError):
                    scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")
            with self.assertRaisesRegex(scheduler.SchedulerError, "test_change_policy=none"):
                scheduler.build_recovery_preview(repo, "Operator One", ["tests/test_partial.py"])

    def test_completed_turn_receipt_is_recovered_without_rerunning_provider_and_cli_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external", max_loops=3)
            approved = approve(repo)
            schedule_preview = scheduler.build_schedule_preview(repo, "Operator One")
            objective = approved["plan"]["steps"][0]["objective"]
            context = planning.approved_step_context(repo, "Operator One")
            assert context is not None
            turn = controller.build_run_preview(
                repo,
                "Operator One",
                objective,
                "write",
            )
            manifest = scheduler.repository_manifest(repo)
            runtime = scheduler._write(repo, {
                "schema": scheduler.SCHEDULER_SCHEMA,
                "product_version": "test",
                "status": "TURN_RUNNING",
                "operator": "Operator One",
                "worktree": str(repo),
                "schedule_preview_sha256": schedule_preview["preview_sha256"],
                "plan_hash": approved["plan_hash"],
                "starting_plan_record_sha256": approved["record_sha256"],
                "current_step": 1,
                "transaction_id": turn["transaction_id"],
                "controller_record_sha256": turn["controller_record_sha256"],
                "tracked_config_sha256": turn["tracked_config_sha256"],
                "review_sha256": turn["review_sha256"],
                "max_loops": 3,
                "loops_completed": 0,
                "pid": 99999999,
                "started_at": "2026-09-25T00:00:00+00:00",
                "finished_at": None,
                "stop_reason": None,
                "last_turn": None,
                "turn_history": [],
                "turn_index": 1,
                "turn_preview_sha256": None,
                "turn_plan_record_sha256": context["plan_record_sha256"],
                "turn_before_baseline_sha256": turn["project_baseline"]["sha256"],
                "turn_before_manifest": manifest,
                "turn_before_manifest_sha256": scheduler._digest(manifest),
            })
            # Rebuild the exact turn now that scheduler ownership is active.
            owned_turn = controller.build_run_preview(
                repo,
                "Operator One",
                objective,
                "write",
                _scheduler_authority=schedule_preview["preview_sha256"],
            )
            runtime["turn_preview_sha256"] = owned_turn["preview_sha256"]
            runtime = scheduler._write(repo, runtime)
            with mock.patch.object(provider_codex, "execute", return_value=implementation_result(
                "ordinary continuation finished before scheduler process died",
                blocker_class="continuation",
            )) as execute:
                result = controller.run_controller(
                    repo,
                    "Operator One",
                    objective,
                    "write",
                    owned_turn["preview_sha256"],
                    "RUN",
                    _scheduler_authority=schedule_preview["preview_sha256"],
                )
            self.assertEqual("continue-same-step", result["next_action"])
            self.assertEqual(1, execute.call_count)
            with mock.patch.object(scheduler, "_pid_active", return_value=False):
                recovery_preview = scheduler.build_recovery_preview(repo, "Operator One", [])
                recovered = scheduler.recover_interrupted(
                    repo,
                    "Operator One",
                    [],
                    recovery_preview["preview_sha256"],
                    "RECOVER",
                )
            self.assertEqual("RECOVERED_COMPLETED_CONTINUATION", recovered["status"])
            self.assertEqual(1, execute.call_count)

        with mock.patch.object(scheduler, "cli_main", return_value=0) as route:
            self.assertEqual(0, cli.main(["scheduler", "status"]))
            route.assert_called_once_with(["status"])


if __name__ == "__main__":
    import unittest
    unittest.main()
