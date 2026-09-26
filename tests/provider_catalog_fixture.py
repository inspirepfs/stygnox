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
