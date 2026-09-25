"""Installed Stygnox human-gate, bounded steering, resume, and resolution authority.

Human decisions are bound to the exact approved plan, current step, active gate,
transaction/controller/policy authority, and blocked repository baseline.  A
human may steer/retry a blocked step, but may resolve/advance it only when the
approved step explicitly delegates human-owned runtime/operator evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

from . import adoption, planning
from .product import PRODUCT


GATE_SCHEMA = "stygnox_human_gate_v1"
DECISION_PREVIEW_SCHEMA = "stygnox_human_decision_preview_v1"
DECISION_RECEIPT_SCHEMA = "stygnox_human_decision_receipt_v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TEST_PATH = re.compile(r"^tests/.+")
_FORBIDDEN_RESOLUTION_MARKERS = (
    "policy violation",
    "protected path",
    "controller/tooling authority",
    "approved plan file changed",
    "repair attempts",
    "secret",
    "credential",
    "runaway",
)


class HumanControlError(RuntimeError):
    """Fail-closed installed human-control error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: object, *, label: str, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise HumanControlError(f"{label} must be non-empty")
    return text[:limit]


def _normalize_repo_path(value: object) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/") or path == ".." or path.startswith("../") or "/../" in f"/{path}/":
        raise HumanControlError(f"invalid repository-relative path: {value!r}")
    return path


def repository_paths(root: Path) -> set[str]:
    """Return tracked + untracked repository paths before one provider turn."""
    result = adoption._git(root, "ls-files", "-co", "--exclude-standard", "-z")
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def test_policy_violations(
    attribution: Mapping[str, Any],
    policy: str,
    before_paths: Iterable[str],
    allowed_new_tests: Iterable[str] = (),
) -> tuple[list[str], list[str]]:
    """Return (violations, exact-new-test candidates) for the current controller turn."""
    if policy not in {"none", "add-only", "modify"}:
        raise HumanControlError(f"unsupported test_change_policy: {policy!r}")
    changed: set[str] = set()
    for key in ("controller_native_paths", "overlap_unresolved_paths", "removed_preexisting_paths"):
        for raw in attribution.get(key) or []:
            path = _normalize_repo_path(raw)
            if path == "tests" or _TEST_PATH.match(path):
                changed.add(path)
    if policy == "modify":
        return [], []
    before = {_normalize_repo_path(path) for path in before_paths}
    allowed = {_normalize_repo_path(path) for path in allowed_new_tests}
    violations: list[str] = []
    candidates: list[str] = []
    for path in sorted(changed):
        if path in allowed:
            continue
        if policy == "add-only" and path not in before:
            continue
        violations.append(path)
        if path not in before and path.startswith("tests/"):
            candidates.append(path)
    return violations, candidates


def approved_step_delegates_human_gate(step: Mapping[str, Any]) -> bool:
    acceptance = step.get("acceptance") if isinstance(step.get("acceptance"), list) else []
    text = " ".join((str(step.get("objective") or ""), *(str(item) for item in acceptance))).lower()
    return "blocked_human" in text and any(
        marker in text for marker in ("operator", "runtime", "evidence", "human-owned", "human owned")
    )


def provider_block_human_resolvable(step: Mapping[str, Any], summary: str) -> bool:
    text = " ".join(str(summary or "").split())
    if not re.match(r"^BLOCKED_HUMAN\s*:", text, flags=re.IGNORECASE):
        return False
    if not approved_step_delegates_human_gate(step):
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in _FORBIDDEN_RESOLUTION_MARKERS)


def _gate_digest(gate: Mapping[str, Any]) -> str:
    body = dict(gate)
    body.pop("gate_sha256", None)
    return _digest(body)


def _validate_gate_object(gate: object) -> dict[str, Any]:
    if not isinstance(gate, Mapping) or gate.get("schema") != GATE_SCHEMA:
        raise HumanControlError("active human gate is missing or invalid")
    value = dict(gate)
    digest = str(value.get("gate_sha256") or "")
    if not _HEX64.fullmatch(digest) or digest != _gate_digest(value):
        raise HumanControlError("active human gate integrity check failed")
    if not str(value.get("gate_id") or "").startswith("HG-"):
        raise HumanControlError("active human gate ID is invalid")
    return value


