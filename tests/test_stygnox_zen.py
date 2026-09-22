from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.stygnox_project import StygnoxProject
from scripts.stygnox_zen import PROJECT_PROFILE, ZEN_PROFILE, ZenControlProfile


class ZenControlProfileTests(unittest.TestCase):
    def test_configured_values_preserve_the_current_zen_profile(self):
        profile = ZEN_PROFILE
        self.assertIs(PROJECT_PROFILE, profile)
        self.assertIsInstance(profile, StygnoxProject)
        self.assertEqual("ZEN Control", profile.identity)
        self.assertEqual("chore(zen):", profile.completion_commit_prefix)
        self.assertEqual(".ralph", profile.runtime_dir_name)
        self.assertEqual("scripts/ralph.py", profile.controller_cli_relative_path)
        self.assertEqual("git", profile.git_executable)
        self.assertEqual(("app", "scripts"), profile.source_roots)
        self.assertEqual("tests", profile.test_root)
        self.assertEqual(
            (
                ("state", "state.json"), ("plan", "plan.md"), ("ideas", "ideas.md"),
                ("journal", "journal.md"), ("policy", "policy.md"), ("live", "live.log"),
                ("context", "context.json"), ("events", "events.jsonl"), ("recovery", "recovery"),
                ("reports", "reports"), ("retirements", "retirements"),
                ("usage_ledger", "usage-ledger.jsonl"), ("usage_stats_reset", "usage-stats-reset.json"),
                ("web_job", "web-job.json"), ("web_log", "web-run.log"),
            ),
            profile.artifacts,
        )
        self.assertEqual(frozenset({".git", ".ralph", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules", "data", "logs", "diagnostics", "backup", "backups"}), profile.excluded_dirs)
        self.assertEqual(("secrets/", "certs/"), profile.protected_prefixes)
        self.assertEqual(frozenset({".npmrc", ".pypirc", ".netrc", ".envrc"}), profile.protected_exact)
        self.assertEqual((".codex/", ".direnv/"), profile.protected_dir_prefixes)
        self.assertEqual((".token", ".secret", ".secrets", ".credentials"), profile.protected_suffixes)
        self.assertEqual(
            frozenset({
                ".gitignore", ".ralph/policy.md", "scripts/ralph.py", "scripts/ralph_efficiency.py", "scripts/ralph_model.py", "scripts/ralph_gate.py", "scripts/ralph_tui.py", "scripts/ralph_web.py", "scripts/ralph_profile.py", "tests/test_ralph_lite.py", "tests/test_ralph_efficiency.py", "tests/test_ralph_model.py", "tests/test_ralph_gate.py", "tests/test_ralph_lifecycle.py", "tests/test_ralph_retry_hardening.py", "tests/test_ralph_web.py", "tests/test_ralph_self_hosting.py", "tests/test_ralph_profile_boundary.py", "tests/test_ralph_web_gate_profile_boundary.py", "docs/RALPH-LITE.md",
            }),
            profile.tooling_paths,
        )
        self.assertEqual((("environment", "scripts/env_validate.py"), ("supply-chain", "scripts/supply_chain_validate.py"), ("public-audit", "scripts/public_release_audit.py")), profile.optional_final_validators)
        self.assertEqual((("ux-validator", "scripts/ux_validate.py"),), profile.optional_step_validators)
        self.assertEqual(("Do not interact with live RouterOS, secrets, credentials, or external production systems.",), profile.execution_prompt_guardrails)
        self.assertEqual(("policy violation", "secret", "credential", "routeros", "human decision"), profile.nonrecoverable_validation_markers)
        self.assertEqual(("routeros", "production", "live write", "live action"), profile.production_action_keywords)
        self.assertEqual((), profile.gate_guidance)
        self.assertFalse(profile.policy_storage_requires_runtime_argument)

    def test_legacy_gate_guidance_compatibility_members_and_web_values(self):
        profile = ZEN_PROFILE
        self.assertEqual("incident", profile.incident_reason_keyword)
        self.assertEqual("performance", profile.performance_reason_keyword)
        self.assertEqual("Incident Monitor state is runtime-owned. No verified source/configuration defect was found; operator action/evidence is required before this approved step can advance.", profile.incident_runtime_summary)
        self.assertEqual("Private home-lab operator console", profile.web_login_subtitle)
        self.assertEqual("RALPH-Lite", profile.web_title)
        self.assertEqual("Operator console · CLI/TUI remains authoritative", profile.web_console_subtitle)
        self.assertEqual(
            (
                ("validation_evidence", ("performance", "sample", "acceptance evidence", "snapshot", "validation")),
                ("runtime_evidence", ("incident", "runtime", "diagnostic", "worker", "active durable")),
                ("credentials_or_access", ("credential", "login", "permission", "access token", "authentication")),
                ("security_approval", ("security approval", "security sign-off", "authority approval")),
                ("production_action", ("routeros", "production", "live write", "live action")),
                ("scope_conflict", ("scope conflict", "overlap", "claimed work", "out of scope")),
                ("external_dependency", ("external dependency", "third-party", "upstream", "service unavailable")),
            ),
            profile.gate_rules(),
        )
        self.assertEqual(
            {"actions": ["Compare the requested path/action with the approved step and its test-change policy.", "Use steer for bounded human direction when the objective is still correct; use --allow-new-test only for an exact test path absent at plan approval.", "Retire/re-plan if the approved objective genuinely needs broader existing-file authority."], "success": ["The requested change is demonstrably inside the approved step or is explicitly bounded by a human steering record.", "Existing protected/tooling paths and pre-existing tests remain unchanged unless the approved plan already permits them."], "forbidden": ["Do not use steering to bypass protected paths, RALPH tooling authority, secrets or existing-test protection.", "Do not broaden the whole step merely to clear one blocked path."]},
            profile.guidance(profile.policy_review_guidance),
        )
        self.assertEqual(
            {"actions": ["Review the currently active ZEN incidents and identify the underlying condition.", "Correct the underlying operational condition where appropriate; do not clear evidence merely for release acceptance.", "Run a fresh Incident Monitor scan after the underlying condition has cleared.", "Capture fresh operational diagnostics and verify the Incident Monitor is healthy with zero active incidents."], "success": ["Incident Monitor diagnostic state is healthy.", "Active durable incident count is 0.", "Fresh evidence is produced by the normal monitor/diagnostic path."], "forbidden": ["Do not disable Incident Monitor to obtain PASS.", "Do not edit/delete the incident database to obtain PASS.", "Do not manufacture or manually rewrite release evidence."]},
            profile.guidance(profile.incident_gate_guidance),
        )
        self.assertEqual(
            {"actions": ["Exercise the real workload required by the existing performance contract.", "Capture a fresh operator-owned performance snapshot outside the repository.", "Validate it with python3 scripts/perf_acceptance.py ../zen-performance.json."], "success": ["All configured request-class sample minima and latency budgets pass.", "Prepared-view effectiveness and mutation-lane evidence pass without threshold relaxation."], "forbidden": ["Do not lower sample minima, latency budgets or acceptance thresholds.", "Do not inject synthetic PASS evidence."]},
            profile.guidance(profile.performance_gate_guidance),
        )

    def test_inherited_behavior_validation_and_replace_preserve_zen_paths(self):
        profile = ZEN_PROFILE
        root = Path("/tmp/zen-control")
        self.assertEqual(root / ".ralph", profile.runtime_directory(root))
        self.assertEqual(".ralph", profile.runtime_relative_path())
        self.assertEqual(".ralph/policy.md", profile.policy_reference())
        self.assertEqual(root / ".ralph" / "state.json", profile.artifact(root, "state"))
        self.assertEqual(".ralph/web-run.log", profile.artifact_relative_path("web_log"))
        self.assertEqual(root / ".ralph" / "recovery" / "cp-7" / "manifest.json", profile.recovery_manifest(root, "cp-7"))
        self.assertTrue(profile.is_runtime_path("./.ralph/events.jsonl"))
        self.assertEqual({}, profile.policy_storage_kwargs(root))
        self.assertEqual("python3 scripts/ralph.py", profile.controller_display_command(root))
        self.assertEqual(["git", "status", "--short"], profile.git_command("status", "--short"))
        self.assertEqual(
            {"identity": "ZEN Control", "repository": "zen-control", "runtime_directory": ".ralph"},
            profile.project_metadata(root),
        )
        self.assertTrue(profile.validation_block_is_nonrecoverable("ROUTEROS access blocked"))
        self.assertFalse(profile.validation_block_is_nonrecoverable("unit test failed"))
        changed = replace(profile, runtime_dir_name=".alternate", identity="Alternate ZEN")
        self.assertIsInstance(changed, ZenControlProfile)
        self.assertEqual(".ralph", profile.runtime_dir_name)
        self.assertEqual(".alternate", changed.runtime_dir_name)
        self.assertEqual(".alternate/policy.md", changed.policy_reference())
        self.assertEqual({"runtime_directory": root / ".alternate"}, changed.policy_storage_kwargs(root))
        self.assertEqual(profile.artifacts, changed.artifacts)
        with self.assertRaises(AttributeError):
            profile.identity = "changed"  # type: ignore[misc]
        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            (temporary_root / "app").mkdir()
            (temporary_root / "app" / "main.py").write_text("value = 1\n", encoding="utf-8")
            (temporary_root / "scripts").mkdir()
            (temporary_root / "scripts" / "module.py").write_text("value = 2\n", encoding="utf-8")
            (temporary_root / "scripts" / "ux_validate.py").write_text("", encoding="utf-8")
            self.assertEqual((temporary_root / "app", temporary_root / "scripts"), profile.source_directories(temporary_root))
            self.assertEqual(temporary_root / "tests", profile.test_directory(temporary_root))
            self.assertEqual(("app/main.py", "scripts/module.py", "scripts/ux_validate.py"), profile.python_sources(temporary_root))
            self.assertEqual(
                [("python-compile", ["python3", "-m", "py_compile", "app/main.py", "scripts/module.py", "scripts/ux_validate.py"]), ("unit-tests", ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]), ("ux-validator", ["python3", "scripts/ux_validate.py"])],
                profile.qualification_gates(temporary_root, "python3"),
            )
            self.assertEqual([], profile.final_validator_gates(temporary_root, "python3"))
        self.assertEqual(
            {field.name for field in fields(ZenControlProfile)},
            {field.name for field in fields(profile)},
        )


if __name__ == "__main__":
    unittest.main()
