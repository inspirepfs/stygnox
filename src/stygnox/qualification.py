"""Controller-owned step and terminal qualification for installed Stygnox.

Qualification is deliberately provider-independent.  The controller executes
only tracked, argv-based project gates, binds their results to exact plan and
repository evidence, advances successful approved steps, and admits the final
write delta to READY_TO_COMMIT only after deterministic provenance checks.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
from typing import Any

from . import adoption, controller, execution_policy, planning, scheduler, transactions
from .product import PRODUCT
from .profile import DEFAULT_PROFILE


CONFIG_SCHEMA = "stygnox_qualification_config_v1"
PREVIEW_SCHEMA = "stygnox_qualification_preview_v1"
RESULT_SCHEMA = "stygnox_qualification_result_v1"
REPORT_SCHEMA = "stygnox_completion_report_v1"
QUALIFICATION_RECORD = "qualification.json"
REPORT_JSON = "completion-report.json"
REPORT_MARKDOWN = "completion-report.md"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_GATE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALLOWED_PLAN_STATES = {"APPROVED", "STEPS_COMPLETE", "READY_TO_COMMIT", "READ_ONLY_COMPLETE"}


class QualificationError(RuntimeError):
    """Fail-closed qualification error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _config_path(root: Path) -> Path:
    return root / getattr(DEFAULT_PROFILE, "qualification_config", "stygnox.qualification.toml")


def qualification_config(root: Path) -> dict[str, Any]:
    path = _config_path(root)
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"tracked qualification configuration is missing or non-regular: {path.name}")
    try:
        raw = path.read_bytes()
        value = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise QualificationError(f"cannot parse tracked qualification configuration: {exc}") from exc
    if value.get("schema") != CONFIG_SCHEMA:
        raise QualificationError(f"unsupported qualification configuration schema: {value.get('schema')!r}")
    rows = value.get("gate")
    if not isinstance(rows, list) or not rows:
        raise QualificationError("qualification configuration must contain at least one [[gate]]")
    gates: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise QualificationError(f"qualification gate {index} must be a table")
        name = str(row.get("name") or "").strip()
        if not _GATE_NAME.fullmatch(name) or name in names:
            raise QualificationError(f"qualification gate {index} has invalid or duplicate name")
        names.add(name)
        command = row.get("command")
        if not isinstance(command, list) or not command or len(command) > 64:
            raise QualificationError(f"qualification gate {name!r} command must contain 1-64 argv items")
        argv: list[str] = []
        for item in command:
            text = str(item)
            if not text or len(text) > 4096 or "\x00" in text or "\n" in text or "\r" in text:
                raise QualificationError(f"qualification gate {name!r} contains invalid argv content")
            argv.append(text)
        try:
            timeout_seconds = int(row.get("timeout_seconds", 1800))
        except (TypeError, ValueError) as exc:
            raise QualificationError(f"qualification gate {name!r} timeout_seconds must be an integer") from exc
        if not 1 <= timeout_seconds <= 7200:
            raise QualificationError(f"qualification gate {name!r} timeout_seconds must be between 1 and 7200")
        gates.append({"name": name, "command": argv, "timeout_seconds": timeout_seconds})
    # diff-check is a controller-owned invariant and cannot be removed by project config.
    if "diff-check" not in names:
        gates.append({"name": "diff-check", "command": ["git", "diff", "--check"], "timeout_seconds": 120})
    return {
        "schema": CONFIG_SCHEMA,
        "path": path.name,
        "sha256": _sha256_bytes(raw),
        "gates": gates,
    }


