"""Hostile ordering guards for the R3D installed-successor binding."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from stygnox import lifecycle


def _records(baseline: str) -> dict[str, dict[str, object]]:
    scope = ["src/stygnox/lifecycle.py"]
    final: dict[str, object] = {
        "state": "PASS",
        "repository_baseline_sha256": baseline,
        "repository_mutation_scope_sha256": lifecycle._digest(scope),
        "accepted_controller_attribution": {"attribution_sha256": "a" * 64},
    }
    final["provenance_sha256"] = lifecycle._digest(final)
    plan: dict[str, object] = {
        "plan_hash": "p" * 64,
        "current_step": 1,
        "repository_mutation_scope": scope,
        "repository_mutation_scope_sha256": lifecycle._digest(scope),
        "final_qualification": final,
    }
    plan["record_sha256"] = lifecycle._digest(plan)
    transaction: dict[str, object] = {"transaction_id": "TX-old", "state": "STOPPED"}
    transaction["record_sha256"] = lifecycle._digest(transaction)
    controller: dict[str, object] = {"enabled": False, "controller_execution_enabled": False}
    controller["record_sha256"] = lifecycle._digest(controller)
    return {"plan": plan, "transaction": transaction, "controller": controller}


def _artifact(*, sha256: str, size: int) -> dict[str, object]:
    rows = [{"path": "stygnox/lifecycle.py", "sha256": sha256, "size": size}]
    return {"package_manifest": rows, "package_manifest_sha256": lifecycle._digest(rows)}


def test_stale_qualification_fails_before_transition_shape_is_interpreted() -> None:
    with tempfile.TemporaryDirectory(prefix="stygnox-r3d-binding-") as td:
        root = Path(td)
        with mock.patch.object(
            lifecycle.adoption,
            "capture_baseline",
            return_value=mock.Mock(public=lambda: {"sha256": "c" * 64}),
        ):
            with pytest.raises(lifecycle.LifecycleError, match="qualification is stale"):
                lifecycle._qualified_successor_binding(root, _records("b" * 64), _artifact(sha256="0" * 64, size=1))


def test_source_substitution_fails_before_transition_shape_is_interpreted() -> None:
    with tempfile.TemporaryDirectory(prefix="stygnox-r3d-binding-") as td:
        root = Path(td)
        source = root / "src" / "stygnox" / "lifecycle.py"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"qualified source\n")
        with mock.patch.object(
            lifecycle.adoption,
            "capture_baseline",
            return_value=mock.Mock(public=lambda: {"sha256": "b" * 64}),
        ):
            with pytest.raises(lifecycle.LifecycleError, match="does not match qualified source"):
                lifecycle._qualified_successor_binding(root, _records("b" * 64), _artifact(sha256="0" * 64, size=1))


def test_matching_legacy_qualification_still_cannot_bypass_pending_transition() -> None:
    with tempfile.TemporaryDirectory(prefix="stygnox-r3d-binding-") as td:
        root = Path(td)
        source = root / "src" / "stygnox" / "lifecycle.py"
        source.parent.mkdir(parents=True)
        payload = b"qualified source\n"
        source.write_bytes(payload)
        with mock.patch.object(
            lifecycle.adoption,
            "capture_baseline",
            return_value=mock.Mock(public=lambda: {"sha256": "b" * 64}),
        ):
            with pytest.raises(lifecycle.LifecycleError, match="plan must be an object"):
                lifecycle._qualified_successor_binding(
                    root,
                    _records("b" * 64),
                    _artifact(sha256=lifecycle.hashlib.sha256(payload).hexdigest(), size=len(payload)),
                )
