"""Focused dependency-boundary coverage for the Stygnox controller contract."""
from __future__ import annotations

import ast
import dataclasses
import unittest
from pathlib import Path

from scripts import ralph_profile, stygnox_project, stygnox_zen


class StygnoxControllerNeutralityTests(unittest.TestCase):
    def test_controller_compatibility_facade_delegates_to_zen_adapter(self):
        facade_tree = ast.parse(Path(ralph_profile.__file__).read_text(encoding="utf-8"))
        adapter_imports = [
            alias.asname or alias.name
            for node in ast.walk(facade_tree)
            if isinstance(node, ast.ImportFrom) and node.module == "scripts.stygnox_zen"
            for alias in node.names
        ]

        self.assertEqual(
            ["PROJECT_PROFILE", "ZEN_PROFILE", "ProjectProfile"],
            adapter_imports,
        )
        self.assertIs(ralph_profile.ProjectProfile, stygnox_zen.ZenControlProfile)
        self.assertIs(ralph_profile.ZEN_PROFILE, stygnox_zen.ZEN_PROFILE)
        self.assertIs(ralph_profile.PROJECT_PROFILE, stygnox_zen.PROJECT_PROFILE)
        self.assertIs(ralph_profile.PROJECT_PROFILE, ralph_profile.ZEN_PROFILE)
        self.assertEqual("ZEN Control", ralph_profile.PROJECT_PROFILE.identity)
        self.assertEqual(".ralph", ralph_profile.PROJECT_PROFILE.runtime_dir_name)

    def test_neutral_contract_has_no_zen_presentation_or_environment_dependencies(self):
        contract_source = Path(stygnox_project.__file__).read_text(encoding="utf-8")
        contract_tree = ast.parse(contract_source)
        imports = {
            node.module
            for node in ast.walk(contract_tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            alias.name
            for node in ast.walk(contract_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        field_names = {field.name for field in dataclasses.fields(stygnox_project.StygnoxProject)}
        identifiers = {
            node.id.lower()
            for node in ast.walk(contract_tree)
            if isinstance(node, ast.Name)
        }

        self.assertEqual({"__future__", "dataclasses", "pathlib"}, imports)
        self.assertFalse({"zen", "ralph", "web", "routeros", "environment", "environ"} & identifiers)
        self.assertFalse(any(name.startswith("web_") or name.startswith("environment_") for name in field_names))
        self.assertNotIn("scripts.stygnox_zen", contract_source)
        self.assertNotIn("scripts.ralph_web", contract_source)
        self.assertNotIn("scripts.env_validate", contract_source)


if __name__ == "__main__":
    unittest.main()
