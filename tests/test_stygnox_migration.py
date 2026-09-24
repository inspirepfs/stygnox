"""D8.4 reversible legacy-runtime migration characterization tests."""
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

from stygnox import adoption, migration, transactions  # noqa: E402


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


def init_legacy_repo(root: Path, *, status: str = "IDLE", custom_ignore: str | None = None) -> None:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.name", "D8.4 Test")
    git(root, "config", "user.email", "d84@example.invalid")
    (root / "README.md").write_text("legacy project\n", encoding="utf-8")
    ignore = ".ralph/*\n!.ralph/policy.md\n" if custom_ignore is None else custom_ignore
    (root / ".gitignore").write_text(ignore, encoding="utf-8")
    legacy = root / ".ralph"
    legacy.mkdir()
    (legacy / "policy.md").write_text("legacy tracked policy\n", encoding="utf-8")
    (legacy / "journal.md").write_text("legacy retained journal\n", encoding="utf-8")
    (legacy / "state.json").write_text(
        json.dumps(
            {
                "schema": migration.LEGACY_STATE_SCHEMA,
                "status": status,
                "controller_runtime": None,
                "updated_at": "2026-09-24T10:46:45+00:00",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    git(root, "add", "README.md", ".gitignore", ".ralph/policy.md")
    git(root, "commit", "-q", "-m", "legacy baseline")


def adopt_and_begin(root: Path, external: adoption.CommandIdentity) -> None:
    with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
        preview = adoption.build_preview(root, "Operator")
        adoption.handoff_adoption(root, "Operator", preview["preview_sha256"], "HANDOFF")
        transactions.begin_transaction(root, "Operator", "BEGIN")


class StygnoxMigrationTests(unittest.TestCase):
    def test_preview_requires_idle_supported_legacy_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-migration-") as temp:
            base = Path(temp)
            repo = base / "repo"
            init_legacy_repo(repo, status="RUNNING")
            external = identity(base)
            adopt_and_begin(repo, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                preview = migration.build_preview(repo, "Operator")
            self.assertFalse(preview["admissible"])
            self.assertTrue(any("must be IDLE" in item for item in preview["blockers"]))
            self.assertTrue((repo / ".ralph").is_dir())

    def test_preview_refuses_unknown_legacy_ignore_semantics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-ignore-") as temp:
            base = Path(temp)
            repo = base / "repo"
            init_legacy_repo(repo, custom_ignore=".ralph/*\n!.ralph/policy.md\n.ralph/**/secret-*\n")
            external = identity(base)
            adopt_and_begin(repo, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                preview = migration.build_preview(repo, "Operator")
            self.assertFalse(preview["admissible"])
            self.assertTrue(any("operator-directed migration" in item for item in preview["blockers"]))

    def test_apply_removes_legacy_authority_and_rollback_restores_exact_git_baseline(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-roundtrip-") as temp:
            base = Path(temp)
            repo = base / "repo"
            init_legacy_repo(repo)
            external = identity(base)
            adopt_and_begin(repo, external)
            before_baseline = adoption.capture_baseline(repo).public()
            before_inventory = migration._legacy_inventory(repo)
            before_index = migration._parse_legacy_index(repo)
            before_ignore = (repo / ".gitignore").read_bytes()

            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                preview = migration.build_preview(repo, "Operator")
                result = migration.apply_migration(repo, "Operator", preview["preview_sha256"], "MIGRATE")
            self.assertEqual("LEGACY_RUNTIME_MIGRATED", result["result"])
            self.assertFalse((repo / ".ralph").exists())
            self.assertEqual([], migration._parse_legacy_index(repo))
            self.assertNotIn(".ralph", (repo / ".gitignore").read_text(encoding="utf-8"))
            self.assertEqual("APPLIED", json.loads((repo / ".stygnox" / "migration.json").read_text())["state"])

            transactions.stop_transaction(repo, "Operator", "qualification", "STOP")
            rollback_preview = migration.build_rollback_preview(repo, "Operator")
            rollback = migration.rollback_migration(
                repo,
                "Operator",
                rollback_preview["preview_sha256"],
                "ROLLBACK",
            )
            self.assertEqual("LEGACY_MIGRATION_ROLLED_BACK", rollback["result"])
            self.assertEqual(before_inventory, migration._legacy_inventory(repo))
            self.assertEqual(before_index, migration._parse_legacy_index(repo))
            self.assertEqual(before_ignore, (repo / ".gitignore").read_bytes())
            self.assertEqual(before_baseline["sha256"], adoption.capture_baseline(repo).public()["sha256"])
            self.assertTrue((repo / ".stygnox" / "migration.json").is_file())

    def test_rollback_refuses_changed_post_migration_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-stale-") as temp:
            base = Path(temp)
            repo = base / "repo"
            init_legacy_repo(repo)
            external = identity(base)
            adopt_and_begin(repo, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                preview = migration.build_preview(repo, "Operator")
                migration.apply_migration(repo, "Operator", preview["preview_sha256"], "MIGRATE")
            transactions.stop_transaction(repo, "Operator", "qualification", "STOP")
            (repo / "after-migration.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(migration.MigrationError, "exact post-migration baseline"):
                migration.build_rollback_preview(repo, "Operator")

    def test_fresh_project_gets_clear_no_change_migration_refusal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-d84-fresh-") as temp:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "D8.4 Test")
            git(repo, "config", "user.email", "d84@example.invalid")
            (repo / "README.md").write_text("fresh\n", encoding="utf-8")
            git(repo, "add", "README.md")
            git(repo, "commit", "-q", "-m", "fresh")
            external = identity(base)
            adopt_and_begin(repo, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                preview = migration.build_preview(repo, "Operator")
            self.assertFalse(preview["admissible"])
            self.assertIn("migration is not required", " ".join(preview["blockers"]))


if __name__ == "__main__":
    unittest.main()
