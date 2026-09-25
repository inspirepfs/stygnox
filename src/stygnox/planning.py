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

from . import adoption, controller, provider_codex, usage
from .product import PRODUCT


PLAN_MIN_STEPS_DEFAULT = 5
PLAN_MAX_STEPS_DEFAULT = 10
PLAN_MAX_STEPS_LIMIT = 20
PLAN_RECORD = "plan.json"
PLAN_SCHEMA = "stygnox_plan_state_v1"
PLAN_PROPOSAL_PREVIEW_SCHEMA = "stygnox_plan_proposal_preview_v1"
PLAN_REJECTION_SCHEMA = "stygnox_plan_rejection_v1"
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
    },
    "required": ["id", "title", "objective", "acceptance", "test_change_policy"],
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


def _validate_plan(plan: object) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise PlanningError("plan must be an object")
    goal = plan.get("goal")
    planning = plan.get("planning")
    authority = plan.get("repository_authority")
    steps = plan.get("steps")
    if not isinstance(goal, str) or not goal.strip():
        raise PlanningError("plan goal must be a non-empty string")
    if not isinstance(planning, Mapping):
        raise PlanningError("plan planning bounds are missing")
    minimum, maximum = proposal_step_bounds(planning.get("min_steps"), planning.get("max_steps"))
    if authority not in _AUTHORITIES:
        raise PlanningError("plan is missing controller-injected repository authority")
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
        "required": ["steps", "files_inspected"],
    }


def _planning_prompt(goal: str, minimum: int, maximum: int) -> str:
    return (
        "You are the read-only planning worker invoked by the installed Stygnox controller. "
        "The operator goal, planning bounds, repository authority, approval, and execution authority are controller-owned. "
        "Inspect the repository read-only and return only the requested structured plan proposal. "
        f"Return between {minimum} and {maximum} ordered, concrete implementation steps. "
        "Keep steps small enough to implement and qualify independently. "
        "For each step choose test_change_policy none, add-only, or modify; prefer add-only unless existing tests genuinely require modification. "
        "Do not execute implementation work and do not modify the repository. "
        "Report every repository file inspected in files_inspected.\n\n"
        f"Operator goal:\n{goal}\n"
    )


def build_proposal_preview(
    project: Path,
    operator: str,
    goal: str,
    repository_authority: str,
    *,
    min_steps: int | None = None,
    max_steps: int | None = None,
) -> dict[str, Any]:
    root, active, tx, policy_status, name = _active_context(project, operator)
    existing = _record(root, required=False)
    if existing and existing.get("status") in {"AWAITING_APPROVAL", "APPROVED", "BLOCKED_HUMAN", "STEPS_COMPLETE"}:
        raise PlanningError(f"cannot propose while plan status={existing.get('status')}; reject/complete the active plan first")
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
        "goal": _goal(goal),
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
    goal: str,
    repository_authority: str,
    preview_sha256: str,
    confirmation: str,
    *,
    min_steps: int | None = None,
    max_steps: int | None = None,
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
    )
    if preview["preview_sha256"] != expected:
        raise PlanningError("plan proposal preview is stale; authority, policy, goal, bounds, or project baseline changed")
    root = Path(preview["worktree"])
    minimum = int(preview["planning"]["min_steps"])
    maximum = int(preview["planning"]["max_steps"])
    try:
        provider = provider_codex.execute_structured(
            cwd=root,
            prompt=_planning_prompt(str(preview["goal"]), minimum, maximum),
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
    metrics = dict(provider.get("metrics") or {})
    metrics["files_inspected"] = len(raw_files)
    provider_result = {**provider, "metrics": metrics}
    steps = payload.get("steps")
    plan = _validate_plan({
        "goal": preview["goal"],
        "planning": dict(preview["planning"]),
        "steps": steps,
        "repository_authority": preview["repository_authority"],
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
    state: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "product_version": PRODUCT.version,
        "status": "AWAITING_APPROVAL",
        "operator": preview["operator"],
        "transaction_id": preview["transaction_id"],
        "controller_record_sha256": preview["controller_record_sha256"],
        "proposal_preview_sha256": expected,
        "proposal_baseline_sha256": preview["project_baseline"]["sha256"],
        "tracked_config_sha256": preview["tracked_config_sha256"],
        "review_sha256": preview["review_sha256"],
        "plan_hash": digest,
        "plan": plan,
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
        "step_resume": None,
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
        raise PlanningError("all approved plan steps are complete; qualification is required before further controller execution")
    if state.get("status") != "APPROVED":
        raise PlanningError(f"unsupported active plan status for execution: {state.get('status')!r}")
    if state.get("execution_authority_granted") is not True:
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
    resume = state.get("step_resume") if isinstance(state.get("step_resume"), Mapping) and int(state.get("step_resume", {}).get("step") or 0) == step_number else None
    return {
        "schema": "stygnox_approved_step_context_v1",
        "plan_hash": expected_hash,
        "plan_record_sha256": state["record_sha256"],
        "current_step": step_number,
        "total_steps": len(steps),
        "step": step,
        "repository_authority": plan["repository_authority"],
        "approval_baseline_sha256": state["approval_baseline_sha256"],
        "step_authority_baseline_sha256": authority_baseline,
        "human_direction": (resume or {}).get("direction"),
        "resume_reason": (resume or {}).get("reason"),
        "allowed_new_tests": list((resume or {}).get("allowed_new_tests") or []),
        "resumed_from_gate": (resume or {}).get("gate_id"),
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
        command.add_argument("--goal", required=True)
        command.add_argument("--repository-authority", required=True, choices=sorted(_AUTHORITIES))
        command.add_argument("--min-steps", type=int, default=PLAN_MIN_STEPS_DEFAULT)
        command.add_argument("--max-steps", type=int, default=PLAN_MAX_STEPS_DEFAULT)

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
                min_steps=args.min_steps, max_steps=args.max_steps,
            )
        elif args.action == "propose":
            result = propose_plan(
                args.project, args.operator, args.goal, args.repository_authority,
                args.preview, args.confirm,
                min_steps=args.min_steps, max_steps=args.max_steps,
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
