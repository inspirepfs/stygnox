from __future__ import annotations

import hashlib
import json


def test_catalog(*, second_efforts: tuple[str, ...] = ("medium",)) -> dict:
    body = {
        "schema": "stygnox_codex_model_catalog_v1",
        "provider": "codex",
        "models": [
            {
                "id": "gpt-test",
                "display_name": "GPT Test",
                "description": "fixture primary",
                "is_default": True,
                "reasoning_efforts": ["low", "medium", "high", "xhigh"],
                "default_reasoning_effort": "medium",
            },
            {
                "id": "gpt-other",
                "display_name": "GPT Other",
                "description": "fixture secondary",
                "is_default": False,
                "reasoning_efforts": list(second_efforts),
                "default_reasoning_effort": second_efforts[0] if second_efforts else None,
            },
        ],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body["catalog_sha256"] = hashlib.sha256(canonical).hexdigest()
    return body


def safe_rate_limits(*, remaining_primary: float = 80.0, remaining_secondary: float = 70.0, allowed: bool | None = True, credits: int = 1) -> dict:
    body = {
        "schema": "stygnox_codex_rate_limits_v1",
        "provider": "codex",
        "model": "gpt-test",
        "plan_type": "test",
        "ordinary_usage_allowed": allowed,
        "windows": [
            {"limit_id": "codex", "name": "5h", "slot": "primary", "used_percent": 100.0-remaining_primary, "remaining_percent": remaining_primary, "window_minutes": 300, "resets_at": 2000000000},
            {"limit_id": "codex", "name": "weekly", "slot": "secondary", "used_percent": 100.0-remaining_secondary, "remaining_percent": remaining_secondary, "window_minutes": 10080, "resets_at": 2000100000},
        ],
        "available_reset_credits": credits,
        "reset_credits": [],
    }
    body["snapshot_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return body
