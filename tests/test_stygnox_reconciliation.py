"""Installed carry-forward ownership reconciliation regressions."""
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

from stygnox import adoption, cli, controller, operator, planning, provider_codex, reconciliation, transactions  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path, *, stygnox_self: bool = False, existing_test: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Reconciliation Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    if existing_test:
        (path / "tests").mkdir()
        (path / "tests" / "test_existing.py").write_text("assert True\n", encoding="utf-8")
    if stygnox_self:
        (path / "src" / "stygnox").mkdir(parents=True)
        (path / "src" / "stygnox" / "product.py").write_text("NAME = 'Stygnox'\n", encoding="utf-8")
        (path / "pyproject.toml").write_text("[project]\nname='stygnox'\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "baseline")


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev-reconciliation")


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
            max_loops=3,
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
            max_loops=3,
        )
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


def planning_result(test_policy: str = "modify") -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "read-only",
        "payload": {
            "steps": [{
                "id": 1,
                "title": "Reconcile ownership",
                "objective": "Reconcile exact carry-forward ownership",
                "acceptance": ["All carry-forward paths have explicit ownership dispositions"],
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


def approve(repo: Path, *, test_policy: str = "modify") -> dict:
    preview = planning.build_proposal_preview(
        repo,
        "Operator One",
        "Restore explicit carry-forward reconciliation",
        "write",
        min_steps=1,
        max_steps=1,
    )
    with mock.patch.object(provider_codex, "execute_structured", return_value=planning_result(test_policy)):
        candidate = planning.propose_plan(
            repo,
            "Operator One",
            "Restore explicit carry-forward reconciliation",
            "write",
            preview["preview_sha256"],
            "PROPOSE",
            min_steps=1,
            max_steps=1,
        )
    return planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")


def apply(repo: Path, plan_hash: str, path: str, disposition: str, *, reason: str | None = None) -> dict:
    preview = reconciliation.build_action_preview(repo, "Operator One", plan_hash, path, disposition, reason=reason)
    return reconciliation.apply_action(
        repo,
        "Operator One",
        plan_hash,
        path,
        disposition,
        preview["preview_sha256"],
        preview["confirmation"],
        reason=reason,
    )


class StygnoxReconciliationTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_inspection_is_read_only_controller_snapshot_and_cli_has_no_path_selector(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "README.md").write_text("external tracked change\n", encoding="utf-8")
            (repo / "retained.py").write_text("external untracked\n", encoding="utf-8")
            before = adoption.capture_baseline(repo).public()["sha256"]
            snapshot = reconciliation.reconciliation_snapshot(repo, "Operator One", approved["plan_hash"])
            after = adoption.capture_baseline(repo).public()["sha256"]
            parsed = reconciliation.build_parser().parse_args(["inspect", approved["plan_hash"], "--operator", "Operator One"])
        self.assertEqual(before, after)
        self.assertEqual(2, snapshot["pending_count"])
        self.assertEqual({"README.md", "retained.py"}, {item["path"] for item in snapshot["candidates"]})
        self.assertTrue(all(item["disposition"] == reconciliation.PENDING for item in snapshot["candidates"]))
        self.assertNotIn("path", parsed.__dict__)
        self.assertEqual("reconcile", cli.build_parser().parse_args(["reconcile"]).command)

    def test_adopts_tracked_and_untracked_without_mutating_worktree_and_operator_view_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "README.md").write_text("retained tracked content\n", encoding="utf-8")
            (repo / "retained.py").write_text("retained untracked content\n", encoding="utf-8")
            before = adoption.capture_baseline(repo).public()["sha256"]
            tracked = apply(repo, approved["plan_hash"], "README.md", "adopt")
            untracked = apply(repo, approved["plan_hash"], "retained.py", "adopt")
            after = adoption.capture_baseline(repo).public()["sha256"]
            state = planning.plan_status(repo)["plan"]
            view = operator.classify_changes(repo)
            snapshot = reconciliation.reconciliation_snapshot(repo, "Operator One", approved["plan_hash"])
            self.assertEqual(before, after)
            self.assertEqual(reconciliation.ADOPTED, tracked["result"])
            self.assertEqual(reconciliation.ADOPTED, untracked["result"])
            self.assertEqual(["README.md", "retained.py"], state["carry_forward_adopted_paths"])
            self.assertEqual({"README.md", "retained.py"}, set(view["categories"]["plan_carry_forward"]["paths"]))
            self.assertEqual(0, snapshot["pending_count"])
            self.assertFalse(snapshot["requires_human_decision"])
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "already has a durable disposition"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "README.md", "adopt")

    def test_leave_outside_and_reject_are_mutually_exclusive_nonabsorption_dispositions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "outside.txt").write_text("external owner\n", encoding="utf-8")
            (repo / "rejected.txt").write_text("needs external reconciliation\n", encoding="utf-8")
            left = apply(repo, approved["plan_hash"], "outside.txt", "leave-outside", reason="owned by external migration")
            rejected = apply(repo, approved["plan_hash"], "rejected.txt", "reject", reason="external owner must reconcile")
            state = planning.plan_status(repo)["plan"]
            view = operator.classify_changes(repo)
            self.assertEqual(reconciliation.LEFT_OUTSIDE, left["result"])
            self.assertEqual(reconciliation.REJECTED, rejected["result"])
            self.assertEqual(["outside.txt"], state["carry_forward_outside_paths"])
            self.assertEqual(["rejected.txt"], state["carry_forward_rejected_paths"])
            self.assertIn("outside.txt", view["categories"]["outside_plan"]["paths"])
            self.assertIn("rejected.txt", view["categories"]["rejected_external"]["paths"])
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "already has a durable disposition"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "outside.txt", "adopt")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "already has a durable disposition"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "rejected.txt", "reject")

    def test_candidate_fingerprint_and_authority_are_revalidated_at_action_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "candidate.txt").write_text("v1\n", encoding="utf-8")
            preview = reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "candidate.txt", "adopt")
            (repo / "candidate.txt").write_text("v2\n", encoding="utf-8")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "preview is stale"):
                reconciliation.apply_action(repo, "Operator One", approved["plan_hash"], "candidate.txt", "adopt", preview["preview_sha256"], "ADOPT")
            preview = reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "candidate.txt", "adopt")
            controller.deactivate_controller(repo, "Operator One", "DEACTIVATE")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "active installed controller"):
                reconciliation.apply_action(repo, "Operator One", approved["plan_hash"], "candidate.txt", "adopt", preview["preview_sha256"], "ADOPT")

    def test_test_policy_is_rechecked_for_adoption_but_not_nonabsorption(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo, existing_test=True)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="add-only")
            (repo / "tests" / "test_existing.py").write_text("assert False\n", encoding="utf-8")
            (repo / "tests" / "test_new.py").write_text("assert True\n", encoding="utf-8")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "add-only cannot adopt pre-existing"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "tests/test_existing.py", "adopt")
            new_preview = reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "tests/test_new.py", "adopt")
            reconciliation.apply_action(repo, "Operator One", approved["plan_hash"], "tests/test_new.py", "adopt", new_preview["preview_sha256"], "ADOPT")
            outside = apply(repo, approved["plan_hash"], "tests/test_existing.py", "leave-outside", reason="pre-existing external test change")
        self.assertEqual(reconciliation.LEFT_OUTSIDE, outside["result"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="none")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_new.py").write_text("assert True\n", encoding="utf-8")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "test policy none"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "tests/test_new.py", "adopt")

    def test_stygnox_self_development_adoption_is_reserved_for_cap011(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo, stygnox_self=True)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            target = repo / "src" / "stygnox" / "product.py"
            target.write_text("NAME = 'changed'\n", encoding="utf-8")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "CAP-011"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "src/stygnox/product.py", "adopt")
            rejected = apply(repo, approved["plan_hash"], "src/stygnox/product.py", "reject", reason="requires scoped self-development authority")
        self.assertEqual(reconciliation.REJECTED, rejected["result"])

    def test_forged_duplicate_action_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
            apply(repo, approved["plan_hash"], "candidate.txt", "adopt")
            state = planning._record(repo)
            assert state is not None
            forged = dict(state)
            actions = [dict(item) for item in forged["reconciliation_actions"]]
            actions[0]["candidate_sha256"] = "0" * 64
            forged["reconciliation_actions"] = actions
            planning._write(repo, forged)
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "action hash is malformed or stale"):
                reconciliation.reconciliation_snapshot(repo, "Operator One", approved["plan_hash"])

    def test_operator_dispatch_exposes_same_reconciliation_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
            inspected = operator.dispatch_action(repo, "reconciliation.inspect", {"operator": "Operator One", "plan_hash": approved["plan_hash"]})
            previewed = operator.dispatch_action(repo, "reconciliation.preview", {
                "operator": "Operator One", "plan_hash": approved["plan_hash"], "path": "candidate.txt", "disposition": "adopt",
            })
            applied = operator.dispatch_action(repo, "reconciliation.apply", {
                "operator": "Operator One", "plan_hash": approved["plan_hash"], "path": "candidate.txt", "disposition": "adopt",
                "preview": previewed["result"]["preview_sha256"], "confirm": "ADOPT",
            })
        self.assertEqual(1, inspected["result"]["pending_count"])
        self.assertEqual(reconciliation.ADOPTED, applied["result"]["result"])


if __name__ == "__main__":
    import unittest
    unittest.main()
