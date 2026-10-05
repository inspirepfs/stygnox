from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RALPH_PATH = ROOT / "scripts" / "ralph.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ralph = load_module("ralph_repository_mutation_scope_v2", RALPH_PATH)
protocol = sys.modules["stygnox_protocol"]
codex = ralph.codex


def plan(*, authority: str = "write", scope: object = None, schema: str | None = "zen_ralph_plan_v2") -> dict:
    candidate = {
        "goal": "Bind bounded repository mutations to the approved plan",
        "repository_authority": authority,
        "planning": {"min_steps": 1, "max_steps": 1},
        "steps": [{
            "id": 1,
            "title": "Bind scope",
            "objective": "Persist one machine-readable path scope.",
            "acceptance": ["The scope is hash-bound."],
            "test_change_policy": "add-only",
        }],
    }
    if schema is not None:
        candidate["schema"] = schema
    if scope is not None:
        candidate["repository_mutation_scope"] = scope
    return candidate


class RepoHarness:
    PATH_NAMES = (
        "ROOT", "RALPH", "STATE", "PLAN", "IDEAS", "JOURNAL", "POLICY", "LIVE", "CONTEXT",
        "EVENTS", "RECOVERY", "REPORTS", "RETIREMENTS", "USAGE_LEDGER", "USAGE_STATS_RESET",
    )

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {name: getattr(ralph, name) for name in self.PATH_NAMES}
        self.saved_gate_live = ralph.ralph_gate.LIVE

    def __enter__(self):
        def run(*args: str) -> None:
            subprocess.run(args, cwd=self.root, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        run("git", "init", "-q")
        run("git", "config", "user.email", "ralph@example.invalid")
        run("git", "config", "user.name", "RALPH Test")
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".ralph").mkdir()
        (self.root / ".ralph" / "policy.md").write_text("# policy\n", encoding="utf-8")
        run("git", "add", "app.py", ".ralph/policy.md")
        run("git", "commit", "-qm", "baseline")
        ralph.bind_controller_root(self.root)
        ralph.init_files()
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.saved.items():
            setattr(ralph, name, value)
        ralph.ralph_gate.LIVE = self.saved_gate_live
        self.tmp.cleanup()


