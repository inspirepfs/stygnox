"""Behavioural tests for isolated, one-shot root-only custody publication."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from stygnox import direct_interruption_custody_intake as intake
from stygnox import direct_interruption_blocked_commissioning as commissioning
from stygnox import direct_interruption_custody_cutover as cutover
from test_stygnox_direct_interruption_blocked_commissioning import fixture


def inputs():
    original = fixture()
    data = cutover.build_blocked_cutover(
        evidence=original['evidence'],
        original_plan=original['plan'],
        original_controller=original['controller'],
        original_transaction=original['transaction'],
    )
    return original, data


def test_integrated_projection_bound_to_unchanged_history():
    original = fixture()
    untouched = deepcopy(original)
    _, data = inputs()
    assert original == untouched
    assert set(data) == {'intake', 'projection', 'cutover'}
    assert all(intake._record_hash(x) for x in data['projection'].values())
    assert intake._record_hash(data['cutover'])
    assert data['cutover']['source_lineage_sha256'] == {
        'plan': original['plan']['record_sha256'],
        'controller': original['controller']['record_sha256'],
        'transaction': original['transaction']['record_sha256'],
    }
    assert data['projection']['plan.json']['continuation_history'] == original['plan']['continuation_history']
    assert data['projection']['plan.json']['step_results'] == original['plan']['step_results']
    assert data['projection']['controller.json']['provider_execution_ready'] is False
    assert data['projection']['transaction.json']['state'] == 'RECOVERY_QUARANTINED'
    assert data['cutover']['old_workspace_ignored_as_successor_authority'] is True
    assert data['cutover']['legacy_controller_excluded'] is False
    assert data['cutover']['operator_release_approved'] is False


@pytest.mark.parametrize('tamper', [
    lambda p: p['cutover'].update({'successor_execution_authorised': True}),
    lambda p: p['cutover'].update({'legacy_controller_excluded': True}),
    lambda p: p['cutover'].update({'original_workspace_retired': True}),
    lambda p: p['cutover'].update({'operator_release_approved': True}),
    lambda p: p['cutover'].update({'root_only_transaction_store': False}),
    lambda p: p['cutover'].update({'intake_record_sha256': '0' * 64}),
    lambda p: p['cutover'].update({'transaction_id': 'TX-OTHER'}),
    lambda p: p['projection']['controller.json'].update({'enabled': True}),
    lambda p: p['projection']['transaction.json'].update({'state': 'ACTIVE'}),
    lambda p: p['projection']['plan.json'].update({'continuation_history': []}),
    lambda p: p['projection'].pop(commissioning.MARKER),
    lambda p: p['intake'].update({'record_sha256': '0' * 64}),
])
def test_tampered_cutover_is_refused_before_publication(tmp_path, tamper):
    _, data = inputs()
    tamper(data)
    with pytest.raises(cutover.CutoverRefused):
        cutover._publish(tmp_path, data)
    assert not list(tmp_path.iterdir())


def test_even_resigned_false_authority_claims_refused(tmp_path):
    _, data = inputs()
    data['cutover']['legacy_controller_excluded'] = True
    data['cutover'] = cutover._seal({k: v for k, v in data['cutover'].items() if k != 'record_sha256'})
    with pytest.raises(cutover.CutoverRefused):
        cutover._publish(tmp_path, data)
    assert not list(tmp_path.iterdir())


def test_one_shot_atomic_publication_and_quarantine_guard(tmp_path):
    _, data = inputs()
    result = cutover._publish(tmp_path, data)
    assert result['phase'] == 'ROOT_CUSTODY_PUBLISHED_EXECUTION_DENIED'
    assert result['successor_execution_authorised'] is False
    assert result['legacy_controller_excluded'] is False
    slot = tmp_path / cutover.SLOT
    assert stat.S_IMODE(slot.stat().st_mode) == 0o700
    assert not (tmp_path / (cutover.SLOT + '.pending')).exists()
    assert sorted(p.name for p in slot.iterdir()) == ['.stygnox', 'custody-intake.json', 'root-custody.json']
    assert not (slot / 'src').exists()
    assert not (slot / 'scripts').exists()
    for name in ('root-custody.json', 'custody-intake.json'):
        path = slot / name
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert intake._record_hash(json.loads(path.read_bytes()))
    assert sorted(p.name for p in (slot / '.stygnox').iterdir()) == sorted(cutover._FILES)
    for path in (slot / '.stygnox').iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        assert intake._record_hash(json.loads(path.read_bytes()))
    with pytest.raises(cutover.CutoverRefused, match='execution-blocked'):
        cutover.refuse_execution_from_custody(slot)
    with pytest.raises(cutover.CutoverRefused, match='existing/interrupted'):
        cutover._publish(tmp_path, data)


def test_crash_marker_blocks_retry_without_deleting_or_repairing(tmp_path):
    _, data = inputs()
    pending = tmp_path / (cutover.SLOT + '.pending')
    pending.mkdir()
    with pytest.raises(cutover.CutoverRefused, match='manual reconciliation'):
        cutover._publish(tmp_path, data)
    assert pending.exists()
    assert not (tmp_path / cutover.SLOT).exists()


def test_resumed_custody_never_grants_provider_access(tmp_path):
    _, data = inputs()
    cutover._publish(tmp_path, data)
    stored = json.loads((tmp_path / cutover.SLOT / 'root-custody.json').read_text())
    assert stored['successor_execution_authorised'] is False
    assert stored['legacy_oauth_revoked'] is False
    assert stored['preopened_file_descriptors_revoked'] is False
    assert stored['root_only_transaction_store'] is True
    assert stored['phase'] == 'ROOT_CUSTODY_PUBLISHED_EXECUTION_DENIED'


def test_ordinary_user_cannot_run_live_root_seal():
    if os.geteuid() == 0:
        pytest.skip('unprivileged Linux fixture cannot run as root')
    with pytest.raises(cutover.CutoverRefused, match='Linux root'):
        cutover.seal_root_custody()


def test_cli_always_denies_service_startup():
    cli = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_root_custody.py'
    for args in ([], ['--invalid']):
        result = subprocess.run([sys.executable, '-I', '-B', str(cli), *args],
                                capture_output=True, text=True, check=False)
        assert result.returncode == 75
        assert json.loads(result.stdout)['successor_execution_authorised'] is False
        assert not result.stderr


def test_missing_quarantine_marker_refuses_execution(tmp_path):
    project = tmp_path / cutover.SLOT
    (project / '.stygnox').mkdir(parents=True)
    with pytest.raises(cutover.CutoverRefused, match='missing quarantine guard'):
        cutover.refuse_execution_from_custody(project)


def test_competing_publishers_cannot_both_claim_one_custody_slot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    _, payload = inputs()

    def attempt():
        try:
            cutover._publish(tmp_path, deepcopy(payload))
            return 'PUBLISHED'
        except cutover.CutoverRefused:
            return 'DENIED'

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda unused: attempt(), range(2)))
    assert sorted(outcomes) == ['DENIED', 'PUBLISHED']
    assert (tmp_path / cutover.SLOT / 'root-custody.json').is_file()


def test_self_sealed_historical_controller_swap_is_rejected():
    original = fixture()
    old_hash = original['controller']['record_sha256']
    replacement = dict(original['controller'])
    replacement['installed_command'] = '/substituted-controller'
    replacement.pop('record_sha256')
    original['controller'] = commissioning._seal(replacement)
    assert original['controller']['record_sha256'] != old_hash
    with pytest.raises(cutover.CutoverRefused, match='blocked projection refused'):
        cutover.build_blocked_cutover(
            evidence=original['evidence'], original_plan=original['plan'],
            original_controller=original['controller'],
            original_transaction=original['transaction'])
