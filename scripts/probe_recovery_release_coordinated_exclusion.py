#!/usr/bin/env python3
"""Release 02E: combined disposable mount denial + exact pidfd drain.

Only accepts --simulate and --predecessor-uid. Never accepts a live path,
plan, installed predecessor, transaction, or release flag. Both the original
and the executable are inert fixtures created by this process. The bind mount
is PRIVATE TO A NEW MOUNT NAMESPACE; it does not deny host-wide access and it
will disappear if the supervisor crashes. No workspace is retired and no
execution authority is granted. Run trusted copies from a root-owned stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

# -I ignores PYTHONPATH and the script directory. Use only this script's
# co-located, explicitly installed code in the protected root-only stage.
# This is not a generic package search path.
_STAGE = Path(__file__).absolute().parent
sys.path.insert(0, str(_STAGE))

# In the independently installed, root-owned test stage this script and the
# mount helper are co-located, and the stygnox package is installed alongside.
from probe_recovery_release_mount_denial import (
    MountDenialRefused, _private_namespace, _fixture_root,
    _private_bind_denial, _child_access_probe, _umount,
)
from stygnox.direct_interruption_batch_drain import (
    BatchDrainRefused, drain_exact_predecessor_batch,
)
from stygnox.direct_interruption_nonchild_drain import InstalledPredecessor
from stygnox.direct_interruption_process import read_process_identity, ProcessDrainRefused


class CoordinatedExclusionRefused(RuntimeError):
    """No authority can be inferred from an incomplete disposable sequence."""


_INERT_CHILD = '''import os, signal, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC)
sys.stdout.write("READY\\n")
sys.stdout.flush()
signal.pause()
'''


def _create_root_owned_installed_fixture(directory: Path) -> tuple[Path, str]:
    directory.mkdir(mode=0o755)
    os.chmod(directory, 0o755)
    script = directory / 'installed-predecessor.py'
    with script.open('x', encoding='utf-8') as handle:
        handle.write(_INERT_CHILD)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(script, 0o555)
    info = script.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
        raise CoordinatedExclusionRefused('disposable installed script identity invalid')
    return script, hashlib.sha256(script.read_bytes()).hexdigest()


def _child_preexec(uid: int) -> None:
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)


def _ready_child(child: subprocess.Popen[str]) -> None:
    if child.stdout is None or not select.select([child.stdout], [], [], 5)[0]:
        raise CoordinatedExclusionRefused('inert predecessor did not signal readiness')
    if child.stdout.readline().strip() != 'READY' or child.poll() is not None:
        raise CoordinatedExclusionRefused('inert predecessor did not open its file')


def _preopened_write_descriptor_verified(pid: int, expected_file: Path) -> bool:
    try:
        for fd in (Path('/proc') / str(pid) / 'fd').iterdir():
            if not fd.name.isdigit():
                continue
            if os.readlink(fd) != str(expected_file):
                continue
            info = ((Path('/proc') / str(pid) / 'fdinfo') / fd.name).read_text()
            flags = next((line.split(':', 1)[1].strip() for line in info.splitlines()
                          if line.startswith('flags:')), None)
            if flags is not None and int(flags, 8) & os.O_ACCMODE in (os.O_WRONLY, os.O_RDWR):
                return True
    except (OSError, ValueError) as exc:
        raise CoordinatedExclusionRefused(f'cannot prove preopened descriptor: {exc}') from exc
    return False


def _trusted_service_and_source() -> None:
    """Never attempt privileged simulation from a sudo user-session checkout."""
    try:
        cgroups = Path('/proc/self/cgroup').read_text(encoding='utf-8')
    except OSError as exc:
        raise CoordinatedExclusionRefused(f'cannot attest system service: {exc}') from exc
    if not any('/system.slice/stygnox-recovery-release02e-' in line and
               line.rstrip().endswith('.service') for line in cgroups.splitlines()):
        raise CoordinatedExclusionRefused('dedicated systemd root-service scope required')
    directory = Path(__file__).absolute().parent
    for entry in (*reversed(directory.parents), directory):
        info = entry.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or
                stat.S_IMODE(info.st_mode) & 0o022):
            raise CoordinatedExclusionRefused(f'untrusted supervisor source ancestor: {entry}')
    if stat.S_IMODE(directory.lstat().st_mode) & 0o077:
        raise CoordinatedExclusionRefused('supervisor source directory must be root-only')
    for name in ('probe_recovery_release_coordinated_exclusion.py',
                 'probe_recovery_release_mount_denial.py'):
        info = (directory / name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                stat.S_IMODE(info.st_mode) & 0o022):
            raise CoordinatedExclusionRefused(f'untrusted supervisor script: {name}')


def simulate(predecessor_uid: int) -> dict[str, Any]:
    if (not isinstance(predecessor_uid, int) or isinstance(predecessor_uid, bool)
            or predecessor_uid <= 0 or predecessor_uid in (65534, os.getuid())):
        # Must be a distinct non-root user when using the fixture; root is the
        # supervisor. If invoked by root, its uid is zero, so any valid target
        # passes this check.
        raise CoordinatedExclusionRefused('distinct non-root predecessor UID required')
    if os.geteuid() != 0 or os.getuid() != 0:
        raise CoordinatedExclusionRefused('dedicated Linux root process required')
    if not hasattr(os, 'pidfd_open') or not hasattr(__import__('signal'), 'pidfd_send_signal'):
        raise CoordinatedExclusionRefused('Linux pidfd signalling unavailable')
    _trusted_service_and_source()
    # Unshare before any mount. The host's namespace is never changed.
    _private_namespace()
    root = _fixture_root()
    executable_root: Path | None = None
    target = root / 'legacy-parent' / 'original'
    child: subprocess.Popen[str] | None = None
    overlay_active = False
    try:
        executable_root = Path(tempfile.mkdtemp(prefix='stygnox-rr02e-installed-', dir='/tmp'))
        os.chmod(executable_root, 0o755)
        script, installed_sha256 = _create_root_owned_installed_fixture(executable_root / 'bin')
        target.parent.mkdir(mode=0o755)
        os.chown(target.parent, predecessor_uid, predecessor_uid)
        target.mkdir(mode=0o700)
        os.chown(target, predecessor_uid, predecessor_uid)
        runtime = target / '.stygnox'
        runtime.mkdir(mode=0o700)
        os.chown(runtime, predecessor_uid, predecessor_uid)
        plan = runtime / 'plan.json'
        plan.write_bytes(b'{"inert_disposable_fixture":true}\n')
        os.chmod(plan, 0o600)
        os.chown(plan, predecessor_uid, predecessor_uid)
        gate = root / 'root-owned-denial'
        gate.mkdir(mode=0o700)

        child = subprocess.Popen(
            [sys.executable, str(script), str(plan)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, preexec_fn=lambda: _child_preexec(predecessor_uid),
        )
        _ready_child(child)
        if not _preopened_write_descriptor_verified(child.pid, plan):
            raise CoordinatedExclusionRefused('preopened legacy write FD was not proven')
        approval = InstalledPredecessor(read_process_identity(child.pid), script, installed_sha256)

        # Refuse fresh access BEFORE signalling. The process can still hold an
        # FD until pidfd draining is complete, so there is no authority transfer.
        _private_bind_denial(target, gate)
        overlay_active = True
        access_before = _child_access_probe(target, predecessor_uid)
        if any(access_before.values()):
            raise CoordinatedExclusionRefused('fresh predecessor path access remained possible')
        drained = drain_exact_predecessor_batch((approval,), timeout=5)
        child.wait(timeout=5)
        if child.returncode is None or child.returncode == 0:
            raise CoordinatedExclusionRefused('inert predecessor did not terminate as expected')
        if not drained['exact_batch_exited_via_pidfd']:
            raise CoordinatedExclusionRefused('kernel pidfd exit not established')
        access_after = _child_access_probe(target, predecessor_uid)
        if any(access_after.values()):
            raise CoordinatedExclusionRefused('fresh path access resumed after drain')
        try:
            read_process_identity(approval.identity.pid)
        except ProcessDrainRefused:
            pass
        else:
            raise CoordinatedExclusionRefused('predecessor remained accessible after reaping')
        return {
            'schema': 'stygnox_release02e_disposable_coordinated_exclusion_v1',
            'fixture_type': 'private_mount_namespace_inert_pidfd_drained_predecessor',
            'separate_mount_namespace': True,
            'preexisting_writable_fd_observed_before_drain': True,
            'fresh_path_access_denied_before_drain': True,
            'exact_installed_predecessor_identity_pinned': True,
            'exact_predecessor_pidfd_drained': True,
            'predecessor_reaped': True,
            'fresh_path_access_denied_after_drain': True,
            'path_denial_held_through_drain': True,
            'old_fds_revoked_systemwide': False,
            'all_predecessor_processes_excluded': False,
            'host_wide_relaunch_excluded': False,
            'reboot_persistent_denial_proved': False,
            'original_binding_retired': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
            'authority_changed': False,
            'provider_executed': False,
            'live_runtime_modified': False,
        }
    finally:
        # All cleanup runs INSIDE the private namespace. A failed drain never
        # produces success evidence; no live or parent mount can be touched.
        if child is not None:
            if child.poll() is None:
                child.terminate()  # ONLY our own inert subprocess
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired as exc:
                raise CoordinatedExclusionRefused('inert child failed to exit during cleanup') from exc
            if child.stdout:
                child.stdout.close()
            if child.stderr:
                child.stderr.close()
        if overlay_active:
            _umount(str(target))
        shutil.rmtree(root)
        if executable_root is not None:
            shutil.rmtree(executable_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(simulate(args.predecessor_uid), indent=2, sort_keys=True))
        return 0
    except (CoordinatedExclusionRefused, MountDenialRefused, BatchDrainRefused,
            OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Recovery Release 02E coordinated exclusion REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
