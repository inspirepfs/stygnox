"""Installed Codex provider adapter used by the neutral D8.5 controller.

This adapter is selected only by an explicitly reviewed tracked execution
policy.  Importing Stygnox never selects Codex, a model, or an effort level.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Any, Mapping


PROVIDER_NAME = "codex"
MODEL_CATALOG_SCHEMA = "stygnox_codex_model_catalog_v1"
RATE_LIMIT_SCHEMA = "stygnox_codex_rate_limits_v1"
RESET_PREVIEW_SCHEMA = "stygnox_codex_reset_preview_v1"
RESET_RESULT_SCHEMA = "stygnox_codex_reset_result_v1"
APP_SERVER_TIMEOUT_SECONDS = 15.0
_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "BLOCKED"]},
        "summary": {"type": "string"},
        "blocker_class": {"type": "string", "enum": ["none", "validation-only", "continuation", "human-decision", "policy"]},
        "blockers": {"type": "array", "maxItems": 16, "items": {"type": "string"}},
        "validation_notes": {"type": "array", "maxItems": 16, "items": {"type": "string"}},
        "files_inspected": {"type": "array", "maxItems": 64, "items": {"type": "string"}},
    },
    "required": ["status", "summary", "blocker_class", "blockers", "validation_notes", "files_inspected"],
}


class ProviderError(RuntimeError):
    """Fail-closed installed-provider error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _app_server_send(handle: Any, payload: Mapping[str, Any]) -> None:
    handle.write(json.dumps(dict(payload), separators=(",", ":")) + "\n")
    handle.flush()


