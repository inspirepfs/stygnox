"""Presentation-neutral installed operator surface for D8.6.

This module is the shared semantic adapter for Web/TUI/CLI parity. It reads only
installed Stygnox state and dispatches only named, explicit installed-product
actions.  It never imports or delegates to legacy Ralph/source-tree surfaces.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import adoption, controller, execution_policy, transactions
from . import operator_state
from .product import PRODUCT
from .profile import profile_record

OPERATOR_SNAPSHOT_SCHEMA = "stygnox_operator_surface_v1"
ACTION_RESULT_SCHEMA = "stygnox_operator_action_v1"


class OperatorSurfaceError(RuntimeError):
    """Fail-closed operator surface error."""


def _runtime_json(root: Path, name: str) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / name
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise OperatorSurfaceError(f"runtime evidence must be a regular file: {name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorSurfaceError(f"invalid runtime evidence {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorSurfaceError(f"runtime evidence must be an object: {name}")
    return value


def _status_paths(status: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for raw in str(status or "").splitlines():
        if len(raw) < 4:
            continue
        code = raw[:2]
        path = raw[3:].strip()
        if " -> " in path:
            _old, path = path.split(" -> ", 1)
        if path:
            rows[path] = code
    return rows


def status_attribution(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    """Derive conservative path attribution for one provider turn.

    Newly appearing paths can be attributed to the turn. Any path already dirty
    before a write turn is deliberately treated as overlap/unresolved rather
    than silently reattributed to Stygnox.
    """
    before_paths = set(_status_paths(str(before.get("status") or "")))
    after_paths = set(_status_paths(str(after.get("status") or "")))
    before_paths.update(str(item.get("path")) for item in before.get("untracked") or [] if isinstance(item, dict) and item.get("path"))
    after_paths.update(str(item.get("path")) for item in after.get("untracked") or [] if isinstance(item, dict) and item.get("path"))
    return {
        "controller_native_paths": sorted(after_paths - before_paths),
        "operator_baseline_paths": sorted(before_paths),
        "overlap_unresolved_paths": sorted(before_paths & after_paths),
        "removed_preexisting_paths": sorted(before_paths - after_paths),
    }


def _runtime_inventory(root: Path) -> list[dict[str, Any]]:
    runtime = root / adoption.RUNTIME_NAME
    if not runtime.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(runtime.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rows.append({
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
            })
    return rows


def _controller_receipts(root: Path) -> list[dict[str, Any]]:
    runtime = root / adoption.RUNTIME_NAME
    if not runtime.is_dir():
        return []
    output: list[dict[str, Any]] = []
    for path in sorted(runtime.glob("controller-run-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("schema") == controller.RUN_RESULT_SCHEMA:
            output.append(value)
    return output


def _handoff_native_paths(handoff: Mapping[str, Any] | None) -> set[str]:
    paths: set[str] = set()
    if not isinstance(handoff, Mapping):
        return paths
    # Current installed adoption records exact tracked files rather than the
    # older tracked_review presentation shape.  Both are accepted so operator
    # attribution never misclassifies controller-created authority files as
    # external carry-forward candidates.
    tracked_files = handoff.get("tracked_files")
    if isinstance(tracked_files, Mapping):
        paths.update(str(path) for path in tracked_files if str(path).strip())
    authority = handoff.get("authority") if isinstance(handoff.get("authority"), Mapping) else {}
    for path in authority.get("paths") or []:
        text = str(path or "").strip()
        if text and not text.startswith(f"{adoption.RUNTIME_NAME}/"):
            paths.add(text)
    for row in handoff.get("tracked_review") or []:
        if isinstance(row, Mapping) and row.get("path") and row.get("action") != "unchanged":
            paths.add(str(row["path"]))
    return paths


def _classify_changes_raw(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    current = adoption.capture_baseline(root).public()
    handoff = _runtime_json(root, "adoption.json")
    baseline = handoff.get("baseline") if isinstance(handoff, dict) and isinstance(handoff.get("baseline"), dict) else {}
    current_paths = set(_status_paths(str(current.get("status") or "")))
    current_paths.update(str(item.get("path")) for item in current.get("untracked") or [] if isinstance(item, dict) and item.get("path"))
    operator_paths = set(_status_paths(str(baseline.get("status") or "")))
    operator_paths.update(str(item.get("path")) for item in baseline.get("untracked") or [] if isinstance(item, dict) and item.get("path"))

    native_paths = _handoff_native_paths(handoff)
    unresolved: set[str] = set()
    human_decisions: list[dict[str, Any]] = []
    for receipt in _controller_receipts(root):
        attribution = receipt.get("change_attribution") if isinstance(receipt.get("change_attribution"), dict) else {}
        native_paths.update(str(p) for p in attribution.get("controller_native_paths") or [])
        unresolved.update(str(p) for p in attribution.get("overlap_unresolved_paths") or [])
        unresolved.update(str(p) for p in attribution.get("removed_preexisting_paths") or [])
        human_decisions.append({
            "kind": "controller-run",
            "record_sha256": receipt.get("record_sha256"),
            "preview_sha256": receipt.get("preview_sha256"),
            "repository_authority": receipt.get("repository_authority"),
        })

    # Controller-created bootstrap authority files can appear in per-turn overlap
    # evidence because they remain dirty relative to Git HEAD.  Their ownership is
    # nevertheless explicit in the adoption handoff and must not be downgraded to
    # unresolved carry-forward merely because a later controller turn observed them.
    unresolved.difference_update(_handoff_native_paths(handoff))

    current_operator = current_paths & operator_paths
    current_native = current_paths & native_paths
    unresolved.update(current_operator & current_native)
    external = current_paths - operator_paths - native_paths - unresolved

    runtime_rows = _runtime_inventory(root)
    categories = {
        "operator_baseline": {"count": len(current_operator - unresolved), "paths": sorted(current_operator - unresolved)},
        "controller_native": {"count": len(current_native - unresolved), "paths": sorted(current_native - unresolved)},
        "runtime_only": {"count": len(runtime_rows), "paths": [row["path"] for row in runtime_rows]},
        "external": {"count": len(external), "paths": sorted(external)},
        "unresolved": {"count": len(unresolved), "paths": sorted(unresolved)},
    }
    return {
        "schema": "stygnox_change_attribution_v1",
        "worktree": str(root),
        "categories": categories,
        "human_decisions": human_decisions,
        "auto_adopt": False,
        "auto_reattribute": False,
        "requires_human_decision": bool(categories["external"]["count"] or categories["unresolved"]["count"]),
    }


def classify_changes(project: Path) -> dict[str, Any]:
    raw = _classify_changes_raw(project)
    try:
        from . import reconciliation
        return reconciliation.overlay_attribution(project, raw)
    except Exception as exc:
        # Attribution must never silently hide invalid reconciliation evidence.
        raw["reconciliation_error"] = str(exc)
        raw["requires_human_decision"] = True
        return raw


def operator_snapshot(project: Path, *, server_pid: int | None = None) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    current = adoption.capture_baseline(root).public()
    handoff = _runtime_json(root, "adoption.json")
    tx = _runtime_json(root, transactions.TRANSACTION_RECORD)
    ctl = _runtime_json(root, controller.CONTROLLER_RECORD)
    policy: dict[str, Any] | None = None
    if (root / adoption.CONFIG_NAME).is_file():
        try:
            policy = execution_policy.show_policy(root)
        except Exception as exc:  # presentation must expose, not hide, invalid policy state
            policy = {"error": str(exc)}
    runtime = _runtime_inventory(root)
    attribution = classify_changes(root)
    lifecycle = operator_state.build_lifecycle_snapshot(
        root,
        adopted=bool(isinstance(handoff, dict) and handoff.get("schema") == adoption.HANDOFF_SCHEMA),
        transaction=tx,
        controller_state=ctl,
        execution_policy=policy,
        attribution=attribution,
    )
    return {
        "schema": OPERATOR_SNAPSHOT_SCHEMA,
        "snapshot_version": 2,
        "product_version": PRODUCT.version,
        "identity": PRODUCT.name,
        "profile": profile_record(),
        "worktree": str(root),
        "operator": handoff.get("operator") if isinstance(handoff, dict) else None,
        "adopted": bool(isinstance(handoff, dict) and handoff.get("schema") == adoption.HANDOFF_SCHEMA),
        "adoption": handoff,
        "transaction": tx,
        "controller": ctl,
        "execution_policy": policy,
        "current_baseline": current,
        "attribution": attribution,
        "lifecycle": lifecycle,
        "next_actions": list(lifecycle["next_actions"]),
        "evidence_summary": {
            "runtime_directory": adoption.RUNTIME_NAME,
            "runtime_files": len(runtime),
            "latest_controller_receipts": len(_controller_receipts(root)),
            "source_tree_dependency": False,
            "legacy_ralph_delegate": False,
        },
        "server": {"pid": int(server_pid or os.getpid())},
    }


def _path(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text).expanduser() if text else None


def _policy_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "provider", "model", "effort", "reviewer", "efficiency_mode",
        "reserve_percent", "wait_for_limits", "usage_poll_seconds", "max_loops",
    )
    return {key: payload.get(key) for key in keys if key in payload and payload.get(key) not in {""}}


def dispatch_action(project: Path, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Dispatch one exact installed-product action for Web/TUI parity."""
    if not isinstance(payload, Mapping):
        raise OperatorSurfaceError("action payload must be an object")
    root = adoption.resolve_worktree(project)
    name = str(action or "").strip()
    operator_name = str(payload.get("operator") or "").strip()
    try:
        if name == "adopt.preview":
            result = adoption.build_preview(root, operator_name, dirty_evidence=_path(payload.get("dirty_evidence")), **_policy_kwargs(payload))
        elif name == "adopt.abort":
            result = adoption.abort_adoption(root, operator_name, str(payload.get("preview") or ""), dirty_evidence=_path(payload.get("dirty_evidence")), **_policy_kwargs(payload))
        elif name == "adopt.handoff":
            result = adoption.handoff_adoption(root, operator_name, str(payload.get("preview") or ""), str(payload.get("confirm") or ""), dirty_evidence=_path(payload.get("dirty_evidence")), **_policy_kwargs(payload))
        elif name == "transaction.begin":
            result = transactions.begin_transaction(root, operator_name, str(payload.get("confirm") or ""))
        elif name == "transaction.stop":
            result = transactions.stop_transaction(root, operator_name, str(payload.get("reason") or ""), str(payload.get("confirm") or ""))
        elif name == "recovery.preview":
            result = transactions.build_recovery_preview(root, operator_name, str(payload.get("post_handoff_disposition") or ""))
        elif name == "recovery.restore":
            result = transactions.restore_baseline(root, operator_name, str(payload.get("preview") or ""), str(payload.get("confirm") or ""), str(payload.get("post_handoff_disposition") or ""))
        elif name == "policy.preview":
            kwargs = _policy_kwargs(payload)
            kwargs["reset"] = bool(payload.get("reset"))
            result = execution_policy.build_policy_preview(root, operator_name, **kwargs)
        elif name in {"policy.set", "policy.reset"}:
            kwargs = _policy_kwargs(payload)
            kwargs["reset"] = name == "policy.reset"
            result = execution_policy.apply_policy(root, operator_name, str(payload.get("preview") or ""), str(payload.get("confirm") or ""), **kwargs)
        elif name == "controller.activate":
            result = controller.activate_controller(root, operator_name, str(payload.get("confirm") or ""))
        elif name == "controller.deactivate":
            result = controller.deactivate_controller(root, operator_name, str(payload.get("confirm") or ""))
        elif name == "controller.run-preview":
            result = controller.build_run_preview(root, operator_name, str(payload.get("objective") or ""), str(payload.get("repository_authority") or ""))
        elif name == "controller.run":
            result = controller.run_controller(root, operator_name, str(payload.get("objective") or ""), str(payload.get("repository_authority") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "reconciliation.inspect":
            from . import reconciliation
            result = reconciliation.reconciliation_snapshot(root, operator_name, str(payload.get("plan_hash") or ""))
        elif name == "reconciliation.preview":
            from . import reconciliation
            result = reconciliation.build_action_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("path") or ""), str(payload.get("disposition") or ""), reason=payload.get("reason"))
        elif name == "reconciliation.apply":
            from . import reconciliation
            result = reconciliation.apply_action(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("path") or ""), str(payload.get("disposition") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""), reason=payload.get("reason"))
        elif name == "plan.propose-preview":
            from . import planning
            result = planning.build_proposal_preview(root, operator_name, str(payload.get("goal") or ""), str(payload.get("repository_authority") or "write"), min_steps=payload.get("min_steps"), max_steps=payload.get("max_steps"))
        elif name == "plan.propose":
            from . import planning
            result = planning.propose_plan(root, operator_name, str(payload.get("goal") or ""), str(payload.get("repository_authority") or "write"), str(payload.get("preview") or ""), str(payload.get("confirm") or ""), min_steps=payload.get("min_steps"), max_steps=payload.get("max_steps"))
        elif name == "plan.approve":
            from . import planning
            result = planning.approve_plan(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("confirm") or ""))
        elif name == "plan.reject":
            from . import planning
            result = planning.reject_plan(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("reason") or ""), str(payload.get("confirm") or ""))
        elif name == "plan.retire-preview":
            from . import retirement
            result = retirement.build_retirement_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("reason") or ""), str(payload.get("disposition") or ""))
        elif name == "plan.retire":
            from . import retirement
            result = retirement.retire_plan(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("reason") or ""), str(payload.get("disposition") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "plan.propose-replacement-preview":
            from . import planning
            result = planning.build_proposal_preview(root, operator_name, payload.get("goal"), str(payload.get("repository_authority") or "write"), min_steps=payload.get("min_steps"), max_steps=payload.get("max_steps"), from_retirement=str(payload.get("retirement_record_id") or ""))
        elif name == "plan.propose-replacement":
            from . import planning
            result = planning.propose_plan(root, operator_name, payload.get("goal"), str(payload.get("repository_authority") or "write"), str(payload.get("preview") or ""), str(payload.get("confirm") or ""), min_steps=payload.get("min_steps"), max_steps=payload.get("max_steps"), from_retirement=str(payload.get("retirement_record_id") or ""))
        elif name == "gate.steer-preview":
            from . import human_control
            result = human_control.build_steer_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), str(payload.get("direction") or ""), payload.get("allow_new_tests") or [])
        elif name == "gate.steer":
            from . import human_control
            result = human_control.steer(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), str(payload.get("direction") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""), payload.get("allow_new_tests") or [])
        elif name == "gate.resume-preview":
            from . import human_control
            result = human_control.build_resume_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), str(payload.get("reason") or ""))
        elif name == "gate.resume":
            from . import human_control
            result = human_control.resume(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), str(payload.get("reason") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "gate.resolve-preview":
            from . import human_control
            result = human_control.build_resolve_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), str(payload.get("reason") or ""))
        elif name == "gate.resolve":
            from . import human_control
            result = human_control.resolve(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), str(payload.get("reason") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "scheduler.run-preview":
            from . import scheduler
            result = scheduler.build_schedule_preview(root, operator_name)
        elif name == "scheduler.run":
            from . import scheduler
            result = scheduler.run_schedule(root, operator_name, str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "scheduler.recover-preview":
            from . import scheduler
            result = scheduler.build_recovery_preview(root, operator_name, payload.get("pending_paths") or [])
        elif name == "scheduler.recover":
            from . import scheduler
            result = scheduler.recover_interrupted(root, operator_name, payload.get("pending_paths") or [], str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "self-development.authorize-preview":
            from . import self_development
            result = self_development.build_authorize_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), payload.get("paths") or [], str(payload.get("reason") or ""))
        elif name == "self-development.authorize":
            from . import self_development
            result = self_development.authorize(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("gate_id") or ""), payload.get("paths") or [], str(payload.get("reason") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "qualification.preview":
            from . import qualification
            result = qualification.build_preview(root, operator_name, str(payload.get("plan_hash") or ""))
        elif name == "qualification.run":
            from . import qualification
            result = qualification.run_qualification(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "qualification.requalify-preview":
            from . import qualification
            result = qualification.build_requalify_preview(root, operator_name, str(payload.get("plan_hash") or ""))
        elif name == "qualification.requalify":
            from . import qualification
            result = qualification.run_qualification(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""), requalify=True)
        elif name == "finalization.commit-preview":
            from . import finalization
            result = finalization.build_commit_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("message") or ""))
        elif name == "finalization.commit":
            from . import finalization
            result = finalization.commit(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("message") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "finalization.push-preview":
            from . import finalization
            result = finalization.build_push_preview(root, operator_name, str(payload.get("plan_hash") or ""))
        elif name == "finalization.push":
            from . import finalization
            result = finalization.push(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "finalization.reconcile-commit-preview":
            from . import finalization
            result = finalization.build_reconcile_commit_preview(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("commit_sha") or ""), str(payload.get("reason") or ""))
        elif name == "finalization.reconcile-commit":
            from . import finalization
            result = finalization.reconcile_commit(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("commit_sha") or ""), str(payload.get("reason") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        elif name == "finalization.reconcile-push-preview":
            from . import finalization
            result = finalization.build_reconcile_push_preview(root, operator_name, str(payload.get("plan_hash") or ""))
        elif name == "finalization.reconcile-push":
            from . import finalization
            result = finalization.reconcile_push(root, operator_name, str(payload.get("plan_hash") or ""), str(payload.get("preview") or ""), str(payload.get("confirm") or ""))
        else:
            raise OperatorSurfaceError(f"unsupported installed operator action: {name!r}")
    except (adoption.AdoptionError, transactions.TransactionError, execution_policy.ExecutionPolicyError, controller.ControllerError, RuntimeError, ValueError, PermissionError) as exc:
        raise OperatorSurfaceError(str(exc)) from exc
    return {"schema": ACTION_RESULT_SCHEMA, "action": name, "result": result}


def _payload_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise OperatorSurfaceError(f"payload JSON is invalid: {exc}") from exc
    if not isinstance(parsed, dict):
        raise OperatorSurfaceError("payload JSON must be an object")
    return parsed


def build_parser():
    import argparse
    parser = argparse.ArgumentParser(prog="stygnox operator", description="Presentation-neutral installed Stygnox operator surface")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="emit the canonical installed operator snapshot")
    snapshot.add_argument("--project", type=Path, default=Path.cwd())
    action = sub.add_parser("action", help="dispatch one named installed operator action")
    action.add_argument("--project", type=Path, default=Path.cwd())
    action.add_argument("--name", required=True)
    action.add_argument("--payload-json", default="{}")
    return parser


def cli_main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "snapshot":
            result = operator_snapshot(args.project)
        else:
            result = dispatch_action(args.project, args.name, _payload_json(args.payload_json))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OperatorSurfaceError, RuntimeError, OSError, ValueError) as exc:
        print(f"stygnox: operator refused: {exc}", file=sys.stderr)
        return 2
