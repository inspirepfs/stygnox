"""C3m: digest lineage and fail-closed disposable integrated-run boundaries."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
import tempfile
import unittest

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_binding as binding
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_quarantine as quarantine
from stygnox import direct_interruption_transfer as transfer
from stygnox.direct_interruption_fence import SUCCESSOR_STATUS

_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_c3m_installed_supervised_transition.py'
_SPEC = importlib.util.spec_from_file_location('stygnox_c3m_integrated_probe', _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


class IntegratedBlockedLineageTests(unittest.TestCase):
    def test_disposable_predecessor_identity_pins_the_successor_but_cannot_release(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            predecessor = root / 'old-stygnox'
            predecessor.write_bytes(b'synthetic predecessor')
            candidate = root / 'new-stygnox'
            installed = {'executable': str(candidate), 'record_sha256': 'a'*64}
            wheel = {'sha256': 'b'*64}
            plan, controller, tx, admission, proposal, journal = probe._evidence(
                predecessor=predecessor, installed=installed, wheel_id=wheel)
            self.assertEqual(admission['predecessor_installed_executable']['sha256'], probe._sha(predecessor))
            self.assertEqual(admission['successor_installed_identity'], installed)
            self.assertEqual(admission['successor_wheel_identity'], wheel)
            self.assertEqual(proposal['fenced_plan']['execution_authority_granted'], False)
            self.assertEqual(proposal['fenced_plan']['status'], SUCCESSOR_STATUS)
            self.assertEqual(admission['admissible'], False)
            self.assertEqual(admission['exclusive_transfer_publication'], 'NOT_IMPLEMENTED')
            self.assertEqual(proposal, transfer.build_fence_publication_preview(admission, plan))
            self.assertEqual(journal, publication.build_journal_preview(proposal))
            witness = binding.build_blocked_binding_witness(
                transfer_preview=proposal, journal_preview=journal,
                predecessor_controller=controller, predecessor_transaction=tx,
                original=root/'old', published=root/'new')
            disabled = quarantine.build_quarantine_binding(
                fenced_plan=proposal['fenced_plan'], journal=journal, witness=witness,
                predecessor_controller=controller, predecessor_transaction=tx)
            self.assertFalse(disabled['controller']['enabled'])
            self.assertEqual(disabled['transaction']['state'], 'RECOVERY_QUARANTINED')
            self.assertFalse(disabled['receipt']['successor_execution_authorised'])
            self.assertEqual(disabled, quarantine.validate_quarantine_binding(
                fenced_plan=proposal['fenced_plan'], journal=journal, witness=witness,
                controller_record=disabled['controller'], transaction_record=disabled['transaction'],
                quarantine_record=disabled['receipt']))

    def test_tampered_predecessor_digest_is_refused_before_fence(self):
        with tempfile.TemporaryDirectory() as td:
            predecessor = Path(td)/'old'
            predecessor.write_bytes(b'synthetic predecessor')
            plan, controller, tx, admission, _, _ = probe._evidence(
                predecessor=predecessor, installed={'executable': str(Path(td)/'new')},
                wheel_id={'sha256': 'a'*64})
            broken = {**plan, 'current_step': 3}
            with self.assertRaises(transfer.TransferRefused):
                transfer.build_fence_publication_preview(admission, broken)
            self.assertEqual(plan['record_sha256'], recovery._digest(
                {k: v for k, v in plan.items() if k != 'record_sha256'}))

    def test_root_owned_candidate_launcher_resolves_for_distinct_uid(self):
        if sys.platform != 'linux' or os.geteuid() != 0:
            self.skipTest('cross-UID subprocess requires Linux root')
        parent = Path('/tmp')
        if os.statvfs(parent).f_flag & os.ST_NOEXEC:
            self.skipTest('/tmp is noexec on this test host')
        successor_uid = probe._unused_uid(0)
        with tempfile.TemporaryDirectory(prefix='stygnox-c3m-candidate-test-', dir='/tmp') as td:
            root = Path(td)
            root.chmod(0o755)
            bin_dir = root / 'bin'
            bin_dir.mkdir(mode=0o755)
            bin_dir.chmod(0o755)
            launcher = bin_dir / 'stygnox'
            launcher.write_text('#!/bin/sh\necho "stygnox 0.1.0"\n')
            launcher.chmod(0o755)
            env = {'PATH': f'{bin_dir}:/usr/bin:/bin', 'PYTHONNOUSERSITE': '1'}
            probe._verify_candidate_launcher(Path(sys.executable), launcher, root, env, successor_uid)
            # A root-only ancestor must fail closed before installed identity
            # lookup; this must not be misinterpreted as a valid binding.
            root.chmod(0o700)
            with self.assertRaises(RuntimeError):
                probe._verify_candidate_launcher(Path(sys.executable), launcher, root, env, successor_uid)

    def test_snapshot_detects_mutated_runtime_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record = root/'transaction.json'
            record.write_bytes(b'one')
            before = probe._snapshot(root)
            record.write_bytes(b'two')
            self.assertNotEqual(before, probe._snapshot(root))


if __name__ == '__main__':
    unittest.main()
