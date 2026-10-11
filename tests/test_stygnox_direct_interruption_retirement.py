"""C3f kernel-real root-owned namespace retirement contract tests."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest

from stygnox.direct_interruption_retirement import RetirementRefused, retire_predecessor_path


class RetirementValidationTests(unittest.TestCase):
    def test_relative_paths_refused(self):
        with self.assertRaises(RetirementRefused):
            retire_predecessor_path(Path('old'), Path('vault/new'),
                                    predecessor_uid=1000, expected_dev=1, expected_inode=1)

    def test_no_root_uid_predecessor(self):
        with self.assertRaises(RetirementRefused):
            retire_predecessor_path(Path('/run/old'), Path('/run/vault/new'),
                                    predecessor_uid=0, expected_dev=1, expected_inode=1)

    def test_untrusted_parent_refused(self):
        with self.assertRaises(RetirementRefused):
            retire_predecessor_path(Path('/tmp/untrusted/original'), Path('/tmp/vault/new'),
                                    predecessor_uid=1000, expected_dev=1, expected_inode=1)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0 and Path('/run').is_dir(),
                     'requires disposable Linux root namespace')
class RootRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/run', prefix='stygnox-c3f-unittest-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.base.chmod(0o755)
        self.active = self.base / 'active'
        self.active.mkdir(mode=0o711)
        self.vault = self.base / 'vault'
        self.vault.mkdir(mode=0o700)
        self.old = self.active / 'old'
        self.old.mkdir(mode=0o700)
        self.legacy_uid = 61010
        os.chown(self.old, self.legacy_uid, self.legacy_uid)
        self.file = self.old / 'authority.json'
        self.file.write_text('UNCHANGED')
        os.chown(self.file, self.legacy_uid, self.legacy_uid)
        self.file.chmod(0o600)
        self.identity = self.old.lstat()
        self.dest = self.vault / 'retired'

    def retire(self):
        return retire_predecessor_path(self.old, self.dest,
                                       predecessor_uid=self.legacy_uid,
                                       expected_dev=self.identity.st_dev,
                                       expected_inode=self.identity.st_ino)

    def test_real_rename_preserves_inode_and_source_bytes(self):
        record = self.retire()
        self.assertTrue(record['old_path_missing'])
        self.assertFalse(self.old.exists())
        self.assertEqual((self.dest.stat().st_dev, self.dest.stat().st_ino),
                         (self.identity.st_dev, self.identity.st_ino))
        self.assertEqual((self.dest / 'authority.json').read_text(), 'UNCHANGED')
        self.assertFalse(record['handoff_admissible'])
        self.assertFalse(record['original_controller_authority_retired'])
        self.assertFalse(record['preopened_descriptors_revoked'])

    def test_replay_refuses_to_act_again(self):
        self.retire()
        with self.assertRaises(RetirementRefused):
            self.retire()
        self.assertTrue(self.dest.is_dir())

    def test_stale_inode_refused_without_mutation(self):
        with self.assertRaisesRegex(RetirementRefused, 'identity'):
            retire_predecessor_path(self.old, self.dest, predecessor_uid=self.legacy_uid,
                                    expected_dev=self.identity.st_dev,
                                    expected_inode=self.identity.st_ino + 1)
        self.assertTrue(self.old.is_dir())
        self.assertFalse(self.dest.exists())

    def test_vault_destination_collision_refused(self):
        self.dest.mkdir()
        with self.assertRaisesRegex(RetirementRefused, 'already exists'):
            self.retire()
        self.assertEqual(self.file.read_text(), 'UNCHANGED')

    def test_untrusted_source_parent_refused(self):
        self.active.chmod(0o777)
        with self.assertRaisesRegex(RetirementRefused, 'root-controlled'):
            self.retire()
        self.assertTrue(self.old.exists())

    def test_exposed_vault_refused(self):
        self.vault.chmod(0o755)
        with self.assertRaisesRegex(RetirementRefused, 'root-only'):
            self.retire()
        self.assertTrue(self.old.exists())

    def test_symlink_vault_parent_refused(self):
        link = self.base / 'link'
        link.symlink_to(self.vault, target_is_directory=True)
        with self.assertRaisesRegex(RetirementRefused, 'root-controlled'):
            retire_predecessor_path(self.old, link / 'new', predecessor_uid=self.legacy_uid,
                                    expected_dev=self.identity.st_dev, expected_inode=self.identity.st_ino)
        self.assertTrue(self.old.exists())

    def test_preopened_descriptor_remains_writable_post_rename(self):
        # This is the explicit negative contract: retirement is not a drain.
        fd = os.open(self.file, os.O_WRONLY | os.O_APPEND)
        try:
            self.retire()
            os.write(fd, b'AFTER-RENAME')
        finally:
            os.close(fd)
        self.assertEqual((self.dest / 'authority.json').read_text(), 'UNCHANGEDAFTER-RENAME')


if __name__ == '__main__':
    unittest.main()
