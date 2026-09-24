"""Focused admission tests for the Stygnox controller wrapper."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WRAPPER = SCRIPTS / "stygnox_cli.py"


def load_wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stygnox_cli_project_root_test", WRAPPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StygnoxCliProjectRootTests(TestCase):
    def setUp(self) -> None:
        self.wrapper = load_wrapper()
        self.original_pycache_prefix = sys.pycache_prefix
        self.ralph = ModuleType("ralph")
        self.ralph.main = Mock(return_value=17)
        self.ralph.bind_controller_root = Mock()
        self.roots = ModuleType("stygnox_project_root")
        self.roots.ProjectRootError = ValueError
        self.roots.resolve_project_root = Mock(return_value=Path("/resolved/project"))

    def tearDown(self) -> None:
        sys.pycache_prefix = self.original_pycache_prefix

    def test_no_project_root_preserves_exact_delegation_and_arguments(self) -> None:
        original_argv = ["stygnox_cli.py", "status", "--json"]
        with patch.dict(sys.modules, {"ralph": self.ralph, "stygnox_project_root": self.roots}):
            with patch.object(sys, "argv", original_argv):
                self.assertEqual(17, self.wrapper.main())
                self.assertEqual(original_argv, sys.argv)
        self.assertEqual(str((SCRIPTS.parent / ".ralph" / "pycache").resolve()), sys.pycache_prefix)
        self.ralph.main.assert_called_once_with()
        self.ralph.bind_controller_root.assert_not_called()
        self.roots.resolve_project_root.assert_not_called()

    def test_top_level_help_adds_wrapper_option_then_delegates(self) -> None:
        with patch.dict(sys.modules, {"ralph": self.ralph}):
            with patch.object(sys, "argv", ["stygnox_cli.py", "--help"]):
                with patch("builtins.print") as printed:
                    self.assertEqual(17, self.wrapper.main())
        self.assertIn("--project-root PATH", printed.call_args.args[0])
        self.ralph.main.assert_called_once_with()

    def test_each_allowlisted_command_binds_then_dispatches_without_wrapper_tokens(self) -> None:
        expected_commands = {
            "init", "status", "propose", "approve", "reject", "run", "steer", "authorize-self-hosting",
            "resume", "resolve-gate", "retire-plan", "inspect-carry-forward", "adopt-carry-forward",
            "leave-carry-forward-outside", "reject-carry-forward", "recover-interrupted-run",
            "recover-self-upgrade", "recover-validation-block", "checkpoints", "checkpoint-info", "report",
            "requalify", "finalize", "reconcile-commit", "reconcile-push", "adopt-test-reconciliation",
            "efficiency-policy", "model-policy", "models", "redeem-reset", "usage-reset-stats", "usage",
            "operator-snapshot",
        }
        self.assertTrue(expected_commands <= self.wrapper._EXTERNAL_PROJECT_COMMANDS)
        for command in sorted(expected_commands):
            with self.subTest(command=command):
                self.ralph.main.reset_mock()
                self.ralph.bind_controller_root.reset_mock()
                self.roots.resolve_project_root.reset_mock()
                argv = ["stygnox_cli.py", command, "--project-root", "/external/project", "--opaque", "value"]
                with patch.dict(sys.modules, {"ralph": self.ralph, "stygnox_project_root": self.roots}):
                    with patch.object(sys, "argv", argv):
                        self.assertEqual(17, self.wrapper.main())
                        self.assertEqual(["stygnox_cli.py", command, "--opaque", "value"], sys.argv)
                self.roots.resolve_project_root.assert_called_once_with("/external/project")
                self.ralph.bind_controller_root.assert_called_once_with(Path("/resolved/project"))
                self.ralph.main.assert_called_once_with()
                self.assertEqual("/resolved/project/.ralph/pycache", sys.pycache_prefix)

    def test_external_mode_refuses_web_and_unknown_commands_before_dispatch(self) -> None:
        sys.pycache_prefix = "/caller/pycache"
        for command, refusal in (("serve", "serve/Web"), ("unknown", "non-allowlisted")):
            with self.subTest(command=command):
                self.ralph.main.reset_mock()
                self.ralph.bind_controller_root.reset_mock()
                with patch.dict(sys.modules, {"ralph": self.ralph, "stygnox_project_root": self.roots}):
                    with patch.object(sys, "argv", ["stygnox_cli.py", "--project-root", "/external", command]):
                        with self.assertRaisesRegex(SystemExit, refusal):
                            self.wrapper.main()
                self.ralph.main.assert_not_called()
                self.ralph.bind_controller_root.assert_not_called()
                self.assertEqual("/caller/pycache", sys.pycache_prefix)

    def test_external_mode_fails_closed_when_root_resolution_fails(self) -> None:
        sys.pycache_prefix = "/caller/pycache"
        self.roots.resolve_project_root.side_effect = ValueError("not a worktree")
        with patch.dict(sys.modules, {"ralph": self.ralph, "stygnox_project_root": self.roots}):
            with patch.object(sys, "argv", ["stygnox_cli.py", "status", "--project-root", "/bad"]):
                with self.assertRaisesRegex(SystemExit, "--project-root refused"):
                    self.wrapper.main()
        self.ralph.bind_controller_root.assert_not_called()
        self.ralph.main.assert_not_called()
        self.assertEqual("/caller/pycache", sys.pycache_prefix)

    def test_wrapper_scan_rejects_missing_or_repeated_roots(self) -> None:
        with patch.dict(sys.modules, {"ralph": self.ralph}):
            for argv, refusal in (
                (["stygnox_cli.py", "status", "--project-root"], "requires PATH"),
                (["stygnox_cli.py", "status", "--project-root", "/one", "--project-root", "/two"], "only once"),
            ):
                with self.subTest(argv=argv):
                    with patch.object(sys, "argv", argv):
                        with self.assertRaisesRegex(SystemExit, refusal):
                            self.wrapper.main()

    def test_wrapper_introduces_no_implicit_project_state_operations(self) -> None:
        tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
        forbidden_attributes = {
            ("os", "chdir"), ("os", "environ"), ("sys", "path"),
            ("Path", "write_text"), ("Path", "write_bytes"), ("Path", "mkdir"),
        }
        observed_attributes = {
            (node.value.id, node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        }
        forbidden_calls = {"open", "setattr", "delattr"}
        observed_calls = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(forbidden_attributes & observed_attributes)
        self.assertFalse(forbidden_calls & observed_calls)