def open_gate(
    project: Path,
    operator: str,
    *,
    plan_binding: Mapping[str, Any],
    origin_preview_sha256: str,
    blocked_baseline: Mapping[str, Any],
    kind: str,
    reason: str,
    human_resolvable: bool,
    allowed_new_test_candidates: Iterable[str] = (),
) -> dict[str, Any]:
    """Latch one exact human gate for the currently approved plan step."""
    root, active, tx, policy_status, name = planning._active_context(project, operator)
    state = planning._record(root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise HumanControlError("human gate can open only for an executing approved plan")
    plan = planning._validate_plan(state.get("plan"))
    plan_hash = planning._plan_hash(plan)
    step_no = int(state.get("current_step") or 0)
    if (
        plan_binding.get("plan_hash") != plan_hash
        or int(plan_binding.get("current_step") or 0) != step_no
        or plan_binding.get("plan_record_sha256") != state.get("record_sha256")
    ):
        raise HumanControlError("human gate source is stale for the current approved plan/step")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise HumanControlError("human gate operator/transaction authority changed")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise HumanControlError("controller authority changed before human gate creation")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise HumanControlError("execution policy changed before human gate creation")
    if not _HEX64.fullmatch(str(blocked_baseline.get("sha256") or "")):
        raise HumanControlError("human gate requires exact blocked repository baseline evidence")

    sequence = int(state.get("human_gate_sequence") or 0) + 1
    gate_id = f"HG-{sequence:04d}-{step_no:02d}"
    step = plan["steps"][step_no - 1]
    candidates = sorted({_normalize_repo_path(path) for path in allowed_new_test_candidates})
    gate: dict[str, Any] = {
        "schema": GATE_SCHEMA,
        "gate_id": gate_id,
        "plan_hash": plan_hash,
        "plan_record_sha256_before_gate": state["record_sha256"],
        "step": step_no,
        "step_title": step["title"],
        "test_change_policy": step["test_change_policy"],
        "operator": name,
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "origin_preview_sha256": str(origin_preview_sha256),
        "kind": str(kind),
        "reason": _clean_text(reason, label="gate reason"),
        "blocked_baseline_sha256": blocked_baseline["sha256"],
        "blocked_repository_evidence": dict(blocked_baseline),
        "allowed_new_test_candidates": candidates,
        "human_resolvable": bool(human_resolvable),
        "opened_at": _utc_now(),
    }
    gate["gate_sha256"] = _gate_digest(gate)
    history = list(state.get("human_gate_history") or [])
    updated = dict(state)
    updated.update({
        "status": "BLOCKED_HUMAN",
        "execution_authority_granted": False,
        "active_gate": gate,
        "human_gate_sequence": sequence,
        "human_gate_history": [*history[-49:], {**gate, "state": "OPEN"}],
    })
    written = planning._write(root, updated)
    return {**gate, "plan_record_sha256": written["record_sha256"]}


def gate_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    state = planning._record(root, required=False)
    gate = None
    if state and state.get("status") == "BLOCKED_HUMAN":
        gate = _validate_gate_object(state.get("active_gate"))
    return {
        "schema": "stygnox_human_gate_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "open": gate is not None,
        "gate": gate,
        "plan_status": state.get("status") if state else None,
    }


def _active_gate_context(project: Path, operator: str, plan_hash: str, gate_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], str]:
    root, active, tx, policy_status, name = planning._active_context(project, operator)
    state = planning._record(root)
    assert state is not None
    if state.get("status") != "BLOCKED_HUMAN" or state.get("execution_authority_granted") is not False:
        raise HumanControlError("human decision requires an active BLOCKED_HUMAN plan")
    gate = _validate_gate_object(state.get("active_gate"))
    supplied_hash = str(plan_hash or "").strip().lower()
    if supplied_hash != state.get("plan_hash") or gate.get("plan_hash") != supplied_hash:
        raise HumanControlError("human decision plan hash does not match the blocked approved plan")
    if str(gate_id or "") != gate.get("gate_id"):
        raise HumanControlError(f"human decision gate does not match current gate {gate.get('gate_id')}")
    if state.get("operator") != name or gate.get("operator") != name:
        raise HumanControlError("human decision operator does not match gate authority")
    if state.get("transaction_id") != tx.get("transaction_id") or gate.get("transaction_id") != tx.get("transaction_id"):
        raise HumanControlError("human decision transaction authority changed")
    if state.get("controller_record_sha256") != active.get("record_sha256") or gate.get("controller_record_sha256") != active.get("record_sha256"):
        raise HumanControlError("controller authority changed while human gate was open")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise HumanControlError("execution policy changed while human gate was open")
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") != gate.get("blocked_baseline_sha256"):
        raise HumanControlError("repository changed after human gate opened; gate decision is stale")
    return root, state, gate, current, name


