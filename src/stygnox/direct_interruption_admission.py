"""Stage C2b read-only successor-admission *preflight*, not an authority grant.

A matching installed binary, digest-bound design, or an assertion that an old
controller refused is not in itself authority.  This module checks that the
pre-transfer identities are still exact, and deliberately never issues a
successor token, upgrades a plan status, or writes to ``.stygnox``.

The exceptional transfer is inadmissible until independently witnessed legacy
fresh-process refusal, exclusive mutation fencing, publication/recovery and
successor execution/qualification paths are implemented and hostile-qualified.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
import hashlib
import sys

from . import adoption, controller, lifecycle, planning, scheduler, transactions
from . import direct_interruption as recovery
from . import direct_interruption_fence as fence
from . import direct_interruption_handoff as handoff

SCHEMA = "stygnox_direct_interruption_successor_admission_preflight_v1"


class AdmissionRefused(RuntimeError):
    """The observed state cannot support an exact future handoff."""


def build_admission_preflight(
    project: Path, origin_file: Path, origin_sha256: str,
    reviewed_paths: Sequence[str], candidate_wheel: Path,
) -> dict[str, Any]:
    """Reread and bind pre-transfer state.  Never infer/transfer execution authority."""
    root = adoption.resolve_worktree(project)
    candidate = handoff.build_handoff_preview(root, origin_file, origin_sha256, reviewed_paths, candidate_wheel)
    design = fence.build_fence_design(candidate)
    state = recovery._checked(planning._record(root))
    active = recovery._checked(controller._controller(root))
    tx = recovery._checked(transactions._transaction(root))

    if (state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True
        or state.get("active_gate") is not None or state.get("self_development_grant") is not None
        or state.get("direct_interruption_pending") is not None
        or state.get("plan_hash") != candidate["plan_hash"]
        or state.get("transaction_id") != candidate["transaction_id"]
        or state.get("current_step") != candidate["step"]
        or state.get("operator") != candidate["operator"]
        or state.get("record_sha256") != candidate["predecessor_plan_record_sha256"]
        or active.get("record_sha256") != candidate["predecessor_controller_record_sha256"]
        or tx.get("record_sha256") != candidate["predecessor_transaction_record_sha256"]
        or active.get("installed_command") != candidate["predecessor_installed_executable"]["path"]
        or tx.get("installed_command") != active.get("installed_command")
        or tx.get("state") != "ACTIVE" or active.get("enabled") is not True):
        raise AdmissionRefused("original approved plan/transaction/controller identity changed")

    original = Path(candidate["predecessor_installed_executable"]["path"])
    if (original.is_symlink() or not original.is_file() or
        hashlib.sha256(original.read_bytes()).hexdigest() != candidate["predecessor_installed_executable"]["sha256"]):
        raise AdmissionRefused("original installed executable changed during admission preflight")

    # Revalidate installed package + RECORD against the actual invoking command.
    # The installed R3D.1 identity verifier rejects source-tree imports and
    # unrelated launcher paths; never accept a claimed self-reported identity.
    try:
        installed = lifecycle._installed_identity(root)
        wheel = lifecycle._wheel_identity(candidate_wheel, installed)
    except (lifecycle.LifecycleError, adoption.AdoptionError) as exc:
        raise AdmissionRefused(f"successor installed identity failed: {exc}") from exc
    if (installed != candidate["candidate_installed_identity"] or
        wheel != candidate["candidate_wheel_identity"] or
        Path(sys.argv[0]).resolve() != Path(installed["executable"]).resolve()):
        raise AdmissionRefused("successor installed package/wheel/invocation identity drifted")

    try:
        recovery._quiescent(root)
    except recovery.RecoveryRefused as exc:
        raise AdmissionRefused(str(exc)) from exc

    if design.get("proposed_plan_status") != fence.SUCCESSOR_STATUS or design.get("proposed_legacy_execution_authority_granted") is not False:
        raise AdmissionRefused("legacy-incompatible successor fencing contract changed")
    if candidate.get("authority_changed") is not False or design.get("admissible") is not False:
        raise AdmissionRefused("unreviewed admission/authority escalation asserted")

    body: dict[str, Any] = {
        "schema": SCHEMA,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "transaction_id": state["transaction_id"],
        "current_step": state["current_step"],
        "operator": state["operator"],
        "predecessor_plan_record_sha256": state["record_sha256"],
        "predecessor_controller_record_sha256": active["record_sha256"],
        "predecessor_transaction_record_sha256": tx["record_sha256"],
        "handoff_preview_sha256": candidate["preview_sha256"],
        "fence_design_sha256": design["preview_sha256"],
        "review_preview_sha256": candidate["review_preview_sha256"],
        "manifest_proof_sha256": candidate["manifest_proof_sha256"],
        "predecessor_installed_executable": candidate["predecessor_installed_executable"],
        "successor_installed_identity": installed,
        "successor_wheel_identity": wheel,
        "proposed_successor_only_plan_status": fence.SUCCESSOR_STATUS,
        "proposed_legacy_execution_authority_granted": False,
        "old_binary_fresh_process_refusal": "UNPROVED",
        "exclusive_transfer_publication": "NOT_IMPLEMENTED",
        "successor_execution_admission": "DISABLED",
        "independent_successor_qualification": "NOT_IMPLEMENTED",
        "authority_changed": False,
        "admissible": False,
    }
    body["preview_sha256"] = recovery._digest(body)
    return body
