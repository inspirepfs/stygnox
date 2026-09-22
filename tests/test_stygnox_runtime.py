from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stygnox_runtime.py"
spec = importlib.util.spec_from_file_location("stygnox_runtime", MODULE_PATH)
runtime = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(runtime)


class RuntimeProcessTests(unittest.TestCase):
    def test_run_process_passes_stdout_stderr_and_input_arguments(self):
        completed = subprocess.CompletedProcess(["tool"], 0, "ok")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed) as run:
            self.assertIs(runtime.run_process(["tool"], cwd=Path("/repo"), input_text="input"), completed)
        run.assert_called_once_with(
            ["tool"], cwd=Path("/repo"), input="input", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def test_git_failure_has_the_existing_exact_error_text(self):
        completed = subprocess.CompletedProcess(["git"], 7, "bad output")
        with mock.patch.object(runtime.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, r"^git status --short failed \(7\): bad output$"):
                runtime._git(["status", "--short"], root=Path("/repo"))

    def test_approval_status_records_skips_porcelain_z_rename_source(self):
        completed = subprocess.CompletedProcess([], 0, "R  destination.py\0source.py\0?? new.py\0")
        with mock.patch.object(runtime, "_git", return_value=completed) as git:
            records = runtime.approval_status_records(root=Path("/repo"), normalize_path=lambda path: f"N:{path}")
        self.assertEqual(records, {"N:destination.py": "R ", "N:new.py": "??"})
        git.assert_called_once_with(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"], root=Path("/repo"),
        )

    def test_write_json_atomic_uses_tmp_suffix_and_replaces_serialized_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            with mock.patch.object(runtime.os, "replace", wraps=runtime.os.replace) as replace:
                runtime.write_json_atomic({"z": 1, "a": [2]}, path=path, directory=path.parent)
            replace.assert_called_once_with(path.with_suffix(".tmp"), path)
            self.assertEqual(path.read_text(encoding="utf-8"), '{\n  "a": [\n    2\n  ],\n  "z": 1\n}\n')


if __name__ == "__main__":
    unittest.main()
