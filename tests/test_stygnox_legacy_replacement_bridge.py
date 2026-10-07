from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stygnox import adoption, planning


RID = "RT-LEGACY-BRIDGE"
MSHA = "a" * 64
TX = "TX-legacy"


def manifest():
    return {
        "schema": "stygnox_plan_retirement_v1",
        "record_id": RID,
        "manifest_sha256": MSHA,
        "disposition": "RETIRED_WITH_CARRY_FORWARD",
        "plan_hash": "b" * 64,
        "reason": "legacy bridge fixture",
        "historical_lineage": None,
        "planning_context": {"goal": "old goal"},
        "paths": [
            {
                "action": "preserve",
                "path": "docs/programme/PROGRESS.md",
                "source": "adopted-carry-forward",
                "approval_presence": "tracked",
                "current": {"fingerprint": "c" * 64},
            },
            {
                "action": "preserve",
                "path": "src/stygnox/planning.py",
                "source": "controller-native",
                "approval_presence": "tracked",
                "current": {"fingerprint": "d" * 64},
            },
        ],
        "operations": {
            "preserved": [
                "docs/programme/PROGRESS.md",
                "src/stygnox/planning.py",
            ],
            "restore": [],
            "delete": [],
        },
    }


def rejected_state():
    scope = [
        "docs/programme/PROGRESS.md",
        "src/stygnox/planning.py",
    ]
    plan = {
        "goal": "replacement",
        "planning": {"min_steps": 1, "max_steps": 1},
        "repository_authority": "write",
        "repository_mutation_scope": scope,
        "repository_mutation_scope_sha256": planning._digest(scope),
        "steps": [{
            "id": 1,
            "title": "Implement",
            "objective": "fixture",
            "acceptance": ["pass"],
            "test_change_policy": "modify",
        }],
    }
    plan_hash = planning._plan_hash(plan)
    state = {
        "schema": "stygnox_plan_v1",
        "status": "REJECTED",
        "operator": "Operator One",
        "transaction_id": TX,
        "plan": plan,
        "plan_hash": plan_hash,
        "proposal_preview_sha256": "e" * 64,
        "proposal_baseline_sha256": "f" * 64,
        "execution_authority_granted": False,
        "approved_at": None,
        "rejected_at": "2026-10-06T20:12:43+00:00",
        "rejection_reason": "hostile review corrections",
        "retirement_record_id": RID,
        "retirement_manifest_sha256": MSHA,
        "retirement_historical_lineage": None,
        "retired_plans": [{
            "record_id": RID,
            "manifest_sha256": MSHA,
            "disposition": "RETIRED_WITH_CARRY_FORWARD",
        }],
        "retirement_carry_forward_candidates": [
            {
                "path": "docs/programme/PROGRESS.md",
                "source": "adopted-carry-forward",
                "approval_presence": "tracked",
                "retirement_fingerprint": "c" * 64,
                "retirement_record_id": RID,
                "retirement_manifest_sha256": MSHA,
            },
            {
                "path": "src/stygnox/planning.py",
                "source": "controller-native",
                "approval_presence": "tracked",
                "retirement_fingerprint": "d" * 64,
                "retirement_record_id": RID,
                "retirement_manifest_sha256": MSHA,
            },
        ],
    }
    state["record_sha256"] = planning._digest(state)
    return state


