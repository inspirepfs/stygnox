"""C3a: deterministic, **read-only** exceptional transfer publication contract.

A transfer must FIRST publish a plan state rejected by the original R3D.1
controller.  This module builds and revalidates that prospective single-record
fence; it does not publish, acquire, or release execution authority.

In particular, a new executable's identity and operator approval are not proof
that old running processes have stopped.  The publication and process fencing
protocol is deliberately not enabled in this stage.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from . import direct_interruption as recovery
from .direct_interruption_fence import SUCCESSOR_STATUS

SCHEMA = "stygnox_direct_interruption_transfer_fence_preview_v1"
FENCE_SCHEMA = "stygnox_direct_interruption_transfer_fence_v1"
BLOCKER = (
    "exclusive installed authority transfer is not hostile-qualified; "
    "successor release and legacy-compatible execution are forbidden"
)


class TransferRefused(RuntimeError):
    """State or evidence cannot be used to publish an exclusive fence."""


def _hash_ok(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in '0123456789abcdef' for ch in value)


def _sealed(value: object, key: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TransferRefused("missing transfer evidence")
    value = dict(value)
    digest = value.get(key)
    if not _hash_ok(digest) or digest != recovery._digest({k: v for k, v in value.items() if k != key}):
        raise TransferRefused("transfer evidence digest invalid")
    return value


def build_fence_publication_preview(preflight: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    """Build an *unpublished* legacy-incompatible successor fence.

    This is a deterministic projection of existing immutable evidence, never a
    way to create authority.  A future publisher must serialize under an
    exclusive process/lease protocol and reread all predecessor identities.
    """
    admission = _sealed(preflight, "preview_sha256")
    state = _sealed(plan, "record_sha256")
    if admission.get("schema") != "stygnox_direct_interruption_successor_admission_preflight_v1":
        raise TransferRefused("unsupported admission preflight")
    if (admission.get("admissible") is not False or admission.get("authority_changed") is not False
        or admission.get("successor_execution_admission") != "DISABLED"
        or admission.get("exclusive_transfer_publication") != "NOT_IMPLEMENTED"
        or admission.get("proposed_successor_only_plan_status") != SUCCESSOR_STATUS
        or admission.get("proposed_legacy_execution_authority_granted") is not False):
        raise TransferRefused("preflight attempts to claim transfer authority")
    if (state.get("schema") != "stygnox_plan_state_v1"
        or state.get("status") != "APPROVED"
        or state.get("execution_authority_granted") is not True
        or state.get("active_gate") is not None
        or state.get("self_development_grant") is not None
        or state.get("direct_interruption_pending") is not None
        or state.get("direct_interruption_recoveries")
        or state.get("direct_interruption_transfer_pending")):
        raise TransferRefused("predecessor is not an eligible unmodified approved checkpoint")
    expected = (
        ("record_sha256", "predecessor_plan_record_sha256"),
        ("plan_hash", "plan_hash"),
        ("transaction_id", "transaction_id"),
        ("operator", "operator"),
        ("current_step", "current_step"),
        ("controller_record_sha256", "predecessor_controller_record_sha256"),
        ("transaction_record_sha256", "predecessor_transaction_record_sha256"),
    )
    if any(state.get(k) != admission.get(other) for k, other in expected):
        raise TransferRefused("admission is not bound to exact live predecessor")
    for key in ("handoff_preview_sha256", "fence_design_sha256", "review_preview_sha256",
                "manifest_proof_sha256", "predecessor_plan_record_sha256",
                "predecessor_controller_record_sha256", "predecessor_transaction_record_sha256"):
        if not _hash_ok(admission.get(key)):
            raise TransferRefused(f"invalid {key} in admission evidence")
    candidate = admission.get("successor_installed_identity")
    wheel = admission.get("successor_wheel_identity")
    predecessor = admission.get("predecessor_installed_executable")
    if (not isinstance(candidate, Mapping) or not isinstance(wheel, Mapping) or not isinstance(predecessor, Mapping)
        or not _hash_ok(wheel.get("sha256")) or not _hash_ok(predecessor.get("sha256"))
        or not isinstance(candidate.get("executable"), str)
        or not isinstance(predecessor.get("path"), str)
        or candidate["executable"] == predecessor["path"]):
        raise TransferRefused("installed predecessor/successor identities are incomplete")

    # Preserve the *whole* preceding plan, including accepted receipt lineage,
    # original scope and any historical fields. The only changes form a fence.
    blocked = deepcopy(dict(state))
    blocked.pop("record_sha256")
    blocked["status"] = SUCCESSOR_STATUS
    blocked["execution_authority_granted"] = False
    blocked["direct_interruption_transfer_pending"] = {
        "schema": FENCE_SCHEMA,
        "admission_preview_sha256": admission["preview_sha256"],
        "predecessor_plan_record_sha256": state["record_sha256"],
        "predecessor_controller_record_sha256": state["controller_record_sha256"],
        "predecessor_transaction_record_sha256": state["transaction_record_sha256"],
        "successor_executable": candidate["executable"],
        "successor_wheel_sha256": wheel["sha256"],
        "review_preview_sha256": admission["review_preview_sha256"],
        "manifest_proof_sha256": admission["manifest_proof_sha256"],
        "publication_state": "UNPUBLISHED",
        "successor_execution_authorised": False,
    }
    blocked["record_sha256"] = recovery._digest(blocked)
    body = {
        "schema": SCHEMA,
        "predecessor_plan_record_sha256": state["record_sha256"],
        "predecessor_controller_record_sha256": state["controller_record_sha256"],
        "predecessor_transaction_record_sha256": state["transaction_record_sha256"],
        "admission_preview_sha256": admission["preview_sha256"],
        "fenced_plan": blocked,
        "authority_changed": False,
        "exclusive_handoff_proved": False,
        "successor_execution_authorised": False,
        "admissible": False,
        "blockers": [BLOCKER],
    }
    body["preview_sha256"] = recovery._digest(body)
    return body


def classify_publication(preview: Mapping[str, Any], current_plan: Mapping[str, Any]) -> str:
    """Pure crash-boundary check: original, exact fence, or refuse ambiguity.

    This must never silently repair/rewrite evidence or interpret a partial
    authority handoff as a completed one.
    """
    projected = _sealed(preview, "preview_sha256")
    current = _sealed(current_plan, "record_sha256")
    if (projected.get("schema") != SCHEMA or projected.get("admissible") is not False
        or projected.get("exclusive_handoff_proved") is not False
        or projected.get("successor_execution_authorised") is not False):
        raise TransferRefused("invalid/untrusted transfer publication preview")
    fenced = _sealed(projected.get("fenced_plan"), "record_sha256")
    if (fenced.get("status") != SUCCESSOR_STATUS
        or fenced.get("execution_authority_granted") is not False
        or (fenced.get("direct_interruption_transfer_pending") or {}).get("successor_execution_authorised") is not False):
        raise TransferRefused("fence does not block legacy and successor execution")
    if current.get("record_sha256") == projected.get("predecessor_plan_record_sha256"):
        return "PREDECESSOR_UNCHANGED_NO_HANDOFF"
    if current == fenced:
        return "FENCED_EXECUTION_BLOCKED_NO_HANDOFF"
    raise TransferRefused("partial, stale or substituted transfer publication; manual review required")


def require_successor_release_authority() -> None:
    """Separate hard stop: even a future lifted C1 mutation gate cannot regrant legacy authority.

    Replace only after successor admission, crashed-publication recovery, and
    independent installed qualification are all wired to a durable authority
    receipt. A preview, proof hash, or boolean witness is not sufficient.
    """
    raise TransferRefused(BLOCKER)
