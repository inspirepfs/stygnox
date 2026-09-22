"""Standalone Codex subprocess boundary with injected controller dependencies."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable


def empty_codex_metrics() -> dict:
    return {
        "commands_executed": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }


def update_codex_metrics(metrics: dict, event: dict) -> None:
    event_type = str(event.get("type") or "")
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    if event_type == "item.completed" and str(item.get("type") or "") == "command_execution":
        metrics["commands_executed"] = int(metrics.get("commands_executed") or 0) + 1
    if event_type == "turn.completed":
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        for key in (
            "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens",
        ):
            metrics[key] = int(usage.get(key) or 0)


def stream_codex_process(
    args: list[str], *, cwd: Path, render_event: Callable[[dict], list[tuple[str, str]]],
    clip: Callable[[str, int], str], live_write: Callable[[str, str], None],
) -> tuple[int, str, dict]:
    """Run Codex while rendering its JSONL event stream for the operator."""
    proc = subprocess.Popen(
        args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
    )
    captured: list[str] = []
    metrics = empty_codex_metrics()
    assert proc.stdout is not None
    for raw in proc.stdout:
        captured.append(raw)
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            live_write(clip(stripped, 800), "CODEX")
            continue
        if isinstance(event, dict):
            update_codex_metrics(metrics, event)
            for category, message in render_event(event):
                if message:
                    live_write(message, category)
    return proc.wait(), "".join(captured), metrics


def is_bwrap_bootstrap_failure(output: str) -> bool:
    """Return True only for the known Codex Linux bubblewrap bootstrap failure."""
    text = output.lower()
    return "bwrap:" in text and any(
        marker in text
        for marker in (
            "failed rtm_newaddr",
            "setting up uid map: permission denied",
            "write failed /proc/self/uid_map",
        )
    )


def codex_environment_error_output(output: str) -> str:
    """Extract only process/turn errors eligible for sandbox classification."""
    errors: list[str] = []
    for raw in output.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            if is_bwrap_bootstrap_failure(stripped):
                errors.append(stripped)
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type == "turn.failed":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            message = str(error.get("message") or "").strip()
            if message:
                errors.append(message)
        elif event_type == "error":
            message = str(event.get("message") or "").strip()
            if message:
                errors.append(message)
    return "\n".join(errors)


class EnvironmentBlocked(RuntimeError):
    """Environment prerequisite failed; metrics are retained if a turn had already started."""

    def __init__(self, message: str, metrics: dict | None = None):
        super().__init__(message)
        self.metrics = dict(metrics or {})


def sandbox_prefix_from_preflights(default_returncode: int, default_output: str) -> list[str]:
    """Accept only the supported default sandbox backend for workspace-write."""
    if default_returncode == 0 and not is_bwrap_bootstrap_failure(default_output):
        return ["codex"]
    detail = default_output[-1200:] or f"exit={default_returncode}"
    raise EnvironmentBlocked(
        "Codex default Linux sandbox preflight failed; fix the host sandbox prerequisites before running RALPH: "
        + detail
    )


def codex_command_prefix(
    *, run_process: Callable[[list[str]], subprocess.CompletedProcess[str]],
    live_write: Callable[[str, str], None], which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Run a zero-model sandbox preflight and return the Codex process prefix."""
    if which("codex") is None:
        raise EnvironmentBlocked("codex CLI is not installed or not on PATH")
    default = run_process(["codex", "sandbox", "--", "/bin/true"])
    prefix = sandbox_prefix_from_preflights(default.returncode, default.stdout)
    live_write("sandbox preflight=PASS backend=default", "SANDBOX")
    return prefix


def run_codex(
    prompt: str, schema: dict, sandbox: str, *, cwd: Path, prefix: list[str],
    stream_process: Callable[[list[str]], tuple[int, str, dict]],
    normalize_failure: Callable[[str], str], clip: Callable[[str, int], str],
    live_write: Callable[[str, str], None], selected_model: str | None = None,
    selected_effort: str | None = None, context: str = "Codex",
    temporary_directory: Callable[..., tempfile.TemporaryDirectory] = tempfile.TemporaryDirectory,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    with temporary_directory(prefix="ralph-lite-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        output_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        command = [*prefix, "exec"]
        if selected_model:
            command += ["--model", selected_model]
        if selected_effort:
            command += ["--config", f'model_reasoning_effort="{selected_effort}"']
        command += [
            "--ephemeral", "--json", "--sandbox", sandbox,
            "--output-schema", str(schema_path), "-o", str(output_path), prompt,
        ]
        live_write(
            f"{context} · model={selected_model or 'codex-default'} · effort={selected_effort or 'codex-default'} "
            f"· sandbox={sandbox} backend=default",
            "CODEX",
        )
        started = monotonic()
        returncode, output, metrics = stream_process(command)
        metrics["codex_seconds"] = monotonic() - started

        environment_error = codex_environment_error_output(output)
        if is_bwrap_bootstrap_failure(environment_error):
            raise EnvironmentBlocked(
                "Codex default sandbox failed inside the model turn; automatic legacy fallback is disabled: "
                + normalize_failure(environment_error)[-1200:],
                metrics=metrics,
            )
        if returncode != 0:
            raise RuntimeError(f"codex exec failed ({returncode}):\n{output[-6000:]}")
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"codex returned invalid structured output: {exc}") from exc
        if isinstance(result, dict) and result.get("summary"):
            live_write(clip(result["summary"], 800), "SUMMARY")
        if isinstance(result, dict):
            result["_ralph_metrics"] = metrics
        return result
