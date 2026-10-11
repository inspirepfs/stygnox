"""C3h blocked installed-binding witness contract; no root privileges needed."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from stygnox import direct_interruption as recovery
from stygnox.direct_interruption_binding import BindingRefused, build_blocked_binding_witness
from tests.test_stygnox_direct_interruption_supervisor import _evidence


def _inputs():
    plan, proposal, journal, active, tx = _evidence()
    return dict(transfer_preview=proposal, journal_preview=journal,
                predecessor_controller=active, predecessor_transaction=tx,
                original=Path('/root-managed/old'), published=Path('/root-managed/new'))


def _reseal(record):
    result = dict(record)
    result.pop('record_sha256')
    result['record_sha256'] = recovery._digest(result)
    return result


def test_exact_predecessor_binding_yields_only_blocked_witness():
    inputs = _inputs()
    record = build_blocked_binding_witness(**inputs)
    assert record['schema'] == 'stygnox_direct_interruption_blocked_binding_witness_v1'
    assert record['predecessor_controller_record_sha256'] == inputs['predecessor_controller']['record_sha256']
    assert record['predecessor_transaction_record_sha256'] == inputs['predecessor_transaction']['record_sha256']
    assert record['original_worktree'] != record['published_successor_worktree']
    assert record['controller_record_replaced'] is False
    assert record['transaction_record_replaced'] is False
    assert record['original_binding_retired'] is False
    assert record['successor_installed_identity_verified'] is False
    assert record['successor_execution_authorised'] is False
    assert record['handoff_admissible'] is False
    assert record['authority_changed'] is False
    digest = record.pop('record_sha256')
    assert digest == recovery._digest(record)


def test_tampered_controller_digest_refused():
    inputs = _inputs()
    inputs['predecessor_controller'] = deepcopy(inputs['predecessor_controller'])
    inputs['predecessor_controller']['installed_command'] = '/forged/bin/stygnox'
    with pytest.raises(BindingRefused):
        build_blocked_binding_witness(**inputs)


def test_self_sealed_substituted_transaction_refused():
    inputs = _inputs()
    inputs['predecessor_transaction'] = _reseal({**inputs['predecessor_transaction'],
                                                 'installed_command': '/forged/bin/stygnox'})
    with pytest.raises(BindingRefused):
        build_blocked_binding_witness(**inputs)


def test_inactive_predecessor_refused_even_with_valid_digest():
    inputs = _inputs()
    inputs['predecessor_transaction'] = _reseal({**inputs['predecessor_transaction'], 'state': 'STOPPED'})
    with pytest.raises(BindingRefused):
        build_blocked_binding_witness(**inputs)


def test_invalid_candidate_journal_refused():
    inputs = _inputs()
    inputs['journal_preview'] = {**inputs['journal_preview'], 'plan_published': True}
    with pytest.raises(BindingRefused):
        build_blocked_binding_witness(**inputs)


def test_same_predecessor_successor_namespace_refused():
    inputs = _inputs()
    inputs['published'] = inputs['original']
    with pytest.raises(BindingRefused):
        build_blocked_binding_witness(**inputs)


def test_same_old_and_candidate_executable_refused():
    inputs = _inputs()
    inputs['predecessor_controller'] = _reseal({**inputs['predecessor_controller'],
                                               'installed_command': '/new/bin/stygnox'})
    inputs['predecessor_transaction'] = _reseal({**inputs['predecessor_transaction'],
                                                'installed_command': '/new/bin/stygnox'})
    with pytest.raises(BindingRefused):
        build_blocked_binding_witness(**inputs)
