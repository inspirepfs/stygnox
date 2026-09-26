"""Controlled Git finalization and external reconciliation regressions."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, cli, finalization, planning, provider_codex, qualification  # noqa: E402
from tests.test_stygnox_qualification import (  # noqa: E402
    active_reviewed,
    approve,
    execute_step,
    git,
    init_repo,
    qualify,
)


def ready_repo(root: Path, *, remote: bool = False, read_only: bool = False):
    repo = root / "repo"
    init_repo(repo)
    remote_path = None
    if remote:
        remote_path = root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote_path)], check=True)
        branch = git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip()
        git(repo, "remote", "add", "origin", str(remote_path))
        git(repo, "push", "-q", "-u", "origin", branch)
    authority = "read-only" if read_only else "write"
    active_reviewed(repo, root / "external", repository_authority=authority)
    approved = approve(repo, repository_authority=authority)
    execute_step(repo, approved, filename="src/final.txt", content="final\n")
    result = qualify(repo, approved["plan_hash"])
    return repo, approved, result, remote_path

from tests.provider_catalog_fixture import test_catalog  # noqa: E402


class StygnoxFinalizationTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)
    def test_qualification_binds_git_finalization_evidence_and_cli_route_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            state = planning.plan_status(repo)["plan"]
            final = state["final_qualification"]
            self.assertEqual(git(repo, "rev-parse", "HEAD").stdout.strip(), final["qualified_head"])
            self.assertEqual(git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip(), final["qualified_branch"])
            self.assertEqual(["src/final.txt"], sorted(final["qualified_path_fingerprints"]))
            self.assertEqual(0, cli.main(["finalization", "status", "--project", str(repo)]))
            self.assertEqual(0, cli.main(["finalize", "status", "--project", str(repo)]))

    def test_git_finalization_provenance_normalizes_group_writable_worktree_mode(self) -> None:
        old_umask = os.umask(0o002)
        try:
            with tempfile.TemporaryDirectory() as td:
                repo, approved, _result, _remote = ready_repo(Path(td))
                self.assertEqual(0o664, (repo / "src" / "final.txt").stat().st_mode & 0o777)
                preview = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: umask-normalized")
                result = finalization.commit(repo, "Operator One", approved["plan_hash"], "test: umask-normalized", preview["preview_sha256"], "COMMIT")
                self.assertEqual("COMMITTED", result["result"])
        finally:
            os.umask(old_umask)

    def test_native_commit_is_previewed_stages_only_qualified_delta_and_records_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            preview = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: qualified commit")
            self.assertEqual([], finalization._staged_paths(repo))
            result = finalization.commit(repo, "Operator One", approved["plan_hash"], "test: qualified commit", preview["preview_sha256"], "COMMIT")
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("COMMITTED", result["result"])
            self.assertEqual("COMMITTED", state["status"])
            self.assertEqual(git(repo, "rev-parse", "HEAD").stdout.strip(), state["commit_sha"])
            self.assertEqual(["src/final.txt"], git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD^", "HEAD").stdout.split())
            self.assertEqual("test: qualified commit", git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip())
            # Controller bootstrap/config residue is deliberately not staged into the plan commit.
            self.assertIn("stygnox.toml", git(repo, "status", "--porcelain=v1").stdout)

    def test_native_commit_refuses_stale_preview_pre_staging_and_legacy_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            preview = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: final")
            (repo / "src" / "final.txt").write_text("changed after qualification\n", encoding="utf-8")
            with self.assertRaisesRegex(finalization.FinalizationError, "baseline changed|stale"):
                finalization.commit(repo, "Operator One", approved["plan_hash"], "test: final", preview["preview_sha256"], "COMMIT")

        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            git(repo, "add", "src/final.txt")
            with self.assertRaisesRegex(finalization.FinalizationError, "baseline changed|pre-staged"):
                finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: final")

        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            state = planning._record(repo)
            final = dict(state["final_qualification"])
            final.pop("qualified_head", None)
            final.pop("qualified_branch", None)
            final.pop("qualified_path_fingerprints", None)
            body = dict(final)
            body.pop("provenance_sha256", None)
            final["provenance_sha256"] = qualification._digest(body)
            planning._write(repo, {**state, "final_qualification": final})
            with self.assertRaisesRegex(finalization.FinalizationError, "requalification"):
                finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: final")

    def test_manual_commit_reconciliation_accepts_exact_qualified_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            git(repo, "add", "src/final.txt")
            git(repo, "commit", "-q", "-m", "manual qualified commit")
            sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            preview = finalization.build_reconcile_commit_preview(repo, "Operator One", approved["plan_hash"], sha, "operator performed reviewed commit")
            result = finalization.reconcile_commit(repo, "Operator One", approved["plan_hash"], sha, "operator performed reviewed commit", preview["preview_sha256"], "RECONCILE_COMMIT")
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("COMMIT_RECONCILED", result["result"])
            self.assertEqual("COMMITTED", state["status"])
            self.assertTrue(state["commit_reconciled"])
            self.assertEqual(sha, state["commit_sha"])

    def test_manual_commit_reconciliation_rejects_extra_or_wrong_qualified_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            (repo / "surprise.txt").write_text("unexpected\n", encoding="utf-8")
            git(repo, "add", "src/final.txt", "surprise.txt")
            git(repo, "commit", "-q", "-m", "bad manual commit")
            sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            with self.assertRaisesRegex(finalization.FinalizationError, "scope differs"):
                finalization.build_reconcile_commit_preview(repo, "Operator One", approved["plan_hash"], sha, "review")

        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td))
            (repo / "src" / "final.txt").write_text("not qualified\n", encoding="utf-8")
            git(repo, "add", "src/final.txt")
            git(repo, "commit", "-q", "-m", "wrong content")
            sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            with self.assertRaisesRegex(finalization.FinalizationError, "contents/modes differ"):
                finalization.build_reconcile_commit_preview(repo, "Operator One", approved["plan_hash"], sha, "review")

    def test_native_push_is_previewed_and_updates_only_exact_upstream_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, remote = ready_repo(Path(td), remote=True)
            cp = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: pushable")
            finalization.commit(repo, "Operator One", approved["plan_hash"], "test: pushable", cp["preview_sha256"], "COMMIT")
            pp = finalization.build_push_preview(repo, "Operator One", approved["plan_hash"])
            self.assertNotEqual(pp["commit_sha"], pp["remote_head"])
            result = finalization.push(repo, "Operator One", approved["plan_hash"], pp["preview_sha256"], "PUSH")
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("PUSHED", result["result"])
            self.assertEqual("PUSHED", state["status"])
            branch = git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip()
            remote_sha = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/{branch}"], text=True, capture_output=True, check=True).stdout.strip()
            self.assertEqual(state["commit_sha"], remote_sha)
            self.assertFalse(state["push_reconciled"])

    def test_external_push_reconciliation_refuses_mismatch_then_accepts_exact_remote(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td), remote=True)
            git(repo, "add", "src/final.txt")
            git(repo, "commit", "-q", "-m", "manual qualified commit")
            sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            cp = finalization.build_reconcile_commit_preview(repo, "Operator One", approved["plan_hash"], sha, "manual review")
            finalization.reconcile_commit(repo, "Operator One", approved["plan_hash"], sha, "manual review", cp["preview_sha256"], "RECONCILE_COMMIT")
            with self.assertRaisesRegex(finalization.FinalizationError, "not the exact current upstream"):
                finalization.build_reconcile_push_preview(repo, "Operator One", approved["plan_hash"])
            git(repo, "push", "-q")
            pp = finalization.build_reconcile_push_preview(repo, "Operator One", approved["plan_hash"])
            result = finalization.reconcile_push(repo, "Operator One", approved["plan_hash"], pp["preview_sha256"], "RECONCILE_PUSH")
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("PUSH_RECONCILED", result["result"])
            self.assertEqual("PUSHED", state["status"])
            self.assertTrue(state["push_reconciled"])

    def test_push_preview_fails_closed_if_local_head_or_remote_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, remote = ready_repo(Path(td), remote=True)
            cp = finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "test: push")
            finalization.commit(repo, "Operator One", approved["plan_hash"], "test: push", cp["preview_sha256"], "COMMIT")
            pp = finalization.build_push_preview(repo, "Operator One", approved["plan_hash"])
            # Advance the remote independently; the old preview must not authorize a push.
            other = Path(td) / "other"
            subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
            git(other, "config", "user.name", "Other")
            git(other, "config", "user.email", "other@example.invalid")
            (other / "remote.txt").write_text("advance\n", encoding="utf-8")
            git(other, "add", "remote.txt")
            git(other, "commit", "-q", "-m", "remote advance")
            git(other, "push", "-q")
            with self.assertRaisesRegex(finalization.FinalizationError, "stale|changed"):
                finalization.push(repo, "Operator One", approved["plan_hash"], pp["preview_sha256"], "PUSH")

    def test_read_only_completion_has_zero_git_finalization_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, approved, _result, _remote = ready_repo(Path(td), read_only=True)
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("READ_ONLY_COMPLETE", state["status"])
            with self.assertRaisesRegex(finalization.FinalizationError, "READ_ONLY_COMPLETE"):
                finalization.build_commit_preview(repo, "Operator One", approved["plan_hash"], "not allowed")
