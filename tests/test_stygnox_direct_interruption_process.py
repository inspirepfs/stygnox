"""C3d exact process identity and real kernel drain, no live PID targets."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import TestCase

from stygnox.direct_interruption_process import (
    ProcessDrainRefused, ProcessIdentity, drain_exact_child, read_process_identity,
)


class IdentityChecks(TestCase):
    def test_pid_refusal(self):
        for pid in (0, 1, -1):
            with self.subTest(pid=pid), self.assertRaises(ProcessDrainRefused):
                read_process_identity(pid)

    def test_refuse_nonexistent_process(self):
        with self.assertRaises(ProcessDrainRefused):
            read_process_identity(2**31 - 1)

    def test_wrong_start_time_cannot_signal_existing_child(self):
        if os.geteuid() == 0:
            self.skipTest('root UID process identity deliberately excluded')
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
        try:
            identity = read_process_identity(proc.pid)
            forged = ProcessIdentity(proc.pid, identity.start_ticks + 1, identity.uid)
            with self.assertRaisesRegex(ProcessDrainRefused, 'changed'):
                drain_exact_child(proc, expected=forged)
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0,
                     'root required for real disposable UID drain')
class RealKernelTests(TestCase):
    def test_disposable_fd_writer_drained_before_successor(self):
        from importlib.util import module_from_spec, spec_from_file_location
        script = Path(__file__).resolve().parents[1] / 'scripts/probe_c3d_process_drain.py'
        spec = spec_from_file_location('stygnox_c3d_probe', script)
        assert spec and spec.loader
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.simulate(65534)
        self.assertTrue(result['predecessor_drained'])
        self.assertTrue(result['predecessor_new_writes_excluded'])
        self.assertTrue(result['preopened_writer_could_not_publish_after_drain'])
        self.assertTrue(result['successor_write_succeeded'])
        self.assertFalse(result['exclusive_handoff_proved'])
        self.assertFalse(result['live_runtime_modified'])

    def test_forged_start_ticks_refused_before_signal(self):
        from importlib.util import module_from_spec, spec_from_file_location
        script = Path(__file__).resolve().parents[1] / 'scripts/probe_c3d_process_drain.py'
        spec = spec_from_file_location('stygnox_c3d_probe_forgery', script)
        assert spec and spec.loader
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'],
                                preexec_fn=lambda: mod._drop(65534))
        try:
            identity = read_process_identity(proc.pid)
            forged = ProcessIdentity(proc.pid, identity.start_ticks + 100, identity.uid)
            with self.assertRaisesRegex(ProcessDrainRefused, 'changed'):
                drain_exact_child(proc, expected=forged)
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)

class HostScanChecks(TestCase):
    def test_unprivileged_pid_scan_is_read_only(self):
        from stygnox.direct_interruption_process import assess_worktree_holders
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            before = sorted(p.iterdir())
            result = assess_worktree_holders(p, predecessor_uid=65534)
            self.assertFalse(result['quiescence_proved'])
            self.assertFalse(result['handoff_admissible'])
            self.assertFalse(result['live_runtime_modified'])
            self.assertEqual(before, sorted(p.iterdir()))

    def test_nonabsolute_worktree_rejected(self):
        from stygnox.direct_interruption_process import assess_worktree_holders
        with self.assertRaises(ProcessDrainRefused):
            assess_worktree_holders(Path('relative'), predecessor_uid=1000)


@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0,
                     'root required for cross-UID holder scan fixture')
class RealHostSnapshot(TestCase):
    def test_detects_real_legacy_cwd_and_open_fd(self):
        import tempfile
        from stygnox.direct_interruption_process import assess_worktree_holders
        with tempfile.TemporaryDirectory(prefix='stygnox-c3d-scan-', dir='/run') as temp:
            worktree = Path(temp)
            worktree.chmod(0o755)
            target = worktree / 'open.txt'
            target.write_text('test')
            os.chown(target, 65534, 65534)
            target.chmod(0o600)
            def drop():
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            child = subprocess.Popen(
                [sys.executable, '-u', '-c',
                 "import sys,time; f=open(sys.argv[1], 'ab'); print('READY',flush=True); time.sleep(20)",
                 str(target)], cwd=worktree, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, preexec_fn=drop)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'READY')
                result = assess_worktree_holders(worktree, predecessor_uid=65534)
                selected = [x for x in result['potential_worktree_holders']
                            if x['pid'] == child.pid]
                self.assertTrue(selected or child.pid in result['uninspectable_process_pids'])
                if selected:
                    self.assertTrue(selected[0]['cwd_under_worktree'] or
                                    selected[0]['worktree_fd_count'] >= 1)
                self.assertFalse(result['no_matches_observed'])
                self.assertFalse(result['quiescence_proved'])
            finally:
                child.terminate()
                child.wait(timeout=5)
                child.stdout.close()
                child.stderr.close()

@unittest.skipUnless(os.name == 'posix' and os.geteuid() == 0,
                     'root required for uncooperative process fixture')
class HostileDrain(TestCase):
    def test_uncooperative_child_is_not_reported_drained(self):
        from importlib.util import module_from_spec, spec_from_file_location
        script = Path(__file__).resolve().parents[1] / 'scripts/probe_c3d_process_drain.py'
        spec = spec_from_file_location('stygnox_c3d_hostile', script)
        assert spec and spec.loader
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        child = subprocess.Popen(
            [sys.executable, '-u', '-c',
             "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('READY', flush=True); time.sleep(20)"],
            preexec_fn=lambda: mod._drop(65534),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'READY')
            identity = read_process_identity(child.pid)
            with self.assertRaisesRegex(ProcessDrainRefused, 'did not stop'):
                drain_exact_child(child, expected=identity, timeout=0.1)
            self.assertIsNone(child.poll())
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
