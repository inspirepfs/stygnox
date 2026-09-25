from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, provider_codex, transactions, usage  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Usage Test")
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


def adopted_transaction(repo: Path, external: Path) -> adoption.CommandIdentity:
    resolved = identity(external)
    kwargs = {"provider": "codex", "model": "gpt-test", "effort": "high", "reviewer": "Reviewer One"}
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(repo, "Operator One", **kwargs)
        adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", **kwargs)
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")
    return resolved


class StygnoxUsageTests(TestCase):
    def test_controller_records_each_completed_turn_in_append_only_usage_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            adopted_transaction(repo, root / "external")
            preview = controller.build_run_preview(repo, "Operator One", "Inspect", "read-only")
            provider_result = {
                "provider": "codex", "model": "gpt-test", "effort": "high", "sandbox": "read-only",
                "status": "PASS", "summary": "done",
                "metrics": {
                    "commands_executed": 2, "input_tokens": 100, "cached_input_tokens": 70,
                    "cache_write_input_tokens": 4, "output_tokens": 20,
                    "reasoning_output_tokens": 7, "codex_seconds": 1.25,
                },
            }
            with mock.patch.object(provider_codex, "execute", return_value=provider_result):
                first = controller.run_controller(repo, "Operator One", "Inspect", "read-only", preview["preview_sha256"], "RUN")
                second = controller.run_controller(repo, "Operator One", "Inspect", "read-only", preview["preview_sha256"], "RUN")

            report = usage.usage_report(repo)
            self.assertEqual(2, report["all_time"]["turns"])
            self.assertEqual(200, report["all_time"]["input_tokens"])
            self.assertEqual(140, report["all_time"]["cached_input_tokens"])
            self.assertEqual(60, report["all_time"]["noncached_input_tokens"])
            self.assertEqual(4, report["all_time"]["commands_executed"])
            self.assertEqual(2.5, report["all_time"]["codex_seconds"])
            self.assertRegex(first["usage_record_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(second["usage_record_sha256"], r"^[0-9a-f]{64}$")
            ledger = repo / adoption.RUNTIME_NAME / usage.USAGE_LEDGER_NAME
            self.assertEqual(2, len(ledger.read_text(encoding="utf-8").splitlines()))
            ledger_text = ledger.read_text(encoding="utf-8")
            self.assertNotIn("Inspect", ledger_text)
            self.assertNotIn("summary", ledger_text)
            self.assertNotIn("done", ledger_text)

    def test_local_reset_moves_baseline_without_deleting_ledger_or_touching_provider_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            old = usage.record_controller_turn(
                repo,
                preview_sha256="a" * 64,
                transaction_id="tx-1",
                repository_authority="read-only",
                provider_result={"provider": "codex", "model": "gpt-test", "metrics": {"input_tokens": 100, "output_tokens": 10}},
            )
            preview = usage.build_reset_preview(repo)
            result = usage.reset_usage_statistics(repo, preview["preview_sha256"], "RESET")
            self.assertEqual("LOCAL_USAGE_BASELINE_RESET", result["result"])
            self.assertFalse(result["provider_quota_mutated"])
            self.assertFalse(result["banked_reset_mutated"])
            self.assertFalse(result["ledger_deleted"])
            time.sleep(0.001)
            usage.record_controller_turn(
                repo,
                preview_sha256="b" * 64,
                transaction_id="tx-2",
                repository_authority="write",
                provider_result={"provider": "codex", "model": "gpt-test", "metrics": {"input_tokens": 50, "cached_input_tokens": 20, "output_tokens": 5}},
            )
            report = usage.usage_report(repo)
            self.assertEqual(2, report["all_time"]["turns"])
            self.assertEqual(150, report["all_time"]["input_tokens"])
            self.assertEqual(1, report["since_reset"]["turns"])
            self.assertEqual(50, report["since_reset"]["input_tokens"])
            self.assertEqual(30, report["since_reset"]["noncached_input_tokens"])
            self.assertEqual(old["record_sha256"], usage.usage_rows(repo, include_before_reset=True)[0]["record_sha256"])
            self.assertEqual(2, len(usage.usage_rows(repo, include_before_reset=True)))

    def test_reset_preview_fails_closed_when_usage_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            usage.record_controller_turn(
                repo,
                preview_sha256="c" * 64,
                transaction_id="tx-1",
                repository_authority="read-only",
                provider_result={"provider": "codex", "model": "gpt-test", "metrics": {"input_tokens": 10}},
            )
            preview = usage.build_reset_preview(repo)
            usage.record_controller_turn(
                repo,
                preview_sha256="d" * 64,
                transaction_id="tx-2",
                repository_authority="read-only",
                provider_result={"provider": "codex", "model": "gpt-test", "metrics": {"input_tokens": 20}},
            )
            with self.assertRaisesRegex(usage.UsageError, "stale"):
                usage.reset_usage_statistics(repo, preview["preview_sha256"], "RESET")

    def test_usage_cli_is_installed_and_reset_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            env = {**__import__("os").environ, "PYTHONPATH": str(SRC)}
            shown = subprocess.run(
                [sys.executable, "-m", "stygnox", "usage", "show", "--project", str(repo)],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, shown.returncode, shown.stderr)
            payload = json.loads(shown.stdout)
            self.assertEqual(usage.USAGE_REPORT_SCHEMA, payload["schema"])
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists(), "read-only usage show must not create runtime state")
            preview_run = subprocess.run(
                [sys.executable, "-m", "stygnox", "usage", "reset-preview", "--project", str(repo)],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, preview_run.returncode, preview_run.stderr)
            reset_preview = json.loads(preview_run.stdout)
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists(), "read-only reset preview must not create runtime state")
            refused = subprocess.run(
                [sys.executable, "-m", "stygnox", "usage", "reset", "--project", str(repo),
                 "--preview", reset_preview["preview_sha256"], "--confirm", "NOPE"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(2, refused.returncode)
            self.assertIn("explicit confirmation required", refused.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
