from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stygnox_codex.py"
spec = importlib.util.spec_from_file_location("stygnox_codex", MODULE_PATH)
codex = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(codex)


class CodexMetricsAndStreamTests(unittest.TestCase):
    def test_metrics_accumulate_commands_and_latest_turn_usage(self):
        metrics = codex.empty_codex_metrics()
        codex.update_codex_metrics(metrics, {"type": "item.completed", "item": {"type": "command_execution"}})
        codex.update_codex_metrics(metrics, {"type": "turn.completed", "usage": {"input_tokens": 8, "cached_input_tokens": 3, "cache_write_input_tokens": 2, "output_tokens": 5, "reasoning_output_tokens": 4}})
        self.assertEqual(metrics, {"commands_executed": 1, "input_tokens": 8, "cached_input_tokens": 3, "cache_write_input_tokens": 2, "output_tokens": 5, "reasoning_output_tokens": 4})

    def test_stream_renders_jsonl_with_injected_renderer_and_clip(self):
        process = mock.Mock(stdout=["not json\n", json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}) + "\n"])
        process.wait.return_value = 0
        rendered, written, clipped = [], [], []
        def render(event):
            rendered.append(event)
            return [("EVENT", "rendered")]
        def clip(text, limit):
            clipped.append((text, limit))
            return "clipped"
        with mock.patch.object(codex.subprocess, "Popen", return_value=process) as popen:
            result = codex.stream_codex_process(["codex", "exec"], cwd=Path("/repo"), render_event=render, clip=clip, live_write=lambda message, category: written.append((message, category)))
        popen.assert_called_once_with(["codex", "exec"], cwd=Path("/repo"), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        self.assertEqual(result, (0, "not json\n" + json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}) + "\n", {"commands_executed": 1, "input_tokens": 0, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}))
        self.assertEqual(clipped, [("not json", 800)])
        self.assertEqual(rendered[0]["type"], "item.completed")
        self.assertEqual(written, [("clipped", "CODEX"), ("rendered", "EVENT")])


class CodexExecutionTests(unittest.TestCase):
    def test_run_codex_preserves_command_order_temp_prefix_and_structured_result(self):
        captured, writes = {}, []
        def stream(command):
            captured["command"] = command
            output = Path(command[command.index("-o") + 1])
            self.assertTrue(output.parent.name.startswith("ralph-lite-"))
            output.write_text('{"summary":"done"}', encoding="utf-8")
            return 0, "", {}
        with tempfile.TemporaryDirectory() as root:
            result = codex.run_codex("prompt", {"type": "object"}, "workspace-write", cwd=Path(root), prefix=["codex"], selected_model="model", selected_effort="high", stream_process=stream, normalize_failure=lambda text: text, clip=lambda text, limit: f"clip:{text}:{limit}", live_write=lambda message, category: writes.append((message, category)), monotonic=iter((10.0, 12.5)).__next__)
        command = captured["command"]
        self.assertEqual(command[:6], ["codex", "exec", "--model", "model", "--config", 'model_reasoning_effort="high"'])
        self.assertEqual(command[6:12], ["--ephemeral", "--json", "--sandbox", "workspace-write", "--output-schema", command[11]])
        self.assertEqual(command[-3:-1], ["-o", command[-2]])
        self.assertEqual(command[-1], "prompt")
        self.assertEqual(result["summary"], "done")
        self.assertEqual(result["_ralph_metrics"]["codex_seconds"], 2.5)
        self.assertIn(("clip:done:800", "SUMMARY"), writes)

    def test_run_codex_reports_nonzero_and_invalid_structured_output(self):
        with tempfile.TemporaryDirectory() as root:
            common = dict(cwd=Path(root), prefix=["codex"], normalize_failure=lambda text: text, clip=lambda text, limit: text, live_write=lambda message, category: None)
            with self.assertRaisesRegex(RuntimeError, r"codex exec failed \(3\):"):
                codex.run_codex("p", {}, "workspace-write", stream_process=lambda command: (3, "failure", {}), **common)
            with self.assertRaisesRegex(RuntimeError, "invalid structured output"):
                codex.run_codex("p", {}, "workspace-write", stream_process=lambda command: (0, "", {}), **common)

    def test_environment_blocked_retains_metrics_and_normalizes_by_callback(self):
        bwrap = "bwrap: setting up uid map: permission denied"
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(codex.EnvironmentBlocked) as raised:
                codex.run_codex("p", {}, "workspace-write", cwd=Path(root), prefix=["codex"], stream_process=lambda command: (0, bwrap, {"commands_executed": 2}), normalize_failure=lambda text: f"normalized:{text}", clip=lambda text, limit: text, live_write=lambda message, category: None)
        self.assertIn("normalized:bwrap", str(raised.exception))
        self.assertEqual(raised.exception.metrics, {"commands_executed": 2, "codex_seconds": mock.ANY})

    def test_preflight_blocks_and_never_caches_a_prefix(self):
        with self.assertRaises(codex.EnvironmentBlocked):
            codex.sandbox_prefix_from_preflights(1, "bwrap: failed RTM_NEWADDR")
        process = subprocess.CompletedProcess([], 0, "")
        calls = []
        for _ in range(2):
            self.assertEqual(codex.codex_command_prefix(run_process=lambda args: calls.append(args) or process, live_write=lambda message, category: None, which=lambda name: "/bin/codex"), ["codex"])
        self.assertEqual(calls, [["codex", "sandbox", "--", "/bin/true"], ["codex", "sandbox", "--", "/bin/true"]])


class CodexBoundaryTests(unittest.TestCase):
    def test_boundary_has_no_controller_state_or_controller_imports(self):
        source = inspect.getsource(codex)
        self.assertNotIn("_CODEX_PREFIX", source)
        for forbidden in ("import ralph", "ralph_profile", "PROJECT_PROFILE", "ralph_web", "ralph_tui", ".ralph"):
            self.assertNotIn(forbidden, source)
        self.assertIn("render_event", source)
        self.assertIn("normalize_failure", source)
        self.assertIn("clip", source)


if __name__ == "__main__":
    unittest.main()