def _decision_preview(
    project: Path,
    operator: str,
    plan_hash: str,
    gate_id: str,
    action: str,
    *,
    direction: str | None = None,
    reason: str | None = None,
    allow_new_tests: Iterable[str] = (),
) -> dict[str, Any]:
    root, state, gate, current, name = _active_gate_context(project, operator, plan_hash, gate_id)
    action = str(action).lower()
    if action not in {"steer", "resume", "resolve"}:
        raise HumanControlError(f"unsupported human decision action: {action}")
    direction_text = _clean_text(direction, label="steering direction") if action == "steer" else None
    reason_text = _clean_text(reason, label=f"{action} reason") if action in {"resume", "resolve"} else None
    allowed: list[str] = []
    if action == "steer":
        candidates = set(gate.get("allowed_new_test_candidates") or [])
        for raw in allow_new_tests:
            path = _normalize_repo_path(raw)
            if not path.startswith("tests/"):
                raise HumanControlError(f"--allow-new-test requires a concrete tests/ path: {path}")
            if gate.get("kind") != "test-policy":
                raise HumanControlError("--allow-new-test is valid only for the current test-policy gate")
            if path not in candidates:
                raise HumanControlError(f"--allow-new-test path is not part of the current policy gate: {path}")
            if path not in allowed:
                allowed.append(path)
    elif list(allow_new_tests):
        raise HumanControlError("--allow-new-test is valid only with steer")

    if action == "resolve":
        if gate.get("human_resolvable") is not True:
            raise HumanControlError("current human gate is not operator-resolvable")
        plan = planning._validate_plan(state.get("plan"))
        step = plan["steps"][int(state["current_step"]) - 1]
        if not approved_step_delegates_human_gate(step):
            raise HumanControlError("approved step does not explicitly delegate human-owned BLOCKED_HUMAN acceptance")
        lowered = str(gate.get("reason") or "").lower()
        if any(marker in lowered for marker in _FORBIDDEN_RESOLUTION_MARKERS):
            raise HumanControlError("current blocker is policy/authority owned and cannot be human-confirmed")

    body: dict[str, Any] = {
        "schema": DECISION_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "action": action,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "current_step": int(state["current_step"]),
        "gate_id": gate["gate_id"],
        "gate_sha256": gate["gate_sha256"],
        "blocked_baseline_sha256": current["sha256"],
        "direction": direction_text,
        "reason": reason_text,
        "allowed_new_tests": allowed,
        "requires_explicit_confirmation": True,
        "confirmation": action.upper(),
    }
    body["preview_sha256"] = _digest(body)
    return body


def build_steer_preview(project: Path, operator: str, plan_hash: str, gate_id: str, direction: str, allow_new_tests: Iterable[str] = ()) -> dict[str, Any]:
    return _decision_preview(project, operator, plan_hash, gate_id, "steer", direction=direction, allow_new_tests=allow_new_tests)


