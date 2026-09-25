"""Installed carry-forward ownership reconciliation for active approved plans.

Reconciliation turns conservative attribution into explicit, durable ownership
choices.  Inspection is controller-derived and read-only.  Every disposition is
bound to the exact active plan/step, authority records, repository baseline and
candidate fingerprint.  A disposition changes ownership evidence only; it does
not mutate project files or grant self-development authority.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

from . import adoption, planning, scheduler
from .product import PRODUCT

RECONCILIATION_SNAPSHOT_SCHEMA = "stygnox_reconciliation_snapshot_v1"
RECONCILIATION_PREVIEW_SCHEMA = "stygnox_reconciliation_preview_v1"
RECONCILIATION_ACTION_SCHEMA = "stygnox_reconciliation_action_v1"

PENDING = "PENDING_RECONCILIATION"
ADOPTED = "ADOPTED_PLAN_CARRY_FORWARD"
LEFT_OUTSIDE = "LEFT_OUTSIDE_PLAN_BOUNDARY"
REJECTED = "REJECTED_EXTERNAL_RECONCILIATION_REQUIRED"
_FINAL = {ADOPTED, LEFT_OUTSIDE, REJECTED}
_DISPOSITIONS = {"adopt": ADOPTED, "leave-outside": LEFT_OUTSIDE, "reject": REJECTED}
_CONFIRMATIONS = {"adopt": "ADOPT", "leave-outside": "LEAVE", "reject": "REJECT"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ReconciliationError(RuntimeError):
    """Fail-closed carry-forward ownership reconciliation error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _normalize_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReconciliationError(f"invalid reconciliation path: {value!r}")
    return path.as_posix()


