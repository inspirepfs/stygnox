"""R3D.2 integrated *blocked* custody cutover: verified evidence -> root-only slot.

One privileged entry integrates preservation audit, custody intake and blocked
commissioning into a single durable publication. It never reads or changes
/home, executes repository code, starts providers or grants execution.

The root-only slot is a NEW authority namespace, not proof that a preexisting
uncooperative predecessor has stopped operating on its original workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import direct_interruption_custody_intake as intake
from . import direct_interruption_blocked_commissioning as commissioning

ROOT = intake.ROOT
SLOT = 'recovery-r3d2-root-custody-blocked-v1'
SCHEMA = 'stygnox_r3d2_root_custody_blocked_v1'
MARKER = commissioning.MARKER
_FILES = {'plan.json', 'controller.json', 'transaction.json', MARKER}


class CutoverRefused(RuntimeError):
    """Cutover was not proved; do not proceed to provider execution."""


def _refuse(reason: str) -> None:
    raise CutoverRefused(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(data: Mapping[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b'\n'


def _seal(data: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(data)
    body['record_sha256'] = _sha(intake._canonical(body))
    return body


def build_blocked_cutover(*, evidence: Mapping[str, Any],
                          original_plan: Mapping[str, Any],
                          original_controller: Mapping[str, Any],
                          original_transaction: Mapping[str, Any]) -> dict[str, Any]:
    """Make a deny-only handoff slot from a fully verified evidence graph."""
    if not all(isinstance(d, dict) for d in
               (evidence, original_plan, original_controller, original_transaction)):
        _refuse('cutover requires verified record objects')
    receipt = _seal(evidence)
    try:
        projected = commissioning.build_blocked_projection(
            intake=receipt, evidence=evidence, plan=original_plan,
            controller=original_controller, transaction=original_transaction)
    except commissioning.BlockedCommissioningRefused as exc:
        raise CutoverRefused(f'blocked projection refused: {exc}') from exc

    if set(projected) != _FILES:
        _refuse('unrecognised blocked projection')
    markers = projected[MARKER]
    if (markers.get('authority_transferred') is not False or
            markers.get('predecessor_exclusion_proved') is not False or
            markers.get('successor_execution_authorised') is not False):
        _refuse('projection claims forbidden authority')
    evidence_identity = {
        'schema': SCHEMA,
        'phase': 'ROOT_CUSTODY_PUBLISHED_EXECUTION_DENIED',
        'transaction_id': intake.TX,
        'approved_plan_hash': intake.PLAN,
        'base_git_head': intake.BASE,
        'current_step': 2,
        'recorded_continuations': 8,
        'historical_step_result_count': 1,
        'evidence_manifest_sha256': dict(intake.EXPECTED),
        'intake_record_sha256': receipt['record_sha256'],
        'source_lineage_sha256': {
            'plan': original_plan['record_sha256'],
            'controller': original_controller['record_sha256'],
            'transaction': original_transaction['record_sha256'],
        },
        'quarantined_records_sha256': {
            key: projected[key]['record_sha256'] for key in sorted(projected)
        },
        'original_workspace_retired': False,
        'legacy_controller_excluded': False,
        'legacy_oauth_revoked': False,
        'preopened_file_descriptors_revoked': False,
        'old_workspace_ignored_as_successor_authority': True,
        'root_only_transaction_store': True,
        'successor_identity_commissioned': False,
        'successor_execution_authorised': False,
        'provider_executed': False,
        'operator_release_approved': False,
    }
    return {'intake': receipt, 'projection': projected, 'cutover': _seal(evidence_identity)}


def _verify_payload(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, dict) or set(payload) != {'intake', 'projection', 'cutover'}:
        _refuse('unexpected cutover package')
    projection = payload['projection']
    receipt = payload['intake']
    record = payload['cutover']
    if (not isinstance(projection, dict) or set(projection) != _FILES or
            not intake._record_hash(receipt) or not intake._record_hash(record)):
        _refuse('untrusted custody package')
    if any(not intake._record_hash(x) for x in projection.values()):
        _refuse('unsealed quarantine record')
    if (record.get('schema') != SCHEMA or
            record.get('phase') != 'ROOT_CUSTODY_PUBLISHED_EXECUTION_DENIED' or
            record.get('transaction_id') != intake.TX or
            record.get('approved_plan_hash') != intake.PLAN or
            record.get('base_git_head') != intake.BASE or
            record.get('evidence_manifest_sha256') != intake.EXPECTED or
            record.get('intake_record_sha256') != receipt['record_sha256'] or
            record.get('quarantined_records_sha256') != {
                k: v['record_sha256'] for k, v in sorted(projection.items())
            } or
            record.get('source_lineage_sha256') != {
                'plan': projection['plan.json']['direct_interruption_blocked_commissioning']['historical_plan_record_sha256'],
                'controller': projection['controller.json']['direct_interruption_blocked_commissioning']['historical_controller_record_sha256'],
                'transaction': projection['transaction.json']['direct_interruption_blocked_commissioning']['historical_transaction_record_sha256'],
            } or
            record.get('current_step') != 2 or
            record.get('recorded_continuations') != 8 or
            record.get('historical_step_result_count') != 1 or
            not all(record.get(field) is False for field in (
                'original_workspace_retired', 'legacy_controller_excluded',
                'legacy_oauth_revoked', 'preopened_file_descriptors_revoked',
                'successor_identity_commissioned', 'successor_execution_authorised',
                'provider_executed', 'operator_release_approved')) or
            not all(record.get(field) is True for field in (
                'old_workspace_ignored_as_successor_authority',
                'root_only_transaction_store')) or
            projection['plan.json'].get('status') != 'RECOVERY_QUARANTINED' or
            projection['plan.json'].get('execution_authority_granted') is not False or
            projection['controller.json'].get('enabled') is not False or
            projection['controller.json'].get('controller_execution_enabled') is not False or
            projection['controller.json'].get('provider_execution_ready') is not False or
            projection['transaction.json'].get('state') != 'RECOVERY_QUARANTINED' or
            projection['transaction.json'].get('authority', {}).get('controller_execution') is not False or
            projection[MARKER].get('successor_execution_authorised') is not False):
        _refuse('blocked cutover contract or lineage invalid')
    histories = projection['plan.json'].get('continuation_history')
    if (not isinstance(histories, list) or len(histories) != 8 or
            len(projection['plan.json'].get('step_results', [])) != 1):
        _refuse('preserved historical work absent')


def _write(fd: int, filename: str, raw: bytes) -> None:
    newfd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                    os.O_NOFOLLOW | os.O_CLOEXEC, 0o400, dir_fd=fd)
    try:
        with os.fdopen(os.dup(newfd), 'wb') as stream:
            stream.write(raw)
            stream.flush()
        os.fsync(newfd)
    finally:
        os.close(newfd)


def _publish(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fixture-tested single atomic root-owned publication. No live mutation."""
    _verify_payload(payload)
    destination = root / SLOT
    pending = root / (SLOT + '.pending')
    rootfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(rootfd)
        if not stat.S_ISDIR(info.st_mode):
            _refuse('custody root changed identity')
        if os.path.lexists(destination) or os.path.lexists(pending):
            _refuse('existing/interrupted custody slot requires manual reconciliation')
        os.mkdir(pending.name, mode=0o700, dir_fd=rootfd)
        fd = os.open(pending.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=rootfd)
        try:
            os.mkdir('.stygnox', 0o700, dir_fd=fd)
            runtimefd = os.open('.stygnox', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=fd)
            try:
                for name, record in sorted(payload['projection'].items()):
                    _write(runtimefd, name, _canonical(record))
                os.fsync(runtimefd)
            finally:
                os.close(runtimefd)
            _write(fd, 'custody-intake.json', _canonical(payload['intake']))
            _write(fd, 'root-custody.json', _canonical(payload['cutover']))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(pending.name, SLOT, src_dir_fd=rootfd, dst_dir_fd=rootfd)
        os.fsync(rootfd)
    except OSError as exc:
        raise CutoverRefused('root custody publication interrupted; manual reconciliation required') from exc
    finally:
        os.close(rootfd)
    return {'schema': SCHEMA, 'phase': 'ROOT_CUSTODY_PUBLISHED_EXECUTION_DENIED',
            'published_path': str(destination),
            'root_only_transaction_store': True,
            'legacy_controller_excluded': False,
            'successor_execution_authorised': False, 'provider_executed': False}