def build_resume_preview(project: Path, operator: str, plan_hash: str, gate_id: str, reason: str) -> dict[str, Any]:
    return _decision_preview(project, operator, plan_hash, gate_id, "resume", reason=reason)


def build_resolve_preview(project: Path, operator: str, plan_hash: str, gate_id: str, reason: str) -> dict[str, Any]:
    return _decision_preview(project, operator, plan_hash, gate_id, "resolve", reason=reason)


def _apply_decision(preview: Mapping[str, Any], supplied_preview: str, confirmation: str) -> dict[str, Any]:
    expected = str(supplied_preview or "").strip().lower()
    if not _HEX64.fullmatch(expected) or expected != preview.get("preview_sha256"):
        raise HumanControlError("human decision preview is stale; gate, authority, baseline, or decision changed")
    required = str(preview["action"]).upper()
    if confirmation != required:
        raise HumanControlError(f"explicit confirmation required: --confirm {required}")
    root = Path(str(preview["worktree"]))
    state = planning._record(root)
    assert state is not None
    gate = _validate_gate_object(state.get("active_gate"))
    action = str(preview["action"])
    now = _utc_now()
    decision = {
        "schema": DECISION_RECEIPT_SCHEMA,
        "product_version": PRODUCT.version,
        "action": action,
        "operator": preview["operator"],
        "plan_hash": preview["plan_hash"],
        "step": preview["current_step"],
        "gate_id": preview["gate_id"],
        "gate_sha256": preview["gate_sha256"],
        "preview_sha256": expected,
        "blocked_baseline_sha256": preview["blocked_baseline_sha256"],
        "direction": preview.get("direction"),
        "reason": preview.get("reason"),
        "allowed_new_tests": list(preview.get("allowed_new_tests") or []),
        "decided_at": now,
    }
    decision["record_sha256"] = _digest(decision)

    updated = dict(state)
    updated["active_gate"] = None
    updated["step_authority_baseline_sha256"] = preview["blocked_baseline_sha256"]
    history = list(updated.get("human_gate_history") or [])
    updated["human_gate_history"] = [*history[-49:], {**gate, "state": action.upper(), "decision_sha256": decision["record_sha256"], "decided_at": now}]

    if action == "steer":
        steering = list(updated.get("human_steering") or [])
        record = {
            "gate_id": preview["gate_id"],
            "plan_hash": preview["plan_hash"],
            "step": preview["current_step"],
            "direction": preview["direction"],
            "allowed_new_tests": list(preview.get("allowed_new_tests") or []),
            "recorded_at": now,
            "decision_sha256": decision["record_sha256"],
        }
        updated["human_steering"] = [*steering[-49:], record]
        updated["step_resume"] = record
        updated["status"] = "APPROVED"
        updated["execution_authority_granted"] = True
        result = "HUMAN_STEERED"
    elif action == "resume":
        resumes = list(updated.get("human_resumes") or [])
        record = {
            "gate_id": preview["gate_id"],
            "plan_hash": preview["plan_hash"],
            "step": preview["current_step"],
            "reason": preview["reason"],
            "recorded_at": now,
            "decision_sha256": decision["record_sha256"],
        }
        updated["human_resumes"] = [*resumes[-49:], record]
        updated["step_resume"] = record
        updated["status"] = "APPROVED"
        updated["execution_authority_granted"] = True
        result = "HUMAN_RESUMED"
    else:
        resolutions = list(updated.get("human_gate_resolutions") or [])
        record = {
            "gate_id": preview["gate_id"],
            "plan_hash": preview["plan_hash"],
            "step": preview["current_step"],
            "reason": preview["reason"],
            "result": "HUMAN_CONFIRMED",
            "resolved_at": now,
            "decision_sha256": decision["record_sha256"],
        }
        updated["human_gate_resolutions"] = [*resolutions[-49:], record]
        updated["step_resume"] = None
        plan = planning._validate_plan(updated.get("plan"))
        next_step = int(preview["current_step"]) + 1
        updated["current_step"] = next_step
        if next_step > len(plan["steps"]):
            updated["status"] = "STEPS_COMPLETE"
            updated["execution_authority_granted"] = False
            result = "PLAN_STEPS_COMPLETE_HUMAN_CONFIRMED"
        else:
            updated["status"] = "APPROVED"
            updated["execution_authority_granted"] = True
            result = "HUMAN_CONFIRMED_STEP_ADVANCED"

    written = planning._write(root, updated)
    adoption.write_runtime_record(
        root,
        f"human-decision-{str(preview['gate_id']).lower()}-{action}.json",
        decision,
        actor="controller",
    )
    return {**decision, "result": result, "plan_record_sha256": written["record_sha256"], "plan_status": written["status"], "current_step": written["current_step"]}