class LegacyRejectedReplacementBridgeTests(unittest.TestCase):

    def bridge(self, state=None, retirement_manifest=None, *, receipt_mode="valid"):
        state = rejected_state() if state is None else state
        retirement_manifest = (
            manifest() if retirement_manifest is None
            else retirement_manifest
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            marker = root / "src" / "stygnox" / "product.py"
            marker.parent.mkdir(parents=True)
            marker.write_text(
                "# native Stygnox source marker\n",
                encoding="utf-8",
            )

            if receipt_mode != "missing":
                receipt = {
                    "schema": planning.PLAN_REJECTION_SCHEMA,
                    "product_version": "0.1.0",
                    "plan_hash": state["plan_hash"],
                    "operator": state["operator"],
                    "transaction_id": state["transaction_id"],
                    "reason": state["rejection_reason"],
                    "rejected_at": state["rejected_at"],
                    "execution_authority_granted": False,
                }
                receipt["record_sha256"] = planning._digest(receipt)

                if receipt_mode == "tampered":
                    receipt["reason"] = "tampered after controller receipt"

                adoption.write_runtime_record(
                    root,
                    f"plan-rejection-{state['plan_hash'][:16]}.json",
                    receipt,
                    actor="controller",
                )

            with mock.patch(
                "stygnox.retirement.load_retirement",
                return_value=retirement_manifest,
            ):
                return planning._legacy_rejected_replacement_bridge(
                    root,
                    state,
                    RID,
                )

    def test_exact_legacy_bridge_preserves_ordinary_and_excludes_tooling(self):
        result = self.bridge()

        self.assertEqual(
            ["docs/programme/PROGRESS.md"],
            [row["path"] for row in result["ordinary_candidates"]],
        )
        self.assertEqual(
            ["src/stygnox/planning.py"],
            [
                row["path"]
                for row in result["excluded_historical_authority_paths"]
            ],
        )
        evidence = result["evidence"]
        self.assertFalse(evidence["creates_execution_authority"])
        self.assertFalse(evidence["creates_provider_attribution"])
        self.assertFalse(
            evidence["modern_historical_lineage_reconstructed"]
        )
        self.assertRegex(evidence["record_sha256"], r"^[0-9a-f]{64}$")

    def test_changed_candidate_fingerprint_fails_closed(self):
        state = rejected_state()
        state["retirement_carry_forward_candidates"][0][
            "retirement_fingerprint"
        ] = "0" * 64
        state["record_sha256"] = planning._digest(
            {k: v for k, v in state.items() if k != "record_sha256"}
        )

        with self.assertRaisesRegex(
            planning.PlanningError,
            "candidate evidence changed",
        ):
            self.bridge(state=state)

    def test_missing_candidate_fails_closed(self):
        state = rejected_state()
        state["retirement_carry_forward_candidates"].pop()
        state["record_sha256"] = planning._digest(
            {k: v for k, v in state.items() if k != "record_sha256"}
        )

        with self.assertRaisesRegex(
            planning.PlanningError,
            "candidate set mismatch",
        ):
            self.bridge(state=state)

    def test_tooling_cannot_be_laundered_as_adopted_carry_forward(self):
        m = manifest()
        m["paths"][1]["source"] = "adopted-carry-forward"

        state = rejected_state()
        state["retirement_carry_forward_candidates"][1][
            "source"
        ] = "adopted-carry-forward"
        state["record_sha256"] = planning._digest(
            {k: v for k, v in state.items() if k != "record_sha256"}
        )

        with self.assertRaisesRegex(
            planning.PlanningError,
            "launder tooling path",
        ):
            self.bridge(state=state, retirement_manifest=m)

    def test_extra_candidate_fails_closed(self):
        state = rejected_state()
        state["retirement_carry_forward_candidates"].append({
            "path": "extra.txt",
            "source": "adopted-carry-forward",
            "approval_presence": "tracked",
            "retirement_fingerprint": "1" * 64,
            "retirement_record_id": RID,
            "retirement_manifest_sha256": MSHA,
        })
        state["record_sha256"] = planning._digest(
            {k: v for k, v in state.items() if k != "record_sha256"}
        )

        with self.assertRaisesRegex(
            planning.PlanningError,
            "candidate set mismatch",
        ):
            self.bridge(state=state)

    def test_duplicate_candidate_fails_closed(self):
        state = rejected_state()
        state["retirement_carry_forward_candidates"].append(
            copy.deepcopy(state["retirement_carry_forward_candidates"][0])
        )
        state["record_sha256"] = planning._digest(
            {k: v for k, v in state.items() if k != "record_sha256"}
        )

        with self.assertRaisesRegex(
            planning.PlanningError,
            "candidate path is missing or duplicated",
        ):
            self.bridge(state=state)

    def test_missing_rejection_receipt_fails_closed(self):
        with self.assertRaisesRegex(
            planning.PlanningError,
            "rejection receipt is missing",
        ):
            self.bridge(receipt_mode="missing")

    def test_tampered_rejection_receipt_fails_closed(self):
        with self.assertRaisesRegex(
            planning.PlanningError,
            "rejection receipt integrity check failed",
        ):
            self.bridge(receipt_mode="tampered")

    def persisted_bridge(self, *, mutate_state=None, source_receipt_mode="valid", current_receipt_mode="valid"):
        retirement_manifest = manifest()
        source = rejected_state()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            marker = root / "src" / "stygnox" / "product.py"
            marker.parent.mkdir(parents=True)
            marker.write_text("# native Stygnox source marker\n", encoding="utf-8")

            source_receipt = {
                "schema": planning.PLAN_REJECTION_SCHEMA,
                "product_version": "0.1.0",
                "plan_hash": source["plan_hash"],
                "operator": source["operator"],
                "transaction_id": source["transaction_id"],
                "reason": source["rejection_reason"],
                "rejected_at": source["rejected_at"],
                "execution_authority_granted": False,
            }
            source_receipt["record_sha256"] = planning._digest(source_receipt)
            adoption.write_runtime_record(
                root,
                f"plan-rejection-{source['plan_hash'][:16]}.json",
                source_receipt,
                actor="controller",
            )

            with mock.patch(
                "stygnox.retirement.load_retirement",
                return_value=retirement_manifest,
            ):
                first = planning._legacy_rejected_replacement_bridge(
                    root,
                    source,
                    RID,
                )

            if source_receipt_mode == "tampered":
                source_receipt["reason"] = "tampered source receipt"
                adoption.write_runtime_record(
                    root,
                    f"plan-rejection-{source['plan_hash'][:16]}.json",
                    source_receipt,
                    actor="controller",
                )

            current = copy.deepcopy(source)
            current_plan = copy.deepcopy(source["plan"])
            current_plan["goal"] = "bridged successor"
            current["plan"] = current_plan
            current["plan_hash"] = planning._plan_hash(current_plan)
            current["proposal_preview_sha256"] = "1" * 64
            current["rejected_at"] = "2026-10-07T09:56:12+00:00"
            current["rejection_reason"] = "second hostile review correction"
            current["retirement_carry_forward_candidates"] = copy.deepcopy(
                first["ordinary_candidates"]
            )
            current["retirement_excluded_historical_authority_paths"] = copy.deepcopy(
                first["excluded_historical_authority_paths"]
            )
            current["retirement_legacy_bridge"] = copy.deepcopy(first["evidence"])
            current["record_sha256"] = planning._digest(
                {k: v for k, v in current.items() if k != "record_sha256"}
            )

            if mutate_state is not None:
                mutate_state(current)
                current["record_sha256"] = planning._digest(
                    {k: v for k, v in current.items() if k != "record_sha256"}
                )

            current_receipt = {
                "schema": planning.PLAN_REJECTION_SCHEMA,
                "product_version": "0.1.0",
                "plan_hash": current["plan_hash"],
                "operator": current["operator"],
                "transaction_id": current["transaction_id"],
                "reason": current["rejection_reason"],
                "rejected_at": current["rejected_at"],
                "execution_authority_granted": False,
            }
            current_receipt["record_sha256"] = planning._digest(current_receipt)
            if current_receipt_mode == "tampered":
                current_receipt["reason"] = "tampered current receipt"
            adoption.write_runtime_record(
                root,
                f"plan-rejection-{current['plan_hash'][:16]}.json",
                current_receipt,
                actor="controller",
            )

            with mock.patch(
                "stygnox.retirement.load_retirement",
                return_value=retirement_manifest,
            ):
                return planning._persisted_legacy_replacement_bridge(
                    root,
                    current,
                    RID,
                )

    def test_persisted_bridge_allows_second_generation_reproposal(self):
        result = self.persisted_bridge()
        self.assertEqual(
            ["docs/programme/PROGRESS.md"],
            [row["path"] for row in result["ordinary_candidates"]],
        )
        self.assertEqual(
            ["src/stygnox/planning.py"],
            [row["path"] for row in result["excluded_historical_authority_paths"]],
        )

    def test_persisted_bridge_tamper_fails_closed(self):
        def mutate(state):
            state["retirement_legacy_bridge"]["operator"] = "Other Operator"

        with self.assertRaisesRegex(
            planning.PlanningError,
            "bridge integrity check failed",
        ):
            self.persisted_bridge(mutate_state=mutate)

    def test_persisted_bridge_ordinary_candidate_change_fails_closed(self):
        def mutate(state):
            state["retirement_carry_forward_candidates"][0][
                "retirement_fingerprint"
            ] = "0" * 64

        with self.assertRaisesRegex(
            planning.PlanningError,
            "ordinary candidate bindings changed",
        ):
            self.persisted_bridge(mutate_state=mutate)

    def test_persisted_bridge_cap011_exclusion_change_fails_closed(self):
        def mutate(state):
            state["retirement_excluded_historical_authority_paths"] = []

        with self.assertRaisesRegex(
            planning.PlanningError,
            "CAP-011 exclusions changed",
        ):
            self.persisted_bridge(mutate_state=mutate)

    def test_persisted_bridge_source_rejection_receipt_tamper_fails_closed(self):
        with self.assertRaisesRegex(
            planning.PlanningError,
            "source rejection receipt integrity check failed",
        ):
            self.persisted_bridge(source_receipt_mode="tampered")

    def test_persisted_bridge_current_rejection_receipt_tamper_fails_closed(self):
        with self.assertRaisesRegex(
            planning.PlanningError,
            "rejection receipt integrity check failed",
        ):
            self.persisted_bridge(current_receipt_mode="tampered")

    def test_modern_manifest_cannot_enter_legacy_bridge(self):
        m = manifest()
        m["historical_lineage"] = {
            "schema": "stygnox_retirement_historical_lineage_v1"
        }

        with self.assertRaisesRegex(
            planning.PlanningError,
            "refuses modern retirement manifest",
        ):
            self.bridge(retirement_manifest=m)


if __name__ == "__main__":
    unittest.main()
