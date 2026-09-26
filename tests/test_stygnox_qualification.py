"""Installed controller-owned qualification and READY_TO_COMMIT regressions."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, cli, controller, human_control, planning, provider_codex, qualification, transactions  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path, *, gate_exit: int = 0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Qualification Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    write_qualification_config(path, gate_exit=gate_exit)
    git(path, "add", "README.md", "stygnox.qualification.toml")
    git(path, "commit", "-q", "-m", "baseline")


def write_qualification_config(path: Path, *, gate_exit: int = 0) -> None:
    (path / "stygnox.qualification.toml").write_text(
        'schema = "stygnox_qualification_config_v1"\n\n'
        '[[gate]]\n'
        'name = "project-tests"\n'
        f'command = ["{sys.executable}", "-c", "raise SystemExit({gate_exit})"]\n'
        'timeout_seconds = 60\n',
        encoding="utf-8",
    )


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev5")


def active_reviewed(repo: Path, external: Path, *, repository_authority: str = "write") -> None:
    resolved = identity(external)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(
            repo, "Operator One", provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One", max_loops=3
        )
        adoption.handoff_adoption(
            repo, "Operator One", preview["preview_sha256"], "HANDOFF",
            provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One", max_loops=3,
        )
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


def plan_payload(steps: int, *, repository_authority: str = "write") -> dict:
    rows = []
    for index in range(1, steps + 1):
        rows.append({
            "id": index,
            "title": f"Step {index}",
            "objective": f"Implement qualification step {index}",
            "acceptance": [f"Step {index} controller-owned qualification passes"],
            "test_change_policy": "add-only",
        })
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "read-only",
        "payload": {"steps": rows, "files_inspected": ["README.md"]},
        "metrics": {
            "commands_executed": 1, "input_tokens": 10, "cached_input_tokens": 5,
            "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 1,
            "codex_seconds": 0.1,
        },
    }


def approve(repo: Path, *, steps: int = 1, repository_authority: str = "write") -> dict:
    proposal = planning.build_proposal_preview(
        repo, "Operator One", "Restore qualification semantics", repository_authority, min_steps=steps, max_steps=steps
    )
    with mock.patch.object(provider_codex, "execute_structured", return_value=plan_payload(steps, repository_authority=repository_authority)):
        candidate = planning.propose_plan(
            repo, "Operator One", "Restore qualification semantics", repository_authority,
            proposal["preview_sha256"], "PROPOSE", min_steps=steps, max_steps=steps,
        )
    return planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")


def implementation_result(summary: str = "step complete") -> dict:
    return {
        "provider": "codex", "model": "gpt-test", "effort": "high", "sandbox": "workspace-write",
        "status": "PASS", "summary": summary, "blocker_class": "none", "blockers": [],
        "validation_notes": [], "files_inspected": ["README.md"],
        "metrics": {
            "commands_executed": 1, "input_tokens": 20, "cached_input_tokens": 10,
            "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 1,
            "codex_seconds": 0.2, "files_inspected": 1,
        },
    }


def execute_step(repo: Path, approved: dict, *, filename: str, content: str) -> dict:
    step = planning.plan_status(repo)["plan"]["current_step"]
    objective = approved["plan"]["steps"][step - 1]["objective"]
    authority = approved["plan"]["repository_authority"]
    preview = controller.build_run_preview(repo, "Operator One", objective, authority)

    def execute(**kwargs):
        if authority == "write":
            target = repo / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return implementation_result()

    with mock.patch.object(provider_codex, "execute", side_effect=execute):
        return controller.run_controller(repo, "Operator One", objective, authority, preview["preview_sha256"], "RUN")


def qualify(repo: Path, plan_hash: str) -> dict:
    preview = qualification.build_preview(repo, "Operator One", plan_hash)
    return qualification.run_qualification(repo, "Operator One", plan_hash, preview["preview_sha256"], "QUALIFY")


class StygnoxQualificationTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_config_preview_is_read_only_and_cli_route_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/work.txt", content="done\n")
            before = adoption.capture_baseline(repo).public()["sha256"]
            preview = qualification.build_preview(repo, "Operator One", approved["plan_hash"])
            after = adoption.capture_baseline(repo).public()["sha256"]
            self.assertEqual(before, after)
            self.assertEqual("final", preview["phase"])
            self.assertEqual("stygnox.qualification.toml", preview["qualification_config_path"])
            self.assertIn("diff-check", [row["name"] for row in preview["gates"]])
            self.assertEqual(0, cli.main(["qualification", "status", "--project", str(repo)]))

    def test_intermediate_step_qualification_advances_only_after_controller_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, steps=2)
            execute_step(repo, approved, filename="src/one.txt", content="one\n")
            result = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("STEP_QUALIFIED", result["result"])
            self.assertEqual("APPROVED", state["status"])
            self.assertEqual(2, state["current_step"])
            self.assertEqual("PASS", state["step_results"][0]["result"])
            self.assertEqual(adoption.capture_baseline(repo).public()["sha256"], state["step_authority_baseline_sha256"])

    def test_final_step_enters_ready_to_commit_with_exact_provenance_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/final.txt", content="final\n")
            result = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("READY_TO_COMMIT", result["result"])
            self.assertEqual("READY_TO_COMMIT", state["status"])
            final = state["final_qualification"]
            self.assertEqual("PASS", final["state"])
            self.assertEqual(["src/final.txt"], final["plan_owned_paths"])
            self.assertRegex(final["qualified_delta_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(adoption.capture_baseline(repo).public()["sha256"], final["repository_baseline_sha256"])
            report = qualification.completion_report(repo, approved["plan_hash"])
            self.assertEqual("READY_TO_COMMIT", report["status"])
            self.assertTrue((repo / ".stygnox" / "completion-report.md").is_file())

    def test_failed_step_qualification_keeps_same_step_open_for_bounded_repair(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo, gate_exit=1)
            active_reviewed(repo, root / "external")
            approved = approve(repo, steps=2)
            execute_step(repo, approved, filename="src/fail.txt", content="needs repair\n")
            result = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("QUALIFICATION_FAILED", result["result"])
            self.assertEqual("APPROVED", state["status"])
            self.assertEqual(1, state["current_step"])
            self.assertEqual([], state["step_results"])
            context = planning.approved_step_context(repo, "Operator One")
            self.assertEqual(1, context["current_step"])
            self.assertIn("qualification failed", context["resume_reason"])

    def test_final_qualification_refuses_unreconciled_external_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/final.txt", content="final\n")
            (repo / "external.txt").write_text("operator surprise\n", encoding="utf-8")
            with self.assertRaisesRegex(qualification.QualificationError, "unresolved repository ownership"):
                qualification.build_preview(repo, "Operator One", approved["plan_hash"])

    def test_stale_preview_and_gate_config_change_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/final.txt", content="final\n")
            preview = qualification.build_preview(repo, "Operator One", approved["plan_hash"])
            write_qualification_config(repo, gate_exit=1)
            with self.assertRaisesRegex(qualification.QualificationError, "unresolved repository ownership|stale"):
                qualification.run_qualification(repo, "Operator One", approved["plan_hash"], preview["preview_sha256"], "QUALIFY")

    def test_requalification_allows_only_previously_qualified_path_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            execute_step(repo, approved, filename="src/final.txt", content="final v1\n")
            qualify(repo, approved["plan_hash"])
            (repo / "src" / "final.txt").write_text("final v2\n", encoding="utf-8")
            preview = qualification.build_requalify_preview(repo, "Operator One", approved["plan_hash"])
            result = qualification.run_qualification(repo, "Operator One", approved["plan_hash"], preview["preview_sha256"], "REQUALIFY", requalify=True)
            self.assertEqual("REQUALIFIED_READY_TO_COMMIT", result["result"])
            first = planning.plan_status(repo)["plan"]["final_qualification"]["qualified_delta_sha256"]
            self.assertRegex(first, r"^[0-9a-f]{64}$")
            (repo / "new-unqualified.txt").write_text("new\n", encoding="utf-8")
            with self.assertRaises(qualification.QualificationError):
                qualification.build_requalify_preview(repo, "Operator One", approved["plan_hash"])

    def test_read_only_plan_finishes_read_only_complete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, repository_authority="read-only")
            execute_step(repo, approved, filename="ignored.txt", content="ignored\n")
            result = qualify(repo, approved["plan_hash"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("READ_ONLY_COMPLETE", result["result"])
            self.assertEqual("READ_ONLY_COMPLETE", state["status"])
            self.assertEqual([], state["final_qualification"]["plan_owned_paths"])

    def test_human_confirmed_last_step_can_enter_terminal_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            # Use one delegated human-owned acceptance step.
            proposal = planning.build_proposal_preview(repo, "Operator One", "Human terminal", "write", min_steps=1, max_steps=1)
            payload = plan_payload(1)
            payload["payload"]["steps"][0]["acceptance"].append("If operator runtime evidence is missing, return BLOCKED_HUMAN for human-owned evidence")
            with mock.patch.object(provider_codex, "execute_structured", return_value=payload):
                candidate = planning.propose_plan(repo, "Operator One", "Human terminal", "write", proposal["preview_sha256"], "PROPOSE", min_steps=1, max_steps=1)
            approved = planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")
            objective = approved["plan"]["steps"][0]["objective"]
            turn_preview = controller.build_run_preview(repo, "Operator One", objective, "write")
            blocked = implementation_result("BLOCKED_HUMAN: operator runtime evidence required")
            blocked["status"] = "BLOCKED"
            blocked["blocker_class"] = "human-decision"
            blocked["blockers"] = [blocked["summary"]]
            with mock.patch.object(provider_codex, "execute", return_value=blocked):
                turn = controller.run_controller(repo, "Operator One", objective, "write", turn_preview["preview_sha256"], "RUN")
            gate = turn["human_gate"]
            rprev = human_control.build_resolve_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "operator evidence accepted")
            human_control.resolve(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "operator evidence accepted", rprev["preview_sha256"], "RESOLVE")
            self.assertEqual("STEPS_COMPLETE", planning.plan_status(repo)["plan"]["status"])
            final = qualify(repo, approved["plan_hash"])
            self.assertEqual("READY_TO_COMMIT", final["result"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("HUMAN_CONFIRMED", state["step_results"][0]["result"])


if __name__ == "__main__":
    import unittest
    unittest.main()
