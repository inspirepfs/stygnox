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
from tests.provider_catalog_fixture import safe_rate_limits, test_catalog  # noqa: E402


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


def plan_result(goal: str = "Retirement plan", repository_mutation_scope: list[str] | None = None) -> dict:
    return {
        "provider": "codex", "model": "gpt-test", "effort": "high", "sandbox": "read-only",
        "payload": {"steps": [{
            "id": 1, "title": "Implement", "objective": "Implement exact retirement fixture",
            "acceptance": ["Retirement fixture is complete"], "test_change_policy": "modify",
        }], "files_inspected": ["app.py"], "repository_mutation_scope": repository_mutation_scope or ["app.py"]},
        "metrics": {"commands_executed": 1, "input_tokens": 10, "cached_input_tokens": 5, "cache_write_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 1, "codex_seconds": 0.1},
    }


def approve(repo: Path, *, goal: str = "Retirement plan", from_retirement: str | None = None, repository_mutation_scope: list[str] | None = None) -> dict:
    preview = planning.build_proposal_preview(repo, "Operator One", goal, "write", min_steps=1, max_steps=1, from_retirement=from_retirement)
    with mock.patch.object(provider_codex, "execute_structured", return_value=plan_result(goal, repository_mutation_scope)):
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
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)
        self._provider_rate_patch = mock.patch.object(provider_codex, "rate_limits", return_value=safe_rate_limits())
        self._provider_rate_patch.start()
        self.addCleanup(self._provider_rate_patch.stop)

    def test_rollback_restores_only_plan_native_paths_and_preserves_operator_residue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo)
            (repo / "residue.py").write_text("operator = 'staged approval residue'\n", encoding="utf-8")
            git(repo, "add", "residue.py")
            (repo / "operator.txt").write_text("untracked approval residue\n", encoding="utf-8")
            active_reviewed(repo, root / "external")
            approved = approve(repo, repository_mutation_scope=["app.py", "created.py", "deleted.py"])
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
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo, repository_mutation_scope=["retained.py"])
            run_mutating_turn(repo, approved, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            before = adoption.capture_baseline(repo).public()["sha256"]
            result = retire(repo, approved["plan_hash"], "carry-forward", "replacement required")
            after = adoption.capture_baseline(repo).public()["sha256"]
            self.assertEqual(before, after)
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("IDLE", state["status"])
            record_id = state["retired_plans"][-1]["record_id"]
            self.assertEqual("RETIRED_WITH_CARRY_FORWARD", state["retired_plans"][-1]["disposition"])
            manifest = retirement.load_retirement(repo, record_id, state["retired_plans"][-1]["manifest_sha256"])
            lineage = retirement._validate_historical_lineage(manifest)
            self.assertEqual(approved["plan_hash"], lineage["source_plan_hash"])
            self.assertEqual(["retained.py"], [row["path"] for row in lineage["preserved_path_fingerprints"]])
            with self.assertRaisesRegex(planning.PlanningError, "must use --from-retirement"):
                planning.build_proposal_preview(repo, "Operator One", "replacement", "write", min_steps=1, max_steps=1)
            preview = planning.build_proposal_preview(repo, "Operator One", "replacement", "write", min_steps=1, max_steps=1, from_retirement=record_id)
            self.assertEqual(record_id, preview["retirement_context"]["record_id"])
            self.assertEqual(["retained.py"], preview["retirement_context"]["preserved_paths"])
            replacement = approve(repo, goal="replacement", from_retirement=record_id, repository_mutation_scope=["retained.py"])
            replacement_state = planning.plan_status(repo)["plan"]
            self.assertEqual(manifest["manifest_sha256"], replacement_state["retirement_historical_lineage"]["retirement_manifest_sha256"])
            self.assertTrue(replacement_state["retirement_historical_lineage"]["historical_evidence_only"])
            snapshot = reconciliation.reconciliation_snapshot(repo, "Operator One", replacement["plan_hash"])
            candidate = next(row for row in snapshot["candidates"] if row["path"] == "retained.py")
            self.assertEqual("retired-carry-forward", candidate["classification"])
            self.assertTrue(candidate["inherited_fingerprint_matches"])
            action_preview = reconciliation.build_action_preview(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt")
            adopted = reconciliation.apply_action(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt", action_preview["preview_sha256"], "ADOPT")
            self.assertEqual(reconciliation.ADOPTED, adopted["result"])

    def test_rejected_replacement_supersession_is_same_lineage_and_never_authorised(self) -> None:
        retirement_id = "RT-TEST-REPLACEMENT"
        baseline = "a" * 64
        tx = {
            "transaction_id": "TX-test",
            "authority_baseline_sha256": baseline,
        }
        state = {
            "status": "REJECTED",
            "execution_authority_granted": False,
            "operator": "Operator One",
            "transaction_id": "TX-test",
            "proposal_baseline_sha256": baseline,
            "approved_at": None,
            "approval_baseline_sha256": None,
            "approval_rollback_snapshot": None,
            "step_authority_baseline_sha256": None,
            "qualified_at": None,
            "final_qualification": None,
            "active_gate": None,
            "step_results": [],
            "continuation_history": [],
            "qualification_history": [],
            "human_gate_history": [],
            "human_gate_resolutions": [],
            "human_resumes": [],
            "human_steering": [],
            "interrupted_recoveries": [],
            "self_development_grant_history": [],
            "self_development_expirations": [],
            "current_step": 1,
            "retirement_record_id": retirement_id,
            "retirement_manifest_sha256": "e" * 64,
            "retired_plans": [{
                "record_id": retirement_id,
                "disposition": "RETIRED_WITH_CARRY_FORWARD",
                "manifest_sha256": "e" * 64,
            }],
            "plan_hash": "b" * 64,
            "record_sha256": "c" * 64,
            "rejected_at": "2026-10-06T20:00:00+00:00",
            "rejection_reason": "bounded hostile-review correction",
        }

        evidence = planning._rejected_replacement_supersession(
            state,
            operator="Operator One",
            transaction=tx,
            retirement_record_id=retirement_id,
        )
        self.assertEqual(retirement_id, evidence["retirement_record_id"])
        self.assertFalse(evidence["execution_authority_granted"])
        self.assertRegex(evidence["record_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual("e" * 64, evidence["retirement_manifest_sha256"])

        modern = dict(state)
        modern["retirement_historical_lineage"] = {
            "retirement_record_id": retirement_id,
            "retirement_manifest_sha256": "e" * 64,
        }
        modern_evidence = planning._rejected_replacement_supersession(
            modern,
            operator="Operator One",
            transaction=tx,
            retirement_record_id=retirement_id,
        )
        self.assertEqual(retirement_id, modern_evidence["retirement_record_id"])

        bad_manifest = dict(state)
        bad_manifest["retirement_manifest_sha256"] = "f" * 64
        with self.assertRaisesRegex(
            planning.PlanningError,
            "manifest does not match durable retirement history",
        ):
            planning._rejected_replacement_supersession(
                bad_manifest,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        wrong_retirement = dict(state)
        wrong_retirement["retirement_record_id"] = "RT-WRONG"
        with self.assertRaisesRegex(planning.PlanningError, "retirement lineage"):
            planning._rejected_replacement_supersession(
                wrong_retirement,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        authorised = dict(state)
        authorised["execution_authority_granted"] = True
        with self.assertRaisesRegex(planning.PlanningError, "execution authority"):
            planning._rejected_replacement_supersession(
                authorised,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        stale = dict(state)
        stale["proposal_baseline_sha256"] = "d" * 64
        with self.assertRaisesRegex(planning.PlanningError, "baseline changed"):
            planning._rejected_replacement_supersession(
                stale,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        wrong_operator = dict(state)
        wrong_operator["operator"] = "Other Operator"
        with self.assertRaisesRegex(
            planning.PlanningError,
            "operator/transaction",
        ):
            planning._rejected_replacement_supersession(
                wrong_operator,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        wrong_transaction = dict(state)
        wrong_transaction["transaction_id"] = "TX-other"
        with self.assertRaisesRegex(
            planning.PlanningError,
            "operator/transaction",
        ):
            planning._rejected_replacement_supersession(
                wrong_transaction,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        previously_approved = dict(state)
        previously_approved["approved_at"] = "2026-10-06T20:01:00+00:00"
        with self.assertRaisesRegex(
            planning.PlanningError,
            "approval or execution",
        ):
            planning._rejected_replacement_supersession(
                previously_approved,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

        executed = dict(state)
        executed["step_results"] = [{"step": 1, "result": "PASS"}]
        with self.assertRaisesRegex(
            planning.PlanningError,
            "execution or authority history",
        ):
            planning._rejected_replacement_supersession(
                executed,
                operator="Operator One",
                transaction=tx,
                retirement_record_id=retirement_id,
            )

    def test_legacy_retirement_rejected_replacement_can_repropose_and_approve(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)

            progress = repo / "docs" / "programme" / "PROGRESS.md"
            progress.parent.mkdir(parents=True)
            progress.write_text("# Progress\n", encoding="utf-8")

            product = repo / "src" / "stygnox" / "product.py"
            product.parent.mkdir(parents=True)
            product.write_text("# source marker\n", encoding="utf-8")

            planning_source = repo / "src" / "stygnox" / "planning.py"
            planning_source.write_text(
                "# legacy carried tooling\n",
                encoding="utf-8",
            )

            git(
                repo,
                "add",
                "docs/programme/PROGRESS.md",
                "src/stygnox/product.py",
                "src/stygnox/planning.py",
            )
            git(repo, "commit", "-q", "-m", "legacy bridge fixture")

            active_reviewed(repo, root / "external")

            retirement_id = "RT-20261006T194144Z-393d5876562f"

            ordinary_fingerprint = retirement._path_state(
                repo,
                "docs/programme/PROGRESS.md",
            )["fingerprint"]

            tooling_fingerprint = retirement._path_state(
                repo,
                "src/stygnox/planning.py",
            )["fingerprint"]

            baseline = adoption.capture_baseline(repo).public()

            legacy_manifest = {
                "schema": retirement.RETIREMENT_SCHEMA,
                "product_version": "0.1.0",
                "record_id": retirement_id,
                "created_at": "2026-10-06T19:41:44+00:00",
                "plan_hash": "b" * 64,
                "status_before": "APPROVED",
                "step": 3,
                "step_count": 3,
                "reason": "legacy carried replacement fixture",
                "disposition": "RETIRED_WITH_CARRY_FORWARD",
                "preview_sha256": "a" * 64,
                "repository_before": baseline,
                "repository_after": baseline,
                "paths": [
                    {
                        "action": "preserve",
                        "path": "docs/programme/PROGRESS.md",
                        "source": "adopted-carry-forward",
                        "approval_presence": "present",
                        "current": {
                            "fingerprint": ordinary_fingerprint,
                        },
                    },
                    {
                        "action": "preserve",
                        "path": "src/stygnox/planning.py",
                        "source": "controller-native",
                        "approval_presence": "present",
                        "current": {
                            "fingerprint": tooling_fingerprint,
                        },
                    },
                ],
                "operations": {
                    "restore": [],
                    "delete": [],
                    "preserved": [
                        "docs/programme/PROGRESS.md",
                        "src/stygnox/planning.py",
                    ],
                },
                "planning_context": {
                    "goal": "legacy replacement source",
                },
            }

            _name, manifest_sha = retirement._write_manifest(
                repo,
                legacy_manifest,
            )

            initial_preview = planning.build_proposal_preview(
                repo,
                "Operator One",
                "legacy rejected replacement",
                "write",
                min_steps=1,
                max_steps=1,
            )

            with mock.patch.object(
                provider_codex,
                "execute_structured",
                return_value=plan_result(
                    "legacy rejected replacement",
                    [
                        "docs/programme/PROGRESS.md",
                        "src/stygnox/planning.py",
                    ],
                ),
            ):
                predecessor = planning.propose_plan(
                    repo,
                    "Operator One",
                    "legacy rejected replacement",
                    "write",
                    initial_preview["preview_sha256"],
                    "PROPOSE",
                    min_steps=1,
                    max_steps=1,
                )

            legacy_predecessor = dict(predecessor)
            legacy_predecessor["retirement_record_id"] = retirement_id
            legacy_predecessor["retirement_manifest_sha256"] = manifest_sha
            legacy_predecessor["retirement_historical_lineage"] = None
            legacy_predecessor["retired_plans"] = [{
                "record_id": retirement_id,
                "manifest_sha256": manifest_sha,
                "plan_hash": legacy_manifest["plan_hash"],
                "status_before": "APPROVED",
                "step": 3,
                "reason": legacy_manifest["reason"],
                "disposition": "RETIRED_WITH_CARRY_FORWARD",
                "retired_at": legacy_manifest["created_at"],
            }]
            legacy_predecessor["retirement_carry_forward_candidates"] = [
                {
                    "path": "docs/programme/PROGRESS.md",
                    "source": "adopted-carry-forward",
                    "approval_presence": "present",
                    "retirement_fingerprint": ordinary_fingerprint,
                    "retirement_record_id": retirement_id,
                    "retirement_manifest_sha256": manifest_sha,
                },
                {
                    "path": "src/stygnox/planning.py",
                    "source": "controller-native",
                    "approval_presence": "present",
                    "retirement_fingerprint": tooling_fingerprint,
                    "retirement_record_id": retirement_id,
                    "retirement_manifest_sha256": manifest_sha,
                },
            ]

            planning._write(repo, legacy_predecessor)

            rejected = planning.reject_plan(
                repo,
                "Operator One",
                predecessor["plan_hash"],
                "hostile review corrections",
                "REJECT",
            )

            receipt_path = (
                repo
                / adoption.RUNTIME_NAME
                / f"plan-rejection-{predecessor['plan_hash'][:16]}.json"
            )
            receipt = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )

            self.assertEqual("REJECTED", rejected["status"])
            self.assertFalse(rejected["execution_authority_granted"])

            corrected_preview = planning.build_proposal_preview(
                repo,
                "Operator One",
                "corrected replacement",
                "write",
                min_steps=1,
                max_steps=1,
                from_retirement=retirement_id,
            )

            context = corrected_preview["retirement_context"]
            bridge = context["legacy_rejected_replacement_bridge"]

            self.assertEqual(
                receipt["record_sha256"],
                bridge["rejection_receipt_record_sha256"],
            )
            self.assertEqual(
                ["docs/programme/PROGRESS.md"],
                context["preserved_paths"],
            )
            self.assertEqual(
                ["src/stygnox/planning.py"],
                [
                    row["path"]
                    for row in context["cap_011_preserved_paths"]
                ],
            )

            with mock.patch.object(
                provider_codex,
                "execute_structured",
                return_value=plan_result(
                    "corrected replacement",
                    ["docs/programme/PROGRESS.md"],
                ),
            ):
                corrected = planning.propose_plan(
                    repo,
                    "Operator One",
                    "corrected replacement",
                    "write",
                    corrected_preview["preview_sha256"],
                    "PROPOSE",
                    min_steps=1,
                    max_steps=1,
                    from_retirement=retirement_id,
                )

            self.assertEqual("AWAITING_APPROVAL", corrected["status"])
            self.assertIsNone(corrected["retirement_historical_lineage"])
            self.assertEqual(
                bridge["record_sha256"],
                corrected["retirement_legacy_bridge"]["record_sha256"],
            )
            self.assertEqual(
                predecessor["plan_hash"],
                corrected[
                    "superseded_rejection_history"
                ][-1]["plan_hash"],
            )

            rejected_corrected = planning.reject_plan(
                repo,
                "Operator One",
                corrected["plan_hash"],
                "second hostile review correction",
                "REJECT",
            )
            self.assertEqual("REJECTED", rejected_corrected["status"])
            self.assertFalse(rejected_corrected["execution_authority_granted"])

            successor_preview = planning.build_proposal_preview(
                repo,
                "Operator One",
                "second corrected replacement",
                "write",
                min_steps=1,
                max_steps=1,
                from_retirement=retirement_id,
            )
            successor_context = successor_preview["retirement_context"]
            self.assertEqual(
                bridge["record_sha256"],
                successor_context["legacy_rejected_replacement_bridge"]["record_sha256"],
            )
            self.assertEqual(
                ["docs/programme/PROGRESS.md"],
                successor_context["preserved_paths"],
            )
            self.assertEqual(
                corrected["plan_hash"],
                successor_context["superseded_rejection"]["plan_hash"],
            )

            with mock.patch.object(
                provider_codex,
                "execute_structured",
                return_value=plan_result(
                    "second corrected replacement",
                    ["docs/programme/PROGRESS.md"],
                ),
            ):
                successor = planning.propose_plan(
                    repo,
                    "Operator One",
                    "second corrected replacement",
                    "write",
                    successor_preview["preview_sha256"],
                    "PROPOSE",
                    min_steps=1,
                    max_steps=1,
                    from_retirement=retirement_id,
                )

            self.assertEqual("AWAITING_APPROVAL", successor["status"])
            self.assertEqual(
                bridge["record_sha256"],
                successor["retirement_legacy_bridge"]["record_sha256"],
            )
            self.assertEqual(
                [predecessor["plan_hash"], corrected["plan_hash"]],
                [
                    row["plan_hash"]
                    for row in successor["superseded_rejection_history"][-2:]
                ],
            )

            approved = planning.approve_plan(
                repo,
                "Operator One",
                successor["plan_hash"],
                "APPROVE",
            )

            self.assertEqual("APPROVED", approved["status"])
            self.assertTrue(approved["execution_authority_granted"])

    def test_operator_projects_same_retirement_reproposal_for_rejected_replacement(self) -> None:
        retirement_id = "RT-TEST-REPLACEMENT"
        actions = operator_state._actions(
            phase="REJECTED",
            adopted=True,
            transaction={"state": "ACTIVE"},
            controller_state={"enabled": True},
            state={
                "status": "REJECTED",
                "retirement_record_id": retirement_id,
            },
            provider_state=None,
            gate={},
            sched={},
            recon={},
            qual={},
            latest=None,
            blockers=[],
        )
        self.assertEqual("plan.propose-replacement-preview", actions[0]["action"])
        self.assertEqual(retirement_id, actions[0]["retirement_record_id"])

    def test_carry_forward_binds_step_reconciliation_and_cap_011_history_without_adopting_cap_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external")
            approved = approve(repo, repository_mutation_scope=["retained.py", "src/stygnox/planning.py"])
            def mutate() -> None:
                (repo / "retained.py").write_text("retained\n", encoding="utf-8")
                target = repo / "src" / "stygnox" / "planning.py"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("historical CAP-011 path\n", encoding="utf-8")
            run_mutating_turn(repo, approved, mutate)

            state = planning._record(repo); assert state is not None
            step_result = {
                "step": 1, "step_id": 1, "title": "Implement", "objective": "fixture", "result": "PASS",
                "controller_receipt_sha256": "a" * 64, "qualified_baseline_sha256": "b" * 64,
                "gates": [], "qualified_at": "2026-10-06T00:00:00+00:00",
            }
            step_result["record_sha256"] = retirement._digest(step_result)
            action = {"schema": "stygnox_reconciliation_action_v1", "plan_hash": approved["plan_hash"], "path": "retained.py", "disposition": "ADOPTED"}
            action["action_hash"] = retirement._digest(action)
            grant = {
                "schema": "stygnox_self_development_grant_v1", "plan_hash": approved["plan_hash"], "step": 1,
                "repository_mutation_scope": ["retained.py", "src/stygnox/planning.py"], "paths": ["src/stygnox/planning.py"],
            }
            grant["grant_sha256"] = retirement._digest(grant)
            expiration = {"grant_sha256": grant["grant_sha256"], "plan_hash": approved["plan_hash"], "step": 1, "gate_id": "gate", "reason": "turn complete", "expired_at": "2026-10-06T00:00:01+00:00"}
            expiration["record_sha256"] = retirement._digest(expiration)
            updated = dict(state)
            updated.update({
                "step_results": [step_result],
                "qualification_history": [{"kind": "step", "state": "PASS", "step": 1, "record_sha256": step_result["record_sha256"], "completed_at": "2026-10-06T00:00:00+00:00"}],
                "reconciliation_actions": [action],
                "self_development_grant_history": [grant],
                "self_development_expirations": [expiration],
            })
            planning._write(repo, updated)

            retire(repo, approved["plan_hash"], "carry-forward", "lineage must survive")
            record_id = planning.plan_status(repo)["plan"]["retired_plans"][-1]["record_id"]
            preview = planning.build_proposal_preview(repo, "Operator One", "replacement", "write", min_steps=1, max_steps=1, from_retirement=record_id)
            context = preview["retirement_context"]
            self.assertEqual(["retained.py"], context["preserved_paths"])
            self.assertEqual(["src/stygnox/planning.py"], [row["path"] for row in context["cap_011_preserved_paths"]])
            self.assertEqual(step_result["record_sha256"], context["prior_step_qualification_evidence"][0]["record_sha256"])
            self.assertEqual(action["action_hash"], context["reconciliation_history"][0]["action_hash"])
            self.assertEqual(grant["grant_sha256"], context["cap_011_history"]["grant_history"][0]["grant_sha256"])

            replacement = approve(repo, goal="replacement", from_retirement=record_id, repository_mutation_scope=["retained.py"])
            replacement_state = planning.plan_status(repo)["plan"]
            self.assertEqual(["retained.py"], [row["path"] for row in replacement_state["retirement_carry_forward_candidates"]])
            self.assertEqual(["src/stygnox/planning.py"], [row["path"] for row in replacement_state["retirement_excluded_historical_authority_paths"]])
            self.assertEqual(approved["plan_hash"], replacement_state["retirement_historical_lineage"]["source_plan_hash"])

    def test_malformed_preserved_historical_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external")
            approved = approve(repo, repository_mutation_scope=["retained.py"])
            run_mutating_turn(repo, approved, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            retire(repo, approved["plan_hash"], "carry-forward")
            state = planning.plan_status(repo)["plan"]
            record_id = state["retired_plans"][-1]["record_id"]
            manifest = retirement.load_retirement(repo, record_id, state["retired_plans"][-1]["manifest_sha256"])
            malformed = dict(manifest)
            lineage = dict(manifest["historical_lineage"])
            lineage["preserved_path_fingerprints"] = [{"path": "retained.py", "fingerprint": "missing"}]
            digest_body = dict(lineage); digest_body.pop("lineage_sha256", None)
            lineage["lineage_sha256"] = retirement._digest(digest_body)
            malformed["historical_lineage"] = lineage
            with self.assertRaisesRegex(retirement.RetirementError, "preserved path lacks immutable ownership/authority evidence"):
                retirement._validate_historical_lineage(malformed)

    def test_replacement_adoption_refuses_content_changed_since_retirement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); approved = approve(repo, repository_mutation_scope=["retained.py"])
            run_mutating_turn(repo, approved, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            retire(repo, approved["plan_hash"], "carry-forward")
            idle = planning.plan_status(repo)["plan"]
            record_id = idle["retired_plans"][-1]["record_id"]
            replacement = approve(repo, goal="replacement", from_retirement=record_id, repository_mutation_scope=["retained.py"])
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
            root = Path(td); repo = root / "repo"; init_repo(repo); active_reviewed(repo, root / "external"); first = approve(repo, repository_mutation_scope=["retained.py"])
            run_mutating_turn(repo, first, lambda: (repo / "retained.py").write_text("retained\n", encoding="utf-8"))
            retire(repo, first["plan_hash"], "carry-forward")
            record_id = planning.plan_status(repo)["plan"]["retired_plans"][-1]["record_id"]
            replacement = approve(repo, goal="replacement", from_retirement=record_id, repository_mutation_scope=["retained.py"])
            ap = reconciliation.build_action_preview(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt")
            reconciliation.apply_action(repo, "Operator One", replacement["plan_hash"], "retained.py", "adopt", ap["preview_sha256"], "ADOPT")
            run_mutating_turn(repo, replacement, lambda: (repo / "retained.py").write_text("replacement changed it\n", encoding="utf-8"))
            result = retire(repo, replacement["plan_hash"], "rollback", "replacement abandoned")
            self.assertEqual("ROLLED_BACK", result["result"])
            self.assertEqual("retained\n", (repo / "retained.py").read_text(encoding="utf-8"))

    def test_approval_snapshot_binds_but_does_not_archive_protected_legacy_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)

            legacy = repo / ".ralph" / "policy.md"
            legacy.parent.mkdir()
            legacy.write_text("# historical policy\n", encoding="utf-8")
            git(repo, "add", ".ralph/policy.md")
            git(repo, "commit", "-q", "-m", "track historical policy")

            active_reviewed(repo, root / "external")
            approved = approve(repo)

            state = planning.plan_status(repo)["plan"]
            self.assertIn(".ralph/policy.md", state["approval_repository_manifest"])

            snapshot = state["approval_rollback_snapshot"]
            manifest_sha = retirement._digest(
                {str(k): str(v) for k, v in state["approval_repository_manifest"].items()}
            )
            self.assertEqual(manifest_sha, snapshot["manifest_sha256"])

            archive = repo / adoption.RUNTIME_NAME / snapshot["archive"]
            with tarfile.open(archive, "r") as captured:
                self.assertNotIn(".ralph/policy.md", captured.getnames())

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
