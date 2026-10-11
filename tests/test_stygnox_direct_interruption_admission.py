"""C2b admission preflight hostile tests; all exercised paths remain read-only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import hashlib

from stygnox import direct_interruption as d
from stygnox import direct_interruption_admission as a
from stygnox import direct_interruption_fence as f
from stygnox import direct_interruption_handoff as h


class AdmissionPreflight(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = self.root / "old-cli"
        self.new = self.root / "new-cli"
        self.old.write_bytes(b"old")
        self.new.write_bytes(b"new")
        self.plan = {
            "schema": "stygnox_plan_state_v1", "record_sha256": "a" * 64,
            "status": "APPROVED", "execution_authority_granted": True,
            "operator": "operator", "plan_hash": "b" * 64,
            "transaction_id": "TX-1", "current_step": 2,
            "active_gate": None, "self_development_grant": None,
            "direct_interruption_pending": None,
        }
        self.ctrl = {"record_sha256": "c" * 64,
                     "installed_command": str(self.old), "enabled": True}
        self.tx = {"record_sha256": "d" * 64, "state": "ACTIVE",
                   "installed_command": str(self.old)}
        self.installed = {"executable": str(self.new), "record_sha256": "e" * 64}
        self.wheel = {"sha256": "f" * 64}
        self.handoff = {
            "schema": h.SCHEMA, "worktree": str(self.root),
            "operator": "operator", "plan_hash": "b" * 64,
            "transaction_id": "TX-1", "step": 2,
            "predecessor_plan_record_sha256": "a" * 64,
            "predecessor_controller_record_sha256": "c" * 64,
            "predecessor_transaction_record_sha256": "d" * 64,
            "predecessor_installed_executable": {
                "path": str(self.old), "sha256": hashlib.sha256(b"old").hexdigest()},
            "candidate_installed_identity": self.installed,
            "candidate_wheel_identity": self.wheel,
            "review_preview_sha256": "1" * 64,
            "manifest_proof_sha256": "2" * 64,
            "origin_preview_sha256": "3" * 64,
            "authority_changed": False,
            "admissible": False,
            "old_controller_fencing_proved": False,
            "fresh_process_authority_transfer_proved": False,
            "candidate_is_authorised_successor": False,
        }
        self.handoff["preview_sha256"] = d._digest(self.handoff)
        patchers = [
            mock.patch.object(a.adoption, "resolve_worktree", return_value=self.root),
            mock.patch.object(h, "build_handoff_preview", return_value=self.handoff),
            mock.patch.object(a.planning, "_record", return_value=self.plan),
            mock.patch.object(a.controller, "_controller", return_value=self.ctrl),
            mock.patch.object(a.transactions, "_transaction", return_value=self.tx),
            mock.patch.object(a.recovery, "_checked", side_effect=lambda v: v),
            mock.patch.object(a.lifecycle, "_installed_identity", return_value=self.installed),
            mock.patch.object(a.lifecycle, "_wheel_identity", return_value=self.wheel),
            mock.patch.object(a.sys, "argv", [str(self.new), "direct-interruption"]),
            mock.patch.object(a.recovery, "_quiescent", return_value=None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_preview(self):
        return a.build_admission_preflight(self.root, self.root / "origin", "3" * 64,
                                           ["src/stygnox/transactions.py"], self.root / "candidate.whl")

    def test_preflight_is_bound_and_cannot_authorise(self):
        preview = self.run_preview()
        self.assertEqual(preview["schema"], a.SCHEMA)
        self.assertEqual(preview["review_preview_sha256"], "1" * 64)
        self.assertEqual(preview["fence_design_sha256"], f.build_fence_design(self.handoff)["preview_sha256"])
        self.assertEqual(preview["old_binary_fresh_process_refusal"], "UNPROVED")
        self.assertEqual(preview["successor_execution_admission"], "DISABLED")
        self.assertFalse(preview["admissible"])
        self.assertFalse(preview["authority_changed"])
        self.assertEqual(preview["preview_sha256"], d._digest({k: v for k, v in preview.items() if k != "preview_sha256"}))

    def test_original_installed_binary_substitution_refused(self):
        self.old.write_bytes(b"changed")
        with self.assertRaisesRegex(a.AdmissionRefused, "original installed executable changed"):
            self.run_preview()

    def test_original_plan_drift_refused(self):
        self.plan["record_sha256"] = "9" * 64
        with self.assertRaisesRegex(a.AdmissionRefused, "identity changed"):
            self.run_preview()

    def test_forged_active_human_gate_refused(self):
        self.plan["active_gate"] = {"gate_id": "open"}
        with self.assertRaisesRegex(a.AdmissionRefused, "identity changed"):
            self.run_preview()

    def test_old_controller_command_substitution_refused(self):
        self.ctrl["installed_command"] = str(self.new)
        with self.assertRaisesRegex(a.AdmissionRefused, "identity changed"):
            self.run_preview()

    def test_new_controller_invocation_substitution_refused(self):
        a.sys.argv[0] = str(self.old)
        with self.assertRaisesRegex(a.AdmissionRefused, "invocation identity drifted"):
            self.run_preview()

    def test_new_package_record_substitution_refused(self):
        substitute = {**self.installed, "record_sha256": "8" * 64}
        with mock.patch.object(a.lifecycle, "_installed_identity", return_value=substitute):
            with self.assertRaisesRegex(a.AdmissionRefused, "identity drifted"):
                self.run_preview()

    def test_forged_fence_admissibility_refused(self):
        self.handoff["admissible"] = True
        self.handoff["preview_sha256"] = d._digest({k: v for k, v in self.handoff.items() if k != "preview_sha256"})
        with self.assertRaisesRegex(f.FenceRefused, "unchanged, read-only"):
            self.run_preview()

    def test_active_scheduler_refuses_preflight(self):
        with mock.patch.object(a.recovery, "_quiescent", side_effect=d.RecoveryRefused("active scheduler")):
            with self.assertRaisesRegex(a.AdmissionRefused, "active scheduler"):
                self.run_preview()

    def test_cli_offers_preflight_but_no_admission_commit(self):
        parser = d.build_parser()
        parsed = parser.parse_args(["successor-admission-preview", "--project", str(self.root),
            "--origin-file", str(self.root / "origin"), "--origin-preview-sha256", "3" * 64,
            "--candidate-wheel", str(self.root / "candidate.whl"),
            "--review-path", "src/stygnox/transactions.py"])
        self.assertEqual(parsed.action, "successor-admission-preview")
        with self.assertRaises(SystemExit):
            parser.parse_args(["successor-admission-commit"])
