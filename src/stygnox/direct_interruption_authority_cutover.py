"""R3D.2 transactional root-authority cutover protocol, ALWAYS execution denied.

This module is deliberately *not* a provider release. It makes the new root
broker's recognition of the recovered transaction durable and one-winner; it
cannot revoke arbitrary user processes or preopened descriptors on the old
inode. Callers must not treat a fenced historic namespace as physically sealed.

Production operations require a separately approved, protected root deployment.
No CLI in this source overlay performs production mutations.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from . import direct_interruption_epoch_reservation as epoch
from . import direct_interruption_custody_intake as intake
from . import direct_interruption_isolated_workspace as isolated

SLOT = 'recovery-r3d2-exclusive-authority-v1'
SCHEMA = 'stygnox_r3d2_exclusive_authority_denied_v1'
PHASES = ('PREPARED_EXECUTION_DENIED',
          'LEGACY_UNTRUSTED_EXECUTION_DENIED',
          'SUCCESSOR_ATTESTED_EXECUTION_DENIED')
MEMBERS = ('00-prepared.json', '01-legacy-untrusted.json', '02-successor-attested.json')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX32 = re.compile(r'^[0-9a-f]{32}$')
BOOT = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
MAX_RECORD = 16384


class AuthorityCutoverRefused(RuntimeError):
    """A state, peer, proof, or filesystem boundary was not established."""


def _deny(reason: str) -> None:
    raise AuthorityCutoverRefused(reason)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False) + '\n').encode('utf-8')


def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(payload)
    item['record_sha256'] = hashlib.sha256(intake._canonical(item)).hexdigest()
    return item


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def build_prepared(*, reservation: Mapping[str, Any], custody_sha256: str,
                   isolated_manifest_sha256: str, installed_source_sha256: str,
                   project_identity: tuple[int, int], boot_id: str) -> dict[str, Any]:
    """Pin the complete existing transaction to the *new* authority namespace."""
    epoch.validate_reservation(reservation)
    if (not all(_valid_hash(x) for x in
            (custody_sha256, isolated_manifest_sha256, installed_source_sha256))
            or reservation['root_custody_record_sha256'] != custody_sha256
            or reservation['isolated_workspace_manifest_sha256'] != isolated_manifest_sha256
            or reservation['installed_source_archive_sha256'] != installed_source_sha256):
        _deny('installed source, isolated worktree or root custody differs from reservation')
    if (not isinstance(project_identity, tuple) or len(project_identity) != 2 or
            any(type(x) is not int or x <= 0 for x in project_identity) or
            project_identity != (reservation['original_workspace_dev'],
                                 reservation['original_workspace_ino'])):
        _deny('original project identity differs from approved recovery')
    if (not isinstance(boot_id, str) or not BOOT.fullmatch(boot_id) or
            reservation['host_boot_id'] != boot_id):
        _deny('host boot changed since reservation')
    return _seal({
        'schema': SCHEMA, 'phase': PHASES[0], 'sequence': 0,
        'transaction_id': intake.TX, 'approved_plan_hash': intake.PLAN,
        'original_project_path': str(isolated.ORIGINAL),
        'original_project_dev': project_identity[0], 'original_project_ino': project_identity[1],
        'current_step': 2, 'recorded_continuations': 8, 'completed_step_results': 1,
        'reserved_epoch': reservation['runtime_epoch'],
        'successor_uid': reservation['successor_uid'], 'host_boot_id': boot_id,
        'reservation_record_sha256': reservation['record_sha256'],
        'root_custody_record_sha256': custody_sha256,
        'isolated_workspace_manifest_sha256': isolated_manifest_sha256,
        'installed_source_archive_sha256': installed_source_sha256,
        'previous_record_sha256': None,
        'original_workspace_physically_retired': False,
        'preopened_fds_revoked': False,
        'legacy_process_launch_forbidden': False,
        'historic_state_trusted_by_new_broker': False,
        'successor_controller_execution_allowed': False,
        'operator_release_approved': False, 'provider_executed': False,
        'execution_authority': 'NONE',
        'attested_pid': None, 'attested_process_start': None,
    })


def build_transition(previous: Mapping[str, Any], *, phase: str,
                     pid: int | None = None, process_start: int | None = None) -> dict[str, Any]:
    validate_record(previous)
    current = PHASES.index(previous['phase'])
    if current >= 2 or phase != PHASES[current + 1]:
        _deny('out-of-order or duplicate authority transition')
    if phase == PHASES[2]:
        if (type(pid) is not int or pid <= 1 or
                type(process_start) is not int or process_start <= 0):
            _deny('missing exact successor PID/start identity')
    elif pid is not None or process_start is not None:
        _deny('premature process admission')
    next_record = {k: v for k, v in previous.items() if k != 'record_sha256'}
    next_record.update(phase=phase, sequence=current + 1,
                       previous_record_sha256=previous['record_sha256'],
                       attested_pid=pid if phase == PHASES[2] else None,
                       attested_process_start=process_start if phase == PHASES[2] else None)
    return _seal(next_record)


def validate_record(record: Any, *, previous: Mapping[str, Any] | None = None) -> None:
    if not isinstance(record, dict) or not intake._record_hash(record):
        _deny('unsealed or modified root authority record')
    if (record.get('schema') != SCHEMA or record.get('phase') not in PHASES or
            type(record.get('sequence')) is not int or
            record['sequence'] != PHASES.index(record['phase'])):
        _deny('invalid authority protocol phase')
    if (record.get('transaction_id') != intake.TX or
            record.get('approved_plan_hash') != intake.PLAN or
            record.get('original_project_path') != str(isolated.ORIGINAL) or
            record.get('current_step') != 2 or
            record.get('recorded_continuations') != 8 or
            record.get('completed_step_results') != 1):
        _deny('lost exact transaction or accepted progress')
    if (any(type(record.get(k)) is not int or record[k] <= 0 for k in
            ('original_project_dev', 'original_project_ino', 'successor_uid')) or
            record['successor_uid'] in (0, 1000) or
            not isinstance(record.get('reserved_epoch'), str) or
            not HEX32.fullmatch(record['reserved_epoch']) or
            not isinstance(record.get('host_boot_id'), str) or
            not BOOT.fullmatch(record['host_boot_id']) or
            any(not _valid_hash(record.get(k)) for k in (
                'reservation_record_sha256', 'root_custody_record_sha256',
                'isolated_workspace_manifest_sha256', 'installed_source_archive_sha256'))):
        _deny('invalid immutable project/source/epoch bindings')
    if (any(record.get(k) is not False for k in (
            'original_workspace_physically_retired', 'preopened_fds_revoked',
            'legacy_process_launch_forbidden', 'historic_state_trusted_by_new_broker',
            'successor_controller_execution_allowed', 'operator_release_approved',
            'provider_executed')) or record.get('execution_authority') != 'NONE'):
        _deny('authority record claims impossible rights')
    expected_keys = set(build_prepared_keys())
    if set(record) != expected_keys:
        _deny('missing or unknown authority fields')
    if record['sequence'] < 2:
        if record['attested_pid'] is not None or record['attested_process_start'] is not None:
            _deny('premature attested process')
    elif (type(record['attested_pid']) is not int or record['attested_pid'] <= 1 or
          type(record['attested_process_start']) is not int or record['attested_process_start'] <= 0):
        _deny('incomplete successor process identity')
    if previous is None:
        if record['sequence'] == 0:
            if record['previous_record_sha256'] is not None:
                _deny('initial record cannot claim a predecessor')
        elif not _valid_hash(record['previous_record_sha256']):
            _deny('missing predecessor hash (full chain required for admission)')
    else:
        if (record['sequence'] != previous['sequence'] + 1 or
                record['previous_record_sha256'] != previous['record_sha256']):
            _deny('broken authority hash chain')
        for k in expected_keys - {
            'record_sha256', 'previous_record_sha256', 'sequence', 'phase',
            'attested_pid', 'attested_process_start'}:
            if record[k] != previous[k]:
                _deny('protected authority binding mutated')


def build_prepared_keys() -> frozenset[str]:
    return frozenset({
        'schema', 'phase', 'sequence', 'transaction_id', 'approved_plan_hash',
        'original_project_path', 'original_project_dev', 'original_project_ino',
        'current_step', 'recorded_continuations', 'completed_step_results',
        'reserved_epoch', 'successor_uid', 'host_boot_id',
        'reservation_record_sha256', 'root_custody_record_sha256',
        'isolated_workspace_manifest_sha256', 'installed_source_archive_sha256',
        'previous_record_sha256', 'original_workspace_physically_retired',
        'preopened_fds_revoked', 'legacy_process_launch_forbidden',
        'historic_state_trusted_by_new_broker',
        'successor_controller_execution_allowed', 'operator_release_approved',
        'provider_executed', 'execution_authority',
        'attested_pid', 'attested_process_start', 'record_sha256'})


def _private_root(root: Path, owner: int) -> int:
    if (not root.is_absolute() or '..' in root.parts or str(root) == '/' or
            str(root) != os.path.normpath(str(root))):
        _deny('invalid trusted root')
    # Verify ancestor trust; deny untrusted home directory and path aliases.
    for path in (*reversed(root.parents), root):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or
                info.st_mode & 0o022):
            _deny('root authority ancestry untrusted')
    if stat.S_IMODE(root.lstat().st_mode) != 0o700:
        _deny('authority storage must be private')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(fd)
    if info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        _deny('authority root changed identity')
    return fd


def _member(fd: int, name: str, owner: int) -> dict[str, Any]:
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=fd)
    try:
        info = os.fstat(handle)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o400 or
                info.st_size <= 0 or info.st_size > MAX_RECORD):
            _deny('untrusted root authority member')
        raw = os.read(handle, MAX_RECORD + 1)
        if len(raw) != info.st_size:
            _deny('changed record length')
    finally:
        os.close(handle)
    try:
        item = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AuthorityCutoverRefused('invalid record JSON') from exc
    if not isinstance(item, dict) or _canonical(item) != raw:
        _deny('noncanonical authority record bytes')
    return item


def _write_once(fd: int, name: str, record: Mapping[str, Any]) -> None:
    """Fixed pending marker blocks restart on any interrupted write."""
    data = _canonical(record)
    if len(data) > MAX_RECORD:
        _deny('authority record exceeds size bound')
    for member in (name, name + '.pending'):
        try:
            os.stat(member, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        else:
            _deny('duplicate or interrupted authority record')
    handle = os.open(name + '.pending', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o400, dir_fd=fd)
    try:
        position = 0
        while position < len(data):
            amount = os.write(handle, data[position:])
            if amount <= 0:
                _deny('short authority write')
            position += amount
        os.fsync(handle)
    finally:
        os.close(handle)
    # POSIX rename would REPLACE a concurrent authority claim. Link creates
    # the destination atomically and fails EEXIST. After the link is durable,
    # remove the pending name. A crash before cleanup remains fail-closed.
    os.link(name + '.pending', name, src_dir_fd=fd, dst_dir_fd=fd,
            follow_symlinks=False)
    os.fsync(fd)
    os.unlink(name + '.pending', dir_fd=fd)
    os.fsync(fd)


def publish_prepared(root: Path, record: Mapping[str, Any], *, owner: int) -> dict[str, Any]:
    validate_record(record)
    fd = _private_root(root, owner)
    try:
        try:
            os.stat(SLOT, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _deny('authority slot already exists')
        try:
            os.mkdir(SLOT, 0o700, dir_fd=fd)
        except FileExistsError as exc:
            raise AuthorityCutoverRefused('concurrent authority publisher') from exc
        os.fsync(fd)
        slotfd = os.open(SLOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                         os.O_CLOEXEC, dir_fd=fd)
        try:
            _write_once(slotfd, MEMBERS[0], record)
        finally:
            os.close(slotfd)
    finally:
        os.close(fd)
    return dict(record)


def read_chain(root: Path, *, owner: int) -> tuple[dict[str, Any], ...]:
    fd = _private_root(root, owner)
    try:
        slotfd = os.open(SLOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                         os.O_CLOEXEC, dir_fd=fd)
        try:
            info = os.fstat(slotfd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
                _deny('untrusted authority slot')
            names = set(os.listdir(slotfd))
            if any(x.endswith('.pending') for x in names):
                _deny('interrupted authority transition')
            if names not in (set(MEMBERS[:1]), set(MEMBERS[:2]), set(MEMBERS[:3])):
                _deny('missing or injected authority records')
            records: list[dict[str, Any]] = []
            for member in MEMBERS[:len(names)]:
                current = _member(slotfd, member, owner)
                validate_record(current, previous=records[-1] if records else None)
                records.append(current)
            return tuple(records)
        finally:
            os.close(slotfd)
    finally:
        os.close(fd)


def advance(root: Path, *, owner: int, next_phase: str,
            pid: int | None = None, process_start: int | None = None) -> dict[str, Any]:
    """Root-controlled transition; no source/content/permission changes."""
    records = read_chain(root, owner=owner)
    record = build_transition(records[-1], phase=next_phase,
                              pid=pid, process_start=process_start)
    fd = _private_root(root, owner)
    try:
        slotfd = os.open(SLOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                         os.O_CLOEXEC, dir_fd=fd)
        try:
            # Re-read and compare under pinned parent before O_EXCL.
            latest = _member(slotfd, MEMBERS[len(records) - 1], owner)
            if latest != records[-1]:
                _deny('authority state changed before publication')
            try:
                _write_once(slotfd, MEMBERS[len(records)], record)
            except OSError as exc:
                raise AuthorityCutoverRefused('concurrent or interrupted authority transition') from exc
        finally:
            os.close(slotfd)
    finally:
        os.close(fd)
    return record


def broker_admission(root: Path, *, owner: int, peer_uid: int, peer_pid: int,
                     peer_start: int, boot_id: str, transaction_id: str,
                     plan_hash: str, source_sha256: str, runtime_epoch: str) -> dict[str, Any]:
    """Kernel-derived peer credentials MUST be supplied by the root broker.

    A plain caller can pass forged integers to this function. This routine is
    not an authentication entrypoint; it may only be invoked inside the broker
    after SO_PEERCRED and /proc start time have been checked by the broker.
    """
    records = read_chain(root, owner=owner)
    if len(records) != 3:
        _deny('successor admission not published')
    rec = records[-1]
    if (peer_uid in (0, 1000) or peer_uid != rec['successor_uid'] or
            peer_pid != rec['attested_pid'] or
            peer_start != rec['attested_process_start'] or
            boot_id != rec['host_boot_id'] or
            transaction_id != rec['transaction_id'] or
            plan_hash != rec['approved_plan_hash'] or
            source_sha256 != rec['installed_source_archive_sha256'] or
            runtime_epoch != rec['reserved_epoch']):
        _deny('wrong successor peer or authority context')
    return {'schema': SCHEMA, 'phase': PHASES[2],
            'transaction_id': rec['transaction_id'], 'runtime_epoch': rec['reserved_epoch'],
            'execution_authority': 'NONE', 'provider_executed': False,
            'successor_execution_authorised': False,
            'historic_state_trusted_by_new_broker': False}
