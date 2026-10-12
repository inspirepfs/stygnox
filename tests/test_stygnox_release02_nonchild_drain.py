"""Release 02: kernel-real exact predecessor PIDFD drain, no authority grants."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

import pytest

from stygnox.direct_interruption_nonchild_drain import (
    InstalledPredecessor, NonchildDrainRefused, drain_exact_installed_predecessor,
)
from stygnox.direct_interruption_process import read_process_identity

pytestmark = pytest.mark.skipif(
    os.name != 'posix' or not hasattr(os, 'pidfd_open') or
    not hasattr(signal, 'pidfd_send_signal') or not Path('/proc/self/status').exists(),
    reason='requires Linux pidfd and procfs',
)


@pytest.fixture
def inert_installed_command():
    with tempfile.TemporaryDirectory(prefix='stygnox-rr02-inert-', dir='/tmp') as temp:
        folder = Path(temp)
        folder.chmod(0o755)
        path = folder / 'stygnox-inert'
        path.write_text('import signal\nimport time\n'
                        'signal.signal(signal.SIGTERM, lambda s, f: exit(0))\n'
                        'print("READY", flush=True)\n'
                        'while True: time.sleep(.05)\n')
        path.chmod(0o644)
        yield path


@contextmanager
def _child(path: Path):
    uid = 61021 if os.geteuid() == 0 else os.getuid()
    if uid == 0:
        pytest.skip('non-root process UID required')
    def switch():
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    child = subprocess.Popen([sys.executable, str(path)], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True,
                             preexec_fn=switch if os.geteuid() == 0 else None)
    try:
        assert child.stdout.readline().strip() == 'READY'
        # Some containers restrict cross-UID /proc/exe even to root; the real
        # host service must fail closed rather than weakening this check.
        try:
            os.readlink(f'/proc/{child.pid}/exe')
        except PermissionError:
            pytest.skip('cross-UID /proc/exe not visible in this container')
        yield child
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=4)
        child.stdout.close()
        child.stderr.close()


def _approval(child, path):
    return InstalledPredecessor(
        identity=read_process_identity(child.pid), installed_path=path,
        installed_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_exact_installed_process_exits_without_child_handle(inert_installed_command):
    with _child(inert_installed_command) as child:
        approval = _approval(child, inert_installed_command)
        result = drain_exact_installed_predecessor(approval, timeout=3)
        assert result['exact_process_exited_via_pidfd'] is True
        assert result['new_legacy_starts_blocked'] is False
        assert result['handoff_admissible'] is False
        assert child.wait(timeout=2) == 0


def test_wrong_starttime_refuses_without_killing(inert_installed_command):
    with _child(inert_installed_command) as child:
        original = _approval(child, inert_installed_command)
        wrong = InstalledPredecessor(
            identity=original.identity.__class__(original.identity.pid, original.identity.start_ticks + 1,
                                                 original.identity.uid),
            installed_path=original.installed_path, installed_sha256=original.installed_sha256)
        with pytest.raises(NonchildDrainRefused, match='identity changed'):
            drain_exact_installed_predecessor(wrong)
        assert child.poll() is None


def test_digest_mismatch_refuses_without_killing(inert_installed_command):
    with _child(inert_installed_command) as child:
        original = _approval(child, inert_installed_command)
        wrong = InstalledPredecessor(identity=original.identity, installed_path=original.installed_path,
                                     installed_sha256='0' * 64)
        with pytest.raises(NonchildDrainRefused, match='digest changed'):
            drain_exact_installed_predecessor(wrong)
        assert child.poll() is None


def test_non_invocation_text_reference_cannot_authorise_drain(inert_installed_command):
    # An unrelated 'python -c' mentioning the installed script is not an invocation.
    uid = 61021 if os.geteuid() == 0 else os.getuid()
    if uid == 0:
        pytest.skip('non-root UID required')
    script = 'import time;print("READY",flush=True);time.sleep(4)'
    def switch():
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    child = subprocess.Popen([sys.executable, '-c', script, str(inert_installed_command)],
                             stdout=subprocess.PIPE, text=True,
                             preexec_fn=switch if os.geteuid() == 0 else None)
    try:
        assert child.stdout.readline().strip() == 'READY'
        approval = _approval(child, inert_installed_command)
        with pytest.raises(NonchildDrainRefused, match='not running the pinned installed command'):
            drain_exact_installed_predecessor(approval)
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=4)
        child.stdout.close()