def _app_server_read_response(proc: subprocess.Popen[str], request_id: int, timeout: float) -> dict[str, Any]:
    if proc.stdout is None:
        raise ProviderError("Codex app-server stdout is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            events = selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, Mapping) or message.get("id") != request_id:
                continue
            if message.get("error"):
                raise ProviderError(f"Codex app-server request failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise ProviderError("Codex app-server returned an invalid result")
            return dict(result)
    finally:
        selector.close()
    stderr = ""
    if proc.poll() is not None and proc.stderr is not None:
        try:
            stderr = proc.stderr.read()[-1200:].strip()
        except OSError:
            pass
    detail = f": {stderr}" if stderr else ""
    raise ProviderError(f"timed out waiting for Codex app-server response{detail}")


def _normalise_model_catalog(raw: Mapping[str, Any]) -> dict[str, Any]:
    data = raw.get("data") if isinstance(raw.get("data"), list) else []
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            continue
        model_id = str(item.get("model") or item.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        efforts: list[str] = []
        for option in item.get("supportedReasoningEfforts") or []:
            if isinstance(option, Mapping):
                effort = str(option.get("reasoningEffort") or "").strip().lower()
                if effort and effort not in efforts:
                    efforts.append(effort)
        default_effort = item.get("defaultReasoningEffort")
        default_effort = str(default_effort).strip().lower() if default_effort is not None else None
        models.append({
            "id": model_id,
            "display_name": str(item.get("displayName") or model_id),
            "description": str(item.get("description") or ""),
            "is_default": bool(item.get("isDefault")),
            "reasoning_efforts": efforts,
            "default_reasoning_effort": default_effort or None,
        })
        seen.add(model_id)
    models.sort(key=lambda row: row["id"])
    if not models:
        raise ProviderError("Codex model catalogue is empty or invalid")
    body = {"schema": MODEL_CATALOG_SCHEMA, "provider": PROVIDER_NAME, "models": models}
    body["catalog_sha256"] = _digest(body)
    return body


def model_catalog(cwd: Path, *, timeout: float = APP_SERVER_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Read the supported Codex model/effort catalogue without executing a model turn."""
    codex = shutil.which("codex")
    if not codex:
        raise ProviderError("reviewed provider 'codex' is not installed or not on PATH")
    proc = subprocess.Popen(
        [codex, "app-server", "--stdio"],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        if proc.stdin is None:
            raise ProviderError("Codex app-server stdin is unavailable")
        _app_server_send(proc.stdin, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "clientInfo": {"name": "stygnox", "title": "Stygnox", "version": "13B-1"},
                "capabilities": {"experimentalApi": True},
            },
        })
        _app_server_read_response(proc, 1, timeout)
        _app_server_send(proc.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _app_server_send(proc.stdin, {
            "jsonrpc": "2.0", "id": 2, "method": "model/list",
            "params": {"limit": 100, "cursor": None, "includeHidden": False},
        })
        raw = _app_server_read_response(proc, 2, timeout)
        return _normalise_model_catalog(raw)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass



def _usage_window_name(minutes: int | None, fallback: str) -> str:
    if minutes is None:
        return fallback
    if 285 <= minutes <= 315:
        return "5h"
    if 9576 <= minutes <= 10584:
        return "weekly"
    if 1368 <= minutes <= 1512:
        return "daily"
    return f"{minutes}m"


def _normalise_rate_limits(raw: Mapping[str, Any], model: str | None = None) -> dict[str, Any]:
    by_id = raw.get("rateLimitsByLimitId") if isinstance(raw.get("rateLimitsByLimitId"), Mapping) else {}
    fallback = raw.get("rateLimits") if isinstance(raw.get("rateLimits"), Mapping) else None
    if not by_id and fallback:
        by_id = {str(fallback.get("limitId") or "codex"): fallback}
    windows: list[dict[str, Any]] = []
    plan_type = None
    for limit_id, snapshot in by_id.items():
        if not isinstance(snapshot, Mapping):
            continue
        if plan_type is None and snapshot.get("planType") is not None:
            plan_type = str(snapshot.get("planType"))
        relevant = str(limit_id).lower() == "codex"
        if model:
            relevant = relevant or snapshot.get("limitName") == model or snapshot.get("normalModelSlug") == model
        if not relevant:
            continue
        for slot in ("primary", "secondary"):
            window = snapshot.get(slot)
            if not isinstance(window, Mapping) or window.get("usedPercent") is None:
                continue
            try:
                used = max(0.0, min(100.0, float(window["usedPercent"])))
            except (TypeError, ValueError):
                continue
            try:
                minutes = int(window.get("windowDurationMins")) if window.get("windowDurationMins") is not None else None
            except (TypeError, ValueError):
                minutes = None
            try:
                reset = int(window.get("resetsAt")) if window.get("resetsAt") is not None else None
            except (TypeError, ValueError):
                reset = None
            windows.append({
                "limit_id": str(limit_id),
                "name": _usage_window_name(minutes, slot),
                "slot": slot,
                "used_percent": used,
                "remaining_percent": max(0.0, 100.0 - used),
                "window_minutes": minutes,
                "resets_at": reset,
            })
    windows.sort(key=lambda row: (row["limit_id"], row["slot"]))
    resets = raw.get("rateLimitResetCredits") if isinstance(raw.get("rateLimitResetCredits"), Mapping) else {}
    try:
        available = int(resets.get("availableCount")) if resets.get("availableCount") is not None else None
    except (TypeError, ValueError):
        available = None
    credits: list[dict[str, Any]] = []
    for item in resets.get("credits") or []:
        if not isinstance(item, Mapping):
            continue
        try:
            granted = int(item.get("grantedAt")) if item.get("grantedAt") is not None else None
        except (TypeError, ValueError):
            granted = None
        try:
            expires = int(item.get("expiresAt")) if item.get("expiresAt") is not None else None
        except (TypeError, ValueError):
            expires = None
        # The provider credit identifier is retained only as a one-way fingerprint.
        # Redemption deliberately asks Codex to choose the currently available credit.
        raw_id = str(item.get("id") or "")
        credits.append({
            "credit_ref": hashlib.sha256(raw_id.encode("utf-8")).hexdigest() if raw_id else None,
            "status": str(item.get("status") or "unknown"),
            "reset_type": str(item.get("resetType") or "unknown"),
            "granted_at": granted,
            "expires_at": expires,
            "title": str(item.get("title") or "Banked reset"),
            "description": str(item.get("description") or ""),
        })
    credits.sort(key=lambda row: (row.get("expires_at") is None, int(row.get("expires_at") or 2**62)))
    body: dict[str, Any] = {
        "schema": RATE_LIMIT_SCHEMA,
        "provider": PROVIDER_NAME,
        "model": model,
        "plan_type": plan_type,
        "ordinary_usage_allowed": raw.get("ordinaryUsageAllowed") if isinstance(raw.get("ordinaryUsageAllowed"), bool) else None,
        "windows": windows,
        "available_reset_credits": available,
        "reset_credits": credits,
    }
    body["snapshot_sha256"] = _digest(body)
    return body


def _app_server_request(cwd: Path, method: str, *, params: Mapping[str, Any] | None = None, timeout: float = APP_SERVER_TIMEOUT_SECONDS) -> dict[str, Any]:
    codex = shutil.which("codex")
    if not codex:
        raise ProviderError("reviewed provider 'codex' is not installed or not on PATH")
    proc = subprocess.Popen(
        [codex, "app-server", "--stdio"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    try:
        if proc.stdin is None:
            raise ProviderError("Codex app-server stdin is unavailable")
        _app_server_send(proc.stdin, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientInfo": {"name": "stygnox", "title": "Stygnox", "version": "13B-2"}, "capabilities": {"experimentalApi": True}},
        })
        _app_server_read_response(proc, 1, timeout)
        _app_server_send(proc.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": method}
        if params is not None:
            request["params"] = dict(params)
        _app_server_send(proc.stdin, request)
        return _app_server_read_response(proc, 2, timeout)
    finally:
        try:
            proc.terminate(); proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try: proc.kill()
            except OSError: pass


def rate_limits(cwd: Path, model: str | None = None, *, timeout: float = APP_SERVER_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Read non-sensitive Codex quota/reset metadata without executing a model turn."""
    return _normalise_rate_limits(_app_server_request(cwd, "account/rateLimits/read", timeout=timeout), model)


def quota_guard(snapshot: Mapping[str, Any], reserve_percent: float, *, admitted: bool = False) -> tuple[str, list[str]]:
    ordinary = snapshot.get("ordinary_usage_allowed")
    windows = snapshot.get("windows") if isinstance(snapshot.get("windows"), list) else []
    if ordinary is False:
        return "PAUSE", ["backend ordinary usage is not allowed"]
    if ordinary is None:
        return "UNKNOWN", ["backend ordinaryUsageAllowed is unavailable"]
    if not windows:
        return "UNKNOWN", ["no relevant Codex rate-limit windows were returned"]
    low = [row for row in windows if isinstance(row, Mapping) and float(row.get("remaining_percent", 100.0)) <= reserve_percent]
    if low:
        findings = [f"{row.get('name', 'usage')} remaining {float(row.get('remaining_percent', 0.0)):.1f}% <= {reserve_percent:.1f}% reserve" for row in low]
        return ("ADMITTED", findings) if admitted else ("PAUSE", findings)
    return "SAFE", []


def minimum_remaining(snapshot: Mapping[str, Any]) -> float | None:
    windows = snapshot.get("windows") if isinstance(snapshot.get("windows"), list) else []
    values = [float(row.get("remaining_percent", 100.0)) for row in windows if isinstance(row, Mapping)]
    return min(values) if values else None


def quota_poll_delay(snapshot: Mapping[str, Any], default_seconds: int) -> int:
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    resets = [int(row["resets_at"]) for row in snapshot.get("windows", []) if isinstance(row, Mapping) and isinstance(row.get("resets_at"), int) and int(row["resets_at"]) > now]
    if not resets:
        return max(15, int(default_seconds))
    return max(15, min(int(default_seconds), min(resets) - now + 5))


def reset_credit_preview(cwd: Path, operator: str) -> dict[str, Any]:
    snapshot = rate_limits(cwd)
    available = snapshot.get("available_reset_credits")
    if not isinstance(available, int) or available < 1:
        raise ProviderError("no banked Codex reset credit is currently available")
    body = {
        "schema": RESET_PREVIEW_SCHEMA,
        "provider": PROVIDER_NAME,
        "operator": str(operator or "").strip(),
        "quota_snapshot_sha256": snapshot["snapshot_sha256"],
        "available_reset_credits": available,
        "reset_credits": snapshot.get("reset_credits") or [],
        "requires_explicit_confirmation": True,
        "confirmation": "REDEEM",
    }
    body["preview_sha256"] = _digest(body)
    return body


def redeem_reset_credit(cwd: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "REDEEM":
        raise ProviderError("explicit confirmation required: --confirm REDEEM")
    preview = reset_credit_preview(cwd, operator)
    if str(preview_sha256 or "").strip().lower() != preview["preview_sha256"]:
        raise ProviderError("reset-credit preview is stale; provider quota/reset evidence changed")
    result = _app_server_request(
        cwd,
        "account/rateLimitResetCredit/consume",
        params={"idempotencyKey": str(uuid.uuid4())},
    )
    outcome = str(result.get("outcome") or "unknown")
    if outcome not in {"reset", "nothingToReset", "noCredit", "alreadyRedeemed"}:
        raise ProviderError(f"unexpected banked-reset outcome: {outcome}")
    refreshed = rate_limits(cwd)
    body = {
        "schema": RESET_RESULT_SCHEMA,
        "provider": PROVIDER_NAME,
        "operator": str(operator or "").strip(),
        "outcome": outcome,
        "before_snapshot_sha256": preview["quota_snapshot_sha256"],
        "after": refreshed,
    }
    body["result_sha256"] = _digest(body)
    return body


def selection_from_catalog(catalog: Mapping[str, Any], model: str, effort: str | None) -> dict[str, Any]:
    """Validate one model/effort pair against already-read provider metadata."""
    if catalog.get("schema") != MODEL_CATALOG_SCHEMA or catalog.get("provider") != PROVIDER_NAME:
        raise ProviderError("Codex model catalogue has an unsupported schema or provider")
    models = catalog.get("models") if isinstance(catalog.get("models"), list) else []
    matches = [row for row in models if isinstance(row, Mapping) and row.get("id") == model]
    if len(matches) != 1:
        raise ProviderError(f"Codex model is not advertised by the current catalogue: {model}")
    selected = dict(matches[0])
    efforts = [str(value).lower() for value in selected.get("reasoning_efforts") or []]
    selected_effort = str(effort or "").strip().lower() or None
    if selected_effort and not efforts:
        raise ProviderError(f"Codex model {model} advertises no selectable reasoning efforts")
    if selected_effort and selected_effort not in efforts:
        raise ProviderError(
            f"Codex effort {selected_effort!r} is not supported by model {model}; supported: {', '.join(efforts)}"
        )
    return {
        "schema": "stygnox_codex_model_selection_v1",
        "provider": PROVIDER_NAME,
        "catalog_sha256": catalog["catalog_sha256"],
        "model": selected,
        "selected_model": model,
        "selected_effort": selected_effort,
    }


def validate_model_selection(cwd: Path, model: str, effort: str | None) -> dict[str, Any]:
    """Bind an exact Codex model/effort selection to current provider metadata."""
    return selection_from_catalog(model_catalog(cwd), model, effort)


def _empty_metrics() -> dict[str, int | float]:
    """Return the neutral metric shape retained from the historical provider boundary."""
    return {
        "commands_executed": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "codex_seconds": 0.0,
    }


def _update_metrics(metrics: dict[str, int | float], event: Mapping[str, Any]) -> None:
    """Accumulate command count and latest completed-turn usage from one Codex event."""
    event_type = str(event.get("type") or "")
    item = event.get("item") if isinstance(event.get("item"), Mapping) else {}
    if event_type == "item.completed" and str(item.get("type") or "") == "command_execution":
        metrics["commands_executed"] = int(metrics.get("commands_executed") or 0) + 1
    if event_type == "turn.completed":
        usage = event.get("usage") if isinstance(event.get("usage"), Mapping) else {}
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ):
            metrics[key] = int(usage.get(key) or 0)


def _metrics_from_jsonl(output: str) -> dict[str, int | float]:
    """Parse Codex JSONL without allowing malformed operator output to break execution."""
    metrics = _empty_metrics()
    for raw in str(output or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, Mapping):
            _update_metrics(metrics, event)
    return metrics


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _preflight(cwd: Path) -> None:
    if shutil.which("codex") is None:
        raise ProviderError("reviewed provider 'codex' is not installed or not on PATH")
    result = _run(["codex", "sandbox", "--", "/bin/true"], cwd=cwd)
    if result.returncode != 0:
        detail = result.stdout[-1200:].strip() or f"exit={result.returncode}"
        raise ProviderError(f"Codex sandbox preflight failed: {detail}")


def execute_structured(
    *,
    cwd: Path,
    prompt: str,
    model: str,
    effort: str | None,
    repository_authority: str,
    result_schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one explicitly-authorised Codex turn against a caller-owned JSON schema."""
    if repository_authority not in {"read-only", "write"}:
        raise ProviderError("repository authority must be read-only or write")
    if not str(model or "").strip():
        raise ProviderError("Codex execution requires an explicitly reviewed model")
    if not isinstance(result_schema, Mapping):
        raise ProviderError("Codex structured execution requires a JSON schema object")
    # Provider metadata is revalidated immediately before execution.  A tracked
    # review never grants permanent authority to a model/effort pair that the
    # current Codex installation no longer advertises.
    validate_model_selection(cwd, model, effort)
    _preflight(cwd)
    sandbox = "read-only" if repository_authority == "read-only" else "workspace-write"
    with tempfile.TemporaryDirectory(prefix="stygnox-codex-") as temp:
        base = Path(temp)
        schema_path = base / "schema.json"
        output_path = base / "result.json"
        schema_path.write_text(json.dumps(dict(result_schema)), encoding="utf-8")
        command = ["codex", "exec", "--model", model]
        if effort:
            command += ["--config", f'model_reasoning_effort="{effort}"']
        command += [
            "--ephemeral",
            "--json",
            "--sandbox",
            sandbox,
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            prompt,
        ]
        started = time.monotonic()
        result = _run(command, cwd=cwd)
        metrics = _metrics_from_jsonl(result.stdout)
        metrics["codex_seconds"] = max(0.0, time.monotonic() - started)
        if result.returncode != 0:
            detail = result.stdout[-4000:].strip() or f"exit={result.returncode}"
            raise ProviderError(f"Codex execution failed: {detail}")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Codex returned invalid structured output: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ProviderError("Codex structured output must be a JSON object")
        return {
            "provider": PROVIDER_NAME,
            "model": model,
            "effort": effort,
            "sandbox": sandbox,
            "payload": dict(payload),
            "metrics": metrics,
        }


def execute(
    *,
    cwd: Path,
    prompt: str,
    model: str,
    effort: str | None,
    repository_authority: str,
) -> dict[str, Any]:
    """Execute one explicitly-authorised implementation turn and return the Stygnox result contract."""
    structured = execute_structured(
        cwd=cwd,
        prompt=prompt,
        model=model,
        effort=effort,
        repository_authority=repository_authority,
        result_schema=_RESULT_SCHEMA,
    )
    payload = structured["payload"]
    status = str(payload.get("status") or "")
    summary = str(payload.get("summary") or "").strip()
    blocker_class = str(payload.get("blocker_class") or "")
    raw_blockers = payload.get("blockers")
    blockers = [str(item).strip() for item in raw_blockers] if isinstance(raw_blockers, list) else []
    raw_validation = payload.get("validation_notes")
    validation_notes = [str(item).strip() for item in raw_validation] if isinstance(raw_validation, list) else []
    raw_files = payload.get("files_inspected")
    files_inspected = [str(item).strip() for item in raw_files] if isinstance(raw_files, list) else []
    if any(not item for item in [*blockers, *validation_notes, *files_inspected]):
        raise ProviderError("Codex structured output contains an empty list entry")
    if (
        status not in {"PASS", "BLOCKED"}
        or not summary
        or blocker_class not in {"none", "validation-only", "continuation", "human-decision", "policy"}
        or not isinstance(raw_blockers, list)
        or not isinstance(raw_validation, list)
        or not isinstance(raw_files, list)
    ):
        raise ProviderError("Codex structured output failed the Stygnox result contract")
    if blocker_class == "continuation" and status != "PASS":
        raise ProviderError("ordinary continuation must use status PASS and blocker_class continuation")
    if status == "BLOCKED" and blocker_class == "continuation":
        raise ProviderError("blocked provider results cannot claim ordinary continuation")
    metrics = dict(structured["metrics"])
    metrics["files_inspected"] = len(files_inspected)
    return {
        "provider": structured["provider"],
        "model": structured["model"],
        "effort": structured["effort"],
        "sandbox": structured["sandbox"],
        "status": status,
        "summary": summary,
        "blocker_class": blocker_class,
        "blockers": blockers,
        "validation_notes": validation_notes,
        "files_inspected": files_inspected,
        "metrics": metrics,
    }
