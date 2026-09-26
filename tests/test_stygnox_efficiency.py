from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, efficiency, execution_policy, provider_codex, transactions  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Efficiency Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "baseline")


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev5")


def adopted_controller(repo: Path, external: Path, **policy_overrides: object) -> None:
    resolved = identity(external)
    kwargs = {"provider": "codex", "model": "gpt-test", "effort": "high", "reviewer": "Reviewer One"}
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(repo, "Operator One", **kwargs)
        adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", **kwargs)
        if policy_overrides:
            policy_preview = execution_policy.build_policy_preview(
                repo, "Operator One", reviewer="Reviewer One", **policy_overrides
            )
            execution_policy.apply_policy(
                repo,
                "Operator One",
                policy_preview["preview_sha256"],
                "SET",
                reviewer="Reviewer One",
                reset=False,
                **policy_overrides,
            )
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


class StygnoxEfficiencyTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_historical_detailed_defaults_and_runaway_floor_are_preserved(self) -> None:
        policy = execution_policy.neutral_policy()
        self.assertEqual(4, policy["strict_prompt_command_budget"])
        self.assertEqual(8, policy["normal_max_commands"])
        self.assertEqual(32, policy["relaxed_max_commands"])
        self.assertEqual(600_000, policy["normal_max_cumulative_input"])
        self.assertEqual(100_000, policy["normal_max_noncached_input"])
        self.assertEqual(40, policy["runaway_max_commands"])
        with self.assertRaisesRegex(execution_policy.ExecutionPolicyError, "runaway_max_commands"):
            execution_policy.normalize_policy(
                detailed_limits={"relaxed_max_commands": 61, "runaway_max_commands": 60}
            )

    def test_off_disables_ordinary_findings_but_not_runaway_guard(self) -> None:
        policy = execution_policy.normalize_policy(efficiency_mode="OFF")
        result = {
            "metrics": {
                "commands_executed": 45,
                "input_tokens": 3_500_000,
                "cached_input_tokens": 2_900_000,
            },
            "files_inspected": [f"f{i}" for i in range(70)],
        }
        assessment = efficiency.assess(result, policy)
        self.assertEqual("RUNAWAY", assessment["status"])
        self.assertEqual([], assessment["ordinary_findings"])
        self.assertIn("commands 45>40", assessment["runaway_findings"])
        self.assertIn("reported-files 70>64", assessment["runaway_findings"])
        self.assertIn("cumulative-input 3500000>3000000", assessment["runaway_findings"])
        self.assertIn("non-cached-input 600000>500000", assessment["runaway_findings"])

    def test_normal_policy_detects_each_historical_budget_dimension(self) -> None:
        policy = execution_policy.normalize_policy(efficiency_mode="NORMAL")
        result = {
            "metrics": {
                "commands_executed": 12,
                "input_tokens": 931_164,
                "cached_input_tokens": 798_464,
            },
            "files_inspected": [f"f{i}" for i in range(10)],
        }
        assessment = efficiency.assess(result, policy)
        self.assertEqual("WARN", assessment["status"])
        self.assertIn("commands 12>8", assessment["findings"])
        self.assertIn("reported-files 10>8", assessment["findings"])
        self.assertIn("cumulative-input 931164>600000", assessment["findings"])
        self.assertIn("non-cached-input 132700>100000", assessment["findings"])

    def test_detailed_limits_are_tracked_previewed_and_exposed_by_installed_cli(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            resolved = identity(root / "external")
            kwargs = {"provider": "codex", "model": "gpt-test", "effort": "high", "reviewer": "Reviewer One"}
            with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
                preview = adoption.build_preview(repo, "Operator One", **kwargs)
                adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", **kwargs)
            detailed = {"normal_max_commands": 11, "runaway_max_commands": 50}
            policy_preview = execution_policy.build_policy_preview(
                repo,
                "Operator One",
                reviewer="Reviewer One",
                detailed_limits=detailed,
            )
            self.assertEqual(11, policy_preview["proposed"]["normal_max_commands"])
            self.assertEqual(50, policy_preview["proposed"]["runaway_max_commands"])
            execution_policy.apply_policy(
                repo,
                "Operator One",
                policy_preview["preview_sha256"],
                "SET",
                reviewer="Reviewer One",
                detailed_limits=detailed,
                reset=False,
            )
            shown = execution_policy.show_policy(repo)
            self.assertEqual(11, shown["policy"]["normal_max_commands"])
            self.assertEqual(50, shown["policy"]["runaway_max_commands"])
            config = (repo / adoption.CONFIG_NAME).read_text(encoding="utf-8")
            self.assertIn("normal_max_commands = 11", config)
            self.assertIn("runaway_max_commands = 50", config)
            env = {**__import__("os").environ, "PYTHONPATH": str(SRC)}
            help_run = subprocess.run(
                [sys.executable, "-m", "stygnox", "execution-policy", "preview", "--help"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, help_run.returncode, help_run.stderr)
            self.assertIn("--normal-max-commands", help_run.stdout)
            self.assertIn("--runaway-max-noncached-input", help_run.stdout)

    def test_controller_binds_prompt_budget_and_returns_post_turn_efficiency_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            adopted_controller(
                repo,
                root / "external",
                efficiency_mode="NORMAL",
                detailed_limits={"normal_prompt_command_budget": 7},
            )
            preview = controller.build_run_preview(repo, "Operator One", "Inspect safely", "read-only")
            self.assertEqual(7, preview["execution_controls"]["normal_prompt_command_budget"])
            provider_result = {
                "provider": "codex",
                "model": "gpt-test",
                "effort": "high",
                "sandbox": "read-only",
                "status": "PASS",
                "summary": "done",
                "files_inspected": [f"src/f{i}.py" for i in range(10)],
                "metrics": {
                    "commands_executed": 12,
                    "files_inspected": 10,
                    "input_tokens": 931_164,
                    "cached_input_tokens": 798_464,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                    "codex_seconds": 2.0,
                },
            }
            with mock.patch.object(provider_codex, "execute", return_value=provider_result) as execute:
                result = controller.run_controller(
                    repo, "Operator One", "Inspect safely", "read-only", preview["preview_sha256"], "RUN"
                )
            prompt = execute.call_args.kwargs["prompt"]
            self.assertIn("Use at most 7 shell command executions", prompt)
            self.assertIn("Report every repository file you inspected", prompt)
            self.assertEqual("WARN", result["efficiency"]["status"])
            self.assertEqual("efficiency-review-required", result["next_action"])
            self.assertIn("commands 12>8", result["efficiency"]["findings"])
            receipt = json.loads(
                (repo / adoption.RUNTIME_NAME / f"controller-run-{preview['preview_sha256'][:16]}.json").read_text(encoding="utf-8")
            )
            self.assertEqual("WARN", receipt["efficiency"]["status"])
            self.assertTrue(receipt["efficiency"]["requires_review_before_automatic_continuation"])


if __name__ == "__main__":
    import unittest
    unittest.main()
