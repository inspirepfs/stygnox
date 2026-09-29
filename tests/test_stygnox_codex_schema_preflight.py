from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


codex = load_module("stygnox_codex_schema_preflight", SCRIPTS / "stygnox_codex.py")
protocol = load_module("stygnox_protocol_schema_preflight", SCRIPTS / "stygnox_protocol.py")


class CodexOutputSchemaPreflightTests(unittest.TestCase):
    def run_codex(self, schema: dict, stream_process):
        with tempfile.TemporaryDirectory() as root:
            return codex.run_codex(
                "prompt",
                schema,
                "workspace-write",
                cwd=Path(root),
                prefix=["codex"],
                stream_process=stream_process,
                normalize_failure=lambda text: text,
                clip=lambda text, limit: text,
                live_write=lambda message, category: None,
            )

    def test_protocol_output_schemas_pass_preflight_before_running_a_turn(self):
        for name, schema in (
            ("PLAN_SCHEMA", protocol.PLAN_SCHEMA),
            ("RESULT_SCHEMA", protocol.RESULT_SCHEMA),
        ):
            with self.subTest(schema=name):
                turns: list[list[str]] = []

                def stream_process(command: list[str]):
                    turns.append(command)
                    output_path = Path(command[command.index("-o") + 1])
                    output_path.write_text('{"summary":"done"}', encoding="utf-8")
                    return 0, "", {}

                result = self.run_codex(schema, stream_process)

                self.assertEqual(result["summary"], "done")
                self.assertEqual(len(turns), 1)

    def test_unsupported_unique_items_is_rejected_before_running_a_turn(self):
        schema = copy.deepcopy(protocol.PLAN_SCHEMA)
        schema["properties"]["steps"]["items"]["properties"]["id"]["uniqueItems"] = True
        turns: list[list[str]] = []

        def stream_process(command: list[str]):
            turns.append(command)
            return 0, "", {}

        with self.assertRaisesRegex(
            ValueError,
            r"unsupported output-schema keyword at "
            r"\$\.properties\.steps\.items\.properties\.id\.uniqueItems: uniqueItems",
        ):
            self.run_codex(schema, stream_process)

        self.assertEqual(turns, [])

    def test_escaped_provider_invalid_json_schema_is_a_non_retryable_contract_defect(self):
        output = json.dumps({
            "type": "turn.failed",
            "error": {"message": json.dumps({
                "type": "invalid_json_schema", "message": "provider rejected schema",
            })},
        })

        with self.assertRaisesRegex(
            codex.ProviderContractDefect,
            r"Codex provider-contract defect: invalid_json_schema; no deterministic retry path: "
            r"provider rejected schema",
        ):
            self.run_codex(protocol.RESULT_SCHEMA, lambda command: (1, output, {}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
