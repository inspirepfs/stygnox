from __future__ import annotations

import json

import pytest

from stygnox import controller


def _plan() -> dict[str, object]:
    steps = [
        {"id": n, "title": f"s{n}", "objective": f"o{n}", "acceptance": ["a"], "test_change_policy": "add-only"}
        for n in range(1, 6)
    ]
    scope = ["docs/current.md"]
    return {"goal": "rebase", "planning": {"min_steps": 5, "max_steps": 5}, "steps": steps,
            "repository_authority": "write", "repository_mutation_scope": scope,
            "repository_mutation_scope_sha256": controller._digest(scope)}


def _receipt(state: dict[str, object], baseline: str) -> dict[str, object]:
    body = {"schema": controller.RUN_RESULT_SCHEMA, "transaction_id": "tx", "repository_authority": "write",
            "plan_binding": {"plan_hash": state["plan_hash"], "plan_record_sha256": state["record_sha256"],
                             "current_step": 1, "step_authority_baseline_sha256": baseline},
            "before_baseline_sha256": baseline, "after_baseline_sha256": baseline,
            "next_action": "qualification-required", "human_gate": None,
            "provider_result": {"status": "PASS"}}
    body["record_sha256"] = controller._digest(body)
    return body


def test_rebase_predecessor_accepts_only_exact_completed_controller_turn(tmp_path, monkeypatch):
    baseline = "a" * 64
    plan = _plan()
    state: dict[str, object] = {"status": "APPROVED", "plan": plan, "plan_hash": controller._digest(plan),
        "record_sha256": "b" * 64, "current_step": 1, "operator": "operator", "transaction_id": "tx",
        "transaction_record_sha256": "c" * 64, "controller_record_sha256": "d" * 64,
        "step_authority_baseline_sha256": baseline, "approval_baseline_sha256": baseline,
        "execution_authority_granted": True, "retirement_historical_lineage": None,
        "retirement_excluded_historical_authority_paths": []}
    runtime = tmp_path / ".stygnox"
    runtime.mkdir()
    receipt = _receipt(state, baseline)
    (runtime / "controller-run-good.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(controller.adoption, "capture_baseline", lambda _root: type("B", (), {"public": lambda self: {"sha256": baseline}})())
    active = {"operator": "operator", "transaction_id": "tx", "record_sha256": "d" * 64}
    tx = {"transaction_id": "tx", "record_sha256": "c" * 64}
    predecessor = controller.current_step_rebase_predecessor(tmp_path, state, active, tx)
    assert predecessor["predecessor"]["predecessor_receipt_sha256"] == receipt["record_sha256"]
    state["record_sha256"] = "e" * 64
    with pytest.raises(controller.ControllerError):
        controller.current_step_rebase_predecessor(tmp_path, state, active, tx)


def test_rebase_predecessor_accepts_only_same_turn_self_development_expiry(tmp_path, monkeypatch):
    baseline = "a" * 64
    plan = _plan()
    bound_record = "b" * 64
    expired_record = "e" * 64
    state: dict[str, object] = {
        "status": "APPROVED", "plan": plan, "plan_hash": controller._digest(plan),
        "record_sha256": expired_record, "current_step": 1, "operator": "operator", "transaction_id": "tx",
        "transaction_record_sha256": "c" * 64, "controller_record_sha256": "d" * 64,
        "step_authority_baseline_sha256": baseline, "approval_baseline_sha256": baseline,
        "execution_authority_granted": True, "retirement_historical_lineage": None,
        "retirement_excluded_historical_authority_paths": [],
    }
    runtime = tmp_path / ".stygnox"
    runtime.mkdir()
    receipt = _receipt({**state, "record_sha256": bound_record}, baseline)
    expiration = {
        "grant_sha256": "f" * 64,
        "plan_hash": state["plan_hash"],
        "step": 1,
        "gate_id": "HG-0001-01",
        "reason": "single reviewed controller retry completed",
        "expired_at": "2026-10-07T00:00:00+00:00",
    }
    expiration["record_sha256"] = controller._digest(expiration)
    receipt["self_development_expiration"] = {**expiration, "plan_record_sha256": expired_record}
    receipt["record_sha256"] = controller._digest({k: v for k, v in receipt.items() if k != "record_sha256"})
    (runtime / "controller-run-good.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(controller.adoption, "capture_baseline", lambda _root: type("B", (), {"public": lambda self: {"sha256": baseline}})())
    active = {"operator": "operator", "transaction_id": "tx", "record_sha256": "d" * 64}
    tx = {"transaction_id": "tx", "record_sha256": "c" * 64}

    predecessor = controller.current_step_rebase_predecessor(tmp_path, state, active, tx)
    assert predecessor["predecessor"]["predecessor_receipt_sha256"] == receipt["record_sha256"]

    receipt["self_development_expiration"]["plan_record_sha256"] = "9" * 64
    receipt["record_sha256"] = controller._digest({k: v for k, v in receipt.items() if k != "record_sha256"})
    (runtime / "controller-run-good.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(controller.ControllerError, match="exactly one completed controller turn"):
        controller.current_step_rebase_predecessor(tmp_path, state, active, tx)


def test_rebase_predecessor_rejects_tampered_nested_self_development_expiry(tmp_path, monkeypatch):
    baseline = "a" * 64
    plan = _plan()
    bound_record = "b" * 64
    expired_record = "e" * 64
    state: dict[str, object] = {
        "status": "APPROVED", "plan": plan, "plan_hash": controller._digest(plan),
        "record_sha256": expired_record, "current_step": 1, "operator": "operator", "transaction_id": "tx",
        "transaction_record_sha256": "c" * 64, "controller_record_sha256": "d" * 64,
        "step_authority_baseline_sha256": baseline, "approval_baseline_sha256": baseline,
        "execution_authority_granted": True, "retirement_historical_lineage": None,
        "retirement_excluded_historical_authority_paths": [],
    }
    runtime = tmp_path / ".stygnox"
    runtime.mkdir()
    receipt = _receipt({**state, "record_sha256": bound_record}, baseline)
    expiration = {
        "grant_sha256": "f" * 64,
        "plan_hash": state["plan_hash"],
        "step": 1,
        "gate_id": "HG-0001-01",
        "reason": "single reviewed controller retry completed",
        "expired_at": "2026-10-07T00:00:00+00:00",
    }
    expiration["record_sha256"] = controller._digest(expiration)
    expiration["plan_record_sha256"] = expired_record
    expiration["reason"] = "tampered after inner digest"
    receipt["self_development_expiration"] = expiration
    receipt["record_sha256"] = controller._digest({k: v for k, v in receipt.items() if k != "record_sha256"})
    (runtime / "controller-run-good.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(controller.adoption, "capture_baseline", lambda _root: type("B", (), {"public": lambda self: {"sha256": baseline}})())
    active = {"operator": "operator", "transaction_id": "tx", "record_sha256": "d" * 64}
    tx = {"transaction_id": "tx", "record_sha256": "c" * 64}
    with pytest.raises(controller.ControllerError, match="exactly one completed controller turn"):
        controller.current_step_rebase_predecessor(tmp_path, state, active, tx)
