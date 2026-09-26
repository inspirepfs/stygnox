"""Round 13B-1 provider model-catalogue and reasoning-effort authority tests."""
from __future__ import annotations

import io
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

from stygnox import adoption, execution_policy, operator, provider_codex  # noqa: E402
from tests.provider_catalog_fixture import test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "13B1 Test")
    git(path, "config", "user.email", "13b1@example.invalid")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-qm", "base")


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev13b1")


def adopt(repo: Path, external: Path, catalog: dict | None = None) -> dict:
    resolved = identity(external)
    kwargs = {"provider": "codex", "model": "gpt-test", "effort": "high", "reviewer": "Reviewer One"}
    with (
        mock.patch.object(adoption, "resolve_installed_command", return_value=resolved),
        mock.patch.object(provider_codex, "model_catalog", return_value=catalog or test_catalog()),
    ):
        preview = adoption.build_preview(repo, "Operator One", **kwargs)
        return adoption.handoff_adoption(repo, "Operator One", preview["preview_sha256"], "HANDOFF", **kwargs)


class StygnoxProviderCatalogTests(TestCase):
    def test_model_list_protocol_is_metadata_only_and_normalised(self) -> None:
        raw = {
            "data": [
                {"model": "gpt-5.6-sol", "displayName": "Sol", "isDefault": True,
                 "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}],
                 "defaultReasoningEffort": "high"},
                {"model": "gpt-5.6-luna", "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]},
            ]
        }
        fake = mock.Mock()
        fake.stdin = io.StringIO()
        fake.terminate.return_value = None
        fake.wait.return_value = 0
        with (
            mock.patch.object(provider_codex.shutil, "which", return_value="/fake/codex"),
            mock.patch.object(provider_codex.subprocess, "Popen", return_value=fake) as popen,
            mock.patch.object(provider_codex, "_app_server_read_response", side_effect=[{}, raw]),
        ):
            result = provider_codex.model_catalog(Path("/tmp"))
        self.assertEqual(["gpt-5.6-luna", "gpt-5.6-sol"], [row["id"] for row in result["models"]])
        self.assertEqual(["low", "high"], next(row for row in result["models"] if row["id"] == "gpt-5.6-sol")["reasoning_efforts"])
        messages = [json.loads(line) for line in fake.stdin.getvalue().splitlines()]
        self.assertEqual("initialize", messages[0]["method"])
        self.assertEqual("initialized", messages[1]["method"])
        self.assertEqual("model/list", messages[2]["method"])
        self.assertEqual({"limit": 100, "cursor": None, "includeHidden": False}, messages[2]["params"])
        self.assertNotIn("exec", str(popen.call_args))

    def test_neutral_adoption_does_not_query_provider_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); resolved = identity(root / "external")
            with (
                mock.patch.object(adoption, "resolve_installed_command", return_value=resolved),
                mock.patch.object(provider_codex, "model_catalog", side_effect=AssertionError("catalogue must stay neutral")) as catalog,
            ):
                preview = adoption.build_preview(repo, "Operator One")
            self.assertIsNone(preview["defaults"]["provider"])
            catalog.assert_not_called()

    def test_adoption_binds_catalogue_evidence_and_rejects_unknown_model_or_effort(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); resolved = identity(root / "external")
            catalog = test_catalog()
            with (
                mock.patch.object(adoption, "resolve_installed_command", return_value=resolved),
                mock.patch.object(provider_codex, "model_catalog", return_value=catalog),
            ):
                preview = adoption.build_preview(repo, "Operator One", provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One")
                evidence = preview["execution_policy"]["review"]["provider_catalog"]
                self.assertEqual(catalog["catalog_sha256"], evidence["catalog_sha256"])
                self.assertEqual("gpt-test", evidence["selected_model"])
                with self.assertRaisesRegex(adoption.AdoptionError, "not advertised"):
                    adoption.build_preview(repo, "Operator One", provider="codex", model="missing", effort="high", reviewer="Reviewer One")
                with self.assertRaisesRegex(adoption.AdoptionError, "not supported"):
                    adoption.build_preview(repo, "Operator One", provider="codex", model="gpt-other", effort="high", reviewer="Reviewer One")

    def test_policy_model_change_clears_only_inherited_incompatible_effort(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); adopt(repo, root / "external")
            catalog = test_catalog(second_efforts=("medium",))
            with mock.patch.object(provider_codex, "model_catalog", return_value=catalog):
                preview = execution_policy.build_policy_preview(repo, "Operator One", reviewer="Reviewer One", model="gpt-other")
                self.assertEqual("gpt-other", preview["proposed"]["model"])
                self.assertIsNone(preview["proposed"]["effort"])
                self.assertIsNone(preview["review"]["provider_catalog"]["selected_effort"])
                with self.assertRaisesRegex(execution_policy.ExecutionPolicyError, "not supported"):
                    execution_policy.build_policy_preview(repo, "Operator One", reviewer="Reviewer One", model="gpt-other", effort="high")

    def test_catalogue_unavailable_blocks_non_neutral_policy_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); resolved = identity(root / "external")
            with (
                mock.patch.object(adoption, "resolve_installed_command", return_value=resolved),
                mock.patch.object(provider_codex, "model_catalog", side_effect=provider_codex.ProviderError("metadata unavailable")),
            ):
                with self.assertRaisesRegex(adoption.AdoptionError, "metadata unavailable"):
                    adoption.build_preview(repo, "Operator One", provider="codex", model="gpt-test", effort="high", reviewer="Reviewer One")

    def test_execution_revalidates_catalog_before_sandbox_or_model_turn(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog(second_efforts=("medium",))),
                mock.patch.object(provider_codex, "_preflight") as preflight,
                mock.patch.object(provider_codex, "_run") as run,
            ):
                with self.assertRaisesRegex(provider_codex.ProviderError, "not supported"):
                    provider_codex.execute_structured(
                        cwd=root, prompt="do not execute", model="gpt-other", effort="high",
                        repository_authority="read-only", result_schema={"type": "object"},
                    )
            preflight.assert_not_called(); run.assert_not_called()

    def test_catalog_action_is_passive_and_available_through_shared_operator_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo)
            with mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog()) as catalog:
                result = operator.dispatch_action(repo, "policy.catalog", {})
            self.assertFalse(result["result"]["model_turn_executed"])
            self.assertEqual("stygnox_codex_model_catalog_v1", result["result"]["catalog"]["schema"])
            catalog.assert_called_once()


    def test_catalogue_change_between_preview_and_apply_fails_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); adopt(repo, root / "external")
            first = test_catalog(second_efforts=("medium",))
            second = test_catalog(second_efforts=("medium", "high"))
            with mock.patch.object(provider_codex, "model_catalog", return_value=first):
                preview = execution_policy.build_policy_preview(
                    repo, "Operator One", reviewer="Reviewer One", model="gpt-other", effort="medium"
                )
            with mock.patch.object(provider_codex, "model_catalog", return_value=second):
                with self.assertRaisesRegex(execution_policy.ExecutionPolicyError, "preview is stale"):
                    execution_policy.apply_policy(
                        repo, "Operator One", preview["preview_sha256"], "SET",
                        reviewer="Reviewer One", model="gpt-other", effort="medium", reset=False,
                    )

    def test_legacy_review_remains_approved_but_is_not_catalogue_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo"; init_repo(repo); adopt(repo, root / "external")
            record_path = repo / adoption.RUNTIME_NAME / execution_policy.POLICY_RECORD
            # Adoption review is normally the fallback when no explicit policy record exists.
            adoption_path = repo / adoption.RUNTIME_NAME / "adoption.json"
            state = json.loads(adoption_path.read_text(encoding="utf-8"))
            state["execution_policy_review"].pop("provider_catalog", None)
            adoption_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.assertFalse(record_path.exists())
            status = execution_policy.show_policy(repo)
            self.assertTrue(status["approved"])
            self.assertFalse(status["provider_catalog_bound"])
            self.assertTrue(status["provider_execution_revalidates_catalog"])

    def test_catalogue_digest_changes_when_provider_capability_changes(self) -> None:
        first = test_catalog(second_efforts=("medium",))
        second = test_catalog(second_efforts=("medium", "high"))
        self.assertNotEqual(first["catalog_sha256"], second["catalog_sha256"])


if __name__ == "__main__":
    import unittest
    unittest.main()
