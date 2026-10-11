"""Stage C2a successor-only authority *design* evidence (read-only).

An installed R3D.1 controller does not validate its invoking executable against
``installed_command``.  A successor must therefore NEVER restore the ordinary
``APPROVED`` / ``execution_authority_granted=True`` combination: that would
allow the legacy executable to resume.  This module specifies an explicitly
incompatible plan encoding for a later, separately qualified successor path.

It does not transfer, acquire, issue, release or grant authority.  The new
controller MUST implement and hostile-test full successor-only admission and
final qualification before this contract may be used to publish live state.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import direct_interruption as recovery

SCHEMA = "stygnox_direct_interruption_successor_fence_design_v1"
SUCCESSOR_STATUS = "RECOVERY_SUCCESSOR_APPROVED_V1"
# A literal boolean False is essential: all legacy admission paths require True.
LEGACY_EXECUTION_AUTHORITY = False


class FenceRefused(RuntimeError):
    """An untrusted, stale or ambiguous handoff design was supplied."""


def build_fence_design(handoff: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the proposed downgrade-fencing format without changing any state.

    The output is an operator-review design, NOT evidence that the original
    installed executable has been exercised or that successor execution is
    available. It is intentionally inadmissible until separate hostile proof.
    """
    if not isinstance(handoff, Mapping):
        raise FenceRefused("handoff preview is not a mapping")
    recorded = handoff.get("preview_sha256")
    if not isinstance(recorded, str) or recorded != recovery._digest(
        {k: v for k, v in handoff.items() if k != "preview_sha256"}
    ):
        raise FenceRefused("handoff preview digest invalid")
    if (handoff.get("schema") != "stygnox_direct_interruption_handoff_preview_v1"
        or handoff.get("authority_changed") is not False
        or handoff.get("admissible") is not False
        or handoff.get("old_controller_fencing_proved") is not False
        or handoff.get("fresh_process_authority_transfer_proved") is not False):
        raise FenceRefused("input must be an unchanged, read-only C1 handoff preview")
    old = handoff.get("predecessor_installed_executable")
    candidate = handoff.get("candidate_installed_identity")
    wheel = handoff.get("candidate_wheel_identity")
    if not isinstance(old, Mapping) or not isinstance(candidate, Mapping) or not isinstance(wheel, Mapping):
        raise FenceRefused("missing predecessor or installed successor identity")
    for name, value in (
        ("predecessor executable fingerprint", old.get("sha256")),
        ("successor wheel digest", wheel.get("sha256")),
        ("plan record identity", handoff.get("predecessor_plan_record_sha256")),
        ("controller record identity", handoff.get("predecessor_controller_record_sha256")),
        ("transaction record identity", handoff.get("predecessor_transaction_record_sha256")),
        ("source review identity", handoff.get("review_preview_sha256")),
        ("manifest proof identity", handoff.get("manifest_proof_sha256")),
    ):
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise FenceRefused(f"missing or invalid {name}")
    if (not isinstance(old.get("path"), str) or not isinstance(candidate.get("executable"), str)
        or old["path"] == candidate["executable"]):
        raise FenceRefused("successor executable must differ from the original")
    body = {
        "schema": SCHEMA,
        "handoff_preview_sha256": recorded,
        "worktree": handoff.get("worktree"),
        "operator": handoff.get("operator"),
        "plan_hash": handoff.get("plan_hash"),
        "transaction_id": handoff.get("transaction_id"),
        "step": handoff.get("step"),
        "predecessor_plan_record_sha256": handoff["predecessor_plan_record_sha256"],
        "predecessor_controller_record_sha256": handoff["predecessor_controller_record_sha256"],
        "predecessor_transaction_record_sha256": handoff["predecessor_transaction_record_sha256"],
        "predecessor_installed_executable": dict(old),
        "successor_installed_identity": dict(candidate),
        "successor_wheel_identity": dict(wheel),
        "review_preview_sha256": handoff["review_preview_sha256"],
        "manifest_proof_sha256": handoff["manifest_proof_sha256"],
        "proposed_plan_status": SUCCESSOR_STATUS,
        "proposed_legacy_execution_authority_granted": LEGACY_EXECUTION_AUTHORITY,
        "legacy_approved_status_must_not_be_published": True,
        "successor_must_prove_exact_installed_invocation": True,
        "old_binary_refusal_tested_in_fresh_process": False,
        "successor_admission_implemented": False,
        "scheduler_and_qualification_compatible": False,
        "exclusive_transfer_qualified": False,
        "authority_changed": False,
        "admissible": False,
    }
    body["preview_sha256"] = recovery._digest(body)
    return body
