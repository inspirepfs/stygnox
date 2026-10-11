"""Stage C read-only candidate binding and fail-closed execution fencing."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import hashlib

from stygnox import direct_interruption_handoff as c
from stygnox import direct_interruption as d


class StageC(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old_exe = self.root / 'original' / 'bin' / 'stygnox'
        self.new_exe = self.root / 'candidate' / 'bin' / 'stygnox'
        for exe, payload in ((self.old_exe, b'old-controller'), (self.new_exe, b'new-controller')):
            exe.parent.mkdir(parents=True)
            exe.write_bytes(payload)
        self.plan = d._checked({'schema': 'test'}) if False else {
            'plan_hash': 'p'*64, 'transaction_id': 'TX-1', 'operator': 'alice',
            'current_step': 2, 'record_sha256': 'plan',
            'controller_record_sha256': 'ctrl', 'transaction_record_sha256': 'tx',
        }
        self.ctrl = {
            'record_sha256': 'ctrl', 'transaction_id': 'TX-1',
            'installed_command': str(self.old_exe),
        }
        self.tx = {
            'record_sha256': 'tx', 'transaction_id': 'TX-1',
            'installed_command': str(self.old_exe),
        }
        self.review = {
            'plan_hash': 'p'*64, 'operator': 'alice',
            'preview_sha256': 'a'*64, 'manifest_proof': {'proof_sha256': 'b'*64},
        }
        self.installed = {'executable': str(self.new_exe), 'package_version': '0.1.0',
                          'package_sha256': 'c'*64, 'record_sha256': 'd'*64}
        self.wheel = {'sha256': 'e'*64, 'path': str(self.root/'stygnox.whl')}
        context = [
            mock.patch.object(c.adoption, 'resolve_worktree', return_value=self.root),
            mock.patch.object(d, 'review_preview', return_value=self.review),
            mock.patch.object(c.planning, '_record', return_value=self.plan),
            mock.patch.object(c.controller, '_controller', return_value=self.ctrl),
            mock.patch.object(c.transactions, '_transaction', return_value=self.tx),
            mock.patch.object(d, '_checked', side_effect=lambda x: x),
            mock.patch.object(c.lifecycle, '_installed_identity', return_value=self.installed),
            mock.patch.object(c.lifecycle, '_wheel_identity', return_value=self.wheel),
            mock.patch.object(c.sys, 'argv', [str(self.new_exe), 'direct-interruption']),
        ]
        for patcher in context:
            patcher.start()
            self.addCleanup(patcher.stop)

    def preview(self):
        return c.build_handoff_preview(self.root, self.root/'origin.json', 'f'*64,
                                       ['src/stygnox/transactions.py'], self.root/'stygnox.whl')

    def test_preview_binds_both_identities_and_never_grants_authority(self):
        got = self.preview()
        self.assertEqual(got['predecessor_installed_executable']['sha256'], hashlib.sha256(b'old-controller').hexdigest())
        self.assertEqual(got['candidate_installed_identity']['executable'], str(self.new_exe))
        self.assertEqual(got['candidate_wheel_identity'], self.wheel)
        self.assertEqual(got['review_preview_sha256'], self.review['preview_sha256'])
        self.assertEqual(got['manifest_proof_sha256'], 'b'*64)
        self.assertFalse(got['admissible'])
        self.assertFalse(got['authority_changed'])
        self.assertFalse(got['old_controller_fencing_proved'])
        self.assertEqual(got['preview_sha256'], d._digest({k:v for k,v in got.items() if k!='preview_sha256'}))

    def test_controller_transaction_mismatch_refused(self):
        self.tx['installed_command'] = str(self.new_exe)
        with self.assertRaisesRegex(c.HandoffRefused, 'installed commands disagree'):
            self.preview()

    def test_mismatched_record_refused(self):
        self.ctrl['record_sha256'] = 'other'
        with self.assertRaisesRegex(c.HandoffRefused, 'runtime authority changed'):
            self.preview()

    def test_predecessor_executable_substitution_changes_bound_digest(self):
        before = self.preview()
        self.old_exe.write_bytes(b'substituted')
        after = self.preview()
        self.assertNotEqual(before['preview_sha256'], after['preview_sha256'])
        self.assertFalse(after['admissible'])

    def test_missing_predecessor_fails_closed(self):
        self.old_exe.unlink()
        with self.assertRaisesRegex(c.HandoffRefused, 'regular non-symlink'):
            self.preview()

    def test_symlinked_predecessor_fails_closed(self):
        self.old_exe.unlink()
        self.old_exe.symlink_to(self.new_exe)
        with self.assertRaisesRegex(c.HandoffRefused, 'regular non-symlink'):
            self.preview()

    def test_candidate_not_invoking_installed_executable_refused(self):
        c.sys.argv = [str(self.old_exe)]
        with self.assertRaisesRegex(c.HandoffRefused, 'invoking process'):
            self.preview()

    def test_candidate_artifact_integrity_error_refused(self):
        with mock.patch.object(c.lifecycle, '_wheel_identity', side_effect=c.lifecycle.LifecycleError('RECORD substitution')):
            with self.assertRaisesRegex(c.HandoffRefused, 'RECORD substitution'):
                self.preview()

    def test_duplicate_candidate_old_executable_refused(self):
        self.installed['executable'] = str(self.old_exe)
        c.sys.argv = [str(self.old_exe)]
        with self.assertRaisesRegex(c.HandoffRefused, 'different installed executables'):
            self.preview()

    def test_mutation_denied_no_environment_flag_can_bypass(self):
        with mock.patch.dict(c.os.environ, {'STYGNOX_SKIP_AUTHORITY': '1', 'STYGNOX_TEST_MODE': '1'}):
            with self.assertRaisesRegex(c.HandoffRefused, 'not implemented'):
                c.require_mutation_authority(self.root)

    def test_all_mutating_api_paths_refuse_before_runtime_write(self):
        with mock.patch.object(d, '_require_qualification_replay', return_value=None), \
             mock.patch.object(d, '_write', side_effect=AssertionError('wrote runtime!')), \
             mock.patch.object(d.planning, '_write', side_effect=AssertionError('wrote plan!')):
            cases = [
                lambda: d.adopt(self.root, self.root/'origin', 'f'*64, [], 'reviewed', 'a'*64, 'ADOPT_UNATTRIBUTED_WORK'),
                lambda: d.qualify(self.root, 'f'*64, self.new_exe),
                lambda: d.release(self.root, 'f'*64, 'a'*64, 'RELEASE_REVIEWED_WORK'),
            ]
            for operation in cases:
                with self.subTest(operation=operation), self.assertRaisesRegex(c.HandoffRefused, 'not implemented'):
                    operation()

    def test_handoff_preview_command_exists_but_no_handoff_commit(self):
        parser = d.build_parser()
        args = parser.parse_args(['handoff-preview', '--project', str(self.root),
                '--origin-file', str(self.root/'origin'), '--origin-preview-sha256', 'f'*64,
                '--review-path', 'src/stygnox/transactions.py', '--candidate-wheel', str(self.root/'wheel.whl')])
        self.assertEqual(args.action, 'handoff-preview')
        with self.assertRaises(SystemExit):
            parser.parse_args(['handoff-commit', '--project', str(self.root)])
