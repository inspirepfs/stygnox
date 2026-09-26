"""Installed Stygnox terminal operator surface for D8.6B.

The TUI is deliberately zero-dependency and presentation-only.  All state and
mutating semantics come from :mod:`stygnox.operator`; no legacy/source-tree
RALPH TUI/controller module is imported or delegated to.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import textwrap
from typing import Any, Mapping, Sequence

from importlib import resources

from . import operator
from .product import PRODUCT

TUI_SCHEMA = "stygnox_tui_v1"

# Approved brand-token colours from branding/design-tokens.json.
ANSI = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "purple": "\x1b[38;2;175;118;240m",
    "text": "\x1b[38;2;242;244;248m",
    "muted": "\x1b[38;2;154;168;190m",
    "success": "\x1b[38;2;95;213;151m",
    "warning": "\x1b[38;2;251;191;36m",
    "danger": "\x1b[38;2;248;113;113m",
    "info": "\x1b[38;2;126;168;255m",
}


class TuiError(RuntimeError):
    """Fail-closed installed TUI error."""


def _asset(name: str) -> str:
    if name not in {"stygnox-ascii.txt", "stygnox-ascii-ansi.txt"}:
        raise TuiError(f"unknown packaged terminal asset: {name}")
    return resources.files("stygnox.terminal_assets").joinpath(name).read_text(encoding="utf-8")


def color_enabled(mode: str, stream: Any = None) -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    if mode == "always":
        return True
    if mode == "never":
        return False
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)())


def _paint(text: str, tone: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{ANSI.get(tone, '')}{text}{ANSI['reset']}"


def _value(record: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    cur: Any = record
    for key in keys:
        if not isinstance(cur, Mapping):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _state(record: Mapping[str, Any] | None, *, default: str = "-") -> str:
    if not isinstance(record, Mapping):
        return default
    for key in ("state", "status", "result"):
        value = record.get(key)
        if value not in {None, ""}:
            return str(value)
    return default


def _clip(text: Any, width: int) -> str:
    value = " ".join(str(text if text is not None else "-").split())
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3] + "..."


def _wrap(prefix: str, text: str, width: int) -> list[str]:
    usable = max(16, width - len(prefix))
    parts = textwrap.wrap(str(text), width=usable, replace_whitespace=True, drop_whitespace=True) or [""]
    return [prefix + parts[0], *[(" " * len(prefix)) + part for part in parts[1:]]]


def _brand(*, color: bool, width: int) -> str:
    # The approved full identity is 67 columns. Narrow terminals get a compact,
    # non-destructive product header rather than clipped artwork.
    if width < 72:
        return _paint(f"Stygnox {PRODUCT.version} · PLAN - EXECUTE - EVIDENCE - EVOLVE", "purple", color)
    return _asset("stygnox-ascii-ansi.txt" if color else "stygnox-ascii.txt").rstrip("\n")


def _section(title: str, rows: list[str], *, width: int, color: bool, tone: str = "purple") -> list[str]:
    rule_width = max(12, min(width, 100))
    heading = _paint(title, tone, color)
    return [heading, _paint("─" * rule_width, "dim", color), *rows]


def render_snapshot(snapshot: Mapping[str, Any], *, color_mode: str = "auto", width: int | None = None, stream: Any = None) -> str:
    if snapshot.get("schema") != operator.OPERATOR_SNAPSHOT_SCHEMA:
        raise TuiError("unsupported operator snapshot schema")
    stream = stream or sys.stdout
    enabled = color_enabled(color_mode, stream)
    columns = int(width or shutil.get_terminal_size(fallback=(100, 24)).columns)
    columns = max(40, min(columns, 160))

    adopted = bool(snapshot.get("adopted"))
    tx = snapshot.get("transaction") if isinstance(snapshot.get("transaction"), Mapping) else None
    ctl = snapshot.get("controller") if isinstance(snapshot.get("controller"), Mapping) else None
    policy = snapshot.get("execution_policy") if isinstance(snapshot.get("execution_policy"), Mapping) else None
    attribution = snapshot.get("attribution") if isinstance(snapshot.get("attribution"), Mapping) else {}
    cats = attribution.get("categories") if isinstance(attribution.get("categories"), Mapping) else {}
    evidence = snapshot.get("evidence_summary") if isinstance(snapshot.get("evidence_summary"), Mapping) else {}

    enabled_ctl = bool(_value(ctl, "controller_execution_enabled", default=False))
    controller_label = "ENABLED" if enabled_ctl else "DISABLED"
    controller_tone = "success" if enabled_ctl else "muted"
    adopted_label = "ADOPTED" if adopted else "NOT ADOPTED"
    adopted_tone = "success" if adopted else "warning"

    lines: list[str] = [_brand(color=enabled, width=columns), ""]
    identity_rows = [
        f"Product    {snapshot.get('identity')} {snapshot.get('product_version')}",
        f"Profile    {_value(snapshot.get('profile'), 'name', default='stygnox-default')}",
        f"Project    {_clip(snapshot.get('worktree'), max(12, columns - 11))}",
        f"Authority  {_paint(adopted_label, adopted_tone, enabled)} · controller {_paint(controller_label, controller_tone, enabled)}",
        f"Transaction {_state(tx)}",
    ]
    lines.extend(_section("OPERATOR STATE", identity_rows, width=columns, color=enabled))

    provider = _value(policy, "policy", "provider", default=_value(policy, "provider", default="neutral"))
    model = _value(policy, "policy", "model", default=_value(policy, "model", default="neutral"))
    effort = _value(policy, "policy", "effort", default=_value(policy, "effort", default="neutral"))
    mode = _value(policy, "policy", "efficiency_mode", default=_value(policy, "efficiency_mode", default="-"))
    reserve = _value(policy, "policy", "reserve_percent", default=_value(policy, "reserve_percent", default="-"))
    wait_limits = _value(policy, "policy", "wait_for_limits", default=_value(policy, "wait_for_limits", default="-"))
    max_loops = _value(policy, "policy", "max_loops", default=_value(policy, "max_loops", default="-"))
    policy_rows = [
        f"Provider   {provider or 'neutral'}",
        f"Model      {model or 'neutral'}",
        f"Effort     {effort or 'neutral'}",
        f"Efficiency {mode} · reserve {reserve}% · wait-limits {wait_limits} · max-loops {max_loops}",
    ]
    lines += [""] + _section("EXECUTION POLICY", policy_rows, width=columns, color=enabled, tone="info")

    def count(name: str) -> int:
        row = cats.get(name) if isinstance(cats, Mapping) else None
        return int(row.get("count", 0)) if isinstance(row, Mapping) else 0

    unresolved = count("unresolved")
    external = count("external")
    recon_rows = [
        f"Operator baseline {count('operator_baseline'):>3}   Stygnox native {count('controller_native'):>3}",
        f"Runtime-only      {count('runtime_only'):>3}   External       {external:>3}",
        f"Unresolved        {unresolved:>3}",
        "Auto-adopt NO · Auto-reattribute NO",
    ]
    if unresolved or external:
        recon_rows.append(_paint("[HUMAN] external/unresolved material requires operator decision", "warning", enabled))
    else:
        recon_rows.append(_paint("[OK] no unresolved reconciliation decision", "success", enabled))
    lines += [""] + _section("CHANGE ATTRIBUTION", recon_rows, width=columns, color=enabled, tone="purple")

    evidence_rows = [
        f"Runtime files       {evidence.get('runtime_files', 0)}",
        f"Controller receipts {evidence.get('latest_controller_receipts', 0)}",
        f"Source-tree fallback {'NO' if evidence.get('source_tree_dependency') is False else 'UNKNOWN'}",
        f"Legacy delegate      {'NO' if evidence.get('legacy_ralph_delegate') is False else 'UNKNOWN'}",
    ]
    lines += [""] + _section("EVIDENCE", evidence_rows, width=columns, color=enabled, tone="muted")

    lifecycle = snapshot.get("lifecycle") if isinstance(snapshot.get("lifecycle"), Mapping) else {}
    if lifecycle:
        phase = str(lifecycle.get("phase") or "UNKNOWN")
        attention = bool(lifecycle.get("attention_required"))
        phase_tone = "warning" if attention else ("success" if phase in {"PUSHED", "READ_ONLY_COMPLETE"} else "info")
        progress = lifecycle.get("progress") if isinstance(lifecycle.get("progress"), Mapping) else {}
        current = progress.get("current") if isinstance(progress.get("current"), Mapping) else {}
        lifecycle_rows = [
            f"Phase      {_paint(phase, phase_tone, enabled)}",
            f"Progress   {progress.get('completed_steps', 0)}/{progress.get('total_steps', 0)} · {progress.get('percent_complete', 0)}%",
            f"Step       {progress.get('current_step') or '-'} · {_clip(current.get('title') or current.get('objective') or '-', max(12, columns - 18))}",
            f"Attention  {'YES' if attention else 'NO'}",
        ]
        lines += [""] + _section("LIFECYCLE", lifecycle_rows, width=columns, color=enabled, tone="purple")

        blockers = lifecycle.get("blockers") if isinstance(lifecycle.get("blockers"), list) else []
        blocker_rows: list[str] = []
        for item in blockers[:8]:
            if isinstance(item, Mapping):
                code = str(item.get("code") or "BLOCKER")
                detail = item.get("detail") or item.get("gate_id") or item.get("pending_paths") or "operator attention required"
                blocker_rows.extend(_wrap("• ", f"{code} · {detail}", columns))
        if not blocker_rows:
            blocker_rows = [_paint("[OK] no lifecycle blockers", "success", enabled)]
        lines += [""] + _section("BLOCKERS", blocker_rows, width=columns, color=enabled, tone="warning" if blockers else "success")

        actions = lifecycle.get("next_actions") if isinstance(lifecycle.get("next_actions"), list) else []
        action_rows: list[str] = []
        for item in actions[:10]:
            if isinstance(item, Mapping):
                action_rows.extend(_wrap("• ", f"{item.get('action', '-')} · {item.get('reason', '')}", columns))
        if not action_rows:
            action_rows = [_paint("[NONE] no authority-valid next action", "muted", enabled)]
        lines += [""] + _section("NEXT ACTIONS", action_rows, width=columns, color=enabled, tone="info")

        recon = lifecycle.get("reconciliation") if isinstance(lifecycle.get("reconciliation"), Mapping) else {}
        gate = lifecycle.get("human_gate") if isinstance(lifecycle.get("human_gate"), Mapping) else {}
        gate_record = gate.get("gate") if isinstance(gate.get("gate"), Mapping) else {}
        selfdev = lifecycle.get("self_development") if isinstance(lifecycle.get("self_development"), Mapping) else {}
        recovery = lifecycle.get("recovery") if isinstance(lifecycle.get("recovery"), Mapping) else {}
        authority_rows = [
            f"Gate       {gate_record.get('gate_id') or '-'} · {gate_record.get('kind') or '-'}",
            f"Recovery   {'REQUIRED' if recovery.get('required') else 'clear'} · transaction {recovery.get('transaction_state') or '-'}",
            f"Reconcile  pending {len(recon.get('pending_paths') or [])} · stale {len(recon.get('stale_paths') or [])}",
            f"Self-dev   {'ACTIVE' if selfdev.get('active_grant') else 'none'} · history {selfdev.get('grant_history_count', 0)}",
        ]
        lines += [""] + _section("AUTHORITY & RECOVERY", authority_rows, width=columns, color=enabled, tone="info")

        qual = lifecycle.get("qualification") if isinstance(lifecycle.get("qualification"), Mapping) else {}
        fin = lifecycle.get("finalization") if isinstance(lifecycle.get("finalization"), Mapping) else {}
        usage = lifecycle.get("usage") if isinstance(lifecycle.get("usage"), Mapping) else {}
        eff = lifecycle.get("efficiency") if isinstance(lifecycle.get("efficiency"), Mapping) else {}
        fin_status = fin.get("plan_status") if fin.get("available") is not False else "-"
        qual_status = qual.get("plan_status") if qual.get("available") is not False else "-"
        summary = usage.get("summary") if isinstance(usage.get("summary"), Mapping) else {}
        runtime_rows = [
            f"Qualification {qual_status or '-'} · current {'YES' if qual.get('qualified_current_repository') else 'NO'}",
            f"Finalization {fin_status or '-'} · commit {fin.get('commit_sha') or '-'}",
            f"Efficiency    {eff.get('mode') or '-'} · latest {_state(eff.get('latest') if isinstance(eff.get('latest'), Mapping) else None)}",
            f"Usage         turns {summary.get('turn_count', summary.get('records', 0))} · input {summary.get('input_tokens', 0)} · output {summary.get('output_tokens', 0)}",
        ]
        lines += [""] + _section("QUALIFICATION / FINALIZATION", runtime_rows, width=columns, color=enabled, tone="purple")

    decisions = attribution.get("human_decisions") if isinstance(attribution, Mapping) else None
    if isinstance(decisions, list) and decisions:
        rows: list[str] = []
        for item in decisions[-5:]:
            if isinstance(item, Mapping):
                text = f"{item.get('kind', 'decision')} · {item.get('repository_authority', '-')} · {item.get('record_sha256', '-') }"
                rows.extend(_wrap("• ", text, columns))
        lines += [""] + _section("RECENT AUTHORITY EVIDENCE", rows, width=columns, color=enabled, tone="info")

    lines += ["", _paint("Stygnox terminal surface · shared installed operator semantics", "dim", enabled)]
    return "\n".join(lines) + "\n"


def _json_payload(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TuiError(f"payload JSON is invalid: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TuiError("payload JSON must be an object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox tui", description="Installed Stygnox terminal operator surface")
    parser.add_argument("command", nargs="?", choices=("snapshot", "action"), default="snapshot")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--width", type=int)
    parser.add_argument("--json", action="store_true", help="emit canonical JSON instead of terminal rendering")
    parser.add_argument("--name", help="installed operator action name for `action`")
    parser.add_argument("--payload-json", default="{}", help="JSON object for `action`")
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "action":
            if not args.name:
                parser.error("action requires --name")
            result = operator.dispatch_action(args.project, args.name, _json_payload(args.payload_json))
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True))
            else:
                print(_paint(f"[ACTION] {args.name}", "purple", color_enabled(args.color)))
                print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        snapshot = operator.operator_snapshot(args.project)
        if args.json:
            print(json.dumps(snapshot, indent=2, sort_keys=True))
        else:
            sys.stdout.write(render_snapshot(snapshot, color_mode=args.color, width=args.width))
        return 0
    except (operator.OperatorSurfaceError, TuiError, RuntimeError, OSError, ValueError) as exc:
        print(f"stygnox: tui refused: {exc}", file=sys.stderr)
        return 2
