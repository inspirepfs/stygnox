from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, cli, controller, planning, provider_codex, transactions, usage  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Planning Test")
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
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev-plan")


def active_reviewed(repo: Path, external: Path) -> adoption.CommandIdentity:
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
    return resolved


def proposal_payload(count: int) -> dict:
    return {
        "steps": [
            {
                "id": index,
                "title": f"Step {index}",
                "objective": f"Objective {index}",
                "acceptance": [f"Acceptance {index}"],
                "test_change_policy": "add-only" if index == 1 else "none",
            }
            for index in range(1, count + 1)
        ],
        "files_inspected": ["src/example.py", "tests/test_example.py"],
    }


def provider_result(count: int) -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "read-only",
        "payload": proposal_payload(count),
        "metrics": {
            "commands_executed": 2,
            "input_tokens": 100,
            "cached_input_tokens": 60,
            "cache_write_input_tokens": 0,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
            "codex_seconds": 1.25,
        },
    }


class StygnoxPlanningTests(TestCase):
    def test_bounds_preserve_historical_contract(self) -> None:
        self.assertEqual((5, 10), planning.proposal_step_bounds())
        self.assertEqual((2, 7), planning.proposal_step_bounds(2, 7))
        for bounds in ((0, 7), (8, 7), (1, 21)):
            with self.assertRaises(planning.PlanningError):
                planning.proposal_step_bounds(*bounds)

    def test_proposal_preview_is_read_only_and_binds_operator_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            before = adoption.capture_baseline(repo).public()["sha256"]
            preview = planning.build_proposal_preview(
                repo,
                "Operator One",
                "Restore bounded planning",
                "write",
                min_steps=2,
                max_steps=4,
            )
            after = adoption.capture_baseline(repo).public()["sha256"]
        self.assertEqual(before, after)
        self.assertEqual({"min_steps": 2, "max_steps": 4}, preview["planning"])
        self.assertEqual("write", preview["repository_authority"])
        self.assertEqual("read-only", preview["provider_repository_authority"])
        self.assertFalse(preview["execution_authority_granted"])
        self.assertEqual("PROPOSE", preview["confirmation"])

    def test_proposal_creates_exact_candidate_and_records_planning_usage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            preview = planning.build_proposal_preview(
                repo, "Operator One", "Restore planning", "write", min_steps=2, max_steps=4
            )
            with mock.patch.object(provider_codex, "execute_structured", return_value=provider_result(3)) as execute:
                state = planning.propose_plan(
                    repo,
                    "Operator One",
                    "Restore planning",
                    "write",
                    preview["preview_sha256"],
                    "PROPOSE",
                    min_steps=2,
                    max_steps=4,
                )
            rows = usage.usage_rows(repo, include_before_reset=True)
        execute.assert_called_once()
        self.assertEqual("AWAITING_APPROVAL", state["status"])
        self.assertFalse(state["execution_authority_granted"])
        self.assertEqual("Restore planning", state["plan"]["goal"])
        self.assertEqual("write", state["plan"]["repository_authority"])
        self.assertEqual([1, 2, 3], [step["id"] for step in state["plan"]["steps"]])
        self.assertEqual(planning._plan_hash(state["plan"]), state["plan_hash"])
        self.assertEqual(1, len(rows))
        self.assertEqual("planning-proposal", rows[0]["scope"])
        self.assertEqual(2, rows[0]["files_inspected"])

    def test_approval_requires_exact_hash_and_unchanged_authority_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            preview = planning.build_proposal_preview(repo, "Operator One", "Plan it", "write", min_steps=2, max_steps=3)
            with mock.patch.object(provider_codex, "execute_structured", return_value=provider_result(2)):
                candidate = planning.propose_plan(
                    repo, "Operator One", "Plan it", "write", preview["preview_sha256"], "PROPOSE", min_steps=2, max_steps=3
                )
            with self.assertRaisesRegex(planning.PlanningError, "approval hash"):
                planning.approve_plan(repo, "Operator One", "0" * 64, "APPROVE")
            (repo / "README.md").write_text("operator changed baseline\n", encoding="utf-8")
            with self.assertRaisesRegex(planning.PlanningError, "baseline changed"):
                planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")
            (repo / "README.md").write_text("baseline\n", encoding="utf-8")
            approved = planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")
        self.assertEqual("APPROVED", approved["status"])
        self.assertTrue(approved["execution_authority_granted"])
        self.assertEqual(1, approved["current_step"])
        self.assertEqual(approved["proposal_baseline_sha256"], approved["approval_baseline_sha256"])
        self.assertEqual(approved["approval_baseline_sha256"], approved["transaction_recovery_baseline_sha256"])
        self.assertEqual(approved["approval_baseline_sha256"], approved["approval_repository_evidence"]["sha256"])

    def test_rejection_is_durable_and_grants_no_execution_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            preview = planning.build_proposal_preview(repo, "Operator One", "Reject me", "read-only", min_steps=1, max_steps=2)
            with mock.patch.object(provider_codex, "execute_structured", return_value=provider_result(1)):
                candidate = planning.propose_plan(
                    repo, "Operator One", "Reject me", "read-only", preview["preview_sha256"], "PROPOSE", min_steps=1, max_steps=2
                )
            rejected = planning.reject_plan(repo, "Operator One", candidate["plan_hash"], "not the right decomposition", "REJECT")
            status = planning.plan_status(repo)
            receipt = repo / adoption.RUNTIME_NAME / f"plan-rejection-{candidate['plan_hash'][:16]}.json"
            self.assertEqual("REJECTED", rejected["status"])
            self.assertFalse(rejected["execution_authority_granted"])
            self.assertFalse(status["execution_authority_granted"])
            self.assertTrue(receipt.is_file())
            with self.assertRaisesRegex(planning.PlanningError, "no plan is awaiting"):
                planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")

    def test_planning_refuses_project_delta_outside_fresh_transaction_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            (repo / "README.md").write_text("changed before planning\n", encoding="utf-8")
            with self.assertRaisesRegex(planning.PlanningError, "fresh transaction authority"):
                planning.build_proposal_preview(repo, "Operator One", "Stale baseline", "write", min_steps=1, max_steps=2)

    def test_tampered_runtime_plan_fails_closed_and_cli_route_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            preview = planning.build_proposal_preview(repo, "Operator One", "Integrity", "write", min_steps=1, max_steps=2)
            with mock.patch.object(provider_codex, "execute_structured", return_value=provider_result(1)):
                planning.propose_plan(
                    repo, "Operator One", "Integrity", "write", preview["preview_sha256"], "PROPOSE", min_steps=1, max_steps=2
                )
            path = repo / adoption.RUNTIME_NAME / planning.PLAN_RECORD
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["plan"]["steps"][0]["objective"] = "tampered"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(planning.PlanningError, "integrity"):
                planning.plan_status(repo)

        with mock.patch.object(planning, "cli_main", return_value=0) as route:
            self.assertEqual(0, cli.main(["plan", "status"]))
            route.assert_called_once_with(["status"])


if __name__ == "__main__":
    import unittest
    unittest.main()
