"""Round 12 canonical lifecycle Web parity tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import threading
import sys
from unittest import TestCase, mock
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import web  # noqa: E402


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "stygnox-tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Stygnox Tests"], check=True)
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "fixture"], check=True)


class StygnoxWebLifecycleTests(TestCase):
    def test_page_contains_canonical_lifecycle_sections_and_context(self) -> None:
        page = web._index_html("csrf-token").decode("utf-8")
        for label in ("Lifecycle", "Blockers", "Next actions", "Authority &amp; recovery", "Qualification / finalization"):
            self.assertIn(label, page)
        for field_id in (
            "lifecycle-phase", "lifecycle-progress", "lifecycle-attention", "lifecycle-step",
            "lifecycle-plan", "lifecycle-latest-turn", "lifecycle-blockers", "lifecycle-actions",
            "lifecycle-gate", "lifecycle-recovery", "lifecycle-reconciliation",
            "lifecycle-self-development", "lifecycle-qualification", "lifecycle-finalization",
            "lifecycle-efficiency", "lifecycle-usage", "lifecycle-preview", "lifecycle-confirm",
        ):
            self.assertIn(f'id="{field_id}"', page)
        self.assertIn("Only actions listed in <strong>Next actions</strong> are rendered", page)
        self.assertNotIn("onclick=\"stygnoxAction('adopt.preview')\"", page)
        self.assertNotIn("onclick=\"stygnoxAction('transaction.begin')\"", page)
        self.assertNotIn("onclick=\"stygnoxAction('controller.activate')\"", page)

    def test_browser_renders_and_admits_actions_only_from_canonical_next_actions(self) -> None:
        script = (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8")
        self.assertIn("Array.isArray(lifecycle?.next_actions)", script)
        self.assertIn("data-lifecycle-action", script)
        self.assertIn("window.stygnoxLifecycleAction", script)
        self.assertIn("if(!canonical.includes(name))", script)
        self.assertIn("Lifecycle action ${name} is not canonical for the current snapshot", script)
        self.assertIn("renderLifecycle(s.lifecycle || {})", script)

    def test_lifecycle_payload_uses_snapshot_plan_and_gate_identity(self) -> None:
        script = (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8")
        self.assertIn("if(progress.plan_hash) payload.plan_hash=progress.plan_hash", script)
        self.assertIn("if(gate.gate_id) payload.gate_id=gate.gate_id", script)
        self.assertNotIn('id="lifecycle-plan-hash"', web._index_html("csrf").decode("utf-8"))
        self.assertNotIn('id="lifecycle-gate-id"', web._index_html("csrf").decode("utf-8"))
        self.assertIn("self_development_candidates", script)

    def test_preview_actions_have_exact_confirmed_follow_up_pairs(self) -> None:
        script = (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8")
        expected = {
            "recovery.preview": "RESTORE",
            "plan.propose-preview": "PROPOSE",
            "gate.steer-preview": "STEER",
            "gate.resume-preview": "RESUME",
            "gate.resolve-preview": "RESOLVE",
            "scheduler.run-preview": "SCHEDULE",
            "scheduler.recover-preview": "RECOVER",
            "self-development.authorize-preview": "AUTHORIZE",
            "qualification.preview": "QUALIFY",
            "qualification.requalify-preview": "REQUALIFY",
            "finalization.commit-preview": "COMMIT",
            "finalization.push-preview": "PUSH",
        }
        for action, confirmation in expected.items():
            with self.subTest(action=action):
                self.assertIn(f"'{action}'", script)
                self.assertIn(f"'{confirmation}'", script)
        self.assertIn("preview:row.preview,confirm:row.confirm", script)

    def test_web_action_endpoint_delegates_lifecycle_action_to_shared_operator_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            server = web.OperatorServer(("127.0.0.1", 0), repo, auth_record=None)
            self.addCleanup(server.server_close)
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = {"operator": "Operator One", "plan_hash": "abc", "reason": "review"}
            result = {"schema": "stygnox_operator_action_v1", "action": "qualification.preview", "result": {"preview_sha256": "f" * 64}}
            with mock.patch("stygnox.web.dispatch_action", return_value=result) as dispatched:
                body = json.dumps({"action": "qualification.preview", "payload": payload}).encode("utf-8")
                req = Request(base + "/api/action", data=body, headers={"Content-Type": "application/json", "X-Stygnox-CSRF": server.csrf}, method="POST")
                with urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            dispatched.assert_called_once_with(repo, "qualification.preview", payload)

    def test_snapshot_endpoint_returns_canonical_lifecycle_without_web_reclassification(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            snapshot = {
                "schema": "stygnox_operator_surface_v1", "snapshot_version": 2,
                "lifecycle": {"schema": "stygnox_operator_lifecycle_v1", "phase": "READY_TO_COMMIT", "blockers": [], "next_actions": [{"action": "finalization.commit-preview", "reason": "qualified"}]},
                "next_actions": [{"action": "finalization.commit-preview", "reason": "qualified"}],
            }
            server = web.OperatorServer(("127.0.0.1", 0), repo, auth_record=None)
            self.addCleanup(server.server_close)
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with mock.patch("stygnox.web.operator_snapshot", return_value=snapshot):
                with urlopen(base + "/api/snapshot", timeout=3) as response:
                    value = json.loads(response.read().decode("utf-8"))
            self.assertEqual(snapshot, value)

    def test_existing_auth_csrf_and_polling_boundaries_remain_in_place(self) -> None:
        script = (SRC / "stygnox/web_assets/operator.js").read_text(encoding="utf-8")
        source = (SRC / "stygnox/web.py").read_text(encoding="utf-8")
        self.assertIn("'X-Stygnox-CSRF':state.csrf", script)
        self.assertIn("setInterval(refresh,5000)", script)
        self.assertIn('self.headers.get("X-Stygnox-CSRF") != self.server.csrf', source)
        self.assertIn("if not self._authorized()", source)


if __name__ == "__main__":
    import unittest
    unittest.main()
