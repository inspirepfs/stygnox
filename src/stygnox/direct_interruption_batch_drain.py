"""Release 02C: simultaneous admission and pidfd drain for *named* predecessors.

The caller supplies a complete independently reviewed list of exact live
installed-command identities. This primitive checks ALL of them and pins ALL
pidfds before sending any signal, so a bad candidate fails without affecting
an otherwise legitimate process. It cannot certify that the list is complete,
prevent new launches, revoke open FDs, or authorise handoff.

Not connected to a CLI or a live retirement operation.
"""
from __future__ import annotations

from contextlib import ExitStack
import os
import select
import signal
import time
from typing import Sequence

from .direct_interruption_nonchild_drain import (
    InstalledPredecessor, NonchildDrainRefused, _attest,
)
from .direct_interruption_process import ProcessDrainRefused, read_process_identity


class BatchDrainRefused(NonchildDrainRefused):
    """The exact set could not be safely admitted or drained."""


def _require_batch(approvals: Sequence[InstalledPredecessor], timeout: float) -> tuple[InstalledPredecessor, ...]:
    if (os.name != 'posix' or not hasattr(os, 'pidfd_open') or
            not hasattr(signal, 'pidfd_send_signal')):
        raise BatchDrainRefused('Linux pidfd_open/pidfd_send_signal required')
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
        raise BatchDrainRefused('bounded positive timeout required')
    if not isinstance(approvals, (tuple, list)) or not 1 <= len(approvals) <= 32:
        raise BatchDrainRefused('one to 32 explicitly approved processes required')
    if any(not isinstance(value, InstalledPredecessor) for value in approvals):
        raise BatchDrainRefused('exact installed predecessor approvals required')
    if len({a.identity.pid for a in approvals}) != len(approvals):
        raise BatchDrainRefused('duplicate PID admission refused')
    if len({a.identity.uid for a in approvals}) != 1:
        raise BatchDrainRefused('all predecessors must share a non-root UID')
    return tuple(approvals)


def drain_exact_predecessor_batch(approvals: Sequence[InstalledPredecessor], *, timeout: float = 5.0) -> dict:
    """TERM a specific, fully attested set using only held Linux pidfds.

    No generic process enumeration, UID sweep, SIGKILL or PID-based signalling.
    Bad admission sends NO signals. A later failure may occur after some TERM
    signals and must be treated as a partial drain, with authority blocked.
    The caller must reconcile the live process set separately; a successful
    batch is *not* proof of exclusive predecessor exclusion.
    """
    targets = _require_batch(approvals, timeout)
    try:
        with ExitStack() as stack:
            pinned: list[tuple[InstalledPredecessor, int, select.poll]] = []
            # Admission phase: attest and pin ALL before any termination.
            for approval in targets:
                _attest(approval)
                try:
                    fd = os.pidfd_open(approval.identity.pid, 0)
                except OSError as exc:
                    raise BatchDrainRefused(f'pidfd admission failed for {approval.identity.pid}: {exc}') from exc
                stack.callback(os.close, fd)
                _attest(approval)
                poller = select.poll()
                poller.register(fd, select.POLLIN)
                if poller.poll(0):
                    raise BatchDrainRefused('process exited during batch admission; no signals sent')
                pinned.append((approval, fd, poller))
            # A final full-set check catches changes after earlier admission.
            for approval, _, poller in pinned:
                _attest(approval)
                if poller.poll(0):
                    raise BatchDrainRefused('process exited before final admission; no signals sent')
            # Signal phase: no unsafe fallback if any kernel operation fails.
            issued: list[int] = []
            for approval, fd, _ in pinned:
                try:
                    signal.pidfd_send_signal(fd, signal.SIGTERM, None, 0)
                    issued.append(approval.identity.pid)
                except OSError as exc:
                    raise BatchDrainRefused(
                        f'partial batch: TERM delivered to {issued!r}; '
                        f'pidfd signalling failed for {approval.identity.pid}: {exc}; '
                        'reconciliation required, authority stays blocked'
                    ) from exc
            deadline = time.monotonic() + timeout
            for approval, _, poller in pinned:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BatchDrainRefused(
                            f'partial/undrained batch after TERM to {issued!r}; '
                            'reconciliation required, authority stays blocked'
                        )
                    if poller.poll(min(max(1, int(remaining * 1000)), 500)):
                        break
                try:
                    current = read_process_identity(approval.identity.pid)
                except ProcessDrainRefused:
                    current = None
                if current == approval.identity:
                    raise BatchDrainRefused(
                        f'process {approval.identity.pid} still active after pidfd readiness; '
                        'authority stays blocked'
                    )
    except NonchildDrainRefused as exc:
        if isinstance(exc, BatchDrainRefused):
            raise
        raise BatchDrainRefused(f'exact batch attestation refused: {exc}') from exc
    return {
        'schema': 'stygnox_release02c_exact_pidfd_batch_v1',
        'predecessor_uid': targets[0].identity.uid,
        'drained_processes': [
            {'pid': a.identity.pid, 'start_ticks': a.identity.start_ticks,
             'installed_sha256': a.installed_sha256}
            for a in targets
        ],
        'exact_batch_exited_via_pidfd': True,
        'batch_claims_all_predecessors': False,
        'unknown_predecessor_holders_excluded': False,
        'new_legacy_starts_blocked': False,
        'original_binding_retired': False,
        'authority_changed': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
    }
