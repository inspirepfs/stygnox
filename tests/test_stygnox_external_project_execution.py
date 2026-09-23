"""External-project execution coverage for the Stygnox CLI boundary."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "stygnox_cli.py"
POLICY_TEXT = "# Synthetic target policy\n\nThis file is the target-local tracked authority prerequisite.\n"
LIFECYCLE_COMMANDS = (
    "init", "propose", "approve", "reject", "retire-plan", "inspect-carry-forward",
    "adopt-carry-forward", "leave-carry-forward-outside", "reject-carry-forward", "run",
    "efficiency-policy", "model-policy", "models", "redeem-reset", "usage-reset-stats",
    "steer", "authorize-self-hosting", "resume", "resolve-gate", "recover-interrupted-run",
    "recover-self-upgrade", "recover-validation-block", "checkpoints", "checkpoint-info",
    "report", "requalify", "finalize", "reconcile-commit", "reconcile-push",
    "adopt-test-reconciliation", "usage", "operator-snapshot", "status",
)


def load_wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stygnox_external_execution_wrapper", CLI)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime_bytes(root: Path) -> dict[str, bytes]:
    runtime = root / ".ralph"
    if not runtime.exists():
        return {}
    return {
        path.relative_to(runtime).as_posix(): path.read_bytes()
        for path in sorted(runtime.rglob("*"))
        if path.is_file()
    }


class ExternalProjectExecutionTests(unittest.TestCase):
    def seed_target_repository(self, root: Path) -> None:
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        policy = root / ".ralph" / "policy.md"
        policy.parent.mkdir()
        policy.write_text(POLICY_TEXT, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", ".ralph/policy.md"], check=True)
        tracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", ".ralph/policy.md"],
            check=True, text=True, capture_output=True,
        )
        self.assertEqual(".ralph/policy.md", tracked.stdout.strip())

    def invoke(self, caller: Path, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["HOME"] = str(home)
        return subprocess.run(
            [sys.executable, str(CLI), *arguments], cwd=caller, env=environment,
            text=True, capture_output=True, check=False,
        )

    def test_real_cli_binds_only_the_selected_external_runtime(self) -> None:
        own_runtime_before = runtime_bytes(ROOT)
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            home = workspace / "isolated-home"
            home.mkdir()
            first, second = workspace / "first", workspace / "second"
            caller_one, caller_two = workspace / "caller-one", workspace / "caller-two"
            caller_one.mkdir()
            caller_two.mkdir()
            self.seed_target_repository(first)
            self.seed_target_repository(second)

            initialized_first = self.invoke(caller_one, home, "init", "--project-root", str(first))
            self.assertEqual(0, initialized_first.returncode, initialized_first.stderr)
            self.assertIn(str(first / ".ralph"), initialized_first.stdout)
            first_after_init = runtime_bytes(first)
            self.assertIn("state.json", first_after_init)
            self.assertNotEqual({"policy.md": POLICY_TEXT.encode()}, first_after_init)
            self.assertEqual({"policy.md": POLICY_TEXT.encode()}, runtime_bytes(second))

            first_status = self.invoke(caller_two, home, "--project-root", str(first), "status")
            self.assertEqual(0, first_status.returncode, first_status.stderr)
            self.assertIn("status=IDLE", first_status.stdout)
            self.assertEqual(first_after_init, runtime_bytes(first))

            initialized_second = self.invoke(caller_two, home, "--project-root", str(second), "init")
            self.assertEqual(0, initialized_second.returncode, initialized_second.stderr)
            second_after_init = runtime_bytes(second)
            self.assertIn("state.json", second_after_init)
            self.assertEqual(first_after_init, runtime_bytes(first))

            second_status = self.invoke(caller_one, home, "status", "--project-root", str(second))
            self.assertEqual(0, second_status.returncode, second_status.stderr)
            self.assertIn("status=IDLE", second_status.stdout)
            self.assertEqual(second_after_init, runtime_bytes(second))
            self.assertFalse((home / "mikrotik-control").exists())

            invalid_root = workspace / "not-a-repository"
            invalid_root.mkdir()
            invalid = self.invoke(caller_one, home, "status", "--project-root", str(invalid_root))
            self.assertNotEqual(0, invalid.returncode)
            self.assertIn("--project-root refused", invalid.stderr)
            self.assertEqual({}, runtime_bytes(invalid_root))

            refused_web = self.invoke(caller_one, home, "serve", "--project-root", str(first))
            self.assertNotEqual(0, refused_web.returncode)
            self.assertIn("refuses serve/Web", refused_web.stderr)
            self.assertEqual(first_after_init, runtime_bytes(first))

        self.assertEqual(own_runtime_before, runtime_bytes(ROOT))

    def test_every_external_lifecycle_dispatches_only_after_rebound_binding(self) -> None:
        wrapper = load_wrapper()
        rebound_root = Path("/synthetic/rebound-root")
        events: list[tuple[str, Path | str]] = []
        controller = ModuleType("ralph")
        controller.bound_root = None

        def bind(root: Path) -> None:
            events.append(("bind", root))
            controller.bound_root = root

        def dispatch() -> int:
            self.assertEqual(rebound_root, controller.bound_root)
            events.append(("dispatch", controller.bound_root))
            return 23

        roots = ModuleType("stygnox_project_root")
        roots.ProjectRootError = ValueError

        def resolve(supplied: str) -> Path:
            events.append(("resolve", supplied))
            return rebound_root

        controller.bind_controller_root = mock.Mock(side_effect=bind)
        controller.main = mock.Mock(side_effect=dispatch)
        roots.resolve_project_root = mock.Mock(side_effect=resolve)

        with mock.patch.dict(sys.modules, {"ralph": controller, "stygnox_project_root": roots}):
            for command in LIFECYCLE_COMMANDS:
                with self.subTest(command=command):
                    events.clear()
                    controller.bound_root = None
                    controller.bind_controller_root.reset_mock()
                    controller.main.reset_mock()
                    roots.resolve_project_root.reset_mock()
                    argv = ["stygnox", command, "--project-root", "/caller/supplied-root"]
                    with mock.patch.object(sys, "argv", argv):
                        self.assertEqual(23, wrapper.main())
                    self.assertEqual(
                        [("resolve", "/caller/supplied-root"), ("bind", rebound_root), ("dispatch", rebound_root)],
                        events,
                    )
                    roots.resolve_project_root.assert_called_once_with("/caller/supplied-root")
                    controller.bind_controller_root.assert_called_once_with(rebound_root)
                    controller.main.assert_called_once_with()

    def test_failed_binding_and_external_web_never_dispatch(self) -> None:
        wrapper = load_wrapper()
        controller = ModuleType("ralph")
        controller.bind_controller_root = mock.Mock()
        controller.main = mock.Mock()
        roots = ModuleType("stygnox_project_root")
        roots.ProjectRootError = ValueError
        roots.resolve_project_root = mock.Mock(side_effect=ValueError("invalid target"))

        with mock.patch.dict(sys.modules, {"ralph": controller, "stygnox_project_root": roots}):
            with mock.patch.object(sys, "argv", ["stygnox", "status", "--project-root", "/invalid"]):
                with self.assertRaisesRegex(SystemExit, "--project-root refused"):
                    wrapper.main()
            with mock.patch.object(sys, "argv", ["stygnox", "serve", "--project-root", "/external"]):
                with self.assertRaisesRegex(SystemExit, "refuses serve/Web"):
                    wrapper.main()

        controller.bind_controller_root.assert_not_called()
        controller.main.assert_not_called()


if __name__ == "__main__":
    unittest.main()
