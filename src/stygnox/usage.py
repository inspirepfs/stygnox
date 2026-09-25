"""Installed Stygnox local usage accounting.

The usage ledger is controller-owned runtime evidence. It records bounded execution
metrics only: no prompts, model output, credentials, account identifiers, or
provider quota mutations. Local reset semantics move the reporting baseline
without deleting history or touching provider-side quota/reset state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence

from . import adoption
from .product import PRODUCT


USAGE_TURN_SCHEMA = "stygnox_usage_turn_v1"
USAGE_RESET_SCHEMA = "stygnox_usage_stats_reset_v1"
USAGE_RESET_PREVIEW_SCHEMA = "stygnox_usage_reset_preview_v1"
USAGE_REPORT_SCHEMA = "stygnox_usage_report_v1"
USAGE_LEDGER_NAME = "usage-ledger.jsonl"
USAGE_RESET_NAME = "usage-stats-reset.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


class UsageError(RuntimeError):
    """Fail-closed local usage-accounting error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _runtime(root: Path, *, create: bool = False) -> Path:
    runtime = root.resolve() / adoption.RUNTIME_NAME
    if runtime.exists() and (runtime.is_symlink() or not runtime.is_dir()):
        raise UsageError(f"Stygnox runtime must be a real directory: {runtime}")
    if create and not runtime.exists():
        runtime.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(runtime, 0o700)
    return runtime


def _ledger_path(root: Path, *, create_runtime: bool = False) -> Path:
    return _runtime(root, create=create_runtime) / USAGE_LEDGER_NAME


def _reset_path(root: Path) -> Path:
    return _runtime(root) / USAGE_RESET_NAME


def _normalise_metrics(value: Mapping[str, Any] | None) -> dict[str, int | float]:
    metrics = dict(value or {})
    output: dict[str, int | float] = {
        "commands_executed": max(0, int(metrics.get("commands_executed") or 0)),
        "codex_seconds": max(0.0, float(metrics.get("codex_seconds") or 0.0)),
    }
    for key in _TOKEN_KEYS:
        output[key] = max(0, int(metrics.get(key) or 0))
    return output


