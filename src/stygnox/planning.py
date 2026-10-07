"""Installed Stygnox bounded planning and explicit approval lifecycle.

Planning is controller-owned authority evidence. Proposal generation is always
read-only, operator goal/bounds/authority are controller-bound, and a generated
candidate grants no execution authority until an exact human approval.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from . import adoption, controller, provider_codex, provider_usage, usage
from .product import PRODUCT


PLAN_MIN_STEPS_DEFAULT = 5
PLAN_MAX_STEPS_DEFAULT = 10
PLAN_MAX_STEPS_LIMIT = 20
PLAN_RECORD = "plan.json"
PLAN_SCHEMA = "stygnox_plan_state_v1"
PLAN_PROPOSAL_PREVIEW_SCHEMA = "stygnox_plan_proposal_preview_v1"
PLAN_REJECTION_SCHEMA = "stygnox_plan_rejection_v1"
REPOSITORY_MUTATION_SCOPE_FIELD = "repository_mutation_scope"
REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD = "repository_mutation_scope_sha256"
POST_QUALIFICATION_TRANSITION_FIELD = "required_post_qualification_transition"
INSTALLED_SUCCESSOR_HANDOFF = "installed-successor-handoff"
CURRENT_STEP_REBASE_SCHEMA = "stygnox_current_step_rebase_receipt_v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITIES = {"read-only", "write"}
_TEST_POLICIES = {"none", "add-only", "modify"}

_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "minimum": 1},
        "title": {"type": "string", "minLength": 1},
        "objective": {"type": "string", "minLength": 1},
        "acceptance": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "test_change_policy": {"type": "string", "enum": sorted(_TEST_POLICIES)},
        POST_QUALIFICATION_TRANSITION_FIELD: {
            "type": ["string", "null"],
            "enum": [INSTALLED_SUCCESSOR_HANDOFF, None],
        },
    },
    "required": [
        "id",
        "title",
        "objective",
        "acceptance",
        "test_change_policy",
        POST_QUALIFICATION_TRANSITION_FIELD,
    ],
}


class PlanningError(RuntimeError):
    """Fail-closed installed planning/approval error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def proposal_step_bounds(min_steps: object = None, max_steps: object = None) -> tuple[int, int]:
    try:
        minimum = PLAN_MIN_STEPS_DEFAULT if min_steps is None else int(min_steps)
        maximum = PLAN_MAX_STEPS_DEFAULT if max_steps is None else int(max_steps)
    except (TypeError, ValueError) as exc:
        raise PlanningError("plan step bounds must be integers") from exc
    if minimum < 1:
        raise PlanningError("minimum plan steps must be at least 1")
    if maximum < minimum:
        raise PlanningError("maximum plan steps must be greater than or equal to minimum plan steps")
    if maximum > PLAN_MAX_STEPS_LIMIT:
        raise PlanningError(f"maximum plan steps must not exceed {PLAN_MAX_STEPS_LIMIT}")
    return minimum, maximum


