"""Prevent terminal-renewal APIs from resuming an ACTIVE or quarantined transaction.

These are behavioural guards for break-glass source reconciliation.  They do
not grant authority to the original interrupted R3D.2 transaction.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from stygnox import adoption, transactions
from stygnox.direct_interruption_execution_guard import QUARANTINE_MARKER
from test_stygnox_transactions import identity, init_repo


def _files(runtime: Path) -> dict[str, bytes]:
    return {str(p.relative_to(runtime)): p.read_bytes()
            for p in runtime.rglob('*') if p.is_file()}


def test_active_predecessor_is_not_renewable_or_mutated(tmp_path: Path) -> None:
    root = tmp_path / 'project'
    init_repo(root)
    installed = identity(tmp_path)
    with mock.patch.object(adoption, 'resolve_installed_command', return_value=installed):
        preview = adoption.build_preview(root, 'Operator')
        adoption.handoff_adoption(root, 'Operator', preview['preview_sha256'], 'HANDOFF')
        active = transactions.begin_transaction(root, 'Operator', 'BEGIN')
    runtime = root / adoption.RUNTIME_NAME
    before = _files(runtime)
    assert active['state'] == 'ACTIVE'
    with pytest.raises(transactions.TransactionError, match='STOPPED'):
        transactions.build_renewal_preview(root, 'Operator')
    with pytest.raises(transactions.TransactionError, match='STOPPED'):
        transactions.renew_transaction(root, 'Operator', 'a' * 64, 'RENEW')
    assert _files(runtime) == before
    assert not list(runtime.glob('renewal-predecessor-*.json'))


def test_quarantined_runtime_refuses_all_renewal_entrypoints(tmp_path: Path) -> None:
    root = tmp_path / 'project'
    init_repo(root)
    runtime = root / adoption.RUNTIME_NAME
    runtime.mkdir()
    (runtime / QUARANTINE_MARKER).write_text('{not JSON}', encoding='utf-8')
    before = _files(runtime)
    with pytest.raises(transactions.TransactionError, match='RECOVERY_QUARANTINED'):
        transactions.build_renewal_preview(root, 'Operator')
    with pytest.raises(transactions.TransactionError, match='RECOVERY_QUARANTINED'):
        transactions.renew_transaction(root, 'Operator', 'a' * 64, 'RENEW')
    assert _files(runtime) == before
