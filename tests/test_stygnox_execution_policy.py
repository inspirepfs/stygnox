"""D8.5 reviewer-bound execution-policy characterization tests."""
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

from stygnox import adoption, execution_policy, provider_codex, transactions  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.5 Test")
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


def adopt(repo: Path, external: Path, **kwargs: object) -> dict:
    resolved = identity(external)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(repo, "Operator One", **kwargs)
        return adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", **kwargs)


class StygnoxExecutionPolicyTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_neutral_defaults_and_profile_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            adopt(repo, root / "external")
            status = execution_policy.show_policy(repo)
            self.assertIsNone(status["policy"]["provider"])
            self.assertIsNone(status["policy"]["model"])
            self.assertIsNone(status["policy"]["effort"])
            self.assertEqual("RELAXED", status["policy"]["efficiency_mode"])
            self.assertEqual(5.0, status["policy"]["reserve_percent"])
            self.assertTrue(status["policy"]["wait_for_limits"])
            self.assertEqual(60, status["policy"]["usage_poll_seconds"])
            self.assertEqual(1, status["policy"]["max_loops"])
            self.assertEqual("Stygnox", status["profile"]["identity"])
            self.assertEqual(".stygnox", status["profile"]["runtime_directory"])

    def test_non_neutral_adoption_requires_reviewer_and_binds_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            resolved = identity(root / "external")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
                with self.assertRaisesRegex(adoption.AdoptionError, "reviewer"):
                    adoption.build_preview(repo, "Operator One", provider="codex", model="gpt-test", effort="high")
                preview = adoption.build_preview(
                    repo,
                    "Operator One",
                    provider="codex",
                    model="gpt-test",
                    effort="high",
                    reviewer="Reviewer One",
                )
                self.assertEqual("Reviewer One", preview["execution_policy"]["review"]["reviewer"])
                result = adoption.handoff_adoption(
                    repo,
                    "Operator One",
                    preview["preview_sha256"],
                    "HANDOFF",
                    provider="codex",
                    model="gpt-test",
                    effort="high",
                    reviewer="Reviewer One",
                )
            self.assertEqual("codex", result["execution_policy_review"]["provider"])
            status = execution_policy.show_policy(repo)
            self.assertTrue(status["approved"])
            self.assertEqual("gpt-test", status["policy"]["model"])

    def test_atomic_set_reset_and_stale_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            adopt(repo, root / "external")
            preview = execution_policy.build_policy_preview(
                repo,
                "Operator One",
                reviewer="Reviewer One",
                provider="codex",
                model="gpt-test",
                effort="high",
                efficiency_mode="RELAXED",
                reserve_percent=7.0,
                wait_for_limits=True,
                usage_poll_seconds=45,
                max_loops=1,
            )
            changed = execution_policy.apply_policy(
                repo,
                "Operator One",
                preview["preview_sha256"],
                "SET",
                reviewer="Reviewer One",
                provider="codex",
                model="gpt-test",
                effort="high",
                efficiency_mode="RELAXED",
                reserve_percent=7.0,
                wait_for_limits=True,
                usage_poll_seconds=45,
                max_loops=1,
                reset=False,
            )
            self.assertEqual("EXECUTION_POLICY_SET", changed["result"])
            status = execution_policy.show_policy(repo)
            self.assertTrue(status["approved"])
            self.assertEqual(7.0, status["policy"]["reserve_percent"])

            reset_preview = execution_policy.build_policy_preview(repo, "Operator One", reset=True)
            reset = execution_policy.apply_policy(
                repo,
                "Operator One",
                reset_preview["preview_sha256"],
                "RESET",
                reset=True,
            )
            self.assertEqual("EXECUTION_POLICY_RESET", reset["result"])
            self.assertIsNone(execution_policy.show_policy(repo)["policy"]["provider"])

            stale = execution_policy.build_policy_preview(
                repo,
                "Operator One",
                reviewer="Reviewer One",
                provider="codex",
                model="gpt-test",
            )
            (repo / "README.md").write_text("operator change\n", encoding="utf-8")
            with self.assertRaises(execution_policy.ExecutionPolicyError):
                execution_policy.apply_policy(
                    repo,
                    "Operator One",
                    stale["preview_sha256"],
                    "SET",
                    reviewer="Reviewer One",
                    provider="codex",
                    model="gpt-test",
                    reset=False,
                )

    def test_policy_change_refuses_after_transaction_begin(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            resolved = identity(root / "external")
            adopt(repo, root / "external")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
                transactions.begin_transaction(repo, "Operator One", "BEGIN")
            with self.assertRaisesRegex(execution_policy.ExecutionPolicyError, "before the first transaction"):
                execution_policy.build_policy_preview(
                    repo,
                    "Operator One",
                    reviewer="Reviewer One",
                    provider="codex",
                    model="gpt-test",
                )


if __name__ == "__main__":
    import unittest
    unittest.main()