def _validate_active_authority(project: Path, operator: str, plan_hash: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
    try:
        root, active, tx, policy_status, name = planning._active_context(project, operator)
    except planning.PlanningError as exc:
        raise QualificationError(str(exc)) from exc
    state = planning._record(root)
    assert state is not None
    if state.get("status") not in _ALLOWED_PLAN_STATES:
        raise QualificationError(f"qualification requires approved/completed plan authority, found {state.get('status')}")
    plan = planning._validate_plan(state.get("plan"))
    expected = planning._plan_hash(plan)
    supplied = str(plan_hash or "").strip().lower()
    if not _HEX64.fullmatch(supplied) or supplied != expected or state.get("plan_hash") != expected:
        raise QualificationError("qualification plan hash does not match the current approved plan")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise QualificationError("qualification authority does not match active transaction/operator")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise QualificationError("controller authority changed after plan approval")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise QualificationError("execution policy changed after plan approval")
    if state.get("transaction_recovery_baseline_sha256") != tx.get("authority_baseline_sha256"):
        raise QualificationError("transaction recovery authority changed after plan approval")
    if state.get("active_gate") is not None or state.get("status") == "BLOCKED_HUMAN":
        raise QualificationError("qualification refuses an unresolved human gate")
    if state.get("self_development_grant") is not None:
        raise QualificationError("qualification refuses an active self-development authority epoch")
    active_scheduler = scheduler.active_scheduler_authority(root)
    if active_scheduler is not None:
        raise QualificationError("qualification refuses active scheduler authority")
    sched = scheduler.scheduler_status(root).get("scheduler")
    if isinstance(sched, Mapping) and str(sched.get("status") or "") in {"INTERRUPTED", "TURN_RUNNING", "RUNNING"}:
        raise QualificationError("qualification refuses active/interrupted scheduler state; recover it first")
    return root, state, active, tx, policy_status, name


def _controller_receipts(root: Path) -> list[dict[str, Any]]:
    runtime = root / adoption.RUNTIME_NAME
    rows: list[dict[str, Any]] = []
    if not runtime.is_dir():
        return rows
    for path in sorted(runtime.glob("controller-run-*.json"), key=lambda item: item.stat().st_mtime_ns):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("schema") != controller.RUN_RESULT_SCHEMA:
            continue
        recorded = str(value.get("record_sha256") or "")
        body = dict(value)
        body.pop("record_sha256", None)
        if _HEX64.fullmatch(recorded) and recorded == _digest(body):
            rows.append(value)
    return rows


def _step_receipt(root: Path, state: Mapping[str, Any], current_baseline_sha256: str) -> dict[str, Any]:
    step = int(state.get("current_step") or 0)
    plan_hash = str(state.get("plan_hash") or "")
    authority_before = str(state.get("step_authority_baseline_sha256") or state.get("approval_baseline_sha256") or "")
    matches: list[dict[str, Any]] = []
    for receipt in _controller_receipts(root):
        binding = receipt.get("plan_binding") if isinstance(receipt.get("plan_binding"), Mapping) else None
        if binding is None:
            continue
        if (
            binding.get("plan_hash") == plan_hash
            and int(binding.get("current_step") or 0) == step
            and receipt.get("before_baseline_sha256") == authority_before
            and receipt.get("after_baseline_sha256") == current_baseline_sha256
            and receipt.get("next_action") in {"qualification-required", "turn-complete"}
            and receipt.get("human_gate") is None
        ):
            matches.append(receipt)
    if not matches:
        raise QualificationError("current approved step has no exact completed controller turn awaiting qualification")
    return matches[-1]


def _attribution_guard(root: Path) -> dict[str, Any]:
    from . import operator as operator_surface
    view = operator_surface.classify_changes(root)
    if view.get("reconciliation_error"):
        raise QualificationError(f"reconciliation evidence is invalid: {view['reconciliation_error']}")
    categories = view.get("categories") if isinstance(view.get("categories"), Mapping) else {}
    pending = list(view.get("reconciliation_pending_paths") or [])
    stale = list((categories.get("reconciliation_stale") or {}).get("paths") or [])
    rejected = list((categories.get("rejected_external") or {}).get("paths") or [])
    external = list((categories.get("external") or {}).get("paths") or [])
    unresolved = list((categories.get("unresolved") or {}).get("paths") or [])
    blockers = {
        "pending": sorted(set(map(str, pending))),
        "stale_adopted": sorted(set(map(str, stale))),
        "rejected_external": sorted(set(map(str, rejected))),
        "external": sorted(set(map(str, external))),
        "unresolved": sorted(set(map(str, unresolved))),
    }
    active = {key: value for key, value in blockers.items() if value}
    if active:
        raise QualificationError("qualification refuses unresolved repository ownership: " + json.dumps(active, sort_keys=True))
    return view


def _completion_coverage(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    plan = planning._validate_plan(state.get("plan"))
    rows = [dict(row) for row in state.get("step_results") or [] if isinstance(row, Mapping)]
    by_step: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            step = int(row.get("step") or 0)
        except (TypeError, ValueError):
            continue
        by_step.setdefault(step, []).append(row)
    missing = [step["id"] for step in plan["steps"] if len(by_step.get(int(step["id"]), [])) != 1]
    bad = [row for row in rows if row.get("result") not in {"PASS", "HUMAN_CONFIRMED"}]
    if missing or bad:
        raise QualificationError(f"terminal qualification requires exactly one accepted result per approved step; missing/duplicate={missing}, nonaccepted={len(bad)}")
    return [by_step[index][0] for index in range(1, len(plan["steps"]) + 1)]


def _manifest_delta(state: Mapping[str, Any], root: Path, attribution: Mapping[str, Any]) -> tuple[list[str], list[str], dict[str, str]]:
    approval = state.get("approval_repository_manifest")
    if not isinstance(approval, Mapping):
        raise QualificationError("approved plan predates qualification manifest binding; regenerate/reapprove the plan")
    before = {str(key): str(value) for key, value in approval.items()}
    current = scheduler.repository_manifest(root)
    changed = scheduler.changed_manifest_paths(before, current)
    categories = attribution.get("categories") if isinstance(attribution.get("categories"), Mapping) else {}
    outside = set(map(str, (categories.get("outside_plan") or {}).get("paths") or []))
    plan_owned = sorted(path for path in changed if path not in outside)
    return changed, plan_owned, current


def _qualified_delta_sha256(manifest: Mapping[str, str], paths: Sequence[str]) -> str:
    return _digest({"paths": {path: manifest.get(path, "missing") for path in sorted(set(paths))}})


def _build_preview(project: Path, operator: str, plan_hash: str, *, requalify: bool = False) -> dict[str, Any]:
    root, state, active, tx, policy_status, name = _validate_active_authority(project, operator, plan_hash)
    config = qualification_config(root)
    current = adoption.capture_baseline(root).public()
    attribution = _attribution_guard(root)
    status = str(state.get("status") or "")
    plan = planning._validate_plan(state.get("plan"))
    repository_authority = str(plan.get("repository_authority") or "")
    phase: str
    receipt: dict[str, Any] | None = None
    step = int(state.get("current_step") or 0)
    if requalify:
        if status != "READY_TO_COMMIT":
            raise QualificationError(f"requalification requires READY_TO_COMMIT, found {status}")
        final = state.get("final_qualification") if isinstance(state.get("final_qualification"), Mapping) else {}
        if final.get("state") != "PASS":
            raise QualificationError("requalification requires prior PASS final qualification")
        if final.get("qualification_config_sha256") != config["sha256"]:
            raise QualificationError("qualification configuration changed after READY_TO_COMMIT; explicit replanning is required")
        _completion_coverage(state)
        _changed, plan_owned, current_manifest = _manifest_delta(state, root, attribution)
        expected_paths = sorted(map(str, final.get("plan_owned_paths") or []))
        if plan_owned != expected_paths:
            raise QualificationError("requalification refuses path-set drift outside the previously qualified plan-owned delta")
        phase = "requalify-final"
    elif status == "APPROVED":
        if step < 1 or step > len(plan["steps"]):
            raise QualificationError("current approved plan step is invalid")
        receipt = _step_receipt(root, state, current["sha256"])
        phase = "final" if step == len(plan["steps"]) else "step"
        if phase == "final":
            # Existing accepted results must cover all earlier steps exactly once.
            prior = [dict(row) for row in state.get("step_results") or [] if isinstance(row, Mapping)]
            prior_steps = sorted(int(row.get("step") or 0) for row in prior if row.get("result") in {"PASS", "HUMAN_CONFIRMED"})
            if prior_steps != list(range(1, step)):
                raise QualificationError("final step qualification requires all earlier approved steps to be accepted exactly once")
        plan_owned = []
        current_manifest = {}
    elif status == "STEPS_COMPLETE":
        _completion_coverage(state)
        phase = "final"
        plan_owned = []
        current_manifest = {}
    elif status == "READ_ONLY_COMPLETE":
        raise QualificationError("read-only plan is already complete")
    else:
        raise QualificationError(f"qualification cannot run from plan status {status}")

    if phase in {"final", "requalify-final"}:
        changed, derived_owned, manifest = _manifest_delta(state, root, attribution)
        plan_owned = derived_owned
        current_manifest = manifest
    else:
        changed = []

    body: dict[str, Any] = {
        "schema": PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "phase": phase,
        "current_step": step,
        "total_steps": len(plan["steps"]),
        "repository_authority": repository_authority,
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "review_sha256": (policy_status.get("review") or {}).get("review_sha256"),
        "qualification_config_path": config["path"],
        "qualification_config_sha256": config["sha256"],
        "gates": config["gates"],
        "repository_baseline_sha256": current["sha256"],
        "step_receipt_sha256": receipt.get("record_sha256") if receipt else None,
        "approval_manifest_sha256": _digest(state.get("approval_repository_manifest")) if isinstance(state.get("approval_repository_manifest"), Mapping) else None,
        "current_manifest_sha256": _digest(current_manifest) if current_manifest else None,
        "changed_since_approval": changed,
        "plan_owned_paths": plan_owned,
        "requires_explicit_confirmation": True,
        "confirmation": "REQUALIFY" if requalify else "QUALIFY",
    }
    body["preview_sha256"] = _digest(body)
    return body


def build_preview(project: Path, operator: str, plan_hash: str) -> dict[str, Any]:
    return _build_preview(project, operator, plan_hash, requalify=False)


def build_requalify_preview(project: Path, operator: str, plan_hash: str) -> dict[str, Any]:
    return _build_preview(project, operator, plan_hash, requalify=True)


def _run_gates(root: Path, gates: Sequence[Mapping[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    for gate in gates:
        name = str(gate["name"])
        argv = [str(item) for item in gate["command"]]
        timeout_seconds = int(gate["timeout_seconds"])
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=root, capture_output=True, text=True, check=False, timeout=timeout_seconds)
            returncode = int(proc.returncode)
            output = ((proc.stdout or "") + (proc.stderr or ""))[-12000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            returncode = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
            output = str(exc)[-12000:]
        row = {
            "name": name,
            "command": argv,
            "timeout_seconds": timeout_seconds,
            "returncode": returncode,
            "status": "PASS" if returncode == 0 else "FAIL",
            "duration_seconds": round(max(0.0, time.monotonic() - started), 6),
            "output": output,
        }
        row["result_sha256"] = _digest(row)
        results.append(row)
        if returncode != 0:
            return False, results
    return True, results


def _record_result(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    body["record_sha256"] = _digest(body)
    adoption.write_runtime_record(root, QUALIFICATION_RECORD, body, actor="controller")
    return body


def _step_result_from_receipt(preview: Mapping[str, Any], receipt: Mapping[str, Any], gates: Sequence[Mapping[str, Any]], baseline_sha256: str) -> dict[str, Any]:
    binding = receipt.get("plan_binding") if isinstance(receipt.get("plan_binding"), Mapping) else {}
    body = {
        "step": int(preview["current_step"]),
        "step_id": binding.get("step_id"),
        "title": binding.get("step_title"),
        "objective": binding.get("step_objective"),
        "result": "PASS",
        "controller_receipt_sha256": receipt.get("record_sha256"),
        "qualified_baseline_sha256": baseline_sha256,
        "gates": [dict(row) for row in gates],
        "qualified_at": _utc_now(),
    }
    body["record_sha256"] = _digest(body)
    return body


def _write_completion_report(root: Path, state: Mapping[str, Any]) -> dict[str, Any]:
    final = state.get("final_qualification") if isinstance(state.get("final_qualification"), Mapping) else {}
    body = {
        "schema": REPORT_SCHEMA,
        "product_version": PRODUCT.version,
        "plan_hash": state.get("plan_hash"),
        "status": state.get("status"),
        "operator": state.get("operator"),
        "repository_authority": (state.get("plan") or {}).get("repository_authority") if isinstance(state.get("plan"), Mapping) else None,
        "step_results": list(state.get("step_results") or []),
        "human_gate_count": len(state.get("human_gate_history") or []),
        "reconciliation_actions": list(state.get("reconciliation_actions") or []),
        "self_development_grants": list(state.get("self_development_grant_history") or []),
        "final_qualification": dict(final),
        "generated_at": _utc_now(),
    }
    body["report_sha256"] = _digest(body)
    adoption.write_runtime_record(root, REPORT_JSON, body, actor="controller")
    lines = [
        "# Stygnox Completion Report",
        "",
        f"- Plan: `{body['plan_hash']}`",
        f"- Status: **{body['status']}**",
        f"- Final qualification: **{final.get('state') or 'UNKNOWN'}**",
        f"- Qualified delta: `{final.get('qualified_delta_sha256') or '-'}`",
        f"- Repository baseline: `{final.get('repository_baseline_sha256') or '-'}`",
        f"- Plan-owned paths: {len(final.get('plan_owned_paths') or [])}",
        f"- Steps: {len(body['step_results'])}",
        f"- Human gates: {body['human_gate_count']}",
        f"- Reconciliation actions: {len(body['reconciliation_actions'])}",
        f"- Self-development grants: {len(body['self_development_grants'])}",
        "",
        "## Plan-owned paths",
        "",
        *([f"- `{path}`" for path in final.get("plan_owned_paths") or []] or ["- None"]),
        "",
        "## Qualification gates",
        "",
        *([f"- {row.get('name')}: **{row.get('status')}**" for row in final.get("gates") or []] or ["- None"]),
        "",
    ]
    runtime = root / adoption.RUNTIME_NAME
    adoption._atomic_write(runtime / REPORT_MARKDOWN, "\n".join(lines), mode=0o600)
    return body


def _final_pass_state(root: Path, state: Mapping[str, Any], preview: Mapping[str, Any], gates: Sequence[Mapping[str, Any]], current_baseline: Mapping[str, Any], current_manifest: Mapping[str, str], *, requalified: bool) -> dict[str, Any]:
    plan = planning._validate_plan(state.get("plan"))
    plan_owned = list(preview.get("plan_owned_paths") or [])
    qualified_delta = _qualified_delta_sha256(current_manifest, plan_owned)
    final = {
        "state": "PASS",
        "phase": "requalify-final" if requalified else "final",
        "plan_hash": state["plan_hash"],
        "source_plan_record_sha256": state["record_sha256"],
        "qualification_preview_sha256": preview["preview_sha256"],
        "qualification_config_sha256": preview["qualification_config_sha256"],
        "repository_baseline_sha256": current_baseline["sha256"],
        "current_manifest_sha256": _digest(current_manifest),
        "approval_manifest_sha256": preview.get("approval_manifest_sha256"),
        "plan_owned_paths": plan_owned,
        "qualified_delta_sha256": qualified_delta,
        "gates": [dict(row) for row in gates],
        "completed_at": _utc_now(),
    }
    final["provenance_sha256"] = _digest(final)
    updated = dict(state)
    updated["final_qualification"] = final
    history = [dict(row) for row in updated.get("qualification_history") or [] if isinstance(row, Mapping)]
    updated["qualification_history"] = [*history[-99:], {"kind": final["phase"], "state": "PASS", "provenance_sha256": final["provenance_sha256"], "completed_at": final["completed_at"]}]
    updated["execution_authority_granted"] = False
    updated["status"] = "READ_ONLY_COMPLETE" if plan["repository_authority"] == "read-only" else "READY_TO_COMMIT"
    updated["qualified_at"] = final["completed_at"]
    written = planning._write(root, updated)
    report = _write_completion_report(root, written)
    return {**written, "completion_report_sha256": report["report_sha256"]}


def run_qualification(project: Path, operator: str, plan_hash: str, preview_sha256: str, confirmation: str, *, requalify: bool = False) -> dict[str, Any]:
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise QualificationError("--preview must be the exact 64-character preview SHA-256")
    preview = _build_preview(project, operator, plan_hash, requalify=requalify)
    if preview["preview_sha256"] != expected:
        raise QualificationError("qualification preview is stale; plan, authority, gates, reconciliation, or repository evidence changed")
    required = "REQUALIFY" if requalify else "QUALIFY"
    if confirmation != required:
        raise QualificationError(f"explicit confirmation required: --confirm {required}")
    root = Path(preview["worktree"])
    before = adoption.capture_baseline(root).public()
    passed, gate_results = _run_gates(root, preview["gates"])
    after = adoption.capture_baseline(root).public()
    if after["sha256"] != before["sha256"]:
        raise QualificationError("qualification gates changed the repository baseline; results are not admissible")
    # Revalidate all authority and ownership after external gate execution.
    refreshed = _build_preview(root, operator, plan_hash, requalify=requalify)
    if refreshed["preview_sha256"] != expected:
        raise QualificationError("qualification authority or repository evidence changed while authoritative gates were running")
    state = planning._record(root)
    assert state is not None
    phase = str(preview["phase"])
    record = {
        "schema": RESULT_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "plan_hash": preview["plan_hash"],
        "phase": phase,
        "current_step": preview["current_step"],
        "preview_sha256": expected,
        "repository_baseline_sha256": after["sha256"],
        "qualification_config_sha256": preview["qualification_config_sha256"],
        "passed": passed,
        "gates": gate_results,
        "completed_at": _utc_now(),
    }

    if not passed:
        updated = dict(state)
        failure = {**record, "state": "FAIL"}
        failure["record_sha256"] = _digest(failure)
        history = [dict(row) for row in updated.get("qualification_history") or [] if isinstance(row, Mapping)]
        updated["qualification_history"] = [*history[-99:], failure]
        updated["last_qualification_failure"] = failure
        updated["final_qualification"] = {"state": "FAIL", "phase": phase, "gates": gate_results, "completed_at": record["completed_at"]} if phase in {"final", "requalify-final"} else updated.get("final_qualification")
        if phase == "requalify-final":
            updated["status"] = "READY_TO_COMMIT"
            updated["execution_authority_granted"] = False
        else:
            plan = planning._validate_plan(updated.get("plan"))
            if updated.get("status") == "STEPS_COMPLETE":
                updated["status"] = "APPROVED"
                updated["current_step"] = len(plan["steps"])
                # Reopen final step so controller-owned repair can occur.
                updated["step_results"] = [row for row in updated.get("step_results") or [] if int((row or {}).get("step") or 0) != len(plan["steps"])]
            updated["step_authority_baseline_sha256"] = after["sha256"]
            updated["execution_authority_granted"] = True
            updated["step_resume"] = {
                "step": int(updated.get("current_step") or 0),
                "reason": "authoritative qualification failed; repair the same approved step",
                "gate_failures": [row["name"] for row in gate_results if row["status"] == "FAIL"],
                "recorded_at": record["completed_at"],
            }
        written = planning._write(root, updated)
        persisted = _record_result(root, {**record, "state": "FAIL", "plan_record_sha256": written["record_sha256"]})
        return {**persisted, "result": "QUALIFICATION_FAILED", "plan_status": written["status"]}

    if phase == "step":
        receipt = _step_receipt(root, state, after["sha256"])
        step_result = _step_result_from_receipt(preview, receipt, gate_results, after["sha256"])
        updated = dict(state)
        results = [dict(row) for row in updated.get("step_results") or [] if isinstance(row, Mapping)]
        if any(int(row.get("step") or 0) == int(preview["current_step"]) for row in results):
            raise QualificationError("current step already has a durable qualification result")
        updated["step_results"] = [*results, step_result]
        updated["current_step"] = int(preview["current_step"]) + 1
        updated["step_authority_baseline_sha256"] = after["sha256"]
        updated["step_resume"] = None
        updated["last_qualification_failure"] = None
        history = [dict(row) for row in updated.get("qualification_history") or [] if isinstance(row, Mapping)]
        updated["qualification_history"] = [*history[-99:], {"kind": "step", "state": "PASS", "step": preview["current_step"], "record_sha256": step_result["record_sha256"], "completed_at": record["completed_at"]}]
        written = planning._write(root, updated)
        persisted = _record_result(root, {**record, "state": "PASS", "step_result_sha256": step_result["record_sha256"], "plan_record_sha256": written["record_sha256"]})
        return {**persisted, "result": "STEP_QUALIFIED", "plan_status": written["status"], "next_step": written["current_step"]}

    # final or requalification
    if phase == "final" and state.get("status") == "APPROVED":
        receipt = _step_receipt(root, state, after["sha256"])
        step_result = _step_result_from_receipt(preview, receipt, gate_results, after["sha256"])
        updated = dict(state)
        results = [dict(row) for row in updated.get("step_results") or [] if isinstance(row, Mapping)]
        if any(int(row.get("step") or 0) == int(preview["current_step"]) for row in results):
            raise QualificationError("final step already has a durable qualification result")
        updated["step_results"] = [*results, step_result]
        updated["status"] = "STEPS_COMPLETE"
        updated["execution_authority_granted"] = False
        updated["step_authority_baseline_sha256"] = after["sha256"]
        state = planning._write(root, updated)
        _completion_coverage(state)
    elif phase == "final":
        _completion_coverage(state)

    attribution = _attribution_guard(root)
    _changed, plan_owned, current_manifest = _manifest_delta(state, root, attribution)
    if sorted(plan_owned) != sorted(preview.get("plan_owned_paths") or []):
        raise QualificationError("final qualified path set changed after gate execution")
    final_state = _final_pass_state(root, state, preview, gate_results, after, current_manifest, requalified=requalify)
    persisted = _record_result(root, {**record, "state": "PASS", "qualified_delta_sha256": final_state["final_qualification"]["qualified_delta_sha256"], "provenance_sha256": final_state["final_qualification"]["provenance_sha256"], "plan_record_sha256": final_state["record_sha256"]})
    return {**persisted, "result": "REQUALIFIED_READY_TO_COMMIT" if requalify else final_state["status"], "plan_status": final_state["status"], "completion_report_sha256": final_state.get("completion_report_sha256")}


def qualification_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    state = planning._record(root, required=False)
    current = adoption.capture_baseline(root).public()
    final = state.get("final_qualification") if isinstance(state, Mapping) and isinstance(state.get("final_qualification"), Mapping) else None
    qualified_current = bool(final and final.get("state") == "PASS" and final.get("repository_baseline_sha256") == current.get("sha256"))
    return {
        "schema": "stygnox_qualification_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "plan_status": state.get("status") if isinstance(state, Mapping) else None,
        "plan_hash": state.get("plan_hash") if isinstance(state, Mapping) else None,
        "final_qualification": final,
        "current_repository_baseline_sha256": current.get("sha256"),
        "qualified_current_repository": qualified_current,
    }


def completion_report(project: Path, plan_hash: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    state = planning._record(root)
    assert state is not None
    if str(state.get("plan_hash") or "") != str(plan_hash or "").strip().lower():
        raise QualificationError("report plan hash does not match current plan")
    path = root / adoption.RUNTIME_NAME / REPORT_JSON
    if not path.is_file() or path.is_symlink():
        raise QualificationError("completion report is not available until final qualification passes")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid completion report: {exc}") from exc
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA or report.get("plan_hash") != state.get("plan_hash"):
        raise QualificationError("completion report does not match current plan")
    recorded = str(report.get("report_sha256") or "")
    body = dict(report)
    body.pop("report_sha256", None)
    if recorded != _digest(body):
        raise QualificationError("completion report integrity check failed")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox qualification", description="Controller-owned step/final qualification and requalification.")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--project", type=Path, default=Path.cwd())
    preview = sub.add_parser("preview")
    preview.add_argument("plan_hash")
    preview.add_argument("--project", type=Path, default=Path.cwd())
    preview.add_argument("--operator", required=True)
    run = sub.add_parser("run")
    run.add_argument("plan_hash")
    run.add_argument("--project", type=Path, default=Path.cwd())
    run.add_argument("--operator", required=True)
    run.add_argument("--preview", required=True)
    run.add_argument("--confirm", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("plan_hash")
    rep.add_argument("--project", type=Path, default=Path.cwd())
    rprev = sub.add_parser("requalify-preview")
    rprev.add_argument("plan_hash")
    rprev.add_argument("--project", type=Path, default=Path.cwd())
    rprev.add_argument("--operator", required=True)
    rerun = sub.add_parser("requalify")
    rerun.add_argument("plan_hash")
    rerun.add_argument("--project", type=Path, default=Path.cwd())
    rerun.add_argument("--operator", required=True)
    rerun.add_argument("--preview", required=True)
    rerun.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = qualification_status(args.project)
        elif args.action == "preview":
            result = build_preview(args.project, args.operator, args.plan_hash)
        elif args.action == "run":
            result = run_qualification(args.project, args.operator, args.plan_hash, args.preview, args.confirm)
        elif args.action == "report":
            result = completion_report(args.project, args.plan_hash)
        elif args.action == "requalify-preview":
            result = build_requalify_preview(args.project, args.operator, args.plan_hash)
        else:
            result = run_qualification(args.project, args.operator, args.plan_hash, args.preview, args.confirm, requalify=True)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (QualificationError, planning.PlanningError, controller.ControllerError, execution_policy.ExecutionPolicyError, transactions.TransactionError, OSError, ValueError) as exc:
        print(f"stygnox: qualification refused: {exc}", file=sys.stderr)
        return 2