class RepositoryMutationScopeV2Tests(unittest.TestCase):
    def test_v2_schema_uses_only_native_output_schema_keywords(self):
        codex.validate_output_schema(protocol.PLAN_V2_SCHEMA)
        proposal_schema = ralph.build_proposal_schema(1, 1)
        codex.validate_output_schema(proposal_schema)
        self.assertEqual("zen_ralph_plan_v2", proposal_schema["properties"]["schema"]["enum"][0])
        scope = protocol.PLAN_V2_SCHEMA["properties"]["repository_mutation_scope"]
        self.assertEqual({"type", "maxItems", "items"}, set(scope))
        self.assertEqual({"type"}, set(scope["items"]))
        self.assertEqual(["schema", "repository_mutation_scope", "goal", "steps"], protocol.PLAN_V2_SCHEMA["required"])

    def test_v2_scope_is_canonical_rendered_and_hash_bound(self):
        candidate = plan(scope=["scripts/ralph.py", "tests/test_scope.py"])
        ralph.validate_complete_plan(candidate, ralph.plan_hash(candidate))
        rendered = ralph.render_plan(candidate)
        self.assertIn(
            "**Repository mutation scope (normalized JSON):** `[\"scripts/ralph.py\",\"tests/test_scope.py\"]`",
            rendered,
        )
        changed_scope = {**candidate, "repository_mutation_scope": ["scripts/ralph.py", "tests/other_scope.py"]}
        self.assertNotEqual(ralph.plan_hash(candidate), ralph.plan_hash(changed_scope))
        unordered_scope = {**candidate, "repository_mutation_scope": ["tests/test_scope.py", "scripts/ralph.py"]}
        with self.assertRaisesRegex(ValueError, "normalized representation"):
            ralph.validate_complete_plan(unordered_scope)

    def test_unapproved_provider_scope_can_be_canonicalized_before_strict_admission(self):
        candidate = plan(scope=["tests/test_scope.py", "./scripts/ralph.py"])
        candidate.pop("repository_authority")
        candidate["repository_mutation_scope"] = list(
            ralph.core.normalize_repository_mutation_scope(
                candidate["repository_mutation_scope"]
            )
        )
        ralph.controller_inject_repository_authority(candidate, "write")
        self.assertEqual(
            ["scripts/ralph.py", "tests/test_scope.py"],
            candidate["repository_mutation_scope"],
        )
        ralph.validate_complete_plan(candidate)

    def test_unapproved_provider_scope_canonicalization_still_rejects_duplicate_semantics(self):
        candidate = plan(scope=["scripts/ralph.py", "./scripts/ralph.py"])
        with self.assertRaisesRegex(ValueError, "unique"):
            ralph.core.normalize_repository_mutation_scope(
                candidate["repository_mutation_scope"]
            )

    def test_cmd_propose_canonicalizes_provider_scope_before_immutable_admission(self):
        proposal = plan(scope=["tests/test_scope.py", "./scripts/ralph.py"])
        proposal.pop("repository_authority")
        proposal.pop("planning")

        args = argparse.Namespace(
            goal=proposal["goal"],
            from_rejection=None,
            from_retirement=None,
            repository_authority="write",
            min_steps=1,
            max_steps=1,
        )

        with (
            RepoHarness(),
            mock.patch.object(
                ralph,
                "query_codex_rate_limits",
                return_value={},
            ),
            mock.patch.object(
                ralph,
                "codex_usage_guard",
                return_value=("SAFE", []),
            ),
            mock.patch.object(
                ralph,
                "run_codex",
                return_value=proposal,
            ),
        ):
            self.assertEqual(0, ralph.cmd_propose(args))

            state = ralph.load_state()

            self.assertEqual("AWAITING_APPROVAL", state["status"])

            self.assertEqual(
                ["scripts/ralph.py", "tests/test_scope.py"],
                state["plan"]["repository_mutation_scope"],
            )

            ralph.validate_complete_plan(
                state["plan"],
                state["plan_hash"],
            )

    def test_write_v2_requires_a_present_bounded_nonempty_scope(self):
        cases = (
            (plan(scope=None), "missing repository mutation scope"),
            (plan(scope="scripts/ralph.py"), "must be an array"),
            (plan(scope=[]), "requires a non-empty"),
            (plan(scope=["*"]), "exact, not glob"),
            (plan(scope=[""]), "non-empty strings"),
            (plan(scope=[f"file-{number}" for number in range(65)]), "at most"),
        )
        for candidate, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                ralph.validate_complete_plan(candidate)

    def test_read_only_v2_requires_and_accepts_an_explicit_empty_scope(self):
        candidate = plan(authority="read-only", scope=[])
        ralph.validate_complete_plan(candidate, ralph.plan_hash(candidate))
        self.assertEqual("read-only", ralph.sandbox_for_approved_plan(candidate, ralph.plan_hash(candidate)))
        with self.assertRaisesRegex(ValueError, "requires an explicit empty"):
            ralph.validate_complete_plan(plan(authority="read-only", scope=["app.py"]))

    def test_artifact_verified_unversioned_and_named_v1_remain_on_v1_dispatch(self):
        with RepoHarness():
            for schema in (None, "zen_ralph_plan_v1"):
                with self.subTest(schema=schema):
                    legacy = plan(schema=schema)
                    legacy.pop("repository_mutation_scope", None)
                    state = ralph.default_state()
                    state.update({"status": "APPROVED", "plan": legacy, "plan_hash": ralph.plan_hash(legacy), "current_step": 1})
                    ralph.PLAN.write_text(ralph.render_plan(legacy), encoding="utf-8")
                    ralph.bind_approved_plan_artifact(state)
                    checkpoint = ralph.create_recovery_checkpoint(state)
                    state["recovery_checkpoint"] = checkpoint["id"]
                    state["approval_repository_evidence"] = checkpoint["repository_evidence"]
                    self.assertEqual("v1", ralph.verified_approved_plan_dispatch(state)[1])


if __name__ == "__main__":
    unittest.main()
