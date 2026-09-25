"""Installed Codex provider adapter used by the neutral D8.5 controller.

This adapter is selected only by an explicitly reviewed tracked execution
policy.  Importing Stygnox never selects Codex, a model, or an effort level.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Mapping


PROVIDER_NAME = "codex"
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
