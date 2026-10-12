"""Root-owned durable *blocked* predecessor-exclusion journal (Release 02F).

A journal is evidence of PREPARATION, not a kernel access-control policy.
It cannot grant execution, declare host-wide relaunch exclusion, or retire an
original workspace. The only state transition here is to NEEDS_RECONCILIATION.
Later code must separately establish an enforcing, reboot-safe kernel barrier.

No method in this module launches, signals, freezes, mounts, or changes any
controller/transaction authority. Unprivileged callers cannot create journals.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

SCHEMA = 'stygnox_release02f_durable_blocked_exclusion_v1'
_NAME = 'blocked-exclusion.json'
_TEMP = '.blocked-exclusion.incomplete'
_RECONCILE = 'reconciliation-required.json'
_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_REASONS = frozenset({
    'SUPERVISOR_INTERRUPTED', 'KERNEL_DENIAL_LOST',
    'PREDECESSOR_IDENTITY_CHANGED', 'REBOOT_DETECTED',
    'PARTIAL_RETIREMENT',
})
_UNSAFE_FLAGS = {
    'host_wide_relaunch_excluded': False,
    'preopened_fds_excluded': False,
    'original_binding_retired': False,
    'authority_changed': False,
    'successor_execution_authorised': False,
    'handoff_admissible': False,
}


class DurableExclusionRefused(RuntimeError):
    """The journal cannot be safely created, trusted, or progressed."""


def _canonical(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True) + '\n').encode('utf-8')


def _digest(data: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def _boot_id() -> str:
    try:
        boot = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    except OSError as exc:
        raise DurableExclusionRefused(f'cannot establish Linux boot identity: {exc}') from exc
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot):
        raise DurableExclusionRefused('Linux boot identifier invalid')
    return boot


def _validate_root_directory(directory: Path) -> int:
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self').exists():
        raise DurableExclusionRefused('Linux root supervisor required')
    if (not directory.is_absolute() or '..' in directory.parts
            or directory == Path('/')):
        raise DurableExclusionRefused('absolute trusted journal directory required')
    for path in (*reversed(directory.parents), directory):
        try:
            info = path.lstat()
        except OSError as exc:
            raise DurableExclusionRefused(f'missing trusted ancestor {path}: {exc}') from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise DurableExclusionRefused(f'untrusted directory ancestry: {path}')
    info = directory.lstat()
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise DurableExclusionRefused('journal directory must be private to root')
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY |
                     os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise DurableExclusionRefused(f'cannot pin journal directory: {exc}') from exc
    pinned = os.fstat(fd)
    if (pinned.st_dev, pinned.st_ino) != (info.st_dev, info.st_ino):
        os.close(fd)
        raise DurableExclusionRefused('journal directory changed identity')
    return fd


def _check_path(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise DurableExclusionRefused(f'{name} must be a path')
    path = Path(value)
    if (not path.is_absolute() or '..' in path.parts or
            path == Path('/') or str(path) != value):
        raise DurableExclusionRefused(f'{name} must be an absolute normalized path')
    return value


def _record_file(dir_fd: int, name: str) -> dict[str, Any] | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DurableExclusionRefused(f'unreadable journal member {name}: {exc}') from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            raise DurableExclusionRefused(f'untrusted journal member {name}')
        raw = os.read(fd, 128 * 1024 + 1)
        if not raw or len(raw) > 128 * 1024:
            raise DurableExclusionRefused(f'invalid journal size {name}')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise DurableExclusionRefused(f'invalid journal JSON {name}') from exc
        if not isinstance(result, dict) or _canonical(result) != raw:
            raise DurableExclusionRefused(f'noncanonical journal {name}')
        return result
    finally:
        os.close(fd)


def _present(dir_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _publish_once(dir_fd: int, name: str, data: dict[str, Any], *, temp: str) -> None:
    # Fixed temporary name is intentional: an interrupted publish is a durable
    # fail-closed signal that cannot be silently discarded on restart.
    if _present(dir_fd, temp) or _present(dir_fd, name):
        raise DurableExclusionRefused('journal already exists or interrupted publication needs reconciliation')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                 os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
    try:
        raw = _canonical(data)
        while raw:
            n = os.write(fd, raw)
            if n <= 0:
                raise DurableExclusionRefused('incomplete journal write')
            raw = raw[n:]
        os.fsync(fd)
    finally:
        os.close(fd)
    # Only root may write inside this directory. No untrusted actor can race
    # the tested absence; any supervisor crash will leave the temp or final.
    os.rename(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    os.fsync(dir_fd)


def _sealed(data: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    result['record_sha256'] = _digest(data)
    return result


def _unseal(record: dict[str, Any]) -> dict[str, Any]:
    actual = dict(record)
    digest = actual.pop('record_sha256', None)
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest) or digest != _digest(actual):
        raise DurableExclusionRefused('journal content fingerprint mismatch')
    return actual


def _validate_prepared(record: dict[str, Any]) -> None:
    data = _unseal(record)
    if (data.get('schema') != SCHEMA or data.get('phase') != 'PREPARED_BLOCKED'
            or data.get('execution_authority') != 'NONE'
            or any(data.get(k) is not v for k, v in _UNSAFE_FLAGS.items())):
        raise DurableExclusionRefused('journal falsely asserts authority or an unsupported state')
    if set(data) != {
        'schema', 'phase', 'execution_authority', 'boot_id',
        'original_path', 'installed_predecessor_path', 'predecessor_uid',
        'original_device', 'original_inode', 'installed_sha256',
        'plan_sha256', 'transaction_sha256', *_UNSAFE_FLAGS,
    }:
        raise DurableExclusionRefused('journal contains unknown or missing fields')
    _check_path(data['original_path'], 'original_path')
    _check_path(data['installed_predecessor_path'], 'installed_predecessor_path')
    if any(not isinstance(data[k], int) or isinstance(data[k], bool) or data[k] <= 0
           for k in ('predecessor_uid', 'original_device', 'original_inode')):
        raise DurableExclusionRefused('invalid predecessor identity')
    for k in ('installed_sha256', 'plan_sha256', 'transaction_sha256'):
        if not isinstance(data[k], str) or not _HEX64.fullmatch(data[k]):
            raise DurableExclusionRefused(f'invalid {k}')


def prepare_blocked_journal(directory: Path, *, original_path: str,
                            installed_predecessor_path: str, predecessor_uid: int,
                            original_device: int, original_inode: int,
                            installed_sha256: str, plan_sha256: str,
                            transaction_sha256: str) -> dict[str, Any]:
    """Durably record untrusted original identifiers without enabling handoff."""
    data = {
        'schema': SCHEMA, 'phase': 'PREPARED_BLOCKED',
        'execution_authority': 'NONE', 'boot_id': _boot_id(),
        'original_path': original_path,
        'installed_predecessor_path': installed_predecessor_path,
        'predecessor_uid': predecessor_uid,
        'original_device': original_device,
        'original_inode': original_inode,
        'installed_sha256': installed_sha256,
        'plan_sha256': plan_sha256,
        'transaction_sha256': transaction_sha256,
        **_UNSAFE_FLAGS,
    }
    sealed = _sealed(data)
    _validate_prepared(sealed)
    fd = _validate_root_directory(Path(directory))
    try:
        _publish_once(fd, _NAME, sealed, temp=_TEMP)
    except OSError as exc:
        raise DurableExclusionRefused(f'uncertain journal publication; reconcile: {exc}') from exc
    finally:
        os.close(fd)
    return sealed


def inspect_blocked_journal(directory: Path) -> dict[str, Any]:
    """Inspect durable state; NEVER return an authority-admission decision."""
    fd = _validate_root_directory(Path(directory))
    try:
        if _present(fd, _TEMP) or _present(fd, '.' + _RECONCILE + '.incomplete'):
            raise DurableExclusionRefused('interrupted journal publication; manual reconciliation required')
        record = _record_file(fd, _NAME)
        if record is None:
            raise DurableExclusionRefused('prepared journal missing')
        _validate_prepared(record)
        reconciliation = _record_file(fd, _RECONCILE)
        if reconciliation is not None:
            data = _unseal(reconciliation)
            if (set(data) != {'schema', 'phase', 'prepared_record_sha256', 'reason', 'boot_id', 'execution_authority'}
                    or data['schema'] != SCHEMA or data['phase'] != 'NEEDS_RECONCILIATION'
                    or data['prepared_record_sha256'] != record['record_sha256']
                    or data['reason'] not in _REASONS or data['execution_authority'] != 'NONE'):
                raise DurableExclusionRefused('invalid reconciliation record')
        current_boot = _boot_id()
        return {
            'schema': SCHEMA,
            'record_sha256': record['record_sha256'],
            'phase': 'NEEDS_RECONCILIATION' if reconciliation or record['boot_id'] != current_boot else 'PREPARED_BLOCKED',
            'boot_id_matches': record['boot_id'] == current_boot,
            'reconciliation_record_present': reconciliation is not None,
            'predecessor_relaunch_excluded': False,
            'all_predecessor_processes_excluded': False,
            'host_wide_kernel_denial_proved': False,
            'reboot_persistent_denial_proved': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
        }
    finally:
        os.close(fd)


def require_reconciliation(directory: Path, *, reason: str) -> dict[str, Any]:
    """One-way durable mark. No API here clears it or grants authority."""
    if reason not in _REASONS:
        raise DurableExclusionRefused('unknown reconciliation reason')
    fd = _validate_root_directory(Path(directory))
    try:
        if _present(fd, _TEMP):
            raise DurableExclusionRefused('incomplete prepared journal; manual reconciliation required')
        record = _record_file(fd, _NAME)
        if record is None:
            raise DurableExclusionRefused('prepared journal missing')
        _validate_prepared(record)
        data = _sealed({
            'schema': SCHEMA, 'phase': 'NEEDS_RECONCILIATION',
            'prepared_record_sha256': record['record_sha256'],
            'reason': reason, 'boot_id': _boot_id(),
            'execution_authority': 'NONE',
        })
        try:
            _publish_once(fd, _RECONCILE, data,
                          temp='.' + _RECONCILE + '.incomplete')
        except OSError as exc:
            raise DurableExclusionRefused(f'uncertain reconciliation publication: {exc}') from exc
    finally:
        os.close(fd)
    return inspect_blocked_journal(directory)
