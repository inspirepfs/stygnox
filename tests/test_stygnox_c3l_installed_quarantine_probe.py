"""C3l installer qualification probe safety and evidence tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_c3l_installed_quarantine.py'
SPEC = importlib.util.spec_from_file_location('stygnox_c3l_probe', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class InstalledQuarantineProbeTests(unittest.TestCase):
    def test_missing_wheel_refuses_before_install(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError, 'regular non-symlink wheel'):
                module.qualify(Path(td) / 'missing.whl')

    def test_symlink_wheel_refuses_before_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'candidate.whl').write_bytes(b'untrusted')
            (root / 'linked.whl').symlink_to(root / 'candidate.whl')
            with self.assertRaisesRegex(RuntimeError, 'regular non-symlink wheel'):
                module.qualify(root / 'linked.whl')

    def test_fixture_snapshot_detects_addition_mutation_and_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = root / '.stygnox'
            fixture.mkdir()
            marker = fixture / 'direct-interruption-quarantined-binding.json'
            marker.write_bytes(b'{}')
            baseline = module.snapshot(root)
            self.assertEqual(len(baseline), 1)
            marker.write_bytes(b'{"modified":true}')
            self.assertNotEqual(module.snapshot(root), baseline)
            marker.write_bytes(b'{}')
            self.assertEqual(module.snapshot(root), baseline)
            marker.unlink()
            self.assertNotEqual(module.snapshot(root), baseline)


if __name__ == '__main__':
    unittest.main()
