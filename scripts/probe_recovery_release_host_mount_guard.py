#!/usr/bin/env python3
"""Release 02G: disposable, PID-1-visible mount denial under an isolated root service.

ONLY --simulate and --predecessor-uid are accepted. This is NOT a live guard
installer. It creates every path itself beneath a fresh /run fixture, verifies
its mount namespace is PID 1's BEFORE performing any mount, verifies the bind
is visible in /proc/1/mountinfo, drains only its own exact inert process, and
unmounts the fixture. The durable 02F journal is reconciled when the temporary
kernel denial is deliberately removed. Never grants handoff or execution.

Unlike 02D/02E this test intentionally mounts in PID 1's mount namespace.
It MUST run as an independently staged systemd root service; a failed or
interrupted process may leave a harmless root-owned disposable overlay which
requires manual cleanup. No caller-supplied path is accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

_STAGE = Path(__file__).absolute().parent
sys.path.insert(0, str(_STAGE))

from probe_recovery_release_mount_denial import (  # noqa: E402
    _mount, _umount, _child_access_probe, MS_BIND,
)
from probe_recovery_release_coordinated_exclusion import (  # noqa: E402
    _create_root_owned_installed_fixture,
    _child_preexec, _ready_child, _preopened_write_descriptor_verified,
)
from stygnox.direct_interruption_batch_drain import (  # noqa: E402
    drain_exact_predecessor_batch,
)
from stygnox.direct_interruption_nonchild_drain import InstalledPredecessor  # noqa: E402
from stygnox.direct_interruption_process import read_process_identity  # noqa: E402
from stygnox.direct_interruption_durable_exclusion import (  # noqa: E402
    prepare_blocked_journal, inspect_blocked_journal, require_reconciliation,
)

SCHEMA = 'stygnox_release02g_disposable_host_visible_denial_v1'


class HostMountGuardRefused(RuntimeError):
    """No host mount denial or authority guarantee can be inferred."""


def _require_host_supervisor() -> None:
    if os.name != 'posix' or os.geteuid() != 0 or os.getuid() != 0:
        raise HostMountGuardRefused('Linux root system service required')
    if not Path('/proc/1/mountinfo').is_file():
        raise HostMountGuardRefused('PID 1 mount table unavailable')
    cgroup = Path('/proc/self/cgroup').read_text(encoding='utf-8')
    if not any(re.fullmatch(r'[0-9]+:[^:]*:/system\.slice/stygnox-recovery-release02g-[A-Za-z0-9_.-]+\.service',
                             line) for line in cgroup.splitlines()):
        raise HostMountGuardRefused('dedicated Release 02G root system service required')
    if os.readlink('/proc/self/ns/mnt') != os.readlink('/proc/1/ns/mnt'):
        raise HostMountGuardRefused('supervisor mount namespace differs from PID 1; refusing to mount')
    script = Path(__file__).absolute()
    if script.is_symlink():
        raise HostMountGuardRefused('supervisor entry is a symlink')
    for path in (*reversed(script.parent.parents), script.parent):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise HostMountGuardRefused(f'untrusted supervisor source ancestor: {path}')
    if stat.S_IMODE(script.parent.stat().st_mode) & 0o077:
        raise HostMountGuardRefused('supervisor source directory must be root-private')
    info = script.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o022):
        raise HostMountGuardRefused('untrusted supervisor script')


def _pid1_mountpoint_present(path: Path) -> bool:
    """Read the real PID-1 mount table, not a private namespace's view."""
    if not path.is_absolute() or not str(path).startswith('/run/stygnox-rr02g-'):
        raise HostMountGuardRefused('non-disposable mountpoint rejected')
    # The generated fixture names never have spaces, tabs or backslashes.
    target = str(path)
    lines = Path('/proc/1/mountinfo').read_text(encoding='utf-8').splitlines()
    return any(len(parts := line.split(' ')) >= 5 and parts[4] == target
               for line in lines)


def _require_owned_fixture(target: Path, root: Path, gate: Path, uid: int) -> tuple[int, int]:
    """Never accept caller paths or a fixture outside this exact root."""
    if (root.parent != Path('/run') or not root.name.startswith('stygnox-rr02g-')
            or target != root / 'legacy-parent' / 'original'
            or gate != root / 'denial' or root.is_symlink()):
        raise HostMountGuardRefused('unexpected fixture path')
    for path, owner, mode in ((root, 0, 0o755), (target.parent, uid, 0o755),
                               (target, uid, 0o700), (gate, 0, 0o700)):
        st = path.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != owner
                or stat.S_IMODE(st.st_mode) != mode):
            raise HostMountGuardRefused(f'fixture ownership/mode mismatch: {path}')
    st = target.lstat()
    return st.st_dev, st.st_ino


