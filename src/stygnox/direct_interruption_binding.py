"""C3h blocked installed-binding *witness* for a protected successor namespace.

This is a digest-bound snapshot of original installed controller and transaction
records. It is neither an installed successor attestation nor a rebind receipt,
and does not authorize execution or replace controller.json/transaction.json.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import controller, transactions
from . import direct_interruption as recovery
from . import direct_interruption_publication as publication
from . import direct_interruption_transfer as transfer

SCHEMA = 'stygnox_direct_interruption_blocked_binding_witness_v1'
FILENAME = 'direct-interruption-blocked-binding.json'


class BindingRefused(RuntimeError):
    """Exact predecessor installed controller/transaction binding is not proven."""


def _record(value: Mapping[str, Any], schema: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BindingRefused('missing predecessor authority record')
    body = dict(value)
    digest = body.pop('record_sha256', None)
    if (body.get('schema') != schema or not transfer._hash_ok(digest)
            or digest != recovery._digest(body)):
        raise BindingRefused('predecessor authority record integrity/schema mismatch')
    body['record_sha256'] = digest
    return body


def build_blocked_binding_witness(*, transfer_preview: Mapping[str, Any],
                                  journal_preview: Mapping[str, Any],
                                  predecessor_controller: Mapping[str, Any],
                                  predecessor_transaction: Mapping[str, Any],
                                  original: Path, published: Path) -> dict[str, Any]:
    """Bind exact predecessor records to a *blocked* candidate namespace.

    The protected successor stays non-executable; the old controller.json and
    transaction.json are intentionally unchanged. Real rebind, installed
    successor verification, process exclusion and human approval remain gates.
    """
    try:
        proposal = publication._transfer(transfer_preview)
        if dict(journal_preview) != publication.build_journal_preview(proposal):
            raise BindingRefused('publication journal does not match fenced proposal')
        active = _record(predecessor_controller, controller.CONTROLLER_SCHEMA)
        tx = _record(predecessor_transaction, transactions.TRANSACTION_SCHEMA)
    except (publication.PublicationRefused, transfer.TransferRefused) as exc:
        raise BindingRefused(str(exc)) from exc
    fenced = proposal['fenced_plan']
    original = Path(original)
    published = Path(published)
    if (not original.is_absolute() or not published.is_absolute() or original == published
            or '..' in original.parts or '..' in published.parts):
        raise BindingRefused('distinct canonical absolute worktree paths required')
    predecessor_path = fenced['direct_interruption_transfer_pending']['successor_executable']
    # The successor is recorded as a *claim* from admission, not an attested
    # fresh-process executable or a release entitlement.
    if (not isinstance(predecessor_path, str) or not predecessor_path.startswith('/')
            or active.get('record_sha256') != proposal['predecessor_controller_record_sha256']
            or tx.get('record_sha256') != proposal['predecessor_transaction_record_sha256']
            or active.get('installed_command') != tx.get('installed_command')
            or not isinstance(active.get('installed_command'), str)
            or not active['installed_command'].startswith('/')
            or active['installed_command'] == predecessor_path
            or active.get('enabled') is not True
            or tx.get('state') != 'ACTIVE'
            or active.get('transaction_id') != fenced.get('transaction_id')
            or tx.get('transaction_id') != fenced.get('transaction_id')
            or fenced.get('controller_record_sha256') != active['record_sha256']
            or fenced.get('transaction_record_sha256') != tx['record_sha256']
            or fenced.get('execution_authority_granted') is not False):
        raise BindingRefused('controller/transaction/plan lineage or blocking invariant failed')
    # The original approved transaction must be tied to the same legacy CLI as
    # the handoff admission; no substitution of an equally self-hashed record.
    # The transfer digest binds the SHA, while this witness binds the path.
    body = {
        'schema': SCHEMA,
        'original_worktree': str(original),
        'published_successor_worktree': str(published),
        'plan_hash': fenced['plan_hash'],
        'transaction_id': fenced['transaction_id'],
        'predecessor_plan_record_sha256': proposal['predecessor_plan_record_sha256'],
        'fenced_plan_record_sha256': fenced['record_sha256'],
        'predecessor_controller_record_sha256': active['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'predecessor_installed_command': active['installed_command'],
        'candidate_installed_command_unverified': predecessor_path,
        'transfer_preview_sha256': proposal['preview_sha256'],
        'journal_preview_sha256': journal_preview['preview_sha256'],
        'controller_record_replaced': False,
        'transaction_record_replaced': False,
        'original_binding_retired': False,
        'successor_installed_identity_verified': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'authority_changed': False,
    }
    body['record_sha256'] = recovery._digest(body)
    return body
