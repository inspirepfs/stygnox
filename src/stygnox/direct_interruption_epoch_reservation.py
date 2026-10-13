"""R3D.2 exact successor-epoch reservation; no live authority transfer.

Root-private immutable reservation ties a non-executing successor identity to the
already-published isolated workspace and approved transaction. The only normal
mutation is one new dedicated reservation slot. This module deliberately has
no legacy retirement, controller admission, credential read, or provider launch.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from . import direct_interruption_custody_intake as intake
from . import direct_interruption_host_readiness as readiness
from . import direct_interruption_isolated_workspace as isolation
from . import direct_interruption_cutover_gate as gate

SLOT = 'recovery-r3d2-successor-epoch-reserved-v1'
SCHEMA = 'stygnox_r3d2_successor_epoch_reserved_v1'
_HEX = re.compile(r'^[0-9a-f]{64}$')
_EPOCH = re.compile(r'^[0-9a-f]{32}$')
_MAX = 8192
_RECORD_FIELDS = frozenset({
    'schema', 'phase', 'transaction_id', 'approved_plan_hash', 'step',
    'recorded_continuations', 'historical_step_results', 'original_workspace',
    'original_workspace_dev', 'original_workspace_ino',
    'root_custody_record_sha256', 'isolated_workspace_manifest_sha256',
    'installed_source_archive_sha256', 'installed_source_file_count',
    'successor_uid', 'host_boot_id', 'runtime_epoch',
    'original_workspace_retired', 'predecessor_execution_excluded',
    'preopened_fds_revoked', 'controller_admitted', 'execution_authority',
    'successor_execution_authorised', 'provider_credentials_read',
    'provider_executed', 'operator_release_approved', 'record_sha256',
})


class EpochReservationRefused(RuntimeError):
    """Host, record, identity, or atomic publication does not meet contract."""


def _refuse(reason: str) -> None:
    raise EpochReservationRefused(reason)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False) + '\n').encode('utf-8')


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(value)
    record['record_sha256'] = hashlib.sha256(intake._canonical(record)).hexdigest()
    return record


def _exact_record(record: Mapping[str, Any]) -> bool:
    return isinstance(record, dict) and intake._record_hash(record)


def build_reservation(*, original_workspace_identity: tuple[int, int],
                      isolated_manifest_sha256: str, custody_sha256: str,
                      source_archive_sha256: str, installed_source_files: int,
                      successor_uid: int, boot_id: str, epoch_nonce: str) -> dict[str, Any]:
    """Construct only a *denied* reservation from measured protected inputs."""
    if (not isinstance(original_workspace_identity, tuple) or
            len(original_workspace_identity) != 2 or
            any(type(x) is not int or x <= 0 for x in original_workspace_identity)):
        _refuse('original workspace device/inode must be pinned')
    if (type(successor_uid) is not int or successor_uid in (0, 1000) or
            not 1 <= successor_uid <= 65533):
        _refuse('successor must be a distinct, non-root dedicated identity')
    if (type(installed_source_files) is not int or not 1 <= installed_source_files <= 10000):
        _refuse('installed inventory missing')
    if any(not isinstance(x, str) or not _HEX.fullmatch(x) for x in
           (isolated_manifest_sha256, custody_sha256, source_archive_sha256)):
        _refuse('invalid protected digest')
    if not isinstance(boot_id, str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot_id):
        _refuse('host boot identity missing')
    if not isinstance(epoch_nonce, str) or not _EPOCH.fullmatch(epoch_nonce):
        _refuse('epoch entropy unavailable')
    return _seal({
        'schema': SCHEMA,
        'phase': 'SUCCESSOR_EPOCH_RESERVED_EXECUTION_DENIED',
        'transaction_id': intake.TX,
        'approved_plan_hash': intake.PLAN,
        'step': 2,
        'recorded_continuations': 8,
        'historical_step_results': 1,
        'original_workspace': str(isolation.ORIGINAL),
        'original_workspace_dev': original_workspace_identity[0],
        'original_workspace_ino': original_workspace_identity[1],
        'root_custody_record_sha256': custody_sha256,
        'isolated_workspace_manifest_sha256': isolated_manifest_sha256,
        'installed_source_archive_sha256': source_archive_sha256,
        'installed_source_file_count': installed_source_files,
        'successor_uid': successor_uid,
        'host_boot_id': boot_id,
        'runtime_epoch': epoch_nonce,
        'original_workspace_retired': False,
        'predecessor_execution_excluded': False,
        'preopened_fds_revoked': False,
        'controller_admitted': False,
        'execution_authority': 'NONE',
        'successor_execution_authorised': False,
        'provider_credentials_read': False,
        'provider_executed': False,
        'operator_release_approved': False,
    })


def validate_reservation(record: Any, *, expected: Mapping[str, Any] | None = None) -> None:
    """Reject altered or authority-claiming records before any consumer may use them."""
    if (not isinstance(record, dict) or set(record) != _RECORD_FIELDS or
            not _exact_record(record) or record.get('schema') != SCHEMA):
        _refuse('unsealed successor epoch reservation')
    if (record.get('phase') != 'SUCCESSOR_EPOCH_RESERVED_EXECUTION_DENIED' or
            record.get('transaction_id') != intake.TX or
            record.get('approved_plan_hash') != intake.PLAN or
            record.get('step') != 2 or record.get('recorded_continuations') != 8 or
            record.get('historical_step_results') != 1 or
            record.get('original_workspace') != str(isolation.ORIGINAL) or
            record.get('execution_authority') != 'NONE' or
            any(record.get(key) is not False for key in (
                'original_workspace_retired', 'predecessor_execution_excluded',
                'preopened_fds_revoked', 'controller_admitted',
                'successor_execution_authorised', 'provider_credentials_read',
                'provider_executed', 'operator_release_approved'))):
        _refuse('reservation claims unproven authority or wrong transaction')
    if (any(type(record.get(key)) is not int or record[key] <= 0 for key in
            ('original_workspace_dev', 'original_workspace_ino',
             'installed_source_file_count')) or
            any(not isinstance(record.get(key), str) or not _HEX.fullmatch(record[key])
                for key in ('root_custody_record_sha256',
                            'isolated_workspace_manifest_sha256',
                            'installed_source_archive_sha256'))):
        _refuse('incomplete exact protected inputs')
    if not isinstance(record.get('host_boot_id'), str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', record['host_boot_id']):
        _refuse('untrusted boot identity')
    if not isinstance(record.get('runtime_epoch'), str) or not _EPOCH.fullmatch(record['runtime_epoch']):
        _refuse('malformed epoch')
    if (type(record.get('successor_uid')) is not int or not 1 <= record['successor_uid'] <= 65533
            or record['successor_uid'] in (0, 1000)):
        _refuse('untrusted successor identity')
    if expected is not None:
        for key, value in expected.items():
            if record.get(key) != value:
                _refuse('pinned source or custody identity changed')


def _new_file(directory_fd: int, filename: str, raw: bytes) -> None:
    fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_CLOEXEC | os.O_NOFOLLOW, 0o400, dir_fd=directory_fd)
    try:
        with os.fdopen(os.dup(fd), 'wb') as stream:
            stream.write(raw)
            stream.flush()
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_reservation(root: Path, record: Mapping[str, Any], *, owner: int) -> dict[str, Any]:
    """One-shot private slot with durable pending marker; never auto-recover."""
    validate_reservation(record)
    if len(_canonical(record)) > _MAX:
        _refuse('oversized reservation')
    if not root.is_absolute() or '..' in root.parts:
        _refuse('uncanonical reservation root')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(root_fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != owner or stat.S_IMODE(st.st_mode) != 0o700:
            _refuse('reservation parent is not private')
        # The absence check and pending-directory claim are one critical section.
        # Without this flock, a late publisher can pass both absence checks,
        # then create .pending after the winner renames it into SLOT. That
        # strands a marker beside a valid winning record (or can replace it).
        # Locking the trusted parent inode also serializes distinct processes;
        # the kernel drops the lock if the publisher crashes, while the
        # durable .pending marker continues to block an interrupted write.
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise EpochReservationRefused('concurrent reservation publisher') from exc
        if os.path.lexists(root / SLOT) or os.path.lexists(root / (SLOT + '.pending')):
            _refuse('duplicate claim or interrupted publication; manual review required')
        os.mkdir(SLOT + '.pending', mode=0o700, dir_fd=root_fd)
        try:
            pending_fd = os.open(SLOT + '.pending', os.O_RDONLY | os.O_DIRECTORY |
                                 os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
            try:
                _new_file(pending_fd, 'epoch-reservation.json', _canonical(record))
                os.fsync(pending_fd)
            finally:
                os.close(pending_fd)
            os.rename(SLOT + '.pending', SLOT, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
        except Exception:
            # Persist .pending: do not hide an interrupted authority operation.
            raise
    except OSError as exc:
        raise EpochReservationRefused('reservation refused/interrupted; manual reconciliation') from exc
    finally:
        os.close(root_fd)
    return {'phase': record['phase'], 'runtime_epoch': record['runtime_epoch'],
            'record_sha256': record['record_sha256'], 'provider_executed': False,
            'successor_execution_authorised': False, 'legacy_controller_excluded': False}


def read_reservation(root: Path, *, owner: int, expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one immutable reservation, denying any interrupted or extra member."""
    if os.path.lexists(root / (SLOT + '.pending')):
        _refuse('interrupted reservation requires manual review')
    st_root = root.lstat()
    if (not stat.S_ISDIR(st_root.st_mode) or st_root.st_uid != owner or
            stat.S_IMODE(st_root.st_mode) != 0o700):
        _refuse('reservation root is no longer trusted')
    slot = root / SLOT
    stat_slot = slot.lstat()
    if not stat.S_ISDIR(stat_slot.st_mode) or stat_slot.st_uid != owner or stat.S_IMODE(stat_slot.st_mode) != 0o700:
        _refuse('substituted reservation slot')
    if set(os.listdir(slot)) != {'epoch-reservation.json'}:
        _refuse('unrecognized reservation member')
    fd = os.open(slot / 'epoch-reservation.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o400 or info.st_size > _MAX):
            _refuse('substituted reservation file')
        raw = os.read(fd, _MAX + 1)
        if len(raw) != info.st_size:
            _refuse('truncated reservation file')
    finally:
        os.close(fd)
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise EpochReservationRefused('invalid reservation JSON') from exc
    if _canonical(record) != raw:
        _refuse('noncanonical reservation bytes')
    validate_reservation(record, expected=expected)
    return record


def prepare_live_reservation(*, successor_uid: int, successor_archive: Path,
                             successor_source: Path, expected_source_sha256: str) -> dict[str, Any]:
    """Privileged ONE SHOT denied-only operation; not wired to any live controller.

    Requires separate operator approval and source promotion. No retired-old
    claim is made; providers, credentials and original workspace are untouched.
    """
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/status').is_file():
        _refuse('Linux root required')
    # Guard source identity BEFORE importing/reading any privileged custody.
    # An untrusted checkout cannot be used as a privileged publisher.
    module = Path(__file__).resolve()
    if (successor_source == gate.SOURCE or
            module != successor_source / 'src/stygnox/direct_interruption_epoch_reservation.py'):
        _refuse('reservation must run from the separately protected successor source')
    artifact = gate.installed_artifact_audit(
        archive=successor_archive, source=successor_source,
        expected_sha=expected_source_sha256,
    )
    from . import direct_interruption_blocked_commissioning as commissioning
    commissioning._trusted_root(intake.ROOT)
    custody_report = readiness.verify_published_slot(intake.ROOT, uid=0)
    isolated = isolation.verify_isolated_workspace(intake.ROOT, uid=0)
    original = isolation.ORIGINAL.lstat()
    if not stat.S_ISDIR(original.st_mode) or original.st_uid != 1000:
        _refuse('original workspace changed')
    try:
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError as exc:
        raise EpochReservationRefused('host boot identity unavailable') from exc
    record = build_reservation(
        original_workspace_identity=(original.st_dev, original.st_ino),
        isolated_manifest_sha256=isolated['manifest_record_sha256'],
        custody_sha256=custody_report['root_custody_record_sha256'],
        source_archive_sha256=artifact['source_archive_sha256'],
        installed_source_files=artifact['installed_source_file_count'],
        successor_uid=successor_uid, boot_id=boot_id,
        epoch_nonce=os.urandom(16).hex(),
    )
    return publish_reservation(intake.ROOT, record, owner=0)
