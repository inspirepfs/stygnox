"""Fail-closed, read-only verification of separately reviewed failed-turn source.

A reviewed recovery is NEVER an accepted controller receipt.  This module
validates immutable human-approval/quarantine/test/release evidence and replays
its manifest delta as a distinct edge in the approved-plan provenance chain.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import re
from typing import Any

from . import adoption, direct_interruption_replay as replay

HEX = re.compile(r"^[a-f0-9]{64}$")
PREFIX = "direct-interruption-"


class AttributionRefused(RuntimeError):
    pass


def read_record(root: Path, name: str, schema: str) -> dict[str, Any]:
    path = root / adoption.RUNTIME_NAME / name
    if path.is_symlink() or not path.is_file():
        raise AttributionRefused(f"missing or unsafe immutable recovery evidence: {name}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        replay.checked(record)
    except (OSError, ValueError, replay.EvidenceRefused) as exc:
        raise AttributionRefused(f"invalid immutable recovery evidence: {name}") from exc
    if record.get("schema") != schema:
        raise AttributionRefused(f"wrong recovery evidence schema: {name}")
    return record


def receipt_loader(root: Path, identifier: str) -> dict[str, Any]:
    """Resolve by exact preview OR exact record digest; reject duplicates/forks."""
    if not isinstance(identifier, str) or not HEX.fullmatch(identifier):
        raise AttributionRefused("invalid accepted receipt identifier")
    directory = root / adoption.RUNTIME_NAME
    matches = []
    for path in directory.glob("controller-run-*.json"):
        if path.is_symlink() or not path.is_file():
            raise AttributionRefused("unsafe controller receipt path")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            replay.checked(record)
        except (OSError, ValueError, replay.EvidenceRefused) as exc:
            raise AttributionRefused("malformed accepted controller receipt") from exc
        if record.get("schema") != "stygnox_controller_run_result_v1":
            raise AttributionRefused("unexpected controller receipt schema")
        origin = record.get("preview_sha256")
        if not isinstance(origin, str) or not HEX.fullmatch(origin) or path.name != f"controller-run-{origin[:16]}.json":
            raise AttributionRefused("controller receipt filename/preview mismatch")
        if identifier in (origin, record.get("record_sha256")):
            matches.append(record)
    if len(matches) != 1:
        raise AttributionRefused("missing or duplicate accepted controller receipt")
    return matches[0]


def prove_review(root: Path, original_plan: Mapping[str, Any], preview: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return replay.verify_reviewed_transition(
            original_plan, preview,
            receipt_loader=lambda identifier: receipt_loader(root, identifier),
        )
    except (replay.EvidenceRefused, KeyError, ValueError) as exc:
        raise AttributionRefused(f"interrupted-source manifest replay refused: {exc}") from exc


def released_recoveries(root: Path, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read and re-prove each published exceptional release, without state writes.

    For B2, multiple sequential recovery releases are not yet qualified: a
    second interruption needs a separately designed multi-epoch replay contract.
    """
    rows = state.get("direct_interruption_recoveries") or []
    if not isinstance(rows, list) or len(rows) > 1:
        raise AttributionRefused("unsupported or malformed reviewed-recovery history")
    if state.get("direct_interruption_pending") is not None:
        raise AttributionRefused("unresolved interrupted-source quarantine")
    verified = []
    for entry in rows:
        if not isinstance(entry, dict):
            raise AttributionRefused("malformed recovery history entry")
        try:
            replay.checked(entry)
        except replay.EvidenceRefused as exc:
            raise AttributionRefused("tampered reviewed-recovery history") from exc
        origin = entry.get("reviewed_origin")
        if not isinstance(origin, str) or not HEX.fullmatch(origin):
            raise AttributionRefused("invalid interrupted provider origin")
        prefix = PREFIX + origin[:16]
        if (root / adoption.RUNTIME_NAME / f"controller-run-{origin[:16]}.json").exists():
            raise AttributionRefused("failed provider origin cannot acquire a controller receipt")
        release = read_record(root, prefix + "-release.json", "stygnox_direct_interruption_release_v1")
        intent = read_record(root, prefix + "-intent.json", "stygnox_direct_interruption_intent_v1")
        previous = read_record(root, prefix + "-predecessor-plan.json", "stygnox_direct_interruption_predecessor_plan_v1")
        qual = read_record(root, prefix + "-qualification.json", "stygnox_direct_interruption_test_evidence_v1")
        original = previous.get("original_plan")
        if not isinstance(original, dict):
            raise AttributionRefused("missing immutable predecessor plan")
        try:
            replay.checked(original)
        except replay.EvidenceRefused as exc:
            raise AttributionRefused("tampered immutable predecessor plan") from exc
        preview = intent.get("review_preview")
        if not isinstance(preview, dict):
            raise AttributionRefused("missing human-reviewed candidate preview")
        try:
            replay.checked(preview, "preview_sha256")
        except replay.EvidenceRefused as exc:
            raise AttributionRefused("tampered reviewed source preview") from exc
        proof = intent.get("manifest_proof")
        if not isinstance(proof, dict):
            raise AttributionRefused("missing Stage B1 full-chain manifest proof")
        if not isinstance(intent.get("human_reason"), str) or not intent["human_reason"].strip():
            raise AttributionRefused("missing explicit operator review rationale")
        if intent.get("operator_review_is_new_authority_not_retroactive_grant") is not True:
            raise AttributionRefused("review incorrectly asserts retrospective provider authority")
        if (release != entry or release.get("reviewed_origin") != origin
            or release.get("provider_pass_fabricated") is not False
            or release.get("retrospective_grant_fabricated") is not False
            or release.get("classification") != "HUMAN_REVIEWED_UNATTRIBUTED_INTERRUPTED_WORK"
            or release.get("intent_record_sha256") != intent["record_sha256"]
            or release.get("qualification_record_sha256") != qual["record_sha256"]
            or release.get("predecessor_plan_record_sha256") != original["record_sha256"]
            or release.get("original_baseline_sha256") != preview.get("predecessor_baseline_sha256")
            or release.get("reviewed_baseline_sha256") != preview.get("candidate_baseline_sha256")
            or original.get("plan_hash") != state.get("plan_hash")
            or original.get("transaction_id") != state.get("transaction_id")
            or original.get("operator") != state.get("operator")
            or original.get("current_step") != preview.get("current_step")
            or preview.get("operator") != state.get("operator")
            or preview.get("worktree") != str(root)
            or preview.get("transaction_id") != state.get("transaction_id")
            or qual.get("intent_record_sha256") != intent["record_sha256"]
            or qual.get("plan_record_sha256") != release.get("quarantined_plan_record_sha256")
            or qual.get("test_files") != list(__import__("stygnox.direct_interruption", fromlist=["QUALIFICATION_FILES"]).QUALIFICATION_FILES)
            or not isinstance(qual.get("test_output_sha256"), str)
            or not HEX.fullmatch(qual["test_output_sha256"])
            or not isinstance(qual.get("test_python"), str)
            or not qual["test_python"].startswith("/")
            or Path(qual["test_python"]).is_relative_to(root)
            or qual.get("candidate_baseline_sha256") != preview.get("candidate_baseline_sha256")
            or qual.get("exit_code") != 0
            or qual.get("origin_preview_sha256") != origin):
            raise AttributionRefused("review/release/qualification/plan bindings do not agree")
        computed = prove_review(root, original, preview)
        if (computed != proof or preview.get("manifest_proof") != proof
            or release.get("manifest_proof_sha256") != proof["proof_sha256"]):
            raise AttributionRefused("reviewed recovery manifest proof substituted or stale")
        # The Stage A review fingerprints the whole Git-dirty worktree, which
        # includes source files from *previously accepted* continuations.
        # The interruption delta is only the predecessor -> candidate change.
        # Do not retrospectively attribute older accepted changes to the
        # failed turn merely because they remain Git-dirty.
        paths = {row["path"] for row in proof["changed_paths"]}
        reviewed_files = preview.get("reviewed_file_sha256")
        if not isinstance(reviewed_files, dict) or not reviewed_files:
            raise AttributionRefused("missing exact Stage A reviewed file fingerprints")
        reviewed_paths = set(reviewed_files) - {"stygnox.toml"}
        predecessor_paths = set(proof["predecessor_manifest"])
        candidate_paths = set(preview.get("candidate_manifest") or {})
        if (not paths.issubset(reviewed_paths)
            or not reviewed_paths.issubset(candidate_paths)
            or any(p not in predecessor_paths and p not in paths for p in reviewed_paths)
            or any(not isinstance(sha, str) or not HEX.fullmatch(sha)
                   for sha in reviewed_files.values())):
            raise AttributionRefused("reviewed file set is not explained by accepted history and the exact interrupted-source delta")
        if proof.get("operator_config_unchanged") is not True:
            raise AttributionRefused("operator-owned configuration was not preserved")
        verified.append({"origin_preview_sha256": origin, "release_record_sha256": release["record_sha256"],
                         "predecessor_manifest_sha256": proof["predecessor_manifest_sha256"],
                         "candidate_manifest_sha256": proof["candidate_manifest_sha256"],
                         "changed_paths": proof["changed_paths"], "manifest_proof_sha256": proof["proof_sha256"],
                         "accepted_controller_receipt_sha256s": proof["accepted_controller_receipt_sha256s"],
                         "preview": preview})
    return verified


