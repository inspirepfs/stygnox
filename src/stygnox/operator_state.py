"""Canonical passive operator lifecycle projection.

This module aggregates controller-owned Stygnox evidence for presentation
surfaces.  It never grants authority, mutates runtime state, or repairs invalid
evidence.  Web/TUI/CLI may render this projection but must continue to invoke
explicit authority functions for every action.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, Callable

from . import adoption, finalization, human_control, planning, qualification, scheduler, usage
from .product import PRODUCT

LIFECYCLE_SCHEMA = "stygnox_operator_lifecycle_v1"


def _error(section: str, exc: BaseException) -> dict[str, Any]:
    return {"available": False, "error": str(exc), "section": section}


def _safe(section: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        value = fn()
    except Exception as exc:  # passive projection must expose broken evidence, not hide it
        return _error(section, exc)
    if not isinstance(value, dict):
        return _error(section, RuntimeError("status provider returned non-object evidence"))
    return {"available": True, **value}


def _latest_controller_receipt(root: Path) -> dict[str, Any] | None:
    runtime = root / adoption.RUNTIME_NAME
    if not runtime.is_dir():
        return None
    rows: list[tuple[int, str, dict[str, Any]]] = []
    for path in runtime.glob("controller-run-*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            modified_ns = path.stat().st_mtime_ns
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("schema") == "stygnox_controller_run_result_v1":
            rows.append((modified_ns, path.name, value))
    if not rows:
        return None
    rows.sort(key=lambda item: (item[0], item[1]))
    return rows[-1][2]


def _turn_summary(receipt: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(receipt, Mapping):
        return None
    binding = receipt.get("plan_binding") if isinstance(receipt.get("plan_binding"), Mapping) else {}
    eff = receipt.get("efficiency") if isinstance(receipt.get("efficiency"), Mapping) else {}
    return {
        "record_sha256": receipt.get("record_sha256"),
        "preview_sha256": receipt.get("preview_sha256"),
        "next_action": receipt.get("next_action"),
        "project_changed": bool(receipt.get("project_changed")),
        "plan_hash": binding.get("plan_hash"),
        "step": binding.get("current_step"),
        "efficiency_status": eff.get("status"),
        "efficiency": dict(eff) if eff else None,
    }


def _plan_progress(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        return {
            "status": None,
            "plan_hash": None,
            "repository_authority": None,
            "current_step": None,
            "total_steps": 0,
            "completed_steps": 0,
            "percent_complete": 0,
            "current": None,
            "step_results": [],
        }
    plan = state.get("plan") if isinstance(state.get("plan"), Mapping) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    results = state.get("step_results") if isinstance(state.get("step_results"), list) else []
    current_number = int(state.get("current_step") or 0)
    current = None
    if 1 <= current_number <= len(steps) and isinstance(steps[current_number - 1], Mapping):
        step = steps[current_number - 1]
        current = {
            "id": step.get("id"),
            "title": step.get("title"),
            "objective": step.get("objective"),
            "acceptance": list(step.get("acceptance") or []),
            "test_change_policy": step.get("test_change_policy"),
        }
    counts = Counter(str(item.get("result") or "UNKNOWN") for item in results if isinstance(item, Mapping))
    complete = min(len(results), len(steps))
    return {
        "status": state.get("status"),
        "plan_hash": state.get("plan_hash"),
        "repository_authority": plan.get("repository_authority"),
        "execution_authority_granted": bool(state.get("execution_authority_granted")),
        "current_step": current_number or None,
        "total_steps": len(steps),
        "completed_steps": complete,
        "percent_complete": int((complete * 100) / len(steps)) if steps else 0,
        "current": current,
        "step_results": list(results),
        "result_counts": dict(sorted(counts.items())),
    }


def _reconciliation_summary(attribution: Mapping[str, Any], state: Mapping[str, Any] | None) -> dict[str, Any]:
    categories = attribution.get("categories") if isinstance(attribution.get("categories"), Mapping) else {}
    pending = list(attribution.get("reconciliation_pending_paths") or [])
    stale = []
    block = categories.get("reconciliation_stale") if isinstance(categories.get("reconciliation_stale"), Mapping) else {}
    stale = list(block.get("paths") or [])
    actions = state.get("reconciliation_actions") if isinstance(state, Mapping) and isinstance(state.get("reconciliation_actions"), list) else []
    dispositions = Counter(str(item.get("disposition") or "UNKNOWN") for item in actions if isinstance(item, Mapping))
    return {
        "pending_paths": sorted(str(path) for path in pending),
        "stale_paths": sorted(str(path) for path in stale),
        "requires_human_decision": bool(attribution.get("requires_human_decision")),
        "action_count": len(actions),
        "disposition_counts": dict(sorted(dispositions.items())),
        "error": attribution.get("reconciliation_error"),
    }


def _self_development_summary(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        return {"active_grant": None, "grant_history_count": 0, "expiration_count": 0}
    grant = state.get("self_development_grant") if isinstance(state.get("self_development_grant"), Mapping) else None
    history = state.get("self_development_grant_history") if isinstance(state.get("self_development_grant_history"), list) else []
    expirations = state.get("self_development_expirations") if isinstance(state.get("self_development_expirations"), list) else []
    active = None
    if grant is not None:
        active = {
            "grant_sha256": grant.get("grant_sha256"),
            "gate_id": grant.get("gate_id"),
            "step": grant.get("step"),
            "allowed_paths": list(grant.get("allowed_paths") or []),
            "authority_baseline_sha256": grant.get("authority_baseline_sha256"),
        }
    return {"active_grant": active, "grant_history_count": len(history), "expiration_count": len(expirations)}


def _phase(*, adopted: bool, transaction: Mapping[str, Any] | None, controller_state: Mapping[str, Any] | None, plan_state: Mapping[str, Any] | None) -> str:
    if isinstance(plan_state, Mapping) and plan_state.get("status"):
        return str(plan_state["status"])
    if not adopted:
        return "UNADOPTED"
    if not isinstance(transaction, Mapping):
        return "ADOPTED"
    if transaction.get("state") != "ACTIVE":
        return f"TRANSACTION_{str(transaction.get('state') or 'UNKNOWN').upper()}"
    if not isinstance(controller_state, Mapping) or controller_state.get("enabled") is not True:
        return "TRANSACTION_ACTIVE"
    return "CONTROLLER_READY"


def _blockers(*, lifecycle_errors: list[dict[str, Any]], phase: str, gate: Mapping[str, Any], sched: Mapping[str, Any], recon: Mapping[str, Any], qual: Mapping[str, Any], state: Mapping[str, Any] | None, latest: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in lifecycle_errors:
        rows.append({"code": "INVALID_EVIDENCE", "section": item.get("section"), "detail": item.get("error")})
    if gate.get("open"):
        active = gate.get("gate") if isinstance(gate.get("gate"), Mapping) else {}
        rows.append({"code": "HUMAN_GATE", "gate_id": active.get("gate_id"), "detail": active.get("reason")})
    sched_state = sched.get("scheduler") if isinstance(sched.get("scheduler"), Mapping) else {}
    if str(sched_state.get("status") or "") in {"INTERRUPTED", "TURN_RUNNING"}:
        rows.append({"code": "INTERRUPTED_SCHEDULER", "detail": sched_state.get("stop_reason") or sched_state.get("status")})
    if recon.get("pending_paths") or recon.get("stale_paths"):
        rows.append({"code": "RECONCILIATION_REQUIRED", "pending_paths": list(recon.get("pending_paths") or []), "stale_paths": list(recon.get("stale_paths") or [])})
    if isinstance(state, Mapping) and state.get("last_qualification_failure"):
        rows.append({"code": "QUALIFICATION_FAILED", "detail": state.get("last_qualification_failure")})
    if phase == "READY_TO_COMMIT" and qual.get("available") is True and qual.get("qualified_current_repository") is not True:
        rows.append({"code": "REQUALIFICATION_REQUIRED", "detail": "qualified repository baseline no longer matches current repository"})
    if isinstance(latest, Mapping) and latest.get("efficiency_status") in {"WARN", "RUNAWAY"}:
        rows.append({"code": "EFFICIENCY_REVIEW_REQUIRED", "detail": latest.get("efficiency")})
    return rows


def _actions(*, phase: str, adopted: bool, transaction: Mapping[str, Any] | None, controller_state: Mapping[str, Any] | None, gate: Mapping[str, Any], sched: Mapping[str, Any], recon: Mapping[str, Any], qual: Mapping[str, Any], latest: Mapping[str, Any] | None, blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(row.get("code") == "INVALID_EVIDENCE" for row in blockers):
        return []
    if not adopted:
        return [{"action": "adopt.preview", "reason": "repository has not been adopted"}]
    if not isinstance(transaction, Mapping):
        return [{"action": "transaction.begin", "reason": "adoption exists but no active transaction is recorded"}]
    if transaction.get("state") != "ACTIVE":
        return [{"action": "recovery.preview", "reason": f"transaction state is {transaction.get('state')}"}]
    if not isinstance(controller_state, Mapping) or controller_state.get("enabled") is not True:
        return [{"action": "controller.activate", "reason": "transaction is active but controller authority is inactive"}]
    if phase in {"CONTROLLER_READY", "REJECTED"}:
        return [{"action": "plan.propose-preview", "reason": "no approved execution plan currently governs the repository"}]
    if phase == "AWAITING_APPROVAL":
        return [
            {"action": "plan.approve", "reason": "candidate plan awaits explicit approval"},
            {"action": "plan.reject", "reason": "candidate plan may be explicitly rejected"},
        ]
    if phase == "BLOCKED_HUMAN":
        active = gate.get("gate") if isinstance(gate.get("gate"), Mapping) else {}
        rows = [
            {"action": "gate.steer-preview", "reason": "bounded human direction may retry the exact step"},
            {"action": "gate.resume-preview", "reason": "retry the exact blocked step without new scope"},
        ]
        if active.get("human_resolvable") is True:
            rows.append({"action": "gate.resolve-preview", "reason": "approved step explicitly delegates human-owned acceptance"})
        if str(active.get("kind") or "") == "self-development":
            rows.insert(0, {"action": "self-development.authorize-preview", "reason": "exact Stygnox tooling paths require supervised authority"})
        return rows
    if phase == "APPROVED":
        sched_state = sched.get("scheduler") if isinstance(sched.get("scheduler"), Mapping) else {}
        if str(sched_state.get("status") or "") in {"INTERRUPTED", "TURN_RUNNING"}:
            return [{"action": "scheduler.recover-preview", "reason": "interrupted turn must be reconciled before execution continues"}]
        if recon.get("pending_paths") or recon.get("stale_paths"):
            return [{"action": "reconciliation.inspect", "reason": "carry-forward ownership requires explicit disposition"}]
        if isinstance(latest, Mapping) and latest.get("next_action") == "qualification-required":
            return [{"action": "qualification.preview", "reason": "latest controller turn requires controller-owned qualification"}]
        return [
            {"action": "scheduler.run-preview", "reason": "run bounded approved-plan continuation"},
            {"action": "controller.run-preview", "reason": "run one explicitly reviewed controller turn"},
        ]
    if phase == "STEPS_COMPLETE":
        return [{"action": "qualification.preview", "reason": "all approved steps require terminal qualification"}]
    if phase == "READY_TO_COMMIT":
        if qual.get("available") is True and qual.get("qualified_current_repository") is not True:
            return [{"action": "qualification.requalify-preview", "reason": "repository changed after qualification"}]
        return [
            {"action": "finalization.commit-preview", "reason": "qualified write plan is ready for controlled commit"},
            {"action": "qualification.requalify-preview", "reason": "explicitly refresh final qualification before commit"},
        ]
    if phase == "COMMITTED":
        return [{"action": "finalization.push-preview", "reason": "recorded qualified commit may be pushed after upstream revalidation"}]
    return []


def build_lifecycle_snapshot(
    project: Path,
    *,
    adopted: bool,
    transaction: Mapping[str, Any] | None,
    controller_state: Mapping[str, Any] | None,
    execution_policy: Mapping[str, Any] | None,
    attribution: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one passive lifecycle projection from installed controller evidence."""
    root = adoption.resolve_worktree(project)
    plan_status = _safe("plan", lambda: planning.plan_status(root))
    sched_status = _safe("scheduler", lambda: scheduler.scheduler_status(root))
    gate_status = _safe("human_gate", lambda: human_control.gate_status(root))
    qual_status = _safe("qualification", lambda: qualification.qualification_status(root))
    fin_status = _safe("finalization", lambda: finalization.finalization_status(root))
    usage_status = _safe("usage", lambda: usage.usage_report(root))

    errors = [row for row in (plan_status, sched_status, gate_status, qual_status, fin_status, usage_status) if row.get("available") is False]
    state = plan_status.get("plan") if plan_status.get("available") is True and isinstance(plan_status.get("plan"), Mapping) else None
    latest_receipt = _latest_controller_receipt(root)
    latest = _turn_summary(latest_receipt)
    phase = _phase(adopted=adopted, transaction=transaction, controller_state=controller_state, plan_state=state)
    progress = _plan_progress(state)
    recon = _reconciliation_summary(attribution, state)
    selfdev = _self_development_summary(state)
    gate = gate_status if gate_status.get("available") is True else {"open": False, "gate": None}
    sched = sched_status if sched_status.get("available") is True else {"scheduler": None}
    blockers = _blockers(lifecycle_errors=errors, phase=phase, gate=gate, sched=sched, recon=recon, qual=qual_status, state=state, latest=latest)
    next_actions = _actions(
        phase=phase,
        adopted=adopted,
        transaction=transaction,
        controller_state=controller_state,
        gate=gate,
        sched=sched,
        recon=recon,
        qual=qual_status,
        latest=latest,
        blockers=blockers,
    )
    return {
        "schema": LIFECYCLE_SCHEMA,
        "product_version": PRODUCT.version,
        "phase": phase,
        "attention_required": bool(blockers),
        "blockers": blockers,
        "next_actions": next_actions,
        "progress": progress,
        "plan": plan_status,
        "scheduler": sched_status,
        "human_gate": gate_status,
        "recovery": {
            "transaction_state": transaction.get("state") if isinstance(transaction, Mapping) else None,
            "scheduler_state": (sched.get("scheduler") or {}).get("status") if isinstance(sched.get("scheduler"), Mapping) else None,
            "scheduler_stop_reason": (sched.get("scheduler") or {}).get("stop_reason") if isinstance(sched.get("scheduler"), Mapping) else None,
            "required": any(row.get("code") == "INTERRUPTED_SCHEDULER" for row in blockers) or (isinstance(transaction, Mapping) and transaction.get("state") != "ACTIVE"),
        },
        "reconciliation": recon,
        "self_development": selfdev,
        "qualification": qual_status,
        "finalization": fin_status,
        "efficiency": {
            "mode": execution_policy.get("efficiency_mode") if isinstance(execution_policy, Mapping) else None,
            "latest": latest.get("efficiency") if isinstance(latest, Mapping) else None,
        },
        "usage": usage_status,
        "latest_controller_turn": latest,
    }