def _active_authority(project: Path, operator_name: str, plan_hash: str | None = None) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
    try:
        root, active, tx, policy_status, name = planning._active_context(project, operator_name)
    except planning.PlanningError as exc:
        raise ReconciliationError(str(exc)) from exc
    state = planning._record(root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise ReconciliationError(f"reconciliation requires current APPROVED plan, found {state.get('status')}")
    if state.get("self_development_grant") is not None:
        raise ReconciliationError("reconciliation refuses an active self-development authority epoch; consume or expire it first")
    plan = planning._validate_plan(state.get("plan"))
    expected_hash = planning._plan_hash(plan)
    if state.get("plan_hash") != expected_hash:
        raise ReconciliationError("active plan hash does not match controller state")
    supplied = str(plan_hash or expected_hash).strip().lower()
    if not _HEX64.fullmatch(supplied) or supplied != expected_hash:
        raise ReconciliationError("reconciliation plan hash does not match the current approved plan")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise ReconciliationError("approved plan authority does not match active transaction/operator")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise ReconciliationError("controller authority changed after plan approval")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise ReconciliationError("execution policy changed after plan approval")
    if state.get("transaction_recovery_baseline_sha256") != tx.get("authority_baseline_sha256"):
        raise ReconciliationError("transaction recovery authority changed after plan approval")
    current_step = int(state.get("current_step") or 0)
    if current_step < 1 or current_step > len(plan["steps"]):
        raise ReconciliationError("current approved plan step is invalid")
    sched = scheduler.scheduler_status(root).get("scheduler")
    if isinstance(sched, Mapping) and str(sched.get("status") or "") in {"RUNNING", "TURN_RUNNING", "INTERRUPTED"}:
        raise ReconciliationError("reconciliation refuses active/interrupted scheduler authority; recover or stop it first")
    return root, state, active, tx, policy_status, name


def _raw_attribution(root: Path) -> dict[str, Any]:
    # Lazy import avoids a module cycle: operator overlays our durable actions.
    from . import operator as operator_surface
    return operator_surface._classify_changes_raw(root)


def _approval_presence(root: Path, state: Mapping[str, Any], source: str, path: str) -> str:
    if source in {"operator_baseline", "unresolved"}:
        return "present"
    evidence = state.get("approval_repository_evidence") if isinstance(state.get("approval_repository_evidence"), Mapping) else {}
    for item in evidence.get("untracked") or []:
        if isinstance(item, Mapping) and str(item.get("path") or "") == path:
            return "present"
    head = str(evidence.get("head") or "").strip()
    if head:
        result = adoption._git(root, "cat-file", "-e", f"{head}:{path}", check=False)
        if result.returncode == 0:
            return "present"
    return "absent"


def _candidate_rows(root: Path, state: Mapping[str, Any], raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    categories = raw.get("categories") if isinstance(raw.get("categories"), Mapping) else {}
    manifest = scheduler.repository_manifest(root)
    current = adoption.capture_baseline(root).public()
    from . import operator as operator_surface
    status_codes = operator_surface._status_paths(str(current.get("status") or ""))
    sources: dict[str, str] = {}
    # Most conservative classification wins when a path somehow appears twice.
    for category in ("operator_baseline", "external", "unresolved"):
        block = categories.get(category) if isinstance(categories.get(category), Mapping) else {}
        for item in block.get("paths") or []:
            path = _normalize_path(str(item))
            sources[path] = category
    rows: list[dict[str, Any]] = []
    for path in sorted(sources):
        source = sources[path]
        body: dict[str, Any] = {
            "path": path,
            "classification": source,
            "status_code": status_codes.get(path, ""),
            "content_fingerprint": manifest.get(path, "missing"),
            "approval_presence": _approval_presence(root, state, source, path),
        }
        body["candidate_sha256"] = _digest(body)
        rows.append(body)
    return rows


def _actions(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("reconciliation_actions") or []
    if not isinstance(raw, list):
        raise ReconciliationError("plan reconciliation action state is malformed")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ReconciliationError("plan reconciliation action state contains a malformed action")
        action = dict(item)
        provided = str(action.get("action_hash") or "")
        body = dict(action)
        body.pop("action_hash", None)
        if not _HEX64.fullmatch(provided) or provided != _digest(body):
            raise ReconciliationError("reconciliation action hash is malformed or stale")
        path = _normalize_path(str(action.get("path") or ""))
        if path in seen:
            raise ReconciliationError("reconciliation state contains duplicate candidate dispositions")
        seen.add(path)
        if action.get("disposition") not in _FINAL:
            raise ReconciliationError("reconciliation state contains an invalid durable disposition")
        if action.get("plan_hash") != state.get("plan_hash"):
            raise ReconciliationError("reconciliation action is not bound to the current immutable plan")
        output.append(action)
    return output


def _is_test_path(path: str) -> bool:
    return path == "tests" or path.startswith("tests/")


def _runtime_or_protected(path: str) -> bool:
    return (
        path in {".git", adoption.RUNTIME_NAME, adoption.CONFIG_NAME, adoption.POLICY_NAME}
        or path.startswith(".git/")
        or path.startswith(f"{adoption.RUNTIME_NAME}/")
        or path == ".ralph"
        or path.startswith(".ralph/")
    )


def _self_development_path(root: Path, path: str) -> bool:
    from . import self_development
    return self_development.is_self_development_path(root, path)


def _validate_adoption(root: Path, state: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    path = str(candidate["path"])
    if _runtime_or_protected(path):
        raise ReconciliationError(f"carry-forward adoption refuses protected/runtime path: {path}")
    if _self_development_path(root, path):
        raise ReconciliationError(f"carry-forward adoption of Stygnox tooling remains outside ownership reconciliation; CAP-011 requires exact supervised controller self-development authority: {path}")
    plan = planning._validate_plan(state.get("plan"))
    step = plan["steps"][int(state["current_step"]) - 1]
    if _is_test_path(path):
        policy = str(step.get("test_change_policy") or "none")
        if policy == "none":
            raise ReconciliationError(f"carry-forward reconciliation violates test policy none: {path}")
        if policy == "add-only" and candidate.get("approval_presence") != "absent":
            raise ReconciliationError(f"carry-forward reconciliation add-only cannot adopt pre-existing test content: {path}")
        if policy not in {"add-only", "modify"}:
            raise ReconciliationError(f"carry-forward reconciliation violates test policy {policy}: {path}")


def reconciliation_snapshot(project: Path, operator_name: str, plan_hash: str) -> dict[str, Any]:
    root, state, _active, tx, policy_status, name = _active_authority(project, operator_name, plan_hash)
    raw = _raw_attribution(root)
    candidates = _candidate_rows(root, state, raw)
    current = {item["path"]: item for item in candidates}
    actions = _actions(state)
    dispositions = {str(item["path"]): item for item in actions}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = candidate["path"]
        action = dispositions.get(path)
        row = dict(candidate)
        if action is None:
            row.update({"disposition": PENDING, "owned": False, "action_hash": None, "fingerprint_matches": True})
        else:
            row.update({
                "disposition": action["disposition"],
                "owned": action["disposition"] == ADOPTED,
                "action_hash": action["action_hash"],
                "claiming_step": action["claiming_step"],
                "reason": action.get("reason"),
                "fingerprint_matches": action.get("candidate_sha256") == candidate.get("candidate_sha256"),
            })
        rows.append(row)
        seen.add(path)
    for action in actions:
        path = str(action["path"])
        if path in seen:
            continue
        rows.append({
            "path": path,
            "classification": action.get("classification"),
            "status_code": "",
            "content_fingerprint": "missing",
            "approval_presence": action.get("approval_presence"),
            "candidate_sha256": None,
            "disposition": action["disposition"],
            "owned": action["disposition"] == ADOPTED,
            "action_hash": action["action_hash"],
            "claiming_step": action["claiming_step"],
            "reason": action.get("reason"),
            "fingerprint_matches": False,
            "current_present": False,
        })
    pending = [row for row in rows if row.get("disposition") == PENDING]
    stale_adopted = [row for row in rows if row.get("disposition") == ADOPTED and row.get("fingerprint_matches") is not True]
    return {
        "schema": RECONCILIATION_SNAPSHOT_SCHEMA,
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "operator": name,
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "current_step": int(state["current_step"]),
        "test_change_policy": planning._validate_plan(state["plan"])["steps"][int(state["current_step"]) - 1]["test_change_policy"],
        "transaction_id": tx["transaction_id"],
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "review_sha256": (policy_status.get("review") or {}).get("review_sha256"),
        "repository_baseline_sha256": adoption.capture_baseline(root).public()["sha256"],
        "candidates": sorted(rows, key=lambda row: (row.get("disposition") != PENDING, str(row.get("path") or ""))),
        "pending_count": len(pending),
        "stale_adopted_count": len(stale_adopted),
        "requires_human_decision": bool(pending or stale_adopted),
    }


def _candidate(snapshot: Mapping[str, Any], path: str) -> dict[str, Any]:
    normalized = _normalize_path(path)
    matches = [dict(item) for item in snapshot.get("candidates") or [] if isinstance(item, Mapping) and item.get("path") == normalized]
    if len(matches) != 1:
        raise ReconciliationError(f"path is not an exact current reconciliation candidate: {normalized}")
    candidate = matches[0]
    if candidate.get("disposition") != PENDING:
        raise ReconciliationError("carry-forward candidate already has a durable disposition")
    return candidate


def build_action_preview(project: Path, operator_name: str, plan_hash: str, path: str, disposition: str, *, reason: str | None = None) -> dict[str, Any]:
    action_name = str(disposition or "").strip().lower()
    if action_name not in _DISPOSITIONS:
        raise ReconciliationError("--disposition must be adopt, leave-outside, or reject")
    snapshot = reconciliation_snapshot(project, operator_name, plan_hash)
    candidate = _candidate(snapshot, path)
    root = Path(snapshot["worktree"])
    state = planning._record(root)
    assert state is not None
    if action_name == "adopt":
        _validate_adoption(root, state, candidate)
        reason_value = None
    else:
        reason_value = " ".join(str(reason or "").split())
        if not reason_value:
            raise ReconciliationError(f"{action_name} requires a non-empty --reason")
        reason_value = reason_value[:1200]
    body: dict[str, Any] = {
        "schema": RECONCILIATION_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": snapshot["operator"],
        "worktree": snapshot["worktree"],
        "plan_hash": snapshot["plan_hash"],
        "plan_record_sha256": snapshot["plan_record_sha256"],
        "current_step": snapshot["current_step"],
        "test_change_policy": snapshot["test_change_policy"],
        "transaction_id": snapshot["transaction_id"],
        "tracked_config_sha256": snapshot["tracked_config_sha256"],
        "review_sha256": snapshot["review_sha256"],
        "repository_baseline_sha256": snapshot["repository_baseline_sha256"],
        "path": candidate["path"],
        "candidate_sha256": candidate["candidate_sha256"],
        "classification": candidate["classification"],
        "approval_presence": candidate["approval_presence"],
        "disposition": _DISPOSITIONS[action_name],
        "action": action_name,
        "reason": reason_value,
        "requires_explicit_confirmation": True,
        "confirmation": _CONFIRMATIONS[action_name],
    }
    body["preview_sha256"] = _digest(body)
    return body


def apply_action(project: Path, operator_name: str, plan_hash: str, path: str, disposition: str, preview_sha256: str, confirmation: str, *, reason: str | None = None) -> dict[str, Any]:
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise ReconciliationError("--preview must be the exact 64-character preview SHA-256")
    preview = build_action_preview(project, operator_name, plan_hash, path, disposition, reason=reason)
    if preview["preview_sha256"] != expected:
        raise ReconciliationError("reconciliation preview is stale; plan, authority, repository, or candidate evidence changed")
    if str(confirmation or "") != preview["confirmation"]:
        raise ReconciliationError(f"explicit confirmation required: --confirm {preview['confirmation']}")
    root = Path(preview["worktree"])
    state = planning._record(root)
    assert state is not None
    # Re-evaluate durable state immediately before mutation.
    actions = _actions(state)
    if any(item.get("path") == preview["path"] for item in actions):
        raise ReconciliationError("carry-forward candidate already has a durable disposition")
    action_body: dict[str, Any] = {
        "schema": RECONCILIATION_ACTION_SCHEMA,
        "plan_hash": preview["plan_hash"],
        "plan_record_sha256_before": preview["plan_record_sha256"],
        "path": preview["path"],
        "disposition": preview["disposition"],
        "claiming_step": preview["current_step"],
        "classification": preview["classification"],
        "candidate_sha256": preview["candidate_sha256"],
        "approval_presence": preview["approval_presence"],
        "test_change_policy": preview["test_change_policy"],
        "transaction_id": preview["transaction_id"],
        "controller_record_sha256": state["controller_record_sha256"],
        "tracked_config_sha256": preview["tracked_config_sha256"],
        "review_sha256": preview["review_sha256"],
        "repository_baseline_sha256": preview["repository_baseline_sha256"],
        "reason": preview["reason"],
        "self_development_authority": None,
        "recorded_at": _utc_now(),
    }
    action_body["action_hash"] = _digest(action_body)
    updated = dict(state)
    updated["reconciliation_actions"] = [*actions, action_body]
    path_value = str(preview["path"])
    if preview["disposition"] == ADOPTED:
        updated["carry_forward_adopted_paths"] = sorted(set(updated.get("carry_forward_adopted_paths") or []) | {path_value})
    elif preview["disposition"] == LEFT_OUTSIDE:
        updated["carry_forward_outside_paths"] = sorted(set(updated.get("carry_forward_outside_paths") or []) | {path_value})
    else:
        updated["carry_forward_rejected_paths"] = sorted(set(updated.get("carry_forward_rejected_paths") or []) | {path_value})
    written = planning._write(root, updated)
    return {
        "schema": RECONCILIATION_ACTION_SCHEMA,
        "result": preview["disposition"],
        "action": action_body,
        "plan_record_sha256": written["record_sha256"],
        "worktree_changed": False,
    }


def overlay_attribution(project: Path, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Project durable reconciliation decisions into the canonical attribution view."""
    root = adoption.resolve_worktree(project)
    output = json.loads(json.dumps(dict(raw)))
    state = planning._record(root, required=False)
    if not isinstance(state, Mapping) or state.get("status") not in {"APPROVED", "BLOCKED_HUMAN", "STEPS_COMPLETE", "READY_TO_COMMIT", "READ_ONLY_COMPLETE"}:
        return output
    try:
        actions = _actions(state)
    except ReconciliationError as exc:
        output["reconciliation_error"] = str(exc)
        output["requires_human_decision"] = True
        return output
    categories = output.get("categories") if isinstance(output.get("categories"), dict) else {}
    categories.setdefault("plan_carry_forward", {"count": 0, "paths": []})
    categories.setdefault("outside_plan", {"count": 0, "paths": []})
    categories.setdefault("rejected_external", {"count": 0, "paths": []})
    categories.setdefault("reconciliation_stale", {"count": 0, "paths": []})
    current_candidates = {item["path"]: item for item in _candidate_rows(root, state, raw)}
    decisions = []
    for action in actions:
        path = str(action["path"])
        target = {
            ADOPTED: "plan_carry_forward",
            LEFT_OUTSIDE: "outside_plan",
            REJECTED: "rejected_external",
        }[str(action["disposition"])]
        for source in ("operator_baseline", "external", "unresolved"):
            block = categories.get(source)
            if isinstance(block, dict) and path in block.get("paths", []):
                block["paths"] = [item for item in block["paths"] if item != path]
                block["count"] = len(block["paths"])
        if path not in categories[target]["paths"]:
            categories[target]["paths"].append(path)
            categories[target]["paths"].sort()
            categories[target]["count"] = len(categories[target]["paths"])
        current = current_candidates.get(path)
        stale = bool(action["disposition"] == ADOPTED and (current is None or current.get("candidate_sha256") != action.get("candidate_sha256")))
        if stale and path not in categories["reconciliation_stale"]["paths"]:
            categories["reconciliation_stale"]["paths"].append(path)
            categories["reconciliation_stale"]["paths"].sort()
            categories["reconciliation_stale"]["count"] = len(categories["reconciliation_stale"]["paths"])
        decisions.append({"kind": "reconciliation", "path": path, "disposition": action["disposition"], "action_hash": action["action_hash"], "stale": stale})
    output["categories"] = categories
    output.setdefault("human_decisions", []).extend(decisions)
    pending = []
    disposed = {str(item["path"]) for item in actions}
    for item in current_candidates.values():
        if item["path"] not in disposed:
            pending.append(item["path"])
    output["reconciliation_pending_paths"] = sorted(pending)
    output["requires_human_decision"] = bool(pending or categories["reconciliation_stale"]["count"])
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox reconcile", description="Explicit carry-forward ownership reconciliation for an approved plan.")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="emit the controller-derived reconciliation candidate snapshot")
    inspect.add_argument("plan_hash")
    inspect.add_argument("--project", type=Path, default=Path.cwd())
    inspect.add_argument("--operator", required=True)
    preview = sub.add_parser("preview", help="preview one exact candidate disposition")
    preview.add_argument("plan_hash")
    preview.add_argument("--project", type=Path, default=Path.cwd())
    preview.add_argument("--operator", required=True)
    preview.add_argument("--path", required=True)
    preview.add_argument("--disposition", choices=sorted(_DISPOSITIONS), required=True)
    preview.add_argument("--reason")
    apply = sub.add_parser("apply", help="apply one exact previewed candidate disposition")
    apply.add_argument("plan_hash")
    apply.add_argument("--project", type=Path, default=Path.cwd())
    apply.add_argument("--operator", required=True)
    apply.add_argument("--path", required=True)
    apply.add_argument("--disposition", choices=sorted(_DISPOSITIONS), required=True)
    apply.add_argument("--reason")
    apply.add_argument("--preview", required=True)
    apply.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "inspect":
            result = reconciliation_snapshot(args.project, args.operator, args.plan_hash)
        elif args.command == "preview":
            result = build_action_preview(args.project, args.operator, args.plan_hash, args.path, args.disposition, reason=args.reason)
        else:
            result = apply_action(args.project, args.operator, args.plan_hash, args.path, args.disposition, args.preview, args.confirm, reason=args.reason)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ReconciliationError, planning.PlanningError, OSError, ValueError, PermissionError) as exc:
        print(f"stygnox: reconciliation refused: {exc}", file=sys.stderr)
        return 2
