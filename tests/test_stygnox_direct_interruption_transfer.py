"""C3a hostile contract tests: publication projections NEVER issue authority."""
from copy import deepcopy
import inspect
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_transfer as transfer
from stygnox import direct_interruption_fence as fence
from stygnox import planning


def seal(body, key):
    result = dict(body)
    result[key] = recovery._digest(result)
    return result


class TransferFenceContract(TestCase):
    def setUp(self):
        self.plan = seal({
            'schema': 'stygnox_plan_state_v1', 'status': 'APPROVED',
            'execution_authority_granted': True,
            'plan_hash': '1'*64, 'transaction_id': 'TX-abc',
            'operator': 'alice', 'current_step': 2,
            'controller_record_sha256': '2'*64,
            'transaction_record_sha256': '3'*64,
            'active_gate': None, 'self_development_grant': None,
            'direct_interruption_pending': None,
            'direct_interruption_recoveries': [],
            'repository_mutation_scope': ['src/stygnox/planning.py'],
            'accepted_controller_receipts': ['4'*64],
            'continuation_history': [{'source': 'original'}],
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

    def reseal(self, source, key):
        source.pop(key, None)
        source[key] = recovery._digest(source)

    def preview(self):
        return transfer.build_fence_publication_preview(self.admission, self.plan)

    def test_exact_projection_blocks_both_old_and_new_execution(self):
        before = deepcopy(self.plan)
        p = self.preview()
        state = p['fenced_plan']
        self.assertEqual(self.plan, before)
        self.assertEqual(state['status'], fence.SUCCESSOR_STATUS)
        self.assertIs(state['execution_authority_granted'], False)
        self.assertIs(state['direct_interruption_transfer_pending']['successor_execution_authorised'], False)
        self.assertIs(p['authority_changed'], False)
        self.assertIs(p['admissible'], False)
        self.assertEqual(transfer.classify_publication(p, self.plan), 'PREDECESSOR_UNCHANGED_NO_HANDOFF')
        self.assertEqual(transfer.classify_publication(p, state), 'FENCED_EXECUTION_BLOCKED_NO_HANDOFF')
        self.assertEqual(state['continuation_history'], self.plan['continuation_history'])
        self.assertEqual(state['repository_mutation_scope'], self.plan['repository_mutation_scope'])

    def test_real_planning_gate_refuses_fenced_state(self):
        p = self.preview()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.stygnox').mkdir()
            (root / '.stygnox' / 'plan.json').write_text(__import__('json').dumps(p['fenced_plan']))
            # Exercise the real installed planning state gate; only root
            # resolution is supplied because this is an isolated fixture.
            with patch.object(planning.adoption, 'resolve_worktree', return_value=root):
                with self.assertRaisesRegex(planning.PlanningError, 'unsupported active plan status'):
                    planning.approved_step_context(root, 'alice')

    def test_determinism_and_candidate_binding(self):
        first = self.preview()
        self.assertEqual(first, self.preview())
        self.admission['successor_wheel_identity']['sha256'] = 'b'*64
        self.reseal(self.admission, 'preview_sha256')
        second = self.preview()
        self.assertNotEqual(first['preview_sha256'], second['preview_sha256'])

    def test_stale_predecessor_refused(self):
        self.plan['record_sha256'] = 'f'*64
        with self.assertRaisesRegex(transfer.TransferRefused, 'digest'):
            self.preview()

    def test_admission_substitution_refused(self):
        self.admission['operator'] = 'mallory'
        self.reseal(self.admission, 'preview_sha256')
        with self.assertRaisesRegex(transfer.TransferRefused, 'bound to exact'):
            self.preview()

    def test_unknown_status_or_pending_recovery_refused(self):
        for status in ('RECOVERY_SUCCESSOR_APPROVED_V1', 'BLOCKED_HUMAN'):
            with self.subTest(status=status):
                self.plan['status'] = status
                self.reseal(self.plan, 'record_sha256')
                self.admission['predecessor_plan_record_sha256'] = self.plan['record_sha256']
                self.reseal(self.admission, 'preview_sha256')
                with self.assertRaisesRegex(transfer.TransferRefused, 'unmodified approved'):
                    self.preview()
        self.plan['status'] = 'APPROVED'
        self.plan['direct_interruption_pending'] = {'unsafe': True}
        self.reseal(self.plan, 'record_sha256')
        self.admission['predecessor_plan_record_sha256'] = self.plan['record_sha256']
        self.reseal(self.admission, 'preview_sha256')
        with self.assertRaisesRegex(transfer.TransferRefused, 'unmodified approved'):
            self.preview()

    def test_stale_or_tampered_publication_refused(self):
        p = self.preview()
        substituted = deepcopy(p['fenced_plan'])
        substituted['plan_hash'] = 'f'*64
        self.reseal(substituted, 'record_sha256')
        with self.assertRaisesRegex(transfer.TransferRefused, 'partial, stale or substituted'):
            transfer.classify_publication(p, substituted)
        modified = deepcopy(p)
        modified['fenced_plan']['execution_authority_granted'] = True
        self.reseal(modified['fenced_plan'], 'record_sha256')
        self.reseal(modified, 'preview_sha256')
        with self.assertRaisesRegex(transfer.TransferRefused, 'fence does not block'):
            transfer.classify_publication(modified, modified['fenced_plan'])

    def test_preflight_claiming_authority_refused(self):
        for key, value in [('admissible', True), ('authority_changed', True),
                           ('successor_execution_admission', 'ENABLED')]:
            with self.subTest(field=key):
                row = deepcopy(self.admission)
                row[key] = value
                self.reseal(row, 'preview_sha256')
                with self.assertRaisesRegex(transfer.TransferRefused, 'claim transfer authority'):
                    transfer.build_fence_publication_preview(row, self.plan)

    def test_legacy_compatible_release_code_removed(self):
        source = inspect.getsource(recovery.release)
        self.assertNotIn('updated["status"] = "APPROVED"', source)
        self.assertNotIn('updated["execution_authority_granted"] = True', source)

    def test_release_has_independent_unliftable_safety_gate(self):
        with self.assertRaisesRegex(transfer.TransferRefused, 'not hostile-qualified'):
            transfer.require_successor_release_authority()
        # Even if a future caller lifts C1's generic mutation blocker,
        # release() cannot progress to write a legacy-compatible plan.
        with patch('stygnox.direct_interruption._require_qualification_replay'), \
             patch('stygnox.direct_interruption_handoff.require_mutation_authority'), \
             patch('stygnox.direct_interruption._write', side_effect=AssertionError('unexpected evidence write')), \
             patch('stygnox.planning._write', side_effect=AssertionError('unexpected plan write')):
            with self.assertRaisesRegex(transfer.TransferRefused, 'not hostile-qualified'):
                recovery.release(Path('/missing'), 'a'*64, 'b'*64, 'RELEASE_REVIEWED_WORK')

    def test_transfer_preview_command_is_read_only_and_never_offers_commit(self):
        parser = recovery.build_parser()
        cmd = ['transfer-fence-preview', '--project', '/tmp/isolated', '--origin-file', '/tmp/origin',
               '--origin-preview-sha256', '3'*64, '--candidate-wheel', '/tmp/wheel',
               '--review-path', 'src/stygnox/planning.py']
        self.assertEqual(parser.parse_args(cmd).action, 'transfer-fence-preview')
        with self.assertRaises(SystemExit):
            parser.parse_args(['transfer-fence-commit', '--project', '/tmp/isolated'])
        with patch('stygnox.direct_interruption_admission.build_admission_preflight', return_value=self.admission), \
             patch.object(planning, '_record', return_value=self.plan), \
             patch.object(recovery.adoption, 'resolve_worktree', return_value=Path('/tmp/isolated')), \
             patch.object(recovery, '_write', side_effect=AssertionError('evidence mutated')), \
             patch.object(planning, '_write', side_effect=AssertionError('plan mutated')):
            self.assertEqual(recovery.cli_main(cmd), 0)
