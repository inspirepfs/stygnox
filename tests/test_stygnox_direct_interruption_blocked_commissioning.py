"""Real data projections and filesystem publication, never provider/controller use."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from stygnox import direct_interruption_custody_intake as custody
from stygnox import direct_interruption_blocked_commissioning as commissioning


def fixture():
    """Synthetic but internally sealed authority graph; caller mutates deep copies."""
    controller = commissioning._seal({
        'transaction_id': custody.TX, 'enabled': True,
        'controller_execution_enabled': True, 'provider_execution_ready': True,
        'installed_command': '/legacy/old-stygnox',
    })
    transaction = commissioning._seal({
        'transaction_id': custody.TX, 'state': 'ACTIVE',
        'installed_command': '/legacy/old-stygnox',
        'authority': {'controller_execution': True, 'scope': 'one-worktree'},
    })
    plan = commissioning._seal({
        'transaction_id': custody.TX, 'plan_hash': custody.PLAN,
        'status': 'APPROVED', 'current_step': 2,
        'execution_authority_granted': True,
        'continuation_history': [{'i': i} for i in range(8)],
        'step_results': [{'step': 1}],
        'controller_record_sha256': controller['record_sha256'],
        'transaction_record_sha256': transaction['record_sha256'],
    })
    evidence = {
        'schema': custody.SCHEMA,
        'phase': 'EVIDENCE_RECONCILED_EXECUTION_BLOCKED',
        'transaction_id': custody.TX,
        'approved_plan_hash': custody.PLAN,
        'evidence_sha256': dict(custody.EXPECTED),
        'predecessor_execution_excluded': False,
        'original_workspace_retired': False,
        'legacy_credential_revoked': False,
        'boot_persistence_proven': False,
        'successor_identity_commissioned': False,
        'exclusive_transaction_custody': False,
        'successor_execution_authorised': False,
        'provider_executed': False,
        'live_workspace_modified': False,
        'execution_authority': 'NONE',
    }
    receipt = commissioning._seal(evidence)
    return dict(intake=receipt, evidence=evidence,
                plan=plan, controller=controller, transaction=transaction)


def render(inputs):
    return commissioning.build_blocked_projection(**inputs)


def test_blocked_projection_preserves_original_history_and_never_releases():
    inputs = fixture()
    historical = deepcopy(inputs)
    result = render(inputs)
    assert inputs == historical  # never mutate historical evidence
    assert set(result) == {'plan.json', 'controller.json', 'transaction.json', commissioning.MARKER}
    for record in result.values():
        assert custody._record_hash(record)
    plan = result['plan.json']
    assert len(plan['continuation_history']) == 8
    assert plan['status'] == 'RECOVERY_QUARANTINED'
    assert plan['execution_authority_granted'] is False
    assert plan['controller_record_sha256'] == inputs['controller']['record_sha256']
    assert result['controller.json']['enabled'] is False
    assert result['controller.json']['controller_execution_enabled'] is False
    assert result['controller.json']['provider_execution_ready'] is False
    assert result['transaction.json']['state'] == 'RECOVERY_QUARANTINED'
    assert result['transaction.json']['authority']['controller_execution'] is False
    marker = result[commissioning.MARKER]
    assert marker['predecessor_exclusion_proved'] is False
    assert marker['successor_execution_authorised'] is False
    assert marker['authority_transferred'] is False
    assert marker['intake_record_sha256'] == inputs['intake']['record_sha256']


@pytest.mark.parametrize('alter', [
    lambda i: i['plan'].update({'current_step': 3}),
    lambda i: i['transaction'].update({'state': 'RELEASED'}),
    lambda i: i['controller'].update({'enabled': False}),
    lambda i: i['plan'].update({'execution_authority_granted': False}),
    lambda i: i['intake'].update({'successor_execution_authorised': True}),
    lambda i: i['evidence'].update({'predecessor_execution_excluded': True}),
    lambda i: i['plan'].update({'continuation_history': [1, 2]}),
    lambda i: i['plan'].update({'transaction_id': 'TX-substituted'}),
    lambda i: i['controller'].update({'installed_command': '/other/controller'}),
    lambda i: i['intake'].update({'record_sha256': '0' * 64}),
])
def test_tampering_refused(alter):
    inputs = fixture()
    alter(inputs)
    with pytest.raises(commissioning.BlockedCommissioningRefused):
        render(inputs)


def test_even_self_hashed_claims_of_exclusion_are_rejected():
    inputs = fixture()
    inputs['evidence']['predecessor_execution_excluded'] = True
    inputs['intake'] = commissioning._seal(inputs['evidence'])
    with pytest.raises(commissioning.BlockedCommissioningRefused):
        render(inputs)


def test_one_shot_filesystem_publication_is_data_only(tmp_path):
    inputs = fixture()
    result = render(inputs)
    before = sorted(tmp_path.iterdir())
    report = commissioning._publish_blocked_projection(tmp_path, result, inputs['intake']['record_sha256'])
    assert before == []
    assert report['successor_execution_authorised'] is False
    assert report['predecessor_excluded'] is False
    published = tmp_path / commissioning.STAGE
    assert published.is_dir()
    assert stat.S_IMODE(published.stat().st_mode) == 0o700
    marker = published / '.stygnox' / commissioning.MARKER
    assert stat.S_IMODE(marker.stat().st_mode) == 0o400
    assert custody._record_hash(json.loads(marker.read_text()))
    state = json.loads((published / '.stygnox' / 'plan.json').read_text())
    assert state['execution_authority_granted'] is False
    assert not (published / 'src').exists()
    assert not (published / 'scripts').exists()
    assert not (tmp_path / (commissioning.STAGE + '.pending')).exists()
    with pytest.raises(commissioning.BlockedCommissioningRefused):
        commissioning._publish_blocked_projection(tmp_path, result, inputs['intake']['record_sha256'])
    assert sorted(tmp_path.iterdir()) == [published]


def test_interrupted_publication_must_not_be_overwritten(tmp_path):
    (tmp_path / (commissioning.STAGE + '.pending')).mkdir()
    with pytest.raises(commissioning.BlockedCommissioningRefused):
        commissioning._publish_blocked_projection(tmp_path, render(fixture()), fixture()['intake']['record_sha256'])
    assert not (tmp_path / commissioning.STAGE).exists()


def test_without_root_real_commissioning_is_denied():
    if os.geteuid() == 0:
        pytest.skip('root host cannot use the unprivileged refusal fixture')
    with pytest.raises(commissioning.BlockedCommissioningRefused, match='Linux root'):
        commissioning.seal_blocked_commissioning()


def test_isolated_cli_never_returns_startup_success():
    script = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_blocked_commissioning.py'
    result = subprocess.run([sys.executable, '-I', '-B', str(script), '--unknown'],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 75
    assert json.loads(result.stdout)['successor_execution_authorised'] is False
    assert not result.stderr


def test_reject_malformed_publication_without_creating_destination(tmp_path):
    inputs = fixture()
    projection = render(inputs)
    projection['plan.json']['execution_authority_granted'] = True
    with pytest.raises(commissioning.BlockedCommissioningRefused):
        commissioning._publish_blocked_projection(tmp_path, projection,
                                                   inputs['intake']['record_sha256'])
    assert list(tmp_path.iterdir()) == []


def test_preserved_marker_blocks_normal_runtime(tmp_path):
    from stygnox.direct_interruption_execution_guard import (
        QuarantinedRuntime, refuse_quarantined_runtime,
    )
    inputs = fixture()
    commissioning._publish_blocked_projection(tmp_path, render(inputs),
                                              inputs['intake']['record_sha256'])
    root = tmp_path / commissioning.STAGE
    with pytest.raises(QuarantinedRuntime, match='RECOVERY_QUARANTINED'):
        refuse_quarantined_runtime(root)
