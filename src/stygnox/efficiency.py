"""Installed Stygnox efficiency policy evaluation.

The detailed ceilings are retained from the historical controller contract but
are evaluated inside the installed Stygnox authority model.  Ordinary limits
follow the selected STRICT/NORMAL/RELAXED mode; OFF disables ordinary findings
but never disables the emergency runaway ceilings.
"""
from __future__ import annotations

from typing import Any, Mapping


DETAIL_DEFAULTS: dict[str, int] = {
    "strict_prompt_command_budget": 4,
    "strict_max_commands": 6,
    "strict_max_reported_files": 6,
    "strict_max_cumulative_input": 450_000,
    "strict_max_noncached_input": 75_000,
    "normal_prompt_command_budget": 6,
    "normal_max_commands": 8,
    "normal_max_reported_files": 8,
    "normal_max_cumulative_input": 600_000,
    "normal_max_noncached_input": 100_000,
    "relaxed_prompt_command_budget": 12,
    "relaxed_max_commands": 32,
    "relaxed_max_reported_files": 32,
    "relaxed_max_cumulative_input": 2_400_000,
    "relaxed_max_noncached_input": 400_000,
    "runaway_max_commands": 40,
    "runaway_max_reported_files": 64,
    "runaway_max_cumulative_input": 3_000_000,
    "runaway_max_noncached_input": 500_000,
}
DETAIL_FIELDS = tuple(DETAIL_DEFAULTS)
_MODE_PREFIXES = ("strict", "normal", "relaxed")
_MODES = ("STRICT", "NORMAL", "RELAXED", "OFF")

_BOUNDS: dict[str, tuple[int, int]] = {
    "prompt_command_budget": (1, 100),
    "max_commands": (1, 200),
    "max_reported_files": (1, 500),
    "max_cumulative_input": (1_000, 50_000_000),
    "max_noncached_input": (1_000, 25_000_000),
    "runaway_max_commands": (1, 2_000),
    "runaway_max_reported_files": (1, 5_000),
    "runaway_max_cumulative_input": (1_000, 250_000_000),
    "runaway_max_noncached_input": (1_000, 100_000_000),
}


class EfficiencyError(ValueError):
    """Invalid detailed efficiency policy."""


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise EfficiencyError(f"{name} must be an integer") from exc
    if str(value).strip() not in {str(number), f"+{number}"} and isinstance(value, str):
        raise EfficiencyError(f"{name} must be an integer")
    if not minimum <= number <= maximum:
        raise EfficiencyError(f"{name} must be between {minimum} and {maximum}")
    return number


def normalize_details(raw: Mapping[str, Any] | None = None) -> dict[str, int]:
    source = dict(raw or {})
    values = dict(DETAIL_DEFAULTS)
    for key in DETAIL_FIELDS:
        if key in source and source[key] is not None:
            values[key] = source[key]

    for prefix in _MODE_PREFIXES:
        for suffix in (
            "prompt_command_budget",
            "max_commands",
            "max_reported_files",
            "max_cumulative_input",
            "max_noncached_input",
        ):
            key = f"{prefix}_{suffix}"
            minimum, maximum = _BOUNDS[suffix]
            values[key] = _integer(values[key], key, minimum, maximum)

    for key in (
        "runaway_max_commands",
        "runaway_max_reported_files",
        "runaway_max_cumulative_input",
        "runaway_max_noncached_input",
    ):
        minimum, maximum = _BOUNDS[key]
        values[key] = _integer(values[key], key, minimum, maximum)

    floors = {
        "runaway_max_commands": max(values[f"{prefix}_max_commands"] for prefix in _MODE_PREFIXES),
        "runaway_max_reported_files": max(values[f"{prefix}_max_reported_files"] for prefix in _MODE_PREFIXES),
        "runaway_max_cumulative_input": max(values[f"{prefix}_max_cumulative_input"] for prefix in _MODE_PREFIXES),
        "runaway_max_noncached_input": max(values[f"{prefix}_max_noncached_input"] for prefix in _MODE_PREFIXES),
    }
    for name, floor in floors.items():
        if values[name] < floor:
            raise EfficiencyError(
                f"{name} must be >= {floor} so the emergency ceiling does not undercut an enabled efficiency mode"
            )
    return values


def mode_limits(policy: Mapping[str, Any], mode: str | None = None) -> dict[str, int]:
    details = normalize_details(policy)
    selected = str(mode or policy.get("efficiency_mode") or "NORMAL").upper()
    if selected not in _MODES:
        raise EfficiencyError(f"efficiency_mode must be one of: {', '.join(_MODES)}")
    prefix = "normal" if selected == "OFF" else selected.lower()
    return {
        "prompt_commands": details[f"{prefix}_prompt_command_budget"],
        "commands": details[f"{prefix}_max_commands"],
        "files": details[f"{prefix}_max_reported_files"],
        "cumulative": details[f"{prefix}_max_cumulative_input"],
        "noncached": details[f"{prefix}_max_noncached_input"],
    }


def runaway_limits(policy: Mapping[str, Any]) -> dict[str, int]:
    details = normalize_details(policy)
    return {
        "commands": details["runaway_max_commands"],
        "files": details["runaway_max_reported_files"],
        "cumulative": details["runaway_max_cumulative_input"],
        "noncached": details["runaway_max_noncached_input"],
    }


def _observed(provider_result: Mapping[str, Any] | None) -> dict[str, int]:
    result = dict(provider_result or {})
    metrics = result.get("metrics") if isinstance(result.get("metrics"), Mapping) else {}
    cumulative = max(0, int(metrics.get("input_tokens") or 0))
    cached = max(0, int(metrics.get("cached_input_tokens") or 0))
    inspected = result.get("files_inspected") if isinstance(result.get("files_inspected"), list) else []
    return {
        "commands": max(0, int(metrics.get("commands_executed") or 0)),
        "files": len(inspected),
        "cumulative": cumulative,
        "noncached": max(0, cumulative - cached),
    }


def _findings(observed: Mapping[str, int], limits: Mapping[str, int]) -> list[str]:
    labels = {
        "commands": "commands",
        "files": "reported-files",
        "cumulative": "cumulative-input",
        "noncached": "non-cached-input",
    }
    return [
        f"{labels[key]} {int(observed[key])}>{int(limits[key])}"
        for key in ("commands", "files", "cumulative", "noncached")
        if int(observed[key]) > int(limits[key])
    ]


def assess(provider_result: Mapping[str, Any] | None, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic post-turn efficiency evidence for one reviewed turn."""
    mode = str(policy.get("efficiency_mode") or "NORMAL").upper()
    if mode not in _MODES:
        raise EfficiencyError(f"efficiency_mode must be one of: {', '.join(_MODES)}")
    observed = _observed(provider_result)
    selected_limits = mode_limits(policy, mode)
    emergency_limits = runaway_limits(policy)
    ordinary = [] if mode == "OFF" else _findings(observed, selected_limits)
    runaway = _findings(observed, emergency_limits)
    status = "RUNAWAY" if runaway else ("WARN" if ordinary else "PASS")
    return {
        "status": status,
        "mode": mode,
        "observed": observed,
        "mode_limits": selected_limits,
        "runaway_limits": emergency_limits,
        "findings": runaway or ordinary,
        "ordinary_findings": ordinary,
        "runaway_findings": runaway,
        "requires_review_before_automatic_continuation": status != "PASS",
    }
