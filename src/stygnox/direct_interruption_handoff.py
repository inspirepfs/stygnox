"""Read-only Stage C recovery-controller compatibility evidence.

The independently installed recovery candidate does not automatically own a live
controller's authority.  In particular the existing R3D.1 executable does not
provide a proved exclusive, recovery-aware fencing protocol.  Therefore this
module deliberately has NO authority-changing API.  It binds the immutable
candidate/predecessor identities for an operator's review and fails closed on
all recovery mutations until a separate, hostile-qualified transfer exists.
"""
from __future__ import annotations

from collections.abc import Sequence
import hashlib
import os
from pathlib import Path
import sys
from typing import Any

from . import adoption, controller, lifecycle, planning, transactions

SCHEMA = "stygnox_direct_interruption_handoff_preview_v1"
BLOCKER = (
    "Stage C installed-authority handoff is not implemented and hostile-qualified: "
    "the predecessor executable has not been proved incapable of resuming "
    "execution under a successor controller"
)


class HandoffRefused(RuntimeError):
    """Read-only compatibility or authority safety check failed."""


def _regular(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise HandoffRefused(f"{label} must be an existing regular non-symlink file")
    if not path.is_absolute():
        raise HandoffRefused(f"{label} must be absolute")
    return path


def _fingerprint(path: Path, label: str) -> dict[str, str]:
    path = _regular(path, label)
    # Hash the exact path, not a PATH lookup or executable name alias.
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require_mutation_authority(project: Path) -> None:
    """Fail-closed until a *verified* old-controller fence and handoff exist.

    Deliberately no environment variable, command-line flag, magic confirmation,
    checksum-only record, or test-mode bypass can authorise this operation.
    Later work must replace this with a verified, exclusive, fresh-process
    transition protocol and corresponding old-executable refusal proof.
    """
    raise HandoffRefused(BLOCKER)


def build_handoff_preview(
    project: Path, origin_file: Path, origin_sha256: str,
    reviewed_paths: Sequence[str], candidate_wheel: Path,
) -> dict[str, Any]:
    """Inspect exact predecessor and candidate; never modify authority state."""
    from . import direct_interruption

    root = adoption.resolve_worktree(project)
    review = direct_interruption.review_preview(root, origin_file, origin_sha256, reviewed_paths)
    state = direct_interruption._checked(planning._record(root))
    active = direct_interruption._checked(controller._controller(root))
    tx = direct_interruption._checked(transactions._transaction(root))

    if (state.get("controller_record_sha256") != active.get("record_sha256")
        or state.get("transaction_record_sha256") != tx.get("record_sha256")
        or state.get("transaction_id") != active.get("transaction_id")
        or state.get("transaction_id") != tx.get("transaction_id")
        or state.get("plan_hash") != review.get("plan_hash")
        or state.get("operator") != review.get("operator")):
        raise HandoffRefused("predecessor runtime authority changed since review")

    commands = [active.get("installed_command"), tx.get("installed_command")]
    if not all(isinstance(c, str) and c and os.path.isabs(c) for c in commands):
        raise HandoffRefused("predecessor has no absolute installed controller command")
    if commands[0] != commands[1]:
        raise HandoffRefused("predecessor transaction/controller installed commands disagree")
    predecessor = _fingerprint(Path(commands[0]), "predecessor installed executable")
    if active.get("rebind_binding") != tx.get("rebind_binding"):
        raise HandoffRefused("predecessor transaction/controller rebind lineage disagrees")

    # Reuse established R3D.1 full wheel, package, RECORD and installed-artifact
    # proof rather than making another weaker Python-distribution validator.
    try:
        candidate = lifecycle._installed_identity(root)
        wheel = lifecycle._wheel_identity(candidate_wheel, candidate)
    except (lifecycle.LifecycleError, adoption.AdoptionError) as exc:
        raise HandoffRefused(f"installed recovery candidate verification failed: {exc}") from exc
    invocation = Path(sys.argv[0]).resolve()
    if invocation != Path(candidate["executable"]).resolve():
        raise HandoffRefused("invoking process is not the exact candidate installed launcher")
    if candidate["executable"] == predecessor["path"]:
        raise HandoffRefused("candidate and predecessor must be different installed executables")

    body: dict[str, Any] = {
        "schema": SCHEMA,
        "worktree": str(root),
        "operator": state["operator"],
        "plan_hash": state["plan_hash"],
        "transaction_id": state["transaction_id"],
        "step": state["current_step"],
        "predecessor_plan_record_sha256": state["record_sha256"],
        "predecessor_controller_record_sha256": active["record_sha256"],
        "predecessor_transaction_record_sha256": tx["record_sha256"],
        "predecessor_installed_executable": predecessor,
        "review_preview_sha256": review["preview_sha256"],
        "manifest_proof_sha256": review["manifest_proof"]["proof_sha256"],
        "candidate_installed_identity": candidate,
        "candidate_wheel_identity": wheel,
        "origin_preview_sha256": origin_sha256,
        "authority_changed": False,
        "candidate_is_authorised_successor": False,
        "fresh_process_authority_transfer_proved": False,
        "old_controller_fencing_proved": False,
        "blockers": [BLOCKER],
        "admissible": False,
    }
    body["preview_sha256"] = direct_interruption._digest(body)
    return body
