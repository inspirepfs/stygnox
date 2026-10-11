"""C3g kernel-real blocked transition and crash boundaries; no success authority."""
from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_transfer as transfer
from stygnox.direct_interruption_fence import SUCCESSOR_STATUS
from stygnox.direct_interruption_supervisor import SupervisorRefused, publish_blocked_namespace
from stygnox import direct_interruption_quarantine as quarantine


def _seal(body: dict, field: str) -> dict:
    value = dict(body)
    value[field] = recovery._digest(value)
    return value


def _evidence():
    tx = _seal({
        'schema': 'stygnox_transaction_v1', 'transaction_id': 'TX-test',
        'state': 'ACTIVE', 'installed_command': '/old/bin/stygnox',
    }, 'record_sha256')
    active = _seal({
        'schema': 'stygnox_controller_state_v1', 'transaction_id': 'TX-test',
        'enabled': True, 'installed_command': '/old/bin/stygnox',
    }, 'record_sha256')
    plan = _seal({
        'schema': 'stygnox_plan_state_v1', 'status': 'APPROVED',
        'execution_authority_granted': True, 'plan_hash': '1'*64,
        'transaction_id': 'TX-test', 'operator': 'operator', 'current_step': 2,
        'controller_record_sha256': active['record_sha256'], 'transaction_record_sha256': tx['record_sha256'],
        'active_gate': None, 'self_development_grant': None,
        'direct_interruption_pending': None, 'direct_interruption_recoveries': [],
        'repository_mutation_scope': ['src/stygnox/planning.py'],
        'continuation_history': [{'accepted': 'receipt'}],
    }, 'record_sha256')
    admission = _seal({
        'schema': 'stygnox_direct_interruption_successor_admission_preflight_v1',
        'admissible': False, 'authority_changed': False,
        'successor_execution_admission': 'DISABLED',
        'exclusive_transfer_publication': 'NOT_IMPLEMENTED',
        'proposed_successor_only_plan_status': SUCCESSOR_STATUS,
        'proposed_legacy_execution_authority_granted': False,
        'predecessor_plan_record_sha256': plan['record_sha256'],
        'predecessor_controller_record_sha256': active['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'plan_hash': '1'*64, 'transaction_id': 'TX-test',
        'operator': 'operator', 'current_step': 2,
        'handoff_preview_sha256': '5'*64, 'fence_design_sha256': '6'*64,
        'review_preview_sha256': '7'*64, 'manifest_proof_sha256': '8'*64,
        'predecessor_installed_executable': {'path': '/old/bin/stygnox', 'sha256': '9'*64},
        'successor_installed_identity': {'executable': '/new/bin/stygnox'},
        'successor_wheel_identity': {'sha256': 'a'*64},
    }, 'preview_sha256')
    projection = transfer.build_fence_publication_preview(admission, plan)
    journal = publication.build_journal_preview(projection)
    return plan, projection, journal, active, tx


class RefusalTests(unittest.TestCase):
    def test_nonroot_calls_never_become_authority(self):
        plan, projection, journal, active, tx = _evidence()
        with self.assertRaises(SupervisorRefused):
            publish_blocked_namespace(
                original=Path('relative'), retired=Path('/run/vault/a'),
                staged=Path('/run/staging/b'), published=Path('/run/published/c'),
                predecessor_uid=1000, successor_uid=61001,
                predecessor_identity=(1, 1), staged_identity=(1, 2),
                transfer_preview=projection, journal_preview=journal,
            )

    def test_mismatched_proposal_refused(self):
        plan, projection, journal, active, tx = _evidence()
        journal['journal_published'] = True
        with self.assertRaises(SupervisorRefused):
            publish_blocked_namespace(
                original=Path('/run/a/old'), retired=Path('/run/b/old'),
                staged=Path('/run/c/next'), published=Path('/run/d/next'),
                predecessor_uid=1000, successor_uid=61001,
                predecessor_identity=(1, 1), staged_identity=(1, 2),
                transfer_preview=projection, journal_preview=journal,
            )


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0 and Path('/run').is_dir(),
                     'requires root on Linux and disposable /run')
class KernelTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/run', prefix='stygnox-c3g-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o755)
        self.legacy_uid = 61010
        self.successor_uid = 61011
        self.active = self.base / 'active'
        self.vault = self.base / 'vault'
        self.staging = self.base / 'staging'
        self.published_dir = self.base / 'published'
        for path, mode in ((self.active, 0o711), (self.vault, 0o700),
                           (self.staging, 0o700), (self.published_dir, 0o711)):
            path.mkdir(mode=mode)
        self.original = self.active / 'old'
        self.retired = self.vault / 'retired'
        self.staged = self.staging / 'successor'
        self.published = self.published_dir / 'successor'
        self.plan, self.preview, self.journal, self.active, self.tx = _evidence()
        for path, uid in ((self.original, self.legacy_uid),
                          (self.staged, self.successor_uid)):
            path.mkdir(mode=0o700)
            rt = path / '.stygnox'
            rt.mkdir(mode=0o700)
            record = rt / 'plan.json'
            record.write_text(json.dumps(self.plan))
            os.chown(record, uid, uid)
            record.chmod(0o600)
            for name, authority in (('controller.json', self.active), ('transaction.json', self.tx)):
                child = rt / name
                child.write_text(json.dumps(authority))
                os.chown(child, uid, uid)
                child.chmod(0o600)
            os.chown(rt, uid, uid)
            os.chown(path, uid, uid)
        s1, s2 = self.original.stat(), self.staged.stat()
        self.kwargs = dict(
            original=self.original, retired=self.retired,
            staged=self.staged, published=self.published,
            predecessor_uid=self.legacy_uid, successor_uid=self.successor_uid,
            predecessor_identity=(s1.st_dev, s1.st_ino),
            staged_identity=(s2.st_dev, s2.st_ino),
            transfer_preview=self.preview, journal_preview=self.journal,
        )

    def run_transition(self):
        return publish_blocked_namespace(**self.kwargs)

    def test_real_namespace_transition_publishes_blocked_plan_only(self):
        result = self.run_transition()
        self.assertTrue(result['predecessor_retired'])
        self.assertTrue(result['blocked_replica_exposed'])
        self.assertEqual(result['publication_phase'], publication.FENCED)
        self.assertFalse(result['handoff_admissible'])
        self.assertFalse(result['binding_transferred'])
        self.assertFalse(result['successor_execution_authorised'])
        self.assertFalse(self.original.exists())
        self.assertFalse(self.staged.exists())
        self.assertTrue(self.retired.is_dir())
        rt = self.published / '.stygnox'
        bound_controller = json.loads((rt / 'controller.json').read_text())
        bound_tx = json.loads((rt / 'transaction.json').read_text())
        bound_quarantine = json.loads((rt / quarantine.FILENAME).read_text())
        self.assertFalse(bound_controller['enabled'])
        self.assertFalse(bound_controller['controller_execution_enabled'])
        self.assertEqual(bound_tx['state'], 'RECOVERY_QUARANTINED')
        self.assertEqual(bound_controller['installed_command'], '/new/bin/stygnox')
        self.assertEqual(bound_tx['installed_command'], '/new/bin/stygnox')
        self.assertEqual(result['quarantine_record_sha256'], bound_quarantine['record_sha256'])
        # Exercise the REAL installed-controller transaction gate (not a mock).
        from stygnox import controller as runtime_controller
        with self.assertRaises(runtime_controller.ControllerError):
            runtime_controller._transaction(self.published)
        plan = json.loads((self.published / '.stygnox' / 'plan.json').read_text())
        journal = json.loads((self.published / '.stygnox' /
                              'direct-interruption-transfer-journal.json').read_text())
        self.assertEqual(plan, self.preview['fenced_plan'])
        self.assertEqual(journal, self.journal)
        witness = json.loads((self.published / '.stygnox' / 'direct-interruption-blocked-binding.json').read_text())
        self.assertFalse(witness['successor_execution_authorised'])
        self.assertFalse(witness['original_binding_retired'])
        self.assertEqual(witness['predecessor_controller_record_sha256'], self.active['record_sha256'])
        self.assertEqual(witness['predecessor_transaction_record_sha256'], self.tx['record_sha256'])
        self.assertEqual(plan['status'], SUCCESSOR_STATUS)
        self.assertFalse(plan['execution_authority_granted'])
        self.assertEqual(plan['plan_hash'], self.plan['plan_hash'])
        self.assertEqual(plan['transaction_id'], self.plan['transaction_id'])
        self.assertEqual(plan['continuation_history'], self.plan['continuation_history'])

    def test_predecessor_denied_reopen_and_successor_can_read_fence(self):
        self.run_transition()
        program = ("from pathlib import Path;import sys;"
                   "p=Path(sys.argv[1]);"
                   "p.joinpath('.stygnox','plan.json').write_text('NO');")
        def drop(uid):
            def child():
                os.setgroups([])
                os.setgid(uid)
                os.setuid(uid)
            return child
        for path in (self.original, self.retired, self.published):
            proc = subprocess.run([sys.executable, '-c', program, str(path)],
                                  capture_output=True, text=True, preexec_fn=drop(self.legacy_uid))
            self.assertNotEqual(proc.returncode, 0, str(path))
        read = subprocess.run([sys.executable, '-c',
                               "import pathlib,sys;print(pathlib.Path(sys.argv[1]).read_text())",
                               str(self.published / '.stygnox' / 'plan.json')],
                              capture_output=True, text=True, preexec_fn=drop(self.successor_uid))
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertIn(SUCCESSOR_STATUS, read.stdout)

    def test_refuses_substituted_staged_controller_before_retirement(self):
        controller_path = self.staged / '.stygnox' / 'controller.json'
        changed = dict(self.active)
        changed['installed_command'] = '/forged/bin/stygnox'
        changed.pop('record_sha256')
        changed['record_sha256'] = recovery._digest(changed)
        controller_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(SupervisorRefused, 'staged installed authority records differ'):
            self.run_transition()
        self.assertTrue(self.original.exists())
        self.assertFalse(self.retired.exists())

    def test_refuses_substituted_staged_transaction_before_retirement(self):
        transaction_path = self.staged / '.stygnox' / 'transaction.json'
        changed = dict(self.tx)
        changed['installed_command'] = '/forged/bin/stygnox'
        changed.pop('record_sha256')
        changed['record_sha256'] = recovery._digest(changed)
        transaction_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(SupervisorRefused, 'staged installed authority records differ'):
            self.run_transition()
        self.assertTrue(self.original.exists())
        self.assertFalse(self.retired.exists())

    def test_refuses_invalid_original_controller_digest_before_retirement(self):
        path = self.original / '.stygnox' / 'controller.json'
        bad = dict(self.active)
        bad['enabled'] = False
        path.write_text(json.dumps(bad))
        (self.staged / '.stygnox' / 'controller.json').write_text(json.dumps(bad))
        with self.assertRaisesRegex(SupervisorRefused, 'installed predecessor binding refused'):
            self.run_transition()
        self.assertTrue(self.original.exists())
        self.assertFalse(self.retired.exists())

    def test_refuses_existing_blocked_witness_before_retirement(self):
        existing = self.staged / '.stygnox' / 'direct-interruption-blocked-binding.json'
        existing.write_text('{}')
        existing.chmod(0o600)
        os.chown(existing, self.successor_uid, self.successor_uid)
        with self.assertRaisesRegex(SupervisorRefused, 'blocked binding record already exists'):
            self.run_transition()
        self.assertTrue(self.original.exists())
        self.assertFalse(self.retired.exists())

    def test_refuses_mismatched_staged_plan_before_retirement(self):
        (self.staged / '.stygnox' / 'plan.json').write_text('{}')
        with self.assertRaises(SupervisorRefused):
            self.run_transition()
        self.assertTrue(self.original.is_dir())
        self.assertFalse(self.retired.exists())
        self.assertFalse(self.published.exists())

    def test_refuses_destination_collision_before_retirement(self):
        self.published.mkdir(mode=0o700)
        with self.assertRaises(SupervisorRefused):
            self.run_transition()
        self.assertTrue(self.original.is_dir())

    def test_fault_after_retirement_preserves_private_unpublished_replica(self):
        with patch('stygnox.direct_interruption_supervisor._write_exact',
                   side_effect=OSError('simulated filesystem interruption')):
            with self.assertRaisesRegex(SupervisorRefused, 'interrupted'):
                self.run_transition()
        self.assertFalse(self.original.exists())
        self.assertTrue(self.retired.is_dir())
        self.assertTrue(self.staged.is_dir())
        self.assertFalse(self.published.exists())
        self.assertEqual(json.loads((self.staged / '.stygnox' / 'plan.json').read_text()), self.plan)
        with self.assertRaises(SupervisorRefused):
            self.run_transition()  # NEVER silently retry/restore predecessor authority

    def test_journal_only_crash_remains_private_and_cannot_replay(self):
        original_write = __import__('stygnox.direct_interruption_supervisor',
                                    fromlist=['_write_exact'])._write_exact
        def stop_before_plan(fd, name, record, uid):
            if name == 'plan.json':
                raise OSError('injected interruption after durable journal')
            return original_write(fd, name, record, uid)
        with patch('stygnox.direct_interruption_supervisor._write_exact', side_effect=stop_before_plan):
            with self.assertRaises(SupervisorRefused):
                self.run_transition()
        self.assertFalse(self.original.exists())
        self.assertFalse(self.published.exists())
        runtime = self.staged / '.stygnox'
        observed_journal = json.loads((runtime / 'direct-interruption-transfer-journal.json').read_text())
        observed_plan = json.loads((runtime / 'plan.json').read_text())
        self.assertEqual(observed_journal, self.journal)
        self.assertEqual(observed_plan, self.plan)
        witness = json.loads((runtime / 'direct-interruption-blocked-binding.json').read_text())
        self.assertFalse(witness['successor_execution_authorised'])
        self.assertFalse(witness['handoff_admissible'])
        self.assertFalse(self.published.exists())
        self.assertEqual(publication.reconcile_crash_boundary(
            self.preview, observed_journal, observed_plan)['phase'], publication.JOURNAL_ONLY)
        with self.assertRaises(SupervisorRefused):
            self.run_transition()

    def test_crash_during_disabled_binding_never_exposes_partial_authority(self):
        from stygnox import direct_interruption_supervisor as supervisor
        original_write = supervisor._write_exact
        def interrupt(fd, name, record, uid):
            if name == 'transaction.json':
                raise OSError('simulated C3j binding interruption')
            return original_write(fd, name, record, uid)
        with patch.object(supervisor, '_write_exact', side_effect=interrupt):
            with self.assertRaisesRegex(SupervisorRefused, 'interrupted'):
                self.run_transition()
        self.assertFalse(self.original.exists())
        self.assertTrue(self.retired.exists())
        self.assertTrue(self.staged.exists())
        self.assertFalse(self.published.exists())
        runtime = self.staged / '.stygnox'
        controller_record = json.loads((runtime / 'controller.json').read_text())
        transaction_record = json.loads((runtime / 'transaction.json').read_text())
        self.assertFalse(controller_record['enabled'])
        self.assertEqual(transaction_record['state'], 'ACTIVE')
        self.assertFalse((runtime / quarantine.FILENAME).exists())
        with self.assertRaises(SupervisorRefused):
            self.run_transition()

    def test_crash_after_both_disabled_records_requires_manual_reconciliation(self):
        from stygnox import direct_interruption_supervisor as supervisor
        original_write = supervisor._write_exact
        def interrupt(fd, name, record, uid):
            if name == quarantine.FILENAME:
                raise OSError('simulated C3j receipt interruption')
            return original_write(fd, name, record, uid)
        with patch.object(supervisor, '_write_exact', side_effect=interrupt):
            with self.assertRaisesRegex(SupervisorRefused, 'interrupted'):
                self.run_transition()
        self.assertFalse(self.original.exists())
        self.assertTrue(self.retired.exists())
        self.assertTrue(self.staged.exists())
        self.assertFalse(self.published.exists())
        runtime = self.staged / '.stygnox'
        controller_record = json.loads((runtime / 'controller.json').read_text())
        transaction_record = json.loads((runtime / 'transaction.json').read_text())
        self.assertFalse(controller_record['enabled'])
        self.assertEqual(transaction_record['state'], 'RECOVERY_QUARANTINED')
        self.assertFalse((runtime / quarantine.FILENAME).exists())
        with self.assertRaises(SupervisorRefused):
            self.run_transition()

    def test_fault_during_exposure_keeps_fenced_replica_private(self):
        original_rename = os.rename
        def interrupt(src, dst, **kwargs):
            if src == self.staged.name and dst == self.published.name:
                raise OSError('simulated interrupted exposure')
            return original_rename(src, dst, **kwargs)
        with patch('stygnox.direct_interruption_supervisor.os.rename', side_effect=interrupt):
            with self.assertRaises(SupervisorRefused):
                self.run_transition()
        self.assertFalse(self.original.exists())
        self.assertTrue(self.retired.exists())
        self.assertFalse(self.published.exists())
        plan = json.loads((self.staged / '.stygnox' / 'plan.json').read_text())
        self.assertEqual(plan['status'], SUCCESSOR_STATUS)
        self.assertFalse(plan['execution_authority_granted'])

    def test_existing_supervisor_lock_refuses_without_retirement(self):
        guard_path = self.vault / '.stygnox-c3g.lock'
        guard_path.write_bytes(b'')
        guard_path.chmod(0o600)
        with guard_path.open('rb') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(SupervisorRefused, 'already active'):
                self.run_transition()
        self.assertTrue(self.original.exists())
        self.assertFalse(self.published.exists())

    def test_symlink_in_private_stage_rejected_before_retirement(self):
        (self.staged / 'outside').symlink_to(self.original, target_is_directory=True)
        with self.assertRaises(SupervisorRefused):
            self.run_transition()
        self.assertTrue(self.original.is_dir())
        self.assertFalse(self.retired.exists())

    def test_replay_refuses_duplicate_publication(self):
        self.run_transition()
        with self.assertRaises(SupervisorRefused):
            self.run_transition()
        self.assertEqual(json.loads((self.published / '.stygnox' / 'plan.json').read_text()),
                         self.preview['fenced_plan'])


if __name__ == '__main__':
    unittest.main()
