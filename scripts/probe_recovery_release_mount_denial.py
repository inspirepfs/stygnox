#!/usr/bin/env python3
"""Release 02D: disposable kernel path-denial and inherited-FD experiment.

This command NEVER accepts a live project path, installed executable, plan, or
transaction as input. It creates inert files under a fresh root-owned /run
fixture, enters a new private Linux mount namespace, and overlays the fixture's
old-UID worktree with a root-only directory. It demonstrates that fresh access
and directory rename are denied, but a previously opened write descriptor is
NOT revoked. No process exclusion, durable reboot fencing or handoff is proved.

Do not repurpose this as a live mount/retirement action. Its temporary mount
exists ONLY in its own, freshly unshared namespace and disappears at exit.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import select
import shutil
import stat
import sys
import tempfile
import time
from typing import Any

MS_BIND = 4096
MS_PRIVATE = 1 << 18
MS_REC = 16384
CLONE_NEWNS = getattr(os, 'CLONE_NEWNS', 0x00020000)


class MountDenialRefused(RuntimeError):
    """Cannot safely establish an isolated Linux path-denial fixture."""


def _mount(source: str | None, target: str, flags: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p,
                            ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]
    libc.mount.restype = ctypes.c_int
    result = libc.mount(source.encode() if source else None, target.encode(),
                        None, flags, None)
    if result:
        code = ctypes.get_errno()
        raise MountDenialRefused(f'Linux mount rejected operation: {os.strerror(code)} ({code})')


def _umount(path: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
    libc.umount2.restype = ctypes.c_int
    if libc.umount2(path.encode(), 0):
        code = ctypes.get_errno()
        raise MountDenialRefused(f'fixture unmount refused: {os.strerror(code)} ({code})')


def _private_namespace() -> None:
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/mountinfo').is_file():
        raise MountDenialRefused('Linux root with procfs is required')
    try:
        os.unshare(CLONE_NEWNS)
    except (OSError, AttributeError) as exc:
        raise MountDenialRefused(f'cannot isolate mount namespace: {exc}') from exc
    # Do not bind ANY path until propagation from the new namespace is disabled.
    _mount(None, '/', MS_REC | MS_PRIVATE)
    if os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt'):
        raise MountDenialRefused('mount namespace is not independent of PID 1')


def _fixture_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix='stygnox-rr02d-', dir='/run'))
    os.chmod(root, 0o755)
    return root


def _spawn_preopened_legacy_fd(path: Path, uid: int) -> tuple[int, tuple[int, int, int]]:
    ready_r, ready_w = os.pipe()
    release_r, release_w = os.pipe()
    result_r, result_w = os.pipe()
    try:
        pid = os.fork()
    except OSError:
        for fd in (ready_r, ready_w, release_r, release_w, result_r, result_w):
            os.close(fd)
        raise
    if pid == 0:
        try:
            for fd in (ready_r, release_w, result_r):
                os.close(fd)
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC)
            os.write(ready_w, b'1')
            os.close(ready_w)
            if os.read(release_r, 1) != b'1':
                os._exit(2)
            os.write(fd, b'legacy-after-denial\n')
            os.fsync(fd)
            os.write(result_w, b'1')
            os.close(fd)
            os._exit(0)
        except BaseException:
            try:
                os.write(ready_w, b'0')
                os.write(result_w, b'0')
            except OSError:
                pass
            os._exit(2)
    for fd in (ready_w, release_r, result_w):
        os.close(fd)
    return pid, (ready_r, release_w, result_r)


def _child_access_probe(target: Path, uid: int) -> dict[str, bool]:
    """Test actual old-UID open/write/rename with no fake permission mocks."""
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(rfd)
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
            outcomes = {}
            for name, attempt in (
                ('can_open_old_plan', lambda: (target / '.stygnox' / 'plan.json').read_text()),
                ('can_create_file', lambda: (target / 'new-file').write_text('x')),
                ('can_rename_mountpoint', lambda: target.rename(target.with_name('original-moved'))),
            ):
                try:
                    attempt()
                except OSError:
                    outcomes[name] = False
                else:
                    outcomes[name] = True
            os.write(wfd, json.dumps(outcomes).encode())
            os._exit(0)
        except BaseException:
            os._exit(2)
    os.close(wfd)
    try:
        if not select.select([rfd], [], [], 5)[0]:
            raise MountDenialRefused('legacy access probe timed out')
        result = os.read(rfd, 4096)
        _, status = os.waitpid(pid, 0)
        if status != 0 or not result:
            raise MountDenialRefused('legacy access probe failed')
        return json.loads(result)
    finally:
        os.close(rfd)


def _private_bind_denial(target: Path, gate: Path) -> None:
    if not target.is_dir() or target.is_symlink():
        raise MountDenialRefused('disposable target must be a real directory')
    info = gate.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or
            stat.S_IMODE(info.st_mode) != 0o700):
        raise MountDenialRefused('denial directory must be root-owned 0700')
    _mount(str(gate), str(target), MS_BIND)
    overlay = target.stat()
    if (overlay.st_dev, overlay.st_ino) != (info.st_dev, info.st_ino):
        raise MountDenialRefused('mount overlay identity mismatch')


def simulate(predecessor_uid: int) -> dict[str, Any]:
    """Safely test kernel semantics on a self-created /run fixture only."""
    if not isinstance(predecessor_uid, int) or predecessor_uid <= 0 or predecessor_uid == 65534:
        raise MountDenialRefused('valid distinct non-root predecessor UID required')
    _private_namespace()
    root = _fixture_root()
    oldpid = None
    pipes: tuple[int, int, int] | None = None
    bound = False
    target = root / 'legacy-parent' / 'original'
    try:
        parent = target.parent
        parent.mkdir(mode=0o755)
        os.chown(parent, predecessor_uid, predecessor_uid)
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
        oldpid, pipes = _spawn_preopened_legacy_fd(plan, predecessor_uid)
        ready_fd, release_fd, result_fd = pipes
        if not select.select([ready_fd], [], [], 5)[0] or os.read(ready_fd, 1) != b'1':
            raise MountDenialRefused('legacy descriptor fixture failed to open')
        _private_bind_denial(target, gate)
        bound = True
        access = _child_access_probe(target, predecessor_uid)
        if any(access.values()):
            raise MountDenialRefused(f'old UID retained fresh path access: {access}')
        os.write(release_fd, b'1')
        if not select.select([result_fd], [], [], 5)[0] or os.read(result_fd, 1) != b'1':
            raise MountDenialRefused('preopened descriptor fixture did not complete')
        _, status = os.waitpid(oldpid, 0)
        oldpid = None
        if status != 0:
            raise MountDenialRefused('preopened legacy process failed')
        _umount(str(target))
        bound = False
        legacy_fd_retained = b'legacy-after-denial' in plan.read_bytes()
        if not legacy_fd_retained:
            raise MountDenialRefused('fixture unexpectedly revoked preopened descriptor')
        return {
            'schema': 'stygnox_recovery_release02d_disposable_mount_denial_v1',
            'fixture_type': 'private_mount_namespace_root_owned_bind_denial',
            'mount_namespace_isolated_from_pid1': True,
            'private_propagation_established': True,
            'legacy_fresh_plan_open_denied': not access['can_open_old_plan'],
            'legacy_fresh_write_denied': not access['can_create_file'],
            'legacy_mountpoint_rename_denied': not access['can_rename_mountpoint'],
            'preopened_legacy_fd_still_writable': legacy_fd_retained,
            'old_open_fds_excluded': False,
            'host_wide_legacy_relaunch_excluded': False,
            'reboot_persistent_denial_proved': False,
            'original_binding_retired': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
            'live_runtime_modified': False,
            'provider_executed': False,
        }
    finally:
        if bound:
            try:
                _umount(str(target))
            except OSError:
                pass
        if pipes is not None:
            for fd in pipes:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if oldpid is not None:
            try:
                os.kill(oldpid, 15)  # only our own disposable child
                os.waitpid(oldpid, 0)
            except OSError:
                pass
        shutil.rmtree(root)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate', action='store_true', required=True)
    p.add_argument('--predecessor-uid', type=int, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(simulate(args.predecessor_uid), indent=2, sort_keys=True))
        return 0
    except (MountDenialRefused, OSError, ValueError) as exc:
        print(f'Recovery Release 02D mount denial REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
