"""Approved-plan retirement, exact rollback, and carry-forward replacement evidence.

Retirement is a controller-owned lifecycle transition.  It never grants new
execution authority.  Rollback restores only paths conservatively attributed to
the exact active plan from a snapshot captured at approval.  Carry-forward is
non-mutating and preserves an immutable inventory for an explicit replacement
plan/reconciliation cycle.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
from typing import Any

from . import adoption, scheduler
from .product import PRODUCT

RETIREMENT_SCHEMA = "stygnox_plan_retirement_v1"
RETIREMENT_PREVIEW_SCHEMA = "stygnox_plan_retirement_preview_v1"
APPROVAL_SNAPSHOT_SCHEMA = "stygnox_plan_approval_snapshot_v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RT_RE = re.compile(r"^RT-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
_ALLOWED_STATUSES = {"APPROVED", "BLOCKED_HUMAN", "STEPS_COMPLETE", "READY_TO_COMMIT"}
_DISPOSITIONS = {"rollback": ("ROLLED_BACK", "ROLLBACK"), "carry-forward": ("RETIRED_WITH_CARRY_FORWARD", "CARRY_FORWARD")}


class RetirementError(RuntimeError):
    """Fail-closed approved-plan retirement error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _record_id(plan_hash: str, reason: str) -> str:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    suffix = _digest({"plan_hash": plan_hash, "reason": reason, "time": now.isoformat()})[:12]
    return f"RT-{now.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"


def _normalize_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RetirementError(f"invalid retirement path: {value!r}")
    normalized = path.as_posix()
    if normalized in {".git", adoption.RUNTIME_NAME, ".ralph"} or normalized.startswith((".git/", f"{adoption.RUNTIME_NAME}/", ".ralph/")):
        raise RetirementError(f"retirement refuses protected/runtime path: {normalized}")
    return normalized


def _runtime_path(root: Path, name: str) -> Path:
    if not name or Path(name).name != name:
        raise RetirementError("retirement runtime filename is invalid")
    runtime = root / adoption.RUNTIME_NAME
    runtime.mkdir(mode=0o700, parents=False, exist_ok=True)
    os.chmod(runtime, 0o700)
    return runtime / name


def _archive_name(plan_hash: str) -> str:
    return f"approval-snapshot-{plan_hash[:24]}.tar"


