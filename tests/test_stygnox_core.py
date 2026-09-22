from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "stygnox_core.py"
spec = importlib.util.spec_from_file_location("stygnox_core", MODULE_PATH)
core = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = core
spec.loader.exec_module(core)


def plan(count: int = 5) -> dict:
    return {"goal": "Build a bounded pure core", "steps": [{"id": number, "title": f"Step {number}", "objective": "Implement the pure contract.", "acceptance": ["A direct test passes."], "test_change_policy": "add-only"} for number in range(1, count + 1)]}


POLICY = core.ProjectPathPolicy(
    protected_prefixes=("secrets", "certs/"), protected_exact=(".netrc",),
    protected_dir_prefixes=(".codex",), protected_suffixes=(".token",),
    tooling_paths=("scripts/controller.py",), tooling_prefixes=("tests/test_controller",),
)


class CanonicalAndPlanTests(unittest.TestCase):
    def test_canonical_json_and_hash_are_stable_and_repeatable(self):
        first = {"z": [2, {"a": "é"}], "a": True}
        second = {"a": True, "z": [2, {"a": "é"}]}
        self.assertEqual(b'{"a":true,"z":[2,{"a":"\\xc3\\xa9"}]}'.decode("unicode_escape").encode("latin1"), core.canonical_json_bytes(first))
        self.assertEqual(core.canonical_json_bytes(first), core.canonical_json_bytes(second))
        self.assertEqual(core.sha256_fingerprint(first), core.sha256_fingerprint(second))
        with self.assertRaises(TypeError): core.canonical_json_bytes({1: "no"})
        with self.assertRaises(ValueError): core.canonical_json_bytes({"bad": float("nan")})

    def test_bounds_validation_and_plan_errors(self):
        self.assertEqual((5, 10), core.proposal_step_bounds())
        self.assertEqual((2, 7), core.proposal_step_bounds(2, 7))
        for bounds in ((0, 7), (8, 7), (1, 21)):
            with self.assertRaises(ValueError): core.proposal_step_bounds(*bounds)
        core.validate_plan(plan())
        invalid = plan(); invalid["steps"][0]["id"] = 2
        with self.assertRaisesRegex(ValueError, "sequential"): core.validate_plan(invalid)
        with self.assertRaisesRegex(ValueError, "5-10"): core.validate_plan(plan(4))

    def test_controller_authority_is_derived_and_selects_sandbox(self):
        proposal = plan()
        bound = core.controller_inject_repository_authority(proposal, "write")
        self.assertNotIn(core.REPOSITORY_AUTHORITY_FIELD, proposal)
        self.assertEqual("write", bound[core.REPOSITORY_AUTHORITY_FIELD])
        digest = core.plan_hash(bound)
        core.validate_complete_plan(bound, digest)
        self.assertEqual("workspace-write", core.sandbox_for_approved_plan(bound, digest))
        readonly = core.controller_inject_repository_authority(plan(), "read-only")
        self.assertEqual("read-only", core.sandbox_for_approved_plan(readonly, core.plan_hash(readonly)))
        with self.assertRaisesRegex(ValueError, "must not supply"): core.controller_inject_repository_authority(bound, "write")
        with self.assertRaisesRegex(ValueError, "does not match"): core.validate_complete_plan(bound, "0" * 64)


class PathAndTestPolicyTests(unittest.TestCase):
    def test_lexical_paths_and_configured_classification(self):
        self.assertEqual("tests/new.py", core.normalize_repo_path(" ./tests\\unit/../new.py "))
        with self.assertRaises(ValueError): core.normalize_repo_path("../outside")
        self.assertTrue(core.is_protected_path("./secrets/key", POLICY))
        self.assertTrue(core.is_protected_path("build/a.token", POLICY))
        self.assertTrue(core.is_tooling_path("tests/test_controller_x.py", POLICY))
        self.assertEqual("protected", core.classify_changes(["app.py", "secrets/key"], POLICY))
        self.assertEqual("tooling", core.classify_changes(["scripts/controller.py"], POLICY))
        self.assertEqual("product", core.classify_changes(["app.py"], POLICY))
        self.assertEqual("mixed", core.classify_changes(["app.py", "scripts/controller.py"], POLICY))
        self.assertEqual("no-change", core.classify_changes([], POLICY))

    def test_test_policy_uses_supplied_approval_baseline_and_allowances(self):
        changed = ["tests/existing.py", "tests/new.py", "app.py"]
        baseline = {"tests/existing.py": "tracked", "tests/new.py": "absent"}
        self.assertEqual(["tests/existing.py", "tests/new.py"], core.test_policy_violations(changed, "none", baseline))
        self.assertEqual(["tests/existing.py"], core.test_policy_violations(changed, "add-only", baseline))
        self.assertEqual([], core.test_policy_violations(changed, "modify", baseline))
        self.assertEqual([], core.test_policy_violations(changed, "none", baseline, ["tests/existing.py", "tests/new.py"]))


class AgentAndFailureTests(unittest.TestCase):
    def test_human_gate_requires_approved_delegation_and_extracts_declaration(self):
        result = {"summary": "BLOCKED_HUMAN: fresh operator evidence is absent", "needs_human": True, "blocker_class": "human-decision", "blockers": ["agent claim"]}
        delegated = {"objective": "Runtime evidence is required.", "acceptance": ["If unavailable, stop at BLOCKED_HUMAN for operator evidence." ]}
        self.assertEqual("fresh operator evidence is absent", core.declared_human_block(result))
        self.assertEqual((True, "fresh operator evidence is absent"), core.agent_requires_human_before_qualification(result, delegated))
        self.assertEqual("human-review", core.agent_disposition(result, delegated))
        self.assertEqual((False, ""), core.agent_requires_human_before_qualification(result, {"objective": "Implement code", "acceptance": ["Tests pass."]}))
        self.assertEqual((False, ""), core.agent_requires_human_before_qualification(result, None))

    def test_continuation_is_not_human_authority(self):
        result = {"summary": "Need another bounded turn.", "blockers": ["One focused command remains."], "needs_human": False, "blocker_class": "continuation"}
        self.assertEqual((True, "One focused command remains."), core.agent_requests_continuation(result))
        self.assertEqual("continuation", core.agent_disposition(result))
        self.assertEqual((False, ""), core.agent_requires_human_before_qualification(result))

    def test_failure_normalization_and_fingerprints_are_stable_and_differentiate(self):
        first = "FAIL: test_x\nAssertionError: object 0x123abc failed in 1.23s /tmp/a/file"
        second = "FAIL: test_x\nAssertionError: object 0x9fffff failed in 9.99s /tmp/b/file"
        self.assertEqual("FAIL: test_x\nAssertionError: object 0xADDR failed in TIME /tmp/TMP", core.normalize_failure(first))
        self.assertEqual(core.failure_fingerprint("unit-tests", first, 1), core.failure_fingerprint("unit-tests", second, 1))
        self.assertNotEqual(core.failure_fingerprint("unit-tests", first, 1), core.failure_fingerprint("other-gate", first, 1))


class BoundaryTests(unittest.TestCase):
    def test_core_has_only_pure_standard_library_imports_and_no_side_effect_surface(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imports.add(node.module.split(".")[0])
        self.assertLessEqual(imports, {"__future__", "dataclasses", "hashlib", "json", "re", "typing"})
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue({"open", "Path", "os", "subprocess", "socket", "urllib", "ralph", "environ", "requests"}.isdisjoint(names))
        self.assertNotIn("ralph.py", MODULE_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
