"""C3e filesystem identity and non-promotion tests; no recovery mutation."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from stygnox.direct_interruption_workspace import (
    WorkspaceRefused, inspect_protected_tree, inspect_transition_candidate,
)


class NonPromotionTests(unittest.TestCase):
    def test_original_user_owned_checkout_is_not_a_sealed_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / 'old'
            old.mkdir()
            with self.assertRaises(WorkspaceRefused):
                inspect_protected_tree(old, predecessor_uid=1000, successor_uid=61001)

    def test_implicit_same_path_transition_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            tree = Path(temp)
            with self.assertRaises(WorkspaceRefused):
                inspect_transition_candidate(tree, tree,
                                             predecessor_uid=1000, successor_uid=61001)

    def test_missing_original_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            tree = Path(temp)
            with self.assertRaises(WorkspaceRefused):
                inspect_transition_candidate(tree/'missing', tree,
                                             predecessor_uid=1000, successor_uid=61001)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0,
                     'requires privileged disposable kernel filesystem fixture')
class RealKernelProtectedTreeTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory(prefix='stygnox-c3e-', dir='/run')
        self.addCleanup(self.context.cleanup)
        self.base = Path(self.context.name)
        self.base.chmod(0o755)
        self.legacy = 65534
        self.successor = 61001
        self.old = self.base / 'old'
        self.old.mkdir(mode=0o700)
        os.chown(self.old, self.legacy, self.legacy)
        self.target = self.base / 'new'
        self.target.mkdir(mode=0o700)
        os.chown(self.target, self.successor, self.successor)
        self.runtime = self.target / '.stygnox'
        self.runtime.mkdir(mode=0o700)
        os.chown(self.runtime, self.successor, self.successor)
        self.state = self.runtime / 'plan-state.json'
        self.state.write_text('unchanged')
        os.chown(self.state, self.successor, self.successor)
        self.state.chmod(0o600)

    def test_private_copy_cannot_be_promoted_to_authority(self):
        result = inspect_transition_candidate(self.old, self.target,
                                             predecessor_uid=self.legacy,
                                             successor_uid=self.successor)
        self.assertTrue(result['protected']['tree_snapshot_private'])
        self.assertFalse(result['handoff_admissible'])
        self.assertFalse(result['old_path_retired'])
        self.assertFalse(result['original_worktree_binding_transferred'])
        self.assertFalse(result['dual_authority_proved_absent'])
        self.assertEqual(self.state.read_text(), 'unchanged')

    def test_predecessor_owned_hardlink_into_protected_tree_refused(self):
        other = self.base / 'alias'
        other.write_text('old-writable-data')
        os.chown(other, self.successor, self.successor)
        other.chmod(0o600)
        os.link(other, self.runtime / 'alias')
        with self.assertRaisesRegex(WorkspaceRefused, 'nlink'):
            inspect_protected_tree(self.target, predecessor_uid=self.legacy,
                                   successor_uid=self.successor)

    def test_subtree_symlink_refused(self):
        (self.runtime / 'unsafe').symlink_to(self.old, target_is_directory=True)
        with self.assertRaisesRegex(WorkspaceRefused, 'symlink'):
            inspect_protected_tree(self.target, predecessor_uid=self.legacy,
                                   successor_uid=self.successor)

    def test_nested_legacy_owned_file_refused(self):
        os.chown(self.state, self.legacy, self.legacy)
        with self.assertRaisesRegex(WorkspaceRefused, 'non-successor-owned'):
            inspect_protected_tree(self.target, predecessor_uid=self.legacy,
                                   successor_uid=self.successor)

    def test_nested_public_file_refused(self):
        self.state.chmod(0o644)
        with self.assertRaisesRegex(WorkspaceRefused, 'permissions'):
            inspect_protected_tree(self.target, predecessor_uid=self.legacy,
                                   successor_uid=self.successor)

    def test_nested_executable_refused(self):
        self.state.chmod(0o700)
        with self.assertRaisesRegex(WorkspaceRefused, 'executable authority'):
            inspect_protected_tree(self.target, predecessor_uid=self.legacy,
                                   successor_uid=self.successor)

    def test_owner_executable_source_file_admitted_without_grant(self):
        source_file = self.target / 'run-tool.sh'
        source_file.write_text('echo test')
        os.chown(source_file, self.successor, self.successor)
        source_file.chmod(0o700)
        result = inspect_protected_tree(self.target, predecessor_uid=self.legacy,
                                        successor_uid=self.successor)
        self.assertTrue(result['tree_snapshot_private'])
        self.assertFalse(result['handoff_admissible'])

    def test_alias_of_original_inside_candidate_refused(self):
        link = self.target / 'alias'
        link.symlink_to(self.old, target_is_directory=True)
        with self.assertRaisesRegex(WorkspaceRefused, 'symlink'):
            inspect_transition_candidate(self.old, self.target,
                                         predecessor_uid=self.legacy,
                                         successor_uid=self.successor)
