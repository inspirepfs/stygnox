"""Fail-closed prerequisites for native transaction renewal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, planning, recovery, scheduler, transactions  # noqa: E402


class RenewalInstalledIdentityTests(TestCase):
    def setUp(self) -> None:
        import base64
        from importlib.metadata import Distribution
        from stygnox import lifecycle

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.root = base / "project"
        self.root.mkdir()
        self.executable = base / "bin" / "stygnox"
        self.executable.parent.mkdir()
        self.executable.write_text("#!/bin/sh\n")
        package_root = base / "site-packages"
        self.package = package_root / "stygnox" / "adoption.py"
        self.package.parent.mkdir(parents=True)
        self.package.write_text("# installed package\n")
        info = package_root / "stygnox-1.0.dist-info"
        info.mkdir()
        metadata = info / "METADATA"
        metadata.write_text("Metadata-Version: 2.1\nName: stygnox\nVersion: 1.0\n")
        self.record = info / "RECORD"
        rows = []
        for path in (self.package, metadata):
            digest = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip("=")
            rows.append(f"{path.relative_to(package_root)},sha256={digest},{path.stat().st_size}")
        self.record.write_text("\n".join([*rows, "stygnox-1.0.dist-info/RECORD,,"]) + "\n")
        command = adoption.CommandIdentity(self.executable, self.package, "1.0")
        for patch in (
            mock.patch.object(adoption, "resolve_installed_command", return_value=command),
            mock.patch.object(lifecycle.metadata, "distribution", return_value=Distribution.at(info)),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.transaction = {"installed_command": str(self.executable)}

    def check(self):
        return transactions._renewal_installed_identity(self.root, self.transaction)

    def test_identity_binds_distribution_and_launcher_without_mutation(self) -> None:
        before = {p: p.read_bytes() for p in self.root.parent.rglob("*") if p.is_file()}
        identity = self.check()
        self.assertEqual(identity, self.check())
        self.assertEqual("stygnox", identity["distribution_name"])
        self.assertEqual(hashlib.sha256(self.executable.read_bytes()).hexdigest(), identity["executable_sha256"])
        self.assertEqual(hashlib.sha256(self.record.read_bytes()).hexdigest(), identity["record_sha256"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.parent.rglob("*") if p.is_file()})

    def test_launcher_drift_changes_identity_digest_even_without_record_hash(self) -> None:
        before = transactions._digest(self.check())
        self.executable.write_text("#!/bin/sh\nexit 2\n")
        self.assertNotEqual(before, transactions._digest(self.check()))

    def test_package_and_metadata_substitution_are_refused(self) -> None:
        for path in (self.package, self.record.parent / "METADATA"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"# changed\n")
                with self.assertRaises(transactions.TransactionError):
                    self.check()
                self.assertEqual(original + b"# changed\n", path.read_bytes())
                path.write_bytes(original)

    def test_predecessor_command_substitution_is_refused(self) -> None:
        self.transaction["installed_command"] = str(self.root.parent / "other-stygnox")
        with self.assertRaisesRegex(transactions.TransactionError, "command"):
            self.check()

    def test_missing_or_malformed_distribution_record_is_refused(self) -> None:
        self.record.unlink()
        with self.assertRaises(transactions.TransactionError):
            self.check()
        self.record.write_text("malformed\n")
        with self.assertRaises(transactions.TransactionError):
            self.check()

    def test_symlinked_launcher_is_refused(self) -> None:
        target = self.executable.with_name("other")
        self.executable.rename(target)
        self.executable.symlink_to(target)
        with self.assertRaises(transactions.TransactionError):
            self.check()


class RenewalPreviewCliTests(TestCase):
    def setUp(self) -> None:
        from test_stygnox_transactions import init_repo

        # Exercise real distribution verification, substituting only discovery
        # of the isolated installation used by this test.
        RenewalInstalledIdentityTests.setUp(self)
        self.root.rmdir()
        init_repo(self.root)
        for module, key, value in (
            (adoption, "RUNTIME_NAME", "renewal-test-runtime"),
            (adoption, "RUNTIME_IGNORE", "/renewal-test-runtime/"),
            (recovery, "RUNTIME_NAME", "renewal-test-runtime"),
        ):
            patch = mock.patch.object(module, key, value)
            patch.start()
            self.addCleanup(patch.stop)
        preview = adoption.build_preview(self.root, "Operator")
        adoption.handoff_adoption(self.root, "Operator", preview["preview_sha256"], "HANDOFF")
        tx = transactions.begin_transaction(self.root, "Operator", "BEGIN")
        controller.activate_controller(self.root, "Operator", "ACTIVATE")
        plan = {
            "goal": "Review", "planning": {"min_steps": 1, "max_steps": 1},
            "repository_authority": "read-only", "repository_mutation_scope": [],
            "repository_mutation_scope_sha256": planning._digest([]),
            "steps": [{"id": 1, "title": "Review", "objective": "Review source",
                       "acceptance": ["Review complete"], "test_change_policy": "none"}],
        }
        baseline = adoption.capture_baseline(self.root).public()
        manifest = {"README.md": hashlib.sha256((self.root / "README.md").read_bytes()).hexdigest()}
        delta = {"approval_manifest_sha256": transactions._digest(manifest),
                 "current_manifest_sha256": transactions._digest(manifest), "paths": []}
        delta["delta_sha256"] = transactions._digest(delta)
        final = {
            "state": "PASS", "phase": "final", "plan_hash": planning._plan_hash(plan),
            "qualified_head": baseline["head"], "qualified_branch": baseline["branch"],
            "repository_baseline_sha256": baseline["sha256"],
            "qualified_path_fingerprints": {}, "plan_owned_paths": [],
            "approval_manifest_sha256": transactions._digest(manifest),
            "repository_mutation_scope_sha256": planning._digest([]),
            "accepted_controller_attribution": {
                "repository_mutation_scope": [], "repository_mutation_scope_sha256": planning._digest([]),
                "accepted_controller_paths": [], "qualified_delta": delta,
            },
        }
        from stygnox import qualification
        final["qualified_delta_sha256"] = qualification._qualified_delta_sha256({}, [])
        final["provenance_sha256"] = transactions._digest(final)
        self.plan = planning._write(self.root, {
            "schema": planning.PLAN_SCHEMA, "status": "READ_ONLY_COMPLETE",
            "operator": "Operator", "transaction_id": tx["transaction_id"],
            "transaction_recovery_baseline_sha256": tx["authority_baseline_sha256"],
            "plan": plan, "plan_hash": planning._plan_hash(plan),
            "repository_mutation_scope": [], "repository_mutation_scope_sha256": planning._digest([]),
            "execution_authority_granted": False, "active_gate": None,
            "self_development_grant": None, "step_resume": None,
            "last_qualification_failure": None, "retirement_rollback_preview": None,
            "step_results": [{"step": 1, "result": "PASS"}],
            "approval_repository_manifest": manifest, "final_qualification": final,
        })
        controller.deactivate_controller(self.root, "Operator", "DEACTIVATE")
        transactions.stop_transaction(self.root, "Operator", "operator-abort", "STOP")

    def snapshot(self):
        return {p.relative_to(self.root.parent).as_posix(): (p.stat().st_mode, p.read_bytes())
                for p in self.root.parent.rglob("*") if p.is_file()}

    def invoke(self, operator="Operator"):
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from stygnox import cli

        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["transaction", "renew-preview", "--project", str(self.root),
                             "--operator", operator])
        return code, out.getvalue(), err.getvalue()

    def test_cli_preview_is_deterministic_and_does_not_mutate_or_grant_authority(self):
        before = self.snapshot()
        code, out, err = self.invoke()
        self.assertEqual(0, code, err)
        preview = json.loads(out)
        self.assertEqual((code, out, err), self.invoke())
        self.assertEqual(before, self.snapshot())
        digest = preview.pop("preview_sha256")
        self.assertEqual(transactions._digest(preview), digest)
        self.assertEqual(str(self.root.resolve()), preview["worktree"])
        self.assertEqual("Operator", preview["operator"])
        self.assertEqual("READ_ONLY_COMPLETE", preview["predecessor"]["plan"]["status"])
        self.assertEqual("IDLE", preview["successor"]["plan_status"])
        self.assertFalse(preview["successor"]["execution_authority_granted"])
        self.assertEqual("RENEW", preview["confirmation"])
        self.assertNotEqual(preview["predecessor"]["transaction"]["transaction_id"],
                            preview["successor"]["transaction_id"])
        with self.assertRaises(planning.PlanningError):
            planning.approved_step_context(self.root, "Operator")
        self.assertEqual(before, self.snapshot())

    def test_cli_refuses_wrong_operator_and_terminal_label_without_proof_read_only(self):
        before = self.snapshot()
        self.assertEqual(2, self.invoke("Someone Else")[0])
        self.assertEqual(before, self.snapshot())
        self.plan["final_qualification"] = None
        planning._write(self.root, self.plan)
        before = self.snapshot()
        code, out, err = self.invoke()
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("qualification", err)
        self.assertEqual(before, self.snapshot())

    def test_launcher_or_runtime_evidence_changes_preview_digest(self):
        code, out, err = self.invoke()
        self.assertEqual(0, code, err)
        first = json.loads(out)["preview_sha256"]
        self.executable.write_text("#!/bin/sh\nexit 0\n")
        code, out, err = self.invoke()
        self.assertEqual(0, code, err)
        second = json.loads(out)["preview_sha256"]
        self.assertNotEqual(first, second)
        (self.root / adoption.RUNTIME_NAME / "historical-evidence.txt").write_text("retained evidence")
        code, out, err = self.invoke()
        self.assertEqual(0, code, err)
        self.assertNotEqual(second, json.loads(out)["preview_sha256"])

    def test_git_drift_is_refused_without_mutation(self):
        (self.root / "README.md").write_text("post-stop drift\n")
        before = self.snapshot()
        code, out, err = self.invoke()
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("baseline", err)
        self.assertEqual(before, self.snapshot())

    def test_preview_cli_in_a_separate_process_is_read_only(self):
        import subprocess

        bootstrap = """
