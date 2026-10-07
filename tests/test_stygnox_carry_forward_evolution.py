from __future__ import annotations

import json

import pytest

from stygnox import controller, reconciliation


def test_adopted_retirement_file_accepts_one_exact_provider_delta(tmp_path):
    before, after = "a" * 64, "b" * 64
    action = {"path": "docs/carried.md", "disposition": reconciliation.ADOPTED,
              "classification": "retired-carry-forward", "inherited_fingerprint": before}
    state = {"plan_hash": "c" * 64, "current_step": 1, "transaction_id": "tx"}
    receipt = {"schema": controller.RUN_RESULT_SCHEMA, "transaction_id": "tx", "next_action": "qualification-required",
               "plan_binding": {"plan_hash": state["plan_hash"], "current_step": 1}, "provider_result": {"status": "PASS"},
               "actual_delta": {"paths": [{"path": "docs/carried.md", "kind": "modified", "before_fingerprint": before, "after_fingerprint": after}]}}
    receipt["record_sha256"] = controller._digest(receipt)
    runtime = tmp_path / ".stygnox"
    runtime.mkdir()
    (runtime / "controller-run-delta.json").write_text(json.dumps(receipt), encoding="utf-8")
    delta = reconciliation._authorised_adopted_delta(tmp_path, state, action, {"content_fingerprint": after})
    assert delta and delta["before_fingerprint"] == before and delta["after_fingerprint"] == after
    with pytest.raises(reconciliation.ReconciliationError, match="CAP-011"):
        reconciliation._validate_adoption(tmp_path, {"retirement_excluded_historical_authority_paths": ["docs/carried.md"], "plan": {
            "goal": "g", "planning": {"min_steps": 5, "max_steps": 5}, "steps": [{"id": n, "title": "t", "objective": "o", "acceptance": ["a"], "test_change_policy": "modify"} for n in range(1, 6)],
            "repository_authority": "write", "repository_mutation_scope": ["docs/carried.md"], "repository_mutation_scope_sha256": reconciliation._digest(["docs/carried.md"])} , "current_step": 1},
            {"path": "docs/carried.md", "classification": "retired-carry-forward", "inherited_fingerprint_matches": True})
