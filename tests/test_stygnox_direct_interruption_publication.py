"""C3b: actual crash-boundary and release-denial behaviour, not mocked locks."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_fence as fence
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_transfer as transfer


def seal(value, key):
    body = dict(value)
    body.pop(key, None)
    body[key] = recovery._digest(body)
    return body


class CrashBoundaryContract(TestCase):
    def setUp(self):
        self.plan = seal({
            'schema': 'stygnox_plan_state_v1', 'status': 'APPROVED',
            'execution_authority_granted': True,
            'plan_hash': '1'*64, 'transaction_id': 'TX-abc',
            'operator': 'alice', 'current_step': 2,
            'controller_record_sha256': '2'*64,
            'transaction_record_sha256': '3'*64,
            'active_gate': None, 'self_development_grant': None,
            'direct_interruption_pending': None, 'direct_interruption_recoveries': [],
            'repository_mutation_scope': ['src/stygnox/planning.py'],
            'continuation_history': [{'accepted': 'receipt'}]
        }, 'record_sha256')
        self.admission = seal({
            'schema': 'stygnox_direct_interruption_successor_admission_preflight_v1',
            'admissible': False, 'authority_changed': False,
            'successor_execution_admission': 'DISABLED',
            'exclusive_transfer_publication': 'NOT_IMPLEMENTED',
            'proposed_successor_only_plan_status': fence.SUCCESSOR_STATUS,
            'proposed_legacy_execution_authority_granted': False,
            'predecessor_plan_record_sha256': self.plan['record_sha256'],
            'predecessor_controller_record_sha256': '2'*64,
            'predecessor_transaction_record_sha256': '3'*64,
            'plan_hash': '1'*64, 'transaction_id': 'TX-abc',
            'operator': 'alice', 'current_step': 2,
            'handoff_preview_sha256': '5'*64,
            'fence_design_sha256': '6'*64,
            'review_preview_sha256': '7'*64,
            'manifest_proof_sha256': '8'*64,
            'predecessor_installed_executable': {'path':'/old/stygnox','sha256':'9'*64},
            'successor_installed_identity': {'executable':'/new/stygnox'},
            'successor_wheel_identity': {'sha256':'a'*64},
        }, 'preview_sha256')
        self.transfer = transfer.build_fence_publication_preview(self.admission, self.plan)
        self.journal = publication.build_journal_preview(self.transfer)

    def test_exact_read_only_determinism_and_no_issuance(self):
        before = deepcopy(self.transfer)
        self.assertEqual(publication.build_journal_preview(self.transfer), self.journal)
        self.assertEqual(self.transfer, before)
        self.assertFalse(self.journal['journal_published'])
        self.assertFalse(self.journal['legacy_process_exclusion_proved'])
        self.assertFalse(self.journal['admissible'])
        self.assertFalse(self.journal['authority_changed'])

    def test_crash_before_journal_keeps_predecessor_untransferred(self):
        r = publication.reconcile_crash_boundary(self.transfer, None, self.plan)
        self.assertEqual(r['phase'], publication.NO_FENCE)
        self.assertTrue(r['legacy_plan_gated_admissions_may_continue'])
        self.assertFalse(r['automatic_repair_permitted'])

    def test_crash_after_journal_but_before_fence_is_not_handoff(self):
        r = publication.reconcile_crash_boundary(self.transfer, self.journal, self.plan)
        self.assertEqual(r['phase'], publication.JOURNAL_ONLY)
        self.assertTrue(r['legacy_plan_gated_admissions_may_continue'])
        self.assertFalse(r['handoff_admissible'])

    def test_crash_after_fence_refuses_successor_execution(self):
        r = publication.reconcile_crash_boundary(self.transfer, self.journal, self.transfer['fenced_plan'])
        self.assertEqual(r['phase'], publication.FENCED)
        self.assertFalse(r['legacy_plan_gated_admissions_may_continue'])
        self.assertFalse(r['inflight_legacy_execution_excluded'])
        self.assertFalse(r['all_legacy_mutation_paths_fenced'])
        self.assertFalse(r['successor_execution_authorised'])
        self.assertFalse(r['automatic_repair_permitted'])

    def test_crash_after_fence_without_journal_refused(self):
        with self.assertRaisesRegex(publication.PublicationRefused, 'without verified'):
            publication.reconcile_crash_boundary(self.transfer, None, self.transfer['fenced_plan'])

    def test_substituted_journal_even_when_rehashed_refused(self):
        for key, value in [('fenced_plan_record_sha256', 'b'*64),
                           ('predecessor_controller_record_sha256', 'c'*64),
                           ('authority_changed', True),
                           ('legacy_process_exclusion_proved', True),
                           ('successor_execution_authorised', True),
                           ('admissible', True)]:
            with self.subTest(field=key):
                candidate = seal({**self.journal, key: value}, 'preview_sha256')
                with self.assertRaisesRegex(publication.PublicationRefused, 'substituted'):
                    publication.reconcile_crash_boundary(self.transfer, candidate, self.plan)

    def test_partial_plan_drift_refused_and_no_autofix(self):
        for key, value in [('status', 'APPROVED'),
                           ('execution_authority_granted', True),
                           ('plan_hash', 'b'*64)]:
            with self.subTest(field=key):
                bad = seal({**self.transfer['fenced_plan'], key: value}, 'record_sha256')
                with self.assertRaisesRegex(publication.PublicationRefused, 'partial|substituted'):
                    publication.reconcile_crash_boundary(self.transfer, self.journal, bad)

    def test_legacy_fence_requires_unchanged_predecessor_lineage(self):
        bad = deepcopy(self.transfer)
        bad['fenced_plan']['direct_interruption_transfer_pending']['predecessor_controller_record_sha256'] = 'c'*64
        bad['fenced_plan'] = seal(bad['fenced_plan'], 'record_sha256')
        bad = seal(bad, 'preview_sha256')
        with self.assertRaisesRegex(publication.PublicationRefused, 'lineage'):
            publication.build_journal_preview(bad)

    def test_missing_or_invalid_fence_and_journal_refused(self):
        with self.assertRaises(publication.PublicationRefused):
            publication.build_journal_preview({})
        invalid = dict(self.journal)
        invalid['preview_sha256'] = '0'*64
        with self.assertRaisesRegex(publication.PublicationRefused, 'integrity'):
            publication.reconcile_crash_boundary(self.transfer, invalid, self.plan)

    def test_no_real_publication_entrypoint_or_release(self):
        with self.assertRaisesRegex(publication.PublicationRefused, 'unproved'):
            publication.require_exclusive_publication_authority()
        p = recovery.build_parser()
        args = p.parse_args(['transfer-journal-preview', '--project', '/tmp/disposable',
            '--origin-file', '/tmp/origin', '--origin-preview-sha256', 'e'*64,
            '--candidate-wheel', '/tmp/candidate.whl', '--review-path', 'src/stygnox/planning.py'])
        self.assertEqual(args.action, 'transfer-journal-preview')
        with self.assertRaises(SystemExit):
            p.parse_args(['transfer-journal-commit', '--project', '/tmp/disposable'])
        with patch('stygnox.direct_interruption_admission.build_admission_preflight', return_value=self.admission), \
             patch.object(recovery.planning, '_record', return_value=self.plan), \
             patch.object(recovery.adoption, 'resolve_worktree', return_value=Path('/tmp/disposable')), \
             patch.object(recovery, '_write', side_effect=AssertionError('write forbidden')), \
             patch.object(recovery.planning, '_write', side_effect=AssertionError('write forbidden')):
            self.assertEqual(recovery.cli_main(['transfer-journal-preview', '--project', '/tmp/disposable',
                '--origin-file', '/tmp/origin', '--origin-preview-sha256', 'e'*64,
                '--candidate-wheel', '/tmp/candidate.whl', '--review-path', 'src/stygnox/planning.py']), 0)