import sys
from pathlib import Path
from importlib.metadata import Distribution
from stygnox import adoption, cli, lifecycle, recovery
adoption.RUNTIME_NAME = recovery.RUNTIME_NAME = 'renewal-test-runtime'
adoption.RUNTIME_IGNORE = '/renewal-test-runtime/'
identity = adoption.CommandIdentity(Path(sys.argv[1]), Path(sys.argv[2]), '1.0')
adoption.resolve_installed_command = lambda *args, **kwargs: identity
distribution = Distribution.at(Path(sys.argv[3]))
lifecycle.metadata.distribution = lambda name: distribution
raise SystemExit(cli.main(sys.argv[4:]))
"""
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-B", "-c", bootstrap, str(self.executable), str(self.package),
             str(self.record.parent), "transaction", "renew-preview", "--project", str(self.root),
             "--operator", "Operator"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(json.loads(self.invoke()[1]), json.loads(result.stdout))
        self.assertEqual(before, self.snapshot())

    def test_cli_refuses_interrupted_scheduler_and_unresolved_gate_without_mutation(self):
        runtime = self.root / adoption.RUNTIME_NAME
        interrupted = {"schema": scheduler.SCHEDULER_SCHEMA, "status": "TURN_RUNNING", "pid": 99999999}
        interrupted["record_sha256"] = transactions._digest(interrupted)
        path = runtime / scheduler.SCHEDULER_RECORD
        path.write_text(json.dumps(interrupted))
        before = self.snapshot()
        code, out, err = self.invoke()
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("scheduler", err)
        self.assertEqual(before, self.snapshot())
        path.unlink()
        self.plan["active_gate"] = {"kind": "human-decision"}
        planning._write(self.root, self.plan)
        before = self.snapshot()
        code, out, err = self.invoke()
        self.assertEqual(2, code)
        self.assertIn("active_gate", err)
        self.assertEqual(before, self.snapshot())

    def test_cli_refuses_tampered_identity_or_controller_without_mutation(self):
        original = self.package.read_bytes()
        self.package.write_bytes(original + b"# changed\n")
        before = self.snapshot()
        code, out, err = self.invoke()
        self.assertEqual(2, code)
        self.assertIn("installed", err)
        self.assertEqual(before, self.snapshot())
        self.package.write_bytes(original)
        path = self.root / adoption.RUNTIME_NAME / controller.CONTROLLER_RECORD
        record = json.loads(path.read_text())
        record["enabled"] = True
        path.write_text(json.dumps(record))
        before = self.snapshot()
        self.assertEqual(2, self.invoke()[0])
        self.assertEqual(before, self.snapshot())


    def renew_preview(self):
        return transactions.build_renewal_preview(self.root, "Operator")

    def test_renew_publishes_empty_epoch_and_preserves_exact_predecessor_bytes(self):
        import base64

        preview = self.renew_preview()
        runtime = self.root / adoption.RUNTIME_NAME
        before = {row["path"]: (self.root / row["path"]).read_bytes()
                  for row in preview["runtime_inventory"]}
        revoked = (runtime / controller.CONTROLLER_RECORD).read_bytes()
        result = transactions.renew_transaction(self.root, "Operator", preview["preview_sha256"], "RENEW")
        tx = transactions._transaction(self.root)
        self.assertEqual("TRANSACTION_RENEWED", result["result"])
        self.assertEqual("ACTIVE", tx["state"])
        self.assertEqual(preview["successor"]["transaction_id"], tx["transaction_id"])
        self.assertNotEqual(preview["predecessor"]["transaction"]["transaction_id"], tx["transaction_id"])
        self.assertEqual(preview["baseline"]["sha256"], tx["authority_baseline_sha256"])
        self.assertEqual(preview["recovery_source"], tx["recovery_source"])
        self.assertEqual(preview["adoption"]["baseline_sha256"], tx["pre_authority_baseline_sha256"])
        archive = json.loads((runtime / tx["predecessor_archive"]).read_text())
        self.assertEqual(before, {row["path"]: base64.b64decode(row["content_base64"])
                                  for row in archive["files"]})
        self.assertEqual(preview, archive["preview"])
        self.assertEqual(revoked, (runtime / controller.CONTROLLER_RECORD).read_bytes())
        state = planning._record(self.root)
        self.assertEqual("IDLE", state["status"])
        self.assertEqual(tx["transaction_id"], state["transaction_id"])
        self.assertEqual([], state["step_results"])
        self.assertEqual([], state["accepted_controller_paths"])
        self.assertIsNone(state["plan"])
        self.assertIsNone(state["self_development_grant"])
        self.assertFalse(state["execution_authority_granted"])
        with self.assertRaises(planning.PlanningError):
            planning.approved_step_context(self.root, "Operator")
        controller.activate_controller(self.root, "Operator", "ACTIVATE")
        with self.assertRaises(planning.PlanningError):
            planning.approved_step_context(self.root, "Operator")

    def test_renew_requires_exact_confirmation_and_digest_without_mutation(self):
        preview = self.renew_preview()
        before = self.snapshot()
        for digest, confirmation in ((preview["preview_sha256"], "BEGIN"),
                                     ("not-a-digest", "RENEW"), ("0" * 64, "RENEW")):
            with self.subTest(digest=digest, confirmation=confirmation):
                with self.assertRaises(transactions.TransactionError):
                    transactions.renew_transaction(self.root, "Operator", digest, confirmation)
                self.assertEqual(before, self.snapshot())

    def test_renew_refuses_stale_launcher_or_runtime_preview(self):
        for drift in ("launcher", "runtime"):
            with self.subTest(drift=drift):
                preview = self.renew_preview()
                path = self.executable if drift == "launcher" else self.root / adoption.RUNTIME_NAME / "evidence.txt"
                path.write_text("changed evidence\n")
                before = self.snapshot()
                with self.assertRaisesRegex(transactions.TransactionError, "stale"):
                    transactions.renew_transaction(self.root, "Operator", preview["preview_sha256"], "RENEW")
                self.assertEqual(before, self.snapshot())

    def test_interrupted_publication_never_exposes_execution_authority(self):
        original = adoption.write_runtime_record
        runtime = self.root / adoption.RUNTIME_NAME
        preview = self.renew_preview()
        revoked = (runtime / controller.CONTROLLER_RECORD).read_bytes()

        def fail_transaction(root, name, payload, *, actor):
            if name == transactions.TRANSACTION_RECORD:
                raise OSError("injected publication interruption")
            return original(root, name, payload, actor=actor)

        with mock.patch.object(adoption, "write_runtime_record", side_effect=fail_transaction):
            with self.assertRaisesRegex(transactions.TransactionError, "interruption"):
                transactions.renew_transaction(self.root, "Operator", preview["preview_sha256"], "RENEW")
        self.assertEqual("STOPPED", transactions._transaction(self.root)["state"])
        self.assertEqual("IDLE", planning._record(self.root)["status"])
        self.assertEqual(revoked, (runtime / controller.CONTROLLER_RECORD).read_bytes())
        self.assertTrue((runtime / f"renewal-predecessor-{preview['preview_sha256']}.json").is_file())
        with self.assertRaises(controller.ControllerError):
            controller.activate_controller(self.root, "Operator", "ACTIVATE")
        with self.assertRaises(planning.PlanningError):
            planning.approved_step_context(self.root, "Operator")
        with self.assertRaises(transactions.TransactionError):
            self.renew_preview()


class RenewalRecoveryLineageTests(TestCase):
    def setUp(self) -> None:
        from test_stygnox_transactions import identity, init_repo

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.root = base / "repo"
        init_repo(self.root)
        for module, key, value in (
            (adoption, "RUNTIME_NAME", "renewal-test-runtime"),
            (adoption, "RUNTIME_IGNORE", "/renewal-test-runtime/"),
            (recovery, "RUNTIME_NAME", "renewal-test-runtime"),
        ):
            patch = mock.patch.object(module, key, value)
            patch.start()
            self.addCleanup(patch.stop)
        command = mock.patch.object(adoption, "resolve_installed_command", return_value=identity(base))
        command.start()
        self.addCleanup(command.stop)
        preview = adoption.build_preview(self.root, "Operator")
        adoption.handoff_adoption(self.root, "Operator", preview["preview_sha256"], "HANDOFF")
        transactions.begin_transaction(self.root, "Operator", "BEGIN")
        transactions.stop_transaction(self.root, "Operator", "operator-abort", "STOP")
        self.transaction = transactions._renewal_stopped_transaction(self.root, "Operator")
        self.runtime = self.root / adoption.RUNTIME_NAME
        self.handoff_path = self.runtime / "adoption.json"

    def check(self):
        return transactions._renewal_adoption_lineage(self.root, self.transaction)

    def test_original_recovery_lineage_is_read_only_after_project_changes(self) -> None:
        (self.root / "README.md").write_text("completed predecessor work\n")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(json.loads(self.handoff_path.read_text()), self.check())
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_substituted_handoff_lineage_is_refused(self) -> None:
        original = self.handoff_path.read_bytes()
        for key, value in (
            ("operator", "Other"), ("preview_sha256", "0" * 64),
            ("baseline_sha256", "0" * 64), ("journey", "dirty"),
            ("recovery_source", {}),
        ):
            with self.subTest(key=key):
                body = json.loads(original)
                body[key] = value
                self.handoff_path.write_text(json.dumps(body))
                with self.assertRaises(transactions.TransactionError):
                    self.check()
        self.handoff_path.write_bytes(original)

    def test_baseline_substitution_is_refused_even_with_recomputed_hash(self) -> None:
        original = self.handoff_path.read_bytes()
        for key in ("baseline", "authority_baseline"):
            with self.subTest(key=key):
                body = json.loads(original)
                baseline = body[key]
                baseline["worktree"] = "/other/project"
                baseline.pop("sha256")
                baseline["sha256"] = transactions._digest(baseline)
                self.handoff_path.write_text(json.dumps(body))
                with self.assertRaises(transactions.TransactionError):
                    self.check()

    def test_recovery_archive_drift_is_refused_without_repair(self) -> None:
        archive = self.runtime / recovery.INTERNAL_RECOVERY_DIR / recovery.INTERNAL_ARCHIVE
        archive.write_bytes(b"substituted archive")
        before = self.handoff_path.read_bytes()
        with self.assertRaises(transactions.TransactionError):
            self.check()
        self.assertEqual(b"substituted archive", archive.read_bytes())
        self.assertEqual(before, self.handoff_path.read_bytes())

    def test_authority_baseline_substitution_is_refused_with_valid_digest(self) -> None:
        body = json.loads(self.handoff_path.read_text())
        baseline = body["authority_baseline"]
        baseline["branch"] = "substituted"
        baseline.pop("sha256")
        baseline["sha256"] = transactions._digest(baseline)
        self.handoff_path.write_text(json.dumps(body))
        with self.assertRaisesRegex(transactions.TransactionError, "authority baseline"):
            self.check()

    def test_real_dirty_and_unborn_recovery_sources_preserve_lineage(self) -> None:
        from test_stygnox_transactions import external_evidence, init_repo, make_dirty

        for journey in ("dirty", "new-unborn"):
            with self.subTest(journey=journey):
                root = self.root.parent / journey
                init_repo(root, commit=journey != "new-unborn")
                if journey == "dirty":
                    make_dirty(root)
                else:
                    (root / "new.txt").write_text("original unborn material\n")
                preview = adoption.build_preview(root, "Operator")
                evidence = None
                if journey == "dirty":
                    evidence = external_evidence(root, preview, self.root.parent / "evidence")
                    preview = adoption.build_preview(root, "Operator", dirty_evidence=evidence)
                adoption.handoff_adoption(root, "Operator", preview["preview_sha256"], "HANDOFF", dirty_evidence=evidence)
                transactions.begin_transaction(root, "Operator", "BEGIN")
                transactions.stop_transaction(root, "Operator", "operator-abort", "STOP")
                tx = transactions._renewal_stopped_transaction(root, "Operator")
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                handoff = transactions._renewal_adoption_lineage(root, tx)
                self.assertEqual(journey, handoff["journey"])
                self.assertEqual(tx["pre_authority_baseline_sha256"], handoff["baseline_sha256"])
                self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()})
                if evidence is not None:
                    manifest = Path(tx["recovery_source"]["manifest_path"])
                    manifest.write_text("{}")
                    with self.assertRaises(transactions.TransactionError):
                        transactions._renewal_adoption_lineage(root, tx)

    def test_checkpoint_path_escape_and_malformed_metadata_are_refused(self) -> None:
        path = self.runtime / recovery.INTERNAL_RECOVERY_DIR / recovery.INTERNAL_METADATA
        original = path.read_bytes()
        for raw in ("[]", "{", json.dumps({**json.loads(original), "archive": "../../outside.tar"})):
            with self.subTest(raw=raw):
                path.write_text(raw)
                with self.assertRaises(transactions.TransactionError):
                    self.check()

    def test_symlinked_handoff_and_recovery_artifacts_are_refused(self) -> None:
        for path in (self.handoff_path, self.runtime / recovery.INTERNAL_RECOVERY_DIR / recovery.INTERNAL_ARCHIVE):
            with self.subTest(path=path.name):
                contents = path.read_bytes()
                target = self.root.parent / (path.name + ".substitute")
                target.write_bytes(contents)
                path.unlink()
                path.symlink_to(target)
                with self.assertRaises(transactions.TransactionError):
                    self.check()
                path.unlink()
                path.write_bytes(contents)


class RenewalPlanObligationTests(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        runtime = mock.patch.object(adoption, "RUNTIME_NAME", "renewal-test-runtime")
        runtime.start()
        self.addCleanup(runtime.stop)
        self.path = self.root / adoption.RUNTIME_NAME / planning.PLAN_RECORD
        self.path.parent.mkdir()
        self.body = {
            "schema": planning.PLAN_SCHEMA, "status": "IDLE",
            "operator": "Operator", "transaction_id": "TX-predecessor",
            "plan": None, "plan_hash": None,
            "execution_authority_granted": False,
            "active_gate": None, "self_development_grant": None,
            "step_resume": None, "last_qualification_failure": None,
            "retirement_rollback_preview": None, "step_results": [],
        }

    def write(self) -> None:
        body = dict(self.body)
        body["record_sha256"] = planning._digest(body)
        self.path.write_text(json.dumps(body), encoding="utf-8")

    def check(self):
        return planning._renewal_plan_obligations(
            self.root, "Operator", transaction_id="TX-predecessor",
        )

    def test_obligation_check_is_read_only_and_grants_no_execution(self) -> None:
        self.write()
        before = self.path.read_bytes()
        self.assertEqual(json.loads(before), self.check())
        with mock.patch.object(adoption, "resolve_worktree", return_value=self.root):
            with self.assertRaises(planning.PlanningError):
                planning.approved_step_context(self.root, "Operator")
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_obligation_fields_are_not_treated_as_cleared(self) -> None:
        for key in tuple(self.body):
            with self.subTest(key=key):
                value = self.body.pop(key)
                self.write()
                with self.assertRaises(planning.PlanningError):
                    self.check()
                self.body[key] = value

    def test_unresolved_or_malformed_obligations_are_refused(self) -> None:
        for key in (
            "active_gate", "self_development_grant", "step_resume",
            "last_qualification_failure", "retirement_rollback_preview",
        ):
            for value in ({"state": "PENDING"}, {}, [], False, ""):
                with self.subTest(key=key, value=value):
                    self.body[key] = value
                    self.write()
                    with self.assertRaises(planning.PlanningError):
                        self.check()
            self.body[key] = None

    def test_substituted_lineage_and_active_status_are_refused(self) -> None:
        for key, value in (
            ("operator", "Other"), ("transaction_id", "TX-other"),
            ("status", "APPROVED"), ("status", "BLOCKED_HUMAN"),
            ("status", "STEPS_COMPLETE"), ("status", "READY_TO_COMMIT"),
            ("status", []), ("execution_authority_granted", True),
            ("execution_authority_granted", 0), ("plan_hash", "a" * 64),
        ):
            with self.subTest(key=key, value=value):
                previous = self.body[key]
                self.body[key] = value
                self.write()
                with self.assertRaises(planning.PlanningError):
                    self.check()
                self.body[key] = previous

    def test_terminal_labels_require_a_plan(self) -> None:
        for status in ("COMMITTED", "PUSHED", "READ_ONLY_COMPLETE"):
            with self.subTest(status=status):
                self.body["status"] = status
                self.write()
                with self.assertRaises(planning.PlanningError):
                    self.check()

    def test_pending_or_malformed_transition_evidence_is_refused(self) -> None:
        for rows in (
            None, {}, [None], [{"post_qualification_transition": {}}],
            [{"post_qualification_transition": {"state": "PENDING"}}],
            [{"post_qualification_transition": {"state": "COMPLETE"}}],
            [{"post_qualification_transition": []}],
        ):
            with self.subTest(rows=rows):
                self.body["step_results"] = rows
                self.write()
                with self.assertRaises(planning.PlanningError):
                    self.check()

    def test_terminal_required_transition_cannot_be_omitted(self) -> None:
        plan = {
            "goal": "Review", "planning": {"min_steps": 1, "max_steps": 1},
            "repository_authority": "read-only", "repository_mutation_scope": [],
            "repository_mutation_scope_sha256": planning._digest([]),
            "steps": [{
                "id": 1, "title": "Review", "objective": "Review source",
                "acceptance": ["Review complete"], "test_change_policy": "none",
                planning.POST_QUALIFICATION_TRANSITION_FIELD: planning.INSTALLED_SUCCESSOR_HANDOFF,
            }],
        }
        self.body.update({
            "status": "READ_ONLY_COMPLETE", "plan": plan,
            "plan_hash": planning._plan_hash(plan),
            "repository_mutation_scope": [],
            "repository_mutation_scope_sha256": planning._digest([]),
        })
        for rows in ([], [{"step": 1, "result": "PASS"}]):
            with self.subTest(rows=rows):
                self.body["step_results"] = rows
                self.write()
                with self.assertRaises(planning.PlanningError):
                    self.check()
        self.body["step_results"] = [{
            "step": 1, "result": "PASS", "post_qualification_transition": {
                "state": "COMPLETE", "transition_receipt_sha256": "a" * 64,
            },
        }]
        self.write()
        before = self.path.read_bytes()
        self.assertEqual(json.loads(before), self.check())
        self.assertEqual(before, self.path.read_bytes())
        self.body["step_results"] *= 2
        self.write()
        with self.assertRaises(planning.PlanningError):
            self.check()

    def test_missing_malformed_tampered_and_symlinked_records_are_refused(self) -> None:
        with self.assertRaises(planning.PlanningError):
            self.check()
        self.write()
        tampered = json.loads(self.path.read_text())
        tampered["operator"] = "Other"
        for raw in (b"{", b"[]", b"\xff", json.dumps(tampered).encode()):
            self.path.write_bytes(raw)
            with self.assertRaises(planning.PlanningError):
                self.check()
        self.path.unlink()
        target = self.root / "substituted.json"
        self.path.symlink_to(target)
        with self.assertRaises(planning.PlanningError):
            self.check()
        target.write_text("{}")
        with self.assertRaises(planning.PlanningError):
            self.check()

    def terminal_plan(self, status="READ_ONLY_COMPLETE", authority="read-only") -> None:
        scope = [] if authority == "read-only" else ["src/example.py"]
        plan = {
            "goal": "Review", "planning": {"min_steps": 2, "max_steps": 2},
            "repository_authority": authority, "repository_mutation_scope": scope,
            "repository_mutation_scope_sha256": planning._digest(scope),
            "steps": [{
                "id": index, "title": "Review", "objective": "Review source",
                "acceptance": ["Review complete"], "test_change_policy": "none",
                planning.POST_QUALIFICATION_TRANSITION_FIELD: None,
            } for index in (1, 2)],
        }
        self.body.update({
            "status": status, "plan": plan, "plan_hash": planning._plan_hash(plan),
            "repository_mutation_scope": scope,
            "repository_mutation_scope_sha256": planning._digest(scope),
            "step_results": [{"step": index, "result": "PASS"} for index in (1, 2)],
        })

    def test_terminal_plan_requires_exact_pass_results_for_every_step(self) -> None:
        self.terminal_plan()
        for rows in (
            [], [{"step": 1, "result": "PASS"}],
            [{"step": 1, "result": "PASS"}, {"step": 1, "result": "PASS"}],
            [{"step": 1, "result": "PASS"}, {"step": 3, "result": "PASS"}],
            [{"step": True, "result": "PASS"}, {"step": 2, "result": "PASS"}],
            [{"step": "1", "result": "PASS"}, {"step": 2, "result": "PASS"}],
            [{"step": 1, "result": "PASS"}, {"step": 2, "result": "FAIL"}],
            [{"step": 1, "result": "PASS"}, {"step": 2}],
            [{"step": 1, "result": "PASS"}, {"step": 2, "result": "PASS"}, {}],
        ):
            with self.subTest(rows=rows):
                self.body["step_results"] = rows
                self.write()
                before = self.path.read_bytes()
                with self.assertRaises(planning.PlanningError):
                    self.check()
                self.assertEqual(before, self.path.read_bytes())

    def test_terminal_status_must_match_plan_repository_authority(self) -> None:
        for status, authority in (
            ("COMMITTED", "read-only"), ("PUSHED", "read-only"),
            ("READ_ONLY_COMPLETE", "write"),
        ):
            with self.subTest(status=status, authority=authority):
                self.terminal_plan(status, authority)
                self.write()
                with self.assertRaises(planning.PlanningError):
                    self.check()

    def test_completed_step_obligations_preserve_predecessor_without_authority(self) -> None:
        for status, authority in (
            ("COMMITTED", "write"), ("PUSHED", "write"),
            ("READ_ONLY_COMPLETE", "read-only"),
        ):
            with self.subTest(status=status):
                self.terminal_plan(status, authority)
                self.write()
                before = self.path.read_bytes()
                self.assertEqual(json.loads(before), self.check())
                with mock.patch.object(adoption, "resolve_worktree", return_value=self.root):
                    with self.assertRaises(planning.PlanningError):
                        planning.approved_step_context(self.root, "Operator")
                self.assertEqual(before, self.path.read_bytes())


class RenewalSchedulerTests(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        runtime = mock.patch.object(adoption, "RUNTIME_NAME", "renewal-test-runtime")
        runtime.start()
        self.addCleanup(runtime.stop)
        self.record_path = self.root / adoption.RUNTIME_NAME / scheduler.SCHEDULER_RECORD
        self.record_path.parent.mkdir()

    def record(self, **updates: object) -> dict:
        body = {
            "schema": scheduler.SCHEDULER_SCHEMA,
            "status": "STOPPED_QUALIFICATION",
            "operator": "Operator",
            "worktree": str(self.root),
            "transaction_id": "TX-predecessor",
            "plan_hash": "a" * 64,
            "schedule_preview_sha256": "b" * 64,
            "pid": None,
            "finished_at": "2026-10-09T12:00:00+00:00",
            "stop_reason": "qualification-required",
        }
        body.update(updates)
        self.write(body)
        return body

    def write(self, body: dict) -> None:
        body = dict(body)
        body.pop("record_sha256", None)
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        body["record_sha256"] = hashlib.sha256(encoded).hexdigest()
        self.record_path.write_text(json.dumps(body), encoding="utf-8")

    def check(self):
        return scheduler.renewal_quiescence(
            self.root, "Operator", transaction_id="TX-predecessor", plan_hash="a" * 64,
        )

    def test_absent_scheduler_is_read_only(self) -> None:
        before = list(self.root.rglob("*"))
        self.assertIsNone(self.check())
        self.assertEqual(before, list(self.root.rglob("*")))

    def test_stopped_scheduler_returns_exact_evidence_without_mutation(self) -> None:
        self.record()
        before = self.record_path.read_bytes()
        self.assertEqual(json.loads(before), self.check())
        self.assertEqual(before, self.record_path.read_bytes())

    def test_active_and_interrupted_ownership_refused_even_without_live_pid(self) -> None:
        for status in ("RUNNING", "TURN_RUNNING", "INTERRUPTED"):
            for pid in (None, 0, 999999999):
                with self.subTest(status=status, pid=pid):
                    self.record(status=status, pid=pid)
                    with self.assertRaisesRegex(scheduler.SchedulerError, "active/interrupted"):
                        self.check()

    def test_substituted_lineage_is_refused(self) -> None:
        for key, value in (
            ("operator", "Another operator"), ("worktree", "/another/project"),
            ("transaction_id", "TX-other"), ("plan_hash", "c" * 64),
        ):
            with self.subTest(key=key):
                self.record(**{key: value})
                with self.assertRaises(scheduler.SchedulerError):
                    self.check()

    def test_status_label_without_release_evidence_is_refused(self) -> None:
        for key in ("pid", "finished_at", "stop_reason", "schedule_preview_sha256"):
            with self.subTest(key=key):
                body = self.record()
                del body[key]
                self.write(body)
                with self.assertRaises(scheduler.SchedulerError):
                    self.check()
        for updates in (
            {"status": "UNKNOWN"}, {"pid": 123}, {"finished_at": "invalid"},
            {"status": []},
            {"finished_at": "2026-10-09"}, {"stop_reason": ""},
            {"schedule_preview_sha256": "bad"},
        ):
            with self.subTest(updates=updates):
                self.record(**updates)
                with self.assertRaises(scheduler.SchedulerError):
                    self.check()

    def test_malformed_and_tampered_records_are_refused(self) -> None:
        for raw in ("{", "[]", '{"schema":"unknown"}'):
            self.record_path.write_text(raw, encoding="utf-8")
            with self.assertRaises(scheduler.SchedulerError):
                self.check()
        self.record()
        body = json.loads(self.record_path.read_text())
        body["stop_reason"] = "substituted"
        self.record_path.write_text(json.dumps(body))
        with self.assertRaisesRegex(scheduler.SchedulerError, "integrity"):
            self.check()

    def test_dangling_and_existing_symlinks_are_not_absent_evidence(self) -> None:
        target = self.root / "substituted.json"
        self.record_path.symlink_to(target)
        with self.assertRaises(scheduler.SchedulerError):
            self.check()
        target.write_text("{}")
        with self.assertRaises(scheduler.SchedulerError):
            self.check()


class RenewalStoppedTransactionTests(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        runtime = mock.patch.object(adoption, "RUNTIME_NAME", "renewal-test-runtime")
        runtime.start()
        self.addCleanup(runtime.stop)
        self.path = self.root / adoption.RUNTIME_NAME / transactions.TRANSACTION_RECORD
        self.path.parent.mkdir()
        baseline = {
            "worktree": str(self.root), "journey": "clean", "head": "a" * 40,
            "branch": "main", "status": "", "index_sha256": "b" * 64,
            "staged_sha256": "c" * 64, "unstaged_sha256": "d" * 64,
            "untracked": [], "dirty_categories": [],
        }
        baseline["sha256"] = transactions._digest(baseline)
        self.body = {
            "schema": transactions.TRANSACTION_SCHEMA, "state": "STOPPED",
            "transaction_id": "TX-predecessor", "operator": "Operator",
            "opened_at": "2026-10-09T11:00:00Z",
            "handoff_preview_sha256": "e" * 64,
            "pre_authority_baseline_sha256": "f" * 64,
            "authority_baseline_sha256": "a" * 64,
            "journey": "clean", "installed_command": "/installed/bin/stygnox",
            "recovery_source": {
                "kind": "controller-internal", "checkpoint_sha256": "b" * 64,
                "baseline_sha256": "f" * 64,
            },
            "authority": {
                "scope": "d8.3-transaction-and-recovery-only",
                "controller_execution": False, "safe_stop_required_before_restore": True,
            },
            "safe_stop": {
                "reason": "operator-abort", "stopped_at": "2026-10-09T12:00:00Z",
                "baseline": baseline, "authority_revoked": True, "project_mutation": False,
            },
        }

    def write(self) -> None:
        body = dict(self.body)
        body["record_sha256"] = transactions._digest(body)
        self.path.write_text(json.dumps(body))

    def check(self):
        return transactions._renewal_stopped_transaction(self.root, "Operator")

    def test_stopped_evidence_is_validated_without_mutation(self) -> None:
        self.write()
        before = self.path.read_bytes()
        self.assertEqual(json.loads(before), self.check())
        self.assertEqual(before, self.path.read_bytes())

    def test_status_alone_and_missing_stop_fields_are_refused(self) -> None:
        stop = self.body["safe_stop"]
        for key in tuple(stop):
            with self.subTest(key=key):
                self.body["safe_stop"] = {k: v for k, v in stop.items() if k != key}
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()
        self.body["safe_stop"] = None
        self.write()
        with self.assertRaises(transactions.TransactionError):
            self.check()

    def test_active_state_operator_and_integrity_drift_are_refused(self) -> None:
        for key, value in (("state", "ACTIVE"), ("operator", "Other"), ("transaction_id", "")):
            with self.subTest(key=key):
                original = self.body[key]
                self.body[key] = value
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()
                self.body[key] = original
        self.write()
        body = json.loads(self.path.read_text())
        body["record_sha256"] = "0" * 64
        self.path.write_text(json.dumps(body))
        with self.assertRaisesRegex(transactions.TransactionError, "integrity"):
            self.check()

    def test_invalid_stop_evidence_is_refused_even_with_valid_outer_digest(self) -> None:
        stop = self.body["safe_stop"]
        for key, value in (
            ("authority_revoked", 1), ("project_mutation", 0), ("reason", "unknown"),
            ("stopped_at", "invalid"), ("stopped_at", "2026-10-09"),
            ("baseline", {}), ("baseline", {**stop["baseline"], "branch": "substituted"}),
        ):
            with self.subTest(key=key, value=value):
                self.body["safe_stop"] = {**stop, key: value}
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()

    def test_substituted_project_is_refused_even_with_valid_baseline_digest(self) -> None:
        baseline = self.body["safe_stop"]["baseline"]
        baseline["worktree"] = "/another/project"
        del baseline["sha256"]
        baseline["sha256"] = transactions._digest(baseline)
        self.write()
        with self.assertRaises(transactions.TransactionError):
            self.check()

    def test_symlink_and_malformed_transaction_records_are_refused(self) -> None:
        target = self.root / "substituted.json"
        self.path.symlink_to(target)
        with self.assertRaises(transactions.TransactionError):
            self.check()
        target.write_text("{}")
        with self.assertRaises(transactions.TransactionError):
            self.check()
        self.path.unlink()
        for raw in ("{", "[]", '{"schema":"unsupported"}'):
            self.path.write_text(raw)
            with self.assertRaises(transactions.TransactionError):
                self.check()

    def test_missing_transaction_lineage_fields_are_refused(self) -> None:
        for key in (
            "opened_at", "handoff_preview_sha256", "pre_authority_baseline_sha256",
            "authority_baseline_sha256", "journey", "installed_command", "recovery_source", "authority",
        ):
            with self.subTest(key=key):
                value = self.body.pop(key)
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()
                self.body[key] = value

    def test_malformed_transaction_lineage_is_refused(self) -> None:
        for key, value in (
            ("opened_at", "2026-10-10T12:00:00Z"), ("opened_at", "2026-10-09"),
            ("handoff_preview_sha256", "invalid"), ("pre_authority_baseline_sha256", None),
            ("authority_baseline_sha256", []), ("journey", "unknown"),
            ("installed_command", "relative/bin/stygnox"), ("recovery_source", {}),
            ("authority", {"controller_execution": True}),
        ):
            with self.subTest(key=key, value=value):
                original = self.body[key]
                self.body[key] = value
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()
                self.body[key] = original

    def test_inconsistent_stop_baseline_is_refused_with_recomputed_digests(self) -> None:
        original = self.body["safe_stop"]["baseline"]
        for updates in (
            {"head": None}, {"head": "invalid"}, {"head": []},
            {"journey": "new-unborn"}, {"journey": "dirty"},
            {"status": " M tracked.txt\n"}, {"dirty_categories": ["unknown"]},
            {"untracked": [None]}, {"untracked": [{"path": "../escape"}]},
        ):
            with self.subTest(updates=updates):
                baseline = {**original, **updates}
                baseline.pop("sha256")
                baseline["sha256"] = transactions._digest(baseline)
                self.body["safe_stop"]["baseline"] = baseline
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()
        self.body["safe_stop"]["baseline"] = original

    def controller_record(self, **updates: object) -> Path:
        body = {
            "schema": controller.CONTROLLER_SCHEMA,
            "operator": "Operator", "transaction_id": self.body["transaction_id"],
            "authority_baseline_sha256": self.body["authority_baseline_sha256"],
            "installed_command": self.body["installed_command"],
            "enabled": True, "controller_execution_enabled": True,
        }
        body.update(updates)
        body["record_sha256"] = transactions._digest(body)
        path = self.path.parent / controller.CONTROLLER_RECORD
        path.write_text(json.dumps(body))
        return path

    def test_dirty_recovery_bindings_require_the_original_baseline(self) -> None:
        self.body["journey"] = "dirty"
        source = {
            "kind": "operator-external", "baseline_sha256": "f" * 64,
            "attestation_path": "/external/attestation.json", "attestation_sha256": "1" * 64,
            "capture_path": "/external/capture.tar.gz", "capture_sha256": "2" * 64,
            "manifest_path": "/external/manifest.json", "manifest_sha256": "3" * 64,
        }
        self.body["recovery_source"] = source
        self.write()
        self.assertEqual(source, self.check()["recovery_source"])
        for key in source:
            with self.subTest(key=key):
                self.body["recovery_source"] = {k: v for k, v in source.items() if k != key}
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()
        self.body["recovery_source"] = {**source, "baseline_sha256": "0" * 64}
        self.write()
        with self.assertRaises(transactions.TransactionError):
            self.check()

    def test_dirty_and_unborn_stop_baselines_remain_valid(self) -> None:
        baseline = self.body["safe_stop"]["baseline"]
        baseline.update({
            "journey": "dirty", "status": "?? new.txt\n", "dirty_categories": ["untracked"],
            "untracked": [{"path": "new.txt", "type": "file", "mode": "0644", "sha256": "4" * 64}],
        })
        for head, journey in (("a" * 40, "dirty"), (None, "new-unborn")):
            with self.subTest(journey=journey):
                baseline.update(head=head, journey=journey)
                baseline.pop("sha256")
                baseline["sha256"] = transactions._digest(baseline)
                self.write()
                self.assertEqual(baseline, self.check()["safe_stop"]["baseline"])

    def test_malformed_untracked_rows_are_refused(self) -> None:
        baseline = self.body["safe_stop"]["baseline"]
        baseline.update(journey="dirty", status="?? new.txt\n", dirty_categories=["untracked"])
        valid = {"path": "new.txt", "type": "file", "mode": "0644", "sha256": "4" * 64}
        for updates in (
            {"path": "../escape"}, {"path": "/absolute"}, {"path": ""},
            {"type": "directory"}, {"mode": 644}, {"sha256": "invalid"},
        ):
            with self.subTest(updates=updates):
                baseline["untracked"] = [{**valid, **updates}]
                baseline.pop("sha256")
                baseline["sha256"] = transactions._digest(baseline)
                self.write()
                with self.assertRaises(transactions.TransactionError):
                    self.check()

    def check_authority(self):
        return transactions._renewal_predecessor_authority(self.root, "Operator")

    def test_safe_stop_requires_separate_explicit_controller_deactivation(self) -> None:
        self.write()
        path = self.controller_record()
        before = path.read_bytes()
        with self.assertRaisesRegex(transactions.TransactionError, "revoked"):
            self.check_authority()
        self.assertEqual(before, path.read_bytes())
        with mock.patch.object(adoption, "resolve_worktree", return_value=self.root):
            controller.deactivate_controller(self.root, "Operator", "DEACTIVATE")
        before = {p.name: p.read_bytes() for p in self.path.parent.iterdir()}
        transaction, revoked = self.check_authority()
        self.assertEqual(json.loads(self.path.read_text()), transaction)
        self.assertEqual(json.loads(path.read_text()), revoked)
        self.assertIs(revoked["controller_execution_enabled"], False)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.path.parent.iterdir()})

    def test_controller_disabled_labels_do_not_prove_revocation(self) -> None:
        self.write()
        for updates in (
            {}, {"deactivation_reason": "unknown"},
            {"deactivation_reason": "operator-confirmed", "enabled": 0},
            {"deactivation_reason": "operator-confirmed", "controller_execution_enabled": 0},
        ):
            with self.subTest(updates=updates):
                self.controller_record(**{
                    "enabled": False, "controller_execution_enabled": False, **updates,
                })
                with self.assertRaises(transactions.TransactionError):
                    self.check_authority()

    def test_revoked_controller_lineage_must_match_stopped_transaction(self) -> None:
        self.write()
        for key, value in (
            ("operator", "Other"), ("transaction_id", "TX-other"),
            ("authority_baseline_sha256", "c" * 64),
            ("installed_command", "/another/bin/stygnox"),
        ):
            with self.subTest(key=key):
                self.controller_record(**{
                    "enabled": False, "controller_execution_enabled": False,
                    "deactivation_reason": "operator-confirmed", key: value,
                })
                with self.assertRaises(transactions.TransactionError):
                    self.check_authority()

    def test_missing_malformed_symlinked_and_tampered_controllers_are_refused(self) -> None:
        self.write()
        with self.assertRaises(transactions.TransactionError):
            self.check_authority()
        path = self.controller_record(
            enabled=False, controller_execution_enabled=False,
            deactivation_reason="operator-confirmed",
        )
        body = json.loads(path.read_text())
        body["operator"] = "Other"
        for raw in ("{", "[]", json.dumps(body)):
            path.write_text(raw)
            with self.assertRaises(transactions.TransactionError):
                self.check_authority()
        path.unlink()
        target = self.root / "substituted-controller.json"
        path.symlink_to(target)
        with self.assertRaises(transactions.TransactionError):
            self.check_authority()
        target.write_text("{}")
        with self.assertRaises(transactions.TransactionError):
            self.check_authority()