def capture_approval_snapshot(root: Path, plan_hash: str, manifest: Mapping[str, str]) -> dict[str, Any]:
    """Capture exact approval-time project bytes/modes in ignored controller runtime."""
    if not _HEX64.fullmatch(str(plan_hash or "")):
        raise RetirementError("approval snapshot requires exact plan hash")
    paths = sorted(_normalize_path(path) for path in manifest)
    target = _runtime_path(root, _archive_name(plan_hash))
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with tarfile.open(tmp, mode="w", dereference=False) as archive:
            for rel in paths:
                source = root / rel
                try:
                    source.lstat()
                except FileNotFoundError as exc:
                    raise RetirementError(f"approval snapshot path disappeared during capture: {rel}") from exc
                archive.add(source, arcname=rel, recursive=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    body = {
        "schema": APPROVAL_SNAPSHOT_SCHEMA,
        "plan_hash": plan_hash,
        "archive": target.name,
        "archive_sha256": _file_sha256(target),
        "manifest_sha256": _digest({str(k): str(v) for k, v in manifest.items()}),
        "path_count": len(paths),
        "captured_at": _utc_now(),
    }
    body["record_sha256"] = _digest(body)
    return body


def _validate_snapshot(root: Path, state: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    raw = state.get("approval_rollback_snapshot")
    if not isinstance(raw, Mapping) or raw.get("schema") != APPROVAL_SNAPSHOT_SCHEMA:
        raise RetirementError("active plan predates approval rollback snapshot binding; regenerate/reapprove before rollback retirement")
    snapshot = dict(raw)
    recorded = str(snapshot.get("record_sha256") or "")
    body = dict(snapshot); body.pop("record_sha256", None)
    if not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise RetirementError("approval rollback snapshot integrity check failed")
    if snapshot.get("plan_hash") != state.get("plan_hash"):
        raise RetirementError("approval rollback snapshot belongs to another plan")
    manifest = state.get("approval_repository_manifest")
    if not isinstance(manifest, Mapping) or snapshot.get("manifest_sha256") != _digest({str(k): str(v) for k, v in manifest.items()}):
        raise RetirementError("approval rollback snapshot manifest binding is stale")
    archive = _runtime_path(root, str(snapshot.get("archive") or ""))
    if archive.is_symlink() or not archive.is_file() or _file_sha256(archive) != snapshot.get("archive_sha256"):
        raise RetirementError("approval rollback snapshot archive is missing or changed")
    return snapshot, archive


def _controller_receipts(root: Path, plan_hash: str) -> list[dict[str, Any]]:
    runtime = root / adoption.RUNTIME_NAME
    rows: list[tuple[int, str, dict[str, Any]]] = []
    if not runtime.is_dir():
        return []
    for path in runtime.glob("controller-run-*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            modified = path.stat().st_mtime_ns
        except (OSError, json.JSONDecodeError):
            continue
        binding = value.get("plan_binding") if isinstance(value, Mapping) and isinstance(value.get("plan_binding"), Mapping) else {}
        if value.get("schema") == "stygnox_controller_run_result_v1" and binding.get("plan_hash") == plan_hash:
            rows.append((modified, path.name, dict(value)))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in rows]


def _plan_native_paths(root: Path, state: Mapping[str, Any]) -> list[str]:
    plan_hash = str(state.get("plan_hash") or "")
    paths: set[str] = set()
    for receipt in _controller_receipts(root, plan_hash):
        attribution = receipt.get("change_attribution") if isinstance(receipt.get("change_attribution"), Mapping) else {}
        for raw in attribution.get("controller_native_paths") or []:
            paths.add(_normalize_path(str(raw)))
    return sorted(paths)


def _plan_owned_paths(root: Path, state: Mapping[str, Any]) -> list[str]:
    # Native paths plus explicitly adopted inherited paths are plan-owned for
    # retirement.  An adopted inherited path restores to its approval-time
    # content on rollback, not to an ancestor plan's baseline.
    paths = set(_plan_native_paths(root, state))
    for raw in state.get("carry_forward_adopted_paths") or []:
        paths.add(_normalize_path(str(raw)))
    return sorted(paths)


def _known_current_baselines(root: Path, state: Mapping[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for key in ("step_authority_baseline_sha256", "approval_baseline_sha256"):
        value = str(state.get(key) or "")
        if _HEX64.fullmatch(value):
            candidates.add(value)
    gate = state.get("active_gate") if isinstance(state.get("active_gate"), Mapping) else {}
    value = str(gate.get("blocked_baseline_sha256") or "")
    if _HEX64.fullmatch(value):
        candidates.add(value)
    final = state.get("final_qualification") if isinstance(state.get("final_qualification"), Mapping) else {}
    value = str(final.get("repository_baseline_sha256") or "")
    if _HEX64.fullmatch(value):
        candidates.add(value)
    for receipt in _controller_receipts(root, str(state.get("plan_hash") or "")):
        value = str(receipt.get("after_baseline_sha256") or "")
        if _HEX64.fullmatch(value):
            candidates.add(value)
    return candidates


def _authority(project: Path, operator: str, plan_hash: str) -> tuple[Path, dict[str, Any], str]:
    from . import planning
    try:
        root, active, tx, policy_status, name = planning._active_context(project, operator)
    except planning.PlanningError as exc:
        raise RetirementError(str(exc)) from exc
    state = planning._record(root)
    assert state is not None
    status = str(state.get("status") or "")
    if status not in _ALLOWED_STATUSES:
        raise RetirementError(f"retirement requires active approved/blocked plan, found {status}")
    plan = planning._validate_plan(state.get("plan"))
    expected = planning._plan_hash(plan)
    supplied = str(plan_hash or "").strip().lower()
    if not _HEX64.fullmatch(supplied) or supplied != expected or state.get("plan_hash") != expected:
        raise RetirementError("retirement plan hash does not match the exact active plan")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise RetirementError("retirement operator/transaction authority changed")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise RetirementError("retirement controller authority changed")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise RetirementError("retirement execution policy changed")
    if state.get("transaction_recovery_baseline_sha256") != tx.get("authority_baseline_sha256"):
        raise RetirementError("retirement transaction recovery authority changed")
    sched = scheduler.scheduler_status(root).get("scheduler")
    if isinstance(sched, Mapping) and str(sched.get("status") or "") in {"RUNNING", "TURN_RUNNING", "INTERRUPTED"}:
        raise RetirementError("retirement refuses active/interrupted scheduler authority; recover it first")
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") not in _known_current_baselines(root, state):
        raise RetirementError("repository changed outside the latest plan-bound authority evidence; retirement refuses stale or unattributed delta")
    return root, state, name


def _path_state(root: Path, path: str) -> dict[str, Any]:
    target = root / path
    fingerprint = scheduler._file_fingerprint(target)
    try:
        st = target.lstat()
    except FileNotFoundError:
        kind, mode = "missing", None
    else:
        if stat.S_ISLNK(st.st_mode):
            kind = "symlink"
        elif stat.S_ISREG(st.st_mode):
            kind = "file"
        else:
            kind = "other"
        mode = stat.S_IMODE(st.st_mode)
    return {"path": path, "kind": kind, "mode": mode, "fingerprint": fingerprint}


def _approval_presence(state: Mapping[str, Any], path: str) -> bool:
    manifest = state.get("approval_repository_manifest") if isinstance(state.get("approval_repository_manifest"), Mapping) else {}
    return path in manifest


def _records(root: Path, state: Mapping[str, Any], disposition: str) -> list[dict[str, Any]]:
    paths = _plan_owned_paths(root, state)
    native = set(_plan_native_paths(root, state))
    rows: list[dict[str, Any]] = []
    manifest = state.get("approval_repository_manifest") if isinstance(state.get("approval_repository_manifest"), Mapping) else {}
    for path in paths:
        current = _path_state(root, path)
        baseline_present = _approval_presence(state, path)
        rows.append({
            "path": path,
            "source": "controller-native" if path in native else "adopted-carry-forward",
            "approval_presence": "present" if baseline_present else "absent",
            "approval_fingerprint": manifest.get(path, "missing"),
            "current": current,
            "action": ("restore" if baseline_present else "delete") if disposition == "rollback" else "preserve",
        })
    return rows


def build_retirement_preview(project: Path, operator: str, plan_hash: str, reason: str, disposition: str) -> dict[str, Any]:
    mode = str(disposition or "").strip().lower()
    if mode not in _DISPOSITIONS:
        raise RetirementError("--disposition must be rollback or carry-forward")
    note = " ".join(str(reason or "").split())
    if not note:
        raise RetirementError("retirement requires a non-empty reason")
    root, state, name = _authority(project, operator, plan_hash)
    if mode == "rollback":
        _validate_snapshot(root, state)
    rows = _records(root, state, mode)
    current = adoption.capture_baseline(root).public()
    plan = state.get("plan") if isinstance(state.get("plan"), Mapping) else {}
    result, confirmation = _DISPOSITIONS[mode]
    body: dict[str, Any] = {
        "schema": RETIREMENT_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "status_before": state["status"],
        "current_step": int(state.get("current_step") or 0),
        "total_steps": len(plan.get("steps") or []),
        "transaction_id": state.get("transaction_id"),
        "controller_record_sha256": state.get("controller_record_sha256"),
        "repository_baseline_sha256": current["sha256"],
        "approval_baseline_sha256": state.get("approval_baseline_sha256"),
        "disposition": mode,
        "result": result,
        "reason": note[:1200],
        "paths": rows,
        "restore_paths": [row["path"] for row in rows if row["action"] == "restore"],
        "delete_paths": [row["path"] for row in rows if row["action"] == "delete"],
        "preserve_paths": [row["path"] for row in rows if row["action"] == "preserve"],
        "requires_explicit_confirmation": True,
        "confirmation": confirmation,
    }
    body["preview_sha256"] = _digest(body)
    return body


def _safe_member(archive: tarfile.TarFile, path: str) -> tarfile.TarInfo:
    try:
        member = archive.getmember(path)
    except KeyError as exc:
        raise RetirementError(f"approval rollback snapshot lacks required path: {path}") from exc
    if member.name != path or member.isdir() or member.isdev() or member.isfifo():
        raise RetirementError(f"approval rollback snapshot contains unsupported path type: {path}")
    return member


def _restore_path(root: Path, archive: tarfile.TarFile, path: str) -> None:
    member = _safe_member(archive, path)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            raise RetirementError(f"rollback refuses to replace directory at plan-owned path: {path}")
        target.unlink()
    if member.issym():
        os.symlink(member.linkname, target)
    elif member.isfile():
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RetirementError(f"approval rollback snapshot cannot read path: {path}")
        with target.open("wb") as stream:
            stream.write(extracted.read())
        os.chmod(target, member.mode & 0o777)
    else:
        raise RetirementError(f"approval rollback snapshot contains unsupported path type: {path}")
    adoption._git(root, "reset", "-q", "HEAD", "--", path, check=False)


def _delete_path(root: Path, path: str) -> None:
    target = root / path
    if target.exists() or target.is_symlink():
        if target.is_dir() and not target.is_symlink():
            raise RetirementError(f"rollback refuses to delete directory at plan-owned path: {path}")
        target.unlink()
    adoption._git(root, "rm", "--cached", "-q", "-f", "--ignore-unmatch", "--", path, check=False)


def _write_manifest(root: Path, manifest: Mapping[str, Any]) -> tuple[str, str]:
    record_id = str(manifest.get("record_id") or "")
    if not _RT_RE.fullmatch(record_id):
        raise RetirementError("retirement record identifier is invalid")
    body = dict(manifest)
    body["manifest_sha256"] = _digest(body)
    name = f"retirement-{record_id}.json"
    adoption.write_runtime_record(root, name, body, actor="controller")
    return name, body["manifest_sha256"]


def load_retirement(root: Path, record_id: str, expected_sha256: str | None = None) -> dict[str, Any]:
    if not _RT_RE.fullmatch(str(record_id or "")):
        raise RetirementError("retirement record identifier is invalid")
    path = root / adoption.RUNTIME_NAME / f"retirement-{record_id}.json"
    if path.is_symlink() or not path.is_file():
        raise RetirementError("retirement record is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetirementError(f"invalid retirement record: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != RETIREMENT_SCHEMA:
        raise RetirementError("unsupported retirement record schema")
    recorded = str(value.get("manifest_sha256") or "")
    body = dict(value); body.pop("manifest_sha256", None)
    if not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise RetirementError("retirement record integrity check failed")
    if expected_sha256 is not None and recorded != expected_sha256:
        raise RetirementError("retirement record immutable digest does not match")
    return value


def latest_carry_forward_retirement(root: Path, state: Mapping[str, Any], record_id: str) -> dict[str, Any]:
    history = state.get("retired_plans") if isinstance(state.get("retired_plans"), list) else []
    if not history:
        raise RetirementError("replacement proposal requires a known carry-forward retirement")
    latest = history[-1] if isinstance(history[-1], Mapping) else {}
    if latest.get("record_id") != record_id:
        raise RetirementError("replacement proposal must consume the latest retirement record")
    if latest.get("disposition") != "RETIRED_WITH_CARRY_FORWARD":
        raise RetirementError("replacement proposal requires a carry-forward retirement record")
    manifest = load_retirement(root, record_id, str(latest.get("manifest_sha256") or ""))
    if manifest.get("disposition") != "RETIRED_WITH_CARRY_FORWARD":
        raise RetirementError("replacement retirement record is not carry-forward")
    return manifest



def _rebase_active_authority(root: Path, operator: str, record_id: str, baseline_sha256: str) -> tuple[str, str]:
    """Bind the still-active transaction/controller to the explicit post-retirement baseline."""
    from . import controller, transactions
    tx = transactions._transaction(root)
    ctl = controller._controller(root)
    assert tx is not None and ctl is not None
    if tx.get("state") != "ACTIVE" or tx.get("operator") != operator or ctl.get("operator") != operator or ctl.get("enabled") is not True:
        raise RetirementError("retirement authority rebase requires the same active transaction/controller/operator")
    if tx.get("transaction_id") != ctl.get("transaction_id"):
        raise RetirementError("retirement authority rebase found mismatched controller transaction")
    now = _utc_now()
    tx_updated = dict(tx)
    history = [dict(row) for row in tx_updated.get("retirement_rebases") or [] if isinstance(row, Mapping)]
    tx_updated["authority_baseline_sha256"] = baseline_sha256
    tx_updated["retirement_rebases"] = [*history[-19:], {"record_id": record_id, "baseline_sha256": baseline_sha256, "rebased_at": now}]
    tx_updated.pop("record_sha256", None)
    tx_updated["record_sha256"] = transactions._digest(tx_updated)
    adoption.write_runtime_record(root, transactions.TRANSACTION_RECORD, tx_updated, actor="controller")

    ctl_updated = dict(ctl)
    ctl_updated["authority_baseline_sha256"] = baseline_sha256
    ctl_updated["authority_rebased_by_retirement"] = record_id
    ctl_updated["authority_rebased_at"] = now
    ctl_updated.pop("record_sha256", None)
    ctl_updated["record_sha256"] = controller._digest(ctl_updated)
    adoption.write_runtime_record(root, controller.CONTROLLER_RECORD, ctl_updated, actor="controller")
    return tx_updated["record_sha256"], ctl_updated["record_sha256"]

def retire_plan(project: Path, operator: str, plan_hash: str, reason: str, disposition: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise RetirementError("--preview must be the exact 64-character preview SHA-256")
    preview = build_retirement_preview(project, operator, plan_hash, reason, disposition)
    if preview["preview_sha256"] != expected:
        raise RetirementError("retirement preview is stale; plan, authority, repository, reason, or attributed paths changed")
    if confirmation != preview["confirmation"]:
        raise RetirementError(f"explicit confirmation required: --confirm {preview['confirmation']}")
    root = Path(preview["worktree"])
    from . import planning
    state = planning._record(root)
    assert state is not None
    before = adoption.capture_baseline(root).public()
    rows = [dict(row) for row in preview["paths"]]
    if preview["disposition"] == "rollback":
        _snapshot, archive_path = _validate_snapshot(root, state)
        with tarfile.open(archive_path, mode="r") as archive:
            for row in rows:
                if _path_state(root, row["path"]) != row["current"]:
                    raise RetirementError(f"retirement path changed after preview: {row['path']}")
                if row["action"] == "restore":
                    _restore_path(root, archive, row["path"])
                else:
                    _delete_path(root, row["path"])
        approval = state.get("approval_repository_manifest") if isinstance(state.get("approval_repository_manifest"), Mapping) else {}
        restored_manifest = scheduler.repository_manifest(root)
        for row in rows:
            path = row["path"]
            if restored_manifest.get(path, "missing") != approval.get(path, "missing"):
                raise RetirementError(f"rollback failed to restore exact approval-time path evidence: {path}")
    after = adoption.capture_baseline(root).public()
    if preview["disposition"] == "carry-forward" and after["sha256"] != before["sha256"]:
        raise RetirementError("carry-forward retirement changed the repository; retirement refused")

    record_id = _record_id(state["plan_hash"], preview["reason"])
    planning_context = {
        "goal": (state.get("plan") or {}).get("goal") if isinstance(state.get("plan"), Mapping) else None,
        "current_step": int(state.get("current_step") or 0),
        "step_results": list(state.get("step_results") or []),
        "human_gate_history": list(state.get("human_gate_history") or []),
        "qualification_history": list(state.get("qualification_history") or []),
    }
    manifest: dict[str, Any] = {
        "schema": RETIREMENT_SCHEMA,
        "product_version": PRODUCT.version,
        "record_id": record_id,
        "created_at": _utc_now(),
        "plan_hash": state["plan_hash"],
        "status_before": state["status"],
        "step": int(state.get("current_step") or 0),
        "step_count": len((state.get("plan") or {}).get("steps") or []) if isinstance(state.get("plan"), Mapping) else 0,
        "reason": preview["reason"],
        "disposition": preview["result"],
        "preview_sha256": expected,
        "repository_before": before,
        "repository_after": after,
        "paths": rows,
        "operations": {
            "restore": list(preview["restore_paths"]),
            "delete": list(preview["delete_paths"]),
            "preserved": list(preview["preserve_paths"]),
        },
        "planning_context": planning_context,
    }
    _name, manifest_sha = _write_manifest(root, manifest)
    tx_record_sha, controller_record_sha = _rebase_active_authority(root, preview["operator"], record_id, after["sha256"])
    retirement_summary = {
        "record_id": record_id,
        "manifest_sha256": manifest_sha,
        "plan_hash": state["plan_hash"],
        "status_before": state["status"],
        "step": int(state.get("current_step") or 0),
        "reason": preview["reason"],
        "disposition": preview["result"],
        "retired_at": manifest["created_at"],
    }
    history = [dict(row) for row in state.get("retired_plans") or [] if isinstance(row, Mapping)]
    updated = dict(state)
    updated.update({
        "status": "IDLE",
        "execution_authority_granted": False,
        "plan_hash": None,
        "plan": None,
        "current_step": 1,
        "active_gate": None,
        "self_development_grant": None,
        "step_resume": None,
        "last_qualification_failure": None,
        "final_qualification": None,
        "qualified_at": None,
        "last_result": preview["result"],
        "retirement_rollback_preview": None,
        "retired_plans": [*history[-19:], retirement_summary],
        "controller_record_sha256": controller_record_sha,
        "transaction_recovery_baseline_sha256": after["sha256"],
        "approval_rollback_snapshot": None,
        "approval_repository_manifest": None,
        "approval_repository_evidence": None,
        "approval_baseline_sha256": None,
        "step_authority_baseline_sha256": None,
    })
    written = planning._write(root, updated)
    receipt = {
        "schema": "stygnox_plan_retirement_result_v1",
        "product_version": PRODUCT.version,
        "record_id": record_id,
        "manifest_sha256": manifest_sha,
        "plan_hash": preview["plan_hash"],
        "disposition": preview["result"],
        "reason": preview["reason"],
        "retired_at": manifest["created_at"],
        "plan_record_sha256": written["record_sha256"],
        "repository_baseline_sha256": after["sha256"],
        "next_action": "plan.propose-preview",
    }
    receipt["record_sha256"] = _digest(receipt)
    adoption.write_runtime_record(root, f"retirement-result-{record_id}.json", receipt, actor="controller")
    return {**receipt, "result": preview["result"], "plan_status": "IDLE"}


def retirement_status(project: Path) -> dict[str, Any]:
    from . import planning
    root = adoption.resolve_worktree(project)
    state = planning._record(root, required=False)
    history = list(state.get("retired_plans") or []) if isinstance(state, Mapping) else []
    return {
        "schema": "stygnox_plan_retirement_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "plan_status": state.get("status") if isinstance(state, Mapping) else None,
        "retired_plans": history,
        "latest": history[-1] if history else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox retirement", description="Exact approved-plan retirement, rollback, and carry-forward replacement evidence.")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--project", type=Path, default=Path.cwd())
    for action in ("preview", "retire"):
        cmd = sub.add_parser(action)
        cmd.add_argument("plan_hash")
        cmd.add_argument("--project", type=Path, default=Path.cwd())
        cmd.add_argument("--operator", required=True)
        cmd.add_argument("--reason", required=True)
        cmd.add_argument("--disposition", required=True, choices=sorted(_DISPOSITIONS))
        if action == "retire":
            cmd.add_argument("--preview", required=True)
            cmd.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = retirement_status(args.project)
        elif args.action == "preview":
            result = build_retirement_preview(args.project, args.operator, args.plan_hash, args.reason, args.disposition)
        else:
            result = retire_plan(args.project, args.operator, args.plan_hash, args.reason, args.disposition, args.preview, args.confirm)
    except (RetirementError, adoption.AdoptionError) as exc:
        print(f"stygnox: retirement refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