def seal_root_custody() -> dict[str, Any]:
    """Privileged one-step publication using only pinned, root-owned evidence.

    Does not require previously published intake/commissioning, so it is an
    integrated host operation rather than another two-stage operator workflow.
    """
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/status').is_file():
        _refuse('Linux root supervisor required')
    commissioning._trusted_root(ROOT)
    evidence = intake.audit_protected_intake()
    source = ROOT / intake.CANDIDATE / '.stygnox'
    records = {
        name: intake._json(intake._read_root_file(source / name))
        for name in ('plan.json', 'controller.json', 'transaction.json')
    }
    payload = build_blocked_cutover(
        evidence=evidence, original_plan=records['plan.json'],
        original_controller=records['controller.json'],
        original_transaction=records['transaction.json'])
    return _publish(ROOT, payload)


def refuse_execution_from_custody(project: Path) -> None:
    """Non-cooperative downstream commands cannot treat a custody slot as runnable."""
    if project.name != SLOT:
        _refuse('not an R3D.2 custody slot')
    from .direct_interruption_execution_guard import refuse_quarantined_runtime
    # This guard always raises for an intact custody slot. Missing/tampered
    # markers must not be interpreted as permission to execute either.
    try:
        refuse_quarantined_runtime(project)
    except Exception as exc:
        raise CutoverRefused('root custody is execution-blocked') from exc
    _refuse('missing quarantine guard: fail closed')
