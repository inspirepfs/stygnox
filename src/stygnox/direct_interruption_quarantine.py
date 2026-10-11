"""C3j: publish a *disabled*, successor-pinned controller/transaction pair.

This is only a blocked authority-state projection. It is NOT a rebind receipt,
operator approval, predecessor process exclusion or permission to execute.
Quarantine records are written exclusively by the root-supervised, unpublished
C3g staging transaction before the protected successor is exposed.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from . import direct_interruption as recovery
from . import direct_interruption_binding as binding
from . import direct_interruption_publication as publication
from .direct_interruption_fence import SUCCESSOR_STATUS

SCHEMA = 'stygnox_c3j_quarantined_installed_binding_v1'
FILENAME = 'direct-interruption-quarantined-binding.json'


class QuarantineRefused(RuntimeError):
    """A copied predecessor cannot be replaced with a safe blocked binding."""


def build_quarantine_binding(*, fenced_plan: Mapping[str, Any],
                             journal: Mapping[str, Any], witness: Mapping[str, Any],
                             predecessor_controller: Mapping[str, Any],
                             predecessor_transaction: Mapping[str, Any]) -> dict[str, Any]:
    """Produce exact successor-pinned *non-executing* records and their witness.

    The original plan's controller/transaction hashes deliberately remain
    predecessor hashes: the successor has NOT been granted new plan authority.
    """
    try:
        plan = publication._sealed(fenced_plan, 'record_sha256')
        jrnl = publication._sealed(journal, 'preview_sha256')
        bridge = publication._sealed(witness, 'record_sha256')
        ctrl = binding._record(predecessor_controller, 'stygnox_controller_state_v1')
        tx = binding._record(predecessor_transaction, 'stygnox_transaction_v1')
    except (publication.PublicationRefused, binding.BindingRefused) as exc:
        raise QuarantineRefused(f'invalid predecessor evidence: {exc}') from exc
    fence = plan.get('direct_interruption_transfer_pending')
    installed = fence.get('successor_executable') if isinstance(fence, Mapping) else None
    if (plan.get('status') != SUCCESSOR_STATUS
            or plan.get('execution_authority_granted') is not False
            or not isinstance(installed, str) or not installed.startswith('/')
            or bridge.get('schema') != binding.SCHEMA
            or bridge.get('fenced_plan_record_sha256') != plan['record_sha256']
            or bridge.get('journal_preview_sha256') != jrnl['preview_sha256']
            or bridge.get('predecessor_controller_record_sha256') != ctrl['record_sha256']
            or bridge.get('predecessor_transaction_record_sha256') != tx['record_sha256']
            or bridge.get('candidate_installed_command_unverified') != installed
            or bridge.get('predecessor_installed_command') != ctrl.get('installed_command')
            or ctrl.get('installed_command') != tx.get('installed_command')
            or ctrl.get('enabled') is not True
            or tx.get('state') != 'ACTIVE'
            or ctrl.get('transaction_id') != tx.get('transaction_id')
            or tx.get('transaction_id') != plan.get('transaction_id')
            or plan.get('controller_record_sha256') != ctrl['record_sha256']
            or plan.get('transaction_record_sha256') != tx['record_sha256']
            or bridge.get('authority_changed') is not False
            or bridge.get('handoff_admissible') is not False
            or bridge.get('original_binding_retired') is not False
            or bridge.get('successor_execution_authorised') is not False):
        raise QuarantineRefused('blocked lineage or successor-disabled invariant mismatch')

    marker = {
        'schema': SCHEMA,
        'predecessor_controller_record_sha256': ctrl['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'fenced_plan_record_sha256': plan['record_sha256'],
        'blocked_binding_record_sha256': bridge['record_sha256'],
        'journal_preview_sha256': jrnl['preview_sha256'],
        'candidate_installed_command_unverified': installed,
        'execution_authorised': False,
    }
    successor_controller = deepcopy(ctrl)
    successor_controller.pop('record_sha256')
    successor_controller.update({
        'installed_command': installed,
        'enabled': False,
        'controller_execution_enabled': False,
        'provider_execution_ready': False,
        'direct_interruption_quarantine': deepcopy(marker),
    })
    successor_controller['record_sha256'] = recovery._digest(successor_controller)

    successor_transaction = deepcopy(tx)
    successor_transaction.pop('record_sha256')
    successor_transaction.update({
        'installed_command': installed,
        'state': 'RECOVERY_QUARANTINED',
        'direct_interruption_quarantine': deepcopy(marker),
    })
    authority = dict(successor_transaction.get('authority') or {})
    authority['controller_execution'] = False
    successor_transaction['authority'] = authority
    successor_transaction['record_sha256'] = recovery._digest(successor_transaction)

    receipt = {
        'schema': SCHEMA,
        'predecessor_controller_snapshot': ctrl,
        'predecessor_transaction_snapshot': tx,
        'predecessor_controller_record_sha256': ctrl['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'successor_controller_record_sha256': successor_controller['record_sha256'],
        'successor_transaction_record_sha256': successor_transaction['record_sha256'],
        'blocked_binding_record_sha256': bridge['record_sha256'],
        'fenced_plan_record_sha256': plan['record_sha256'],
        'journal_preview_sha256': jrnl['preview_sha256'],
        'candidate_installed_command_unverified': installed,
        'transaction_id': plan['transaction_id'],
        'original_binding_retired': False,
        'installed_successor_identity_verified': False,
        'predecessor_process_exclusion_proved': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'authority_changed': False,
    }
    receipt['record_sha256'] = recovery._digest(receipt)
    return {'controller': successor_controller, 'transaction': successor_transaction,
            'receipt': receipt}


def validate_quarantine_binding(*, fenced_plan: Mapping[str, Any],
                                journal: Mapping[str, Any], witness: Mapping[str, Any],
                                controller_record: Mapping[str, Any],
                                transaction_record: Mapping[str, Any],
                                quarantine_record: Mapping[str, Any]) -> dict[str, Any]:
    """Compare each published record to a fresh immutable predecessor projection."""
    try:
        receipt = publication._sealed(quarantine_record, 'record_sha256')
        old_controller = receipt['predecessor_controller_snapshot']
        old_transaction = receipt['predecessor_transaction_snapshot']
        expected = build_quarantine_binding(
            fenced_plan=fenced_plan, journal=journal, witness=witness,
            predecessor_controller=old_controller,
            predecessor_transaction=old_transaction)
    except (KeyError, TypeError, ValueError, publication.PublicationRefused) as exc:
        raise QuarantineRefused(f'invalid quarantine witness: {exc}') from exc
    if (receipt != expected['receipt']
            or dict(controller_record) != expected['controller']
            or dict(transaction_record) != expected['transaction']):
        raise QuarantineRefused('quarantine records are partial, stale or substituted')
    return expected
