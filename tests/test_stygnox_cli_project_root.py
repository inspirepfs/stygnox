"""Regression coverage for retirement of the source-tree Ralph wrapper."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import patch


WRAPPER = Path(__file__).resolve().parents[1] / "scripts" / "stygnox_cli.py"


def load_wrapper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stygnox_cli_project_root_test", WRAPPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StygnoxCliProjectRootTests(TestCase):
    def setUp(self) -> None:
        self.wrapper = load_wrapper()

    def test_project_roots_are_not_an_authority_selection_surface(self) -> None:
        for arguments in (
            ("controller", "status", "--project", "/external/project"),
            ("bootstrap", "--project-root", "/external/project"),
            ("status", "--project-root", "/external/project"),
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(SystemExit, "source-tree wrapper is retired"):
                    self.wrapper.main(arguments)

    def test_hostile_legacy_modules_cannot_capture_the_retired_wrapper(self) -> None:
        sentinel = object()
        with patch.dict(sys.modules, {"ralph": sentinel, "stygnox_project_root": sentinel}):
            with self.assertRaisesRegex(SystemExit, "install Stygnox independently"):
                self.wrapper.main(("controller", "status", "--project", "/external/project"))

    def test_web_routes_remain_explicitly_refused(self) -> None:
        for command in ("serve", "web", "web-auth"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(SystemExit, "refuses serve/Web"):
                    self.wrapper.main((command, "--project-root", "/external/project"))

    def test_wrapper_has_no_legacy_authority_or_execution_dependency(self) -> None:
        tree = ast.parse(WRAPPER.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertFalse({"ralph", "stygnox_project_root", "subprocess", "os", "Path"} & imported)
        self.assertFalse({"ralph", "bind_controller_root", "resolve_project_root", "execvp", "run"} & names)
