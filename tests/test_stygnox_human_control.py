"""Installed human-gate, bounded steering, resume, and resolve regression tests."""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, cli, controller, human_control, planning, provider_codex, qualification, transactions  # noqa: E402
from tests.provider_catalog_fixture import safe_rate_limits, test_catalog  # noqa: E402


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path, *, existing_test: bool = False, qualification_gate: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Human Gate Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    if existing_test:
        (path / "tests").mkdir()
        (path / "tests" / "test_existing.py").write_text("value = 1\n", encoding="utf-8")
    if qualification_gate:
        (path / "stygnox.qualification.toml").write_text(
            'schema = "stygnox_qualification_config_v1"\n\n'
            '[[gate]]\n'
            'name = "project-tests"\n'
            f'command = ["{sys.executable}", "-c", "raise SystemExit(0)"]\n'
            'timeout_seconds = 60\n',
            encoding="utf-8",
        )
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "baseline")


def identity(base: Path) -> adoption.CommandIdentity:
    executable = base / "bin" / "stygnox"
    package = base / "site" / "stygnox" / "adoption.py"
    executable.parent.mkdir(parents=True, exist_ok=True)
    package.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    package.write_text("# installed\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), package.resolve(), "0.1.0.dev5")


def active_reviewed(repo: Path, external: Path) -> None:
    resolved = identity(external)
    with mock.patch.object(adoption, "resolve_installed_command", return_value=resolved):
        preview = adoption.build_preview(
            repo,
            "Operator One",
            provider="codex",
            model="gpt-test",
            effort="high",
            reviewer="Reviewer One",
        )
        adoption.handoff_adoption(
            repo,
            "Operator One",
            preview["preview_sha256"],
            "HANDOFF",
            provider="codex",
            model="gpt-test",
            effort="high",
            reviewer="Reviewer One",
        )
        transactions.begin_transaction(repo, "Operator One", "BEGIN")
        controller.activate_controller(repo, "Operator One", "ACTIVATE")


def planning_provider(steps: list[dict]) -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "read-only",
        "payload": {"steps": steps, "files_inspected": ["README.md"]},
        "metrics": {
            "commands_executed": 1,
            "input_tokens": 10,
            "cached_input_tokens": 5,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "codex_seconds": 0.1,
        },
    }


def implementation_result(status: str, summary: str) -> dict:
    return {
        "provider": "codex",
        "model": "gpt-test",
        "effort": "high",
        "sandbox": "workspace-write",
        "status": status,
        "summary": summary,
        "files_inspected": ["README.md"],
        "metrics": {
            "commands_executed": 1,
            "input_tokens": 20,
            "cached_input_tokens": 10,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "codex_seconds": 0.2,
            "files_inspected": 1,
        },
    }


def approve(repo: Path, steps: list[dict]) -> dict:
    preview = planning.build_proposal_preview(
        repo,
        "Operator One",
        "Human gate plan",
        "write",
        min_steps=len(steps),
        max_steps=len(steps),
    )
    with mock.patch.object(provider_codex, "execute_structured", return_value=planning_provider(steps)):
        candidate = planning.propose_plan(
            repo,
            "Operator One",
            "Human gate plan",
            "write",
            preview["preview_sha256"],
            "PROPOSE",
            min_steps=len(steps),
            max_steps=len(steps),
        )
    return planning.approve_plan(repo, "Operator One", candidate["plan_hash"], "APPROVE")


def step(
    index: int,
    *,
    objective: str | None = None,
    acceptance: list[str] | None = None,
    policy: str = "add-only",
) -> dict:
    return {
        "id": index,
        "title": f"Step {index}",
        "objective": objective or f"Implement step {index}",
        "acceptance": acceptance or [f"Step {index} is complete"],
        "test_change_policy": policy,
    }


def open_provider_gate(repo: Path, approved: dict, *, summary: str = "Need operator direction") -> dict:
    objective = approved["plan"]["steps"][0]["objective"]
    preview = controller.build_run_preview(repo, "Operator One", objective, "write")
    with mock.patch.object(provider_codex, "execute", return_value=implementation_result("BLOCKED", summary)):
        return controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")


