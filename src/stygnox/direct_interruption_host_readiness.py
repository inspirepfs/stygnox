"""R3D.2 read-only, deny-only host cutover readiness evidence.

The published root custody slot cannot, by itself, exclude independent legacy
processes. This module verifies that slot as DATA. No result here is an
execution credential or a certificate of predecessor exclusion.

Crucially, this does not touch the live workspace, provider credentials, or
any host access-control policy. A future cutover requires a separate reviewed
kernel-enforced boundary, immutable successor binding, hostile host tests and
an explicit operator release. Until then, all callers receive DENIED.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import direct_interruption_custody_cutover as custody
from . import direct_interruption_custody_intake as intake
from . import direct_interruption_blocked_commissioning as commissioning

SCHEMA = 'stygnox_r3d2_host_readiness_denied_v1'
EXIT_DENIED = 75
_FILE_LIMIT = 16 * 1024 * 1024
_EXPECTED_ROOT = frozenset({'custody-intake.json', 'root-custody.json', '.stygnox'})
_EXPECTED_RUNTIME = frozenset(custody._FILES)
# These are questions to be proved by a HOST cutover, not claimed by this tool.
_MISSING_PROOFS = (
    'PREDECESSOR_RELAUNCH_DENIAL_NOT_ENFORCED',
    'PREOPENED_FD_AND_PATH_ALIAS_EXCLUSION_NOT_PROVED',
    'ORIGINAL_WORKSPACE_RETIREMENT_NOT_PROVED',
    'LEGACY_PROVIDER_AUTHORITY_NOT_EXCLUDED',
    'INDEPENDENT_SUCCESSOR_IDENTITY_NOT_COMMISSIONED',
    'IMMUTABLE_SUCCESSOR_ARTIFACT_AND_EPOCH_NOT_ADMITTED',
    'REBOOT_AND_CRASH_EXCLUSION_NOT_QUALIFIED',
    'CONTROLLED_OPERATOR_RELEASE_NOT_APPROVED',
)


class ReadinessRefused(RuntimeError):
    """Read-only inspection could not authenticate the blocked custody slot."""


def _canonical(record: Mapping[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False) + '\n').encode('utf-8')


def _directory(path: Path, *, uid: int, mode: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReadinessRefused(f'missing protected directory: {path.name}') from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != mode:
        raise ReadinessRefused(f'untrusted protected directory: {path.name}')


def _members(path: Path, expected: frozenset[str]) -> None:
    try:
        actual = {name for name in os.listdir(path)}
    except OSError as exc:
        raise ReadinessRefused('cannot inspect protected member list') from exc
    if actual != expected:
        raise ReadinessRefused('missing or unexpected custody member; manual reconciliation required')


def _record(parent: Path, name: str, *, uid: int) -> dict[str, Any]:
    """Read one pinned inode, refusing substitution and noncanonical contents."""
    if '/' in name or name.startswith('.') or name in ('', '..'):
        raise ReadinessRefused('unsafe authority record member')
    dirfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        parent_st = os.fstat(dirfd)
        on_disk = os.stat(parent, follow_symlinks=False)
        if (not stat.S_ISDIR(parent_st.st_mode) or parent_st.st_uid != uid or
                (parent_st.st_dev, parent_st.st_ino) != (on_disk.st_dev, on_disk.st_ino)):
            raise ReadinessRefused('authority directory substituted')
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=dirfd)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
                    info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o400 or
                    not 0 < info.st_size <= _FILE_LIMIT):
                raise ReadinessRefused(f'untrusted custody record: {name}')
            raw = os.read(fd, _FILE_LIMIT + 1)
            if len(raw) != info.st_size:
                raise ReadinessRefused(f'changed or oversized custody record: {name}')
        finally:
            os.close(fd)
    except OSError as exc:
        raise ReadinessRefused(f'cannot safely open custody member: {name}') from exc
    finally:
        os.close(dirfd)
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ReadinessRefused(f'corrupted custody JSON: {name}') from exc
    if (not isinstance(record, dict) or not intake._record_hash(record) or
            raw != _canonical(record)):
        raise ReadinessRefused(f'corrupted or noncanonical custody record: {name}')
    return record


def verify_published_slot(root: Path, *, uid: int) -> dict[str, Any]:
    """Verify existing custody as immutable data, without publishing or repairing.

    Caller must separately establish root/private trusted ancestry before
    interpreting this evidence as HOST custody. UID argument only permits the
    very same parsing contract to be tested on private disposable fixtures.
    """
    slot = root / custody.SLOT
    for pending in (custody.SLOT + '.pending',
                    commissioning.STAGE + '.pending'):
        if os.path.lexists(root / pending):
            raise ReadinessRefused('interrupted publication needs manual reconciliation')
    _directory(slot, uid=uid, mode=0o700)
    _directory(slot / '.stygnox', uid=uid, mode=0o700)
    _members(slot, _EXPECTED_ROOT)
    _members(slot / '.stygnox', _EXPECTED_RUNTIME)
    payload = {
        'intake': _record(slot, 'custody-intake.json', uid=uid),
        'cutover': _record(slot, 'root-custody.json', uid=uid),
        'projection': {
            name: _record(slot / '.stygnox', name, uid=uid)
            for name in sorted(_EXPECTED_RUNTIME)
        },
    }
    try:
        custody._verify_payload(payload)
    except (custody.CutoverRefused, KeyError, TypeError, ValueError) as exc:
        raise ReadinessRefused('custody record lineage or deny-state is invalid') from exc
    return {
        'slot': str(slot),
        'transaction_id': payload['cutover']['transaction_id'],
        'approved_plan_hash': payload['cutover']['approved_plan_hash'],
        'root_custody_record_sha256': payload['cutover']['record_sha256'],
        'historical_step_result_count': 1,
        'recorded_continuations': 8,
        'current_step': 2,
        'blocked_root_custody_intact': True,
    }


def audit_live_host() -> dict[str, Any]:
    """Privileged READ-ONLY inventory; ALWAYS denies successor execution."""
    if (os.name != 'posix' or os.geteuid() != 0 or
            not Path('/proc/self/status').is_file()):
        raise ReadinessRefused('Linux root required for trusted custody inspection')
    try:
        commissioning._trusted_root(intake.ROOT)
        slot = verify_published_slot(intake.ROOT, uid=0)
    except (commissioning.BlockedCommissioningRefused, OSError) as exc:
        raise ReadinessRefused('root storage ancestry or privacy invalid') from exc
    # The legacy checkout and its provider authentication are deliberately
    # NOT read or modified. A snapshot of /proc cannot prove future exclusion.
    return {
        'schema': SCHEMA,
        'phase': 'EXCLUSIVE_CUSTODY_NOT_PROVED',
        **slot,
        'legacy_controller_excluded': False,
        'preopened_fds_revoked': False,
        'provider_credentials_read': False,
        'original_workspace_modified': False,
        'root_custody_modified': False,
        'successor_identity_commissioned': False,
        'execution_authority': 'NONE',
        'successor_execution_authorised': False,
        'provider_executed': False,
        'required_proofs': list(_MISSING_PROOFS),
    }


def denied_report() -> dict[str, Any]:
    """For invalid hosts or CLI usage; not a release protocol."""
    return {'schema': SCHEMA, 'phase': 'HOST_READINESS_REFUSED',
            'execution_authority': 'NONE', 'successor_execution_authorised': False,
            'provider_executed': False}
