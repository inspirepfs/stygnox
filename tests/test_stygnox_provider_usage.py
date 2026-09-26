"""Round 13B-2 Codex quota admission and banked-reset authority tests."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import controller, operator, provider_codex, provider_usage, scheduler  # noqa: E402
from tests.provider_catalog_fixture import safe_rate_limits, test_catalog  # noqa: E402
from tests.test_stygnox_scheduler import active_reviewed, approve, init_repo  # noqa: E402


def raw_limits(*, used_primary=20, used_secondary=30, allowed=True, credits=1):
    return {
        "ordinaryUsageAllowed": allowed,
        "rateLimitsByLimitId": {
            "codex": {
                "planType": "plus",
                "primary": {"usedPercent": used_primary, "windowDurationMins": 300, "resetsAt": 2000000000},
                "secondary": {"usedPercent": used_secondary, "windowDurationMins": 10080, "resetsAt": 2000100000},
            }
        },
        "rateLimitResetCredits": {
            "availableCount": credits,
            "credits": ([{"id": "must-not-leak", "status": "available", "resetType": "manual", "expiresAt": 2000200000, "title": "Banked reset"}] if credits else []),
        },
    }


class ProviderUsageTests(TestCase):
    def test_rate_limit_normalization_scrubs_credit_ids_and_binds_digest(self):
        snap = provider_codex._normalise_rate_limits(raw_limits(), "gpt-test")
        self.assertEqual(provider_codex.RATE_LIMIT_SCHEMA, snap["schema"])
        self.assertTrue(snap["ordinary_usage_allowed"])
        self.assertEqual(["5h", "weekly"], [x["name"] for x in snap["windows"]])
        self.assertEqual(1, snap["available_reset_credits"])
        self.assertNotIn("must-not-leak", json.dumps(snap))
        self.assertEqual(64, len(snap["reset_credits"][0]["credit_ref"]))
        self.assertEqual(64, len(snap["snapshot_sha256"]))

    def test_rate_limits_rpc_has_no_model_turn_and_no_legacy_params(self):
        fake = mock.Mock(); fake.stdin = io.StringIO(); fake.terminate.return_value=None; fake.wait.return_value=0
        with (
            mock.patch.object(provider_codex.shutil, "which", return_value="/fake/codex"),
            mock.patch.object(provider_codex.subprocess, "Popen", return_value=fake) as popen,
            mock.patch.object(provider_codex, "_app_server_read_response", side_effect=[{}, raw_limits()]),
        ):
            provider_codex.rate_limits(Path("/tmp"), "gpt-test")
        messages=[json.loads(x) for x in fake.stdin.getvalue().splitlines()]
        self.assertEqual("account/rateLimits/read", messages[2]["method"])
        self.assertNotIn("params", messages[2])
        self.assertNotIn("exec", str(popen.call_args))

    def test_guard_preserves_historical_start_reserve_semantics(self):
        low = provider_codex._normalise_rate_limits(raw_limits(used_primary=95), "gpt-test")
        self.assertEqual("PAUSE", provider_codex.quota_guard(low, 5.0)[0])
        self.assertEqual("ADMITTED", provider_codex.quota_guard(low, 5.0, admitted=True)[0])
        denied = provider_codex._normalise_rate_limits(raw_limits(used_primary=10, allowed=False), "gpt-test")
        self.assertEqual("PAUSE", provider_codex.quota_guard(denied, 5.0, admitted=True)[0])
        unknown = provider_codex._normalise_rate_limits(raw_limits(used_primary=10, allowed=None), "gpt-test")
        self.assertEqual("UNKNOWN", provider_codex.quota_guard(unknown, 5.0)[0])

    def test_exactly_reserve_is_not_new_plan_admissible(self):
        snap = provider_codex._normalise_rate_limits(raw_limits(used_primary=95), "gpt-test")
        status, findings = provider_codex.quota_guard(snap, 5.0)
        self.assertEqual("PAUSE", status)
        self.assertIn("5h remaining 5.0% <= 5.0% reserve", findings)

    def test_plan_admission_is_persisted_and_allows_same_plan_below_reserve(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan={"plan_hash":"plan-a", "status":"APPROVED"}
            high=provider_codex._normalise_rate_limits(raw_limits(used_primary=80), "gpt-test")
            low=provider_codex._normalise_rate_limits(raw_limits(used_primary=99), "gpt-test")
            with mock.patch.object(provider_codex, "rate_limits", side_effect=[high, low]):
                first=provider_usage.ensure_capacity(root, plan_state=plan, model="gpt-test", reserve_percent=5, wait=False, poll_seconds=60)
                second=provider_usage.ensure_capacity(root, plan_state=plan, model="gpt-test", reserve_percent=5, wait=False, poll_seconds=60)
            recorded=provider_usage._state_record(root)
            self.assertEqual("SAFE", first["guard"]); self.assertEqual("ADMITTED", second["guard"])
            self.assertEqual("plan-a", recorded["admission"]["plan_hash"])
            self.assertEqual(1.0, recorded["admission"]["last_remaining_percent"])

    def test_admission_does_not_transfer_to_replacement_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan_a={"plan_hash":"plan-a", "status":"APPROVED"}; plan_b={"plan_hash":"plan-b", "status":"APPROVED"}
            high=provider_codex._normalise_rate_limits(raw_limits(used_primary=80), "gpt-test")
            low=provider_codex._normalise_rate_limits(raw_limits(used_primary=99), "gpt-test")
            with mock.patch.object(provider_codex, "rate_limits", return_value=high):
                provider_usage.ensure_capacity(root, plan_state=plan_a, model="gpt-test", reserve_percent=5, wait=False, poll_seconds=60)
            with mock.patch.object(provider_codex, "rate_limits", return_value=low):
                with self.assertRaisesRegex(provider_usage.ProviderUsageError, "admission blocked"):
                    provider_usage.ensure_capacity(root, plan_state=plan_b, model="gpt-test", reserve_percent=5, wait=False, poll_seconds=60)
            recorded=provider_usage._state_record(root)
            self.assertEqual("plan-b", recorded["plan_hash"]); self.assertIsNone(recorded["admission"])

    def test_non_waiting_pause_persists_and_never_sleeps(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); state={"plan_hash":"plan-a", "status":"APPROVED"}
            low=provider_codex._normalise_rate_limits(raw_limits(used_primary=96), "gpt-test")
            with (
                mock.patch.object(provider_codex, "rate_limits", return_value=low),
                mock.patch.object(provider_usage.time, "sleep") as sleep,
            ):
                with self.assertRaises(provider_usage.ProviderUsageError):
                    provider_usage.ensure_capacity(root, plan_state=state, model="gpt-test", reserve_percent=5, wait=False, poll_seconds=60)
            sleep.assert_not_called(); self.assertEqual("PAUSE", provider_usage._state_record(root)["pause"]["guard"])

    def test_waiting_path_polls_metadata_only_until_recovered(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); state={"plan_hash":"plan-a", "status":"APPROVED"}
            low=provider_codex._normalise_rate_limits(raw_limits(used_primary=96), "gpt-test")
            high=provider_codex._normalise_rate_limits(raw_limits(used_primary=80), "gpt-test")
            with (
                mock.patch.object(provider_codex, "rate_limits", side_effect=[low, high]) as read,
                mock.patch.object(provider_usage.time, "sleep") as sleep,
            ):
                result=provider_usage.ensure_capacity(root, plan_state=state, model="gpt-test", reserve_percent=5, wait=True, poll_seconds=60)
            self.assertEqual("SAFE", result["guard"]); self.assertEqual(2, read.call_count); sleep.assert_called_once()
            self.assertIsNone(provider_usage._state_record(root)["pause"])

    def test_reset_preview_is_exact_and_redeem_requires_confirmation_and_refresh(self):
        before=provider_codex._normalise_rate_limits(raw_limits(credits=1), None)
        after=provider_codex._normalise_rate_limits(raw_limits(credits=0), None)
        with mock.patch.object(provider_codex, "rate_limits", return_value=before):
            preview=provider_codex.reset_credit_preview(Path("/tmp"), "Operator One")
        self.assertEqual("REDEEM", preview["confirmation"]); self.assertNotIn("must-not-leak", json.dumps(preview))
        with self.assertRaisesRegex(provider_codex.ProviderError, "confirmation"):
            provider_codex.redeem_reset_credit(Path("/tmp"), "Operator One", preview["preview_sha256"], "NO")
        with (
            mock.patch.object(provider_codex, "reset_credit_preview", return_value=preview),
            mock.patch.object(provider_codex, "_app_server_request", return_value={"outcome":"reset"}) as rpc,
            mock.patch.object(provider_codex, "rate_limits", return_value=after),
        ):
            result=provider_codex.redeem_reset_credit(Path("/tmp"), "Operator One", preview["preview_sha256"], "REDEEM")
        self.assertEqual("reset", result["outcome"]); self.assertEqual(0, result["after"]["available_reset_credits"])
        self.assertEqual("account/rateLimitResetCredit/consume", rpc.call_args.args[1])
        self.assertIn("idempotencyKey", rpc.call_args.kwargs["params"]); self.assertNotIn("creditId", rpc.call_args.kwargs["params"])

    def test_stale_reset_preview_refuses_consumption(self):
        first=provider_codex._normalise_rate_limits(raw_limits(credits=1), None)
        second=provider_codex._normalise_rate_limits(raw_limits(used_primary=21, credits=1), None)
        with mock.patch.object(provider_codex, "rate_limits", return_value=first):
            preview=provider_codex.reset_credit_preview(Path("/tmp"), "Operator One")
        with (
            mock.patch.object(provider_codex, "rate_limits", return_value=second),
            mock.patch.object(provider_codex, "_app_server_request") as consume,
        ):
            with self.assertRaisesRegex(provider_codex.ProviderError, "stale"):
                provider_codex.redeem_reset_credit(Path("/tmp"), "Operator One", preview["preview_sha256"], "REDEEM")
        consume.assert_not_called()
    def test_shared_operator_reset_actions_are_metadata_only(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); init_repo(root)
            preview={"schema":provider_codex.RESET_PREVIEW_SCHEMA,"preview_sha256":"a"*64,"confirmation":"REDEEM","available_reset_credits":1}
            result={"schema":provider_codex.RESET_RESULT_SCHEMA,"outcome":"reset"}
            with mock.patch.object(provider_usage, "build_reset_preview", return_value=preview) as bp:
                got=operator.dispatch_action(root, "provider.reset-preview", {"operator":"Operator One"})
            self.assertEqual("a"*64, got["result"]["preview_sha256"]); bp.assert_called_once()
            with mock.patch.object(provider_usage, "redeem_reset", return_value=result) as rr:
                got=operator.dispatch_action(root, "provider.reset-redeem", {"operator":"Operator One","preview":"a"*64,"confirm":"REDEEM"})
            self.assertEqual("reset", got["result"]["outcome"]); rr.assert_called_once()


    def test_canonical_operator_state_surfaces_pause_refresh_reset_and_retry(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); repo=base/"repo"; init_repo(repo)
            with (
                mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog()),
                mock.patch.object(provider_codex, "rate_limits", return_value=safe_rate_limits()),
            ):
                active_reviewed(repo, base/"external")
                approved=approve(repo)
            low=provider_codex._normalise_rate_limits(raw_limits(used_primary=99, credits=1), "gpt-test")
            with mock.patch.object(provider_codex, "rate_limits", return_value=low):
                with self.assertRaises(provider_usage.ProviderUsageError):
                    provider_usage.ensure_capacity(repo, plan_state=approved, model="gpt-test", reserve_percent=5, wait=False, poll_seconds=60)
            snap=operator.operator_snapshot(repo)
            codes=[row.get("code") for row in snap["lifecycle"]["blockers"]]
            actions=[row.get("action") for row in snap["lifecycle"]["next_actions"]]
            self.assertIn("PROVIDER_USAGE_LIMIT", codes)
            self.assertEqual(["provider.usage-refresh", "provider.reset-preview", "scheduler.run-preview", "plan.retire-preview"], actions)
            state=snap["lifecycle"]["provider_usage"]["state"]
            self.assertEqual("PAUSE", state["pause"]["guard"])
            self.assertEqual(1, state["quota"]["available_reset_credits"])

    def test_scheduler_records_usage_stop_not_interrupted_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); repo=base/"repo"; init_repo(repo)
            with (
                mock.patch.object(provider_codex, "model_catalog", return_value=test_catalog()),
                mock.patch.object(provider_codex, "rate_limits", return_value=safe_rate_limits()),
            ):
                active_reviewed(repo, base/"external")
                approved=approve(repo)
                preview=scheduler.build_schedule_preview(repo, "Operator One")
                with mock.patch.object(controller, "run_controller", side_effect=controller.ControllerUsageBlocked("provider usage admission blocked: reserve")):
                    stopped=scheduler.run_schedule(repo, "Operator One", preview["preview_sha256"], "SCHEDULE")
            self.assertEqual("STOPPED_USAGE_LIMIT", stopped["status"])
            self.assertIn("reserve", stopped["stop_reason"])
            self.assertIsNone(stopped.get("turn_before_manifest"))
