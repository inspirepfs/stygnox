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
from typing import Any, Mapping


PROVIDER_NAME = "codex"
_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["PASS", "BLOCKED"]},
        "summary": {"type": "string"},
    },
    "required": ["status", "summary"],
}


class ProviderError(RuntimeError):
    """Fail-closed installed-provider error."""


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


def execute(
    *,
    cwd: Path,
    prompt: str,
    model: str,
    effort: str | None,
    repository_authority: str,
) -> dict[str, Any]:
    """Execute one explicitly-authorised Codex turn and return structured output."""
    if repository_authority not in {"read-only", "write"}:
        raise ProviderError("repository authority must be read-only or write")
    if not str(model or "").strip():
        raise ProviderError("Codex execution requires an explicitly reviewed model")
    _preflight(cwd)
    sandbox = "read-only" if repository_authority == "read-only" else "workspace-write"
    with tempfile.TemporaryDirectory(prefix="stygnox-codex-") as temp:
        base = Path(temp)
        schema_path = base / "schema.json"
        output_path = base / "result.json"
        schema_path.write_text(json.dumps(_RESULT_SCHEMA), encoding="utf-8")
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
        result = _run(command, cwd=cwd)
        if result.returncode != 0:
            detail = result.stdout[-4000:].strip() or f"exit={result.returncode}"
            raise ProviderError(f"Codex execution failed: {detail}")
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Codex returned invalid structured output: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ProviderError("Codex structured output must be a JSON object")
        status = str(payload.get("status") or "")
        summary = str(payload.get("summary") or "").strip()
        if status not in {"PASS", "BLOCKED"} or not summary:
            raise ProviderError("Codex structured output failed the Stygnox result contract")
        return {
            "provider": PROVIDER_NAME,
            "model": model,
            "effort": effort,
            "sandbox": sandbox,
            "status": status,
            "summary": summary,
        }
