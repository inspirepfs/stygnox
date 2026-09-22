import ast
import importlib.util
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stygnox_protocol.py"
spec = importlib.util.spec_from_file_location("stygnox_protocol", MODULE_PATH)
protocol = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)


class StygnoxProtocolTests(unittest.TestCase):
    def test_registry_resolves_only_known_v1_contracts(self):
        self.assertIs(protocol.resolve_contract("WorkOrder"), protocol.AgentWorkOrder)
        self.assertIs(protocol.resolve_contract("PLAN_SCHEMA"), protocol.PLAN_SCHEMA)
        with self.assertRaises(ValueError):
            protocol.resolve_contract("Task", major_version=2)
        with self.assertRaises(LookupError):
            protocol.resolve_contract("Unknown")

    def test_canonicalization_and_fingerprints_are_deterministic(self):
        first = {"z": [2, {"a": "é"}], "a": True}
        second = {"a": True, "z": [2, {"a": "é"}]}
        self.assertEqual(protocol.canonical_json_bytes(first), protocol.canonical_json_bytes(second))
        self.assertEqual(protocol.sha256_fingerprint(first), protocol.sha256_fingerprint(second))
        order = protocol.WorkOrder("wo-1", "task-1", ("repository:example",), {"b": 2, "a": 1})
        self.assertEqual(order.fingerprint(), protocol.sha256_fingerprint(order))
        with self.assertRaises(FrozenInstanceError):
            order.task_id = "other"

    def test_state_fingerprints_are_stable(self):
        one = protocol.StateFingerprint.from_state({"b": 2, "a": [1, 2]}, ("target",))
        two = protocol.StateFingerprint.from_state({"a": [1, 2], "b": 2}, ("target",))
        self.assertEqual(one, two)
        self.assertEqual(one.fingerprint(), two.fingerprint())

    def test_claimed_and_observed_checks_are_structurally_separate(self):
        result = protocol.SemanticResult("r-1", "ok", claimed_checks=("unit test passed",))
        receipt = protocol.ExecutionReceipt("x-1", "wo-1", "ok", observed_checks=("exit code 0",))
        self.assertEqual(result.claimed_checks, ("unit test passed",))
        self.assertFalse(hasattr(result, "observed_checks"))
        self.assertEqual(receipt.observed_checks, ("exit code 0",))
        self.assertFalse(hasattr(receipt, "claimed_checks"))

    def test_evidence_and_references_make_no_verification_claim(self):
        reference = protocol.KnowledgeRef("unverified://source")
        evidence = protocol.EvidenceBundle("e-1", (reference,))
        result = protocol.SemanticResult("r-1", "ok", evidence=(evidence,))
        self.assertEqual(result.evidence[0].references[0].reference, "unverified://source")
        self.assertFalse(hasattr(evidence, "verified"))
        self.assertFalse(hasattr(reference, "verified"))

    def test_adapter_and_backend_are_passive_contracts(self):
        self.assertTrue(getattr(protocol.AgentAdapter, "_is_protocol", False))
        self.assertTrue(getattr(protocol.Evaluator, "_is_protocol", False))
        backend = protocol.TaskBackend("backend-1", "local", ("declared",))
        self.assertEqual(backend.declared_scope, ("declared",))
        self.assertFalse(hasattr(backend, "execute"))

    def test_source_is_provider_and_project_neutral_standard_library_only(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, {"__future__", "dataclasses", "hashlib", "json", "math", "types", "typing"})
        imported_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        for forbidden in ("subprocess", "socket", "urllib", "http", "routeros"):
            self.assertNotIn(forbidden, imported_names)

    def test_controller_schema_fingerprints(self):
        self.assertEqual(
            protocol.sha256_fingerprint(protocol.PLAN_SCHEMA),
            "48b24fbfdf44dd82638ff4fe73cc9099b239d5aa4f2715d05123bd5f71b6b6fc",
        )
        self.assertEqual(
            protocol.sha256_fingerprint(protocol.RESULT_SCHEMA),
            "e9fa63641a870ad2fed93f31d76f1a75c6fddfa919715942917eaa05aa833fa8",
        )


if __name__ == "__main__":
    unittest.main()