def replay_attribution(root: Path, state: Mapping[str, Any], plan: Mapping[str, Any],
                       current_manifest: Mapping[str, str], *, pending_receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Reconstruct the complete approved-plan manifest with a DISTINCT recovery edge.

    Only plan-referenced accepted receipts count. The recovery's predecessor
    proof is rechecked independently against the immutable saved plan before
    this function admits the exceptional edge. No successful receipt is minted.
    """
    reviewed = released_recoveries(root, state)
    if len(reviewed) != 1:
        raise AttributionRefused("exactly one explicitly released reviewed recovery is required")
    recovery = reviewed[0]
    try:
        approval = replay._manifest(state.get("approval_repository_manifest"))
        scope = replay._scope(plan.get("repository_mutation_scope"))
    except replay.EvidenceRefused as exc:
        raise AttributionRefused(str(exc)) from exc
    if plan.get("repository_mutation_scope_sha256") != replay.digest(scope):
        raise AttributionRefused("approved scope integrity mismatch")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise AttributionRefused("approved steps missing")
    try:
        receipts = [(r,delta) for r,delta,_,_ in replay._accepted_receipts(
            state,steps=steps,receipt_loader=lambda identifier: receipt_loader(root,identifier),
            plan_hash=state["plan_hash"],tx=state["transaction_id"],scope=scope,
            recovery_edge=(recovery["accepted_controller_receipt_sha256s"],
                           recovery["preview"]["predecessor_baseline_sha256"],
                           recovery["preview"]["candidate_baseline_sha256"]))]
    except (replay.EvidenceRefused, AttributionRefused) as exc:
        raise AttributionRefused(str(exc)) from exc
    if pending_receipt is not None:
        try:
            replay.checked(dict(pending_receipt))
            delta = replay._receipt_delta(pending_receipt,plan_hash=state["plan_hash"],
                                          tx=state["transaction_id"],scope=scope)
        except replay.EvidenceRefused as exc:
            raise AttributionRefused("invalid pending controller receipt") from exc
        if any(r["record_sha256"] == pending_receipt["record_sha256"] for r,_ in receipts):
            raise AttributionRefused("pending controller receipt duplicates accepted history")
        receipts.append((dict(pending_receipt),delta))

    out = dict(approval)
    applied = set()
    attributed = set()
    controller_paths = set()
    receipt_shas = []
    release_done = False
    latest_baseline=state.get("approval_baseline_sha256")
    # The immutable release specifies *where* its exceptional edge belongs:
    # after its exact accepted-controller receipt prefix, never at the first
    # matching manifest.  No-op turns may share a manifest with later events.
    expected_prefix=recovery["accepted_controller_receipt_sha256s"]
    if not isinstance(expected_prefix,list) or not expected_prefix:
        raise AttributionRefused("reviewed recovery lacks accepted predecessor receipt identities")

    def apply_recovery_if_due() -> None:
        nonlocal out, release_done, latest_baseline
        if release_done or receipt_shas != expected_prefix:
            return
        if replay.digest(out) != recovery["predecessor_manifest_sha256"]:
            raise AttributionRefused("reviewed predecessor manifest does not match exact receipt prefix")
        delta={"before_manifest_sha256":replay.digest(out),
               "after_manifest_sha256":recovery["candidate_manifest_sha256"],
               "paths":recovery["changed_paths"]}
        delta["delta_sha256"]=replay.digest(delta)
        previous_step=recovery["preview"]["current_step"]
        policy=steps[previous_step-1].get("test_change_policy") if type(previous_step) is int and 1 <= previous_step <= len(steps) else None
        if policy not in ("add-only","none"):
            raise AttributionRefused("invalid approval-time recovery step test policy")
        try:
            out=replay._apply(out,delta,set(scope),approval,add_only=policy=="add-only")
        except replay.EvidenceRefused as exc:
            raise AttributionRefused(str(exc)) from exc
        if policy == "none" and any(path["path"].startswith("tests/") for path in delta["paths"]):
            raise AttributionRefused("recovery violated no-test mutation policy")
        attributed.update(row["path"] for row in delta["paths"])
        if latest_baseline != recovery["preview"]["predecessor_baseline_sha256"]:
            raise AttributionRefused("reviewed baseline edge does not match accepted predecessor")
        latest_baseline=recovery["preview"]["candidate_baseline_sha256"]
        release_done=True

    for receipt,delta in receipts:
        apply_recovery_if_due()
        if (isinstance(latest_baseline,str) and HEX.fullmatch(latest_baseline)
            and receipt.get("before_baseline_sha256") != latest_baseline):
            raise AttributionRefused("controller baseline discontinuity after reviewed recovery")
        if not isinstance(receipt.get("after_baseline_sha256"),str) or not HEX.fullmatch(receipt["after_baseline_sha256"]):
            raise AttributionRefused("missing controller post-turn baseline identity")
        binding=receipt.get("plan_binding")
        step=binding.get("current_step") if isinstance(binding,Mapping) else None
        policy=steps[step-1].get("test_change_policy") if type(step) is int and 1 <= step <= len(steps) else None
        if policy not in ("add-only","none"):
            raise AttributionRefused("invalid accepted turn step/test policy")
        try:
            out=replay._apply(out,delta,set(scope),approval,add_only=policy=="add-only")
        except replay.EvidenceRefused as exc:
            raise AttributionRefused(str(exc)) from exc
        if policy == "none" and any(row["path"].startswith("tests/") for row in delta["paths"]):
            raise AttributionRefused("accepted turn violated no-test policy")
        receipt_shas.append(receipt["record_sha256"])
        latest_baseline=receipt["after_baseline_sha256"]
        controller_paths.update(row["path"] for row in delta["paths"])
        attributed.update(row["path"] for row in delta["paths"])
    apply_recovery_if_due()
    if not release_done:
        raise AttributionRefused("reviewed recovery displaced or missing from exact accepted controller lineage")

    if out != dict(current_manifest):
        raise AttributionRefused("reviewed/controller history does not reproduce qualified manifest")
    qualified_paths = {p for p in set(approval) | set(current_manifest)
                       if approval.get(p) != current_manifest.get(p)}
    if attributed != qualified_paths:
        raise AttributionRefused("reviewed/controller mutation paths differ from exact qualified delta")
    return {"accepted_controller_receipts": receipt_shas,
            "accepted_controller_paths": sorted(controller_paths),
            "reviewed_recovery_paths": sorted({r["path"] for r in recovery["changed_paths"]}),
            "attributed_paths": sorted(attributed),
            "reviewed_recovery_evidence": [{
                "origin_preview_sha256": recovery["origin_preview_sha256"],
                "release_record_sha256": recovery["release_record_sha256"],
                "manifest_proof_sha256": recovery["manifest_proof_sha256"],
                "predecessor_manifest_sha256": recovery["predecessor_manifest_sha256"],
                "candidate_manifest_sha256": recovery["candidate_manifest_sha256"],
            }]}
