from __future__ import annotations

import argparse
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SOURCE_ROOT / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ralph = load_module("ralph_proposal_schema", SCRIPTS / "ralph.py")
codex = load_module("stygnox_codex_proposal_schema", SCRIPTS / "stygnox_codex.py")


class RepoHarness:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous_root = ralph.ROOT

    def __enter__(self) -> "RepoHarness":
        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=self.root, check=True, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )

        git("init", "-q")
        git("config", "user.email", "ralph@example.invalid")
        git("config", "user.name", "RALPH Test")
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".ralph").mkdir()
        (self.root / ".ralph" / "policy.md").write_text("# temporary test policy\n", encoding="utf-8")
        git("add", "app.py", ".ralph/policy.md")
        git("commit", "-qm", "baseline")
        ralph.bind_controller_root(self.root)
        ralph.init_files()
        return self

    def __exit__(self, *_args: object) -> None:
        ralph.bind_controller_root(self.previous_root)
        self.temporary.cleanup()


def candidate() -> dict:
    return {
        "goal": "Schema builder behavior",
        "steps": [
            {
                "id": number,
                "title": f"Step {number}",
                "objective": f"Exercise bounded step {number}",
                "acceptance": [f"Bounded result {number}"],
                "test_change_policy": "add-only",
            }
            for number in range(1, 3)
        ],
    }


class ProposalSchemaTests(unittest.TestCase):
    def assert_no_unique_items(self, value: object) -> None:
        if isinstance(value, dict):
            self.assertNotIn("uniqueItems", value)
            for child in value.values():
                self.assert_no_unique_items(child)
        elif isinstance(value, list):
            for child in value:
                self.assert_no_unique_items(child)

    def test_replacement_builder_preserves_contract_and_passes_adapter_preflight(self) -> None:
        rejection_ids = ["RJ-00000001", "RJ-00000002"]
        schema = ralph.build_proposal_schema(2, 3, rejection_ids=rejection_ids)
        acknowledgement = schema["properties"]["rejection_acknowledgements"]
        item = acknowledgement["items"]

        self.assertEqual(2, schema["properties"]["steps"]["minItems"])
        self.assertEqual(3, schema["properties"]["steps"]["maxItems"])
        self.assertEqual(2, acknowledgement["minItems"])
        self.assertEqual(2, acknowledgement["maxItems"])
        self.assertEqual(rejection_ids, item["properties"]["rejection_id"]["enum"])
        self.assertEqual(
            sorted(ralph._REJECTION_ACKNOWLEDGEMENT_DISPOSITIONS),
            item["properties"]["disposition"]["enum"],
        )
        self.assertEqual(["rejection_id", "disposition", "scope"], item["required"])
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(["plan", "steps"], item["properties"]["scope"]["required"])
        self.assertFalse(item["properties"]["scope"]["additionalProperties"])
        self.assert_no_unique_items(schema)

        turns: list[list[str]] = []
        with tempfile.TemporaryDirectory() as root:
            def stream_process(command: list[str]):
                turns.append(command)
                Path(command[command.index("-o") + 1]).write_text("{}", encoding="utf-8")
                return 0, "", {}

            codex.run_codex(
                "proposal",
                schema,
                "read-only",
                cwd=Path(root),
                prefix=["codex"],
                stream_process=stream_process,
                normalize_failure=lambda text: text,
                clip=lambda text, limit: text,
                live_write=lambda message, category: None,
            )
        self.assertEqual(1, len(turns))

    def test_normal_builder_applies_bounds_without_replacement_fields(self) -> None:
        schema = ralph.build_proposal_schema(2, 3)

        self.assertEqual(2, schema["properties"]["steps"]["minItems"])
        self.assertEqual(3, schema["properties"]["steps"]["maxItems"])
        self.assertNotIn("rejection_acknowledgements", schema["properties"])
        self.assertNotIn("rejection_acknowledgements", schema["required"])

    def test_cmd_propose_uses_the_production_normal_schema_builder(self) -> None:
        captured_schemas: list[dict] = []

        def run_codex(_prompt: str, schema: dict, _sandbox: str, **_kwargs: object) -> dict:
            captured_schemas.append(schema)
            return candidate()

        args = argparse.Namespace(
            goal="Schema builder behavior",
            from_rejection=None,
            from_retirement=None,
            repository_authority="write",
            min_steps=2,
            max_steps=3,
        )
        with (
            RepoHarness(),
            mock.patch.object(ralph, "query_codex_rate_limits", return_value={}),
            mock.patch.object(ralph, "codex_usage_guard", return_value=("SAFE", [])),
            mock.patch.object(ralph, "run_codex", side_effect=run_codex),
        ):
            self.assertEqual(0, ralph.cmd_propose(args))
            state = ralph.load_state()

        self.assertEqual([ralph.build_proposal_schema(2, 3)], captured_schemas)
        self.assertEqual("AWAITING_APPROVAL", state["status"])
        self.assertEqual({"min_steps": 2, "max_steps": 3}, state["plan"]["planning"])
        self.assertNotIn("rejection_acknowledgements", state["plan"])
        self.assertNotIn("rejection_lineage", state["plan"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
