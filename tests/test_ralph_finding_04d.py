from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

import test_ralph_lifecycle as lifecycle


RepoHarness = lifecycle.RepoHarness
ralph = lifecycle.ralph
valid_plan = lifecycle.valid_plan


class Finding04DSelfHostingWitnessLifecycleTests(unittest.TestCase):
    """Exercise supervised self-hosting without reissuing sibling witnesses."""

    PATHS = [
        "scripts/ralph.py",
        "scripts/stygnox_core.py",
        "scripts/stygnox_protocol.py",
    ]

    @classmethod
    def _plan(cls) -> dict:
        plan = valid_plan()
        plan.update({
            "schema": "zen_ralph_plan_v2",
            "repository_authority": "write",
            "repository_mutation_scope": cls.PATHS,
        })
        return plan

    @staticmethod
    def _gate(passed: bool) -> tuple[bool, list[str], str | None, str, dict]:
        if passed:
            return True, ["finding-04d-controller=PASS"], None, "", {}
        return False, ["finding-04d-controller=FAIL"], "finding-04d", "controlled qualification failure", {}

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
            "reason": "exercise FINDING-04D supervised self-hosting retirement",
            "rollback": True,
            "carry_forward": False,
            "reconcile_restored": reconcile_restored,
            "preview_sha": preview_sha,
            "confirm": confirm,
        })()

    @staticmethod
    def _refresh_pending(pending: dict) -> None:
        for record in pending["path_evidence"]:
            record["witness_sha256"] = ralph._evidence_digest({
                key: value for key, value in record.items() if key != "witness_sha256"
            })
        pending["evidence_sha256"] = ralph._evidence_digest({
            key: value for key, value in pending.items() if key != "evidence_sha256"
        })

    def _pending_after_authorized_a_retry(self, repo) -> tuple[dict, dict[str, object], dict[str, dict]]:
        lifecycle.RunLoopSandboxVerificationTests._approved_state(self, self._plan())
        paths = {path: repo.root / path for path in self.PATHS}

        def denied_turn() -> None:
            for path, text in {
                "scripts/ralph.py": "controller = 'denied'\n",
                "scripts/stygnox_core.py": "core = 'first witness'\n",
                "scripts/stygnox_protocol.py": "protocol = 'first witness'\n",
            }.items():
                paths[path].parent.mkdir(parents=True, exist_ok=True)
                paths[path].write_text(text, encoding="utf-8")

        with (
            mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
            mock.patch.object(ralph, "run_codex", side_effect=lambda *_args, **_kwargs: (denied_turn() or lifecycle.RunLoopSandboxVerificationTests._result())),
            mock.patch.object(ralph, "run_gates") as gates,
        ):
            self.assertEqual(2, ralph.cmd_run(lifecycle.RunLoopSandboxVerificationTests._args()))
        gates.assert_not_called()

        blocked = ralph.load_state()
        self.assertEqual("BLOCKED_HUMAN", blocked["status"])
        self.assertFalse(paths["scripts/ralph.py"].exists())
        self.assertEqual("core = 'first witness'\n", paths["scripts/stygnox_core.py"].read_text(encoding="utf-8"))
        self.assertEqual("protocol = 'first witness'\n", paths["scripts/stygnox_protocol.py"].read_text(encoding="utf-8"))
        first = {
            record["path"]: copy.deepcopy(record)
            for record in blocked["pending_current_step_provenance"]["path_evidence"]
        }
        self.assertEqual(set(self.PATHS[1:]), set(first))

        candidate = blocked["self_hosting_candidate"]
        self.assertEqual(self.PATHS[:1], candidate["paths"])
        self.assertEqual(0, ralph.cmd_authorize_self_hosting(type("Args", (), {
            "plan_hash": blocked["plan_hash"], "gate": candidate["gate_id"],
            "path": candidate["paths"], "reason": "FINDING-04D bounded A-only retry",
        })()))

        self.assertEqual(0, self._run_turn(
            lambda: paths["scripts/ralph.py"].write_text("controller = 'authorized retry'\n", encoding="utf-8"),
            passed=False,
        ))
        retry = ralph.load_state()
        witnesses = {record["path"]: record for record in retry["pending_current_step_provenance"]["path_evidence"]}
        self.assertEqual(set(self.PATHS), set(witnesses))
        for sibling in self.PATHS[1:]:
            self.assertEqual(first[sibling], witnesses[sibling])
        self.assertNotEqual(
            witnesses["scripts/ralph.py"]["checkpoint_verification"]["fingerprint"],
            first[self.PATHS[1]]["checkpoint_verification"]["fingerprint"],
        )
        return retry, paths, first

    def test_authorized_retry_preserves_sibling_witnesses_and_qualifies_normally(self):
        with RepoHarness(self) as repo:
            _retry, paths, first = self._pending_after_authorized_a_retry(repo)
            self.assertEqual(0, self._run_turn(lambda: None, passed=True))
            accepted = ralph.load_state()
            records = {record["path"]: record for record in accepted["operation_attributions"]}

            self.assertEqual([], accepted["pending_current_step_provenance"])
            self.assertEqual(set(self.PATHS), set(accepted["step_results"][-1]["files"]))
            self.assertEqual("PASS", accepted["last_post_turn_verification"]["state"])
            self.assertNotIn("UNATTRIBUTED_CHECKPOINT_DELTA", json.dumps(accepted, sort_keys=True))
            self.assertNotIn("unknown checkpoint delta", json.dumps(accepted, sort_keys=True).lower())
            for sibling in self.PATHS[1:]:
                witness = first[sibling]
                promoted = records[sibling]
                self.assertEqual(witness["current_fingerprint"], promoted["current_fingerprint"])
                self.assertEqual(witness["checkpoint_verification"], promoted["controller_verification"])
                self.assertEqual(witness["originating_step"], promoted["originating_step"])
                self.assertEqual(witness["repository_authority"], promoted["repository_authority"])
                self.assertEqual(witness["originating_test_change_policy"], promoted["originating_test_change_policy"])
                self.assertEqual(witness["self_hosting_grant"], promoted["self_hosting_grant"])

            self.assertEqual("controller = 'authorized retry'\n", paths["scripts/ralph.py"].read_text(encoding="utf-8"))

    def test_sibling_alteration_removal_stale_unknown_scope_and_authority_fail_closed(self):
        for mutation in ("altered", "removed", "stale", "unknown", "out-of-scope", "authority-invalid"):
            with self.subTest(mutation=mutation), RepoHarness(self) as repo:
                retry, paths, _first = self._pending_after_authorized_a_retry(repo)
                pending = retry["pending_current_step_provenance"]
                records = {record["path"]: record for record in pending["path_evidence"]}
                if mutation == "altered":
                    paths["scripts/stygnox_core.py"].write_text("core = 'externally altered'\n", encoding="utf-8")
                elif mutation == "removed":
                    paths["scripts/stygnox_core.py"].unlink()
                elif mutation == "stale":
                    records["scripts/stygnox_core.py"]["current_fingerprint"]["content_sha256"] = "0" * 64
                    self._refresh_pending(pending)
                    ralph.save_state(retry)
                elif mutation == "unknown":
                    forged = copy.deepcopy(records["scripts/stygnox_core.py"])
                    forged["path"] = "scripts/unknown.py"
                    pending["paths"].append(forged["path"])
                    pending["path_evidence"].append(forged)
                    self._refresh_pending(pending)
                    ralph.save_state(retry)
                elif mutation == "out-of-scope":
                    (repo.root / "outside.py").write_text("outside = True\n", encoding="utf-8")
                else:
                    records["scripts/stygnox_core.py"]["self_hosting_grant"] = {"forged": True}
                    records["scripts/stygnox_core.py"]["self_hosting_grant_sha256"] = ralph._evidence_digest({"forged": True})
                    self._refresh_pending(pending)
                    ralph.save_state(retry)

                with (
                    mock.patch.object(ralph, "ensure_codex_usage_capacity", return_value=True),
                    mock.patch.object(ralph, "run_codex", return_value=lifecycle.RunLoopSandboxVerificationTests._result()),
                    mock.patch.object(ralph, "run_gates") as gates,
                ):
                    self.assertEqual(2, ralph.cmd_run(lifecycle.RunLoopSandboxVerificationTests._args()))
                gates.assert_not_called()
                blocked = ralph.load_state()
                self.assertEqual("BLOCKED_HUMAN", blocked["status"])
                self.assertEqual([], blocked["operation_attributions"])

    def test_preacceptance_retirement_uses_exact_preview_confirmation_and_reconcile_is_noop(self):
        with RepoHarness(self) as repo:
            retry, paths, _first = self._pending_after_authorized_a_retry(repo)
            self.assertEqual(0, ralph.cmd_retire_plan(self._retire_args(retry)))
            preview = ralph.load_state()["retirement_rollback_preview"]
            self.assertEqual(self.PATHS, [item["path"] for item in preview["paths"]])
            self.assertEqual(0, ralph.cmd_retire_plan(self._retire_args(
                retry, preview_sha=preview["sha256"], confirm="ROLLBACK",
            )))
            self.assertTrue(all(not path.exists() for path in paths.values()))
            manifest = ralph.load_retirement_manifest(ralph.load_state()["retired_plans"][-1]["record_id"])
            self.assertEqual({"restore": [], "delete": self.PATHS, "preserved": []}, manifest["operations"])

        with RepoHarness(self) as repo:
            retry, paths, _first = self._pending_after_authorized_a_retry(repo)
            for path in paths.values():
                path.unlink()
            before = ralph.repo_snapshot()
            self.assertEqual(0, ralph.cmd_retire_plan(self._retire_args(retry, reconcile_restored=True)))
            self.assertEqual(before, ralph.repo_snapshot())
            manifest = ralph.load_retirement_manifest(ralph.load_state()["retired_plans"][-1]["record_id"])
            self.assertEqual({"restore": [], "delete": [], "preserved": []}, manifest["operations"])
            self.assertTrue(all(item["restoration"]["action"] == "none" for item in manifest["paths"]))


if __name__ == "__main__":
    unittest.main()
