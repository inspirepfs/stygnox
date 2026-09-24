"""D8.4 support/upgrade/uninstall characterization tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, lifecycle, transactions  # noqa: E402


def run(argv: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(argv)}\n{result.stdout}\n{result.stderr}")
    return result


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], root, check=check)


def identity(base: Path) -> adoption.CommandIdentity:
    binary = base / "venv" / "bin" / "stygnox"
    package = base / "venv" / "lib" / "stygnox" / "adoption.py"
    binary.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(binary.resolve(), package.resolve(), "0.1.0.dev4")


def adopted_repo(base: Path) -> tuple[Path, adoption.CommandIdentity]:
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "D8.4 Test")
    git(repo, "config", "user.email", "d84@example.invalid")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "baseline")
    external = identity(base)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
        preview = adoption.build_preview(repo, "Operator")
        adoption.handoff_adoption(repo, "Operator", preview["preview_sha256"], "HANDOFF")
    return repo, external


class StygnoxLifecycleTests(unittest.TestCase):
    def test_support_policy_is_explicit_and_bounded(self) -> None:
        policy = lifecycle.support_policy()
        self.assertEqual(lifecycle.SUPPORT_POLICY_SCHEMA, policy["schema"])
        self.assertEqual("Linux", policy["platform"]["os"])
        self.assertEqual(">=3.11,<3.14", policy["python"]["supported_range"])
        self.assertEqual(False, policy["install_media"]["source_tree_dependency"])
        self.assertIn("Python wheel installed with pip", policy["install_media"]["supported"][0])
        self.assertFalse(policy["controller_execution"])
        self.assertIn("0.1.0.dev4", policy["project_state_compatibility"]["package_only_upgrade_from"])
        self.assertIn("0.1.0.dev5", policy["project_state_compatibility"]["package_only_upgrade_from"])
        self.assertIn("0.1.0.dev6", policy["project_state_compatibility"]["package_only_upgrade_from"])

    def test_upgrade_refuses_active_transaction_then_accepts_stopped_state_without_tracked_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-upgrade-") as temp:
            base = Path(temp)
            repo, external = adopted_repo(base)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(repo, "Operator", "BEGIN")
            active_preview = lifecycle.build_upgrade_preview(repo, "Operator")
            self.assertFalse(active_preview["admissible"])
            self.assertTrue(any("ACTIVE transaction" in item for item in active_preview["blockers"]))
            transactions.stop_transaction(repo, "Operator", "qualification", "STOP")
            before = adoption.capture_baseline(repo).public()["sha256"]
            preview = lifecycle.build_upgrade_preview(repo, "Operator")
            self.assertTrue(preview["admissible"], preview["blockers"])
            accepted = lifecycle.accept_upgrade(repo, "Operator", preview["preview_sha256"], "UPGRADE")
            self.assertEqual("UPGRADE_COMPATIBILITY_ACCEPTED", accepted["result"])
            self.assertEqual(before, adoption.capture_baseline(repo).public()["sha256"])
            self.assertTrue((repo / ".stygnox" / lifecycle.UPGRADE_RECORD).is_file())

    def test_upgrade_refuses_unknown_authority_schema_before_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-schema-") as temp:
            base = Path(temp)
            repo, _ = adopted_repo(base)
            transaction = repo / ".stygnox" / transactions.TRANSACTION_RECORD
            transaction.write_text(json.dumps({"schema": "future_unknown", "state": "STOPPED"}) + "\n", encoding="utf-8")
            preview = lifecycle.build_upgrade_preview(repo, "Operator")
            self.assertFalse(preview["admissible"])
            self.assertTrue(any("unsupported authority schema" in item for item in preview["blockers"]))
            self.assertFalse((repo / ".stygnox" / lifecycle.UPGRADE_RECORD).exists())

    def test_uninstall_is_safe_idempotent_and_changes_no_tracked_project_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-uninstall-") as temp:
            base = Path(temp)
            repo, external = adopted_repo(base)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(repo, "Operator", "BEGIN")
            active = lifecycle.build_uninstall_preview(repo, "Operator")
            self.assertFalse(active["admissible"])
            transactions.stop_transaction(repo, "Operator", "operator-abort", "STOP")
            before = adoption.capture_baseline(repo).public()["sha256"]
            preview = lifecycle.build_uninstall_preview(repo, "Operator")
            self.assertTrue(preview["admissible"], preview["blockers"])
            first = lifecycle.prepare_uninstall(repo, "Operator", preview["preview_sha256"], "UNINSTALL")
            second_preview = lifecycle.build_uninstall_preview(repo, "Operator")
            self.assertEqual(preview["preview_sha256"], second_preview["preview_sha256"])
            second = lifecycle.prepare_uninstall(repo, "Operator", second_preview["preview_sha256"], "UNINSTALL")
            self.assertEqual("UNINSTALL_PREPARED", first["result"])
            self.assertEqual("UNINSTALL_ALREADY_PREPARED", second["result"])
            self.assertTrue(first["activity_disabled"])
            self.assertFalse(first["tracked_project_mutation"])
            self.assertFalse(first["retained_evidence_deleted"])
            self.assertEqual(before, adoption.capture_baseline(repo).public()["sha256"])


if __name__ == "__main__":
    unittest.main()