def rewrite_runtime_record(path: Path, value: dict) -> None:
    """Persist a syntactically valid canonical-authority interleaving."""
    body = dict(value)
    body.pop("record_sha256", None)
    body["record_sha256"] = human_control._digest(body)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class StygnoxHumanControlTests(TestCase):
    def setUp(self) -> None:
        self._provider_catalog_patch = mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog())
        self._provider_catalog_patch.start()
        self.addCleanup(self._provider_catalog_patch.stop)
        self._provider_rate_patch = mock.patch.object(provider_codex, "rate_limits", return_value=safe_rate_limits())
        self._provider_rate_patch.start()
        self.addCleanup(self._provider_rate_patch.stop)

    def assert_direct_apply_refusal_preserves_gate(self, repo: Path, preview: dict) -> None:
        """Verify the mutation boundary, not a wrapper's rebuilt preview."""
        before = planning._record(repo)
        assert before is not None
        durable = json.loads(json.dumps({
            key: before.get(key)
            for key in ("active_gate", "status", "current_step", "execution_authority_granted", "human_gate_history")
        }))
        self.assertEqual("BLOCKED_HUMAN", durable["status"])
        self.assertFalse(durable["execution_authority_granted"])
        self.assertIsNotNone(durable["active_gate"])

        with self.assertRaises((human_control.HumanControlError, planning.PlanningError, controller.ControllerError)):
            human_control._apply_decision(preview, preview["preview_sha256"], "RESUME")

        after = planning._record(repo)
        assert after is not None
        self.assertEqual(durable["active_gate"], after.get("active_gate"))
        self.assertEqual(durable["status"], after.get("status"))
        self.assertEqual(durable["current_step"], after.get("current_step"))
        self.assertEqual(durable["execution_authority_granted"], after.get("execution_authority_granted"))
        self.assertEqual(durable["human_gate_history"], after.get("human_gate_history"))
        self.assertEqual([], list((repo / adoption.RUNTIME_NAME).glob("human-decision-*.json")))

    def test_apply_decision_refuses_each_canonical_authority_interleaving(self) -> None:
        def mutate_plan_record(repo: Path) -> None:
            state = planning._record(repo)
            assert state is not None
            state["human_gate_sequence"] = int(state["human_gate_sequence"]) + 1
            planning._write(repo, state)

        def mutate_plan_identity(repo: Path) -> None:
            state = planning._record(repo)
            assert state is not None
            state["plan"]["steps"][0]["title"] = "Replacement approved step"
            state["plan_hash"] = planning._plan_hash(state["plan"])
            gate = dict(state["active_gate"])
            gate["plan_hash"] = state["plan_hash"]
            gate["gate_sha256"] = human_control._gate_digest(gate)
            state["active_gate"] = gate
            planning._write(repo, state)

        def mutate_active_gate(repo: Path) -> None:
            state = planning._record(repo)
            assert state is not None
            gate = dict(state["active_gate"])
            gate["gate_id"] = "HG-REPLACED-01"
            gate["gate_sha256"] = human_control._gate_digest(gate)
            state["active_gate"] = gate
            planning._write(repo, state)

        def mutate_gate_digest(repo: Path) -> None:
            state = planning._record(repo)
            assert state is not None
            gate = dict(state["active_gate"])
            gate["reason"] = "A replacement gate reason"
            gate["gate_sha256"] = human_control._gate_digest(gate)
            state["active_gate"] = gate
            planning._write(repo, state)

        def mutate_current_step(repo: Path) -> None:
            state = planning._record(repo)
            assert state is not None
            state["current_step"] = 2
            planning._write(repo, state)

        def mutate_blocked_baseline(repo: Path) -> None:
            (repo / "README.md").write_text("canonical boundary drift\n", encoding="utf-8")

        def mutate_transaction_operator(repo: Path) -> None:
            path = repo / adoption.RUNTIME_NAME / transactions.TRANSACTION_RECORD
            record = json.loads(path.read_text(encoding="utf-8"))
            record["operator"] = "Operator Two"
            record["transaction_id"] = "TX-MUTATED-01"
            rewrite_runtime_record(path, record)

        def mutate_controller_authority(repo: Path) -> None:
            path = repo / adoption.RUNTIME_NAME / controller.CONTROLLER_RECORD
            record = json.loads(path.read_text(encoding="utf-8"))
            record["controller_execution_enabled"] = False
            rewrite_runtime_record(path, record)

        def mutate_execution_policy_authority(repo: Path) -> None:
            path = repo / adoption.RUNTIME_NAME / "adoption.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["execution_policy_review"]["review_sha256"] = "f" * 64
            rewrite_runtime_record(path, record)

        mutations = (
            ("plan record", mutate_plan_record),
            ("plan identity", mutate_plan_identity),
            ("active gate", mutate_active_gate),
            ("gate digest", mutate_gate_digest),
            ("current step", mutate_current_step),
            ("blocked baseline", mutate_blocked_baseline),
            ("transaction and operator", mutate_transaction_operator),
            ("controller authority", mutate_controller_authority),
            ("execution-policy authority", mutate_execution_policy_authority),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for label, mutate in mutations:
                with self.subTest(authority=label):
                    repo = root / label.replace(" ", "-")
                    init_repo(repo)
                    active_reviewed(repo, root / f"{label}-external")
                    approved = approve(repo, [step(1), step(2)])
                    gate = open_provider_gate(repo, approved)["human_gate"]
                    preview = human_control.build_resume_preview(
                        repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Retry with the same authority."
                    )
                    mutate(repo)
                    self.assert_direct_apply_refusal_preserves_gate(repo, preview)

    def test_apply_decision_commits_an_unchanged_exact_preview(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1)])
            gate = open_provider_gate(repo, approved)["human_gate"]
            preview = human_control.build_resume_preview(
                repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Exact authority remains unchanged."
            )

            decision = human_control._apply_decision(preview, preview["preview_sha256"], "RESUME")

            state = planning.plan_status(repo)["plan"]
            receipt = repo / adoption.RUNTIME_NAME / f"human-decision-{gate['gate_id'].lower()}-resume.json"
            self.assertEqual("HUMAN_RESUMED", decision["result"])
            self.assertEqual("APPROVED", state["status"])
            self.assertTrue(state["execution_authority_granted"])
            self.assertEqual(1, state["current_step"])
            self.assertIsNone(state["active_gate"])
            self.assertTrue(receipt.is_file())

    def test_shared_cli_dispatch_preserves_steer_resume_and_resolve_behavior(self) -> None:
        cases = (
            ("gate", "steer", step(1), "--direction", "Keep the exact approved scope.", "HUMAN_STEERED", "APPROVED", 1),
            ("human", "resume", step(1), "--reason", "Evidence is now available.", "HUMAN_RESUMED", "APPROVED", 1),
            (
                "gate",
                "resolve",
                step(1, acceptance=["If runtime evidence is absent, stop at BLOCKED_HUMAN for operator evidence."]),
                "--reason",
                "Operator evidence confirms the step.",
                "PLAN_STEPS_COMPLETE_HUMAN_CONFIRMED",
                "STEPS_COMPLETE",
                2,
            ),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for command, action, first_step, text_flag, text, result, status, current_step in cases:
                with self.subTest(action=action):
                    repo = root / action
                    init_repo(repo)
                    active_reviewed(repo, root / f"{action}-external")
                    approved = approve(repo, [first_step])
                    summary = "BLOCKED_HUMAN: operator evidence is required" if action == "resolve" else "Need operator direction"
                    gate = open_provider_gate(repo, approved, summary=summary)["human_gate"]
                    if action == "steer":
                        preview = human_control.build_steer_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], text)
                    elif action == "resume":
                        preview = human_control.build_resume_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], text)
                    else:
                        preview = human_control.build_resolve_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], text)
                    output = StringIO()
                    with redirect_stdout(output):
                        exit_code = cli.main([
                            command,
                            action,
                            approved["plan_hash"],
                            "--gate", gate["gate_id"],
                            "--project", str(repo),
                            "--operator", "Operator One",
                            text_flag, text,
                            "--preview", preview["preview_sha256"],
                            "--confirm", action.upper(),
                        ])
                    decision = json.loads(output.getvalue())
                    state = planning.plan_status(repo)["plan"]
                    self.assertEqual(0, exit_code)
                    self.assertEqual(result, decision["result"])
                    self.assertEqual(status, state["status"])
                    self.assertEqual(current_step, state["current_step"])

    def test_provider_block_latches_exact_gate_and_blocks_controller_bypass(self) -> None:
        delegated = step(
            1,
            acceptance=["If runtime evidence is absent, stop at BLOCKED_HUMAN for operator evidence."],
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [delegated])
            result = open_provider_gate(repo, approved, summary="BLOCKED_HUMAN: operator runtime evidence is required")
            status = planning.plan_status(repo)["plan"]
            gate = result["human_gate"]
            gate_status = human_control.gate_status(repo)
            self.assertEqual("human-gate-required", result["next_action"])
            self.assertEqual("BLOCKED_HUMAN", status["status"])
            self.assertFalse(status["execution_authority_granted"])
            self.assertTrue(gate["human_resolvable"])
            self.assertEqual(approved["plan_hash"], gate["plan_hash"])
            self.assertEqual(1, gate["step"])
            self.assertEqual(gate["gate_id"], gate_status["gate"]["gate_id"])
            with self.assertRaisesRegex(controller.ControllerError, "blocked at human gate"):
                controller.build_run_preview(repo, "Operator One", delegated["objective"], "write")

    def test_steer_records_bounded_direction_and_retries_exact_same_step(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1)])
            blocked = open_provider_gate(repo, approved)
            gate = blocked["human_gate"]
            preview = human_control.build_steer_preview(
                repo,
                "Operator One",
                approved["plan_hash"],
                gate["gate_id"],
                "Keep the approved objective; inspect the local evidence first.",
            )
            decision = human_control.steer(
                repo,
                "Operator One",
                approved["plan_hash"],
                gate["gate_id"],
                "Keep the approved objective; inspect the local evidence first.",
                preview["preview_sha256"],
                "STEER",
            )
            state = planning.plan_status(repo)["plan"]
            run_preview = controller.build_run_preview(repo, "Operator One", step(1)["objective"], "write")
            self.assertEqual("HUMAN_STEERED", decision["result"])
            self.assertEqual("APPROVED", state["status"])
            self.assertEqual(1, state["current_step"])
            self.assertEqual(gate["blocked_baseline_sha256"], state["step_authority_baseline_sha256"])
            self.assertEqual(gate["gate_id"], run_preview["plan_binding"]["resumed_from_gate"])
            self.assertIn("Keep the approved objective", run_preview["plan_binding"]["human_direction"])
            self.assertIn("Bounded human direction", controller._prompt(run_preview))

    def test_policy_gate_allows_only_exact_new_test_candidate_and_never_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1, policy="none")])
            self.assertNotIn("tests/test_new.py", approved["approval_repository_manifest"])
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")

            def mutate(**_kwargs: object) -> dict:
                (repo / "tests").mkdir(exist_ok=True)
                (repo / "tests" / "test_new.py").write_text("value = 1\n", encoding="utf-8")
                return implementation_result("PASS", "implementation complete")

            with mock.patch.object(provider_codex, "execute", side_effect=mutate):
                result = controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")
            gate = result["human_gate"]
            self.assertEqual("test-policy", gate["kind"])
            self.assertFalse(gate["human_resolvable"])
            self.assertEqual(["tests/test_new.py"], gate["allowed_new_test_candidates"])
            with self.assertRaisesRegex(human_control.HumanControlError, "not operator-resolvable"):
                human_control.build_resolve_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "accept it")
            with self.assertRaisesRegex(human_control.HumanControlError, "not part of the current policy gate"):
                human_control.build_steer_preview(
                    repo, "Operator One", approved["plan_hash"], gate["gate_id"], "allow wrong", ["tests/test_other.py"]
                )
            steer_preview = human_control.build_steer_preview(
                repo,
                "Operator One",
                approved["plan_hash"],
                gate["gate_id"],
                "Authorise this exact new regression test only.",
                ["tests/test_new.py"],
            )
            human_control.steer(
                repo,
                "Operator One",
                approved["plan_hash"],
                gate["gate_id"],
                "Authorise this exact new regression test only.",
                steer_preview["preview_sha256"],
                "STEER",
                ["tests/test_new.py"],
            )
            retry = controller.build_run_preview(repo, "Operator One", objective, "write")
            self.assertEqual(["tests/test_new.py"], retry["plan_binding"]["allowed_new_tests"])

    def test_policy_gate_refuses_approval_time_test_path_after_permitted_removal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo, existing_test=True, qualification_gate=True)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1, policy="modify"), step(2, policy="none")])
            self.assertIn("tests/test_existing.py", approved["approval_repository_manifest"])

            first_objective = approved["plan"]["steps"][0]["objective"]
            first_preview = controller.build_run_preview(repo, "Operator One", first_objective, "write")

            def remove_approval_time_test(**_kwargs: object) -> dict:
                (repo / "tests" / "test_existing.py").unlink()
                return implementation_result("PASS", "permitted test removal complete")

            with mock.patch.object(provider_codex, "execute", side_effect=remove_approval_time_test):
                first_result = controller.run_controller(repo, "Operator One", first_objective, "write", first_preview["preview_sha256"], "RUN")
            self.assertIsNone(first_result["human_gate"])
            qualification_preview = qualification.build_preview(repo, "Operator One", approved["plan_hash"])
            qualification_result = qualification.run_qualification(
                repo, "Operator One", approved["plan_hash"], qualification_preview["preview_sha256"], "QUALIFY"
            )
            self.assertEqual("STEP_QUALIFIED", qualification_result["result"])

            second_objective = approved["plan"]["steps"][1]["objective"]
            second_preview = controller.build_run_preview(repo, "Operator One", second_objective, "write")

            def recreate_approval_time_test(**_kwargs: object) -> dict:
                (repo / "tests" / "test_existing.py").write_text("value = 2\n", encoding="utf-8")
                return implementation_result("PASS", "policy-none test recreation complete")

            with mock.patch.object(provider_codex, "execute", side_effect=recreate_approval_time_test):
                second_result = controller.run_controller(repo, "Operator One", second_objective, "write", second_preview["preview_sha256"], "RUN")
            gate = second_result["human_gate"]
            self.assertEqual("test-policy", gate["kind"])
            self.assertEqual([], gate["allowed_new_test_candidates"])
            for refused_path in ("tests/test_existing.py", "tests/test_wrong.py"):
                with self.assertRaisesRegex(human_control.HumanControlError, "not part of the current policy gate"):
                    human_control.build_steer_preview(
                        repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Do not broaden authority.", [refused_path]
                    )

    def test_add_only_new_test_and_modify_existing_test_remain_permitted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            add_only_repo = root / "add-only"
            init_repo(add_only_repo)
            active_reviewed(add_only_repo, root / "add-only-external")
            add_only_approved = approve(add_only_repo, [step(1, policy="add-only")])
            add_only_objective = add_only_approved["plan"]["steps"][0]["objective"]
            add_only_preview = controller.build_run_preview(add_only_repo, "Operator One", add_only_objective, "write")

            def add_test(**_kwargs: object) -> dict:
                (add_only_repo / "tests").mkdir()
                (add_only_repo / "tests" / "test_added.py").write_text("value = 1\n", encoding="utf-8")
                return implementation_result("PASS", "add-only test addition complete")

            with mock.patch.object(provider_codex, "execute", side_effect=add_test):
                add_only_result = controller.run_controller(
                    add_only_repo, "Operator One", add_only_objective, "write", add_only_preview["preview_sha256"], "RUN"
                )
            self.assertIsNone(add_only_result["human_gate"])
            self.assertEqual("qualification-required", add_only_result["next_action"])

            modify_repo = root / "modify"
            init_repo(modify_repo, existing_test=True)
            active_reviewed(modify_repo, root / "modify-external")
            modify_approved = approve(modify_repo, [step(1, policy="modify")])
            modify_objective = modify_approved["plan"]["steps"][0]["objective"]
            modify_preview = controller.build_run_preview(modify_repo, "Operator One", modify_objective, "write")

            def modify_test(**_kwargs: object) -> dict:
                (modify_repo / "tests" / "test_existing.py").write_text("value = 2\n", encoding="utf-8")
                return implementation_result("PASS", "modify test edit complete")

            with mock.patch.object(provider_codex, "execute", side_effect=modify_test):
                modify_result = controller.run_controller(
                    modify_repo, "Operator One", modify_objective, "write", modify_preview["preview_sha256"], "RUN"
                )
            self.assertIsNone(modify_result["human_gate"])
            self.assertEqual("qualification-required", modify_result["next_action"])

    def test_steer_refuses_new_test_grant_for_preexisting_test_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo, existing_test=True)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1, policy="none")])
            objective = approved["plan"]["steps"][0]["objective"]
            preview = controller.build_run_preview(repo, "Operator One", objective, "write")

            def mutate(**_kwargs: object) -> dict:
                (repo / "tests" / "test_existing.py").write_text("value = 2\n", encoding="utf-8")
                return implementation_result("PASS", "implementation complete")

            with mock.patch.object(provider_codex, "execute", side_effect=mutate):
                result = controller.run_controller(repo, "Operator One", objective, "write", preview["preview_sha256"], "RUN")
            gate = result["human_gate"]
            self.assertEqual([], gate["allowed_new_test_candidates"])
            with self.assertRaisesRegex(human_control.HumanControlError, "not part of the current policy gate"):
                human_control.build_steer_preview(
                    repo,
                    "Operator One",
                    approved["plan_hash"],
                    gate["gate_id"],
                    "Do not broaden authority.",
                    ["tests/test_existing.py"],
                )

    def test_resume_retries_same_step_without_granting_new_scope(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1)])
            blocked = open_provider_gate(repo, approved)
            gate = blocked["human_gate"]
            preview = human_control.build_resume_preview(
                repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Environment evidence is now available."
            )
            decision = human_control.resume(
                repo,
                "Operator One",
                approved["plan_hash"],
                gate["gate_id"],
                "Environment evidence is now available.",
                preview["preview_sha256"],
                "RESUME",
            )
            state = planning.plan_status(repo)["plan"]
            retry = controller.build_run_preview(repo, "Operator One", step(1)["objective"], "write")
            self.assertEqual("HUMAN_RESUMED", decision["result"])
            self.assertEqual(1, state["current_step"])
            self.assertEqual([], retry["plan_binding"]["allowed_new_tests"])
            self.assertIn("Environment evidence", retry["plan_binding"]["resume_reason"])

    def test_human_owned_resolve_advances_without_provider_retry(self) -> None:
        delegated = step(
            1,
            acceptance=["If runtime evidence is absent, stop at BLOCKED_HUMAN for operator evidence."],
        )
        second = step(2, objective="Implement step two")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [delegated, second])
            blocked = open_provider_gate(repo, approved, summary="BLOCKED_HUMAN: operator runtime evidence is required")
            gate = blocked["human_gate"]
            preview = human_control.build_resolve_preview(
                repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Observed runtime evidence is satisfactory."
            )
            with mock.patch.object(provider_codex, "execute") as execute:
                decision = human_control.resolve(
                    repo,
                    "Operator One",
                    approved["plan_hash"],
                    gate["gate_id"],
                    "Observed runtime evidence is satisfactory.",
                    preview["preview_sha256"],
                    "RESOLVE",
                )
            execute.assert_not_called()
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("HUMAN_CONFIRMED_STEP_ADVANCED", decision["result"])
            self.assertEqual("APPROVED", state["status"])
            self.assertEqual(2, state["current_step"])
            self.assertEqual(gate["blocked_baseline_sha256"], state["step_authority_baseline_sha256"])
            next_preview = controller.build_run_preview(repo, "Operator One", "Implement step two", "write")
            self.assertEqual(2, next_preview["plan_binding"]["current_step"])
            receipt = repo / adoption.RUNTIME_NAME / f"human-decision-{gate['gate_id'].lower()}-resolve.json"
            self.assertTrue(receipt.is_file())

    def test_last_human_owned_resolution_enters_steps_complete_not_free_execution(self) -> None:
        delegated = step(
            1,
            acceptance=["If runtime evidence is absent, stop at BLOCKED_HUMAN for human-owned operator evidence."],
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [delegated])
            blocked = open_provider_gate(repo, approved, summary="BLOCKED_HUMAN: operator evidence is required")
            gate = blocked["human_gate"]
            preview = human_control.build_resolve_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Evidence confirmed")
            human_control.resolve(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "Evidence confirmed", preview["preview_sha256"], "RESOLVE")
            state = planning.plan_status(repo)["plan"]
            self.assertEqual("STEPS_COMPLETE", state["status"])
            self.assertFalse(state["execution_authority_granted"])
            with self.assertRaisesRegex(controller.ControllerError, "qualification is required"):
                controller.build_run_preview(repo, "Operator One", delegated["objective"], "write")

    def test_gate_decisions_fail_closed_on_wrong_gate_or_repository_drift_and_cli_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            active_reviewed(repo, root / "external")
            approved = approve(repo, [step(1)])
            blocked = open_provider_gate(repo, approved)
            gate = blocked["human_gate"]
            with self.assertRaisesRegex(human_control.HumanControlError, "does not match current gate"):
                human_control.build_resume_preview(repo, "Operator One", approved["plan_hash"], "HG-9999-01", "retry")
            preview = human_control.build_steer_preview(repo, "Operator One", approved["plan_hash"], gate["gate_id"], "bounded retry")
            (repo / "README.md").write_text("external drift\n", encoding="utf-8")
            with self.assertRaisesRegex(human_control.HumanControlError, "repository changed after human gate opened"):
                human_control.steer(
                    repo,
                    "Operator One",
                    approved["plan_hash"],
                    gate["gate_id"],
                    "bounded retry",
                    preview["preview_sha256"],
                    "STEER",
                )

        with mock.patch.object(human_control, "cli_main", return_value=0) as route:
            self.assertEqual(0, cli.main(["gate", "status"]))
            route.assert_called_once_with(["status"])


if __name__ == "__main__":
    import unittest
    unittest.main()
