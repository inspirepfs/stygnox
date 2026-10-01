from __future__ import annotations

import json
import unittest
from unittest import mock

import test_ralph_lifecycle as lifecycle


RepoHarness = lifecycle.RepoHarness
ralph = lifecycle.ralph
valid_plan = lifecycle.valid_plan


class PendingRetirementRecoveryTests(unittest.TestCase):
    """Exercise retirement recovery from the controller's real repository evidence."""

    @staticmethod
    def _approved_v2_state(scope: list[str]) -> dict:
        plan = valid_plan()
        plan.update({
            "schema": "zen_ralph_plan_v2",
            "repository_mutation_scope": sorted(scope),
        })
        state = ralph.default_state()
        state.update({
            "status": "APPROVED",
            "plan_hash": ralph.plan_hash(plan),
            "plan": plan,
            "current_step": 1,
        })
        ralph.PLAN.write_text(ralph.render_plan(plan), encoding="utf-8")
        ralph.bind_approved_plan_artifact(state)
        checkpoint = ralph.create_recovery_checkpoint(state)
        state["recovery_checkpoint"] = checkpoint["id"]
        state["approval_repository_evidence"] = checkpoint["repository_evidence"]
        ralph.save_state(state)
        return state

    @staticmethod
    def _rollback_args(state: dict, *, reconcile_restored: bool = False):
        return type("Args", (), {
            "plan_hash": state["plan_hash"],
            "reason": "exercise stranded pending retirement evidence",
            "rollback": True,
            "carry_forward": False,
            "preview_sha": None,
            "confirm": None,
            "reconcile_restored": reconcile_restored,
        })()

    def _strand_variants(self, repo) -> dict:
        modified = repo.root / "modified.py"
        deleted = repo.root / "deleted.py"
        modified.write_text("value = 'baseline'\n", encoding="utf-8")
        deleted.write_text("value = 'baseline'\n", encoding="utf-8")
        repo.git("add", "modified.py", "deleted.py")
        repo.git("commit", "-qm", "pending recovery baselines")

        state = self._approved_v2_state([
            "created.py", "deleted.py", "modified.py", "scripts/ralph.py",
        ])
        controller = repo.root / "scripts" / "ralph.py"

        def denied_turn(*_args, **_kwargs):
            controller.parent.mkdir(parents=True, exist_ok=True)
            controller.write_text("unapproved controller edit\n", encoding="utf-8")
            modified.write_text("value = 'pending'\n", encoding="utf-8")
            deleted.unlink()
            (repo.root / "created.py").write_text("value = 'pending'\n", encoding="utf-8")
            return lifecycle.RunLoopSandboxVerificationTests._result()

        with (
            mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
            mock.patch.object(ralph, "run_codex", side_effect=denied_turn),
            mock.patch.object(ralph, "run_gates") as gates,
        ):
            self.assertEqual(2, ralph.cmd_run(lifecycle.RunLoopSandboxVerificationTests._args()))
        gates.assert_not_called()
        self.assertFalse(controller.exists())
        return ralph.load_state()

    def test_denied_self_hosting_restores_controller_preserves_siblings_and_retry_stops_before_inference(self):
        with RepoHarness(self) as repo:
            state = self._approved_v2_state([
                "scripts/ralph.py", "scripts/stygnox_core.py", "scripts/stygnox_protocol.py",
            ])
            controller = repo.root / "scripts" / "ralph.py"
            core = repo.root / "scripts" / "stygnox_core.py"
            protocol = repo.root / "scripts" / "stygnox_protocol.py"

            def denied_turn(*_args, **_kwargs):
                controller.parent.mkdir(parents=True, exist_ok=True)
                controller.write_text("unapproved controller edit\n", encoding="utf-8")
                core.write_text("pending core sibling\n", encoding="utf-8")
                protocol.write_text("pending protocol sibling\n", encoding="utf-8")
                return lifecycle.RunLoopSandboxVerificationTests._result()

            with (
                mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
                mock.patch.object(ralph, "run_codex", side_effect=denied_turn),
                mock.patch.object(ralph, "run_gates") as gates,
            ):
                self.assertEqual(2, ralph.cmd_run(lifecycle.RunLoopSandboxVerificationTests._args()))
            gates.assert_not_called()
            blocked = ralph.load_state()
            self.assertEqual("BLOCKED_HUMAN", blocked["status"])
            self.assertFalse(controller.exists())
            self.assertEqual("pending core sibling\n", core.read_text(encoding="utf-8"))
            self.assertEqual("pending protocol sibling\n", protocol.read_text(encoding="utf-8"))
            evidence = blocked["pending_retirement_recovery_evidence"]
            self.assertEqual(["scripts/stygnox_core.py", "scripts/stygnox_protocol.py"], evidence["paths"])
            self.assertEqual(["scripts/ralph.py"], [item["path"] for item in evidence["authority_enforcement_removals"]])
            self.assertEqual([], blocked["operation_attributions"])

            candidate = blocked["self_hosting_candidate"]
            self.assertEqual(0, ralph.cmd_authorize_self_hosting(type("Args", (), {
                "plan_hash": state["plan_hash"], "gate": candidate["gate_id"],
                "path": candidate["paths"], "reason": "bounded retry fixture",
            })()))
            retry = ralph.load_state()
            retry["approved_plan_artifact"]["sha256"] = "0" * 64
            ralph.save_state(retry)
            with mock.patch.object(ralph, "run_codex") as inference:
                with self.assertRaisesRegex(RuntimeError, "blocked for human review"):
                    ralph.cmd_run(lifecycle.RunLoopSandboxVerificationTests._args())
            inference.assert_not_called()
            self.assertEqual("BLOCKED_HUMAN", ralph.load_state()["status"])

    def test_tracked_modification_checkpoint_absent_creation_and_tracked_deletion_remain_pending(self):
        with RepoHarness(self) as repo:
            blocked = self._strand_variants(repo)
            evidence = blocked["pending_retirement_recovery_evidence"]
            self.assertEqual([], blocked["operation_attributions"])
            self.assertEqual([], blocked["step_results"])
            self.assertEqual(
                {
                    "modified.py": "tracked-modification",
                    "created.py": "checkpoint-absent-creation",
                    "deleted.py": "tracked-deletion",
                },
                {item["path"]: item["change"] for item in evidence["path_evidence"]},
            )
            self.assertEqual(0, ralph.cmd_retire_plan(self._rollback_args(blocked)))
            preview = ralph.load_state()["retirement_rollback_preview"]
            self.assertTrue(all(item["provenance"]["authority"] == "pending-recovery-only" for item in preview["paths"]))

    def test_rollback_refuses_altered_replaced_restored_pending_evidence_and_extra_dirty_path(self):
        for mutation in ("altered", "replaced", "restored", "extra"):
            with self.subTest(mutation=mutation), RepoHarness(self) as repo:
                blocked = self._strand_variants(repo)
                if mutation == "altered":
                    (repo.root / "modified.py").write_text("value = 'altered'\n", encoding="utf-8")
                elif mutation == "replaced":
                    (repo.root / "created.py").write_text("value = 'replacement'\n", encoding="utf-8")
                elif mutation == "restored":
                    repo.git("checkout", "HEAD", "--", "modified.py")
                else:
                    (repo.root / "extra.py").write_text("outside evidence\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "(pending recovery evidence|unattributed or stale checkpoint delta)"):
                    ralph.cmd_retire_plan(self._rollback_args(blocked))

    def test_external_restore_is_strict_noop_and_enforcement_scope_and_provenance_fail_closed(self):
        with RepoHarness(self) as repo:
            blocked = self._strand_variants(repo)
            repo.git("checkout", "HEAD", "--", "modified.py", "deleted.py")
            (repo.root / "created.py").unlink()
            before = ralph.repo_snapshot()
            self.assertEqual(0, ralph.cmd_retire_plan(self._rollback_args(blocked, reconcile_restored=True)))
            self.assertEqual(before, ralph.repo_snapshot())
            manifest = json.loads(next(ralph.RETIREMENTS.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual({"restore": [], "delete": [], "preserved": []}, manifest["operations"])
            self.assertTrue(all(item["restoration"]["action"] == "none" for item in manifest["paths"]))

        for failure in ("enforcement", "scope", "provenance"):
            with self.subTest(failure=failure), RepoHarness(self) as repo:
                blocked = self._strand_variants(repo)
                pending = blocked["pending_retirement_recovery_evidence"]
                if failure == "enforcement":
                    pending["authority_enforcement_removals"][0]["path"] = ".ralph/state.json"
                elif failure == "scope":
                    pending["repository_scope"] = ["created.py"]
                    pending["repository_scope_sha256"] = ralph._evidence_digest(pending["repository_scope"])
                else:
                    pending["originating_step_sha256"] = "0" * 64
                pending["evidence_sha256"] = ralph._evidence_digest({
                    key: value for key, value in pending.items() if key != "evidence_sha256"
                })
                ralph.save_state(blocked)
                with self.assertRaisesRegex(RuntimeError, "(scope|originating step|enforcement removal)"):
                    ralph.cmd_retire_plan(self._rollback_args(blocked, reconcile_restored=True))


if __name__ == "__main__":
    unittest.main()
