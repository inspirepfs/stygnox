"""Release 02C: batch admission has real process behaviour, no mocks."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

import pytest

from stygnox.direct_interruption_batch_drain import (
    BatchDrainRefused, drain_exact_predecessor_batch,
)
from stygnox.direct_interruption_nonchild_drain import InstalledPredecessor
from stygnox.direct_interruption_process import read_process_identity

pytestmark = pytest.mark.skipif(
    os.name != 'posix' or not hasattr(os, 'pidfd_open') or
    not hasattr(signal, 'pidfd_send_signal') or not Path('/proc/self/status').exists(),
    reason='requires Linux pidfd and procfs',
)


@contextmanager
def _inert_processes(count=2):
    with tempfile.TemporaryDirectory(prefix='stygnox-rr02c-', dir='/tmp') as location:
        script = Path(location) / 'installed-inert'
        Path(location).chmod(0o755)
        script.write_text('import signal,time\n'
                          'signal.signal(signal.SIGTERM, lambda s,f: exit(0))\n'
                          'print("READY", flush=True)\n'
                          'while True: time.sleep(0.05)\n')
        script.chmod(0o644)
        uid = 61021 if os.geteuid() == 0 else os.getuid()
        if uid == 0:
            pytest.skip('requires a non-root predecessor UID')

        def switch():
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)

        children = []
        try:
            for _ in range(count):
                child = subprocess.Popen(
                    [sys.executable, str(script)], stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True,
                    preexec_fn=switch if os.geteuid() == 0 else None,
                )
                children.append(child)
                assert child.stdout.readline().strip() == 'READY'
            try:
                os.readlink(f'/proc/{children[0].pid}/exe')
            except PermissionError:
                pytest.skip('host denies cross-UID /proc/exe inspection')
            approvals = tuple(InstalledPredecessor(
                identity=read_process_identity(c.pid), installed_path=script,
                installed_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
            ) for c in children)
            yield children, approvals
        finally:
            for c in children:
                if c.poll() is None:
                    c.terminate()
                c.wait(timeout=4)
                if c.stdout:
                    c.stdout.close()
                if c.stderr:
                    c.stderr.close()


def test_drains_two_exact_real_processes_but_never_authorises_handoff():
    with _inert_processes() as (children, approvals):
        result = drain_exact_predecessor_batch(approvals, timeout=3)
        assert result['exact_batch_exited_via_pidfd'] is True
        assert len(result['drained_processes']) == 2
        assert result['new_legacy_starts_blocked'] is False
        assert result['handoff_admissible'] is False
        assert all(c.wait(timeout=2) == 0 for c in children)


def test_invalid_second_identity_refuses_before_signalling_first():
    with _inert_processes() as (children, approvals):
        bad = replace(approvals[1], identity=replace(approvals[1].identity,
                                                    start_ticks=approvals[1].identity.start_ticks + 1))
        with pytest.raises(BatchDrainRefused, match='attestation refused'):
            drain_exact_predecessor_batch((approvals[0], bad))
        assert all(c.poll() is None for c in children)


def test_duplicate_process_refused_without_signalling():
    with _inert_processes(count=1) as (children, approvals):
        with pytest.raises(BatchDrainRefused, match='duplicate PID'):
            drain_exact_predecessor_batch((approvals[0], approvals[0]))
        assert children[0].poll() is None


def test_wrong_digest_refused_before_signalling():
    with _inert_processes() as (children, approvals):
        bad = replace(approvals[1], installed_sha256='0'*64)
        with pytest.raises(BatchDrainRefused, match='attestation refused'):
            drain_exact_predecessor_batch((approvals[0], bad))
        assert all(c.poll() is None for c in children)


def test_empty_and_unsupported_batch_refused():
    with pytest.raises(BatchDrainRefused, match='one to 32'):
        drain_exact_predecessor_batch([])
    with pytest.raises(BatchDrainRefused, match='bounded positive'):
        drain_exact_predecessor_batch([None], timeout=0)
