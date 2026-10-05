"""Hostile R3C convergence coverage for the installed native controller.

These tests deliberately drive the real native lifecycle seams.  Provider calls
are replaced only at the external boundary so each assertion observes durable
controller, qualification, or Git behaviour rather than a mock interaction.
"""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
WRAPPER = ROOT / "scripts" / "stygnox_cli.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import (  # noqa: E402
    adoption,
    cli,
    controller,
    finalization,
    human_control,
    planning,
    provider_codex,
    qualification,
    reconciliation,
    scheduler,
    self_development,
)
from tests.provider_catalog_fixture import safe_rate_limits, test_catalog  # noqa: E402
from tests.test_stygnox_finalization import ready_repo  # noqa: E402
from tests.test_stygnox_qualification import (  # noqa: E402
    active_reviewed,
    approve,
    execute_step,
    git,
    implementation_result,
    init_repo,
    qualify,
)
from tests.test_stygnox_scheduler import (  # noqa: E402
    active_reviewed as scheduler_active_reviewed,
    approve as scheduler_approve,
)
from tests.test_stygnox_self_development import (  # noqa: E402
    init_stygnox_repo,
    open_self_gate,
)


class R3CHostileNativeConvergenceTests(TestCase):
    def setUp(self) -> None:
        catalog = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        catalog.start()
        self.addCleanup(catalog.stop)
        limits = mock.patch.object(provider_codex, "rate_limits", return_value=safe_rate_limits())
        limits.start()
        self.addCleanup(limits.stop)

    def test_scope_evidence_is_canonical_digest_bound_and_preserves_authority_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            plan = approved["plan"]

            hostile_plans: list[tuple[dict, bool]] = []
            for change, recompute in (
                (lambda value: value.pop("repository_mutation_scope_sha256"), False),
                (lambda value: value.update(repository_mutation_scope=["README.md", "README.md"]), True),
                (lambda value: value.update(repository_mutation_scope=["./README.md"]), True),
                (lambda value: value.update(repository_mutation_scope=list(reversed(value["repository_mutation_scope"]))), True),
                (lambda value: value.update(repository_mutation_scope_sha256="0" * 64), False),
            ):
                candidate = copy.deepcopy(plan)
                change(candidate)
                # A hostile provider can recompute a digest, but cannot make a
                # duplicate/noncanonical/non-sorted scope a valid authority.
                if recompute and "repository_mutation_scope" in candidate and "repository_mutation_scope_sha256" in candidate:
                    candidate["repository_mutation_scope_sha256"] = planning._digest(candidate["repository_mutation_scope"])
                hostile_plans.append((candidate, recompute))
            for hostile, _recompute in hostile_plans:
                with self.subTest(scope=hostile.get("repository_mutation_scope")):
                    with self.assertRaisesRegex(planning.PlanningError, "scope|digest"):
                        planning._validate_plan(hostile)

            receipt = execute_step(repo, approved, filename="src/work.txt", content="bounded\n")
            self.assertEqual(["src/work.txt"], [row["path"] for row in receipt["actual_delta"]["paths"]])
            self.assertIn("src/final.txt", approved["plan"]["repository_mutation_scope"])
            self.assertEqual(approved["repository_mutation_scope_sha256"], receipt["plan_binding"]["repository_mutation_scope_sha256"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "readonly"
            init_repo(repo)
            active_reviewed(repo, root / "external", repository_authority="read-only")
            approved = approve(repo, repository_authority="read-only")
            self.assertEqual([], approved["plan"]["repository_mutation_scope"])
            execute_step(repo, approved, filename="src/never-written.txt", content="nope\n")
            result = qualify(repo, approved["plan_hash"])
            self.assertEqual("READ_ONLY_COMPLETE", result["result"])
            self.assertFalse((repo / "src" / "never-written.txt").exists())

    def test_out_of_scope_create_edit_and_delete_are_restored_before_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            (repo / "outside-edit.txt").write_text("before\n", encoding="utf-8")
            (repo / "outside-delete.txt").write_text("before\n", encoding="utf-8")
            git(repo, "add", "outside-edit.txt", "outside-delete.txt")
            git(repo, "commit", "-q", "-m", "outside baseline")
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")

            def escape(**_kwargs: object) -> dict:
                (repo / "outside-edit.txt").write_text("escape\n", encoding="utf-8")
                (repo / "outside-delete.txt").unlink()
                (repo / "outside-created.txt").write_text("escape\n", encoding="utf-8")
                return implementation_result("scope escape")

            with mock.patch.object(provider_codex, "execute", side_effect=escape):
                with self.assertRaisesRegex(controller.ControllerError, "exceeded approved repository scope"):
                    controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")
            self.assertEqual("before\n", (repo / "outside-edit.txt").read_text(encoding="utf-8"))
            self.assertEqual("before\n", (repo / "outside-delete.txt").read_text(encoding="utf-8"))
            self.assertFalse((repo / "outside-created.txt").exists())

    def test_qualified_attribution_and_native_commit_have_exact_same_delta(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, receipt, _remote = ready_repo(Path(td))
            state = planning.plan_status(repo)["plan"]
            final = state["final_qualification"]
            attribution = final["accepted_controller_attribution"]
            qualified_paths = final["plan_owned_paths"]
            self.assertEqual(qualified_paths, attribution["accepted_controller_paths"])
            self.assertEqual(qualified_paths, [row["path"] for row in attribution["qualified_delta"]["paths"]])
            self.assertEqual(
                final["qualified_delta_sha256"],
                qualification._qualified_delta_sha256(final["qualified_path_fingerprints"], qualified_paths),
            )
            self.assertEqual(approved["repository_mutation_scope_sha256"], final["repository_mutation_scope_sha256"])
            self.assertEqual(approved["plan_hash"], state["plan_hash"])
            preview = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: exact convergence")
            committed = finalization.commit(repo, "Operator One", approved["plan_hash"], "test: exact convergence", preview["preview_sha256"], "COMMIT")
            committed_state = planning.plan_status(repo)["plan"]
            self.assertEqual("COMMITTED", committed["result"])
            self.assertEqual(final["qualified_path_fingerprints"], committed_state["commit_record"]["path_fingerprints"])
            self.assertEqual(
                final["qualified_delta_sha256"],
                qualification._qualified_delta_sha256(committed_state["commit_record"]["path_fingerprints"], qualified_paths),
            )
            self.assertEqual(qualified_paths, git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD^", "HEAD").stdout.split())

    def test_pending_provenance_is_receipt_bound_not_scheduler_substitutable_or_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            objective = approved["plan"]["steps"][0]["objective"]
            turn = controller.build_run_preview(repo, "Operator One", objective, "write")

            def complete(**_kwargs: object) -> dict:
                (repo / "src").mkdir(exist_ok=True)
                (repo / "src" / "work.txt").write_text("witnessed\n", encoding="utf-8")
                return implementation_result("receipt-bound pending provenance")

            with mock.patch.object(provider_codex, "execute", side_effect=complete):
                receipt = controller.run_controller(repo, "Operator One", objective, "write", turn["preview_sha256"], "RUN")
            receipt_path = repo / adoption.RUNTIME_NAME / f"controller-run-{receipt['preview_sha256'][:16]}.json"
            original_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            for evidence_name, mutate_receipt in (
                ("extra", lambda value: value["actual_delta"]["paths"].append(copy.deepcopy(value["actual_delta"]["paths"][0]))),
                ("duplicate", lambda value: value["actual_delta"]["paths"].append({**value["actual_delta"]["paths"][0], "path": "src/work.txt"})),
                ("unknown", lambda value: value["actual_delta"]["paths"].append({"path": "unknown.txt", "kind": "created", "before_fingerprint": None, "after_fingerprint": "0" * 64})),
                ("grant-mismatch", lambda value: value.update(self_development={"status": "AUTHORIZED", "changed_paths": ["src/work.txt"], "grant_sha256": "0" * 64})),
            ):
                tampered_receipt = copy.deepcopy(original_receipt)
                mutate_receipt(tampered_receipt)
                receipt_path.write_text(json.dumps(tampered_receipt), encoding="utf-8")
                with self.subTest(evidence=evidence_name):
                    with self.assertRaisesRegex(controller.ControllerError, "integrity check"):
                        controller.build_pending_provenance_recovery_preview(repo, "Operator One", receipt["preview_sha256"])
            receipt_path.write_text(json.dumps(original_receipt), encoding="utf-8")
            for stale_preview in ("0" * 64, receipt["preview_sha256"][:-1] + "0"):
                with self.subTest(stale_preview=stale_preview):
                    with self.assertRaisesRegex(controller.ControllerError, "stale|exact"):
                        controller.recover_pending_provenance(repo, "Operator One", receipt["preview_sha256"], stale_preview, "RECOVER_PENDING_PROVENANCE")
            preview = controller.build_pending_provenance_recovery_preview(repo, "Operator One", receipt["preview_sha256"])
            witness = copy.deepcopy(preview["witness"])
            for mutate in (
                lambda value: value.update(current_step=2),
                lambda value: value["paths"].append(copy.deepcopy(value["paths"][0])),
                lambda value: value.update(repository_mutation_scope_sha256="0" * 64),
            ):
                hostile = copy.deepcopy(witness)
                mutate(hostile)
                body = dict(hostile)
                body.pop("witness_sha256", None)
                hostile["witness_sha256"] = planning._digest(body)
                with self.subTest(hostile=hostile):
                    with self.assertRaisesRegex(planning.PlanningError, "stale|malformed|matches"):
                        planning.recover_pending_provenance_same_step(repo, "Operator One", witness=hostile)
            (repo / "src" / "work.txt").write_text("fingerprint drift\n", encoding="utf-8")
            with self.assertRaisesRegex(controller.ControllerError, "live checkpoint-relative state"):
                controller.build_pending_provenance_recovery_preview(repo, "Operator One", receipt["preview_sha256"])
            (repo / "src" / "work.txt").write_text("witnessed\n", encoding="utf-8")
            recovered = controller.recover_pending_provenance(repo, "Operator One", receipt["preview_sha256"], preview["preview_sha256"], "RECOVER_PENDING_PROVENANCE")
            self.assertEqual("PENDING_PROVENANCE_RECOVERED", recovered["result"])
            with self.assertRaisesRegex(controller.ControllerError, "already originated"):
                controller.build_pending_provenance_recovery_preview(repo, "Operator One", receipt["preview_sha256"])
            with self.assertRaisesRegex(scheduler.SchedulerError, "no scheduler state exists"):
                scheduler.build_recovery_preview(repo, "Operator One", [])

    def test_reconciliation_and_operator_surface_cannot_expand_approved_scope(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo)
            (repo / "outside.txt").write_text("operator content\n", encoding="utf-8")
            with self.assertRaisesRegex(reconciliation.ReconciliationError, "outside the approved repository scope"):
                reconciliation.build_action_preview(repo, "Operator One", approved["plan_hash"], "outside.txt", "adopt", reason="hostile scope expansion")
            # Classification is presentation-only: taking a snapshot has no
            # mechanism to alter the authoritative plan scope or grant.
            from stygnox import operator as operator_surface
            before = planning.plan_status(repo)["plan"]
            snapshot = operator_surface.operator_snapshot(repo)
            after = planning.plan_status(repo)["plan"]
            self.assertEqual(before["repository_mutation_scope"], after["repository_mutation_scope"])
            self.assertEqual(before["execution_authority_granted"], after["execution_authority_granted"])
            self.assertEqual("stygnox_operator_surface_v1", snapshot["schema"])

    def test_human_and_self_development_gates_cannot_broaden_native_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            scheduler_active_reviewed(repo, root / "external")
            approved = scheduler_approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved)
            gate = blocked["human_gate"]
            self.assertEqual("self-development-authority", gate["kind"])
            self.assertEqual("RESTORED_UNAUTHORIZED", blocked["self_development"]["status"])
            with self.assertRaisesRegex(controller.ControllerError, "refuses controller receipts with a gate"):
                controller.build_pending_provenance_recovery_preview(repo, "Operator One", blocked["preview_sha256"])
            with self.assertRaisesRegex(human_control.HumanControlError, "requires explicit self-development authorize"):
                human_control.build_resume_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "do not expand scope")
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "exactly match the controller-derived candidate"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"],
                    ["src/stygnox/product.py", "src/stygnox/controller.py"], "attempt scope expansion",
                )
            state = planning.plan_status(repo)["plan"]
            self.assertFalse(state["execution_authority_granted"])
            self.assertIsNone(state["self_development_grant"])

    def test_installed_native_boundary_refuses_bootstrap_decoys_ralph_capture_and_web(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            project.mkdir()
            sentinel = root / "captured"
            (project / "ralph.py").write_text(f"from pathlib import Path; Path({str(sentinel)!r}).write_text('bad')\n", encoding="utf-8")
            fakebin = root / "fakebin"
            fakebin.mkdir()
            fake = fakebin / "stygnox"
            fake.write_text(f"#!/bin/sh\ntouch {str(sentinel)!r}\n", encoding="utf-8")
            fake.chmod(0o755)
            environment = dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ.get("PATH", ""))
            result = subprocess.run([sys.executable, str(WRAPPER), "bootstrap", "--project", str(project)], cwd=project, env=environment, text=True, capture_output=True, check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("source-tree wrapper is retired", result.stderr)
            self.assertFalse(sentinel.exists())
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as refused:
                cli.main(["serve"])
            self.assertEqual(2, refused.exception.code)
            self.assertIn("unknown installed Stygnox command", stderr.getvalue())


if __name__ == "__main__":
    import unittest

    unittest.main()
