"""Bounded installed scheduler and exact interrupted-turn continuation recovery.

The scheduler never carries implicit in-process authority between provider turns.
Every loop rebuilds controller authority from durable plan/transaction/policy state.
It can automatically repeat only an explicit ordinary same-step continuation and
must stop for qualification, human gates, efficiency review, provider blocks,
authority drift, or its reviewed loop budget.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable, Mapping, Sequence

from . import adoption, controller, planning
from .product import PRODUCT


SCHEDULER_RECORD = "scheduler.json"
SCHEDULER_SCHEMA = "stygnox_scheduler_state_v1"
SCHEDULE_PREVIEW_SCHEMA = "stygnox_scheduler_preview_v1"
RECOVERY_PREVIEW_SCHEMA = "stygnox_interrupted_recovery_preview_v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE = {"RUNNING", "TURN_RUNNING", "INTERRUPTED"}


class SchedulerError(RuntimeError):
    """Fail-closed bounded scheduler error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _record(root: Path, *, required: bool = False) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / SCHEDULER_RECORD
    if not path.exists():
        if required:
            raise SchedulerError("no scheduler state exists")
        return None
    if path.is_symlink() or not path.is_file():
        raise SchedulerError("scheduler runtime record must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchedulerError(f"invalid scheduler runtime record: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEDULER_SCHEMA:
        raise SchedulerError("unsupported scheduler runtime schema")
    recorded = str(value.get("record_sha256") or "")
    body = dict(value)
    body.pop("record_sha256", None)
    if not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise SchedulerError("scheduler runtime record integrity check failed")
    return value


def _write(root: Path, body: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(body)
    payload.pop("record_sha256", None)
    payload["record_sha256"] = _digest(payload)
    adoption.write_runtime_record(root, SCHEDULER_RECORD, payload, actor="controller")
    return payload


def _pid_active(pid: object) -> bool:
    try:
        number = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    try:
        os.kill(number, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def active_scheduler_authority(root: Path) -> dict[str, Any] | None:
    """Return active scheduler ownership evidence for controller concurrency checks."""
    state = _record(root, required=False)
    if state is None or state.get("status") not in {"RUNNING", "TURN_RUNNING"}:
        return None
    return {
        "status": state.get("status"),
        "schedule_preview_sha256": state.get("schedule_preview_sha256"),
        "pid": state.get("pid"),
        "plan_hash": state.get("plan_hash"),
        "current_step": state.get("current_step"),
    }


def _file_fingerprint(path: Path) -> str:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return "missing"
    mode = stat.S_IMODE(st.st_mode)
    if path.is_symlink():
        payload = f"symlink:{mode:o}:{os.readlink(path)}".encode("utf-8", errors="surrogateescape")
        return hashlib.sha256(payload).hexdigest()
    if not path.is_file():
        return hashlib.sha256(f"other:{mode:o}".encode()).hexdigest()
    digest = hashlib.sha256()
    digest.update(f"file:{mode:o}:".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_manifest(root: Path) -> dict[str, str]:
    """Content/mode fingerprint of tracked + untracked project files, excluding ignored runtime."""
    result = adoption._git(root, "ls-files", "-co", "--exclude-standard", "-z")
    paths = sorted({item.decode("utf-8", errors="surrogateescape") for item in result.stdout.split(b"\0") if item})
    return {path: _file_fingerprint(root / path) for path in paths}


def changed_manifest_paths(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _normalize_paths(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    for raw in values:
        path = str(raw or "").strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path or path.startswith("/") or path == ".." or path.startswith("../") or "/../" in f"/{path}/":
            raise SchedulerError(f"invalid pending repository path: {raw!r}")
        if path.startswith(".stygnox/") or path == ".stygnox" or path.startswith(".git/") or path == ".git":
            raise SchedulerError(f"interrupted recovery refuses runtime/protected path: {path}")
        if path not in output:
            output.append(path)
    return sorted(output)


def _policy_forbids_pending_tests(plan: Mapping[str, Any], step: int, before_manifest: Mapping[str, str], pending: list[str]) -> str | None:
    step_view = plan["steps"][step - 1]
    policy = str(step_view.get("test_change_policy") or "none")
    tests = [path for path in pending if path == "tests" or path.startswith("tests/")]
    if not tests or policy == "modify":
        return None
    if policy == "none":
        return f"test_change_policy=none refuses interrupted test delta: {tests}"
    modified = [path for path in tests if path in before_manifest]
    if modified:
        return f"test_change_policy=add-only refuses interrupted modification of existing tests: {modified}"
    return None


def build_schedule_preview(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    existing = _record(root, required=False)
    if existing and existing.get("status") in _ACTIVE:
        if _pid_active(existing.get("pid")):
            raise SchedulerError(f"scheduler runtime is already active at pid {existing.get('pid')}")
        raise SchedulerError("interrupted scheduler state requires explicit recovery before a new schedule")
    try:
        context = planning.approved_step_context(root, operator)
    except planning.PlanningError as exc:
        raise SchedulerError(str(exc)) from exc
    if context is None:
        raise SchedulerError("scheduler requires an approved plan")
    step = context["step"]
    try:
        turn = controller.build_run_preview(root, operator, step["objective"], context["repository_authority"])
    except controller.ControllerError as exc:
        raise SchedulerError(str(exc)) from exc
    loops = int((turn.get("execution_controls") or {}).get("max_loops") or 1)
    body: dict[str, Any] = {
        "schema": SCHEDULE_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": turn["operator"],
        "worktree": str(root),
        "plan_hash": context["plan_hash"],
        "plan_record_sha256": context["plan_record_sha256"],
        "current_step": context["current_step"],
        "step_authority_baseline_sha256": context["step_authority_baseline_sha256"],
        "transaction_id": turn["transaction_id"],
        "controller_record_sha256": turn["controller_record_sha256"],
        "tracked_config_sha256": turn["tracked_config_sha256"],
        "review_sha256": turn["review_sha256"],
        "project_baseline_sha256": turn["project_baseline"]["sha256"],
        "max_loops": loops,
        "requires_explicit_confirmation": True,
        "confirmation": "SCHEDULE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def _stop_status(next_action: str) -> tuple[str, str]:
    mapping = {
        "human-gate-required": ("STOPPED_HUMAN_GATE", "human-gate-required"),
        "turn-blocked": ("STOPPED_PROVIDER_BLOCK", "turn-blocked"),
        "efficiency-review-required": ("STOPPED_EFFICIENCY", "efficiency-review-required"),
        "qualification-required": ("STOPPED_QUALIFICATION", "qualification-required"),
        "turn-complete": ("STOPPED_QUALIFICATION", "qualification-required"),
    }
    return mapping.get(next_action, ("STOPPED_UNEXPECTED", next_action or "unexpected-controller-result"))


def run_schedule(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "SCHEDULE":
        raise SchedulerError("explicit confirmation required: --confirm SCHEDULE")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise SchedulerError("--preview must be the exact 64-character preview SHA-256")
    preview = build_schedule_preview(project, operator)
    if preview["preview_sha256"] != expected:
        raise SchedulerError("scheduler preview is stale; plan, authority, policy, or baseline changed")
    root = Path(preview["worktree"])
    state: dict[str, Any] = {
        "schema": SCHEDULER_SCHEMA,
        "product_version": PRODUCT.version,
        "status": "RUNNING",
        "operator": preview["operator"],
        "worktree": str(root),
        "schedule_preview_sha256": expected,
        "plan_hash": preview["plan_hash"],
        "starting_plan_record_sha256": preview["plan_record_sha256"],
        "current_step": preview["current_step"],
        "transaction_id": preview["transaction_id"],
        "controller_record_sha256": preview["controller_record_sha256"],
        "tracked_config_sha256": preview["tracked_config_sha256"],
        "review_sha256": preview["review_sha256"],
        "max_loops": preview["max_loops"],
        "loops_completed": 0,
        "pid": os.getpid(),
        "started_at": _utc_now(),
        "finished_at": None,
        "stop_reason": None,
        "last_turn": None,
        "turn_history": [],
    }
    state = _write(root, state)
    try:
        for index in range(1, int(preview["max_loops"]) + 1):
            try:
                context = planning.approved_step_context(root, operator)
            except planning.PlanningError as exc:
                raise SchedulerError(str(exc)) from exc
            if context is None or context["plan_hash"] != preview["plan_hash"]:
                raise SchedulerError("approved plan identity changed during scheduler execution")
            step = context["step"]
            turn = controller.build_run_preview(
                root,
                operator,
                step["objective"],
                context["repository_authority"],
                _scheduler_authority=expected,
            )
            before_manifest = repository_manifest(root)
            state.update({
                "status": "TURN_RUNNING",
                "current_step": context["current_step"],
                "turn_index": index,
                "turn_preview_sha256": turn["preview_sha256"],
                "turn_plan_record_sha256": context["plan_record_sha256"],
                "turn_before_baseline_sha256": turn["project_baseline"]["sha256"],
                "turn_before_manifest": before_manifest,
                "turn_before_manifest_sha256": _digest(before_manifest),
            })
            state = _write(root, state)
            try:
                result = controller.run_controller(
                    root,
                    operator,
                    step["objective"],
                    context["repository_authority"],
                    turn["preview_sha256"],
                    "RUN",
                    _scheduler_authority=expected,
                )
            except (controller.ControllerError, planning.PlanningError, adoption.AdoptionError, OSError, ValueError) as exc:
                state.update({
                    "status": "INTERRUPTED",
                    "pid": None,
                    "finished_at": _utc_now(),
                    "stop_reason": f"controller-exception: {exc}",
                })
                _write(root, state)
                raise SchedulerError(f"scheduler interrupted during controller turn: {exc}") from exc
            history = list(state.get("turn_history") or [])
            turn_evidence = {
                "turn_index": index,
                "step": context["current_step"],
                "preview_sha256": turn["preview_sha256"],
                "controller_result_sha256": result["record_sha256"],
                "before_baseline_sha256": result["before_baseline_sha256"],
                "after_baseline_sha256": result["after_baseline_sha256"],
                "next_action": result["next_action"],
                "completed_at": _utc_now(),
            }
            turn_evidence["record_sha256"] = _digest(turn_evidence)
            state.update({
                "loops_completed": int(state.get("loops_completed") or 0) + 1,
                "last_turn": turn_evidence,
                "turn_history": [*history[-99:], turn_evidence],
                "turn_before_manifest": None,
                "turn_before_manifest_sha256": None,
            })
            if result["next_action"] == "continue-same-step":
                if index >= int(preview["max_loops"]):
                    state.update({
                        "status": "PAUSED_MAX_LOOPS",
                        "pid": None,
                        "finished_at": _utc_now(),
                        "stop_reason": "max-loops",
                    })
                    return _write(root, state)
                state["status"] = "RUNNING"
                state = _write(root, state)
                continue
            status, reason = _stop_status(str(result.get("next_action") or ""))
            state.update({"status": status, "pid": None, "finished_at": _utc_now(), "stop_reason": reason})
            return _write(root, state)
        state.update({"status": "PAUSED_MAX_LOOPS", "pid": None, "finished_at": _utc_now(), "stop_reason": "max-loops"})
        return _write(root, state)
    except BaseException:
        # KeyboardInterrupt/process kill cannot always execute this branch; TURN_RUNNING is intentionally durable.
        raise


def _controller_receipt(root: Path, preview_sha256: str) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / f"controller-run-{preview_sha256[:16]}.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != controller.RUN_RESULT_SCHEMA or value.get("preview_sha256") != preview_sha256:
        return None
    digest = str(value.get("record_sha256") or "")
    body = dict(value)
    body.pop("record_sha256", None)
    if not _HEX64.fullmatch(digest) or digest != _digest(body):
        return None
    return value


def _recovery_authority(root: Path, operator: str, state: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        bound_root, active, tx, policy_status, name = planning._active_context(root, operator)
    except planning.PlanningError as exc:
        raise SchedulerError(str(exc)) from exc
    plan_state = planning._record(bound_root)
    assert plan_state is not None
    if plan_state.get("status") != "APPROVED" or plan_state.get("execution_authority_granted") is not True:
        raise SchedulerError("interrupted recovery requires the same approved plan authority")
    if plan_state.get("plan_hash") != state.get("plan_hash") or int(plan_state.get("current_step") or 0) != int(state.get("current_step") or 0):
        raise SchedulerError("plan/step changed after scheduler interruption")
    if name != state.get("operator") or tx.get("transaction_id") != state.get("transaction_id"):
        raise SchedulerError("transaction/operator authority changed after scheduler interruption")
    if active.get("record_sha256") != state.get("controller_record_sha256"):
        raise SchedulerError("controller authority changed after scheduler interruption")
    if policy_status.get("tracked_config_sha256") != state.get("tracked_config_sha256") or (policy_status.get("review") or {}).get("review_sha256") != state.get("review_sha256"):
        raise SchedulerError("execution policy changed after scheduler interruption")
    return plan_state, tx


def build_recovery_preview(project: Path, operator: str, pending_paths: Iterable[str]) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    state = _record(root, required=True)
    assert state is not None
    if state.get("status") not in {"TURN_RUNNING", "INTERRUPTED"}:
        raise SchedulerError(f"interrupted recovery requires TURN_RUNNING/INTERRUPTED scheduler state, found {state.get('status')}")
    if _pid_active(state.get("pid")):
        raise SchedulerError(f"interrupted recovery refuses active scheduler pid {state.get('pid')}")
    plan_state, _tx = _recovery_authority(root, operator, state)
    turn_preview = str(state.get("turn_preview_sha256") or "")
    if not _HEX64.fullmatch(turn_preview):
        raise SchedulerError("interrupted scheduler state lacks an exact turn preview")
    receipt = _controller_receipt(root, turn_preview)
    declared = _normalize_paths(pending_paths)
    if receipt is not None:
        if declared:
            raise SchedulerError("completed interrupted turn recovery requires no pending-path declaration")
        body: dict[str, Any] = {
            "schema": RECOVERY_PREVIEW_SCHEMA,
            "product_version": PRODUCT.version,
            "operator": state["operator"],
            "worktree": str(root),
            "mode": "completed-turn",
            "scheduler_record_sha256": state["record_sha256"],
            "schedule_preview_sha256": state["schedule_preview_sha256"],
            "plan_hash": state["plan_hash"],
            "current_step": state["current_step"],
            "turn_preview_sha256": turn_preview,
            "controller_result_sha256": receipt["record_sha256"],
            "pending_paths": [],
            "recovered_baseline_sha256": receipt["after_baseline_sha256"],
            "requires_explicit_confirmation": True,
            "confirmation": "RECOVER",
        }
        body["preview_sha256"] = _digest(body)
        return body
    before_manifest = state.get("turn_before_manifest")
    if not isinstance(before_manifest, Mapping) or _digest(before_manifest) != state.get("turn_before_manifest_sha256"):
        raise SchedulerError("interrupted scheduler pre-turn manifest is missing or altered")
    current_manifest = repository_manifest(root)
    changed = changed_manifest_paths(before_manifest, current_manifest)
    if declared != changed:
        raise SchedulerError(f"interrupted recovery requires exact pending paths: declared={declared} expected={changed}")
    plan = planning._validate_plan(plan_state.get("plan"))
    policy_error = _policy_forbids_pending_tests(plan, int(state["current_step"]), before_manifest, declared)
    if policy_error:
        raise SchedulerError(policy_error)
    current = adoption.capture_baseline(root).public()
    body = {
        "schema": RECOVERY_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": state["operator"],
        "worktree": str(root),
        "mode": "partial-turn",
        "scheduler_record_sha256": state["record_sha256"],
        "schedule_preview_sha256": state["schedule_preview_sha256"],
        "plan_hash": state["plan_hash"],
        "current_step": state["current_step"],
        "turn_preview_sha256": turn_preview,
        "before_baseline_sha256": state["turn_before_baseline_sha256"],
        "pending_paths": declared,
        "pending_manifest_sha256": _digest(current_manifest),
        "recovered_baseline_sha256": current["sha256"],
        "requires_explicit_confirmation": True,
        "confirmation": "RECOVER",
    }
    body["preview_sha256"] = _digest(body)
    return body


def recover_interrupted(project: Path, operator: str, pending_paths: Iterable[str], preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "RECOVER":
        raise SchedulerError("explicit confirmation required: --confirm RECOVER")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise SchedulerError("--preview must be the exact 64-character preview SHA-256")
    preview = build_recovery_preview(project, operator, pending_paths)
    if preview["preview_sha256"] != expected:
        raise SchedulerError("interrupted recovery preview is stale; authority or repository evidence changed")
    root = Path(preview["worktree"])
    state = _record(root, required=True)
    assert state is not None
    if preview["mode"] == "completed-turn":
        receipt = _controller_receipt(root, preview["turn_preview_sha256"])
        assert receipt is not None
        status, reason = _stop_status(str(receipt.get("next_action") or ""))
        if receipt.get("next_action") == "continue-same-step":
            status, reason = "RECOVERED_COMPLETED_CONTINUATION", "completed-turn-continuation"
        state.update({
            "status": status,
            "pid": None,
            "finished_at": _utc_now(),
            "stop_reason": reason,
            "recovery_preview_sha256": expected,
            "recovery_mode": "completed-turn",
            "recovered_controller_result_sha256": receipt["record_sha256"],
        })
        return _write(root, state)
    current = adoption.capture_baseline(root).public()
    if current["sha256"] != preview["recovered_baseline_sha256"]:
        raise SchedulerError("repository changed after interrupted recovery preview")
    try:
        recovered = planning.recover_interrupted_same_step(
            root,
            operator,
            plan_hash=preview["plan_hash"],
            step=int(preview["current_step"]),
            before_baseline_sha256=preview["before_baseline_sha256"],
            recovered_baseline=current,
            pending_paths=list(preview["pending_paths"]),
            scheduler_run_sha256=preview["scheduler_record_sha256"],
        )
    except planning.PlanningError as exc:
        raise SchedulerError(str(exc)) from exc
    state.update({
        "status": "RECOVERED_PARTIAL_TURN",
        "pid": None,
        "finished_at": _utc_now(),
        "stop_reason": "interrupted-turn-recovered",
        "recovery_preview_sha256": expected,
        "recovery_mode": "partial-turn",
        "recovered_plan_record_sha256": recovered["plan_record_sha256"],
        "recovered_pending_paths": list(preview["pending_paths"]),
    })
    written = _write(root, state)
    return {**written, "recovery": recovered}


def scheduler_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    return {
        "schema": "stygnox_scheduler_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "scheduler": _record(root, required=False),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox scheduler", description="Bounded approved-plan continuation scheduler and interrupted-turn recovery.")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--project", type=Path, default=Path.cwd())
    preview = sub.add_parser("run-preview")
    preview.add_argument("--project", type=Path, default=Path.cwd())
    preview.add_argument("--operator", required=True)
    run = sub.add_parser("run")
    run.add_argument("--project", type=Path, default=Path.cwd())
    run.add_argument("--operator", required=True)
    run.add_argument("--preview", required=True)
    run.add_argument("--confirm", required=True)
    recovery_preview = sub.add_parser("recover-preview")
    recovery_preview.add_argument("--project", type=Path, default=Path.cwd())
    recovery_preview.add_argument("--operator", required=True)
    recovery_preview.add_argument("--pending-path", action="append", default=[])
    recover = sub.add_parser("recover")
    recover.add_argument("--project", type=Path, default=Path.cwd())
    recover.add_argument("--operator", required=True)
    recover.add_argument("--pending-path", action="append", default=[])
    recover.add_argument("--preview", required=True)
    recover.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = scheduler_status(args.project)
        elif args.action == "run-preview":
            result = build_schedule_preview(args.project, args.operator)
        elif args.action == "run":
            result = run_schedule(args.project, args.operator, args.preview, args.confirm)
        elif args.action == "recover-preview":
            result = build_recovery_preview(args.project, args.operator, args.pending_path)
        else:
            result = recover_interrupted(args.project, args.operator, args.pending_path, args.preview, args.confirm)
    except (SchedulerError, controller.ControllerError, planning.PlanningError, adoption.AdoptionError, OSError, ValueError) as exc:
        print(f"stygnox: scheduler refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
