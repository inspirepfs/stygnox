"""C3b crash-boundary journal *contract*, with no live publication authority.

A journal is a proposal, not a durable lease, proof of process exclusion or
permission to write ``.stygnox``. Neither building nor replaying this contract
can transfer control. In particular an old provider process can be in flight
past its initial planning check; a journal and an atomic plan replacement
alone cannot fence that process.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import direct_interruption as recovery
from . import direct_interruption_transfer as transfer
from .direct_interruption_fence import SUCCESSOR_STATUS

SCHEMA = "stygnox_direct_interruption_publication_journal_preview_v1"
NO_FENCE = "PREDECESSOR_UNCHANGED_NO_HANDOFF"
JOURNAL_ONLY = "JOURNAL_PROPOSED_PREDECESSOR_STILL_ENABLED"
FENCED = "FENCED_EXECUTION_BLOCKED_NO_HANDOFF"


class PublicationRefused(RuntimeError):
    """Publication integrity, lineage or fencing evidence is insufficient."""


def _sealed(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicationRefused("missing journal/transfer evidence")
    body = dict(value)
    proof = body.pop(field, None)
    if not transfer._hash_ok(proof) or recovery._digest(body) != proof:
        raise PublicationRefused(f"{field} integrity mismatch")
    body[field] = proof
    return body


def _transfer(preview: object) -> dict[str, Any]:
    candidate = _sealed(preview, "preview_sha256")
    if (candidate.get("schema") != transfer.SCHEMA
        or candidate.get("authority_changed") is not False
        or candidate.get("admissible") is not False
        or candidate.get("exclusive_handoff_proved") is not False
        or candidate.get("successor_execution_authorised") is not False):
        raise PublicationRefused("transfer proposal is not a blocked, unapproved preview")
    plan = _sealed(candidate.get("fenced_plan"), "record_sha256")
    pending = plan.get("direct_interruption_transfer_pending")
    if (plan.get("status") != SUCCESSOR_STATUS
        or plan.get("execution_authority_granted") is not False
        or not isinstance(pending, Mapping)
        or pending.get("publication_state") != "UNPUBLISHED"
        or pending.get("successor_execution_authorised") is not False
        or pending.get("predecessor_plan_record_sha256") != candidate.get("predecessor_plan_record_sha256")
        or pending.get("admission_preview_sha256") != candidate.get("admission_preview_sha256")
        or pending.get("predecessor_controller_record_sha256") != candidate.get("predecessor_controller_record_sha256")
        or pending.get("predecessor_transaction_record_sha256") != candidate.get("predecessor_transaction_record_sha256")
        or pending.get("review_preview_sha256") is None
        or pending.get("manifest_proof_sha256") is None):
        raise PublicationRefused("fenced plan has incomplete or execution-enabling lineage")
    for key in ("predecessor_plan_record_sha256", "predecessor_controller_record_sha256",
                "predecessor_transaction_record_sha256", "admission_preview_sha256"):
        if not transfer._hash_ok(candidate.get(key)):
            raise PublicationRefused(f"invalid transfer identity: {key}")
    return candidate


def build_journal_preview(transfer_preview: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic proposed write-ahead journal; no filesystem operations.

    It is not an authenticated human approval or fencing lease. The future
    publisher must establish exclusive old-process exclusion *before* any
    journal/plan publication and must revalidate the exact predecessor.
    """
    proposal = _transfer(transfer_preview)
    fenced = proposal["fenced_plan"]
    pending = fenced["direct_interruption_transfer_pending"]
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "transfer_preview_sha256": proposal["preview_sha256"],
        "predecessor_plan_record_sha256": proposal["predecessor_plan_record_sha256"],
        "fenced_plan_record_sha256": fenced["record_sha256"],
        "predecessor_controller_record_sha256": proposal["predecessor_controller_record_sha256"],
        "predecessor_transaction_record_sha256": proposal["predecessor_transaction_record_sha256"],
        "admission_preview_sha256": pending["admission_preview_sha256"],
        "review_preview_sha256": pending["review_preview_sha256"],
        "manifest_proof_sha256": pending["manifest_proof_sha256"],
        "proposed_status": SUCCESSOR_STATUS,
        "legacy_process_exclusion_proved": False,
        "exclusive_lock_proved": False,
        "journal_published": False,
        "plan_published": False,
        "successor_execution_authorised": False,
        "authority_changed": False,
        "admissible": False,
    }
    body["preview_sha256"] = recovery._digest(body)
    return body


def reconcile_crash_boundary(transfer_preview: Mapping[str, Any],
                             journal: Mapping[str, Any] | None,
                             current_plan: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a proposed journal/plan crash boundary without writing anything.

    The two exact, fully blocked states may be inspected, NEVER automatically
    recovered or released. A missing journal alongside a fenced plan is an
    unresolved publication, not a valid transfer. No boolean in supplied
    evidence can elevate authority or validate exclusion of live processes.
    """
    proposal = _transfer(transfer_preview)
    current = _sealed(current_plan, "record_sha256")
    if journal is None:
        if current.get("record_sha256") != proposal["predecessor_plan_record_sha256"]:
            raise PublicationRefused("fence exists without verified publication journal")
        phase = NO_FENCE
    else:
        observed = _sealed(journal, "preview_sha256")
        exact = build_journal_preview(proposal)
        if observed != exact:
            raise PublicationRefused("substituted or authority-claiming publication journal")
        try:
            phase = transfer.classify_publication(proposal, current)
        except transfer.TransferRefused as exc:
            raise PublicationRefused(str(exc)) from exc
        if phase == NO_FENCE:
            phase = JOURNAL_ONLY
        elif phase != FENCED:
            raise PublicationRefused("unknown or partial publication boundary")
    return {
        "schema": "stygnox_direct_interruption_crash_boundary_review_v1",
        "phase": phase,
        "predecessor_record_sha256": proposal["predecessor_plan_record_sha256"],
        "current_plan_record_sha256": current["record_sha256"],
        "transfer_preview_sha256": proposal["preview_sha256"],
        "legacy_plan_gated_admissions_may_continue": phase != FENCED,
        "all_legacy_mutation_paths_fenced": False,
        "inflight_legacy_execution_excluded": False,
        "authority_changed": False,
        "handoff_admissible": False,
        "successor_execution_authorised": False,
        "automatic_repair_permitted": False,
    }


def require_exclusive_publication_authority() -> None:
    """Never treat an ordinary file lock or a proposal as legacy-process fencing."""
    raise PublicationRefused(
        "exclusive predecessor process fencing is unproved; no live fence publication authorised"
    )
