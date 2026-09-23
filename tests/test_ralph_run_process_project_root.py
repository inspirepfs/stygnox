from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE = SOURCE_ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_run_process_project_root", MODULE)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)


class RunProcessProjectRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = ralph.ROOT
        self.original_runtime = ralph.RALPH

    def tearDown(self) -> None:
        ralph.bind_controller_root(self.original_root)

    def test_bound_root_is_used_for_relative_commands_without_chdir(self) -> None:
        self.assertIsNone(inspect.signature(ralph.run_process).parameters["cwd"].default)
        caller_cwd = Path.cwd()
        source_file = Path(ralph.__file__).resolve()
        source_runtime = self.original_runtime
        runtime_before = self._runtime_snapshot(source_runtime)

        with TemporaryDirectory() as temporary:
            external_root = Path(temporary).resolve()
            explicit_root = external_root / "explicit"
            explicit_root.mkdir()
            for root, marker in ((external_root, "external"), (explicit_root, "explicit")):
                (root / "qualification_probe.py").write_text(
                    f"print({marker!r})\n",
                    encoding="utf-8",
                )

            ralph.bind_controller_root(external_root)

            omitted_cwd = ralph.run_process([sys.executable, "qualification_probe.py"])
            explicit_cwd = ralph.run_process(
                [sys.executable, "qualification_probe.py"], cwd=explicit_root,
            )

        self.assertEqual(0, omitted_cwd.returncode, omitted_cwd.stdout)
        self.assertEqual("external", omitted_cwd.stdout.strip())
        self.assertEqual(0, explicit_cwd.returncode, explicit_cwd.stdout)
        self.assertEqual("explicit", explicit_cwd.stdout.strip())
        self.assertEqual(caller_cwd, Path.cwd())
        self.assertEqual(source_file, Path(ralph.__file__).resolve())
        self.assertEqual(source_runtime, SOURCE_ROOT / ".ralph")
        self.assertEqual(runtime_before, self._runtime_snapshot(source_runtime))

    @staticmethod
    def _runtime_snapshot(runtime: Path) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            sorted(
                (str(path.relative_to(runtime)), path.stat().st_mtime_ns, path.stat().st_size)
                for path in runtime.rglob("*")
            )
        )


if __name__ == "__main__":
    unittest.main()
