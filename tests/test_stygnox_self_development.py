"""Scoped Stygnox self-development authority regressions."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import cli, controller, human_control, planning, provider_codex, scheduler, self_development
from tests.test_stygnox_scheduler import active_reviewed, approve, git, implementation_result, init_repo
from tests.provider_catalog_fixture import test_catalog


def init_stygnox_repo(path: Path) -> None:
    init_repo(path)
    (path / "src" / "stygnox").mkdir(parents=True)
    (path / "src" / "stygnox" / "product.py").write_text("VERSION = 1\n", encoding="utf-8")
    (path / "src" / "stygnox" / "controller.py").write_text("VALUE = 1\n", encoding="utf-8")
    (path / "tests").mkdir(exist_ok=True)
    (path / "tests" / "test_stygnox_existing.py").write_text("VALUE = 1\n", encoding="utf-8")
    (path / "pyproject.toml").write_text("[project]\nname='stygnox-test'\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "stygnox source baseline")


def open_self_gate(repo: Path, approved: dict, *, paths: tuple[str, ...] = ("src/stygnox/product.py",)) -> dict:
    objective = approved["plan"]["steps"][0]["objective"]
    preview = controller.build_run_preview(repo, "Operator One", objective, "write")

    def mutate(**_kwargs: object) -> dict:
        for item in paths:
            target = repo / item
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"changed {item}\n", encoding="utf-8")
        return implementation_result("attempted self development")

    with mock.patch.object(provider_codex, "execute", side_effect=mutate):
        return controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")


def authorize_gate(repo: Path, approved: dict, gate: dict, paths: list[str]) -> dict:
    preview = self_development.build_authorize_preview(
        repo,
        "Operator One",
        approved["plan_hash"],
        gate["gate_id"],
        paths,
        "Permit only this exact supervised Stygnox repair surface.",
    )
    return self_development.authorize(
        repo,
        "Operator One",
        approved["plan_hash"],
        gate["gate_id"],
        paths,
        "Permit only this exact supervised Stygnox repair surface.",
        preview["preview_sha256"],
        "AUTHORIZE",
    )


class StygnoxSelfDevelopmentTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)

    def test_unauthorized_self_development_is_restored_and_latches_exact_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            original = (repo / "src/stygnox/product.py").read_text(encoding="utf-8")
            result = open_self_gate(repo, approved)
            gate = result["human_gate"]
            self.assertEqual("human-gate-required", result["next_action"])
            self.assertEqual("self-development-authority", gate["kind"])
            self.assertFalse(gate["human_resolvable"])
            self.assertEqual(["src/stygnox/product.py"], [row["path"] for row in gate["self_development_candidates"]])
            self.assertEqual(original, (repo / "src/stygnox/product.py").read_text(encoding="utf-8"))
            self.assertEqual("RESTORED_UNAUTHORIZED", result["self_development"]["status"])
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("BLOCKED_HUMAN", state["status"])
            self.assertIsNone(state["self_development_grant"])

    def test_exact_authorization_allows_one_retry_and_then_expires(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved)
            gate = blocked["human_gate"]
            receipt = authorize_gate(repo, approved, gate, ["src/stygnox/product.py"])
            self.assertEqual("SELF_DEVELOPMENT_AUTHORIZED", receipt["result"])
            state = planning.plan_status(repo)["plan"]
            self.assertIsNotNone(state["self_development_grant"])
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")
            self.assertIn("src/stygnox/product.py", controller._prompt(preview))

            def mutate(**_kwargs: object) -> dict:
                (repo / "src/stygnox/product.py").write_text("VERSION = 2\n", encoding="utf-8")
                return implementation_result("authorized self development complete")

            with mock.patch.object(provider_codex, "execute", side_effect=mutate):
                result = controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")
            self.assertEqual("AUTHORIZED", result["self_development"]["status"])
            self.assertIsNone(result["human_gate"])
            self.assertIsNotNone(result["self_development_expiration"])
            self.assertEqual("VERSION = 2\n", (repo / "src/stygnox/product.py").read_text(encoding="utf-8"))
            state = planning.plan_status(repo)["plan"]
            self.assertIsNone(state["self_development_grant"])
            self.assertEqual(1, len(state["self_development_grant_history"]))
            self.assertEqual(1, len(state["self_development_expirations"]))

    def test_authorization_requires_exact_candidates_and_generic_gate_actions_cannot_substitute(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved, paths=("src/stygnox/product.py", "src/stygnox/controller.py"))
            gate = blocked["human_gate"]
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "exactly match"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], ["src/stygnox/product.py"], "subset"
                )
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "runtime/protected"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], [".stygnox/plan.json"], "runtime"
                )
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "exact Stygnox tooling"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], ["README.md"], "non tooling"
                )
            with self.assertRaisesRegex(human_control.HumanControlError, "self-development authorize"):
                human_control.build_resume_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "retry")
            with self.assertRaisesRegex(human_control.HumanControlError, "self-development authorize"):
                human_control.build_steer_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "retry")

    def test_grant_does_not_expand_to_extra_tooling_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            first = open_self_gate(repo, approved)
            authorize_gate(repo, approved, first["human_gate"], ["src/stygnox/product.py"])
            product_before = (repo / "src/stygnox/product.py").read_text(encoding="utf-8")
            controller_before = (repo / "src/stygnox/controller.py").read_text(encoding="utf-8")
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")

            def mutate(**_kwargs: object) -> dict:
                (repo / "src/stygnox/product.py").write_text("VERSION = 3\n", encoding="utf-8")
                (repo / "src/stygnox/controller.py").write_text("VALUE = 3\n", encoding="utf-8")
                return implementation_result("expanded tooling attempt")

            with mock.patch.object(provider_codex, "execute", side_effect=mutate):
                result = controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")
            self.assertEqual("RESTORED_UNAUTHORIZED", result["self_development"]["status"])
            self.assertEqual(product_before, (repo / "src/stygnox/product.py").read_text(encoding="utf-8"))
            self.assertEqual(controller_before, (repo / "src/stygnox/controller.py").read_text(encoding="utf-8"))
            self.assertEqual(
                ["src/stygnox/controller.py", "src/stygnox/product.py"],
                [row["path"] for row in result["human_gate"]["self_development_candidates"]],
            )
            self.assertIsNone(planning.plan_status(repo)["plan"]["self_development_grant"])

    def test_test_policy_still_limits_self_development_test_authority(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="none")
            blocked = open_self_gate(repo, approved, paths=("tests/test_stygnox_existing.py",))
            gate = blocked["human_gate"]
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "test_change_policy=none"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], ["tests/test_stygnox_existing.py"], "cannot override policy"
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="add-only")
            blocked = open_self_gate(repo, approved, paths=("tests/test_stygnox_existing.py",))
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "add-only"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], blocked["human_gate"]["gate_id"], ["tests/test_stygnox_existing.py"], "cannot modify existing"
                )

    def test_secret_named_tooling_candidate_is_restored_but_never_grantable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved, paths=("src/stygnox/secrets.py",))
            gate = blocked["human_gate"]
            self.assertFalse((repo / "src/stygnox/secrets.py").exists())
            self.assertFalse(gate["self_development_candidates"][0]["grantable"])
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "secret/credential"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], ["src/stygnox/secrets.py"], "never authorize secrets"
                )

    def test_direct_non_plan_self_development_is_restored_and_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            original = (repo / "src/stygnox/product.py").read_text(encoding="utf-8")
            preview = controller.build_run_preview(repo, "Operator One", "Direct task", "write")

            def mutate(**_kwargs: object) -> dict:
                (repo / "src/stygnox/product.py").write_text("VERSION = 99\n", encoding="utf-8")
                return implementation_result("direct self change")

            with mock.patch.object(provider_codex, "execute", side_effect=mutate):
                with self.assertRaisesRegex(controller.ControllerError, "without an approved plan/gate authority"):
                    controller.run_controller(repo, "Operator One", "Direct task", "write", preview["preview_sha256"], "RUN")
            self.assertEqual(original, (repo / "src/stygnox/product.py").read_text(encoding="utf-8"))

    def test_stale_gate_candidate_or_cross_gate_grant_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved)
            gate = blocked["human_gate"]
            (repo / "README.md").write_text("external drift\n", encoding="utf-8")
            with self.assertRaisesRegex(self_development.SelfDevelopmentError, "repository changed"):
                self_development.build_authorize_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], ["src/stygnox/product.py"], "stale"
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved)
            authorize_gate(repo, approved, blocked["human_gate"], ["src/stygnox/product.py"])
            state = planning._record(repo)
            assert state is not None
            resume = dict(state["step_resume"])
            resume["gate_id"] = "HG-9999-01"
            tampered = dict(state)
            tampered["step_resume"] = resume
            planning._write(repo, tampered)
            with self.assertRaisesRegex(controller.ControllerError, "stale for the current gate"):
                controller.build_run_preview(repo, "Operator One", approved["plan"]["steps"][0]["objective"], "write")

    def test_interrupted_recovery_refuses_ungranted_and_accepts_exact_granted_tooling(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external", max_loops=2)
            approve(repo, test_policy="modify")
            schedule_preview = scheduler.build_schedule_preview(repo, "Operator One")

            def interrupted(**_kwargs: object) -> dict:
                (repo / "src/stygnox/product.py").write_text("VERSION = interrupted\n", encoding="utf-8")
                raise provider_codex.ProviderError("simulated interruption")

            with mock.patch.object(provider_codex, "execute", side_effect=interrupted):
                with self.assertRaises(scheduler.SchedulerError):
                    scheduler.run_schedule(repo, "Operator One", schedule_preview["preview_sha256"], "SCHEDULE")
            with self.assertRaisesRegex(scheduler.SchedulerError, "ungranted self-development"):
                scheduler.build_recovery_preview(repo, "Operator One", ["src/stygnox/product.py"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_stygnox_repo(repo)
            active_reviewed(repo, root / "external", max_loops=2)
            approved = approve(repo, test_policy="modify")
            blocked = open_self_gate(repo, approved)
            authorize_gate(repo, approved, blocked["human_gate"], ["src/stygnox/product.py"])
            schedule_preview = scheduler.build_schedule_preview(repo, "Operator One")

            def interrupted_granted(**_kwargs: object) -> dict:
                (repo / "src/stygnox/product.py").write_text("VERSION = recovered\n", encoding="utf-8")
                raise provider_codex.ProviderError("simulated interruption")

            with mock.patch.object(provider_codex, "execute", side_effect=interrupted_granted):
                with self.assertRaises(scheduler.SchedulerError):
                    scheduler.run_schedule(repo, "Operator One", schedule_preview["preview_sha256"], "SCHEDULE")
            preview = scheduler.build_recovery_preview(repo, "Operator One", ["src/stygnox/product.py"])
            recovered = scheduler.recover_interrupted(
                repo, "Operator One", ["src/stygnox/product.py"], preview["preview_sha256"], "RECOVER"
            )
            self.assertEqual("RECOVERED_PARTIAL_TURN", recovered["status"])
            self.assertEqual("VERSION = recovered\n", (repo / "src/stygnox/product.py").read_text(encoding="utf-8"))
            self.assertIsNone(planning.plan_status(repo)["plan"]["self_development_grant"])

    def test_cli_routes_self_development_surface(self) -> None:
        with mock.patch.object(self_development, "cli_main", return_value=0) as route:
            self.assertEqual(0, cli.main(["self-development", "status"]))
            route.assert_called_once_with(["status"])
        with mock.patch.object(self_development, "cli_main", return_value=0) as route:
            self.assertEqual(0, cli.main(["self-hosting", "status"]))
            route.assert_called_once_with(["status"])


if __name__ == "__main__":
    import unittest
    unittest.main()
