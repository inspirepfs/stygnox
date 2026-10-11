"""Standalone contract tests for the reviewed recovery module.

Production full-repo tests must ALSO pass after isolated installation.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "src" / "stygnox" / "direct_interruption.py"
if not SOURCE.exists():
    SOURCE = BASE / "direct_interruption.py"

def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def record(v, key="record_sha256"):
    r = dict(v)
    r[key] = digest(r)
    return r

class Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "worktree"
        self.root.mkdir()
        (self.root / ".stygnox").mkdir()
        for d in ("src/stygnox", "tests"):
            (self.root / d).mkdir(parents=True)
        tracked = ["src/stygnox/transactions.py", "src/stygnox/planning.py", "src/stygnox/scheduler.py", "stygnox.toml", "tests/tracked.py"]
        for p in tracked:
            (self.root / p).write_text("original\n")
        for args in [["git", "init", "-q"], ["git", "config", "user.name", "Test"],
                     ["git", "config", "user.email", "test@example.com"], ["git", "add", "."],
                     ["git", "commit", "-q", "-m", "start"]]:
            subprocess.run(args, cwd=self.root, check=True, capture_output=True)
        (self.root / ".git" / "info" / "exclude").write_text(".stygnox/\n")
        self.dirty = ["src/stygnox/transactions.py", "src/stygnox/planning.py", "src/stygnox/scheduler.py", "stygnox.toml", "tests/test_stygnox_transaction_renewal.py"]
        for name in self.dirty:
            (self.root / name).write_text("modified\n")
        # Realistic immutable approval manifest: operator-owned config was already
        # dirty before the interrupted turn. An accepted scoped turn changes only
        # the transaction source; the failed turn changes the remaining sources.
        def fingerprint(content):
            return hashlib.sha256(content.encode()).hexdigest()
        approved = {p: fingerprint("original\n") for p in tracked}
        approved["stygnox.toml"] = fingerprint("modified\n")
        prior = dict(approved)
        prior["src/stygnox/transactions.py"] = fingerprint("accepted\n")
        scope = sorted(p for p in self.dirty if p != "stygnox.toml")
        self.plan_hash = "a" * 64
        self.tx = record({"state": "ACTIVE", "transaction_id": "TX-1", "operator": "alice"})
        self.ctrl = record({"enabled": True, "transaction_id": "TX-1", "operator": "alice"})
        self.plan = record({"status": "APPROVED", "execution_authority_granted": True,
            "plan_hash": self.plan_hash, "current_step": 2, "transaction_id": "TX-1", "operator": "alice",
            "controller_record_sha256": self.ctrl["record_sha256"],
            "transaction_record_sha256": self.tx["record_sha256"],
            "approval_baseline_sha256": "b"*64,
            "step_authority_baseline_sha256": "b"*64,
            "repository_mutation_scope_sha256": digest(scope),
            "repository_mutation_scope": scope,
            "approval_repository_manifest": approved,
            "active_gate": None, "self_development_grant": None,
            "tracked_config_sha256": "e"*64, "review_sha256": "f"*64,
            "plan": {"repository_mutation_scope": scope,
                     "repository_mutation_scope_sha256": digest(scope),
                     "steps": [{"test_change_policy": "add-only"} for _ in range(2)]},
            "step_results": []
        })
        self.accepted_origin = "1" * 64
        delta = {"before_manifest_sha256": digest(approved),
                 "after_manifest_sha256": digest(prior),
                 "paths": [{"path": "src/stygnox/transactions.py", "kind": "modified",
                            "before_fingerprint": approved["src/stygnox/transactions.py"],
                            "after_fingerprint": prior["src/stygnox/transactions.py"]}]}
        delta["delta_sha256"] = digest(delta)
        self.accepted = record({"schema": "stygnox_controller_run_result_v1",
            "preview_sha256": self.accepted_origin,
            "next_action": "continue-same-step", "before_baseline_sha256": "b"*64, "after_baseline_sha256": "b"*64,
            "transaction_id": "TX-1", "repository_authority": "write",
            "human_gate": None, "provider_result": {"status": "PASS"},
            "plan_binding": {"plan_hash": self.plan_hash, "current_step": 2,
                             "repository_mutation_scope": scope,
                             "repository_mutation_scope_sha256": digest(scope)},
            "actual_delta": delta})
        (self.root / ".stygnox" / f"controller-run-{self.accepted_origin[:16]}.json").write_text(json.dumps(self.accepted))
        self.plan["continuation_history"] = [record({"plan_hash": self.plan_hash, "step": 2,
            "origin_preview_sha256": self.accepted_origin, "before_baseline_sha256": "b"*64, "after_baseline_sha256": "b"*64})]
        self.plan = record({k:v for k,v in self.plan.items() if k != "record_sha256"})
        self.origin = record({
            "plan_binding": {"plan_hash": self.plan_hash, "plan_record_sha256": self.plan["record_sha256"],
                "current_step": 2, "approval_baseline_sha256": "b"*64,
            "step_authority_baseline_sha256": "b"*64,
                "repository_mutation_scope_sha256": self.plan["repository_mutation_scope_sha256"],
                "repository_mutation_scope": self.plan["repository_mutation_scope"]},
            "transaction_id": "TX-1", "controller_record_sha256": self.ctrl["record_sha256"],
            "operator": "alice", "worktree": str(self.root), "repository_authority": "write",
            "project_baseline": {"sha256": "b"*64}, "scheduler_authority": None,
            "tracked_config_sha256": "e"*64, "review_sha256": "f"*64,
        }, "preview_sha256")
        self.origin_file = Path(self.temp.name) / "original.json"
        self.origin_file.write_text(json.dumps(self.origin))
        self.modules = {}
        for sub in ("adoption", "controller", "planning", "scheduler", "self_development", "transactions", "qualification", "direct_interruption_handoff"):
            self.modules[sub] = types.ModuleType("stygnox." + sub)
        pkg = types.ModuleType("stygnox")
        pkg.__path__ = [str(BASE / "src" / "stygnox")]
        for k,v in self.modules.items():
            setattr(pkg,k,v)
        self.oldmodules = {k:sys.modules.get(k) for k in ["stygnox", "stygnox.direct_interruption", *["stygnox." + x for x in self.modules]]}
        sys.modules["stygnox"] = pkg
        for k,v in self.modules.items():
            sys.modules["stygnox." + k] = v
        spec = importlib.util.spec_from_file_location("stygnox.direct_interruption", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules["stygnox.direct_interruption"] = self.module
        spec.loader.exec_module(self.module)
        self.addCleanup(self.restore_modules)
        m = self.modules
        # Synthetic Stage A lifecycle tests explicitly mock the Stage C gate.
        # Real installed mutation refuses until old-controller fencing is proved.
        m["direct_interruption_handoff"].require_mutation_authority = lambda root: None
        m["direct_interruption_handoff"].HandoffRefused = type("HandoffRefused", (RuntimeError,), {})
        m["qualification"].replay_human_reviewed_interruption = lambda *args, **kwargs: None
        m["qualification"]._DIRECT_INTERRUPTION_REPLAY_V1 = True
        m["adoption"].RUNTIME_NAME = ".stygnox"
        m["adoption"].resolve_worktree = lambda p: Path(p).resolve()
        m["adoption"].capture_baseline = lambda p: types.SimpleNamespace(public=lambda: {"sha256":"d"*64})
        m["adoption"].write_runtime_record = lambda root, name, obj, actor: (Path(root)/".stygnox"/name).write_text(json.dumps(obj))
        m["planning"]._record = lambda p: self.plan
        m["planning"]._validate_plan = lambda p: p
        m["planning"]._write = self.plan_write
        m["transactions"]._transaction = lambda p: self.tx
        m["controller"]._controller = lambda p: self.ctrl
        m["controller"]._policy_status = lambda p: {"approved":True, "tracked_config_sha256":"e"*64, "review":{"review_sha256":"f"*64}}
        m["scheduler"].scheduler_status = lambda p: {"scheduler": {"status": "PAUSED_MAX_LOOPS"}}
        m["scheduler"].repository_manifest = lambda p: {q: hashlib.sha256((self.root/q).read_bytes()).hexdigest() for q in sorted(set(tracked + self.dirty))}
        m["self_development"].normalize_path = lambda s: s.replace("\\","/")
        m["self_development"].is_secret_path = lambda p: False
        m["self_development"].is_runtime_or_protected = lambda p: p == "stygnox.toml" or p.startswith(".stygnox/")

    def restore_modules(self):
        for k,v in self.oldmodules.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def plan_write(self, root, body):
        self.plan = record({k:v for k,v in body.items() if k != "record_sha256"})
        return self.plan

    def preview(self):
        return self.module.review_preview(self.root, self.origin_file, self.origin["preview_sha256"], self.dirty)

    def adopt(self):
        p = self.preview()
        return self.module.adopt(self.root, self.origin_file, self.origin["preview_sha256"], self.dirty,
            "I reviewed all five exact paths and accept uncertainty about pre-turn config", p["preview_sha256"], "ADOPT_UNATTRIBUTED_WORK")

    def test_review_preview_bound_to_original_and_all_files(self):
        p = self.preview()
        self.assertEqual(p["candidate_baseline_sha256"], "d"*64)
        self.assertEqual(set(p["reviewed_file_sha256"]), set(self.dirty))
        self.assertEqual(p["operator_config_preturn_status"], "UNCHANGED_PROVED_BY_RECEIPT_CHAIN")
        self.assertEqual(len(p["manifest_proof"]["changed_paths"]), 4)
        self.assertFalse(p["past_provider_success"])
        self.assertEqual(p["last_accepted_manifest_sha256"], self.accepted["actual_delta"]["after_manifest_sha256"])

    def test_missing_last_accepted_receipt_refused(self):
        (self.root / ".stygnox" / f"controller-run-{self.accepted_origin[:16]}.json").unlink()
        with self.assertRaisesRegex(self.module.RecoveryRefused, "evidence"):
            self.preview()

    def test_policy_drift_refused(self):
        self.modules["controller"]._policy_status = lambda p: {"approved":True, "tracked_config_sha256":"0"*64, "review":{"review_sha256":"f"*64}}
        with self.assertRaisesRegex(self.module.RecoveryRefused, "config binding drifted"):
            self.preview()

    def test_interrupted_scheduler_refused(self):
        self.modules["scheduler"].scheduler_status = lambda p: {"scheduler":{"status":"INTERRUPTED"}}
        with self.assertRaisesRegex(self.module.RecoveryRefused, "scheduler authority"):
            self.preview()

    def test_missing_approval_manifest_refused(self):
        self.plan["approval_repository_manifest"] = None
        self.plan = record({k:v for k,v in self.plan.items() if k != "record_sha256"})
        binding = dict(self.origin["plan_binding"])
        binding["plan_record_sha256"] = self.plan["record_sha256"]
        self.origin["plan_binding"] = binding
        self.origin = record({k:v for k,v in self.origin.items() if k != "preview_sha256"}, "preview_sha256")
        self.origin_file.write_text(json.dumps(self.origin))
        with self.assertRaisesRegex(self.module.RecoveryRefused, "approval-time manifest"):
            self.preview()

    def test_wrong_original_digest_refused(self):
        with self.assertRaisesRegex(self.module.RecoveryRefused, "known digest"):
            self.module.review_preview(self.root, self.origin_file, "0"*64, self.dirty)

    def test_tampered_original_refused(self):
        tampered = dict(self.origin, operator="mallory")
        self.origin_file.write_text(json.dumps(tampered))
        with self.assertRaisesRegex(self.module.RecoveryRefused, "integrity"):
            self.preview()

    def test_operator_configuration_requires_explicit_review(self):
        with self.assertRaisesRegex(self.module.RecoveryRefused, "exact Git-dirty"):
            self.module.review_preview(self.root, self.origin_file, self.origin["preview_sha256"], [p for p in self.dirty if p != "stygnox.toml"])

    def test_extra_path_refused(self):
        (self.root / "evil.py").write_text("bad")
        with self.assertRaisesRegex(self.module.RecoveryRefused, "exact Git-dirty"):
            self.preview()

    def test_existing_approval_test_refused(self):
        self.plan["approval_repository_manifest"]["tests/test_stygnox_transaction_renewal.py"] = hashlib.sha256(b"preexisting-test").hexdigest()
        self.plan = record({k:v for k,v in self.plan.items() if k != "record_sha256"})
        binding = dict(self.origin["plan_binding"])
        binding["plan_record_sha256"] = self.plan["record_sha256"]
        self.origin["plan_binding"] = binding
        self.origin = record({k:v for k,v in self.origin.items() if k != "preview_sha256"}, "preview_sha256")
        self.origin_file.write_text(json.dumps(self.origin))
        with self.assertRaisesRegex(self.module.RecoveryRefused, "approval-time existing"):
            self.preview()

    def test_missing_authoritative_qualification_replay_blocks_adoption(self):
        delattr(self.modules["qualification"], "replay_human_reviewed_interruption")
        p = self.preview()
        with self.assertRaisesRegex(self.module.RecoveryRefused, "authority mutation disabled"):
            self.module.adopt(self.root, self.origin_file, self.origin["preview_sha256"], self.dirty,
                              "reviewed", p["preview_sha256"], "ADOPT_UNATTRIBUTED_WORK")
        self.assertEqual(self.plan["status"], "APPROVED")
        self.assertFalse(list((self.root / ".stygnox").glob("direct-interruption-*-intent.json")))

    def test_stale_preview_cannot_quarantine(self):
        with self.assertRaisesRegex(self.module.RecoveryRefused, "stale"):
            self.module.adopt(self.root, self.origin_file, self.origin["preview_sha256"], self.dirty,
                "reviewed", "0"*64, "ADOPT_UNATTRIBUTED_WORK")
        self.assertEqual(self.plan["status"], "APPROVED")

    def test_adopt_quarantines_authority_without_fabricating_success(self):
        r = self.adopt()
        self.assertEqual(r["result"], "RECOVERY_QUARANTINED_AWAITING_TESTS")
        self.assertFalse(self.plan["execution_authority_granted"])
        self.assertEqual(self.plan["status"], self.module.PENDING)
        self.assertTrue((self.root/".stygnox"/("direct-interruption-"+self.origin["preview_sha256"][:16]+"-intent.json")).is_file())

    def test_quarantined_candidate_mutation_refused(self):
        self.adopt()
        (self.root / "src/stygnox/transactions.py").write_text("later mutation")
        with self.assertRaisesRegex(self.module.RecoveryRefused, "baseline|manifest|reviewed"):
            self.module.release_preview(self.root, self.origin["preview_sha256"])

    def test_cannot_release_without_qualification(self):
        self.adopt()
        with self.assertRaisesRegex(self.module.RecoveryRefused, "missing or non-regular evidence"):
            self.module.release_preview(self.root, self.origin["preview_sha256"])

    def test_release_requires_explicit_confirmation_and_preserves_failed_origin(self):
        self.adopt()
        preview = self.module._pending(self.root, self.origin["preview_sha256"])
        root, state, intent, saved, prefix = preview
        qual = {"schema": self.module.TEST_SCHEMA, "intent_record_sha256": intent["record_sha256"],
            "plan_record_sha256": state["record_sha256"], "candidate_baseline_sha256": saved["candidate_baseline_sha256"],
            "origin_preview_sha256": self.origin["preview_sha256"], "exit_code": 0,
            "test_files": list(self.module.QUALIFICATION_FILES)}
        self.module._write(root, prefix + "-qualification.json", qual)
        rp = self.module.release_preview(root, self.origin["preview_sha256"])
        with self.assertRaisesRegex(self.module.RecoveryRefused, "explicit"):
            self.module.release(root, self.origin["preview_sha256"], rp["preview_sha256"], "RELEASE")
        # C3a closes the latent legacy-release path: even a mocked C1 gate
        # cannot permit APPROVED/True to be republished by the old controller.
        # The separately qualified successor protocol is not yet installed.
        with self.assertRaisesRegex(RuntimeError, "not hostile-qualified"):
            self.module.release(root, self.origin["preview_sha256"], rp["preview_sha256"], "RELEASE_REVIEWED_WORK")
        self.assertEqual(self.plan["status"], self.module.PENDING)
        self.assertFalse(self.plan["execution_authority_granted"])
        self.assertEqual(self.plan["direct_interruption_pending"]["origin_preview_sha256"], self.origin["preview_sha256"])
        self.assertFalse((root / '.stygnox' / (prefix + '-release.json')).exists())
        self.assertFalse(self.plan.get('direct_interruption_recoveries'))

if __name__ == "__main__":
    unittest.main()
