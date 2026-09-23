from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE = SOURCE_ROOT / "scripts" / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph_external_project_integration", MODULE)
ralph = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ralph)
ralph_gate = ralph.ralph_gate


class ExternalProjectIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_root = ralph.ROOT

    def tearDown(self) -> None:
        ralph.bind_controller_root(self.original_root)

    def test_rebound_controller_uses_external_project_without_touching_source_runtime(self) -> None:
        caller_cwd = Path.cwd()
        source_controller = Path(ralph.__file__).resolve()
        source_runtime = ralph.PROJECT_PROFILE.runtime_directory(SOURCE_ROOT)
        source_runtime_before = self._runtime_snapshot(source_runtime)
        zen_control_before = self._git_status(SOURCE_ROOT)

        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary).resolve()
            initial_project = temporary_root / "stygnox-fixture"
            external_project = temporary_root / "external-project"
            explicit_cwd = external_project / "explicit-cwd"
            for root, title in (
                (initial_project, "Initial fixture history"),
                (external_project, "External project history"),
            ):
                self._init_repository(root)
                self._write_history(root, title)
            explicit_cwd.mkdir()
            self._write_probe(external_project, "external")
            self._write_probe(explicit_cwd, "explicit")

            ralph.bind_controller_root(initial_project)
            initial_live = ralph.PROJECT_PROFILE.artifact(initial_project, "live")
            self.assertEqual("Initial fixture history", ralph_gate.gate_history()[0]["title"])

            ralph.bind_controller_root(external_project)

            omitted_cwd = ralph.run_process([sys.executable, "qualification_probe.py"])
            explicit_cwd_result = ralph.run_process(
                [sys.executable, "qualification_probe.py"], cwd=explicit_cwd,
            )

            self.assertEqual(external_project, ralph.ROOT)
            self.assertEqual(
                ralph.PROJECT_PROFILE.artifact(external_project, "live"), ralph_gate.LIVE,
            )
            self.assertEqual(0, omitted_cwd.returncode, omitted_cwd.stdout)
            self.assertEqual("external", omitted_cwd.stdout.strip())
            self.assertEqual(0, explicit_cwd_result.returncode, explicit_cwd_result.stdout)
            self.assertEqual("explicit", explicit_cwd_result.stdout.strip())
            self.assertEqual("External project history", ralph_gate.gate_history()[0]["title"])
            self.assertEqual("Initial fixture history", ralph_gate.gate_history(initial_live)[0]["title"])
            self.assertEqual(caller_cwd, Path.cwd())
            self.assertEqual(source_controller, Path(ralph.__file__).resolve())
            self.assertEqual(source_runtime_before, self._runtime_snapshot(source_runtime))
            self.assertEqual(zen_control_before, self._git_status(SOURCE_ROOT))

    @staticmethod
    def _init_repository(root: Path) -> None:
        root.mkdir()
        result = subprocess.run(
            ["git", "init", "--quiet", str(root)], text=True, capture_output=True, check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr)

    @staticmethod
    def _write_history(root: Path, title: str) -> None:
        live = ralph.PROJECT_PROFILE.artifact(root, "live")
        live.parent.mkdir(parents=True)
        live.write_text(
            "\n".join(
                (
                    f"[10:00:00] RALPH    loop=0001 step=1/3 phase=implement repair=0 title={title}",
                    "[10:01:00] SUMMARY  BLOCKED_HUMAN: distinct history",
                )
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_probe(root: Path, marker: str) -> None:
        (root / "qualification_probe.py").write_text(
            f"print({marker!r})\n", encoding="utf-8",
        )

    @staticmethod
    def _git_status(root: Path) -> str:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root,
            text=True, capture_output=True, check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout

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
