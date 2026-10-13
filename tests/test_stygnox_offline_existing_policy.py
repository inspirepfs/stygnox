"""Operator-approved, bootstrap-only adoption without launching a provider."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, execution_policy, provider_codex, transactions


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=True)
    return p.stdout.strip()


def fixture(root: Path) -> tuple[Path, adoption.CommandIdentity, dict]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Tester")
    git(repo, "config", "user.email", "test@example.invalid")
    selected = execution_policy.normalize_policy(
        provider="codex", model="gpt-5.6-terra", effort="high", reviewer="pfsykes", max_loops=16
    )
    review = execution_policy.policy_review(selected, "pfsykes")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    (repo / ".gitignore").write_text("/.stygnox/\n", encoding="utf-8")
    (repo / adoption.CONFIG_NAME).write_text(adoption.render_config(selected), encoding="utf-8")
    (repo / adoption.POLICY_NAME).write_text(adoption.render_policy("pfsykes", review), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "clean reviewed policy")
    binary = root / "installed" / "bin" / "stygnox"
    pkg = root / "installed" / "lib" / "stygnox" / "adoption.py"
    binary.parent.mkdir(parents=True)
    pkg.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    pkg.write_text("# installed\n", encoding="utf-8")
    return repo, adoption.CommandIdentity(binary, pkg, "0.1.0"), selected


def policy_kwargs() -> dict:
    return dict(provider="codex", model="gpt-5.6-terra", effort="high", reviewer="pfsykes", max_loops=16)


def test_offline_bootstrap_is_exact_unchanged_clean_and_never_calls_codex():
    with TemporaryDirectory() as td:
        repo, identity, _ = fixture(Path(td))
        before = git(repo, "status", "--porcelain")
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity), mock.patch.object(
            provider_codex, "model_catalog", side_effect=AssertionError("Codex catalogue must not be called")
        ):
            preview = adoption.build_preview(repo, "pfsykes", offline_existing_policy=True, **policy_kwargs())
            assert preview["admissible"] is True
            assert preview["conflicts"] == []
            assert preview["execution_policy"]["provider_catalog_deferred"] is True
            assert preview["execution_policy"]["review"]["provider_catalog"] is None
            assert {x["path"]: x["action"] for x in preview["tracked_review"]} == {
                ".gitignore": "unchanged", "stygnox.toml": "unchanged", "stygnox.policy.md": "unchanged"
            }
            assert not (repo / ".stygnox").exists()
            assert git(repo, "status", "--porcelain") == before
            outcome = adoption.handoff_adoption(
                repo, "pfsykes", preview["preview_sha256"], "HANDOFF",
                offline_existing_policy=True, **policy_kwargs()
            )
        assert outcome["controller_execution"] is False
        assert (repo / ".stygnox" / "adoption.json").is_file()
        status = execution_policy.show_policy(repo)
        assert status["provider_catalog_bound"] is False
        assert status["approved"] is True  # reviewer, but catalogue not bound
        assert controller._policy_status(repo)["provider_catalog_bound"] is False
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
            tx = transactions.begin_transaction(repo, "pfsykes", "BEGIN")
            assert tx["state"] == "ACTIVE"
            active = controller.activate_controller(repo, "pfsykes", "ACTIVATE")
            assert active["provider_execution_ready"] is False
            with pytest.raises(controller.ControllerError, match="model catalogue binding is absent"):
                controller.build_run_preview(repo, "pfsykes", "test", "read-only")


def test_online_path_still_hits_original_02n_guard():
    with TemporaryDirectory() as td:
        repo, identity, _ = fixture(Path(td))
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
            with pytest.raises(adoption.AdoptionError, match="02N recovery provider dispatch blocked"):
                adoption.build_preview(repo, "pfsykes", **policy_kwargs())
        assert not (repo / ".stygnox").exists()


@pytest.mark.parametrize("tamper", ["not_tracked", "alter_config", "alter_policy", "dirty", "symlink", "runtime"])
def test_offline_override_refuses_nonidentical_or_unclean_input(tamper):
    with TemporaryDirectory() as td:
        repo, identity, _ = fixture(Path(td))
        if tamper == "not_tracked":
            git(repo, "rm", "--cached", "stygnox.toml")
        elif tamper == "alter_config":
            (repo / "stygnox.toml").write_text("modified\n", encoding="utf-8")
            git(repo, "add", "stygnox.toml")
            git(repo, "commit", "-qm", "tracked config changed")
        elif tamper == "alter_policy":
            (repo / "stygnox.policy.md").write_text("modified\n", encoding="utf-8")
            git(repo, "add", "stygnox.policy.md")
            git(repo, "commit", "-qm", "tracked policy changed")
        elif tamper == "dirty":
            (repo / "README.md").write_text("modified\n", encoding="utf-8")
        elif tamper == "symlink":
            (repo / "stygnox.toml").unlink()
            (repo / "stygnox.toml").symlink_to("README.md")
        elif tamper == "runtime":
            (repo / ".stygnox").mkdir()
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity), mock.patch.object(
            provider_codex, "model_catalog", side_effect=AssertionError("never call provider")
        ):
            with pytest.raises(adoption.AdoptionError):
                adoption.build_preview(repo, "pfsykes", offline_existing_policy=True, **policy_kwargs())


def test_offline_preview_hash_cannot_be_used_for_online_handoff():
    with TemporaryDirectory() as td:
        repo, identity, _ = fixture(Path(td))
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
            preview = adoption.build_preview(repo, "pfsykes", offline_existing_policy=True, **policy_kwargs())
            with pytest.raises(adoption.AdoptionError, match="02N recovery provider dispatch blocked"):
                adoption.handoff_adoption(repo, "pfsykes", preview["preview_sha256"], "HANDOFF", **policy_kwargs())
        assert not (repo / ".stygnox").exists()


def test_offline_flag_refuses_neutral_policy():
    with TemporaryDirectory() as td:
        repo, identity, _ = fixture(Path(td))
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
            with pytest.raises(adoption.AdoptionError, match="requires an explicitly reviewed Codex policy"):
                adoption.build_preview(repo, "pfsykes", offline_existing_policy=True)
