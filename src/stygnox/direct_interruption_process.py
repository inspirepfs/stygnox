"""C3d narrow PIDFD identity guard for an operator-controlled process drain.

This primitive cannot stop new launches, escaped descendants, or an unrelated
same-UID process. There is deliberately no live authority transfer or arbitrary
PID termination command. The first integration is a disposable fixture only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import signal
import subprocess


class ProcessDrainRefused(RuntimeError):
    """Fail closed on ambiguous identity or unsupported kernel behavior."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    uid: int


def read_process_identity(pid: int) -> ProcessIdentity:
    """Read a Linux /proc identity: PID, kernel start ticks and all UIDs."""
    if os.name != "posix" or not Path("/proc/self/stat").exists():
        raise ProcessDrainRefused("Linux /proc required")
    if not isinstance(pid, int) or pid < 2:
        raise ProcessDrainRefused("invalid PID")
    try:
        stat_text = (Path('/proc') / str(pid) / 'stat').read_text()
        status = (Path('/proc') / str(pid) / 'status').read_text()
    except OSError as exc:
        raise ProcessDrainRefused(f"cannot inspect PID {pid}: {exc}") from exc
    # Comm in parentheses may contain spaces and closing parentheses.
    end = stat_text.rfind(')')
    if end < 0 or len(stat_text) <= end + 2:
        raise ProcessDrainRefused('malformed /proc stat')
    fields = stat_text[end + 2:].split()
    if len(fields) <= 19 or fields[0] in ('Z', 'X', 'x'):
        raise ProcessDrainRefused('process absent or already terminated')
    uids = []
    for line in status.splitlines():
        if line.startswith('Uid:'):
            try:
                uids = [int(v) for v in line.split()[1:5]]
            except ValueError as exc:
                raise ProcessDrainRefused('malformed process UID') from exc
            break
    if len(uids) != 4 or len(set(uids)) != 1 or uids[0] <= 0:
        raise ProcessDrainRefused('requires one consistent non-root process UID')
    try:
        start_ticks = int(fields[19])
    except ValueError as exc:
        raise ProcessDrainRefused('malformed process start time') from exc
    return ProcessIdentity(pid=pid, start_ticks=start_ticks, uid=uids[0])


def drain_exact_child(child: subprocess.Popen, *, expected: ProcessIdentity, timeout: float = 5) -> dict:
    """Stop ONLY an explicitly tracked direct child via Linux pidfd.

    No process-name matching, kill-all, discovery-based termination or fallback
    to os.kill(PID). The caller is accountable for *all* descendants, future
    starts, open handles and path isolation; this function proves none of them.
    """
    if child.pid != expected.pid or expected.uid <= 0:
        raise ProcessDrainRefused('child PID or expected UID mismatch')
    if child.poll() is not None:
        raise ProcessDrainRefused('tracked child has already exited')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise ProcessDrainRefused('Linux pidfd_open/pidfd_send_signal required')
    before = read_process_identity(child.pid)
    if before != expected:
        raise ProcessDrainRefused('process PID, kernel start time or UID changed')
    try:
        pidfd = os.pidfd_open(expected.pid)
    except OSError as exc:
        raise ProcessDrainRefused(f'cannot pin process by pidfd: {exc}') from exc
    try:
        # PIDFD pins the process object even across PID reuse. Re-attest after
        # opening it; if identity changed, do not signal anything.
        if read_process_identity(child.pid) != expected:
            raise ProcessDrainRefused('process identity changed during pidfd admission')
        signal.pidfd_send_signal(pidfd, signal.SIGTERM, None, 0)
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ProcessDrainRefused('child did not stop; authority must stay blocked') from exc
    finally:
        os.close(pidfd)
    if child.poll() is None:
        raise ProcessDrainRefused('child liveness unresolved')
    try:
        after = read_process_identity(expected.pid)
    except ProcessDrainRefused:
        after = None
    if after == expected:
        raise ProcessDrainRefused('same process still active after attempted drain')
    return {
        'pid': expected.pid,
        'start_ticks': expected.start_ticks,
        'uid': expected.uid,
        'terminated_via_pidfd': True,
        'direct_child_reaped': True,
        'escaped_descendants_excluded': False,
        'new_legacy_starts_blocked': False,
        'authority_changed': False,
        'handoff_admissible': False,
    }


def assess_worktree_holders(worktree: Path, *, predecessor_uid: int) -> dict:
    """Read-only /proc snapshot of legacy-UID cwd and open worktree descriptors.

    This is advisory detection, NEVER a quiescence certificate. Processes can
    start immediately after the scan, and a provider can mutate by other means.
    Uninspectable processes are reported rather than silently ignored.
    """
    if not Path('/proc/self/fd').is_dir() or predecessor_uid <= 0:
        raise ProcessDrainRefused('Linux /proc and non-root predecessor UID required')
    target = str(worktree)
    if not worktree.is_absolute() or '..' in worktree.parts or not worktree.is_dir():
        raise ProcessDrainRefused('existing absolute canonical worktree directory required')

    def under_target(value: str) -> bool:
        if value.endswith(' (deleted)'):
            value = value[:-10]
        if not value.startswith('/'):
            return False
        try:
            return os.path.commonpath((target, value)) == target
        except ValueError:
            return False

    examined = 0
    holders = []
    unknown = []
    for entry in sorted(Path('/proc').iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else -1):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            status = (entry / 'status').read_text()
        except FileNotFoundError:
            continue
        except OSError:
            # Could be inaccessible, but we cannot know the UID. Keep it
            # visible rather than claiming the population was fully surveyed.
            unknown.append(pid)
            continue
        uid_line = next((line for line in status.splitlines() if line.startswith('Uid:')), None)
        if uid_line is None:
            unknown.append(pid)
            continue
        try:
            uids = tuple(int(v) for v in uid_line.split()[1:5])
        except ValueError:
            unknown.append(pid)
            continue
        if len(uids) != 4 or uids[0] != predecessor_uid:
            continue
        examined += 1
        if any(uid != predecessor_uid for uid in uids):
            unknown.append(pid)
            continue
        try:
            identity = read_process_identity(pid)
        except ProcessDrainRefused:
            unknown.append(pid)
            continue
        cwd_match = False
        access_failed = False
        try:
            cwd_match = under_target(os.readlink(entry / 'cwd'))
        except FileNotFoundError:
            if not entry.exists():
                continue
            access_failed = True
        except OSError:
            access_failed = True
        fds = []
        try:
            for fd in (entry / 'fd').iterdir():
                try:
                    if under_target(os.readlink(fd)):
                        fds.append(fd.name)
                except FileNotFoundError:
                    continue
                except OSError:
                    access_failed = True
        except FileNotFoundError:
            if not entry.exists():
                continue
            access_failed = True
        except OSError:
            access_failed = True
        if cwd_match or fds:
            holders.append({'pid': pid, 'start_ticks': identity.start_ticks,
                            'cwd_under_worktree': cwd_match,
                            'worktree_fd_count': len(fds)})
        if access_failed:
            unknown.append(pid)
    return {
        'schema': 'stygnox_c3d_worktree_holders_snapshot_v1',
        'worktree': target,
        'predecessor_uid': predecessor_uid,
        'predecessor_processes_examined': examined,
        'potential_worktree_holders': holders,
        'uninspectable_process_pids': sorted(set(unknown)),
        'no_matches_observed': not holders and not unknown,
        'quiescence_proved': False,
        'new_legacy_starts_blocked': False,
        'handoff_admissible': False,
        'authority_changed': False,
        'live_runtime_modified': False,
    }
