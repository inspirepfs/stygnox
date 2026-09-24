"""D8.5 neutral installed-controller characterization tests."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, provider_codex, transactions  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.5 Controller Test")
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


def adopted_transaction(repo: Path, external: Path, *, reviewed: bool) -> adoption.CommandIdentity:
    resolved = identity(external)
    kwargs = {}
    if reviewed:
        kwargs = {"provider": "codex", "model": "gpt-test", "effort": "high", "reviewer": "Reviewer One"}
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(repo, "Operator One", **kwargs)
        adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", **kwargs)
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
    return resolved


class StygnoxControllerTests(TestCase):
    def test_neutral_controller_activation_has_no_provider_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            resolved = adopted_transaction(repo, root / "external", reviewed=False)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
                active = controller.activate_controller(repo, "Operator One", "ACTIVATE")
            self.assertTrue(active["controller_execution_enabled"])
            self.assertFalse(active["provider_execution_ready"])
            self.assertEqual("Stygnox", active["profile"]["identity"])
            self.assertEqual("stygnox controller", active["profile"]["controller_command"])
            with self.assertRaisesRegex(controller.ControllerError, "defaults are neutral"):
                controller.build_run_preview(repo, "Operator One", "Inspect the project", "read-only")

    def test_reviewed_controller_executes_exact_preview_and_records_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            resolved = adopted_transaction(repo, root / "external", reviewed=True)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
                controller.activate_controller(repo, "Operator One", "ACTIVATE")
            preview = controller.build_run_preview(repo, "Operator One", "Inspect without changes", "read-only")
            with mock.patch.object(
                provider_codex,
                "execute",
                return_value={
                    "provider": "codex",
                    "model": "gpt-test",
                    "effort": "high",
                    "sandbox": "read-only",
                    "status": "PASS",
                    "summary": "inspection complete",
                },
            ) as execute:
                result = controller.run_controller(
                    repo,
                    "Operator One",
                    "Inspect without changes",
                    "read-only",
                    preview["preview_sha256"],
                    "RUN",
                )
            self.assertTrue(result["controller_execution_enabled"])
            self.assertFalse(result["project_changed"])
            self.assertEqual("turn-complete", result["next_action"])
            execute.assert_called_once()
            receipt = repo / adoption.RUNTIME_NAME / f"controller-run-{preview['preview_sha256'][:16]}.json"
            self.assertTrue(receipt.is_file())
            with self.assertRaisesRegex(controller.ControllerError, "stale"):
                controller.run_controller(
                    repo,
                    "Operator One",
                    "different objective",
                    "read-only",
                    preview["preview_sha256"],
                    "RUN",
                )

    def test_controller_deactivation_revokes_execution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            resolved = adopted_transaction(repo, root / "external", reviewed=True)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
                controller.activate_controller(repo, "Operator One", "ACTIVATE")
            stopped = controller.deactivate_controller(repo, "Operator One", "DEACTIVATE")
            self.assertFalse(stopped["controller_execution_enabled"])
            with self.assertRaisesRegex(controller.ControllerError, "not active"):
                controller.build_run_preview(repo, "Operator One", "Inspect", "read-only")


if __name__ == "__main__":
    import unittest
    unittest.main()
