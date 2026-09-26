"""Controller-owned Codex quota admission and banked-reset lifecycle.

Provider metadata reads use Codex app-server and never execute a model turn.
The configured reserve is a start-of-plan admission threshold.  Once an exact
plan is admitted, falling below reserve does not revoke that plan, but backend
``ordinaryUsageAllowed == false`` always blocks execution.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping

from . import adoption, provider_codex

USAGE_ADMISSION_SCHEMA = "stygnox_provider_usage_admission_v1"
USAGE_PAUSE_SCHEMA = "stygnox_provider_usage_pause_v1"
USAGE_STATE_SCHEMA = "stygnox_provider_usage_state_v1"
USAGE_STATE_RECORD = "provider-usage.json"


class ProviderUsageError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _state_record(root: Path) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / USAGE_STATE_RECORD
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProviderUsageError("provider usage runtime record must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderUsageError(f"invalid provider usage runtime record: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != USAGE_STATE_SCHEMA:
        raise ProviderUsageError("unsupported provider usage runtime record schema")
    recorded = str(value.get("record_sha256") or "")
    body = dict(value); body.pop("record_sha256", None)
    if recorded != _digest(body):
        raise ProviderUsageError("provider usage runtime record integrity check failed")
    return value


def _write_state(root: Path, body: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(body); payload.pop("record_sha256", None); payload["record_sha256"] = _digest(payload)
    adoption.write_runtime_record(root, USAGE_STATE_RECORD, payload, actor="controller")
    return payload


def _valid_admission(record: Mapping[str, Any] | None, plan_hash: str | None) -> bool:
    row = record.get("admission") if isinstance(record, Mapping) and isinstance(record.get("admission"), Mapping) else {}
    return bool(
        plan_hash
        and row.get("schema") == USAGE_ADMISSION_SCHEMA
        and row.get("admitted") is True
        and row.get("plan_hash") == plan_hash
    )


def ensure_capacity(
    root: Path,
    *,
    plan_state: Mapping[str, Any] | None,
    model: str,
    reserve_percent: float,
    wait: bool,
    poll_seconds: int,
) -> dict[str, Any]:
    """Return current quota evidence or fail before any model turn.

    Approved-plan admission is durable in a separate controller-owned runtime
    record keyed to the exact plan hash.  Direct/planning turns have no latch
    and must satisfy reserve on every invocation.
    """
    plan_hash = str(plan_state.get("plan_hash") or "") if isinstance(plan_state, Mapping) else None
    while True:
        record = _state_record(root) or {
            "schema": USAGE_STATE_SCHEMA,
            "provider": provider_codex.PROVIDER_NAME,
            "plan_hash": plan_hash,
            "quota": None,
            "admission": None,
            "pause": None,
        }
        try:
            snapshot = provider_codex.rate_limits(root, model)
            admitted = _valid_admission(record, plan_hash)
            guard, findings = provider_codex.quota_guard(snapshot, float(reserve_percent), admitted=admitted)
        except provider_codex.ProviderError as exc:
            snapshot = {
                "schema": provider_codex.RATE_LIMIT_SCHEMA, "provider": provider_codex.PROVIDER_NAME,
                "model": model, "ordinary_usage_allowed": None, "windows": [],
                "available_reset_credits": None, "reset_credits": [], "snapshot_sha256": None,
            }
            guard, findings = "UNKNOWN", [f"rate-limit read failed: {exc}"]
        record.update({"schema": USAGE_STATE_SCHEMA, "provider": provider_codex.PROVIDER_NAME, "plan_hash": plan_hash, "quota": snapshot})

        if guard == "SAFE":
            if plan_hash and not _valid_admission(record, plan_hash):
                admission = {
                    "schema": USAGE_ADMISSION_SCHEMA, "admitted": True, "plan_hash": plan_hash,
                    "admitted_at": _utc_now(), "reserve_percent": float(reserve_percent),
                    "remaining_percent_at_admission": provider_codex.minimum_remaining(snapshot),
                    "quota_snapshot_sha256": snapshot.get("snapshot_sha256"),
                }
                admission["record_sha256"] = _digest(admission)
                record["admission"] = admission
            elif not plan_hash:
                record["admission"] = None
            record["pause"] = None
            persisted = _write_state(root, record)
            return {"guard": guard, "snapshot": snapshot, "admitted": _valid_admission(persisted, plan_hash), "findings": []}

        if guard == "ADMITTED":
            admission = dict(record.get("admission") or {})
            admission["last_below_reserve_at"] = _utc_now()
            admission["last_remaining_percent"] = provider_codex.minimum_remaining(snapshot)
            admission.pop("record_sha256", None); admission["record_sha256"] = _digest(admission)
            record["admission"] = admission; record["pause"] = None
            _write_state(root, record)
            return {"guard": guard, "snapshot": snapshot, "admitted": True, "findings": findings}

        pause = {
            "schema": USAGE_PAUSE_SCHEMA, "recorded_at": _utc_now(), "guard": guard,
            "plan_hash": plan_hash, "reserve_percent": float(reserve_percent),
            "findings": list(findings), "quota_snapshot": snapshot,
        }
        pause["record_sha256"] = _digest(pause)
        record["pause"] = pause
        # A different/new plan never inherits the old plan's admission latch.
        if not _valid_admission(record, plan_hash):
            record["admission"] = None
        _write_state(root, record)
        if not wait:
            raise ProviderUsageError("provider usage admission blocked: " + "; ".join(findings))
        delay = provider_codex.quota_poll_delay(snapshot, int(poll_seconds))
        try:
            time.sleep(delay)
        except KeyboardInterrupt as exc:
            raise ProviderUsageError("provider usage pause recorded; rerun to continue zero-model quota polling") from exc


def recorded_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    record = _state_record(root)
    return {"schema": "stygnox_provider_usage_recorded_status_v1", "worktree": str(root), "state": record}

def provider_status(project: Path, model: str | None = None) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    snapshot = provider_codex.rate_limits(root, model)
    return {"schema": "stygnox_provider_usage_status_v1", "provider": provider_codex.PROVIDER_NAME, "model_turn_executed": False, "quota": snapshot}


def build_reset_preview(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    preview = provider_codex.reset_credit_preview(root, operator)
    return {**preview, "worktree": str(root), "model_turn_executed": False}


def redeem_reset(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    result = provider_codex.redeem_reset_credit(root, operator, preview_sha256, confirmation)
    return {**result, "worktree": str(root), "model_turn_executed": False}


def cli_main(argv: list[str] | None = None) -> int:
    import argparse, sys
    parser = argparse.ArgumentParser(prog="stygnox provider-usage")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status"); status.add_argument("--model")
    preview = sub.add_parser("reset-preview"); preview.add_argument("--operator", required=True)
    redeem = sub.add_parser("redeem"); redeem.add_argument("--operator", required=True); redeem.add_argument("--preview", required=True); redeem.add_argument("--confirm", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status": result = provider_status(args.project, args.model)
        elif args.command == "reset-preview": result = build_reset_preview(args.project, args.operator)
        else: result = redeem_reset(args.project, args.operator, args.preview, args.confirm)
    except (ProviderUsageError, provider_codex.ProviderError, adoption.AdoptionError) as exc:
        print(f"stygnox: provider usage refused: {exc}", file=sys.stderr); return 2
    print(json.dumps(result, indent=2, sort_keys=True)); return 0
