"""02N scoped planning release: real transaction, policy and dispatch-boundary tests."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

from stygnox import adoption, controller, execution_policy, provider_codex, provider_release, transactions
from test_stygnox_offline_existing_policy import fixture, policy_kwargs, git


def boot(td: Path):
    repo, identity, _ = fixture(td)
    ctx = mock.patch.object(adoption, "resolve_installed_command", return_value=identity)
    ctx.start()
    prev = adoption.build_preview(repo, "pfsykes", offline_existing_policy=True, **policy_kwargs())
    adoption.handoff_adoption(repo, "pfsykes", prev["preview_sha256"], "HANDOFF", offline_existing_policy=True, **policy_kwargs())
    tx = transactions.begin_transaction(repo, "pfsykes", "BEGIN")
    return repo, identity, tx, ctx


def catalog():
    body = {
        "schema": provider_codex.MODEL_CATALOG_SCHEMA,
        "provider": "codex",
        "models": [{"id": "gpt-5.6-terra", "reasoning_efforts": ["high"]}],
    }
    body["catalog_sha256"] = provider_codex._digest(body)
    return body


def release_fixture(td: Path):
    repo, identity, tx, ctx = boot(td)
    prev = provider_release.preview(repo, "pfsykes")
    with mock.patch.object(provider_codex, "model_catalog", return_value=catalog()):
        result = provider_release.release(repo, "pfsykes", prev["preview_sha256"], "RELEASE_PLANNING")
    assert result["transaction_id"] == tx["transaction_id"]
    assert result["scope"] == "PLANNING_ONLY"
    return repo, identity, tx, ctx


def test_preview_requires_confirmed_transaction_and_no_provider_call():
    with TemporaryDirectory() as td:
        repo, identity, _ = fixture(Path(td))
        with mock.patch.object(adoption, "resolve_installed_command", return_value=identity):
            with pytest.raises(transactions.TransactionError):
                provider_release.preview(repo, "pfsykes")
        assert not (repo / adoption.RUNTIME_NAME).exists()


def test_release_is_exact_operator_preview_and_model_catalogue_bound():
    with TemporaryDirectory() as td:
        repo, identity, tx, ctx = boot(Path(td))
        try:
            p = provider_release.preview(repo, "pfsykes")
            assert p["transaction_id"] == tx["transaction_id"]
            assert p["scope"] == "catalogue-and-confirmed-plan-proposal-only"
            assert not (repo / ".stygnox" / provider_release.RECORD).exists()
            with pytest.raises(provider_release.ProviderReleaseError, match="confirmation"):
                provider_release.release(repo, "pfsykes", p["preview_sha256"], "UNSAFE")
            with pytest.raises(provider_release.ProviderReleaseError, match="stale"):
                provider_release.release(repo, "pfsykes", "0"*64, "RELEASE_PLANNING")
            with pytest.raises(provider_release.ProviderReleaseError, match="operator"):
                provider_release.preview(repo, "not-pfsykes")
            with pytest.raises(provider_release.ProviderReleaseError, match="confirmation"):
                provider_release.catalogue_probe(repo, "pfsykes", p["preview_sha256"], "NO")
            with mock.patch.object(provider_codex, "model_catalog", return_value=catalog()):
                inspected = provider_release.catalogue_probe(repo, "pfsykes", p["preview_sha256"], "PROBE")
                assert inspected["result"] == "CATALOGUE_INSPECTED_NO_RELEASE"
                assert not provider_release.planning_ready(repo)
                r = provider_release.release(repo, "pfsykes", p["preview_sha256"], "RELEASE_PLANNING")
            assert r["result"] == "PLANNING_RELEASE_RECORDED"
            assert provider_release.planning_ready(repo)
            assert execution_policy.show_policy(repo)["provider_catalog_bound"] is True
            assert controller.activate_controller(repo, "pfsykes", "ACTIVATE")["provider_execution_ready"] is False
            with pytest.raises(controller.ControllerError, match="planning-only release"):
                controller.build_run_preview(repo, "pfsykes", "Do unapproved work", "write")
            with pytest.raises(provider_release.ProviderReleaseError, match="already exists"):
                provider_release.preview(repo, "pfsykes")
            assert git(repo, "status", "--porcelain") == ""
        finally:
            ctx.stop()


def test_catalogue_unavailable_or_unadvertised_fails_closed_before_release():
    with TemporaryDirectory() as td:
        repo, identity, tx, ctx = boot(Path(td))
        try:
            p = provider_release.preview(repo, "pfsykes")
            with mock.patch.object(provider_codex, "model_catalog", side_effect=provider_codex.ProviderError("catalogue offline")):
                with pytest.raises(provider_release.ProviderReleaseError, match="offline"):
                    provider_release.release(repo, "pfsykes", p["preview_sha256"], "RELEASE_PLANNING")
            wrong = catalog()
            wrong["models"] = []
            wrong["catalog_sha256"] = provider_codex._digest({k:v for k,v in wrong.items() if k != "catalog_sha256"})
            with mock.patch.object(provider_codex, "model_catalog", return_value=wrong):
                with pytest.raises(provider_release.ProviderReleaseError, match="not advertised"):
                    provider_release.release(repo, "pfsykes", p["preview_sha256"], "RELEASE_PLANNING")
            assert not (repo / ".stygnox" / provider_release.RECORD).exists()
        finally:
            ctx.stop()


@pytest.mark.parametrize("tamper", ["tx", "package", "baseline", "release-record", "symlink"])
def test_change_after_release_revokes_all_dispatch(tamper):
    with TemporaryDirectory() as td:
        repo, identity, _, ctx = release_fixture(Path(td))
        try:
            assert provider_release.dispatch_allowed(repo, "catalogue")
            if tamper == "tx":
                path = repo / ".stygnox" / "transaction.json"
                data = __import__("json").loads(path.read_text())
                data["transaction_id"] = "TX-WRONG"
                path.write_text(__import__("json").dumps(data))
            elif tamper == "package":
                identity.package_file.write_text("tampered")
            elif tamper == "baseline":
                (repo / "README.md").write_text("changed")
            elif tamper == "release-record":
                path = repo / ".stygnox" / provider_release.RECORD
                data = __import__("json").loads(path.read_text())
                data["scope"] = "WRITE_EVERYWHERE"
                path.write_text(__import__("json").dumps(data))
            else:
                path = repo / ".stygnox" / provider_release.RECORD
                other = repo / ".stygnox" / "fake.json"
                path.rename(other)
                path.symlink_to(other)
            assert not provider_release.planning_ready(repo)
            assert not provider_release.dispatch_allowed(repo, "catalogue")
            assert not provider_release.dispatch_allowed(repo, "read-only-turn")
        finally:
            ctx.stop()


def test_read_only_plan_turn_requires_proposal_context_write_always_denied():
    with TemporaryDirectory() as td:
        repo, _, _, ctx = release_fixture(Path(td))
        try:
            assert provider_release.dispatch_allowed(repo, "catalogue")
            assert provider_release.dispatch_allowed(repo, "quota")
            assert not provider_release.dispatch_allowed(repo, "read-only-turn")
            assert not provider_release.dispatch_allowed(repo, "write-turn")
            with provider_release.approved_proposal_turn(repo, "a"*64):
                assert provider_release.dispatch_allowed(repo, "read-only-turn")
                assert not provider_release.dispatch_allowed(repo, "write-turn")
            assert not provider_release.dispatch_allowed(repo, "read-only-turn")
            assert not provider_release.dispatch_allowed(Path(td), "catalogue")
        finally:
            ctx.stop()


def test_original_02n_block_remains_when_no_release_even_with_environment_override(monkeypatch):
    with TemporaryDirectory() as td:
        root = Path(td)
        monkeypatch.setenv("STYGNOX_PROVIDER_RELEASE", "RELEASED")
        with pytest.raises(provider_codex.ProviderError, match="02N recovery provider dispatch blocked"):
            provider_codex.model_catalog(root)
        with pytest.raises(provider_codex.ProviderError, match="02N recovery provider dispatch blocked"):
            provider_codex._run(["codex", "exec", "--sandbox", "workspace-write"], cwd=root)
