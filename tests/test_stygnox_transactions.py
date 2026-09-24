"""D8.3 transaction and exact baseline-recovery characterization tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, recovery, transactions  # noqa: E402


def run(argv: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(argv)}\n{result.stdout}\n{result.stderr}")
    return result


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], root, check=check)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def init_repo(root: Path, *, commit: bool = True) -> None:
    root.mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.name", "D8.3 Test")
    git(root, "config", "user.email", "d83@example.invalid")
    if commit:
        (root / "README.md").write_text("baseline\n", encoding="utf-8")
        (root / "stage.txt").write_text("stage baseline\n", encoding="utf-8")
        (root / "work.txt").write_text("work baseline\n", encoding="utf-8")
        (root / "rename.txt").write_text("rename baseline\n", encoding="utf-8")
        (root / "delete.txt").write_text("delete baseline\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", "baseline")


def identity(base: Path) -> adoption.CommandIdentity:
    binary = base / "installed" / "bin" / "stygnox"
    package = base / "installed" / "lib" / "stygnox" / "adoption.py"
    binary.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(binary.resolve(), package.resolve(), "0.1.0.dev3")


def make_dirty(root: Path) -> None:
    (root / "stage.txt").write_text("staged change\n", encoding="utf-8")
    git(root, "add", "stage.txt")
    (root / "work.txt").write_text("unstaged change\n", encoding="utf-8")
    git(root, "mv", "rename.txt", "renamed.txt")
    (root / "delete.txt").unlink()
    (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    empty = root / "empty-dir"
    empty.mkdir()


def external_evidence(root: Path, preview: dict, evidence_root: Path) -> Path:
    evidence_root.mkdir(parents=True)
    capture = evidence_root / "dirty-baseline.tar.gz"
    with tarfile.open(capture, "w:gz") as archive:
        archive.add(root, arcname="repo", recursive=True)
    entries = list(recovery.snapshot_worktree(root, include_ignored=True))
    index = root / ".git" / "index"
    manifest = {
        "schema": recovery.OPERATOR_MANIFEST_SCHEMA,
        "baseline_sha256": preview["baseline"]["sha256"],
        "head": preview["baseline"]["head"],
        "branch": preview["baseline"]["branch"],
        "status": preview["baseline"]["status"],
        "index_file_sha256": sha256(index) if index.is_file() else None,
        "worktree_manifest": entries,
        "worktree_manifest_sha256": recovery.manifest_sha256(entries),
    }
    manifest_path = evidence_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    attestation = {
        "schema": adoption.DIRTY_EVIDENCE_SCHEMA,
        "worktree": str(root.resolve()),
        "baseline_sha256": preview["baseline"]["sha256"],
        "capture_path": str(capture.resolve()),
        "capture_sha256": sha256(capture),
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path),
        "verified": True,
        "restoration_rehearsed": True,
        "verified_by": "External D8.3 Operator",
        "categories": preview["baseline"]["dirty_categories"],
    }
    attestation_path = evidence_root / "attestation.json"
    attestation_path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return attestation_path


class StygnoxTransactionTests(unittest.TestCase):
    def adopted(self, root: Path, external: adoption.CommandIdentity, *, evidence: Path | None = None) -> tuple[dict, dict]:
        with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
            preview = adoption.build_preview(root, "Operator", dirty_evidence=evidence)
            handoff = adoption.handoff_adoption(
                root,
                "Operator",
                preview["preview_sha256"],
                "HANDOFF",
                dirty_evidence=evidence,
            )
        return preview, handoff

    def test_clean_handoff_creates_internal_checkpoint_and_authority_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            external = identity(base)
            preview, handoff = self.adopted(root, external)
            self.assertEqual("clean", preview["baseline"]["journey"])
            self.assertEqual("controller-internal", handoff["recovery_source"]["kind"])
            self.assertTrue((root / ".stygnox/recovery/pre-authority.json").is_file())
            self.assertNotEqual(handoff["baseline_sha256"], handoff["authority_baseline"]["sha256"])

    def test_transaction_begin_refuses_post_handoff_project_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            external = identity(base)
            self.adopted(root, external)
            (root / "README.md").write_text("operator changed after handoff\n", encoding="utf-8")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                with self.assertRaisesRegex(transactions.TransactionError, "changed after handoff"):
                    transactions.begin_transaction(root, "Operator", "BEGIN")

    def test_restore_requires_safe_stop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            external = identity(base)
            self.adopted(root, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(root, "Operator", "BEGIN")
            with self.assertRaisesRegex(transactions.TransactionError, "safe stop"):
                transactions.build_recovery_preview(root, "Operator", "discard")

    def test_clean_safe_stop_and_restore_exact_preauthority_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            external = identity(base)
            before = adoption.capture_baseline(root)
            self.adopted(root, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                begin = transactions.begin_transaction(root, "Operator", "BEGIN")
            self.assertFalse(begin["authority"]["controller_execution"])
            (root / "README.md").write_text("post handoff\n", encoding="utf-8")
            (root / "generated.txt").write_text("controller residue\n", encoding="utf-8")
            transactions.stop_transaction(root, "Operator", "qualification", "STOP")
            preview = transactions.build_recovery_preview(root, "Operator", "discard")
            result = transactions.restore_baseline(root, "Operator", preview["preview_sha256"], "RESTORE", "discard")
            self.assertTrue(result["verified"])
            self.assertEqual(before.sha256, adoption.capture_baseline(root).sha256)
            self.assertEqual("baseline\n", (root / "README.md").read_text(encoding="utf-8"))
            self.assertFalse((root / "generated.txt").exists())
            self.assertFalse((root / adoption.CONFIG_NAME).exists())
            self.assertTrue((root / adoption.RUNTIME_NAME / transactions.RECOVERY_RESULT_RECORD).is_file())
            self.assertEqual(0, git(root, "check-ignore", "-q", "--no-index", ".stygnox/transaction.json", check=False).returncode)

    def test_stale_recovery_preview_refuses_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            external = identity(base)
            self.adopted(root, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(root, "Operator", "BEGIN")
            transactions.stop_transaction(root, "Operator", "qualification", "STOP")
            preview = transactions.build_recovery_preview(root, "Operator", "discard")
            (root / "later.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(transactions.TransactionError, "stale"):
                transactions.restore_baseline(root, "Operator", preview["preview_sha256"], "RESTORE", "discard")
            self.assertTrue((root / "later.txt").is_file())

    def test_new_unborn_restore_recovers_initial_untracked_and_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root, commit=False)
            (root / "initial.txt").write_text("initial\n", encoding="utf-8")
            (root / "initial-empty").mkdir()
            before = adoption.capture_baseline(root)
            external = identity(base)
            self.adopted(root, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(root, "Operator", "BEGIN")
            (root / "initial.txt").write_text("overwritten\n", encoding="utf-8")
            shutil.rmtree(root / "initial-empty")
            (root / "post.txt").write_text("post\n", encoding="utf-8")
            transactions.stop_transaction(root, "Operator", "qualification", "STOP")
            preview = transactions.build_recovery_preview(root, "Operator", "discard")
            transactions.restore_baseline(root, "Operator", preview["preview_sha256"], "RESTORE", "discard")
            self.assertEqual(before.sha256, adoption.capture_baseline(root).sha256)
            self.assertEqual("initial\n", (root / "initial.txt").read_text(encoding="utf-8"))
            self.assertTrue((root / "initial-empty").is_dir())
            self.assertFalse((root / "post.txt").exists())

    def test_dirty_transaction_requires_manifest_bound_external_package(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            make_dirty(root)
            external = identity(base)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                first = adoption.build_preview(root, "Operator")
            evidence = external_evidence(root, first, base / "evidence")
            self.adopted(root, external, evidence=evidence)
            manifest_path = Path(json.loads(evidence.read_text())["manifest_path"])
            manifest_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                with self.assertRaisesRegex(transactions.TransactionError, "manifest digest"):
                    transactions.begin_transaction(root, "Operator", "BEGIN")

    def test_dirty_attestation_change_after_handoff_invalidates_transaction_begin(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            make_dirty(root)
            external = identity(base)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                first = adoption.build_preview(root, "Operator")
            evidence = external_evidence(root, first, base / "evidence")
            self.adopted(root, external, evidence=evidence)
            body = json.loads(evidence.read_text(encoding="utf-8"))
            body["verified_by"] = "Changed after handoff"
            evidence.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                with self.assertRaisesRegex(transactions.TransactionError, "attestation changed"):
                    transactions.begin_transaction(root, "Operator", "BEGIN")

    def test_dirty_restore_reproduces_staged_unstaged_rename_delete_untracked_and_modes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            make_dirty(root)
            (root / "untracked.txt").chmod(0o664)
            external = identity(base)
            before = adoption.capture_baseline(root)
            before_manifest = recovery.snapshot_worktree(root, include_ignored=True)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                first = adoption.build_preview(root, "Operator")
            evidence = external_evidence(root, first, base / "evidence")
            self.adopted(root, external, evidence=evidence)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(root, "Operator", "BEGIN")
            (root / "stage.txt").write_text("post-stage\n", encoding="utf-8")
            git(root, "add", "stage.txt")
            (root / "untracked.txt").write_text("post-untracked\n", encoding="utf-8")
            (root / "new-after.txt").write_text("post\n", encoding="utf-8")
            transactions.stop_transaction(root, "Operator", "interrupted", "STOP")
            preview = transactions.build_recovery_preview(root, "Operator", "discard")
            transactions.restore_baseline(root, "Operator", preview["preview_sha256"], "RESTORE", "discard")
            after = adoption.capture_baseline(root)
            self.assertEqual(before.sha256, after.sha256)
            self.assertEqual(before.status, after.status)
            self.assertEqual(before_manifest, recovery.snapshot_worktree(root, include_ignored=True))
            self.assertEqual(0o664, (root / "untracked.txt").stat().st_mode & 0o777)
            self.assertFalse((root / "new-after.txt").exists())

    def test_restore_confirmation_and_disposition_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            init_repo(root)
            external = identity(base)
            self.adopted(root, external)
            with mock.patch.object(adoption, "resolve_installed_command", return_value=external):
                transactions.begin_transaction(root, "Operator", "BEGIN")
            transactions.stop_transaction(root, "Operator", "qualification", "STOP")
            preview = transactions.build_recovery_preview(root, "Operator", "discard")
            with self.assertRaisesRegex(transactions.TransactionError, "RESTORE"):
                transactions.restore_baseline(root, "Operator", preview["preview_sha256"], "NO", "discard")
            with self.assertRaisesRegex(transactions.TransactionError, "supports only explicit"):
                transactions.build_recovery_preview(root, "Operator", "preserve")


if __name__ == "__main__":
    unittest.main()
