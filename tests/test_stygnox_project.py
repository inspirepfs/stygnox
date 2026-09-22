from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.stygnox_project import StygnoxProject


class StygnoxProjectTests(unittest.TestCase):
    def project(self) -> StygnoxProject:
        return StygnoxProject(
            identity="Example Host",
            completion_commit_prefix="chore(example):",
            runtime_dir_name=".control-data",
            controller_cli_relative_path="tools/control.py",
            git_executable="example-git",
            source_roots=("lib", "tools"),
            test_root="checks",
            artifacts=(("state", "state.json"), ("policy", "policy.txt"), ("recovery", "recovery")),
            excluded_dirs=frozenset({"cache"}),
            protected_prefixes=("private/",),
            protected_exact=frozenset({".local-config"}),
            protected_dir_prefixes=(".local/",),
            protected_suffixes=(".private",),
            tooling_paths=frozenset({"tools/control.py"}),
            optional_step_validators=(("format", "tools/format_check.py"),),
            optional_final_validators=(("release", "tools/release_check.py"),),
            execution_prompt_guardrails=("Remain within the checkout.", "", "Preserve qualification."),
            nonrecoverable_validation_markers=("access denied",),
            production_action_keywords=("deploy", "external action"),
            policy_review_guidance=(("actions", ("Compare approved scope.",)),),
            gate_guidance=(("scope_conflict", (("actions", ("Resolve ownership.",)),)),),
            policy_storage_requires_runtime_argument=True,
        )

    def test_frozen_configuration_supports_replace_and_policy_data(self):
        project = self.project()
        changed = replace(project, runtime_dir_name=".alternate")
        self.assertEqual(".control-data", project.runtime_dir_name)
        self.assertEqual(".alternate", changed.runtime_dir_name)
        self.assertEqual(frozenset({"cache"}), project.excluded_dirs)
        self.assertEqual(("private/",), project.protected_prefixes)
        self.assertEqual(frozenset({"tools/control.py"}), project.tooling_paths)
        with self.assertRaises(AttributeError):
            project.identity = "changed"  # type: ignore[misc]

    def test_paths_artifacts_and_controller_git_metadata(self):
        project = self.project()
        root = Path("/tmp/example-host")
        self.assertEqual(root, project.repository_root(root / "tools" / "control.py"))
        self.assertEqual(root / ".control-data", project.runtime_directory(root))
        self.assertEqual(".control-data", project.runtime_relative_path())
        self.assertEqual(".control-data/state.json", project.artifact_relative_path("state"))
        self.assertEqual(root / ".control-data" / "state.json", project.artifact(root, "state"))
        self.assertEqual(root / ".control-data" / "settings.json", project.runtime_config_path(root, "settings.json"))
        self.assertEqual(root / ".control-data" / "recovery" / "cp-7" / "manifest.json", project.recovery_manifest(root, "cp-7"))
        self.assertTrue(project.is_runtime_path("./.control-data/state.json"))
        self.assertFalse(project.is_runtime_path(".other/state.json"))
        self.assertEqual(".control-data/policy.txt", project.policy_reference())
        self.assertEqual(root / "tools/control.py", project.controller_cli(root))
        self.assertEqual("python3 tools/control.py", project.controller_display_command(root))
        self.assertEqual(root, project.git_worktree(root))
        self.assertEqual(["example-git", "status", "--short"], project.git_command("status", "--short"))
        self.assertEqual({"runtime_directory": root / ".control-data"}, project.policy_storage_kwargs(root))

    def test_discovery_validation_gates_rendering_and_guidance(self):
        project = self.project()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "lib").mkdir()
            (root / "lib" / "alpha.py").write_text("value = 1\n", encoding="utf-8")
            (root / "tools").mkdir()
            (root / "tools" / "beta.py").write_text("value = 2\n", encoding="utf-8")
            (root / "tools" / "format_check.py").write_text("", encoding="utf-8")
            (root / "tools" / "release_check.py").write_text("", encoding="utf-8")
            self.assertEqual((root / "lib", root / "tools"), project.source_directories(root))
            self.assertEqual(root / "checks", project.test_directory(root))
            self.assertEqual(("lib/alpha.py", "tools/beta.py", "tools/format_check.py", "tools/release_check.py"), project.python_sources(root))
            gates = project.qualification_gates(root, "python3")
            self.assertEqual(["python3", "-m", "py_compile", *project.python_sources(root)], gates[0][1])
            self.assertEqual(["python3", "-m", "unittest", "discover", "-s", "checks", "-v"], gates[1][1])
            self.assertEqual(("format", ["python3", "tools/format_check.py"]), gates[2])
            self.assertEqual([("release", ["python3", "tools/release_check.py"])], project.final_validator_gates(root, "python3"))
            self.assertEqual({"identity": "Example Host", "repository": root.name, "runtime_directory": ".control-data"}, project.project_metadata(root))
        self.assertEqual("Remain within the checkout. Preserve qualification.", project.prompt_guardrails())
        self.assertTrue(project.validation_block_is_nonrecoverable("ACCESS DENIED while checking"))
        self.assertFalse(project.validation_block_is_nonrecoverable("test failed"))
        self.assertIn(("production_action", ("deploy", "external action")), project.gate_rules())
        self.assertEqual({"actions": ["Compare approved scope."]}, project.guidance(project.policy_review_guidance))
        self.assertEqual({"actions": ["Resolve ownership."]}, project.guidance_for("scope_conflict"))
        self.assertEqual({}, project.guidance_for("unknown"))


if __name__ == "__main__":
    unittest.main()
