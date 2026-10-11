"""C3i blocked installed successor inspection and hostile lineage tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_transfer as transfer
from stygnox import direct_interruption_binding as binding
from stygnox import direct_interruption_successor as successor
from stygnox.direct_interruption_fence import SUCCESSOR_STATUS
from tests.test_stygnox_direct_interruption_supervisor import _evidence


def _seal(value, key):
    v = dict(value)
    v.pop(key, None)
    v[key] = recovery._digest(v)
    return v


def _inputs():
    plan, _projection, _journal, ctrl, tx = _evidence()
    installed = {'executable': '/new/bin/stygnox', 'record_sha256': 'e'*64,
                 'record_manifest_sha256': 'f'*64, 'package_sha256': 'c'*64}
    wheel = {'sha256': 'a'*64, 'package_manifest_sha256': 'd'*64}
    admission = _seal({
        'schema': 'stygnox_direct_interruption_successor_admission_preflight_v1',
        'admissible': False, 'authority_changed': False,
        'successor_execution_admission': 'DISABLED',
        'exclusive_transfer_publication': 'NOT_IMPLEMENTED',
        'proposed_successor_only_plan_status': SUCCESSOR_STATUS,
        'proposed_legacy_execution_authority_granted': False,
        'predecessor_plan_record_sha256': plan['record_sha256'],
        'predecessor_controller_record_sha256': ctrl['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'plan_hash': plan['plan_hash'], 'operator': plan['operator'],
        'transaction_id': plan['transaction_id'], 'current_step': plan['current_step'],
        'handoff_preview_sha256': '5'*64, 'fence_design_sha256': '6'*64,
        'review_preview_sha256': '7'*64, 'manifest_proof_sha256': '8'*64,
        'predecessor_installed_executable': {'path':'/old/bin/stygnox', 'sha256': '9'*64},
        'successor_installed_identity': installed, 'successor_wheel_identity': wheel,
    }, 'preview_sha256')
    proposal = transfer.build_fence_publication_preview(admission, plan)
    journal = publication.build_journal_preview(proposal)
    original, published = Path('/trusted/old'), Path('/trusted/new')
    witness = binding.build_blocked_binding_witness(
        transfer_preview=proposal, journal_preview=journal,
        predecessor_controller=ctrl, predecessor_transaction=tx,
        original=original, published=published,
    )
    return dict(original=original, published=published,
                admission=admission, proposal=proposal,
                current_plan=proposal['fenced_plan'], journal=journal,
                witness=witness, controller_record=ctrl, transaction_record=tx,
                installed_identity=installed, wheel_identity=wheel,
                invocation=Path(installed['executable']))


class BlockedSuccessorInspectionTests(unittest.TestCase):
    def setUp(self):
        self.inputs = _inputs()

    def inspect(self):
        return successor.validate_blocked_snapshot(**self.inputs)

    def test_exact_snapshot_proves_identity_but_never_grants_execution(self):
        result = self.inspect()
        self.assertTrue(result['installed_successor_identity_verified'])
        self.assertTrue(result['exact_blocked_lineage'])
        self.assertFalse(result['successor_execution_authorised'])
        self.assertFalse(result['handoff_admissible'])
        self.assertFalse(result['authority_changed'])
        self.assertFalse(result['original_binding_retired'])

    def test_digest_tampered_plan_refused(self):
        self.inputs['current_plan'] = {**self.inputs['current_plan'], 'plan_hash': '0'*64}
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_self_resealed_authority_grant_refused(self):
        self.inputs['current_plan'] = _seal({**self.inputs['current_plan'],
                'execution_authority_granted': True}, 'record_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_substituted_journal_even_if_resigned_refused(self):
        self.inputs['journal'] = _seal({**self.inputs['journal'], 'plan_published': True}, 'preview_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_resealed_binding_witness_substitution_refused(self):
        self.inputs['witness'] = _seal({**self.inputs['witness'], 'original_binding_retired': True}, 'record_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_predecessor_controller_substitution_refused(self):
        self.inputs['controller_record'] = _seal({**self.inputs['controller_record'],
                                                  'installed_command': '/other/cli'}, 'record_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_predecessor_transaction_substitution_refused(self):
        self.inputs['transaction_record'] = _seal({**self.inputs['transaction_record'],
                                                   'state': 'STOPPED'}, 'record_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_installed_record_drift_refused(self):
        self.inputs['installed_identity'] = {**self.inputs['installed_identity'],
                                            'record_sha256': '0'*64}
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_wheel_identity_drift_refused(self):
        self.inputs['wheel_identity'] = {**self.inputs['wheel_identity'], 'sha256': '0'*64}
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_invoking_original_binary_refused(self):
        self.inputs['invocation'] = Path('/old/bin/stygnox')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_original_and_published_path_substitution_refused(self):
        self.inputs['published'] = Path('/other/published')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_stale_admission_refused(self):
        self.inputs['admission'] = _seal({**self.inputs['admission'], 'plan_hash':'2'*64}, 'preview_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_disabling_execution_in_preview_must_remain(self):
        self.inputs['admission'] = _seal({**self.inputs['admission'],
                          'successor_execution_admission':'ENABLED'}, 'preview_sha256')
        with self.assertRaises(successor.SuccessorInspectionRefused):
            self.inspect()

    def test_readonly_evidence_reader_rejects_symlinks_and_unsafe_paths(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / 'proof.json'
            evidence.write_text(json.dumps(self.inputs['admission']))
            self.assertEqual(successor._read_external(evidence), self.inputs['admission'])
            (root/'alias.json').symlink_to(evidence)
            with self.assertRaises(OSError):
                successor._read_external(root/'alias.json')
            with self.assertRaises(successor.SuccessorInspectionRefused):
                successor._read_external(Path('relative.json'))

    def test_private_legacy_parent_is_not_false_retirement_proof(self):
        from unittest import mock
        with mock.patch.object(successor.os, 'lstat', side_effect=PermissionError('private')):
            self.assertFalse(successor._original_absence_visible(Path('/private/old')))
        with mock.patch.object(successor.os, 'lstat', side_effect=FileNotFoundError('retired')):
            self.assertTrue(successor._original_absence_visible(Path('/trusted/old')))
        with mock.patch.object(successor.os, 'lstat', return_value=object()):
            with self.assertRaises(successor.SuccessorInspectionRefused):
                successor._original_absence_visible(Path('/trusted/old'))

    def test_privileged_root_does_not_pretend_to_be_successor(self):
        from unittest import mock
        with mock.patch.object(successor.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(successor.SuccessorInspectionRefused,
                                        'distinct non-root successor UID'):
                successor.inspect_installed_blocked_successor(
                    project=Path('/not-a-project'), predecessor_uid=1000,
                    admission_file=Path('/proof'), transfer_file=Path('/transfer'),
                    candidate_wheel=Path('/wheel'))

    def test_cli_exposes_inspection_but_not_execution_release(self):
        parser = recovery.build_parser()
        parsed = parser.parse_args(['inspect-blocked-successor', '--project','/p',
            '--predecessor-uid','1000', '--admission-evidence','/a',
            '--transfer-evidence','/t', '--candidate-wheel','/w'])
        self.assertEqual(parsed.action, 'inspect-blocked-successor')
        with self.assertRaises(SystemExit):
            parser.parse_args(['authorize-blocked-successor'])