def _goal(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 20_000 or "\x00" in text:
        raise PlanningError("--goal must be 1-20000 characters")
    return text


def _authority(value: str) -> str:
    authority = str(value or "").strip().lower()
    if authority not in _AUTHORITIES:
        raise PlanningError("--repository-authority must be read-only or write")
    return authority


def _plan_hash(plan: Mapping[str, Any]) -> str:
    return _digest(plan)


def _repository_mutation_scope(value: object, authority: object) -> list[str]:
    """Validate immutable native write authority without inferring legacy scope."""
    if not isinstance(value, list):
        raise PlanningError("plan repository_mutation_scope must be an explicit array")
    if authority == "read-only" and value != []:
        raise PlanningError("read-only plans must use an explicit empty repository_mutation_scope")
    if authority == "write" and not value:
        raise PlanningError("write plans require a non-empty repository_mutation_scope")
    normalized: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
            raise PlanningError("repository_mutation_scope paths must be non-empty canonical repository-relative paths")
        path = Path(raw)
        if path.is_absolute() or raw.startswith("/") or raw in {".", ".."} or ".." in path.parts:
            raise PlanningError("repository_mutation_scope paths must be repository-relative without traversal")
        canonical = path.as_posix()
        if canonical != raw or raw.startswith("./") or raw.endswith("/"):
            raise PlanningError("repository_mutation_scope paths must be canonical")
        normalized.append(raw)
    if normalized != sorted(normalized) or len(set(normalized)) != len(normalized):
        raise PlanningError("repository_mutation_scope must be sorted and duplicate-free")
    return normalized


def _validate_plan(plan: object) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise PlanningError("plan must be an object")
    goal = plan.get("goal")
    planning = plan.get("planning")
    authority = plan.get("repository_authority")
    scope = plan.get(REPOSITORY_MUTATION_SCOPE_FIELD)
    scope_digest = plan.get(REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD)
    steps = plan.get("steps")
    if not isinstance(goal, str) or not goal.strip():
        raise PlanningError("plan goal must be a non-empty string")
    if not isinstance(planning, Mapping):
        raise PlanningError("plan planning bounds are missing")
    minimum, maximum = proposal_step_bounds(planning.get("min_steps"), planning.get("max_steps"))
    if authority not in _AUTHORITIES:
        raise PlanningError("plan is missing controller-injected repository authority")
    canonical_scope = _repository_mutation_scope(scope, authority)
    if not isinstance(scope_digest, str) or not _HEX64.fullmatch(scope_digest) or scope_digest != _digest(canonical_scope):
        raise PlanningError("plan repository_mutation_scope digest is missing, stale, or mismatched")
    if not isinstance(steps, list) or not minimum <= len(steps) <= maximum:
        raise PlanningError(f"plan must contain {minimum}-{maximum} steps")
    for index, raw in enumerate(steps, 1):
        if not isinstance(raw, Mapping) or raw.get("id") != index:
            raise PlanningError("plan step ids must be sequential starting at 1")
        for key in ("title", "objective"):
            if not isinstance(raw.get(key), str) or not str(raw[key]).strip():
                raise PlanningError(f"step {index} {key} must be non-empty")
        acceptance = raw.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance or not all(isinstance(item, str) and item.strip() for item in acceptance):
            raise PlanningError(f"step {index} acceptance must contain at least one item")
        if raw.get("test_change_policy") not in _TEST_POLICIES:
            raise PlanningError(f"step {index} has invalid test_change_policy")
        transition = raw.get(POST_QUALIFICATION_TRANSITION_FIELD)
        if transition is not None and transition != INSTALLED_SUCCESSOR_HANDOFF:
            raise PlanningError(f"step {index} has an unsupported post-qualification transition")
    return json.loads(json.dumps(dict(plan)))


def _record(root: Path, *, required: bool = True) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / PLAN_RECORD
    if not path.exists():
        if required:
            raise PlanningError("no Stygnox plan state exists")
        return None
    if path.is_symlink() or not path.is_file():
        raise PlanningError("plan runtime record must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningError(f"invalid plan runtime record: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != PLAN_SCHEMA:
        raise PlanningError("unsupported plan runtime schema")
    recorded = str(value.get("record_sha256") or "")
    body = dict(value)
    body.pop("record_sha256", None)
    if not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise PlanningError("plan runtime record integrity check failed")
    if value.get("plan") is not None:
        plan = _validate_plan(value["plan"])
        if value.get("plan_hash") != _plan_hash(plan):
            raise PlanningError("plan runtime record does not match its plan hash")
        if (
            value.get(REPOSITORY_MUTATION_SCOPE_FIELD) != plan[REPOSITORY_MUTATION_SCOPE_FIELD]
            or value.get(REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD) != plan[REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD]
        ):
            raise PlanningError("plan runtime scope evidence is missing, stale, altered, or mismatched")
    return value


def _write(root: Path, body: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(body)
    payload.pop("record_sha256", None)
    payload["record_sha256"] = _digest(payload)
    adoption.write_runtime_record(root, PLAN_RECORD, payload, actor="controller")
    return payload


def _active_context(project: Path, operator: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], str]:
    root = adoption.resolve_worktree(project)
    active = controller._controller(root)
    assert active is not None
    if active.get("enabled") is not True:
        raise PlanningError("planning requires an active installed controller")
    tx = controller._transaction(root)
    name = controller._operator(operator)
    if active.get("operator") != name or tx.get("operator") != name:
        raise PlanningError("planning operator does not match active controller authority")
    if active.get("transaction_id") != tx.get("transaction_id"):
        raise PlanningError("controller activation is stale for the active transaction")
    policy_status = controller._policy_status(root)
    policy = policy_status["policy"]
    if not policy.get("provider") or not policy.get("model") or not policy_status.get("approved"):
        raise PlanningError("planning requires an explicitly reviewed provider/model execution policy")
    if policy.get("provider") != provider_codex.PROVIDER_NAME:
        raise PlanningError(f"unsupported installed planning provider: {policy.get('provider')!r}")
    return root, active, tx, policy_status, name


def _proposal_schema(minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            REPOSITORY_MUTATION_SCOPE_FIELD: {
                "type": "array",
                "maxItems": 256,
                "items": {"type": "string", "minLength": 1},
            },
            "steps": {
                "type": "array",
                "minItems": minimum,
                "maxItems": maximum,
                "items": _STEP_SCHEMA,
            },
            "files_inspected": {
                "type": "array",
                "maxItems": 64,
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": [REPOSITORY_MUTATION_SCOPE_FIELD, "steps", "files_inspected"],
    }


def _planning_prompt(goal: str, minimum: int, maximum: int, retirement_context: Mapping[str, Any] | None = None) -> str:
    carry = ""
    if retirement_context:
        carry = ("\n\nReplacement-plan retirement context (controller-owned evidence; retained paths require explicit reconciliation):\n" + json.dumps(dict(retirement_context), indent=2, sort_keys=True))
    return (
        "You are the read-only planning worker invoked by the installed Stygnox controller. "
        "The operator goal, planning bounds, repository authority, approval, and execution authority are controller-owned. "
        "Inspect the repository read-only and return only the requested structured plan proposal. "
        f"Return between {minimum} and {maximum} ordered, concrete implementation steps. "
        "Keep steps small enough to implement and qualify independently. "
        "For each step choose test_change_policy none, add-only, or modify; prefer add-only unless existing tests genuinely require modification. "
        f"For every step return {POST_QUALIFICATION_TRANSITION_FIELD}; use null unless that step explicitly requires the {INSTALLED_SUCCESSOR_HANDOFF} transition after qualification. "
        "Return repository_mutation_scope as the exact sorted, duplicate-free repository-relative paths this plan may mutate; use [] exactly for read-only authority. "
        "Do not execute implementation work and do not modify the repository. "
        "Replacement retirement lineage is immutable historical evidence only: it grants no provider attribution or execution authority. "
        "CAP-011-classified historical paths must not become ordinary carry-forward ownership. "
        "Report every repository file inspected in files_inspected.\n\n"
        f"Operator goal:\n{goal}\n"
        + carry
    )



def _rejected_replacement_supersession(
    existing: Mapping[str, Any],
    *,
    operator: str,
    transaction: Mapping[str, Any],
    retirement_record_id: str,
) -> dict[str, Any]:
    """Validate a never-authorised rejected replacement before supersession."""
    if existing.get("status") != "REJECTED":
        raise PlanningError("replacement supersession requires REJECTED proposal state")

    if existing.get("execution_authority_granted") is not False:
        raise PlanningError("rejected replacement previously held execution authority")

    if existing.get("operator") != operator or existing.get("transaction_id") != transaction.get("transaction_id"):
        raise PlanningError("rejected replacement operator/transaction authority changed")

    if existing.get("proposal_baseline_sha256") != transaction.get("authority_baseline_sha256"):
        raise PlanningError("rejected replacement authority baseline changed")

    # A proposal eligible for this transition was rejected before approval.
    # Any evidence of approval/execution/qualification makes supersession unsafe.
    forbidden_scalar = (
        "approved_at",
        "approval_baseline_sha256",
        "approval_rollback_snapshot",
        "step_authority_baseline_sha256",
        "qualified_at",
        "final_qualification",
        "active_gate",
    )
    if any(existing.get(key) is not None for key in forbidden_scalar):
        raise PlanningError("rejected replacement contains approval or execution authority evidence")

    forbidden_history = (
        "step_results",
        "continuation_history",
        "qualification_history",
        "human_gate_history",
        "human_gate_resolutions",
        "human_resumes",
        "human_steering",
        "interrupted_recoveries",
        "self_development_grant_history",
        "self_development_expirations",
    )
    if any(existing.get(key) for key in forbidden_history):
        raise PlanningError("rejected replacement contains execution or authority history")

    if int(existing.get("current_step") or 0) != 1:
        raise PlanningError("rejected replacement is not at untouched step 1")

    expected_retirement = str(retirement_record_id or "").strip()
    retirement_manifest_sha256 = str(
        existing.get("retirement_manifest_sha256") or ""
    ).strip().lower()

    if (
        not expected_retirement
        or existing.get("retirement_record_id") != expected_retirement
    ):
        raise PlanningError(
            "rejected replacement retirement lineage does not match --from-retirement"
        )

    if not _HEX64.fullmatch(retirement_manifest_sha256):
        raise PlanningError(
            "rejected replacement retirement manifest identity is missing or malformed"
        )

    retired_history = (
        existing.get("retired_plans")
        if isinstance(existing.get("retired_plans"), list)
        else []
    )
    retirement_matches = [
        dict(row)
        for row in retired_history
        if isinstance(row, Mapping)
        and row.get("record_id") == expected_retirement
    ]

    if len(retirement_matches) != 1:
        raise PlanningError(
            "rejected replacement retirement history is missing or ambiguous"
        )

    retired = retirement_matches[0]
    if (
        retired.get("disposition") != "RETIRED_WITH_CARRY_FORWARD"
        or retired.get("manifest_sha256") != retirement_manifest_sha256
    ):
        raise PlanningError(
            "rejected replacement retirement manifest does not match durable retirement history"
        )

    # Newer proposal records carry the expanded historical-lineage block.
    # Older valid replacement proposals predate it.  In that legacy case the
    # top-level retirement record/manifest binding above is accepted here and
    # latest_carry_forward_retirement() performs the authoritative archive and
    # historical-lineage validation immediately afterwards.
    lineage = existing.get("retirement_historical_lineage")
    if lineage is not None:
        if (
            not isinstance(lineage, Mapping)
            or lineage.get("retirement_record_id") != expected_retirement
            or lineage.get("retirement_manifest_sha256")
                != retirement_manifest_sha256
        ):
            raise PlanningError(
                "rejected replacement expanded retirement lineage is inconsistent"
            )

    plan_hash = str(existing.get("plan_hash") or "").strip().lower()
    plan_record_sha256 = str(existing.get("record_sha256") or "").strip().lower()

    if not _HEX64.fullmatch(plan_hash) or not _HEX64.fullmatch(plan_record_sha256):
        raise PlanningError("rejected replacement evidence identity is malformed")

    rejected_at = str(existing.get("rejected_at") or "").strip()
    rejection_reason = str(existing.get("rejection_reason") or "").strip()
    if not rejected_at or not rejection_reason:
        raise PlanningError("rejected replacement lacks durable rejection evidence")

    record = {
        "plan_hash": plan_hash,
        "plan_record_sha256": plan_record_sha256,
        "rejected_at": rejected_at,
        "rejection_reason": rejection_reason,
        "retirement_record_id": expected_retirement,
        "retirement_manifest_sha256": retirement_manifest_sha256,
        "transaction_id": str(existing["transaction_id"]),
        "operator": operator,
        "execution_authority_granted": False,
    }
    record["record_sha256"] = _digest(record)
    return record


def _legacy_rejection_receipt(
    root: Path,
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    plan_hash = str(existing.get("plan_hash") or "").strip().lower()
    if not _HEX64.fullmatch(plan_hash):
        raise PlanningError(
            "legacy replacement bridge rejection receipt plan identity is malformed"
        )

    path = root / adoption.RUNTIME_NAME / f"plan-rejection-{plan_hash[:16]}.json"
    if path.is_symlink() or not path.is_file():
        raise PlanningError(
            "legacy replacement bridge rejection receipt is missing"
        )

    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningError(
            f"legacy replacement bridge rejection receipt is invalid: {exc}"
        ) from exc

    if not isinstance(receipt, dict) or receipt.get("schema") != PLAN_REJECTION_SCHEMA:
        raise PlanningError(
            "legacy replacement bridge rejection receipt schema is unsupported"
        )

    recorded = str(receipt.get("record_sha256") or "").strip().lower()
    body = dict(receipt)
    body.pop("record_sha256", None)
    if not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise PlanningError(
            "legacy replacement bridge rejection receipt integrity check failed"
        )

    expected = {
        "plan_hash": plan_hash,
        "operator": existing.get("operator"),
        "transaction_id": existing.get("transaction_id"),
        "reason": existing.get("rejection_reason"),
        "rejected_at": existing.get("rejected_at"),
        "execution_authority_granted": False,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise PlanningError(
            "legacy replacement bridge rejection receipt does not match rejected proposal"
        )

    return receipt


LEGACY_REJECTED_REPLACEMENT_BRIDGE_SCHEMA = "stygnox_legacy_rejected_replacement_bridge_v1"


def _legacy_rejected_replacement_bridge(
    root,
    existing: Mapping[str, Any],
    retirement_record_id: str,
) -> dict[str, Any]:
    """Validate the exact predecessor-format retirement/rejection boundary.

    This is intentionally not a migration to modern historical_lineage.
    It proves only facts recorded by the legacy retirement plus the rejected
    replacement that was generated from it.  No execution authority or provider
    attribution is created by this bridge.
    """
    from . import retirement, self_development

    record_id = str(retirement_record_id or "").strip()
    manifest_sha256 = str(
        existing.get("retirement_manifest_sha256") or ""
    ).strip().lower()

    if existing.get("status") != "REJECTED":
        raise PlanningError("legacy replacement bridge requires REJECTED proposal state")
    if existing.get("execution_authority_granted") is not False:
        raise PlanningError("legacy replacement bridge refuses proposal that held execution authority")
    if existing.get("approved_at") is not None:
        raise PlanningError("legacy replacement bridge refuses previously approved proposal")
    if existing.get("retirement_record_id") != record_id:
        raise PlanningError("legacy replacement bridge retirement record mismatch")
    if not _HEX64.fullmatch(manifest_sha256):
        raise PlanningError("legacy replacement bridge manifest identity is malformed")
    if existing.get("retirement_historical_lineage") is not None:
        raise PlanningError("modern retirement lineage must use the modern validator")

    plan = _validate_plan(existing.get("plan"))
    plan_hash = _plan_hash(plan)
    if plan_hash != existing.get("plan_hash"):
        raise PlanningError("legacy replacement bridge rejected-plan identity mismatch")

    recorded_plan_sha = str(existing.get("record_sha256") or "")
    body = dict(existing)
    body.pop("record_sha256", None)
    if (
        not _HEX64.fullmatch(recorded_plan_sha)
        or recorded_plan_sha != _digest(body)
    ):
        raise PlanningError("legacy replacement bridge rejected-plan integrity check failed")

    history = (
        existing.get("retired_plans")
        if isinstance(existing.get("retired_plans"), list)
        else []
    )
    if not history or not isinstance(history[-1], Mapping):
        raise PlanningError("legacy replacement bridge lacks durable retirement history")

    latest = history[-1]
    if (
        latest.get("record_id") != record_id
        or latest.get("manifest_sha256") != manifest_sha256
        or latest.get("disposition") != "RETIRED_WITH_CARRY_FORWARD"
    ):
        raise PlanningError("legacy replacement bridge is not bound to the latest carry-forward retirement")

    manifest = retirement.load_retirement(
        root,
        record_id,
        manifest_sha256,
    )

    if manifest.get("historical_lineage") is not None:
        raise PlanningError("legacy replacement bridge refuses modern retirement manifest")
    if manifest.get("schema") != "stygnox_plan_retirement_v1":
        raise PlanningError("legacy replacement bridge retirement schema is unsupported")
    if (
        manifest.get("record_id") != record_id
        or manifest.get("manifest_sha256") != manifest_sha256
        or manifest.get("disposition") != "RETIRED_WITH_CARRY_FORWARD"
    ):
        raise PlanningError("legacy replacement bridge retirement identity changed")

    rows = manifest.get("paths")
    if not isinstance(rows, list) or not rows:
        raise PlanningError("legacy replacement bridge retirement paths are missing")

    preserved: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping) or raw.get("action") != "preserve":
            continue

        candidate = dict(raw)
        p = str(candidate.get("path") or "").strip()
        source = str(candidate.get("source") or "").strip()
        current = candidate.get("current")
        fingerprint = (
            current.get("fingerprint")
            if isinstance(current, Mapping)
            else None
        )

        if (
            not p
            or p.startswith("/")
            or ".." in Path(p).parts
            or p in preserved
            or not isinstance(fingerprint, str)
            or not _HEX64.fullmatch(fingerprint)
        ):
            raise PlanningError("legacy replacement bridge contains malformed preserved path evidence")

        is_tooling = self_development.is_self_development_path(root, p)

        if source == "controller-native":
            if not is_tooling:
                raise PlanningError(
                    f"legacy replacement bridge has ambiguous controller-native path: {p}"
                )
            classification = "CAP-011-self-development"
        elif source == "adopted-carry-forward":
            if is_tooling:
                raise PlanningError(
                    f"legacy replacement bridge would launder tooling path into ordinary carry-forward: {p}"
                )
            classification = "ordinary-plan-carry-forward"
        else:
            raise PlanningError(
                f"legacy replacement bridge has unsupported preserved source for {p}: {source!r}"
            )

        preserved[p] = {
            "path": p,
            "source": source,
            "approval_presence": candidate.get("approval_presence"),
            "fingerprint": fingerprint,
            "historical_authority_classification": classification,
        }

    if not preserved:
        raise PlanningError("legacy replacement bridge contains no preserved evidence")

    operations = manifest.get("operations")
    op_preserved = (
        operations.get("preserved")
        if isinstance(operations, Mapping)
        else None
    )
    if not isinstance(op_preserved, list):
        raise PlanningError("legacy replacement bridge preserved operations are missing")

    operation_paths = []
    for raw in op_preserved:
        if isinstance(raw, str):
            operation_paths.append(raw)
        elif isinstance(raw, Mapping):
            operation_paths.append(str(raw.get("path") or ""))
        else:
            raise PlanningError("legacy replacement bridge preserved operation is malformed")

    if (
        len(operation_paths) != len(set(operation_paths))
        or set(operation_paths) != set(preserved)
    ):
        raise PlanningError("legacy replacement bridge path/operation evidence disagrees")

    raw_candidates = existing.get("retirement_carry_forward_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise PlanningError("legacy replacement bridge rejected proposal lacks carry-forward candidates")

    rejected_candidates: dict[str, dict[str, Any]] = {}
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            raise PlanningError("legacy replacement bridge candidate is malformed")
        row = dict(raw)
        p = str(row.get("path") or "").strip()

        if not p or p in rejected_candidates:
            raise PlanningError("legacy replacement bridge candidate path is missing or duplicated")

        rejected_candidates[p] = row

    if set(rejected_candidates) != set(preserved):
        missing = sorted(set(preserved) - set(rejected_candidates))
        extra = sorted(set(rejected_candidates) - set(preserved))
        raise PlanningError(
            f"legacy replacement bridge candidate set mismatch; missing={missing} extra={extra}"
        )

    all_bindings: list[dict[str, Any]] = []
    ordinary_candidates: list[dict[str, Any]] = []
    excluded_authority: list[dict[str, Any]] = []

    for p in sorted(preserved):
        source = preserved[p]
        rejected = rejected_candidates[p]

        expected = {
            "path": p,
            "source": source["source"],
            "approval_presence": source["approval_presence"],
            "retirement_fingerprint": source["fingerprint"],
            "retirement_record_id": record_id,
            "retirement_manifest_sha256": manifest_sha256,
        }

        if any(rejected.get(key) != value for key, value in expected.items()):
            raise PlanningError(
                f"legacy replacement bridge candidate evidence changed for {p}"
            )

        binding = {
            **expected,
            "historical_authority_classification":
                source["historical_authority_classification"],
        }
        all_bindings.append(binding)

        if source["historical_authority_classification"] == "ordinary-plan-carry-forward":
            ordinary_candidates.append(dict(expected))
        else:
            excluded_authority.append({
                "path": p,
                "fingerprint": source["fingerprint"],
                "approval_presence": source["approval_presence"],
                "prior_ownership": source["source"],
                "historical_authority_classification": "CAP-011-self-development",
                "classification_basis": "legacy-controller-native+native-tooling-path",
                "retirement_record_id": record_id,
                "retirement_manifest_sha256": manifest_sha256,
            })

    if not ordinary_candidates:
        raise PlanningError("legacy replacement bridge has no ordinary carry-forward candidates")

    rejected_at = str(existing.get("rejected_at") or "").strip()
    rejection_reason = str(existing.get("rejection_reason") or "").strip()
    if not rejected_at or not rejection_reason:
        raise PlanningError("legacy replacement bridge lacks durable rejection evidence")

    rejection_receipt = _legacy_rejection_receipt(root, existing)

    bindings_sha256 = _digest({
        "retirement_record_id": record_id,
        "retirement_manifest_sha256": manifest_sha256,
        "bindings": all_bindings,
    })

    bridge = {
        "schema": LEGACY_REJECTED_REPLACEMENT_BRIDGE_SCHEMA,
        "historical_evidence_only": True,
        "creates_execution_authority": False,
        "creates_provider_attribution": False,
        "modern_historical_lineage_reconstructed": False,
        "retirement_record_id": record_id,
        "retirement_manifest_sha256": manifest_sha256,
        "retired_source_plan_hash": manifest.get("plan_hash"),
        "rejected_replacement_plan_hash": existing.get("plan_hash"),
        "rejected_replacement_record_sha256": recorded_plan_sha,
        "proposal_preview_sha256": existing.get("proposal_preview_sha256"),
        "proposal_baseline_sha256": existing.get("proposal_baseline_sha256"),
        "transaction_id": existing.get("transaction_id"),
        "operator": existing.get("operator"),
        "rejected_at": rejected_at,
        "rejection_reason": rejection_reason,
        "rejection_receipt_record_sha256": rejection_receipt["record_sha256"],
        "preserved_bindings_sha256": bindings_sha256,
        "ordinary_carry_forward_paths": [
            row["path"] for row in ordinary_candidates
        ],
        "historical_authority_paths": [
            row["path"] for row in excluded_authority
        ],
        "preserved_bindings": all_bindings,
    }
    bridge["record_sha256"] = _digest(bridge)

    return {
        "manifest": manifest,
        "evidence": bridge,
        "ordinary_candidates": ordinary_candidates,
        "excluded_historical_authority_paths": excluded_authority,
    }


def _persisted_legacy_replacement_bridge(
    root: Path,
    existing: Mapping[str, Any],
    retirement_record_id: str,
) -> dict[str, Any]:
    """Validate a proposal produced by the one-time legacy bridge.

    Once the predecessor-format retirement/rejection boundary has been bridged,
    later rejected proposals must reuse that immutable bridge evidence instead
    of attempting to reconstruct the original 10-row legacy candidate set.
    """
    from . import retirement, self_development

    bridge = existing.get("retirement_legacy_bridge")
    if not isinstance(bridge, Mapping):
        raise PlanningError("persisted legacy replacement bridge is missing")

    bridge = dict(bridge)
    bridge_record_sha256 = str(bridge.get("record_sha256") or "").strip().lower()
    bridge_body = dict(bridge)
    bridge_body.pop("record_sha256", None)
    if (
        not _HEX64.fullmatch(bridge_record_sha256)
        or bridge_record_sha256 != _digest(bridge_body)
    ):
        raise PlanningError("persisted legacy replacement bridge integrity check failed")

    if bridge.get("schema") != LEGACY_REJECTED_REPLACEMENT_BRIDGE_SCHEMA:
        raise PlanningError("persisted legacy replacement bridge schema is unsupported")
    if bridge.get("historical_evidence_only") is not True:
        raise PlanningError("persisted legacy replacement bridge is not historical evidence only")
    if bridge.get("creates_execution_authority") is not False:
        raise PlanningError("persisted legacy replacement bridge would create execution authority")
    if bridge.get("creates_provider_attribution") is not False:
        raise PlanningError("persisted legacy replacement bridge would create provider attribution")
    if bridge.get("modern_historical_lineage_reconstructed") is not False:
        raise PlanningError("persisted legacy replacement bridge claims reconstructed modern lineage")

    record_id = str(retirement_record_id or "").strip()
    manifest_sha256 = str(existing.get("retirement_manifest_sha256") or "").strip().lower()
    if (
        not record_id
        or existing.get("retirement_record_id") != record_id
        or bridge.get("retirement_record_id") != record_id
    ):
        raise PlanningError("persisted legacy replacement bridge retirement record mismatch")
    if (
        not _HEX64.fullmatch(manifest_sha256)
        or bridge.get("retirement_manifest_sha256") != manifest_sha256
    ):
        raise PlanningError("persisted legacy replacement bridge retirement manifest mismatch")
    if existing.get("retirement_historical_lineage") is not None:
        raise PlanningError("persisted legacy replacement bridge cannot coexist with modern retirement lineage")

    # The current rejected proposal remains a normal integrity-bound plan record.
    plan = _validate_plan(existing.get("plan"))
    if _plan_hash(plan) != existing.get("plan_hash"):
        raise PlanningError("persisted legacy replacement bridge current plan identity mismatch")

    # Its own rejection is independently durable and must match the current plan.
    _legacy_rejection_receipt(root, existing)

    manifest = retirement.load_retirement(root, record_id, manifest_sha256)
    if manifest.get("historical_lineage") is not None:
        raise PlanningError("persisted legacy replacement bridge refuses modern retirement manifest")
    if manifest.get("schema") != "stygnox_plan_retirement_v1":
        raise PlanningError("persisted legacy replacement bridge retirement schema is unsupported")
    if (
        manifest.get("record_id") != record_id
        or manifest.get("manifest_sha256") != manifest_sha256
        or manifest.get("disposition") != "RETIRED_WITH_CARRY_FORWARD"
    ):
        raise PlanningError("persisted legacy replacement bridge retirement identity changed")

    rows = manifest.get("paths")
    if not isinstance(rows, list) or not rows:
        raise PlanningError("persisted legacy replacement bridge retirement paths are missing")

    expected_bindings: list[dict[str, Any]] = []
    ordinary_candidates: list[dict[str, Any]] = []
    excluded_authority: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in rows:
        if not isinstance(raw, Mapping) or raw.get("action") != "preserve":
            continue
        path = str(raw.get("path") or "").strip()
        source = str(raw.get("source") or "").strip()
        current = raw.get("current")
        fingerprint = current.get("fingerprint") if isinstance(current, Mapping) else None
        if (
            not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or path in seen
            or not isinstance(fingerprint, str)
            or not _HEX64.fullmatch(fingerprint)
        ):
            raise PlanningError("persisted legacy replacement bridge contains malformed retirement evidence")
        seen.add(path)

        is_tooling = self_development.is_self_development_path(root, path)
        if source == "controller-native":
            if not is_tooling:
                raise PlanningError(
                    f"persisted legacy replacement bridge has ambiguous controller-native path: {path}"
                )
            classification = "CAP-011-self-development"
        elif source == "adopted-carry-forward":
            if is_tooling:
                raise PlanningError(
                    f"persisted legacy replacement bridge would launder tooling path into ordinary carry-forward: {path}"
                )
            classification = "ordinary-plan-carry-forward"
        else:
            raise PlanningError(
                f"persisted legacy replacement bridge has unsupported preserved source for {path}: {source!r}"
            )

        binding = {
            "path": path,
            "source": source,
            "approval_presence": raw.get("approval_presence"),
            "retirement_fingerprint": fingerprint,
            "retirement_record_id": record_id,
            "retirement_manifest_sha256": manifest_sha256,
            "historical_authority_classification": classification,
        }
        expected_bindings.append(binding)

        if classification == "ordinary-plan-carry-forward":
            ordinary_candidates.append({
                key: binding[key]
                for key in (
                    "path",
                    "source",
                    "approval_presence",
                    "retirement_fingerprint",
                    "retirement_record_id",
                    "retirement_manifest_sha256",
                )
            })
        else:
            excluded_authority.append({
                "path": path,
                "fingerprint": fingerprint,
                "approval_presence": raw.get("approval_presence"),
                "prior_ownership": source,
                "historical_authority_classification": "CAP-011-self-development",
                "classification_basis": "legacy-controller-native+native-tooling-path",
                "retirement_record_id": record_id,
                "retirement_manifest_sha256": manifest_sha256,
            })

    expected_bindings.sort(key=lambda row: row["path"])
    ordinary_candidates.sort(key=lambda row: row["path"])
    excluded_authority.sort(key=lambda row: row["path"])

    recorded_bindings = bridge.get("preserved_bindings")
    if not isinstance(recorded_bindings, list) or recorded_bindings != expected_bindings:
        raise PlanningError("persisted legacy replacement bridge preserved bindings changed")

    expected_bindings_sha256 = _digest({
        "retirement_record_id": record_id,
        "retirement_manifest_sha256": manifest_sha256,
        "bindings": expected_bindings,
    })
    if bridge.get("preserved_bindings_sha256") != expected_bindings_sha256:
        raise PlanningError("persisted legacy replacement bridge binding digest changed")

    if bridge.get("ordinary_carry_forward_paths") != [row["path"] for row in ordinary_candidates]:
        raise PlanningError("persisted legacy replacement bridge ordinary path set changed")
    if bridge.get("historical_authority_paths") != [row["path"] for row in excluded_authority]:
        raise PlanningError("persisted legacy replacement bridge historical authority path set changed")

    current_candidates = existing.get("retirement_carry_forward_candidates")
    if not isinstance(current_candidates, list) or current_candidates != ordinary_candidates:
        raise PlanningError("persisted legacy replacement bridge ordinary candidate bindings changed")

    current_excluded = existing.get("retirement_excluded_historical_authority_paths")
    if not isinstance(current_excluded, list) or current_excluded != excluded_authority:
        raise PlanningError("persisted legacy replacement bridge CAP-011 exclusions changed")

    # Revalidate the original bridged rejection receipt that anchors c188.
    source_plan_hash = str(bridge.get("rejected_replacement_plan_hash") or "").strip().lower()
    source_receipt_sha = str(bridge.get("rejection_receipt_record_sha256") or "").strip().lower()
    if not _HEX64.fullmatch(source_plan_hash) or not _HEX64.fullmatch(source_receipt_sha):
        raise PlanningError("persisted legacy replacement bridge source rejection identity is malformed")
    source_receipt_path = root / adoption.RUNTIME_NAME / f"plan-rejection-{source_plan_hash[:16]}.json"
    if source_receipt_path.is_symlink() or not source_receipt_path.is_file():
        raise PlanningError("persisted legacy replacement bridge source rejection receipt is missing")
    try:
        source_receipt = json.loads(source_receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningError(
            f"persisted legacy replacement bridge source rejection receipt is invalid: {exc}"
        ) from exc
    if not isinstance(source_receipt, dict) or source_receipt.get("schema") != PLAN_REJECTION_SCHEMA:
        raise PlanningError("persisted legacy replacement bridge source rejection receipt schema is unsupported")
    source_body = dict(source_receipt)
    recorded_source_sha = str(source_body.pop("record_sha256", None) or "").strip().lower()
    if (
        not _HEX64.fullmatch(recorded_source_sha)
        or recorded_source_sha != _digest(source_body)
        or recorded_source_sha != source_receipt_sha
    ):
        raise PlanningError("persisted legacy replacement bridge source rejection receipt integrity check failed")
    expected_source_receipt = {
        "plan_hash": source_plan_hash,
        "operator": bridge.get("operator"),
        "transaction_id": bridge.get("transaction_id"),
        "reason": bridge.get("rejection_reason"),
        "rejected_at": bridge.get("rejected_at"),
        "execution_authority_granted": False,
    }
    if any(source_receipt.get(key) != value for key, value in expected_source_receipt.items()):
        raise PlanningError("persisted legacy replacement bridge source rejection receipt changed")

    return {
        "manifest": manifest,
        "evidence": bridge,
        "ordinary_candidates": ordinary_candidates,
        "excluded_historical_authority_paths": excluded_authority,
    }


def build_proposal_preview(
    project: Path,
    operator: str,
    goal: str | None,
    repository_authority: str,
    *,
    min_steps: int | None = None,
    max_steps: int | None = None,
    from_retirement: str | None = None,
) -> dict[str, Any]:
    root, active, tx, policy_status, name = _active_context(project, operator)
    existing = _record(root, required=False)
    if existing and existing.get("status") in {"AWAITING_APPROVAL", "APPROVED", "BLOCKED_HUMAN", "STEPS_COMPLETE", "READY_TO_COMMIT", "COMMITTED", "PUSHED", "READ_ONLY_COMPLETE"}:
        raise PlanningError(f"cannot propose while plan status={existing.get('status')}; reject/complete the active plan first")
    retirement_context = None
    superseded_rejection = None
    goal_value = str(goal or "").strip()

    if existing and not from_retirement:
        if existing.get("status") == "IDLE":
            history = existing.get("retired_plans") if isinstance(existing.get("retired_plans"), list) else []
            latest = history[-1] if history and isinstance(history[-1], Mapping) else {}
            if latest.get("disposition") == "RETIRED_WITH_CARRY_FORWARD":
                raise PlanningError("latest retirement preserved carry-forward work; replacement proposal must use --from-retirement")

        if existing.get("status") == "REJECTED" and existing.get("retirement_record_id"):
            raise PlanningError(
                "rejected replacement preserves retirement lineage; corrected proposal must use --from-retirement"
            )

    if from_retirement:
        from . import retirement
        if not existing or existing.get("status") not in {"IDLE", "REJECTED"}:
            raise PlanningError("replacement proposal requires an IDLE or safely REJECTED retired-plan state")

        if existing.get("status") == "REJECTED":
            superseded_rejection = _rejected_replacement_supersession(
                existing,
                operator=name,
                transaction=tx,
                retirement_record_id=str(from_retirement),
            )
        legacy_bridge = None
        if (
            existing.get("status") == "REJECTED"
            and existing.get("retirement_historical_lineage") is None
        ):
            if existing.get("retirement_legacy_bridge") is not None:
                legacy_bridge = _persisted_legacy_replacement_bridge(
                    root,
                    existing,
                    str(from_retirement),
                )
            else:
                legacy_bridge = _legacy_rejected_replacement_bridge(
                    root,
                    existing,
                    str(from_retirement),
                )

        if legacy_bridge is not None:
            manifest = legacy_bridge["manifest"]

            if not goal_value:
                goal_value = (
                    f"Continue from {manifest['record_id']} to resolve retirement "
                    f"condition: {manifest['reason']}"
                )

            ordinary = legacy_bridge["ordinary_candidates"]
            excluded = legacy_bridge["excluded_historical_authority_paths"]

            retirement_context = {
                "record_id": manifest["record_id"],
                "manifest_sha256": manifest["manifest_sha256"],
                "source_plan_hash": manifest["plan_hash"],
                "reason": manifest["reason"],
                "historical_goal":
                    (manifest.get("planning_context") or {}).get("goal"),
                "preserved_paths": [row["path"] for row in ordinary],
                "historical_evidence_only": True,
                "legacy_rejected_replacement_bridge":
                    legacy_bridge["evidence"],
                "legacy_carry_forward_candidates": ordinary,
                "preserved_path_fingerprints": [
                    {
                        "path": row["path"],
                        "fingerprint": row["retirement_fingerprint"],
                        "approval_presence": row["approval_presence"],
                        "prior_ownership": row["source"],
                        "historical_authority_classification":
                            "ordinary-plan-carry-forward",
                    }
                    for row in ordinary
                ],
                "cap_011_preserved_paths": excluded,
            }

            if superseded_rejection is not None:
                retirement_context["superseded_rejection"] = superseded_rejection

        else:
            try:
                manifest = retirement.latest_carry_forward_retirement(root, existing, str(from_retirement))
            except retirement.RetirementError as exc:
                raise PlanningError(str(exc)) from exc
            lineage = retirement._validate_historical_lineage(manifest)
            paths = list(lineage["preserved_path_fingerprints"])
            ordinary_paths = [row for row in paths if row["historical_authority_classification"] == "ordinary-plan-carry-forward"]
            cap_paths = [row for row in paths if row["historical_authority_classification"] == "CAP-011-self-development"]
            if not goal_value:
                goal_value = f"Continue from {manifest['record_id']} to resolve retirement condition: {manifest['reason']}"
            retirement_context = {
                "record_id": manifest["record_id"],
                "manifest_sha256": manifest["manifest_sha256"],
                "source_plan_hash": manifest["plan_hash"],
                "reason": manifest["reason"],
                "historical_goal": (manifest.get("planning_context") or {}).get("goal"),
                "preserved_paths": [row["path"] for row in ordinary_paths],
                "historical_evidence_only": True,
                "historical_lineage_sha256": lineage["lineage_sha256"],
                "prior_step_qualification_evidence": list((lineage["qualification"] or {}).get("history") or []),
                "reconciliation_history": list((lineage["reconciliation"] or {}).get("actions") or []),
                "cap_011_history": dict(lineage["cap_011"]),
                "preserved_path_fingerprints": ordinary_paths,
                "cap_011_preserved_paths": cap_paths,
                "historical_lineage": lineage,
            }
            if superseded_rejection is not None:
                retirement_context["superseded_rejection"] = superseded_rejection

    minimum, maximum = proposal_step_bounds(min_steps, max_steps)
    authority = _authority(repository_authority)
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") != tx.get("authority_baseline_sha256"):
        raise PlanningError("project changed after transaction begin; planning requires a fresh transaction authority baseline")
    policy = policy_status["policy"]
    body: dict[str, Any] = {
        "schema": PLAN_PROPOSAL_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "project_baseline": current,
        "goal": _goal(goal_value),
        "retirement_context": retirement_context,
        "planning": {"min_steps": minimum, "max_steps": maximum},
        "repository_authority": authority,
        "provider": policy["provider"],
        "model": policy["model"],
        "effort": policy.get("effort"),
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "review_sha256": (policy_status.get("review") or {}).get("review_sha256"),
        "provider_repository_authority": "read-only",
        "execution_authority_granted": False,
        "requires_explicit_confirmation": True,
        "confirmation": "PROPOSE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def propose_plan(
    project: Path,
    operator: str,
    goal: str | None,
    repository_authority: str,
    preview_sha256: str,
    confirmation: str,
    *,
    min_steps: int | None = None,
    max_steps: int | None = None,
    from_retirement: str | None = None,
) -> dict[str, Any]:
    if confirmation != "PROPOSE":
        raise PlanningError("explicit confirmation required: --confirm PROPOSE")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise PlanningError("--preview must be the exact 64-character preview SHA-256")
    preview = build_proposal_preview(
        project,
        operator,
        goal,
        repository_authority,
        min_steps=min_steps,
        max_steps=max_steps,
        from_retirement=from_retirement,
    )
    if preview["preview_sha256"] != expected:
        raise PlanningError("plan proposal preview is stale; authority, policy, goal, bounds, or project baseline changed")
    root = Path(preview["worktree"])
    minimum = int(preview["planning"]["min_steps"])
    maximum = int(preview["planning"]["max_steps"])
    policy_status = controller._policy_status(root)
    controls = policy_status.get("policy") or {}
    try:
        provider_usage.ensure_capacity(
            root,
            plan_state=None,
            model=str(preview["model"]),
            reserve_percent=float(controls.get("reserve_percent", 5.0)),
            wait=bool(controls.get("wait_for_limits", True)),
            poll_seconds=int(controls.get("usage_poll_seconds", 60)),
        )
    except provider_usage.ProviderUsageError as exc:
        raise PlanningError(str(exc)) from exc
    try:
        provider = provider_codex.execute_structured(
            cwd=root,
            prompt=_planning_prompt(str(preview["goal"]), minimum, maximum, preview.get("retirement_context")),
            model=str(preview["model"]),
            effort=preview.get("effort"),
            repository_authority="read-only",
            result_schema=_proposal_schema(minimum, maximum),
        )
    except provider_codex.ProviderError as exc:
        raise PlanningError(str(exc)) from exc
    payload = provider.get("payload")
    if not isinstance(payload, Mapping):
        raise PlanningError("planning provider returned no structured proposal")
    raw_files = payload.get("files_inspected")
    if not isinstance(raw_files, list) or any(not isinstance(item, str) or not item.strip() for item in raw_files):
        raise PlanningError("planning provider returned invalid files_inspected evidence")
    raw_scope = payload.get(REPOSITORY_MUTATION_SCOPE_FIELD)
    canonical_scope = _repository_mutation_scope(raw_scope, preview["repository_authority"])
    metrics = dict(provider.get("metrics") or {})
    metrics["files_inspected"] = len(raw_files)
    provider_result = {**provider, "metrics": metrics}
    steps = payload.get("steps")
    plan = _validate_plan({
        "goal": preview["goal"],
        "planning": dict(preview["planning"]),
        "steps": steps,
        "repository_authority": preview["repository_authority"],
        REPOSITORY_MUTATION_SCOPE_FIELD: canonical_scope,
        REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD: _digest(canonical_scope),
    })
    digest = _plan_hash(plan)
    usage_record = usage.record_provider_turn(
        root,
        evidence_sha256=expected,
        scope="planning-proposal",
        transaction_id=str(preview["transaction_id"]),
        repository_authority="read-only",
        provider_result=provider_result,
    )
    previous = _record(root, required=False)
    retired_history = [dict(row) for row in (previous.get("retired_plans") or []) if isinstance(row, Mapping)] if isinstance(previous, Mapping) else []
    retirement_context = preview.get("retirement_context") if isinstance(preview.get("retirement_context"), Mapping) else None

    superseded_rejection_history = [
        dict(row)
        for row in (previous.get("superseded_rejection_history") or [])
        if isinstance(row, Mapping)
    ] if isinstance(previous, Mapping) else []

    if retirement_context and isinstance(retirement_context.get("superseded_rejection"), Mapping):
        superseded_rejection_history = [
            *superseded_rejection_history[-49:],
            dict(retirement_context["superseded_rejection"]),
        ]

    retirement_candidates: list[dict[str, Any]] = []
    retirement_historical_lineage = None
    retirement_legacy_bridge = None

    if retirement_context:
        bridge_preview = retirement_context.get(
            "legacy_rejected_replacement_bridge"
        )

        if bridge_preview is not None:
            if not isinstance(previous, Mapping) or previous.get("status") != "REJECTED":
                raise PlanningError(
                    "legacy replacement bridge requires the exact rejected predecessor state"
                )

            if previous.get("retirement_legacy_bridge") is not None:
                current_bridge = _persisted_legacy_replacement_bridge(
                    root,
                    previous,
                    str(retirement_context["record_id"]),
                )
            else:
                current_bridge = _legacy_rejected_replacement_bridge(
                    root,
                    previous,
                    str(retirement_context["record_id"]),
                )

            if (
                not isinstance(bridge_preview, Mapping)
                or _digest(bridge_preview)
                    != _digest(current_bridge["evidence"])
            ):
                raise PlanningError(
                    "legacy replacement bridge changed after proposal preview"
                )

            preview_candidates = retirement_context.get(
                "legacy_carry_forward_candidates"
            )
            if (
                not isinstance(preview_candidates, list)
                or _digest(preview_candidates)
                    != _digest(current_bridge["ordinary_candidates"])
            ):
                raise PlanningError(
                    "legacy replacement bridge candidate bindings changed after preview"
                )

            retirement_candidates = [
                dict(row)
                for row in current_bridge["ordinary_candidates"]
            ]
            retirement_legacy_bridge = dict(
                current_bridge["evidence"]
            )

        else:
            from . import retirement
            manifest = retirement.load_retirement(root, str(retirement_context["record_id"]), str(retirement_context["manifest_sha256"]))
            lineage = retirement._validate_historical_lineage(manifest)
            if lineage["lineage_sha256"] != retirement_context.get("historical_lineage_sha256"):
                raise PlanningError("replacement retirement historical lineage changed after proposal preview")
            preview_lineage = retirement_context.get("historical_lineage")
            if not isinstance(preview_lineage, Mapping) or _digest(preview_lineage) != _digest(lineage):
                raise PlanningError("replacement retirement historical evidence changed after proposal preview")
            retirement_historical_lineage = {
                "schema": retirement.HISTORICAL_LINEAGE_SCHEMA,
                "retirement_record_id": manifest["record_id"],
                "retirement_manifest_sha256": manifest["manifest_sha256"],
                "lineage_sha256": lineage["lineage_sha256"],
                "source_plan_hash": lineage["source_plan_hash"],
                "source_plan_record_sha256": lineage["source_plan_record_sha256"],
                "qualification": lineage["qualification"],
                "reconciliation": lineage["reconciliation"],
                "cap_011": lineage["cap_011"],
                "preserved_path_fingerprints": lineage["preserved_path_fingerprints"],
                "historical_evidence_only": True,
            }
            for row in lineage["preserved_path_fingerprints"]:
                if row["historical_authority_classification"] == "ordinary-plan-carry-forward":
                    retirement_candidates.append({
                        "path": row.get("path"),
                        "source": row.get("prior_ownership"),
                        "approval_presence": row.get("approval_presence"),
                        "retirement_fingerprint": row.get("fingerprint"),
                        "retirement_record_id": manifest["record_id"],
                        "retirement_manifest_sha256": manifest["manifest_sha256"],
                        "historical_authority_classification": row["historical_authority_classification"],
                    })
    state: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "product_version": PRODUCT.version,
        "status": "AWAITING_APPROVAL",
        "superseded_rejection_history": superseded_rejection_history,
        "operator": preview["operator"],
        "transaction_id": preview["transaction_id"],
        "transaction_record_sha256": controller._transaction(root)["record_sha256"],
        "controller_record_sha256": preview["controller_record_sha256"],
        "proposal_preview_sha256": expected,
        "proposal_baseline_sha256": preview["project_baseline"]["sha256"],
        "tracked_config_sha256": preview["tracked_config_sha256"],
        "review_sha256": preview["review_sha256"],
        "plan_hash": digest,
        "plan": plan,
        REPOSITORY_MUTATION_SCOPE_FIELD: list(plan[REPOSITORY_MUTATION_SCOPE_FIELD]),
        REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD: plan[REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD],
        "current_step": 1,
        "proposed_at": _utc_now(),
        "approved_at": None,
        "rejected_at": None,
        "approval_baseline_sha256": None,
        "execution_authority_granted": False,
        "usage_record_sha256": usage_record["record_sha256"],
        "step_authority_baseline_sha256": None,
        "human_gate_sequence": 0,
        "active_gate": None,
        "human_gate_history": [],
        "human_steering": [],
        "human_resumes": [],
        "human_gate_resolutions": [],
        "continuation_history": [],
        "interrupted_recoveries": [],
        "reconciliation_actions": [],
        "carry_forward_adopted_paths": [],
        "carry_forward_outside_paths": [],
        "carry_forward_rejected_paths": [],
        "self_development_grant": None,
        "self_development_grant_history": [],
        "self_development_expirations": [],
        "step_results": [],
        "qualification_history": [],
        "last_qualification_failure": None,
        "final_qualification": None,
        "qualified_at": None,
        "step_resume": None,
        "retired_plans": retired_history,
        "retirement_record_id": retirement_context.get("record_id") if retirement_context else None,
        "retirement_manifest_sha256": retirement_context.get("manifest_sha256") if retirement_context else None,
        "retirement_carry_forward_candidates": retirement_candidates,
        "retirement_excluded_historical_authority_paths": list(retirement_context.get("cap_011_preserved_paths") or []) if retirement_context else [],
        "retirement_historical_lineage": retirement_historical_lineage,
        "retirement_legacy_bridge": retirement_legacy_bridge,
        "approval_rollback_snapshot": None,
        "retirement_rollback_preview": None,
    }
    return {**_write(root, state), "result": "PLAN_AWAITING_APPROVAL"}


def plan_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    state = _record(root, required=False)
    return {
        "schema": "stygnox_plan_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "plan": state,
        "execution_authority_granted": bool(state and state.get("status") == "APPROVED" and state.get("execution_authority_granted") is True),
    }


def build_current_step_rebase_preview(project: Path, operator: str, plan_hash: str) -> dict[str, Any]:
    """Preview a narrowly scoped rebase of only the live APPROVED step."""
    root, active, tx, policy_status, name = _active_context(project, operator)
    state = _record(root)
    assert state is not None
    plan = _validate_plan(state.get("plan"))
    expected = _plan_hash(plan)
    if str(plan_hash or "").strip().lower() != expected or state.get("plan_hash") != expected:
        raise PlanningError("current-step rebase plan hash does not match active authority")
    predecessor = controller.current_step_rebase_predecessor(root, state, active, tx)
    body = {
        "schema": "stygnox_current_step_rebase_preview_v1", "operator": name,
        "worktree": str(root), "plan_hash": expected, "plan_record_sha256": state["record_sha256"],
        "current_step": int(state["current_step"]), "transaction_id": tx["transaction_id"],
        "transaction_record_sha256": tx["record_sha256"], "controller_record_sha256": active["record_sha256"],
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "review_sha256": (policy_status.get("review") or {}).get("review_sha256"),
        "predecessor": predecessor, "requires_explicit_confirmation": True,
        "confirmation": "REBASE_CURRENT_STEP",
    }
    body["preview_sha256"] = _digest(body)
    return body


def confirm_current_step_rebase(project: Path, operator: str, plan_hash: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "REBASE_CURRENT_STEP":
        raise PlanningError("explicit confirmation required: --confirm REBASE_CURRENT_STEP")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise PlanningError("current-step rebase preview must be the exact 64-character SHA-256")
    preview = build_current_step_rebase_preview(project, operator, plan_hash)
    if preview["preview_sha256"] != expected:
        raise PlanningError("current-step rebase preview is stale; controller, transaction, plan, or baseline evidence changed")
    root = Path(preview["worktree"])
    state = _record(root)
    assert state is not None
    existing = state.get("current_step_rebase")
    if isinstance(existing, Mapping) and existing.get("predecessor_sha256") == preview["predecessor"].get("predecessor_sha256"):
        raise PlanningError("current-step predecessor was already rebased")
    receipt = {
        "schema": CURRENT_STEP_REBASE_SCHEMA, "plan_hash": preview["plan_hash"],
        "current_step": preview["current_step"], "plan_record_sha256_before": preview["plan_record_sha256"],
        "controller_record_sha256": preview["controller_record_sha256"],
        "transaction_id": preview["transaction_id"], "transaction_record_sha256": preview["transaction_record_sha256"],
        "predecessor": preview["predecessor"], "predecessor_sha256": preview["predecessor"]["predecessor_sha256"],
        "rebased_baseline_sha256": preview["predecessor"]["reconciled_baseline_sha256"],
        "recorded_at": _utc_now(),
    }
    receipt["record_sha256"] = _digest(receipt)
    updated = dict(state)
    updated["step_authority_baseline_sha256"] = receipt["rebased_baseline_sha256"]
    updated["current_step_rebase"] = receipt
    history = [dict(item) for item in state.get("current_step_rebase_history") or [] if isinstance(item, Mapping)]
    updated["current_step_rebase_history"] = [*history[-49:], receipt]
    written = _write(root, updated)
    return {**receipt, "plan_record_sha256": written["record_sha256"], "result": "CURRENT_STEP_REBASED"}


def pending_required_transition(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the one durable transition that must close the current step.

    A qualified step remains the current step until this record is independently
    attested.  Keeping the requirement on the accepted result makes the gate
    survive plan-state rewrites and prevents a later controller turn from
    treating source qualification as authority to advance.
    """
    plan = _validate_plan(state.get("plan"))
    try:
        step_number = int(state.get("current_step") or 0)
    except (TypeError, ValueError) as exc:
        raise PlanningError("approved plan current_step is invalid") from exc
    if step_number < 1 or step_number > len(plan["steps"]):
        raise PlanningError("approved plan current_step is outside the plan bounds")
    if plan["steps"][step_number - 1].get(POST_QUALIFICATION_TRANSITION_FIELD) is None:
        return None
    matches = [
        dict(row) for row in state.get("step_results") or []
        if isinstance(row, Mapping) and int(row.get("step") or 0) == step_number
    ]
    if not matches:
        return None
    if len(matches) != 1 or matches[0].get("result") != "PASS":
        raise PlanningError("required post-qualification transition has invalid accepted-step evidence")
    transition = matches[0].get("post_qualification_transition")
    if not isinstance(transition, Mapping):
        raise PlanningError("accepted step is missing its required post-qualification transition")
    expected = {
        "kind": INSTALLED_SUCCESSOR_HANDOFF,
        "state": "PENDING",
        "plan_hash": state.get("plan_hash"),
        "plan_step": step_number,
        "qualification_binding_sha256": matches[0].get("qualification_binding_sha256"),
        "controller_record_sha256": state.get("controller_record_sha256"),
        "transaction_id": state.get("transaction_id"),
        "transaction_record_sha256": state.get("transaction_record_sha256"),
    }
    if {key: transition.get(key) for key in expected} != expected:
        raise PlanningError("required post-qualification transition is stale or bound to predecessor authority")
    if (
        not isinstance(expected["qualification_binding_sha256"], str)
        or not _HEX64.fullmatch(expected["qualification_binding_sha256"])
        or not isinstance(transition.get("plan_record_sha256"), str)
        or not _HEX64.fullmatch(transition["plan_record_sha256"])
        or not isinstance(expected["transaction_record_sha256"], str)
        or not _HEX64.fullmatch(expected["transaction_record_sha256"])
    ):
        raise PlanningError("required post-qualification transition lacks qualification provenance")
    return dict(transition)


def complete_required_transition(project: Path, operator: str, *, attestation: Mapping[str, Any]) -> dict[str, Any]:
    """Accept an independently attested installed-successor transition.

    This deliberately advances the plan only after the successor transaction
    and controller are live.  The attestation is retained with the accepted
    step rather than inferred from a version number or a lifecycle shortcut.
    """
    root = adoption.resolve_worktree(project)
    state = _record(root)
    assert state is not None
    name = controller._operator(operator)
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not False:
        raise PlanningError("post-qualification transition requires a closed approved step")
    if state.get("operator") != name:
        raise PlanningError("post-qualification transition operator does not match accepted step authority")
    pending = pending_required_transition(state)
    if pending is None:
        raise PlanningError("current approved step has no pending post-qualification transition")
    if not isinstance(attestation, Mapping) or attestation.get("result") != "REBIND_COMPLETED_BY_FRESH_INSTALLED_PROCESS":
        raise PlanningError("post-qualification transition requires a completed installed-successor attestation")
    binding = attestation.get("successor_binding")
    successor_transaction = attestation.get("successor_transaction")
    successor_controller = attestation.get("successor_controller")
    if not isinstance(binding, Mapping) or not isinstance(successor_transaction, Mapping) or not isinstance(successor_controller, Mapping):
        raise PlanningError("post-qualification transition attestation is incomplete")
    if binding.get("required_post_qualification_transition") != pending:
        raise PlanningError("post-qualification transition attestation does not bind the accepted step")
    if binding.get("predecessor_controller_record_sha256") != pending["controller_record_sha256"] or binding.get("predecessor_transaction_record_sha256") != state.get("transaction_record_sha256"):
        raise PlanningError("post-qualification transition attestation is bound to predecessor authority")
    artifact = binding.get("candidate_artifact")
    identity = binding.get("installed_identity")
    epoch = binding.get("new_runtime_epoch")
    if not isinstance(artifact, Mapping) or not _HEX64.fullmatch(str(artifact.get("sha256") or "")) or not isinstance(identity, Mapping) or not isinstance(epoch, int) or epoch < 1:
        raise PlanningError("post-qualification transition lacks exact artifact, identity, or epoch evidence")
    active = controller._controller(root)
    transaction = controller._transaction(root)
    assert active is not None and transaction is not None
    if (
        transaction.get("record_sha256") != successor_transaction.get("record_sha256")
        or active.get("record_sha256") != successor_controller.get("record_sha256")
        or transaction.get("rebind_binding") != binding
        or active.get("rebind_binding") != binding
        or transaction.get("transaction_id") != successor_controller.get("transaction_id")
        or active.get("enabled") is not True
        or active.get("controller_execution_enabled") is not True
    ):
        raise PlanningError("post-qualification transition successor authority is not live")
    for record_name, record in (("successor transaction", transaction), ("successor controller", active)):
        record_body = dict(record)
        record_sha256 = record_body.pop("record_sha256", None)
        if not isinstance(record_sha256, str) or not _HEX64.fullmatch(record_sha256) or record_sha256 != _digest(record_body):
            raise PlanningError(f"post-qualification transition {record_name} integrity check failed")
    receipt_sha256 = attestation.get("record_sha256")
    attestation_body = dict(attestation)
    attestation_body.pop("record_sha256", None)
    if not isinstance(receipt_sha256, str) or not _HEX64.fullmatch(receipt_sha256) or receipt_sha256 != _digest(attestation_body):
        raise PlanningError("post-qualification transition attestation integrity check failed")
    plan = _validate_plan(state.get("plan"))
    step_number = int(state["current_step"])
    results = [dict(row) for row in state.get("step_results") or [] if isinstance(row, Mapping)]
    accepted = next(row for row in results if int(row.get("step") or 0) == step_number)
    completed = dict(pending)
    completed.update({
        "state": "COMPLETE",
        "transition_receipt_sha256": receipt_sha256,
        "artifact": dict(artifact),
        "artifact_sha256": artifact["sha256"],
        "installed_identity": dict(identity),
        "installed_identity_sha256": _digest(identity),
        "runtime_epoch": epoch,
        "successor_transaction_id": transaction["transaction_id"],
        "successor_transaction_record_sha256": transaction["record_sha256"],
        "successor_controller_record_sha256": active["record_sha256"],
        "completed_at": _utc_now(),
    })
    accepted["post_qualification_transition"] = completed
    updated = dict(state)
    updated["step_results"] = [accepted if int(row.get("step") or 0) == step_number else row for row in results]
    updated["current_step"] = step_number + 1
    updated["transaction_id"] = transaction["transaction_id"]
    updated["transaction_record_sha256"] = transaction["record_sha256"]
    updated["controller_record_sha256"] = active["record_sha256"]
    updated["transaction_recovery_baseline_sha256"] = transaction.get("authority_baseline_sha256")
    updated["step_authority_baseline_sha256"] = pending.get("qualified_baseline_sha256")
    updated["execution_authority_granted"] = True
    updated["step_resume"] = None
    history = [dict(row) for row in updated.get("qualification_history") or [] if isinstance(row, Mapping)]
    updated["qualification_history"] = [*history[-99:], {"kind": "post-qualification-transition", "state": "PASS", "step": step_number, "transition_receipt_sha256": receipt_sha256, "completed_at": completed["completed_at"]}]
    return _write(root, updated)


def approved_step_context(project: Path, operator: str) -> dict[str, Any] | None:
    """Return exact current-step authority for an approved plan, or None when no plan governs execution."""
    root = adoption.resolve_worktree(project)
    state = _record(root, required=False)
    if state is None or state.get("status") == "REJECTED":
        return None
    if state.get("status") == "AWAITING_APPROVAL":
        raise PlanningError("plan is awaiting approval; controller execution authority is not granted")
    if state.get("status") == "BLOCKED_HUMAN":
        gate = state.get("active_gate") if isinstance(state.get("active_gate"), Mapping) else {}
        raise PlanningError(f"plan is blocked at human gate {gate.get('gate_id') or "unknown"}; resolve, steer, or resume it before controller execution")
    if state.get("status") == "STEPS_COMPLETE":
        raise PlanningError("all approved plan steps are complete; final qualification is required before further controller execution")
    if state.get("status") == "READY_TO_COMMIT":
        raise PlanningError("plan is READY_TO_COMMIT; controller execution is closed unless requalification invalidates readiness")
    if state.get("status") == "READ_ONLY_COMPLETE":
        raise PlanningError("read-only plan is complete; controller execution is closed")
    if state.get("status") != "APPROVED":
        raise PlanningError(f"unsupported active plan status for execution: {state.get('status')!r}")
    if state.get("execution_authority_granted") is not True:
        if pending_required_transition(state) is not None:
            raise PlanningError("current approved step requires a completed post-qualification transition before later execution")
        raise PlanningError("approved plan does not grant controller execution authority")

    bound_root, active, tx, policy_status, name = _active_context(root, operator)
    if bound_root != root:
        raise PlanningError("approved plan worktree binding changed")
    plan = _validate_plan(state.get("plan"))
    expected_hash = _plan_hash(plan)
    if state.get("plan_hash") != expected_hash:
        raise PlanningError("approved plan hash does not match controller state")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise PlanningError("approved plan authority does not match the active transaction/operator")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise PlanningError("controller authority changed after plan approval")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise PlanningError("execution policy changed after plan approval")
    if state.get("transaction_recovery_baseline_sha256") != tx.get("authority_baseline_sha256"):
        raise PlanningError("transaction recovery authority changed after plan approval")

    current = adoption.capture_baseline(root).public()
    authority_baseline = state.get("step_authority_baseline_sha256") or state.get("approval_baseline_sha256")
    if current.get("sha256") != authority_baseline:
        raise PlanningError("approved step authority baseline changed; qualification, gate decision, or recovery is required before another plan-bound turn")

    try:
        step_number = int(state.get("current_step"))
    except (TypeError, ValueError) as exc:
        raise PlanningError("approved plan current_step is invalid") from exc
    steps = plan["steps"]
    if step_number < 1 or step_number > len(steps):
        raise PlanningError("approved plan current_step is outside the plan bounds")
    step = dict(steps[step_number - 1])
    pending = pending_required_transition(state)
    if pending is not None:
        raise PlanningError("current approved step requires a completed post-qualification transition before later execution")
    resume = state.get("step_resume") if isinstance(state.get("step_resume"), Mapping) and int(state.get("step_resume", {}).get("step") or 0) == step_number else None
    return {
        "schema": "stygnox_approved_step_context_v1",
        "plan_hash": expected_hash,
        "plan_record_sha256": state["record_sha256"],
        "current_step": step_number,
        "total_steps": len(steps),
        "step": step,
        "repository_authority": plan["repository_authority"],
        REPOSITORY_MUTATION_SCOPE_FIELD: list(plan[REPOSITORY_MUTATION_SCOPE_FIELD]),
        REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD: plan[REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD],
        "approval_baseline_sha256": state["approval_baseline_sha256"],
        "step_authority_baseline_sha256": authority_baseline,
        "human_direction": (resume or {}).get("direction"),
        "resume_reason": (resume or {}).get("reason"),
        "allowed_new_tests": list((resume or {}).get("allowed_new_tests") or []),
        "resumed_from_gate": (resume or {}).get("gate_id"),
        "self_development_grant": dict(state.get("self_development_grant")) if isinstance(state.get("self_development_grant"), Mapping) else None,
        "transaction_id": tx["transaction_id"],
    }


def record_same_step_continuation(
    project: Path,
    operator: str,
    *,
    plan_binding: Mapping[str, Any],
    origin_preview_sha256: str,
    before_baseline_sha256: str,
    after_baseline: Mapping[str, Any],
    summary: str,
) -> dict[str, Any]:
    """Advance only the authority baseline for an explicit bounded same-step continuation."""
    root, active, tx, policy_status, name = _active_context(project, operator)
    state = _record(root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise PlanningError("same-step continuation requires an approved executable plan")
    plan = _validate_plan(state.get("plan"))
    expected_hash = _plan_hash(plan)
    step_no = int(state.get("current_step") or 0)
    if (
        plan_binding.get("plan_hash") != expected_hash
        or plan_binding.get("plan_record_sha256") != state.get("record_sha256")
        or int(plan_binding.get("current_step") or 0) != step_no
        or plan_binding.get(REPOSITORY_MUTATION_SCOPE_FIELD) != plan[REPOSITORY_MUTATION_SCOPE_FIELD]
        or plan_binding.get(REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD) != plan[REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD]
    ):
        raise PlanningError("same-step continuation source is stale for the approved plan")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise PlanningError("same-step continuation authority changed")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise PlanningError("controller authority changed before same-step continuation")
    if (
        state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256")
        or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256")
    ):
        raise PlanningError("execution policy changed before same-step continuation")
    authority_before = state.get("step_authority_baseline_sha256") or state.get("approval_baseline_sha256")
    if authority_before != before_baseline_sha256:
        raise PlanningError("same-step continuation baseline does not match current step authority")
    after_sha = str(after_baseline.get("sha256") or "")
    if not _HEX64.fullmatch(after_sha):
        raise PlanningError("same-step continuation requires exact post-turn baseline evidence")
    history = list(state.get("continuation_history") or [])
    record = {
        "plan_hash": expected_hash,
        "step": step_no,
        "origin_preview_sha256": str(origin_preview_sha256),
        "before_baseline_sha256": before_baseline_sha256,
        "after_baseline_sha256": after_sha,
        "summary": " ".join(str(summary or "").split())[:1200],
        "recorded_at": _utc_now(),
    }
    record["record_sha256"] = _digest(record)
    updated = dict(state)
    updated["step_authority_baseline_sha256"] = after_sha
    updated["step_resume"] = None
    updated["continuation_history"] = [*history[-99:], record]
    written = _write(root, updated)
    return {**record, "plan_record_sha256": written["record_sha256"]}


def recover_interrupted_same_step(
    project: Path,
    operator: str,
    *,
    plan_hash: str,
    step: int,
    before_baseline_sha256: str,
    recovered_baseline: Mapping[str, Any],
    pending_paths: list[str],
    scheduler_run_sha256: str,
) -> dict[str, Any]:
    """Preserve exact verified interrupted work and return the same step to APPROVED."""
    root, active, tx, policy_status, name = _active_context(project, operator)
    state = _record(root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise PlanningError("interrupted recovery requires an approved executable plan")
    plan = _validate_plan(state.get("plan"))
    expected_hash = _plan_hash(plan)
    if str(plan_hash) != expected_hash or state.get("plan_hash") != expected_hash:
        raise PlanningError("interrupted recovery plan hash changed")
    if int(state.get("current_step") or 0) != int(step):
        raise PlanningError("interrupted recovery step changed")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise PlanningError("interrupted recovery transaction/operator authority changed")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise PlanningError("controller authority changed before interrupted recovery")
    if (
        state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256")
        or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256")
    ):
        raise PlanningError("execution policy changed before interrupted recovery")
    authority_before = state.get("step_authority_baseline_sha256") or state.get("approval_baseline_sha256")
    if authority_before != before_baseline_sha256:
        raise PlanningError("interrupted recovery baseline no longer matches step authority")
    recovered_sha = str(recovered_baseline.get("sha256") or "")
    if not _HEX64.fullmatch(recovered_sha):
        raise PlanningError("interrupted recovery requires exact repository evidence")
    history = list(state.get("interrupted_recoveries") or [])
    record = {
        "plan_hash": expected_hash,
        "step": int(step),
        "scheduler_run_sha256": str(scheduler_run_sha256),
        "before_baseline_sha256": before_baseline_sha256,
        "recovered_baseline_sha256": recovered_sha,
        "pending_paths": list(pending_paths),
        "recovered_at": _utc_now(),
    }
    record["record_sha256"] = _digest(record)
    updated = dict(state)
    updated["step_authority_baseline_sha256"] = recovered_sha
    existing_resume = state.get("step_resume")
    if isinstance(existing_resume, Mapping) and int(existing_resume.get("step") or 0) == int(step):
        # An interrupted/rolled-back controller attempt does not consume an
        # already-recorded bounded human decision.  Preserve the exact steering
        # or resume provenance for the same step and bind the recovery receipt
        # alongside it.  A completed valid continuation remains responsible for
        # clearing step_resume through record_same_step_continuation().
        resume = dict(existing_resume)
        resume["interrupted_recovery_record_sha256"] = record["record_sha256"]
        resume["interrupted_recovered_at"] = record["recovered_at"]
        updated["step_resume"] = resume
    else:
        updated["step_resume"] = {
            "step": int(step),
            "gate_id": None,
            "reason": "verified interrupted controller work recovered; continue the same approved step",
            "allowed_new_tests": [],
            "recorded_at": record["recovered_at"],
            "decision_sha256": record["record_sha256"],
        }
    updated["interrupted_recoveries"] = [*history[-49:], record]
    written = _write(root, updated)
    return {**record, "plan_record_sha256": written["record_sha256"], "result": "INTERRUPTED_STEP_RECOVERED"}


def recover_pending_provenance_same_step(project: Path, operator: str, *, witness: Mapping[str, Any]) -> dict[str, Any]:
    """Advance only the step checkpoint backed by a controller-created pending witness.

    This has no scheduler input or scheduler record dependency.  Scheduler interruption
    recovery remains a separate mechanism with its own authority and evidence contract.
    """
    root, active, tx, policy_status, name = _active_context(project, operator)
    state = _record(root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise PlanningError("pending provenance recovery requires an approved executable plan")
    value = dict(witness)
    claimed = str(value.pop("witness_sha256", ""))
    if value.get("schema") != "stygnox_pending_provenance_witness_v1" or not _HEX64.fullmatch(claimed) or _digest(value) != claimed:
        raise PlanningError("pending provenance witness is malformed or failed its integrity check")
    plan = _validate_plan(state.get("plan"))
    expected_hash = _plan_hash(plan)
    step = int(state.get("current_step") or 0)
    authority_before = state.get("step_authority_baseline_sha256") or state.get("approval_baseline_sha256")
    if value.get("plan_hash") != expected_hash or value.get("current_step") != step or value.get("repository_mutation_scope") != plan[REPOSITORY_MUTATION_SCOPE_FIELD] or value.get("repository_mutation_scope_sha256") != plan[REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD]:
        raise PlanningError("pending provenance witness plan, step, or scope is stale")
    if value.get("approval_baseline_sha256") != state.get("approval_baseline_sha256") or value.get("step_checkpoint_baseline_sha256") != authority_before or value.get("before_baseline_sha256") != authority_before:
        raise PlanningError("pending provenance witness checkpoint baseline is stale")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id") or state.get("controller_record_sha256") != active.get("record_sha256"):
        raise PlanningError("pending provenance recovery authority changed")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise PlanningError("pending provenance recovery execution policy changed")
    after = str(value.get("after_baseline_sha256") or "")
    if not _HEX64.fullmatch(after) or adoption.capture_baseline(root).public().get("sha256") != after:
        raise PlanningError("pending provenance witness no longer matches the live repository baseline")
    paths = value.get("paths")
    if not isinstance(paths, list) or not paths or len({item.get("path") for item in paths if isinstance(item, Mapping)}) != len(paths):
        raise PlanningError("pending provenance witness paths are malformed")
    history = list(state.get("pending_provenance_witnesses") or [])
    if any(isinstance(item, Mapping) and item.get("controller_receipt_sha256") == value.get("controller_receipt_sha256") for item in history):
        raise PlanningError("pending provenance witness receipt origin was already consumed")
    record = {**value, "witness_sha256": claimed, "recovered_at": _utc_now()}
    updated = dict(state)
    updated["step_authority_baseline_sha256"] = after
    updated["step_resume"] = {
        "step": step, "gate_id": None,
        "reason": "controller-receipt-bound pending provenance recovered; continue the same approved step",
        "allowed_new_tests": [], "recorded_at": record["recovered_at"], "decision_sha256": claimed,
    }
    updated["pending_provenance_witnesses"] = [*history[-49:], record]
    written = _write(root, updated)
    return {**record, "plan_record_sha256": written["record_sha256"], "result": "PENDING_PROVENANCE_RECOVERED"}


def approve_plan(project: Path, operator: str, plan_hash: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "APPROVE":
        raise PlanningError("explicit confirmation required: --confirm APPROVE")
    supplied = str(plan_hash or "").strip().lower()
    if not _HEX64.fullmatch(supplied):
        raise PlanningError("plan hash must be the exact 64-character SHA-256")
    root, active, tx, policy_status, name = _active_context(project, operator)
    state = _record(root)
    assert state is not None
    if state.get("status") != "AWAITING_APPROVAL":
        raise PlanningError("no plan is awaiting approval")
    plan = _validate_plan(state.get("plan"))
    expected = _plan_hash(plan)
    if supplied != expected or state.get("plan_hash") != expected:
        raise PlanningError("approval hash does not match the proposed plan")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise PlanningError("proposal authority does not match the active transaction/operator")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise PlanningError("controller authority changed after proposal; regenerate the plan")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise PlanningError("execution policy changed after proposal; regenerate the plan")
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") != state.get("proposal_baseline_sha256"):
        raise PlanningError("project baseline changed after proposal; regenerate the plan before approval")
    updated = dict(state)
    updated["status"] = "APPROVED"
    updated["approved_at"] = _utc_now()
    updated["approval_baseline_sha256"] = current["sha256"]
    updated["approval_repository_evidence"] = current
    from . import scheduler
    updated["approval_repository_manifest"] = scheduler.repository_manifest(root)
    from . import retirement
    try:
        updated["approval_rollback_snapshot"] = retirement.capture_approval_snapshot(root, expected, updated["approval_repository_manifest"])
    except retirement.RetirementError as exc:
        raise PlanningError(str(exc)) from exc
    updated["transaction_recovery_baseline_sha256"] = tx.get("authority_baseline_sha256")
    updated["step_authority_baseline_sha256"] = current["sha256"]
    updated["execution_authority_granted"] = True
    return {**_write(root, updated), "result": "PLAN_APPROVED"}


def reject_plan(project: Path, operator: str, plan_hash: str, reason: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "REJECT":
        raise PlanningError("explicit confirmation required: --confirm REJECT")
    supplied = str(plan_hash or "").strip().lower()
    if not _HEX64.fullmatch(supplied):
        raise PlanningError("plan hash must be the exact 64-character SHA-256")
    note = " ".join(str(reason or "").split())
    if not note:
        raise PlanningError("plan rejection requires a non-empty --reason")
    root, _active, tx, _policy_status, name = _active_context(project, operator)
    state = _record(root)
    assert state is not None
    if state.get("status") != "AWAITING_APPROVAL":
        raise PlanningError("no plan is awaiting approval")
    plan = _validate_plan(state.get("plan"))
    expected = _plan_hash(plan)
    if supplied != expected or state.get("plan_hash") != expected:
        raise PlanningError("rejection hash does not match the proposed plan")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise PlanningError("proposal authority does not match the active transaction/operator")
    updated = dict(state)
    updated["status"] = "REJECTED"
    updated["rejected_at"] = _utc_now()
    updated["rejection_reason"] = note[:1200]
    updated["execution_authority_granted"] = False
    rejected = _write(root, updated)
    receipt = {
        "schema": PLAN_REJECTION_SCHEMA,
        "product_version": PRODUCT.version,
        "plan_hash": expected,
        "operator": name,
        "transaction_id": tx["transaction_id"],
        "reason": note[:1200],
        "rejected_at": updated["rejected_at"],
        "execution_authority_granted": False,
    }
    receipt["record_sha256"] = _digest(receipt)
    adoption.write_runtime_record(root, f"plan-rejection-{expected[:16]}.json", receipt, actor="controller")
    return {**rejected, "result": "PLAN_REJECTED"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox plan",
        description="Bounded read-only plan proposal and exact human approval/rejection lifecycle.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    status = sub.add_parser("status", help="show current installed plan authority state")
    status.add_argument("--project", type=Path, default=Path.cwd())

    def proposal_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--operator", required=True)
        command.add_argument("--goal")
        command.add_argument("--repository-authority", required=True, choices=sorted(_AUTHORITIES))
        command.add_argument("--min-steps", type=int, default=PLAN_MIN_STEPS_DEFAULT)
        command.add_argument("--max-steps", type=int, default=PLAN_MAX_STEPS_DEFAULT)
        command.add_argument("--from-retirement")

    preview = sub.add_parser("propose-preview", help="preview one exact read-only planning request")
    proposal_args(preview)

    propose = sub.add_parser("propose", help="execute the exact reviewed read-only planning request")
    proposal_args(propose)
    propose.add_argument("--preview", required=True)
    propose.add_argument("--confirm", required=True)

    approve = sub.add_parser("approve", help="approve exactly one pending plan hash")
    approve.add_argument("plan_hash")
    approve.add_argument("--project", type=Path, default=Path.cwd())
    approve.add_argument("--operator", required=True)
    approve.add_argument("--confirm", required=True)

    reject = sub.add_parser("reject", help="reject exactly one pending plan hash without granting execution authority")
    reject.add_argument("plan_hash")
    reject.add_argument("--project", type=Path, default=Path.cwd())
    reject.add_argument("--operator", required=True)
    reject.add_argument("--reason", required=True)
    reject.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = plan_status(args.project)
        elif args.action == "propose-preview":
            result = build_proposal_preview(
                args.project, args.operator, args.goal, args.repository_authority,
                min_steps=args.min_steps, max_steps=args.max_steps, from_retirement=args.from_retirement,
            )
        elif args.action == "propose":
            result = propose_plan(
                args.project, args.operator, args.goal, args.repository_authority,
                args.preview, args.confirm,
                min_steps=args.min_steps, max_steps=args.max_steps, from_retirement=args.from_retirement,
            )
        elif args.action == "approve":
            result = approve_plan(args.project, args.operator, args.plan_hash, args.confirm)
        else:
            result = reject_plan(args.project, args.operator, args.plan_hash, args.reason, args.confirm)
    except (PlanningError, controller.ControllerError, adoption.AdoptionError, OSError, ValueError) as exc:
        print(f"stygnox: plan refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
