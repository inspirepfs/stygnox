"""Approved-plan retirement, rollback, carry-forward and replacement-plan regressions."""
from __future__ import annotations

from pathlib import Path
import json
import hashlib
import tarfile
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, cli, controller, operator, operator_state, planning, provider_codex, reconciliation, retirement, transactions, recovery  # noqa: E402


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Retirement Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (path / "deleted.py").write_text("delete_me = True\n", encoding="utf-8")
    (path / "residue.py").write_text("operator = 'before'\n", encoding="utf-8")
    git(path, "add", "app.py", "deleted.py", "residue.py")
    git(path, "commit", "-q", "-m", "baseline")


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev5")


def _sha(path: Path) -> str:
    h = hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def _dirty_evidence(repo: Path, preview: dict, evidence_root: Path) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True)
    capture = evidence_root / "dirty-baseline.tar.gz"
    with tarfile.open(capture, "w:gz") as archive:
        archive.add(repo, arcname="repo", recursive=True)
    entries = list(recovery.snapshot_worktree(repo, include_ignored=True))
    index = repo / ".git" / "index"
    manifest = {
        "schema": recovery.OPERATOR_MANIFEST_SCHEMA, "baseline_sha256": preview["baseline"]["sha256"],
        "head": preview["baseline"]["head"], "branch": preview["baseline"]["branch"], "status": preview["baseline"]["status"],
        "index_file_sha256": _sha(index) if index.is_file() else None, "worktree_manifest": entries,
        "worktree_manifest_sha256": recovery.manifest_sha256(entries),
    }
    manifest_path=evidence_root/"manifest.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    attestation={
        "schema": adoption.DIRTY_EVIDENCE_SCHEMA, "worktree": str(repo.resolve()), "baseline_sha256": preview["baseline"]["sha256"],
        "capture_path": str(capture.resolve()), "capture_sha256": _sha(capture), "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha(manifest_path), "verified": True, "restoration_rehearsed": True,
        "verified_by": "Retirement Test Operator", "categories": preview["baseline"]["dirty_categories"],
    }
    path=evidence_root/"attestation.json"; path.write_text(json.dumps(attestation, indent=2, sort_keys=True)+"\n", encoding="utf-8"); return path

