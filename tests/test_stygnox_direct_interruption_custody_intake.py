"""Behavioural tests for the root-custody evidence contract; no provider use."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from stygnox import direct_interruption_custody_intake as custody


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def seal(value):
    obj = dict(value)
    obj['record_sha256'] = sha(blob(obj))
    return obj


def fixture(monkeypatch):
    """A complete, tiny synthetic 609/36/5 file evidence graph.

    Tests *behavioural* reconciliation, not a mocked controller response.
    Production audit pins the real known four digests and a root-owned vault.
    """
    filemap = {'candidate': {}, 'control': {}, 'delta': {}}
    records = {}
    plan_def = {'steps': [{'id': x} for x in range(4)]}
    expected_plan = sha(blob(plan_def))
    monkeypatch.setattr(custody, 'PLAN', expected_plan)

    history = []
    for i in range(8):
        entry = {
            'plan_hash': expected_plan,
            'step': 1 if i == 0 else 2,
            'origin_preview_sha256': sha(f'preview{i}'.encode()),
            'before_baseline_sha256': sha(f'baseline{i}'.encode()),
            'after_baseline_sha256': sha(f'baseline{i+1}'.encode()),
            'summary': 'accepted continuation',
            'recorded_at': f'2026-10-08T{i:02d}:00:00Z',
        }
        history.append(seal(entry))

    runs = []
    for i in range(16):
        if i < 8:
            entry = history[i]
            preview = entry['origin_preview_sha256']
            before = entry['before_baseline_sha256']
            after = entry['after_baseline_sha256']
            step = entry['step']
        else:
            preview = sha(f'unrelated{i}'.encode())
            before = sha(f'unrelated-before{i}'.encode())
            after = sha(f'unrelated-after{i}'.encode())
            step = 2
        record = seal({
            'transaction_id': custody.TX,
            'preview_sha256': preview,
            'before_baseline_sha256': before,
            'after_baseline_sha256': after,
            'plan_binding': {'plan_hash': expected_plan, 'current_step': step,
                             'acceptance': [{}] * (6 if step == 1 else 7)},
            'provider_result': {'status': 'PASS'},
            'repository_authority': 'write',
            'next_action': 'continue-same-step',
        })
        runs.append(record)
        records[f'.stygnox/controller-run-{i:016x}.json'] = blob(record)

    result = seal({'step': 1, 'result': 'PASS', 'controller_receipt_sha256': runs[0]['record_sha256']})
    records['.stygnox/plan.json'] = blob(seal({
        'plan': plan_def, 'plan_hash': expected_plan,
        'transaction_id': custody.TX, 'status': 'APPROVED', 'current_step': 2,
        'step_resume': None, 'current_step_rebase': None,
        'step_results': [result], 'continuation_history': history,
        'step_authority_baseline_sha256': history[-1]['after_baseline_sha256'],
    }))
    records['.stygnox/transaction.json'] = blob(seal({
        'transaction_id': custody.TX, 'state': 'ACTIVE',
    }))
    records['.stygnox/execution-policy.json'] = blob({'provider': 'codex', 'reviewed': True})
    records['.stygnox/qualification.json'] = blob({
        'step_result_sha256': result['record_sha256'],
        'passed': True, 'current_step': 1,
    })
    for i in range(16):
        records[f'.stygnox/other-{i}.json'] = blob({'counter': i})
    assert len(records) == 36

    for name, content in records.items():
        filemap['candidate'][name] = content
        filemap['control'][name] = content

    for name in ('src/stygnox/planning.py', 'src/stygnox/scheduler.py',
                 'src/stygnox/transactions.py', 'stygnox.toml',
                 'tests/test_stygnox_transaction_renewal.py'):
        content = (f'synthetic {name}\n').encode()
        filemap['candidate'][name] = content
        filemap['delta'][name] = content
    for i in range(609 - len(filemap['candidate'])):
        filemap['candidate'][f'docs/unrelated-{i:04d}.txt'] = b'non-executable test bytes'
    assert len(filemap['candidate']) == 609

    ctrl_manifest = {
        'schema': 'stygnox_r3d2_preservation_manifest_v1',
        'snapshot_kind': 'CONTROL_STATE_ONLY_NOT_AUTHORITY_TRANSFER',
        'execution_authorised': False,
        'source_files': {name: {'sha256': sha(data), 'size': len(data)}
                         for name, data in filemap['control'].items()},
    }
    control_bytes = blob(ctrl_manifest)
    archive_bytes = b'inert archive fixture'
    delta_manifest = {
        'schema': 'stygnox_r3d2_worktree_delta_preservation_v1',
        'kind': 'SOURCE_DELTA_ONLY_NOT_AUTHORITY_TRANSFER',
        'base_git_head': custody.BASE,
        'transaction_id': custody.TX,
        'approved_plan_hash': expected_plan,
        'control_manifest_sha256': sha(control_bytes),
        'successor_execution_authorised': False,
        'files': {name: {'sha256': sha(data), 'size': len(data)}
                  for name, data in filemap['delta'].items()},
    }
    delta_bytes = blob(delta_manifest)
    reconstructed = {
        'schema': 'stygnox_r3d2_offline_reconstruction_v1',
        'kind': 'DATA_ONLY_NOT_EXECUTABLE_SUCCESSOR',
        'original_git_head': custody.BASE,
        'transaction_id': custody.TX,
        'approved_plan_hash': expected_plan,
        'current_step': 2,
        'recorded_continuations': 8,
        'continuation_acceptance_verified': False,
        'committed_archive_sha256': sha(archive_bytes),
        'control_manifest_sha256': sha(control_bytes),
        'delta_manifest_sha256': sha(delta_bytes),
        'transaction_custody_transferred': False,
        'provider_execution_authorised': False,
        'files': {name: {'sha256': sha(data)} for name, data in filemap['candidate'].items()},
    }
    candidate_bytes = blob(reconstructed)
    manifests = {
        'archive': archive_bytes, 'control': control_bytes,
        'delta': delta_bytes, 'candidate': candidate_bytes,
    }
    monkeypatch.setattr(custody, 'EXPECTED', {key: sha(value) for key, value in manifests.items()})
    monkeypatch.setattr(custody, '_EXPECTED_CORE', {
        name: sha(records[name]) for name in (
            '.stygnox/plan.json', '.stygnox/transaction.json', '.stygnox/execution-policy.json')
    })
    return manifests, filemap


def reconcile(manifests, filemap):
    return custody.reconcile_evidence(
        manifests=manifests,
        read=lambda namespace, name: filemap[namespace][name],
    )


def test_intake_reconciles_real_evidence_shapes_without_executing_provider(monkeypatch):
    manifests, files = fixture(monkeypatch)
    report = reconcile(manifests, files)
    assert report['continuations_reconciled'] == 8
    assert report['controller_records_reconciled'] == 16
    assert report['candidate_file_count'] == 609
    assert report['phase'] == 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED'
    assert report['execution_authority'] == 'NONE'
    assert report['successor_execution_authorised'] is False
    assert report['exclusive_transaction_custody'] is False
    assert report['predecessor_execution_excluded'] is False
    assert report['legacy_credential_revoked'] is False
    assert report['provider_executed'] is False


@pytest.mark.parametrize('namespace,filename', [
    ('control', '.stygnox/plan.json'),
    ('delta', 'src/stygnox/transactions.py'),
    ('candidate', '.stygnox/controller-run-0000000000000002.json'),
])
def test_modified_evidence_refused(monkeypatch, namespace, filename):
    manifests, files = fixture(monkeypatch)
    files[namespace][filename] += b'\nUNEXPECTED'
    with pytest.raises(custody.CustodyIntakeRefused):
        reconcile(manifests, files)


def test_missing_controller_binding_refused_even_with_resealed_hash(monkeypatch):
    manifests, files = fixture(monkeypatch)
    # Repair every manifest hash to preserve byte consistency, but disconnect
    # one entry from its controller preview. Semantic validation must reject.
    entry = json.loads(files['candidate']['.stygnox/controller-run-0000000000000002.json'])
    entry['preview_sha256'] = sha(b'wrong preview')
    entry.pop('record_sha256')
    altered = blob(seal(entry))
    name = '.stygnox/controller-run-0000000000000002.json'
    files['candidate'][name] = files['control'][name] = altered
    ctrl = json.loads(manifests['control'])
    ctrl['source_files'][name]['sha256'] = sha(altered)
    ctrl['source_files'][name]['size'] = len(altered)
    manifests['control'] = blob(ctrl)
    delta = json.loads(manifests['delta'])
    delta['control_manifest_sha256'] = sha(manifests['control'])
    manifests['delta'] = blob(delta)
    candidate = json.loads(manifests['candidate'])
    candidate['files'][name]['sha256'] = sha(altered)
    candidate['control_manifest_sha256'] = sha(manifests['control'])
    candidate['delta_manifest_sha256'] = sha(manifests['delta'])
    manifests['candidate'] = blob(candidate)
    monkeypatch.setattr(custody, 'EXPECTED', {key: sha(value) for key, value in manifests.items()})
    with pytest.raises(custody.CustodyIntakeRefused, match='continuation is not uniquely bound'):
        reconcile(manifests, files)


@pytest.mark.parametrize('name', [
    '../escape', '/root/state', '.stygnox/../plan.json', 'docs\\file',
])
def test_path_traversal_refused(name):
    with pytest.raises(custody.CustodyIntakeRefused):
        custody._path(name)


def test_host_audit_rejects_nonroot_and_alternate_vault(monkeypatch, tmp_path):
    monkeypatch.setattr(os, 'geteuid', lambda: 1000)
    with pytest.raises(custody.CustodyIntakeRefused, match='privileged Linux'):
        custody.audit_protected_intake()
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    with pytest.raises(custody.CustodyIntakeRefused, match='pinned real recovery vault'):
        custody.audit_protected_intake(tmp_path)


def test_sealing_fails_closed_on_existing_pending_without_overwriting(monkeypatch, tmp_path):
    # Simulate an earlier interrupted publication. The journal is immutable
    # and cannot silently overwrite or recover across crash boundaries.
    monkeypatch.setattr(custody, 'ROOT', tmp_path)
    monkeypatch.setattr(custody, 'audit_protected_intake', lambda: {'phase': 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED'})
    pending = tmp_path / (custody.INTAKE + '.pending')
    pending.mkdir()
    marker = pending / 'marker'
    marker.write_text('keep', encoding='utf-8')
    with pytest.raises(custody.CustodyIntakeRefused, match='manual reconciliation'):
        custody.seal_blocked_intake()
    assert marker.read_text() == 'keep'
    assert not (tmp_path / custody.INTAKE).exists()


def test_source_has_no_authorising_provider_import_or_release_primitive():
    import ast
    path = Path(custody.__file__)
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert not any('provider' in name or 'subprocess' in name for name in imports if name)
    assert not any(isinstance(node, ast.FunctionDef) and
                   ('release' in node.name or 'dispatch' in node.name or 'authorize' in node.name)
                   for node in tree.body)


def test_cli_never_returns_startup_success_or_accepts_release_flags():
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_custody_intake.py'
    blocked = subprocess.run([sys.executable, '-I', '-B', str(script), '--audit'],
                             capture_output=True, text=True, timeout=10)
    assert blocked.returncode == 75
    report = json.loads(blocked.stdout)
    assert report['execution_authority'] == 'NONE'
    assert report['successor_execution_authorised'] is False
    denied = subprocess.run([sys.executable, '-I', '-B', str(script), '--release'],
                            capture_output=True, text=True, timeout=10)
    assert denied.returncode != 0
    assert not denied.stdout


@pytest.mark.skipif(os.geteuid() != 0, reason='root-private publication integration fixture')
def test_one_shot_root_owned_blocked_receipt_is_durable_and_not_replayable(monkeypatch, tmp_path):
    monkeypatch.setattr(custody, 'ROOT', tmp_path)
    monkeypatch.setattr(custody, 'audit_protected_intake',
                        lambda: {'schema': custody.SCHEMA,
                                 'phase': 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED',
                                 'execution_authority': 'NONE',
                                 'successor_execution_authorised': False})
    assert tmp_path.stat().st_uid == 0
    result = custody.seal_blocked_intake()
    assert result['exclusive_transaction_custody'] is False
    assert result['successor_execution_authorised'] is False
    assert result['phase'] == 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED'
    receipt = tmp_path / custody.INTAKE / 'custody-intake.json'
    assert receipt.stat().st_uid == 0
    assert receipt.stat().st_mode & 0o777 == 0o400
    saved = json.loads(receipt.read_text(encoding='utf-8'))
    body = dict(saved)
    assert sha(blob({k: v for k, v in body.items() if k != 'record_sha256'})) == body['record_sha256']
    assert saved['execution_authority'] == 'NONE'
    with pytest.raises(custody.CustodyIntakeRefused, match='manual reconciliation'):
        custody.seal_blocked_intake()
    assert receipt.exists()
