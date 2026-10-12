"""Exact-PID, pidfd-only predecessor drain for independently supervised recovery.

This is a low-level building block, *not* a CLI or authority-transfer action.
The caller must separately prove that all relevant processes/descendants and
new launches are excluded; draining one PID is never that proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import select
import signal
import stat
import time

from .direct_interruption_process import ProcessIdentity, ProcessDrainRefused, read_process_identity


class NonchildDrainRefused(ProcessDrainRefused):
    """An exact identity/launch cannot be verified or stopped by pidfd."""


@dataclass(frozen=True)
class InstalledPredecessor:
    identity: ProcessIdentity
    installed_path: Path
    installed_sha256: str


def _sha256_exact_regular(path: Path) -> str:
    if not path.is_absolute() or '..' in path.parts:
        raise NonchildDrainRefused('installed command requires canonical absolute path')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise NonchildDrainRefused('installed command is not a single regular file')
            digest = hashlib.sha256()
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    return digest.hexdigest()
                digest.update(block)
        finally:
            os.close(fd)
    except OSError as exc:
        raise NonchildDrainRefused(f'cannot pin installed command: {exc}') from exc


def _launch_is_exact(pid: int, path: Path) -> bool:
    """Only an actual argv0 script or argv1 Python script, never a mention later.

    Python -c, python -m, shells mentioning the path and unrelated processes
    are not admitted as direct installed-command invocations.
    """
    try:
        args = [a.decode('utf-8', 'surrogateescape') for a in
                (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0') if a]
    except OSError as exc:
        raise NonchildDrainRefused(f'cannot inspect command invocation: {exc}') from exc
    if not args:
        return False
    target = str(path)
    if args[0] == target:
        return True
    # For #!/usr/bin/env python, Linux reports python as the first argument.
    # Require an absolute interpreter executable; never infer from argv2+.
    if len(args) >= 2 and args[1] == target and Path(args[0]).is_absolute():
        try:
            executable = os.readlink(Path('/proc') / str(pid) / 'exe')
        except OSError as exc:
            raise NonchildDrainRefused(f'cannot inspect process executable: {exc}') from exc
        try:
            return executable == args[0] or os.path.samefile(executable, args[0])
        except OSError as exc:
            raise NonchildDrainRefused(f"interpreter identity cannot be verified: {exc}") from exc
    return False


def _attest(approval: InstalledPredecessor) -> None:
    ident = approval.identity
    if ident.pid < 2 or ident.uid <= 0 or ident.start_ticks <= 0:
        raise NonchildDrainRefused('exact non-root process identity required')
    if (len(approval.installed_sha256) != 64 or
            any(ch not in '0123456789abcdef' for ch in approval.installed_sha256)):
        raise NonchildDrainRefused('expected installed digest must be lowercase SHA-256')
    if _sha256_exact_regular(approval.installed_path) != approval.installed_sha256:
        raise NonchildDrainRefused('installed command digest changed')
    if read_process_identity(ident.pid) != ident:
        raise NonchildDrainRefused('process identity changed')
    if not _launch_is_exact(ident.pid, approval.installed_path):
        raise NonchildDrainRefused('process is not running the pinned installed command')


def drain_exact_installed_predecessor(approval: InstalledPredecessor, *, timeout: float = 5.0) -> dict:
    """TERM one independently attested process by pidfd; never PID fallback.

    Works for *nonchildren* (no subprocess.Popen handle). Never sends SIGKILL,
    sweeps UID/process names, or asserts exclusion of descendants/new launches.
    This function is deliberately not wired to a CLI or active recovery route.
    """
    if (os.name != 'posix' or not hasattr(os, 'pidfd_open') or
            not hasattr(signal, 'pidfd_send_signal')):
        raise NonchildDrainRefused('Linux pidfd capability required')
    if not (0 < timeout <= 30):
        raise NonchildDrainRefused('bounded positive timeout required')
    _attest(approval)
    try:
        pidfd = os.pidfd_open(approval.identity.pid, 0)
    except OSError as exc:
        raise NonchildDrainRefused(f'cannot open pidfd: {exc}') from exc
    try:
        _attest(approval)
        # A readable pidfd before sending means the process is already gone.
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        if poller.poll(0):
            raise NonchildDrainRefused('process exited before signal admission')
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM, None, 0)
        except OSError as exc:
            raise NonchildDrainRefused(f'pidfd signal failed: {exc}') from exc
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NonchildDrainRefused('process did not exit; authority stays blocked')
            if poller.poll(min(max(1, int(remaining * 1000)), 500)):
                break
        try:
            after = read_process_identity(approval.identity.pid)
        except ProcessDrainRefused:
            after = None
        if after == approval.identity:
            raise NonchildDrainRefused('matching process remains active after pidfd readiness')
    finally:
        os.close(pidfd)
    return {
        'schema': 'stygnox_release02_exact_nonchild_pidfd_drain_v1',
        'pid': approval.identity.pid,
        'start_ticks': approval.identity.start_ticks,
        'uid': approval.identity.uid,
        'installed_sha256': approval.installed_sha256,
        'exact_process_exited_via_pidfd': True,
        'known_descendants_excluded': False,
        'other_legacy_processes_excluded': False,
        'new_legacy_starts_blocked': False,
        'original_binding_retired': False,
        'authority_changed': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
    }
