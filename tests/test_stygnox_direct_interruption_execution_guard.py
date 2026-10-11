"""C3k: ordinary execution and mutation reject quarantined installed state.

Real controller/scheduler entry functions are exercised, not mocked. The
fresh-process test imports from a disposable install-like site-packages tree.
It is not proof of the live predecessor's exclusion or a qualified release.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

from stygnox import controller, scheduler
from stygnox.direct_interruption_execution_guard import (
    QUARANTINE_MARKER, QuarantinedRuntime, refuse_quarantined_runtime,
)
from stygnox.direct_interruption_quarantine import FILENAME


ROOT = Path(__file__).resolve().parents[1]


def _project(tmp: Path) -> Path:
    subprocess.run(['git', 'init', '-q', str(tmp)], check=True, capture_output=True)
    (tmp / '.stygnox').mkdir()
    (tmp / '.stygnox' / FILENAME).write_text('{}', encoding='utf-8')
    return tmp


def _entries(project: Path):
    return {
        'controller-activate': lambda: controller.activate_controller(project, 'tester', 'ACTIVATE'),
        'controller-deactivate': lambda: controller.deactivate_controller(project, 'tester', 'DEACTIVATE'),
        'controller-preview': lambda: controller.build_run_preview(project, 'tester', 'objective', 'write'),
        'controller-run': lambda: controller.run_controller(project, 'tester', 'objective', 'write', 'a'*64, 'RUN'),
        'controller-provenance-preview': lambda: controller.build_pending_provenance_recovery_preview(project, 'tester', 'b'*64),
        'controller-provenance-recovery': lambda: controller.recover_pending_provenance(project, 'tester', 'b'*64, 'c'*64, 'RECOVER_PENDING_PROVENANCE'),
        'scheduler-preview': lambda: scheduler.build_schedule_preview(project, 'tester'),
        'scheduler-run': lambda: scheduler.run_schedule(project, 'tester', 'd'*64, 'SCHEDULE'),
        'scheduler-recovery-preview': lambda: scheduler.build_recovery_preview(project, 'tester', []),
        'scheduler-recover': lambda: scheduler.recover_interrupted(project, 'tester', [], 'e'*64, 'RECOVER'),
    }


class QuarantinedExecutionGuardTests(unittest.TestCase):
    def test_guard_marker_matches_published_quarantine_contract(self):
        self.assertEqual(QUARANTINE_MARKER, FILENAME)

    def test_real_controller_and_scheduler_entries_refuse_before_runtime_writes(self):
        with tempfile.TemporaryDirectory(prefix='stygnox-c3k-') as td:
            root = _project(Path(td))
            marker = root/'.stygnox'/FILENAME
            before = marker.read_bytes()
            for name, invoke in _entries(root).items():
                with self.subTest(name=name):
                    expected = controller.ControllerError if name.startswith('controller') else scheduler.SchedulerError
                    with self.assertRaisesRegex(expected, 'RECOVERY_QUARANTINED'):
                        invoke()
                    self.assertEqual(marker.read_bytes(), before)
                    self.assertFalse((root/'.stygnox'/'scheduler.json').exists())
                    self.assertFalse((root/'.stygnox'/'pending-provenance').exists())

    def test_any_marker_object_blocks_even_when_corrupted_or_symlinked(self):
        with tempfile.TemporaryDirectory(prefix='stygnox-c3k-') as td:
            root = _project(Path(td))
            marker = root/'.stygnox'/FILENAME
            marker.unlink()
            marker.mkdir()
            with self.assertRaisesRegex(QuarantinedRuntime, 'RECOVERY_QUARANTINED'):
                refuse_quarantined_runtime(root)
            marker.rmdir()
            marker.symlink_to(root/'missing')
            with self.assertRaisesRegex(QuarantinedRuntime, 'RECOVERY_QUARANTINED'):
                refuse_quarantined_runtime(root)

    def test_runtime_symlink_refused_and_absent_marker_does_not_grant_authority(self):
        with tempfile.TemporaryDirectory(prefix='stygnox-c3k-') as td:
            root = _project(Path(td))
            (root/'.stygnox'/FILENAME).unlink()
            self.assertIsNone(refuse_quarantined_runtime(root))
            (root/'.stygnox').rename(root/'runtime-original')
            (root/'.stygnox').symlink_to(root/'runtime-original', target_is_directory=True)
            with self.assertRaisesRegex(QuarantinedRuntime, 'not a real directory'):
                refuse_quarantined_runtime(root)

    def test_independently_imported_site_package_fresh_process_refuses(self):
        with tempfile.TemporaryDirectory(prefix='stygnox-c3k-installed-') as td:
            root = Path(td)
            project = root/'project'
            project.mkdir()
            _project(project)
            virtual = root/'venv'
            venv.EnvBuilder(with_pip=False, symlinks=True, system_site_packages=True).create(virtual)
            interpreter = virtual/'bin'/'python3'
            proc = subprocess.run([str(interpreter), '-I', '-c',
                "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
                check=True, capture_output=True, text=True)
            package = Path(proc.stdout.strip())/'stygnox'
            shutil.copytree(ROOT/'src'/'stygnox', package,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            script = '''import json,sys
from pathlib import Path
from stygnox import controller,scheduler
root=Path(sys.argv[1])
entries = (
 ('controller-preview', lambda: controller.build_run_preview(root,'tester','objective','write')),
 ('controller-run', lambda: controller.run_controller(root,'tester','objective','write','a'*64,'RUN')),
 ('scheduler-preview', lambda: scheduler.build_schedule_preview(root,'tester')),
 ('scheduler-run', lambda: scheduler.run_schedule(root,'tester','b'*64,'SCHEDULE')),
)
result={}
for name, fn in entries:
 try:
  fn()
 except (controller.ControllerError,scheduler.SchedulerError) as exc:
  result[name]='RECOVERY_QUARANTINED' in str(exc)
 else:
  result[name]=False
print(json.dumps(result,sort_keys=True))
'''
            p = subprocess.run([str(interpreter), '-I', '-c', script, str(project)],
                               text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            evidence = json.loads(p.stdout)
            self.assertEqual(len(evidence), 4)
            self.assertTrue(all(evidence.values()), evidence)
            self.assertFalse((project/'.stygnox'/'scheduler.json').exists())


if __name__ == '__main__':
    unittest.main()