def _append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise UsageError(f"usage ledger must be a regular file: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise UsageError(f"unable to open usage ledger: {exc}") from exc
    try:
        os.chmod(path, 0o600)
        payload = json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        with os.fdopen(fd, "a", encoding="utf-8", closefd=True) as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise UsageError(f"unable to append usage ledger: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def record_controller_turn(
    project: Path,
    *,
    preview_sha256: str,
    transaction_id: str,
    repository_authority: str,
    provider_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one completed installed-provider turn to durable local accounting."""
    root = adoption.resolve_worktree(project)
    preview = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(preview):
        raise UsageError("usage accounting requires the exact 64-character preview SHA-256")
    recorded_ns = time.time_ns()
    metrics = _normalise_metrics(provider_result.get("metrics") if isinstance(provider_result, Mapping) else None)
    row: dict[str, Any] = {
        "schema": USAGE_TURN_SCHEMA,
        "product_version": PRODUCT.version,
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "recorded_ns": recorded_ns,
        "preview_sha256": preview,
        "transaction_id": str(transaction_id or "") or None,
        "repository_authority": str(repository_authority or "") or None,
        "provider": str(provider_result.get("provider") or "") or None,
        "model": str(provider_result.get("model") or "") or None,
        "effort": provider_result.get("effort"),
        **metrics,
    }
    row["record_sha256"] = _digest(row)
    _append_jsonl(_ledger_path(root, create_runtime=True), row)
    return row


def _reset_info(root: Path) -> dict[str, Any]:
    path = _reset_path(root)
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise UsageError(f"usage reset marker must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"invalid usage reset marker: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != USAGE_RESET_SCHEMA:
        raise UsageError("unsupported usage reset marker schema")
    return value


def _row_recorded_ns(row: Mapping[str, Any]) -> int:
    try:
        if row.get("recorded_ns") is not None:
            return max(0, int(row.get("recorded_ns") or 0))
        return max(0, int(row.get("epoch") or 0)) * 1_000_000_000
    except (TypeError, ValueError):
        return 0


def usage_rows(project: Path, *, include_before_reset: bool = False) -> list[dict[str, Any]]:
    root = adoption.resolve_worktree(project)
    path = _ledger_path(root)
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise UsageError(f"usage ledger must be a regular file: {path}")
    cutoff = 0 if include_before_reset else int(_reset_info(root).get("cutoff_ns") or 0)
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise UsageError(f"unable to read usage ledger: {exc}") from exc
    for raw in lines:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("schema") != USAGE_TURN_SCHEMA:
            continue
        if cutoff and _row_recorded_ns(item) <= cutoff:
            continue
        rows.append(item)
    return rows


def _sum_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, int | float]:
    total: dict[str, int | float] = {
        "turns": 0,
        "commands_executed": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "codex_seconds": 0.0,
    }
    for row in rows:
        total["turns"] = int(total["turns"]) + 1
        total["commands_executed"] = int(total["commands_executed"]) + max(0, int(row.get("commands_executed") or 0))
        for key in _TOKEN_KEYS:
            total[key] = int(total[key]) + max(0, int(row.get(key) or 0))
        total["codex_seconds"] = float(total["codex_seconds"]) + max(0.0, float(row.get("codex_seconds") or 0.0))
    total["noncached_input_tokens"] = max(0, int(total["input_tokens"]) - int(total["cached_input_tokens"]))
    total["total_tokens"] = int(total["input_tokens"]) + int(total["output_tokens"])
    return total


def usage_report(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    all_rows = usage_rows(root, include_before_reset=True)
    since_reset = usage_rows(root, include_before_reset=False)
    return {
        "schema": USAGE_REPORT_SCHEMA,
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "stats_reset": _reset_info(root) or None,
        "since_reset": _sum_rows(since_reset),
        "all_time": _sum_rows(all_rows),
        "provider_quota_mutated": False,
        "banked_reset_mutated": False,
        "ledger_retained": True,
    }


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise UsageError(f"usage evidence must be a regular file: {path}")
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise UsageError(f"unable to fingerprint usage evidence: {exc}") from exc


def build_reset_preview(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    all_rows = usage_rows(root, include_before_reset=True)
    current_rows = usage_rows(root, include_before_reset=False)
    body: dict[str, Any] = {
        "schema": USAGE_RESET_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "ledger_sha256": _file_sha256(_ledger_path(root)),
        "reset_marker_sha256": _file_sha256(_reset_path(root)),
        "cutoff_ns": max((_row_recorded_ns(row) for row in all_rows), default=0),
        "all_time": _sum_rows(all_rows),
        "current_since_reset": _sum_rows(current_rows),
        "effect": "move-local-statistics-baseline-only",
        "provider_quota_mutated": False,
        "banked_reset_mutated": False,
        "ledger_deleted": False,
        "requires_explicit_confirmation": True,
        "confirmation": "RESET",
    }
    body["preview_sha256"] = _digest(body)
    return body


def reset_usage_statistics(project: Path, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "RESET":
        raise UsageError("explicit confirmation required: --confirm RESET")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise UsageError("--preview must be the exact 64-character preview SHA-256")
    root = adoption.resolve_worktree(project)
    preview = build_reset_preview(root)
    if preview["preview_sha256"] != expected:
        raise UsageError("usage reset preview is stale; usage evidence changed, preview again")
    now = dt.datetime.now(dt.timezone.utc)
    marker: dict[str, Any] = {
        "schema": USAGE_RESET_SCHEMA,
        "product_version": PRODUCT.version,
        "reset_at": now.isoformat(),
        "cutoff_ns": int(preview.get("cutoff_ns") or 0),
        "preview_sha256": expected,
        "provider_quota_mutated": False,
        "banked_reset_mutated": False,
        "ledger_deleted": False,
    }
    marker["record_sha256"] = _digest(marker)
    adoption.write_runtime_record(root, USAGE_RESET_NAME, marker, actor="controller")
    return {**marker, "result": "LOCAL_USAGE_BASELINE_RESET"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox usage",
        description="Read/reset local Stygnox execution accounting without touching provider quota or banked resets.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show", help="show local execution accounting")
    show.add_argument("--project", type=Path, default=Path.cwd())
    preview = sub.add_parser("reset-preview", help="preview a local statistics-baseline reset")
    preview.add_argument("--project", type=Path, default=Path.cwd())
    reset = sub.add_parser("reset", help="reset the local statistics baseline only")
    reset.add_argument("--project", type=Path, default=Path.cwd())
    reset.add_argument("--preview", required=True)
    reset.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "show":
            result = usage_report(args.project)
        elif args.action == "reset-preview":
            result = build_reset_preview(args.project)
        else:
            result = reset_usage_statistics(args.project, args.preview, args.confirm)
    except (UsageError, adoption.AdoptionError, OSError, ValueError) as exc:
        print(f"stygnox: usage refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
