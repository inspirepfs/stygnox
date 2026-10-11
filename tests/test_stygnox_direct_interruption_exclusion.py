"""C3c: real Linux DAC isolation, no simulated mock locks or authority changes."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest import TestCase

from stygnox.direct_interruption_exclusion import ExclusionRefused, verify_dac_boundary


class BoundaryValidation(TestCase):
    def test_same_uid_is_never_a_boundary(self):
        with self.assertRaisesRegex(ExclusionRefused, 'distinct non-root'):
            verify_dac_boundary(Path('/root'), predecessor_uid=1000, successor_uid=1000)

    def test_root_predecessor_is_never_fenced_by_dac(self):
        with self.assertRaisesRegex(ExclusionRefused, 'distinct non-root'):
            verify_dac_boundary(Path('/root'), predecessor_uid=0, successor_uid=1000)

    def test_relative_and_dotdot_paths_refused(self):
        for p in (Path('relative'), Path('/tmp/../run')):
            with self.subTest(path=str(p)), self.assertRaisesRegex(ExclusionRefused, 'absolute, canonical'):
                verify_dac_boundary(p, predecessor_uid=1000, successor_uid=1001)

    def test_nonexistent_and_symlink_ancestors_refused(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base/'redirect').symlink_to('/run')
            with self.assertRaises(ExclusionRefused):
                verify_dac_boundary(base/'redirect'/'child', predecessor_uid=1000, successor_uid=1001)

    def test_readonly_live_assessment_reports_unsealed_without_writing(self):
        from importlib.util import spec_from_file_location, module_from_spec
        script = Path(__file__).resolve().parents[1] / 'scripts/probe_c3c_linux_exclusion.py'
        spec = spec_from_file_location('c3c_readonly', script)
        assert spec is not None and spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as root:
            worktree = Path(root)
            (worktree/'.stygnox').mkdir()
            before = sorted(x.relative_to(worktree) for x in worktree.rglob('*'))
            result = mod.assess_worktree(worktree, legacy_uid=65534, successor_uid=61001)
            self.assertFalse(result['kernel_path_boundary_sealed'])
            self.assertFalse(result['handoff_admissible'])
            self.assertFalse(result['authority_changed'])
            self.assertEqual(before, sorted(x.relative_to(worktree) for x in worktree.rglob('*')))

    def test_normal_user_owned_checkout_is_not_accepted(self):
        if os.geteuid() == 0:
            self.skipTest('ordinary user boundary requires non-root pytest')
        with self.assertRaises(ExclusionRefused):
            verify_dac_boundary(Path.cwd(), predecessor_uid=os.getuid(), successor_uid=61001)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0, 'root required for real UID isolation test')
class KernelIsolation(TestCase):
    def test_actual_cross_uid_mutations_blocked_in_disposable_tree(self):
        from importlib.util import spec_from_file_location, module_from_spec
        script = Path(__file__).resolve().parents[1] / 'scripts/probe_c3c_linux_exclusion.py'
        spec = spec_from_file_location('c3c_probe', script)
        assert spec is not None and spec.loader is not None
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.simulate(65534)
        self.assertTrue(result['predecessor_new_writes_excluded'])
        self.assertTrue(result['authority_files_unchanged'])
        self.assertTrue(result['dac_boundaries_verified'])
        self.assertTrue(all(result['successor_mutations_succeeded'].values()))
        self.assertFalse(result['handoff_admissible'])
        self.assertFalse(result['inflight_predecessor_excluded'])
        self.assertTrue(result['preopened_legacy_fd_can_still_write'])
        self.assertFalse(result['authority_changed'])

    def test_parent_replacement_is_refused_even_if_leaf_is_private(self):
        # This is a separate explicit negative case: an old-owned ancestor
        # can rename/replace a sealed directory despite the leaf being 0700.
        with tempfile.TemporaryDirectory(prefix='stygnox-c3c-', dir='/run') as root:
            parent = Path(root)
            os.chown(parent, 65534, 65534)
            leaf = parent/'private'
            leaf.mkdir(mode=0o700)
            os.chown(leaf, 61001, 61001)
            with self.assertRaisesRegex(ExclusionRefused, 'untrusted UID'):
                verify_dac_boundary(leaf, predecessor_uid=65534, successor_uid=61001)
