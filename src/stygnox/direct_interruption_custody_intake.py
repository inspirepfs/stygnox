"""R3D.2 blocked custody intake: protected evidence -> durable deny-only receipt.

This is intentionally NOT a predecessor exclusion, live retirement or successor
release. All inputs are immutable root-owned preservation artifacts, never the
live workspace. No legacy controller or provider code is imported or run.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

TX = 'TX-a6379f065ce68138'
PLAN = 'efe4acfaff25edc8fce015ec5c5f0e250a5f58e1a6a39ed569db71c5304cde03'
BASE = '1072451db2c85b340e4c78a7b895190ef1b3f5cd'
ROOT = Path('/var/lib/stygnox')
ORIGINAL_ARCHIVE = 'recovery-r3d2-baseline-1072451/source.tar'
CONTROL = 'recovery-r3d2-control-snapshot-8030ff3'
DELTA = 'recovery-r3d2-worktree-delta-8030ff3'
CANDIDATE = 'recovery-r3d2-offline-candidate-1072451'
INTAKE = 'recovery-r3d2-custody-8030ff3'
EXPECTED = {
    'archive': '8621e84834751c672a62926e4e085726e2139c3032bc33331189f091b5bb4a33',
    'control': 'a1a88ffa4cd4e82d018a3e54457e360dc79cb1210b9de56aa44fb57170bb2cff',
    'delta': '4d5f3b428f88a076f90ede6333e6af8bcfa754b2b5f0639f58c6ea62b9115547',
    'candidate': 'd305cd8eccb5cdb8b1c29bfdda614d53887a66c17d2a1a0ef2e792b34a1594eb',
}
_EXPECTED_CORE = {
    '.stygnox/plan.json': '483487b0c70e47366e559514e20ca223af3036cd89d7a65145f269f1aa01969f',
    '.stygnox/transaction.json': '47d61cbacfbbf6b70847e8c6d5aad5b1fa5ca12db4323c6fff26988c64129498',
    '.stygnox/execution-policy.json': '281692713f9634361cb6e4c5cfb0bdee0c34d5219f9382b631775180c14dbcad',
}
SCHEMA = 'stygnox_r3d2_blocked_custody_intake_v1'
_HEX = re.compile(r'^[0-9a-f]{64}$')
_MAX = 64 * 1024 * 1024


class CustodyIntakeRefused(RuntimeError):
    """Corrupt, untrusted, changing or authority-claiming evidence."""


def _reject(reason: str) -> None:
    raise CustodyIntakeRefused(reason)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _record_hash(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get('record_sha256'), str):
        return False
    body = dict(value)
    digest = body.pop('record_sha256')
    return bool(_HEX.fullmatch(digest)) and _sha(_canonical(body)) == digest


def _path(name: str, *, prefix: str = '') -> str:
    if (not isinstance(name, str) or not name or name.startswith('/')
            or '\\' in name or any(p in ('', '.', '..') for p in name.split('/'))
            or (prefix and not name.startswith(prefix))):
        _reject('noncanonical or out-of-scope evidence path')
    return name


def _json(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CustodyIntakeRefused('invalid evidence JSON') from exc
    if not isinstance(data, dict):
        _reject('evidence root must be an object')
    return data


def reconcile_evidence(*, manifests: Mapping[str, bytes],
                       read: Callable[[str, str], bytes]) -> dict[str, Any]:
    """Pure reconciliation core; caller supplies *already trusted* byte streams.

    Namespaces: candidate/control/delta. This function does NOT attest Linux
    ownership; privileged `audit_protected_intake` does that separately.
    """
    if set(manifests) != {'archive', 'control', 'delta', 'candidate'}:
        _reject('incomplete evidence set')
    if any(_sha(manifests[name]) != EXPECTED[name] for name in EXPECTED):
        _reject('protected source digest differs from operator-verified checkpoint')
    control, delta, offline = (_json(manifests[key]) for key in ('control', 'delta', 'candidate'))
    if (control.get('schema') != 'stygnox_r3d2_preservation_manifest_v1'
            or control.get('snapshot_kind') != 'CONTROL_STATE_ONLY_NOT_AUTHORITY_TRANSFER'
            or control.get('execution_authorised') is not False):
        _reject('control preservation is not explicitly blocked')
    if (delta.get('schema') != 'stygnox_r3d2_worktree_delta_preservation_v1'
            or delta.get('kind') != 'SOURCE_DELTA_ONLY_NOT_AUTHORITY_TRANSFER'
            or delta.get('base_git_head') != BASE
            or delta.get('transaction_id') != TX or delta.get('approved_plan_hash') != PLAN
            or delta.get('control_manifest_sha256') != EXPECTED['control']
            or delta.get('successor_execution_authorised') is not False):
        _reject('source preservation is not correctly bound')
    if (offline.get('schema') != 'stygnox_r3d2_offline_reconstruction_v1'
            or offline.get('kind') != 'DATA_ONLY_NOT_EXECUTABLE_SUCCESSOR'
            or offline.get('original_git_head') != BASE
            or offline.get('transaction_id') != TX or offline.get('approved_plan_hash') != PLAN
            or offline.get('current_step') != 2 or offline.get('recorded_continuations') != 8
            or offline.get('continuation_acceptance_verified') is not False
            or offline.get('committed_archive_sha256') != EXPECTED['archive']
            or offline.get('control_manifest_sha256') != EXPECTED['control']
            or offline.get('delta_manifest_sha256') != EXPECTED['delta']
            or offline.get('transaction_custody_transferred') is not False
            or offline.get('provider_execution_authorised') is not False):
        _reject('candidate asserts unsupported custody or execution authority')
    cfiles, dfiles, ofiles = control.get('source_files'), delta.get('files'), offline.get('files')
    if (not isinstance(cfiles, dict) or len(cfiles) != 36 or not isinstance(dfiles, dict)
            or set(dfiles) != {'src/stygnox/planning.py', 'src/stygnox/scheduler.py',
                              'src/stygnox/transactions.py', 'stygnox.toml',
                              'tests/test_stygnox_transaction_renewal.py'}
            or not isinstance(ofiles, dict) or len(ofiles) != 609):
        _reject('unexpected preserved inventory')
    for name, expected in _EXPECTED_CORE.items():
        if cfiles.get(name, {}).get('sha256') != expected:
            _reject('core plan, transaction, or execution policy changed')
    for namespace, entries, prefix in (('control', cfiles, ''), ('delta', dfiles, ''), ('candidate', ofiles, '')):
        for name, entry in entries.items():
            _path(name, prefix=prefix)
            if namespace == 'control' and not name.startswith(('.stygnox/', '.ralph/')):
                _reject('control evidence outside state directories')
            if not isinstance(entry, dict) or not isinstance(entry.get('sha256'), str):
                _reject('missing per-file digest')
            data = read(namespace, name)
            if _sha(data) != entry['sha256']:
                _reject('preserved member digest mismatch')
            if namespace != 'candidate' and len(data) != entry.get('size'):
                _reject('preserved member size mismatch')
    for namespace, entries in (('control', cfiles), ('delta', dfiles)):
        for name, entry in entries.items():
            if name not in ofiles or ofiles[name]['sha256'] != entry['sha256']:
                _reject('reconstructed candidate does not match protected input')
    def candidate_json(name: str) -> dict[str, Any]:
        return _json(read('candidate', name))
    plan, tx = candidate_json('.stygnox/plan.json'), candidate_json('.stygnox/transaction.json')
    if (plan.get('transaction_id') != TX or tx.get('transaction_id') != TX
            or plan.get('plan_hash') != PLAN or _sha(_canonical(plan.get('plan'))) != PLAN
            or not _record_hash(plan) or not _record_hash(tx)
            or plan.get('status') != 'APPROVED' or tx.get('state') != 'ACTIVE'
            or plan.get('current_step') != 2
            or plan.get('step_resume') is not None or plan.get('current_step_rebase') is not None):
        _reject('plan or transaction contract no longer matches interruption')
    history, steps = plan.get('continuation_history'), plan.get('step_results')
    if (not isinstance(history, list) or len(history) != 8
            or not isinstance(steps, list) or len(steps) != 1
            or not isinstance(plan.get('plan', {}).get('steps'), list)
            or len(plan['plan']['steps']) != 4):
        _reject('step or continuation count mismatch')
    if (not _record_hash(steps[0]) or steps[0].get('step') != 1
            or steps[0].get('result') != 'PASS'):
        _reject('completed Step 1 receipt invalid')
    qual = candidate_json('.stygnox/qualification.json')
    if (qual.get('step_result_sha256') != steps[0]['record_sha256']
            or qual.get('passed') is not True or qual.get('current_step') != 1):
        _reject('Step 1 qualification not linked to completed result')
    names = sorted(n for n in ofiles if n.startswith('.stygnox/controller-run-') and n.endswith('.json'))
    if len(names) != 16:
        _reject('controller history count changed')
    runs = []
    for name in names:
        run = candidate_json(name)
        if not _record_hash(run) or run.get('transaction_id') != TX:
            _reject('invalid controller history or transaction')
        runs.append(run)
    if sum(steps[0].get('controller_receipt_sha256') == run['record_sha256'] for run in runs) != 1:
        _reject('Step 1 receipt does not uniquely identify controller record')
    for index, entry in enumerate(history):
        if not _record_hash(entry) or entry.get('plan_hash') != PLAN or entry.get('step') != (1 if index == 0 else 2):
            _reject('continuation record or step invalid')
        if index and history[index - 1]['after_baseline_sha256'] != entry['before_baseline_sha256']:
            _reject('continuation baseline chain discontinuity')
        matches = [run for run in runs if run.get('preview_sha256') == entry.get('origin_preview_sha256')
                   and run.get('before_baseline_sha256') == entry.get('before_baseline_sha256')
                   and run.get('after_baseline_sha256') == entry.get('after_baseline_sha256')]
        if len(matches) != 1:
            _reject('continuation is not uniquely bound to controller record')
        run = matches[0]
        binding = run.get('plan_binding')
        if (not isinstance(binding, dict) or binding.get('plan_hash') != PLAN
                or binding.get('current_step') != entry['step']
                or not isinstance(binding.get('acceptance'), list)
                or len(binding['acceptance']) != (6 if index == 0 else 7)
                or run.get('provider_result', {}).get('status') != 'PASS'
                or run.get('repository_authority') != 'write'
                or run.get('next_action') != 'continue-same-step'):
            _reject('controller acceptance context does not match historical outcome')
    if plan.get('step_authority_baseline_sha256') != history[-1]['after_baseline_sha256']:
        _reject('final Step 2 checkpoint differs from continuation lineage')
    return {
        'schema': SCHEMA,
        'phase': 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED',
        'transaction_id': TX,
        'approved_plan_hash': PLAN,
        'original_git_head': BASE,
        'current_step': 2,
        'continuations_reconciled': 8,
        'controller_records_reconciled': 16,
        'candidate_file_count': 609,
        'evidence_sha256': dict(EXPECTED),
        'predecessor_execution_excluded': False,
        'original_workspace_retired': False,
        'legacy_credential_revoked': False,
        'boot_persistence_proven': False,
        'successor_identity_commissioned': False,
        'exclusive_transaction_custody': False,
        'execution_authority': 'NONE',
        'successor_execution_authorised': False,
        'provider_executed': False,
        'live_workspace_modified': False,
    }


def _read_root_file(path: Path) -> bytes:
    """No-follow component walk; never trust user-writable dirs or symlinks."""
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        _reject('unsafe protected input path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:-1]:
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = nxt
            s = os.fstat(fd)
            if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                _reject('untrusted protected directory ancestry')
        item = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            s = os.fstat(item)
            if (not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o222
                    or s.st_nlink != 1 or s.st_size > _MAX):
                _reject('untrusted protected input member')
            with os.fdopen(os.dup(item), 'rb') as stream:
                raw = stream.read(_MAX + 1)
            if len(raw) != s.st_size:
                _reject('protected member changed size during inspection')
            after = os.fstat(item)
            if (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                _reject('protected input mutated during inspection')
            return raw
        finally:
            os.close(item)
    finally:
        os.close(fd)


def audit_protected_intake(root: Path = ROOT) -> dict[str, Any]:
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self').exists():
        _reject('privileged Linux supervisor required')
    if Path(root) != ROOT:
        _reject('custody intake can only target the pinned real recovery vault')
    manifests = {
        'archive': _read_root_file(ROOT / ORIGINAL_ARCHIVE),
        'control': _read_root_file(ROOT / CONTROL / 'preservation-manifest.json'),
        'delta': _read_root_file(ROOT / DELTA / 'delta-manifest.json'),
        'candidate': _read_root_file(ROOT / CANDIDATE / 'offline-reconstruction-manifest.json'),
    }
    # Archive is bounded and immutable; do not parse or extract untrusted tar here.
    def reader(namespace: str, name: str) -> bytes:
        if namespace not in {'control', 'delta', 'candidate'}:
            _reject('unsupported evidence namespace')
        _path(name)
        prefix = {'control': CONTROL, 'delta': DELTA, 'candidate': CANDIDATE}[namespace]
        return _read_root_file(ROOT / prefix / name)
    result = reconcile_evidence(manifests=manifests, read=reader)
    return result


def seal_blocked_intake() -> dict[str, Any]:
    """One-shot root-private deny-only evidence; never a release credential.

    Interrupted publication leaves a .pending directory and must be manually
    reconciled. This intentionally does not permit automatic retry or rollback.
    """
    evidence = audit_protected_intake()
    vault = ROOT / INTAKE
    pending = ROOT / (INTAKE + '.pending')
    if os.path.lexists(vault) or os.path.lexists(pending):
        _reject('intake exists or publication interrupted; manual reconciliation required')
    # Pin trusted parent to avoid writing through a substituted path.
    rootfd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(rootfd)
        if info.st_uid != 0 or info.st_mode & 0o077 or info.st_mode & 0o022:
            _reject('custody vault parent not root-private')
        os.mkdir(pending.name, 0o700, dir_fd=rootfd)
        pendingfd = os.open(pending.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=rootfd)
        try:
            body = dict(evidence)
            body['record_sha256'] = _sha(_canonical(body))
            raw = _canonical(body) + b'\n'
            reportfd = os.open('custody-intake.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400, dir_fd=pendingfd)
            try:
                with os.fdopen(os.dup(reportfd), 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                os.fsync(reportfd)
            finally:
                os.close(reportfd)
            os.fsync(pendingfd)
        finally:
            os.close(pendingfd)
        os.rename(pending.name, vault.name, src_dir_fd=rootfd, dst_dir_fd=rootfd)
        os.fsync(rootfd)
        return {'phase': body['phase'], 'intake_path': str(vault),
                'receipt_sha256': _sha(raw), 'exclusive_transaction_custody': False,
                'successor_execution_authorised': False}
    except OSError as exc:
        raise CustodyIntakeRefused(f'intake publication interrupted; manual reconciliation required: {exc}') from exc
    finally:
        os.close(rootfd)