def active_reviewed(repo: Path, external: Path) -> None:
    resolved = identity(external)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        first = adoption.build_preview(repo, "Operator One", provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One", max_loops=3)
        evidence = None
        if first["baseline"].get("journey") == "dirty":
            evidence = _dirty_evidence(repo, first, external / "evidence")
        preview = adoption.build_preview(repo, "Operator One", dirty_evidence=evidence, provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One", max_loops=3)
        adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", dirty_evidence=evidence, provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One", max_loops=3)
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


def plan_result(goal: str = "Retirement plan") -> dict:
    return {
        "provider": "codex", "model": "gpt-test", "effort": "high", "sandbox": "read-only",
        "payload": {"steps": [{
            "id": 1, "title": "Implement", "objective": "Implement exact retirement fixture",
            "acceptance": ["Retirement fixture is complete"], "test_change_policy": "modify",
        }], "files_inspected": ["app.py"]},
        "metrics": {"commands_executed": 1, "input_tokens": 10, "cached_input_tokens": 5, "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 1, "codex_seconds": 0.1},
    }


def approve(repo: Path, *, goal: str = "Retirement plan", from_retirement: str | None = None) -> dict:
    preview = planning.build_proposal_preview(repo, "Operator One", goal, "write", min_steps=1, max_steps=1, from_retirement=from_retirement)
    with mock.patch.object(provider_codex, "execute_structured", return_value=plan_result(goal)):
        candidate = planning.propose_plan(repo, "Operator One", goal, "write", preview["preview_sha256"], "PROPOSE", min_steps=1, max_steps=1, from_retirement=from_retirement)
    return planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")


def implementation_result(status: str = "PASS", summary: str = "done") -> dict:
    blocker = "human" if status == "BLOCKED" else "none"
    return {
        "provider": "codex", "model": "gpt-test", "effort": "high", "sandbox": "workspace-write",
        "status": status, "summary": summary, "blocker_class": blocker, "blockers": [summary] if status == "BLOCKED" else [],
        "validation_notes": [], "files_inspected": ["app.py"],
        "metrics": {"commands_executed": 1, "input_tokens": 20, "cached_input_tokens": 10, "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 1, "codex_seconds": 0.2, "files_inspected": 1},
    }


def run_mutating_turn(repo: Path, approved: dict, mutator, *, result: dict | None = None) -> dict:
    objective = approved["plan"]["steps"][0]["objective"]
    preview = controller.build_run_preview(repo, "Operator One", objective, "write")
    def execute(**_kwargs):
        mutator()
        return result or implementation_result()
    with mock.patch.object(provider_codex, "execute", side_effect=execute):
        return controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")


def retire(repo: Path, plan_hash: str, disposition: str, reason: str = "superseded") -> dict:
    preview = retirement.build_retirement_preview(repo, "Operator One", plan_hash, reason, disposition)
    return retirement.retire_plan(repo, "Operator One", plan_hash, reason, disposition, preview["preview_sha256"], preview["confirmation"])


class StygnoxPlanRetirementTests(TestCase):
    def test_rollback_restores_only_plan_native_paths_and_preserves_operator_residue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo)
            (repo / "residue.py").write_text("operator = 'staged approval residue'\n", encoding="utf-8")
            git(repo, "add", "residue.py")
            (repo / "operator.txt").write_text("untracked approval residue\n", encoding="utf-8")
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            state = planning.plan_status(repo)["plan"]
            self.assertEqual(retirement.APPROVAL_SNAPSHOT_SCHEMA, state["approval_rollback_snapshot"]["schema"])

            def mutate():
                (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
                (repo / "deleted.py").unlink()
                (repo / "created.py").write_text("created = True\n", encoding="utf-8")
            run_mutating_turn(repo, approved, mutate)
            preview = retirement.build_retirement_preview(repo, "Operator One", approved["plan_hash"], "obsolete", "rollback")
            self.assertEqual(["app.py", "deleted.py"], preview["restore_paths"])
            self.assertEqual(["created.py"], preview["delete_paths"])
            result = retirement.retire_plan(repo, "Operator One", approved["plan_hash"], "obsolete", "rollback", preview["preview_sha256"], "ROLLBACK")

            self.assertEqual("ROLLED_BACK", result["result"])
            self.assertEqual("IDLE", planning.plan_status(repo)["plan"]["status"])
            self.assertEqual("value = 1\n", (repo / "app.py").read_text(encoding="utf-8"))
            self.assertEqual("delete_me = True\n", (repo / "deleted.py").read_text(encoding="utf-8"))
            self.assertFalse((repo / "created.py").exists())
            self.assertEqual("operator = 'staged approval residue'\n", (repo / "residue.py").read_text(encoding="utf-8"))
            self.assertEqual("untracked approval residue\n", (repo / "operator.txt").read_text(encoding="utf-8"))
            self.assertIn("M  residue.py", git(repo, "status", "--short").stdout)

    def test_retirement_preview_is_exact_and_stale_repository_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            run_mutating_turn(repo, approved, lambda: (repo / "app.py").write_text("value = 2\n", encoding="utf-8"))
            preview = retirement.build_retirement_preview(repo, "Operator One", approved["plan_hash"], "obsolete", "rollback")
            (repo / "app.py").write_text("operator changed it\n", encoding="utf-8")
            with self.assertRaisesRegex(retirement.RetirementError, "outside the latest plan-bound authority evidence|stale"):
                retirement.retire_plan(repo, "Operator One", approved["plan_hash"], "obsolete", "rollback", preview["preview_sha256"], "ROLLBACK")

    def test_carry_forward_is_non_mutating_and_replacement_must_consume_latest_retirement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            run_mutating_turn(repo, approved, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            before = adoption.capture_baseline(repo).public()["sha256"]
            result = retire(repo, approved["plan_hash"], "carry-forward", "replacement required")
            after = adoption.capture_baseline(repo).public()["sha256"]
            self.assertEqual(before, after)
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("IDLE", state["status"])
            record_id = state["retired_plans"][-1]["record_id"]
            self.assertEqual("RETIRED_WITH_CARRY_FORWARD", state["retired_plans"][-1]["disposition"])
            with self.assertRaisesRegex(planning.PlanningError, "must use --from-retirement"):
                planning.build_proposal_preview(repo, "Operator One", "replacement", "write", min_steps=1, max_steps=1)
            preview = planning.build_proposal_preview(repo, "Operator One", "replacement", "write", min_steps=1, max_steps=1, from_retirement=record_id)
            self.assertEqual(record_id, preview["retirement_context"]["record_id"])
            self.assertEqual(["retained.py"], preview["retirement_context"]["preserved_paths"])
            replacement = approve(repo, goal="replacement", from_retirement=record_id)
            snapshot = reconciliation.reconciliation_snapshot(repo, "Operator One", replacement["plan_hash"])
            candidate = next(row for row in snapshot["candidates"] if row["path"] == "retained.py")
            self.assertEqual("retired-carry-forward", candidate["classification"])
            self.assertTrue(candidate["inherited_fingerprint_matches"])
            action_preview = reconciliation.build_action_preview(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt")
            adopted = reconciliation.apply_action(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt", action_preview["preview_sha256"], "ADOPT")
            self.assertEqual(reconciliation.ADOPTED, adopted["result"])

    def test_replacement_adoption_refuses_content_changed_since_retirement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            run_mutating_turn(repo, approved, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            retire(repo, approved["plan_hash"], "carry-forward")
            idle = planning.plan_status(repo)["plan"]
            record_id = idle["retired_plans"][-1]["record_id"]
            replacement = approve(repo, goal="replacement", from_retirement=record_id)
            (repo / "retained.py").write_text("changed after retirement\n", encoding="utf-8")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "changed since retirement"):
                reconciliation.build_action_preview(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt")

    def test_blocked_plan_can_retire_and_gate_authority_is_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            blocked = implementation_result("BLOCKED", "BLOCKED_HUMAN: operator evidence required")
            run_mutating_turn(repo, approved, lambda: None, result=blocked)
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("BLOCKED_HUMAN", state["status"])
            self.assertIsNotNone(state["active_gate"])
            result = retire(repo, approved["plan_hash"], "carry-forward", "blocked plan superseded")
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("RETIRED_WITH_CARRY_FORWARD", result["result"])
            self.assertEqual("IDLE", state["status"])
            self.assertIsNone(state["active_gate"])
            self.assertIsNone(state["self_development_grant"])

    def test_terminal_committed_or_pushed_plan_cannot_be_retired_backwards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            for status in ("COMMITTED", "PUSHED", "READ_ONLY_COMPLETE"):
                state = planning._record(repo); assert state is not None
                updated = dict(state); updated["status"] = status; updated["execution_authority_granted"] = False; planning._write(repo, updated)
                with self.assertRaisesRegex(retirement.RetirementError, "active approved/blocked"):
                    retirement.build_retirement_preview(repo, "Operator One", approved["plan_hash"], "no", "carry-forward")

    def test_operator_lifecycle_and_dispatch_expose_retire_then_replacement_without_new_authority_logic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            snap = operator.operator_snapshot(repo)
            self.assertIn("plan.retire-preview", [row["action"] for row in snap["next_actions"]])
            preview = operator.dispatch_action(repo, "plan.retire-preview", {"operator": "Operator One", "plan_hash": approved["plan_hash"], "reason": "replace", "disposition": "carry-forward"})["result"]
            operator.dispatch_action(repo, "plan.retire", {"operator": "Operator One", "plan_hash": approved["plan_hash"], "reason": "replace", "disposition": "carry-forward", "preview": preview["preview_sha256"], "confirm": "CARRY_FORWARD"})
            idle = operator.operator_snapshot(repo)
            actions = idle["next_actions"]
            self.assertEqual(["plan.propose-replacement-preview"], [row["action"] for row in actions])
            self.assertEqual(planning.plan_status(repo)["plan"]["retired_plans"][-1]["record_id"], actions[0]["retirement_record_id"])


    def test_replacement_plan_rollback_restores_adopted_inherited_path_to_replacement_approval_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); first = approve(repo)
            run_mutating_turn(repo, first, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            retire(repo, first["plan_hash"], "carry-forward")
            record_id = planning.plan_status(repo)["plan"]["retired_plans"][-1]["record_id"]
            replacement = approve(repo, goal="replacement", from_retirement=record_id)
            ap = reconciliation.build_action_preview(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt")
            reconciliation.apply_action(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt", ap["preview_sha256"], "ADOPT")
            run_mutating_turn(repo, replacement, lambda: (repo / "retained.py").write_text("replacement changed it\n", encoding="utf-8"))
            result = retire(repo, replacement["plan_hash"], "rollback", "replacement abandoned")
            self.assertEqual("ROLLED_BACK", result["result"])
            self.assertEqual("retained\n", (repo / "retained.py").read_text(encoding="utf-8"))

    def test_web_assets_have_retirement_and_replacement_preview_confirmation_bridge(self) -> None:
        js = (ROOT / "src" / "stygnox" / "web_assets" / "operator.js").read_text(encoding="utf-8")
        html = (ROOT / "src" / "stygnox" / "web.py").read_text(encoding="utf-8")
        self.assertIn("'plan.retire-preview':['plan.retire','CARRY_FORWARD']", js)
        self.assertIn("'plan.propose-replacement-preview':['plan.propose-replacement','PROPOSE']", js)
        self.assertIn("lifecycle-retirement-disposition", html)

    def test_cli_routes_retirement_and_approval_snapshot_is_integrity_bound(self) -> None:
        self.assertEqual("retirement", cli.build_parser().parse_args(["retirement"]).command)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo)
            state = planning.plan_status(repo)["plan"]
            archive = repo / adoption.RUNTIME_NAME / state["approval_rollback_snapshot"]["archive"]
            archive.write_bytes(archive.read_bytes() + b"tamper")
            with self.assertRaisesRegex(retirement.RetirementError, "archive is missing or changed"):
                retirement.build_retirement_preview(repo, "Operator One", approved["plan_hash"], "obsolete", "rollback")


if __name__ == "__main__":
    import unittest
    unittest.main()
