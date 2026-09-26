"""Installed Codex provider adapter used by the neutral D8.5 controller.

This adapter is selected only by an explicitly reviewed tracked execution
policy.  Importing Stygnox never selects Codex, a model, or an effort level.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time
from typing import Any, Mapping


PROVIDER_NAME = "codex"
MODEL_CATALOG_SCHEMA = "stygnox_codex_model_catalog_v1"
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