def steer(project: Path, operator: str, plan_hash: str, gate_id: str, direction: str, preview_sha256: str, confirmation: str, allow_new_tests: Iterable[str] = ()) -> dict[str, Any]:
    preview = build_steer_preview(project, operator, plan_hash, gate_id, direction, allow_new_tests)
    return _apply_decision(preview, preview_sha256, confirmation)


def resume(project: Path, operator: str, plan_hash: str, gate_id: str, reason: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    preview = build_resume_preview(project, operator, plan_hash, gate_id, reason)
    return _apply_decision(preview, preview_sha256, confirmation)


def resolve(project: Path, operator: str, plan_hash: str, gate_id: str, reason: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    preview = build_resolve_preview(project, operator, plan_hash, gate_id, reason)
    return _apply_decision(preview, preview_sha256, confirmation)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox gate", description="Exact human gate, bounded steering, resume, and human-owned resolution authority.")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status", help="show the currently latched human gate")
    status.add_argument("--project", type=Path, default=Path.cwd())

    def base(command: argparse.ArgumentParser) -> None:
        command.add_argument("plan_hash")
        command.add_argument("--gate", required=True)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--operator", required=True)

    steer_p = sub.add_parser("steer-preview", help="preview bounded human direction for the current blocked step")
    base(steer_p)
    steer_p.add_argument("--direction", required=True)
    steer_p.add_argument("--allow-new-test", action="append", default=[])
    steer_c = sub.add_parser("steer", help="record exact bounded human direction and retry the same step")
    base(steer_c)
    steer_c.add_argument("--direction", required=True)
    steer_c.add_argument("--allow-new-test", action="append", default=[])
    steer_c.add_argument("--preview", required=True)
    steer_c.add_argument("--confirm", required=True)

    for action in ("resume", "resolve"):
        preview = sub.add_parser(f"{action}-preview", help=f"preview exact human {action} authority")
        base(preview)
        preview.add_argument("--reason", required=True)
        command = sub.add_parser(action, help=f"apply exact human {action} authority")
        base(command)
        command.add_argument("--reason", required=True)
        command.add_argument("--preview", required=True)
        command.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = gate_status(args.project)
        elif args.action == "steer-preview":
            result = build_steer_preview(args.project, args.operator, args.plan_hash, args.gate, args.direction, args.allow_new_test)
        elif args.action == "steer":
            result = steer(args.project, args.operator, args.plan_hash, args.gate, args.direction, args.preview, args.confirm, args.allow_new_test)
        elif args.action == "resume-preview":
            result = build_resume_preview(args.project, args.operator, args.plan_hash, args.gate, args.reason)
        elif args.action == "resume":
            result = resume(args.project, args.operator, args.plan_hash, args.gate, args.reason, args.preview, args.confirm)
        elif args.action == "resolve-preview":
            result = build_resolve_preview(args.project, args.operator, args.plan_hash, args.gate, args.reason)
        else:
            result = resolve(args.project, args.operator, args.plan_hash, args.gate, args.reason, args.preview, args.confirm)
    except (HumanControlError, planning.PlanningError, adoption.AdoptionError, OSError, ValueError) as exc:
        print(f"stygnox: gate refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
