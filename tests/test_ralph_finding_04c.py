from __future__ import annotations

import unittest
from unittest import mock

import test_ralph_lifecycle as lifecycle


RepoHarness = lifecycle.RepoHarness
ralph = lifecycle.ralph
valid_plan = lifecycle.valid_plan


class Finding04CLifecycleRegressionTests(unittest.TestCase):
    """Exercise accepted-plus-pending provenance through the real controller lifecycle."""

    @staticmethod
    def _plan() -> dict:
        plan = valid_plan()
        plan.update({
            "schema": "zen_ralph_plan_v2",
            "repository_authority": "write",
            "repository_mutation_scope": ["app.py", "second.py"],
        })
        return plan

    @staticmethod
    def _gate(passed: bool) -> tuple[bool, list[str], str | None, str, dict]:
        if passed:
            return True, ["focused-controller-provenance=PASS"], None, "", {}
        return (
            False,
            ["focused-controller-provenance=FAIL"],
            "finding-04c-qualification",
            "authoritative qualification failure",
            {},
        )

    def _run_turn(self, change, *, passed: bool) -> int:
        def codex_turn(*_args, **_kwargs):
            change()
            return lifecycle.RunLoopSandboxVerificationTests._result()

        with (
            mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
            mock.patch.object(ralph, "run_codex", side_effect=codex_turn),
            mock.patch.object(ralph, "codex_requests_continuation", return_value=(False, "")),
            mock.patch.object(ralph, "run_gates", return_value=self._gate(passed)),
        ):
            return ralph.cmd_run(lifecycle.RunLoopSandboxVerificationTests._args())

    @staticmethod
    def _retire_args(state: dict, *, reconcile_restored: bool = False, preview_sha: str | None = None, confirm: str | None = None):
        return type("Args", (), {
            "plan_hash": state["plan_hash"],
            "reason": "exercise FINDING-04C layered provenance retirement",
            "rollback": True,
            "carry_forward": False,
            "reconcile_restored": reconcile_restored,
            "preview_sha": preview_sha,
            "confirm": confirm,
        })()

    def _layered_state(self, repo) -> tuple[dict, dict, dict]:
        lifecycle.RunLoopSandboxVerificationTests._approved_state(self, self._plan())
        shared = repo.root / "app.py"
        created = repo.root / "second.py"

        self.assertEqual(0, self._run_turn(
            lambda: shared.write_text("value = 'accepted step one'\n", encoding="utf-8"),
            passed=True,
        ))
        accepted = ralph.load_state()
        self.assertEqual(2, accepted["current_step"])
        first_record = accepted["operation_attributions"][0]

        def failing_step_two() -> None:
            shared.write_text("value = 'failed step two'\n", encoding="utf-8")
            created.write_text("value = 'created step two'\n", encoding="utf-8")

        self.assertEqual(0, self._run_turn(failing_step_two, passed=False))
        failed = ralph.load_state()
        first_pending = failed["pending_current_step_provenance"]
        first_shared = next(item for item in first_pending["path_evidence"] if item["path"] == "app.py")

        self.assertEqual(0, self._run_turn(
            lambda: shared.write_text("value = 'repaired shared path'\n", encoding="utf-8"),
            passed=False,
        ))
        layered = ralph.load_state()
        pending = layered["pending_current_step_provenance"]
        pending_by_path = {item["path"]: item for item in pending["path_evidence"]}

        self.assertEqual(["app.py", "second.py"], pending["paths"])
        self.assertNotEqual(first_shared["current_fingerprint"], pending_by_path["app.py"]["current_fingerprint"])
        self.assertEqual(
            first_pending["verification"]["current_fingerprints"]["second.py"],
            pending_by_path["second.py"]["current_fingerprint"],
        )
        self.assertNotEqual(first_record["current_fingerprint"], pending_by_path["app.py"]["current_fingerprint"])
        self.assertNotIn("UNATTRIBUTED_CHECKPOINT_DELTA", str(layered))
        # The controller keeps legacy recovery evidence as a distinct passive
        # witness for its own fail-closed recovery contract.  It intentionally
        # cannot overlap current-step evidence, so remove only that duplicate
        # witness to exercise the newer accepted-plus-current-step layer.
        self.assertEqual(pending["paths"], layered["pending_retirement_recovery_evidence"]["paths"])
        layered["pending_retirement_recovery_evidence"] = []
        ralph.save_state(layered)
        return layered, {"shared": shared, "created": created}, pending_by_path

    def test_repair_preserves_untouched_pending_path_and_later_qualification_promotes_latest_generation(self):
        with RepoHarness(self) as repo:
            layered, paths, pending_by_path = self._layered_state(repo)
            self.assertEqual("value = 'repaired shared path'\n", paths["shared"].read_text(encoding="utf-8"))
            self.assertEqual("value = 'created step two'\n", paths["created"].read_text(encoding="utf-8"))

            self.assertEqual(0, self._run_turn(lambda: None, passed=True))
            accepted = ralph.load_state()
            records = {record["path"]: record for record in accepted["operation_attributions"]}

            self.assertEqual([], accepted["pending_current_step_provenance"])
            self.assertEqual({"app.py", "second.py"}, set(accepted["step_results"][-1]["files"]))
            self.assertEqual(pending_by_path["app.py"]["current_fingerprint"], records["app.py"]["current_fingerprint"])
            self.assertEqual(pending_by_path["second.py"]["current_fingerprint"], records["second.py"]["current_fingerprint"])
            self.assertEqual(3, len(accepted["operation_attributions"]))
            self.assertEqual(3, accepted["current_step"])

    def test_layered_provenance_rolls_back_once_per_path_and_reconciles_external_restore_as_noop(self):
        with RepoHarness(self) as repo:
            layered, paths, _pending_by_path = self._layered_state(repo)
            self.assertEqual(0, ralph.cmd_retire_plan(self._retire_args(layered)))
            preview = ralph.load_state()["retirement_rollback_preview"]
            self.assertEqual(0, ralph.cmd_retire_plan(self._retire_args(
                layered, preview_sha=preview["sha256"], confirm="ROLLBACK",
            )))
            self.assertEqual("value = 1\n", paths["shared"].read_text(encoding="utf-8"))
            self.assertFalse(paths["created"].exists())
            manifest = ralph.load_retirement_manifest(ralph.load_state()["retired_plans"][-1]["record_id"])
            self.assertEqual({"restore": ["app.py"], "delete": ["second.py"], "preserved": []}, manifest["operations"])
            app = next(item for item in manifest["paths"] if item["path"] == "app.py")
            self.assertEqual("accepted-plus-current-step-pending", app["attribution"]["authority"])

        with RepoHarness(self) as repo:
            layered, paths, _pending_by_path = self._layered_state(repo)
            repo.git("checkout", "HEAD", "--", "app.py")
            paths["created"].unlink()
            before = ralph.repo_snapshot()
            self.assertEqual(0, ralph.cmd_retire_plan(self._retire_args(layered, reconcile_restored=True)))
            self.assertEqual(before, ralph.repo_snapshot())
            manifest = ralph.load_retirement_manifest(ralph.load_state()["retired_plans"][-1]["record_id"])
            self.assertEqual({"restore": [], "delete": [], "preserved": []}, manifest["operations"])
            self.assertTrue(all(item["restoration"]["action"] == "none" for item in manifest["paths"]))

    def test_layered_provenance_refuses_stale_pending_fingerprint_and_extra_delta(self):
        for mutation in ("stale", "extra"):
            with self.subTest(mutation=mutation), RepoHarness(self) as repo:
                layered, paths, _pending_by_path = self._layered_state(repo)
                if mutation == "stale":
                    paths["shared"].write_text("value = 'stale pending fingerprint'\n", encoding="utf-8")
                    expected = "current-step pending provenance fingerprint is stale or altered"
                else:
                    (repo.root / "extra.py").write_text("outside layered provenance\n", encoding="utf-8")
                    expected = "unattributed or stale checkpoint delta"
                with self.assertRaisesRegex(RuntimeError, expected):
                    ralph.cmd_retire_plan(self._retire_args(layered))


if __name__ == "__main__":
    unittest.main()