def simulate(predecessor_uid: int) -> dict:
    if (not isinstance(predecessor_uid, int) or isinstance(predecessor_uid, bool)
            or predecessor_uid <= 0 or predecessor_uid in (65534, os.getuid())):
        raise HostMountGuardRefused('distinct non-root predecessor UID required')
    _require_host_supervisor()  # before creating anything, and before mount()
    if not hasattr(os, 'pidfd_open'):
        raise HostMountGuardRefused('Linux pidfd unavailable')
    # The caller may not supply any path. All filesystem actions are confined to
    # an exclusive newly generated /run root and /tmp inert executable fixture.
    root = Path(tempfile.mkdtemp(prefix='stygnox-rr02g-', dir='/run'))
    installed_dir: Path | None = None
    target = root / 'legacy-parent' / 'original'
    gate = root / 'denial'
    mounted = False
    child: subprocess.Popen | None = None
    try:
        os.chmod(root, 0o755)
        target.parent.mkdir(mode=0o755)
        os.chown(target.parent, predecessor_uid, predecessor_uid)
        os.chmod(target.parent, 0o755)  # independent of root-service umask
        target.mkdir(mode=0o700)
        os.chown(target, predecessor_uid, predecessor_uid)
        runtime = target / '.stygnox'
        runtime.mkdir(mode=0o700)
        os.chown(runtime, predecessor_uid, predecessor_uid)
        plan = runtime / 'plan.json'
        plan.write_bytes(b'{"disposable":"02g","authority":false}\n')
        os.chmod(plan, 0o600)
        os.chown(plan, predecessor_uid, predecessor_uid)
        transaction = runtime / 'transaction.json'
        transaction.write_bytes(b'{"disposable":true,"execution_authority":"NONE"}\n')
        os.chmod(transaction, 0o600)
        os.chown(transaction, predecessor_uid, predecessor_uid)
        gate.mkdir(mode=0o700)
        installed_dir = Path(tempfile.mkdtemp(prefix='stygnox-rr02g-inert-', dir='/tmp'))
        os.chmod(installed_dir, 0o755)
        installed_script, digest = _create_root_owned_installed_fixture(installed_dir / 'bin')
        device, inode = _require_owned_fixture(target, root, gate, predecessor_uid)
        if _pid1_mountpoint_present(target):
            raise HostMountGuardRefused('fixture target already mounted')
        journal_dir = root / 'journal'
        journal_dir.mkdir(mode=0o700)
        prepared = prepare_blocked_journal(
            journal_dir, original_path=str(target),
            installed_predecessor_path=str(installed_script),
            predecessor_uid=predecessor_uid, original_device=device,
            original_inode=inode, installed_sha256=digest,
            plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
            transaction_sha256=hashlib.sha256(transaction.read_bytes()).hexdigest(),
        )
        child = subprocess.Popen(
            [sys.executable, str(installed_script), str(plan)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            preexec_fn=lambda: _child_preexec(predecessor_uid),
        )
        _ready_child(child)
        if not _preopened_write_descriptor_verified(child.pid, plan):
            raise HostMountGuardRefused('old writable FD was not observed')
        approved = InstalledPredecessor(read_process_identity(child.pid), installed_script, digest)
        # GLOBAL TO THIS HOST: _require_host_supervisor verified PID 1's mount
        # namespace. Only this disposable test path may ever be overmounted.
        _mount(str(gate), str(target), MS_BIND)
        mounted = True
        if not _pid1_mountpoint_present(target):
            raise HostMountGuardRefused('denial mount not visible in PID 1 mountinfo')
        access_before = _child_access_probe(target, predecessor_uid)
        if any(access_before.values()):
            raise HostMountGuardRefused(f'old UID can access overmounted path: {access_before}')
        drained = drain_exact_predecessor_batch((approved,), timeout=5)
        child.wait(timeout=5)
        if not drained['exact_batch_exited_via_pidfd']:
            raise HostMountGuardRefused('exact predecessor was not drained')
        access_after = _child_access_probe(target, predecessor_uid)
        if any(access_after.values()) or not _pid1_mountpoint_present(target):
            raise HostMountGuardRefused('host-visible denial did not persist through drain')
        blocked = inspect_blocked_journal(journal_dir)
        if (blocked['phase'] != 'PREPARED_BLOCKED' or
                blocked['record_sha256'] != prepared['record_sha256'] or
                blocked['handoff_admissible'] is not False):
            raise HostMountGuardRefused('journal did not remain blocked')
        _umount(str(target))
        mounted = False
        if _pid1_mountpoint_present(target):
            raise HostMountGuardRefused('disposable mount still present after unmount')
        reconciled = require_reconciliation(journal_dir, reason='KERNEL_DENIAL_LOST')
        if reconciled['phase'] != 'NEEDS_RECONCILIATION' or reconciled['handoff_admissible'] is not False:
            raise HostMountGuardRefused('removing mount did not durably block the journal')
        return {
            'schema': SCHEMA,
            'fixture_type': 'pid1_mount_namespace_disposable_original_and_inert_process',
            'host_mount_namespace_matches_pid1': True,
            'host_visible_denial_mount_observed': True,
            'preopened_writable_fd_observed': True,
            'exact_inert_predecessor_drained': True,
            'fresh_old_uid_access_denied_before_and_after_drain': True,
            'denial_removed_from_pid1_mount_table': True,
            'journal_record_sha256': prepared['record_sha256'],
            'journal_reconciled_after_denial_removed': True,
            'all_real_predecessor_processes_excluded': False,
            'host_wide_real_predecessor_relaunch_excluded': False,
            'reboot_persistent_denial_proved': False,
            'original_binding_retired': False,
            'provider_executed': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
            'live_runtime_modified': False,
        }
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()  # only the process spawned by this fixture
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            if child.stdout:
                child.stdout.close()
            if child.stderr:
                child.stderr.close()
        if mounted:
            try:
                _umount(str(target))
                mounted = False
            except (OSError, RuntimeError):
                # If the kernel mount remains, do not remove the underlying
                # target or fabricate a success response.
                pass
        if not mounted:
            shutil.rmtree(root)
        if installed_dir is not None:
            shutil.rmtree(installed_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        result = simulate(args.predecessor_uid)
    except (HostMountGuardRefused, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
