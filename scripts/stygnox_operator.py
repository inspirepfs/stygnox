"""Pure, presentation-neutral operator snapshot shaping.

This module is deliberately passive: callers supply controller-derived values,
and this contract bounds and copies plain data without reading state or causing
effects.  It has no knowledge of controller implementations, runtime files, or
presentation transports.
"""

from math import isfinite
from typing import Any, Mapping


OPERATOR_SNAPSHOT_SCHEMA = "stygnox_operator_snapshot_v1"
OPERATOR_SNAPSHOT_VERSION = 1
DEFAULT_MAX_ITEMS = 120
DEFAULT_MAX_TEXT = 4_000
_MAX_DEPTH = 8


def _limit(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _shape(value: Any, *, max_items: int, max_text: int, depth: int = 0) -> Any:
    """Copy JSON-like data while applying explicit depth, text, and item bounds."""
    if depth > _MAX_DEPTH:
        return {"truncated": "maximum depth"}
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("snapshot values cannot contain non-finite floats")
        return value
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, Mapping):
        shaped: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                break
            if not isinstance(key, str):
                raise TypeError("snapshot mapping keys must be strings")
            shaped[key[:max_text]] = _shape(
                item, max_items=max_items, max_text=max_text, depth=depth + 1
            )
        return shaped
    if isinstance(value, (list, tuple)):
        return [
            _shape(item, max_items=max_items, max_text=max_text, depth=depth + 1)
            for item in value[:max_items]
        ]
    raise TypeError(f"snapshot values must be JSON-like, not {type(value).__name__}")


def _section(value: Mapping[str, Any] | None, *, max_items: int, max_text: int) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("snapshot sections must be mappings or None")
    shaped = _shape(value, max_items=max_items, max_text=max_text)
    assert isinstance(shaped, dict)
    return shaped


def stygnox_operator_snapshot_v1(
    *,
    controller: Mapping[str, Any] | None = None,
    progress: Mapping[str, Any] | None = None,
    gate: Mapping[str, Any] | None = None,
    pending_paths: list[Any] | tuple[Any, ...] | None = None,
    recovery: Mapping[str, Any] | None = None,
    reconciliation: Mapping[str, Any] | None = None,
    retirement: Mapping[str, Any] | None = None,
    efficiency_model: Mapping[str, Any] | None = None,
    report: Mapping[str, Any] | None = None,
    events: list[Any] | tuple[Any, ...] | None = None,
    live_output: str | list[Any] | tuple[Any, ...] | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    max_text: int = DEFAULT_MAX_TEXT,
) -> dict[str, Any]:
    """Return the v1 operator snapshot from caller-supplied, derived values.

    The result contains no authority calculation: every section remains a
    bounded projection of the matching caller input.
    """
    max_items = _limit(max_items, "max_items")
    max_text = _limit(max_text, "max_text")
    if pending_paths is not None and not isinstance(pending_paths, (list, tuple)):
        raise TypeError("pending_paths must be a list, tuple, or None")
    if events is not None and not isinstance(events, (list, tuple)):
        raise TypeError("events must be a list, tuple, or None")
    if live_output is not None and not isinstance(live_output, (str, list, tuple)):
        raise TypeError("live_output must be text, a list, a tuple, or None")
    return {
        "schema": OPERATOR_SNAPSHOT_SCHEMA,
        "version": OPERATOR_SNAPSHOT_VERSION,
        "controller": _section(controller, max_items=max_items, max_text=max_text),
        "progress": _section(progress, max_items=max_items, max_text=max_text),
        "gate": _section(gate, max_items=max_items, max_text=max_text),
        "pending_paths": _shape(pending_paths or [], max_items=max_items, max_text=max_text),
        "recovery": _section(recovery, max_items=max_items, max_text=max_text),
        "reconciliation": _section(reconciliation, max_items=max_items, max_text=max_text),
        "retirement": _section(retirement, max_items=max_items, max_text=max_text),
        "efficiency_model": _section(efficiency_model, max_items=max_items, max_text=max_text),
        "report": _section(report, max_items=max_items, max_text=max_text),
        "events": _shape(events or [], max_items=max_items, max_text=max_text),
        "live_output": _shape(live_output if live_output is not None else "", max_items=max_items, max_text=max_text),
    }
