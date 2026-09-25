from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import provider_codex  # noqa: E402


class InstalledCodexMetricTests(TestCase):
    def test_metric_parser_preserves_historical_metric_contract(self) -> None:
        output = "\n".join(
            (
                "operator text that is not json",
                json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
                json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 70,
                            "cache_write_input_tokens": 5,
                            "output_tokens": 20,
                            "reasoning_output_tokens": 11,
                        },
                    }
                ),
            )
        )

        metrics = provider_codex._metrics_from_jsonl(output)

        self.assertEqual(2, metrics["commands_executed"])
        self.assertEqual(100, metrics["input_tokens"])
        self.assertEqual(70, metrics["cached_input_tokens"])
        self.assertEqual(5, metrics["cache_write_input_tokens"])
        self.assertEqual(20, metrics["output_tokens"])
        self.assertEqual(11, metrics["reasoning_output_tokens"])
        self.assertEqual(0.0, metrics["codex_seconds"])

    def test_metric_parser_uses_latest_completed_turn_usage(self) -> None:
        output = "\n".join(
            (
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 4}}),
            )
        )

        metrics = provider_codex._metrics_from_jsonl(output)

        self.assertEqual(20, metrics["input_tokens"])
        self.assertEqual(4, metrics["output_tokens"])

    def test_execute_returns_metrics_in_installed_provider_result(self) -> None:
        def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
            output_path = Path(args[args.index("-o") + 1])
            output_path.write_text('{"status":"PASS","summary":"done","files_inspected":["src/a.py","tests/test_a.py"]}', encoding="utf-8")
            stream = "\n".join(
                (
                    json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 50,
                                "cached_input_tokens": 30,
                                "cache_write_input_tokens": 3,
                                "output_tokens": 9,
                                "reasoning_output_tokens": 6,
                            },
                        }
                    ),
                )
            )
            return subprocess.CompletedProcess(args, 0, stream)

        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider_codex, "_preflight"), \
             mock.patch.object(provider_codex, "_run", side_effect=fake_run), \
             mock.patch.object(provider_codex.time, "monotonic", side_effect=(10.0, 12.5)):
            result = provider_codex.execute(
                cwd=Path(td),
                prompt="inspect",
                model="gpt-test",
                effort="high",
                repository_authority="read-only",
            )

        self.assertEqual("PASS", result["status"])
        self.assertEqual("done", result["summary"])
        self.assertEqual(["src/a.py", "tests/test_a.py"], result["files_inspected"])
        self.assertEqual(
            {
                "commands_executed": 1,
                "input_tokens": 50,
                "cached_input_tokens": 30,
                "cache_write_input_tokens": 3,
                "output_tokens": 9,
                "reasoning_output_tokens": 6,
                "codex_seconds": 2.5,
                "files_inspected": 2,
            },
            result["metrics"],
        )

    def test_execute_structured_supports_planning_schema_without_changing_default_contract(self) -> None:
        custom_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"steps": {"type": "array"}},
            "required": ["steps"],
        }

        def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
            output_path = Path(args[args.index("-o") + 1])
            output_path.write_text('{"steps":[{"id":1}]}', encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, json.dumps({"type": "turn.completed", "usage": {"input_tokens": 7}}))

        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider_codex, "_preflight"), \
             mock.patch.object(provider_codex, "_run", side_effect=fake_run):
            result = provider_codex.execute_structured(
                cwd=Path(td),
                prompt="plan",
                model="gpt-test",
                effort="high",
                repository_authority="read-only",
                result_schema=custom_schema,
            )

        self.assertEqual({"steps": [{"id": 1}]}, result["payload"])
        self.assertEqual("read-only", result["sandbox"])
        self.assertEqual(7, result["metrics"]["input_tokens"])


if __name__ == "__main__":
    import unittest

    unittest.main()
