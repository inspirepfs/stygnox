"""D8.2 installed bootstrap/admission characterization tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path, *, commit: bool = True) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.2 Test")
    git(path, "config", "user.email", "test@example.invalid")
    if commit:
        (path / "README.md").write_text("baseline\n", encoding="utf-8")
        git(path, "add", "README.md")
        git(path, "commit", "-q", "-m", "baseline")


def external_command_identity(temp: Path) -> adoption.CommandIdentity:
    executable = temp / "bin" / "stygnox"
    package = temp / "site-packages" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev2")


class StygnoxAdoptionTests(TestCase):
    def preview(self, repo: Path, temp: Path, *, evidence: Path | None = None) -> dict:
        identity = external_command_identity(temp)
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
            return adoption.build_preview(repo, "Operator One", dirty_evidence=evidence)

    def test_preview_is_read_only_and_exposes_tracked_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            before = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
            preview = self.preview(repo, base / "external")
            after = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
            self.assertEqual(before, after)
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists())
            self.assertFalse((repo / adoption.CONFIG_NAME).exists())
            self.assertTrue(preview["admissible"])
            self.assertEqual("clean", preview["baseline"]["journey"])
            self.assertEqual({"provider": None, "model": None, "effort": None}, preview["defaults"])
            paths = {item["path"] for item in preview["tracked_review"]}
            self.assertEqual({".gitignore", adoption.CONFIG_NAME, adoption.POLICY_NAME}, paths)

    def test_preview_digest_changes_when_baseline_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            first = self.preview(repo, base / "external")
            (repo / "README.md").write_text("changed\n", encoding="utf-8")
            second = self.preview(repo, base / "external2")
            self.assertNotEqual(first["baseline"]["sha256"], second["baseline"]["sha256"])
            self.assertNotEqual(first["preview_sha256"], second["preview_sha256"])

    def test_abort_requires_exact_preview_and_makes_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            identity = external_command_identity(base / "external")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
                preview = adoption.build_preview(repo, "Operator One")
                result = adoption.abort_adoption(repo, "Operator One", preview["preview_sha256"])
            self.assertEqual("ABORTED_NO_CHANGE", result["result"])
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists())
            self.assertFalse((repo / adoption.CONFIG_NAME).exists())

    def test_stale_preview_refuses_handoff_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            identity = external_command_identity(base / "external")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
                preview = adoption.build_preview(repo, "Operator One")
                (repo / "new.txt").write_text("operator change\n", encoding="utf-8")
                with self.assertRaisesRegex(adoption.AdoptionError, "preview is stale"):
                    adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF")
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists())
            self.assertFalse((repo / adoption.CONFIG_NAME).exists())

    def test_handoff_writes_exact_tracked_boundary_and_ignored_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            identity = external_command_identity(base / "external")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
                preview = adoption.build_preview(repo, "Operator One")
                result = adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF")
            self.assertEqual("HANDOFF_RECORDED", result["result"])
            self.assertTrue((repo / adoption.CONFIG_NAME).is_file())
            self.assertTrue((repo / adoption.POLICY_NAME).is_file())
            runtime_record = repo / adoption.RUNTIME_NAME / "adoption.json"
            self.assertTrue(runtime_record.is_file())
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", "--no-index", ".stygnox/adoption.json"],
                cwd=repo,
                check=False,
            )
            self.assertEqual(0, ignored.returncode)
            status = git(repo, "status", "--short", "--untracked-files=all").stdout
            self.assertIn("stygnox.toml", status)
            self.assertIn("stygnox.policy.md", status)
            self.assertNotIn(".stygnox", status)
            config = tomllib.loads((repo / adoption.CONFIG_NAME).read_text(encoding="utf-8"))
            self.assertEqual("", config["defaults"]["provider"])
            self.assertEqual("", config["defaults"]["model"])
            self.assertEqual("", config["defaults"]["effort"])
            self.assertFalse(config["authority"]["controller_execution"])

    def test_runtime_api_refuses_agent_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(PermissionError, "controller-owned"):
                adoption.write_runtime_record(root, "probe.json", {"x": 1}, actor="agent")
            self.assertFalse((root / adoption.RUNTIME_NAME).exists())

    def test_reserved_tracked_paths_make_preview_inadmissible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            (repo / adoption.CONFIG_NAME).write_text("operator owned\n", encoding="utf-8")
            preview = self.preview(repo, base / "external")
            self.assertFalse(preview["admissible"])
            self.assertIn(adoption.CONFIG_NAME, preview["conflicts"])

    def test_dirty_preview_requires_external_recovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            (repo / "README.md").write_text("dirty\n", encoding="utf-8")
            preview = self.preview(repo, base / "external")
            self.assertEqual("dirty", preview["baseline"]["journey"])
            self.assertTrue(preview["dirty_recovery"]["required"])
            self.assertFalse(preview["admissible"])

    def test_dirty_external_attestation_must_match_baseline_and_capture_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            init_repo(repo)
            (repo / "README.md").write_text("dirty\n", encoding="utf-8")
            baseline = adoption.capture_baseline(repo)
            capture = base / "capture.bin"
            capture.write_bytes(b"operator-owned-capture")
            evidence = base / "attestation.json"
            evidence.write_text(
                json.dumps(
                    {
                        "schema": adoption.DIRTY_EVIDENCE_SCHEMA,
                        "worktree": str(repo.resolve()),
                        "baseline_sha256": baseline.sha256,
                        "capture_path": str(capture.resolve()),
                        "capture_sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
                        "verified": True,
                        "restoration_rehearsed": True,
                        "verified_by": "External Operator",
                        "categories": list(baseline.dirty_categories),
                    }
                ),
                encoding="utf-8",
            )
            preview = self.preview(repo, base / "external", evidence=evidence)
            self.assertTrue(preview["admissible"])
            capture.write_bytes(b"tampered")
            refused = self.preview(repo, base / "external2", evidence=evidence)
            self.assertFalse(refused["admissible"])
            self.assertIn("digest", refused["evidence_error"])

    def test_command_identity_refuses_worktree_executable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            local = repo / "stygnox"
            local.write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch.object(shutil, "which", return_value=str(local)):
                with self.assertRaisesRegex(adoption.AdoptionError, "inside adopting worktree"):
                    adoption.resolve_installed_command(repo)


if __name__ == "__main__":
    import unittest
    unittest.main()
