"""R3D.2: sealed evidence -> a non-executable, root-private authority projection.

The original R3D.2 runtime is NEVER touched. This module does not implement
predecessor exclusion, successor rebind, credential transfer or provider release.
Its only host-side mutation is one new root-private *data-only* staging directory.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import direct_interruption_custody_intake as custody

ROOT = custody.ROOT
STAGE = 'recovery-r3d2-blocked-commissioning-426572f'
SCHEMA = 'stygnox_r3d2_blocked_commissioning_v1'
MARKER = 'direct-interruption-quarantined-binding.json'


class BlockedCommissioningRefused(RuntimeError):
    """Invalid preservation inputs, ambiguous authority, or unsafe publication."""


def _refuse(reason: str) -> None:
    raise BlockedCommissioningRefused(reason)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonbytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\n'


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result['record_sha256'] = _sha(custody._canonical(result))
    return result


def build_blocked_projection(*, intake: Mapping[str, Any],
                             evidence: Mapping[str, Any],
                             plan: Mapping[str, Any],
                             controller: Mapping[str, Any],
                             transaction: Mapping[str, Any]) -> dict[str, Any]:
    """Pure, irreversible-in-meaning *disabled* projection; no I/O, no execution.

    An old APPROVED record is deliberately converted to a distinct blocked
    lineage. It is never overwritten in the preserved evidence vault.
    """
    if not all(isinstance(x, dict) for x in (intake, evidence, plan, controller, transaction)):
        _refuse('all authority and evidence inputs must be records')
    if not custody._record_hash(intake):
        _refuse('unsealed or modified intake receipt')
    if (intake.get('schema') != custody.SCHEMA
            or intake.get('phase') != 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED'
            or intake.get('transaction_id') != custody.TX
            or intake.get('approved_plan_hash') != custody.PLAN
            or intake.get('evidence_sha256') != custody.EXPECTED):
        _refuse('intake receipt does not describe exact preserved R3D.2 evidence')
    if any(intake.get(key) is not False for key in (
            'predecessor_execution_excluded', 'original_workspace_retired',
            'legacy_credential_revoked', 'boot_persistence_proven',
            'successor_identity_commissioned', 'exclusive_transaction_custody',
            'successor_execution_authorised', 'provider_executed',
            'live_workspace_modified')) or intake.get('execution_authority') != 'NONE':
        _refuse('intake asserts unsupported authority')
    if {k: v for k, v in intake.items() if k != 'record_sha256'} != dict(evidence):
        _refuse('published intake differs from freshly reconciled evidence')
    if not all(custody._record_hash(x) for x in (plan, controller, transaction)):
        _refuse('predecessor authority canonical hash failure')
    if (plan.get('transaction_id') != custody.TX or plan.get('plan_hash') != custody.PLAN
            or plan.get('current_step') != 2 or plan.get('status') != 'APPROVED'
            or plan.get('execution_authority_granted') is not True
            or not isinstance(plan.get('continuation_history'), list)
            or len(plan['continuation_history']) != 8
            or not isinstance(plan.get('step_results'), list)
            or len(plan['step_results']) != 1
            or transaction.get('transaction_id') != custody.TX
            or transaction.get('state') != 'ACTIVE'
            or controller.get('transaction_id') != custody.TX
            or controller.get('enabled') is not True
            or plan.get('controller_record_sha256') != controller['record_sha256']
            or plan.get('transaction_record_sha256') != transaction['record_sha256']
            or controller.get('installed_command') != transaction.get('installed_command')):
        _refuse('original installed controller/transaction binding mismatch')

    lineage = {
        'schema': SCHEMA,
        'transaction_id': custody.TX,
        'approved_plan_hash': custody.PLAN,
        'current_step': 2,
        'recorded_continuations': 8,
        'historical_plan_record_sha256': plan['record_sha256'],
        'historical_controller_record_sha256': controller['record_sha256'],
        'historical_transaction_record_sha256': transaction['record_sha256'],
        'intake_record_sha256': intake['record_sha256'],
        'candidate_manifest_sha256': custody.EXPECTED['candidate'],
        'predecessor_exclusion_proved': False,
        'original_workspace_retired': False,
        'successor_installed_identity_verified': False,
        'successor_execution_authorised': False,
        'provider_executed': False,
        'authority_transferred': False,
        'operator_release_approved': False,
    }
    marker = _seal(lineage)
    disabled_plan = deepcopy(plan)
    disabled_plan.pop('record_sha256')
    disabled_plan['status'] = 'RECOVERY_QUARANTINED'
    disabled_plan['execution_authority_granted'] = False
    disabled_plan['direct_interruption_blocked_commissioning'] = lineage
    disabled_plan = _seal(disabled_plan)

    disabled_controller = deepcopy(controller)
    disabled_controller.pop('record_sha256')
    disabled_controller['enabled'] = False
    disabled_controller['controller_execution_enabled'] = False
    disabled_controller['provider_execution_ready'] = False
    disabled_controller['direct_interruption_blocked_commissioning'] = lineage
    disabled_controller = _seal(disabled_controller)

    disabled_transaction = deepcopy(transaction)
    disabled_transaction.pop('record_sha256')
    disabled_transaction['state'] = 'RECOVERY_QUARANTINED'
    authority = disabled_transaction.get('authority')
    if not isinstance(authority, dict):
        _refuse('original transaction authority must be an object')
    disabled_transaction['authority'] = {**authority, 'controller_execution': False}
    disabled_transaction['direct_interruption_blocked_commissioning'] = lineage
    disabled_transaction = _seal(disabled_transaction)

    return {
        'plan.json': disabled_plan,
        'controller.json': disabled_controller,
        'transaction.json': disabled_transaction,
        MARKER: marker,
    }


def _trusted_root(path: Path) -> None:
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        _refuse('unsafe root storage path')
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            _refuse('root storage parent not protected')
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        _refuse('root storage must be root-private')


def _new_file(dirfd: int, name: str, data: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o400, dir_fd=dirfd)
    try:
        with os.fdopen(os.dup(fd), 'wb') as handle:
            handle.write(data)
            handle.flush()
        os.fsync(fd)
    finally:
        os.close(fd)


def seal_blocked_commissioning() -> dict[str, Any]:
    """One-shot root-owned publication of blocked *data*, never source code.

    This is intentionally not a general-purpose root operation: host paths and
    evidence identities are pinned. A crash leaves `.pending` for reconciliation.
    """
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/status').is_file():
        _refuse('Linux root supervisor required')
    _trusted_root(ROOT)
    intake_file = ROOT / custody.INTAKE / 'custody-intake.json'
    receipt = custody._json(custody._read_root_file(intake_file))
    evidence = custody.audit_protected_intake()  # fresh verification, all 609 files
    candidate_root = ROOT / custody.CANDIDATE / '.stygnox'
    records = {
        name: custody._json(custody._read_root_file(candidate_root / name))
        for name in ('plan.json', 'controller.json', 'transaction.json')
    }
    projection = build_blocked_projection(
        intake=receipt, evidence=evidence,
        plan=records['plan.json'], controller=records['controller.json'],
        transaction=records['transaction.json'],
    )
    return _publish_blocked_projection(ROOT, projection, receipt['record_sha256'])


def _publish_blocked_projection(root: Path, projection: Mapping[str, Mapping[str, Any]],
                                intake_hash: str) -> dict[str, Any]:
    """One-shot durable publication after the caller has verified protected inputs.

    Private filesystem fixture tests exercise this exact publisher. Only the
    privileged `seal_blocked_commissioning` entry calls it in production.
    """
    expected_names = {'plan.json', 'controller.json', 'transaction.json', MARKER}
    if (set(projection) != expected_names or
            any(not custody._record_hash(row) for row in projection.values()) or
            projection['plan.json'].get('status') != 'RECOVERY_QUARANTINED' or
            projection['plan.json'].get('execution_authority_granted') is not False or
            projection['controller.json'].get('enabled') is not False or
            projection['controller.json'].get('controller_execution_enabled') is not False or
            projection['controller.json'].get('provider_execution_ready') is not False or
            projection['transaction.json'].get('state') != 'RECOVERY_QUARANTINED' or
            projection['transaction.json'].get('authority', {}).get('controller_execution') is not False or
            projection[MARKER].get('successor_execution_authorised') is not False or
            projection[MARKER].get('predecessor_exclusion_proved') is not False):
        _refuse('projection must contain only exact quarantined authority records')
    published = root / STAGE
    pending = root / (STAGE + '.pending')
    rootfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.path.lexists(published) or os.path.lexists(pending):
            _refuse('blocked commissioning already exists or is interrupted')
        os.mkdir(pending.name, 0o700, dir_fd=rootfd)
        stagefd = os.open(pending.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                          dir_fd=rootfd)
        try:
            os.mkdir('.stygnox', 0o700, dir_fd=stagefd)
            statefd = os.open('.stygnox', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=stagefd)
            try:
                for filename, record in sorted(projection.items()):
                    _new_file(statefd, filename, _jsonbytes(record))
                os.fsync(statefd)
            finally:
                os.close(statefd)
            result = {
                'schema': SCHEMA,
                'phase': 'ROOT_PRIVATE_BLOCKED_PROJECTION_ONLY',
                'transaction_id': custody.TX,
                'approved_plan_hash': custody.PLAN,
                'intake_record_sha256': intake_hash,
                'records': {name: value['record_sha256'] for name, value in sorted(projection.items())},
                'reconstructed_source_executed': False,
                'predecessor_excluded': False,
                'custody_transferred': False,
                'successor_execution_authorised': False,
                'provider_executed': False,
            }
            _new_file(stagefd, 'blocked-commissioning.json', _jsonbytes(_seal(result)))
            os.fsync(stagefd)
        finally:
            os.close(stagefd)
        os.rename(pending.name, published.name, src_dir_fd=rootfd, dst_dir_fd=rootfd)
        os.fsync(rootfd)
        return {
            'phase': 'ROOT_PRIVATE_BLOCKED_PROJECTION_ONLY',
            'published_path': str(published),
            'predecessor_excluded': False,
            'successor_execution_authorised': False,
            'provider_executed': False,
        }
    except OSError as exc:
        raise BlockedCommissioningRefused('blocked projection interrupted; manual reconciliation required') from exc
    finally:
        os.close(rootfd)
