"""Exceptional, human-reviewed adoption of retained work from a failed *direct* turn.

This is NOT controller PASS and does not issue retrospective self-development grants.
An explicit human review chooses a new authority basis for the observed complete
working tree. The review first quarantines the plan, then requires independent
regression tests before releasing the revised same-step checkpoint.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from . import adoption, controller, planning, scheduler, self_development, transactions

SCHEMA = "stygnox_direct_interruption_review_v1"
INTENT_SCHEMA = "stygnox_direct_interruption_intent_v1"
TEST_SCHEMA = "stygnox_direct_interruption_test_evidence_v1"
RELEASE_SCHEMA = "stygnox_direct_interruption_release_v1"
PENDING = "INTERRUPTION_REVIEW_QUALIFICATION_REQUIRED"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SPECIAL_CONFIG = "stygnox.toml"
QUALIFICATION_FILES = (
    "tests/test_stygnox_transaction_renewal.py",
    "tests/test_stygnox_transactions.py",
    "tests/test_stygnox_planning.py",
    "tests/test_stygnox_scheduler.py",
    "tests/test_stygnox_plan_retirement.py",
    "tests/test_stygnox_r3d_upgrade_rebind.py",
)

class RecoveryRefused(RuntimeError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _checked(record: object, key: str = "record_sha256") -> dict[str, Any]:
    if not isinstance(record, dict):
        raise RecoveryRefused("required authority record is not an object")
    value = record.get(key)
    body = dict(record)
    body.pop(key, None)
    if not isinstance(value, str) or not HEX64.fullmatch(value) or _digest(body) != value:
        raise RecoveryRefused(f"{key} integrity check failed")
    return record


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RecoveryRefused(f"missing or non-regular evidence: {path}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryRefused(f"invalid evidence: {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise RecoveryRefused("evidence must be a JSON object")
    return result


def _runtime(root: Path, name: str) -> Path:
    return root / adoption.RUNTIME_NAME / name


def _record(root: Path, name: str, schema: str) -> dict[str, Any]:
    value = _checked(_read_json(_runtime(root, name)))
    if value.get("schema") != schema:
        raise RecoveryRefused(f"unexpected schema in {name}")
    return value


def _write(root: Path, name: str, value: dict[str, Any]) -> dict[str, Any]:
    record = dict(value)
    record.pop("record_sha256", None)
    record["record_sha256"] = _digest(record)
    adoption.write_runtime_record(root, name, record, actor="controller")
    return record


def _git_paths(root: Path) -> list[str]:
    p = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z"], capture_output=True)
    if p.returncode:
        raise RecoveryRefused(f"Git status failed: {p.stderr[-1000:]!r}")
    fields = p.stdout.split(b"\0")
    result = []
    i = 0
    while i < len(fields):
        raw = fields[i]
        i += 1
        if not raw:
            continue
        if len(raw) < 4 or raw[2:3] != b" ":
            raise RecoveryRefused("unexpected Git porcelain status")
        status = raw[:2].decode("ascii", errors="replace")
        result.append(os.fsdecode(raw[3:]))
        if "R" in status or "C" in status:
            if i >= len(fields):
                raise RecoveryRefused("missing Git rename source")
            result.append(os.fsdecode(fields[i]))
            i += 1
    return sorted(set(result))


def _path_hash(root: Path, rel: str) -> str:
    p = root / rel
    if not p.is_file() or p.is_symlink():
        raise RecoveryRefused(f"reviewed paths must be regular existing files: {rel}")
    if not p.resolve().is_relative_to(root):
        raise RecoveryRefused(f"review path escapes worktree: {rel}")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _safe_paths(root: Path, state: Mapping[str, Any], exact_paths: Sequence[str]) -> dict[str, str]:
    dirty = _git_paths(root)
    reviewed = sorted(exact_paths)
    if not reviewed or len(set(reviewed)) != len(reviewed) or dirty != reviewed:
        raise RecoveryRefused(f"reviewed paths must equal exact Git-dirty paths: dirty={dirty!r}, reviewed={reviewed!r}")
    scope = set(planning._validate_plan(state["plan"])["repository_mutation_scope"])
    approval_manifest = state.get("approval_repository_manifest")
    if not isinstance(approval_manifest, dict):
        raise RecoveryRefused("immutable approval-time manifest is absent")
    result: dict[str, str] = {}
    for rel in reviewed:
        canonical = self_development.normalize_path(rel)
        if (canonical != rel or self_development.is_secret_path(rel)
            or (rel != SPECIAL_CONFIG and self_development.is_runtime_or_protected(rel))):
            raise RecoveryRefused(f"unsafe reviewed path: {rel}")
        if rel != SPECIAL_CONFIG and rel not in scope:
            raise RecoveryRefused(f"dirty path outside approved scope: {rel}")
        if rel.startswith("tests/") and rel in approval_manifest:
            raise RecoveryRefused(f"approval-time existing test cannot be retrospectively adopted: {rel}")
        if rel == SPECIAL_CONFIG and rel not in dirty:
            raise RecoveryRefused("operator configuration not in observed status")
        result[rel] = _path_hash(root, rel)
    return result


def _quiescent(root: Path) -> None:
    sched = scheduler.scheduler_status(root).get("scheduler")
    if isinstance(sched, Mapping) and sched.get("status") in {"RUNNING", "TURN_RUNNING", "INTERRUPTED"}:
        raise RecoveryRefused("active or interrupted scheduler authority blocks recovery")


def _identity(root: Path, state: Mapping[str, Any], origin: Mapping[str, Any]) -> dict[str, Any]:
    # The preview file is operator-held evidence. Exact preview digest MUST be
    # independently checked against the known preview from the failed run.
    preview = _checked(dict(origin), "preview_sha256")
    binding = preview.get("plan_binding")
    if not isinstance(binding, Mapping):
        raise RecoveryRefused("missing original approved-plan binding")
    tx = _checked(transactions._transaction(root))
    active = _checked(controller._controller(root))
    policy_status = controller._policy_status(root)
    if not policy_status.get("approved"):
        raise RecoveryRefused("execution policy is not currently reviewed")
    if (policy_status.get("tracked_config_sha256") != preview.get("tracked_config_sha256")
        or policy_status.get("tracked_config_sha256") != state.get("tracked_config_sha256")
        or (policy_status.get("review") or {}).get("review_sha256") != preview.get("review_sha256")
        or (policy_status.get("review") or {}).get("review_sha256") != state.get("review_sha256")):
        raise RecoveryRefused("reviewed execution-policy/config binding drifted since the failed preview")
    if tx.get("state") != "ACTIVE" or active.get("enabled") is not True:
        raise RecoveryRefused("predecessor transaction/controller no longer active")
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise RecoveryRefused("expected unchanged APPROVED predecessor checkpoint")
    if state.get("active_gate") is not None or state.get("self_development_grant") is not None:
        raise RecoveryRefused("open human gate or self-development grant blocks recovery")
    if int(state.get("current_step") or 0) != int(binding.get("current_step") or -1):
        raise RecoveryRefused("predecessor step mismatch")
    if (
        state.get("plan_hash") != binding.get("plan_hash")
        or state.get("record_sha256") != binding.get("plan_record_sha256")
        or state.get("transaction_id") != tx.get("transaction_id")
        or tx.get("transaction_id") != preview.get("transaction_id")
        or active.get("transaction_id") != tx.get("transaction_id")
        or active.get("record_sha256") != preview.get("controller_record_sha256")
        or state.get("controller_record_sha256") != active.get("record_sha256")
        or state.get("transaction_record_sha256") != tx.get("record_sha256")
        or state.get("operator") != preview.get("operator")
        or state.get("operator") != active.get("operator")
        or state.get("operator") != tx.get("operator")
        or preview.get("worktree") != str(root)
        or preview.get("repository_authority") != "write"
        or binding.get("repository_mutation_scope_sha256") != state.get("repository_mutation_scope_sha256")
        or binding.get("repository_mutation_scope") != state.get("repository_mutation_scope")
        or binding.get("step_authority_baseline_sha256") != state.get("step_authority_baseline_sha256")
        or (preview.get("project_baseline") or {}).get("sha256") != state.get("step_authority_baseline_sha256")
    ):
        raise RecoveryRefused("original provider preview is not bound to live predecessor authority")
    if preview.get("scheduler_authority") is not None:
        raise RecoveryRefused("direct interruption origin unexpectedly belongs to a scheduler")
    _quiescent(root)
    # The last accepted continuation is the only trustworthy predecessor to
    # the interrupted direct turn. Bind its exact controller receipt and the
    # *hash* of its after-manifest. Do not pretend we have the full manifest.
    history = state.get("continuation_history")
    if not isinstance(history, list) or not history or not isinstance(history[-1], dict):
        raise RecoveryRefused("accepted same-step continuation evidence is missing")
    last = _checked(history[-1])
    origin_preview = last.get("origin_preview_sha256")
    if not isinstance(origin_preview, str) or not HEX64.fullmatch(origin_preview):
        raise RecoveryRefused("last accepted continuation has no exact origin")
    accepted = _checked(_read_json(_runtime(root, f"controller-run-{origin_preview[:16]}.json")))
    delta = accepted.get("actual_delta")
    if (accepted.get("preview_sha256") != origin_preview
        or accepted.get("next_action") != "continue-same-step"
        or accepted.get("after_baseline_sha256") != state["step_authority_baseline_sha256"]
        or last.get("after_baseline_sha256") != state["step_authority_baseline_sha256"]
        or not isinstance(delta, dict)
        or not isinstance(delta.get("after_manifest_sha256"), str)
        or not HEX64.fullmatch(delta["after_manifest_sha256"])):
        raise RecoveryRefused("last accepted controller continuation is missing or inconsistent")
    return {"plan_record_sha256": state["record_sha256"],
            "controller_record_sha256": active["record_sha256"],
            "transaction_record_sha256": tx["record_sha256"],
            "last_accepted_controller_receipt_sha256": accepted["record_sha256"],
            "last_accepted_manifest_sha256": delta["after_manifest_sha256"]}


def review_preview(project: Path, origin_file: Path, expected_preview: str, reviewed_paths: Sequence[str]) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    if expected_preview is None or not HEX64.fullmatch(expected_preview):
        raise RecoveryRefused("exact known 64-character origin preview digest required")
    state = _checked(planning._record(root))
    origin = _read_json(origin_file)
    if origin.get("preview_sha256") != expected_preview:
        raise RecoveryRefused("origin preview does not match known digest from failed turn")
    identity = _identity(root, state, origin)
    receipt_name = f"controller-run-{expected_preview[:16]}.json"
    if _runtime(root, receipt_name).exists():
        raise RecoveryRefused("controller receipt already exists; use normal receipt recovery")
    prefix = f"direct-interruption-{expected_preview[:16]}"
    if any(_runtime(root, prefix + suffix).exists() for suffix in ("-intent.json", "-qualification.json", "-release.json", "-predecessor-plan.json")):
        raise RecoveryRefused("this origin already has durable recovery evidence")
    manifest = scheduler.repository_manifest(root)
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") == state.get("step_authority_baseline_sha256"):
        raise RecoveryRefused("no interrupted baseline drift to review")
    hashes = _safe_paths(root, state, reviewed_paths)
    body = {
        "schema": SCHEMA,
        "operator": state["operator"],
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "current_step": state["current_step"],
        "transaction_id": state["transaction_id"],
        **identity,
        "origin_preview_sha256": expected_preview,
        "predecessor_baseline_sha256": state["step_authority_baseline_sha256"],
        "candidate_baseline_sha256": current["sha256"],
        "candidate_manifest_sha256": _digest(manifest),
        "candidate_manifest": manifest,
        "approval_manifest_sha256": _digest(state["approval_repository_manifest"]),
        "reviewed_file_sha256": hashes,
        "operator_config_preturn_status": "UNKNOWN_NOT_PROVED",
        "past_provider_success": False,
        "past_self_development_grant": False,
        "provenance_classification": "HUMAN_REVIEWED_UNATTRIBUTED_INTERRUPTED_WORK",
        "new_execution_authority": False,
        "confirmation": "ADOPT_UNATTRIBUTED_WORK",
    }
    # Show the operator the REAL changed source/test set and the proven
    # predecessor before obtaining their digest-bound adoption confirmation.
    from . import direct_interruption_attribution as attribution
    candidate = {**body, "preview_sha256": _digest(body)}
    try:
        proof = attribution.prove_review(root, state, candidate)
    except attribution.AttributionRefused as exc:
        raise RecoveryRefused(str(exc)) from exc
    body["manifest_proof"] = proof
    body["operator_config_preturn_status"] = "UNCHANGED_PROVED_BY_RECEIPT_CHAIN"
    body["preview_sha256"] = _digest(body)
    return body


def _require_qualification_replay() -> None:
    # Fail-closed: merely accepting a new current-step baseline is insufficient.
    # Authoritative qualification MUST replay the exceptional human-reviewed
    # manifest transition as a DISTINCT attribution, in addition to accepted
    # controller receipts. That integration is a separately reviewed patch.
    from . import qualification
    if not callable(getattr(qualification, "replay_human_reviewed_interruption", None)) or not getattr(qualification, "_DIRECT_INTERRUPTION_REPLAY_V1", False):
        raise RecoveryRefused(
            "authority mutation disabled: reviewed-interruption manifest replay "
            "is not integrated into authoritative qualification"
        )


def adopt(project: Path, origin_file: Path, expected_preview: str, reviewed_paths: Sequence[str],
          reason: str, preview_sha256: str, confirm: str) -> dict[str, Any]:
    _require_qualification_replay()
    if confirm != "ADOPT_UNATTRIBUTED_WORK":
        raise RecoveryRefused("explicit --confirm ADOPT_UNATTRIBUTED_WORK required")
    if not reason or not reason.strip() or len(reason) > 1200:
        raise RecoveryRefused("human review reason required (max 1200 characters)")
    preview = review_preview(project, origin_file, expected_preview, reviewed_paths)
    if preview["preview_sha256"] != preview_sha256:
        raise RecoveryRefused("review preview stale; no state mutated")
    root = Path(preview["worktree"])
    state = planning._record(root)
    # A human may approve only a fully reconstructed and independently checked
    # predecessor -> candidate manifest transition, not simply dirty file names.
    from . import direct_interruption_attribution as attribution
    try:
        manifest_proof = attribution.prove_review(root, state, preview)
    except attribution.AttributionRefused as exc:
        raise RecoveryRefused(str(exc)) from exc
    if manifest_proof != preview.get("manifest_proof"):
        raise RecoveryRefused("human-reviewed preview manifest proof is stale")
    prefix = f"direct-interruption-{expected_preview[:16]}"
    intent_body = {
        "schema": INTENT_SCHEMA,
        "review_preview": preview,
        "manifest_proof": manifest_proof,
        "human_reason": " ".join(reason.split()),
        "operator_config_not_proved": True,
        "operator_review_is_new_authority_not_retroactive_grant": True,
        "adopted_at": _now(),
    }
    # Preserve exact predecessor before blocking execution. Interruptions between
    # these writes remain fail-closed from baseline drift; they are NOT auto-healed.
    _write(root, prefix + "-predecessor-plan.json", {"schema": "stygnox_direct_interruption_predecessor_plan_v1", "original_plan": state})
    intent = _write(root, prefix + "-intent.json", intent_body)
    frozen = dict(state)
    frozen["status"] = PENDING
    frozen["execution_authority_granted"] = False
    frozen["direct_interruption_pending"] = {
        "intent_record_sha256": intent["record_sha256"],
        "origin_preview_sha256": expected_preview,
        "previous_plan_record_sha256": state["record_sha256"],
        "candidate_baseline_sha256": preview["candidate_baseline_sha256"],
    }
    written = planning._write(root, frozen)
    return {"result": "RECOVERY_QUARANTINED_AWAITING_TESTS", "plan_record_sha256": written["record_sha256"],
            "intent_record_sha256": intent["record_sha256"], "current_step": written["current_step"],
            "execution_authority_granted": False}


def _pending(project: Path, expected_preview: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], str]:
    if not HEX64.fullmatch(expected_preview):
        raise RecoveryRefused("invalid origin preview digest")
    root = adoption.resolve_worktree(project)
    state = _checked(planning._record(root))
    prefix = f"direct-interruption-{expected_preview[:16]}"
    intent = _record(root, prefix + "-intent.json", INTENT_SCHEMA)
    saved = intent.get("review_preview")
    if not isinstance(saved, dict) or saved.get("preview_sha256") != _digest({k:v for k,v in saved.items() if k != "preview_sha256"}):
        raise RecoveryRefused("stored review preview failed integrity check")
    if (
        saved.get("origin_preview_sha256") != expected_preview
        or state.get("status") != PENDING
        or state.get("execution_authority_granted") is not False
        or state.get("active_gate") is not None
        or state.get("self_development_grant") is not None
        or not isinstance(state.get("direct_interruption_pending"), dict)
        or state["direct_interruption_pending"].get("intent_record_sha256") != intent["record_sha256"]
        or state["direct_interruption_pending"].get("previous_plan_record_sha256") != saved["plan_record_sha256"]
        or state.get("plan_hash") != saved.get("plan_hash")
        or state.get("transaction_id") != saved.get("transaction_id")
        or state.get("current_step") != saved.get("current_step")
    ):
        raise RecoveryRefused("quarantined plan does not match human-reviewed interruption")
    _quiescent(root)
    current = adoption.capture_baseline(root).public()
    if current["sha256"] != saved["candidate_baseline_sha256"]:
        raise RecoveryRefused("candidate baseline changed after quarantine")
    if (_digest(scheduler.repository_manifest(root)) != saved["candidate_manifest_sha256"]
        or saved.get("candidate_manifest") != scheduler.repository_manifest(root)):
        raise RecoveryRefused("reviewed repository manifest changed after quarantine")
    if _git_paths(root) != sorted(saved["reviewed_file_sha256"]):
        raise RecoveryRefused("dirty reviewed path set changed")
    for rel, sha in saved["reviewed_file_sha256"].items():
        if _path_hash(root, rel) != sha:
            raise RecoveryRefused(f"reviewed file changed after quarantine: {rel}")
    tx = _checked(transactions._transaction(root))
    active = _checked(controller._controller(root))
    policy_status = controller._policy_status(root)
    predecessor = _record(root, prefix + "-predecessor-plan.json", "stygnox_direct_interruption_predecessor_plan_v1")
    old_plan = _checked(predecessor.get("original_plan"))
    from . import direct_interruption_attribution as attribution
    try:
        full_proof = attribution.prove_review(root, old_plan, saved)
    except attribution.AttributionRefused as exc:
        raise RecoveryRefused(str(exc)) from exc
    if (full_proof != intent.get("manifest_proof")
        or full_proof != saved.get("manifest_proof")):
        raise RecoveryRefused("quarantined source proof or accepted receipt chain is stale")
    if (old_plan.get("record_sha256") != saved["plan_record_sha256"]
        or tx.get("record_sha256") != saved["transaction_record_sha256"]
        or active.get("record_sha256") != saved["controller_record_sha256"]
        or tx.get("state") != "ACTIVE"
        or active.get("enabled") is not True
        or not policy_status.get("approved")
        or policy_status.get("tracked_config_sha256") != old_plan.get("tracked_config_sha256")
        or (policy_status.get("review") or {}).get("review_sha256") != old_plan.get("review_sha256")):
        raise RecoveryRefused("predecessor controller, transaction or execution policy changed during quarantine")
    return root, state, intent, saved, prefix


def qualify(project: Path, expected_preview: str, test_python: Path) -> dict[str, Any]:
    _require_qualification_replay()
    root, state, intent, saved, prefix = _pending(project, expected_preview)
    if _runtime(root, prefix + "-qualification.json").exists():
        raise RecoveryRefused("qualification receipt already exists")
    py = test_python.resolve()
    if not py.is_file() or root == py or root in py.parents:
        raise RecoveryRefused("test Python must resolve outside target worktree")
    for rel in QUALIFICATION_FILES:
        if not (root / rel).is_file():
            raise RecoveryRefused(f"required regression test missing: {rel}")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{root / 'tests'}:{root / 'src'}"
    guarded_test_runner = r"""
import os, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
protected = root / ".stygnox"
def unsafe(path):
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    try:
        p = pathlib.Path(os.fsdecode(path)).absolute()
        return p == protected or protected in p.parents
    except (TypeError, ValueError):
        return True
def guard(event, args):
    if event == "open":
        if len(args) >= 3 and isinstance(args[2], int) and (args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)) and unsafe(args[0]):
            raise PermissionError("live controller runtime is read-only during independent recovery tests")
    elif event in {"os.rename", "os.remove", "os.unlink", "os.mkdir", "os.rmdir", "os.chmod", "os.chown", "os.utime", "os.link", "os.symlink", "os.truncate"} and any(unsafe(p) for p in args[:2]):
        raise PermissionError("live controller runtime is read-only during independent recovery tests")
sys.addaudithook(guard)
import pytest
raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[2:]]))
"""
    args = [str(py), "-c", guarded_test_runner, str(root), *QUALIFICATION_FILES]
    run = subprocess.run(args, cwd=root, env=env, text=True, capture_output=True, check=False)
    root, current_state, _intent, _saved, _prefix = _pending(project, expected_preview)
    if current_state["record_sha256"] != state["record_sha256"]:
        raise RecoveryRefused("plan changed during independent regression execution")
    text = run.stdout + run.stderr
    if run.returncode:
        raise RecoveryRefused("independent regression FAILED; last 1200 chars: " + text[-1200:])
    body = {"schema": TEST_SCHEMA, "origin_preview_sha256": expected_preview,
            "intent_record_sha256": intent["record_sha256"],
            "plan_record_sha256": state["record_sha256"],
            "candidate_baseline_sha256": saved["candidate_baseline_sha256"],
            "test_python": str(py), "test_files": list(QUALIFICATION_FILES),
            "test_output_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "test_output_tail": text[-1200:], "exit_code": run.returncode, "tested_at": _now()}
    rec = _write(root, prefix + "-qualification.json", body)
    return {"result": "INDEPENDENT_REGRESSIONS_PASSED", "qualification_record_sha256": rec["record_sha256"],
            "test_output_tail": text[-1200:], "execution_authority_granted": False}


def release_preview(project: Path, expected_preview: str) -> dict[str, Any]:
    root, state, intent, saved, prefix = _pending(project, expected_preview)
    if _runtime(root, prefix + "-release.json").exists():
        raise RecoveryRefused("release already recorded")
    qual = _record(root, prefix + "-qualification.json", TEST_SCHEMA)
    if (qual.get("intent_record_sha256") != intent["record_sha256"]
        or qual.get("plan_record_sha256") != state["record_sha256"]
        or qual.get("candidate_baseline_sha256") != saved["candidate_baseline_sha256"]
        or qual.get("exit_code") != 0
        or qual.get("test_files") != list(QUALIFICATION_FILES)):
        raise RecoveryRefused("independent qualification evidence is stale")
    body = {"schema": "stygnox_direct_interruption_release_preview_v1",
            "operator": saved["operator"], "worktree": str(root),
            "origin_preview_sha256": expected_preview,
            "intent_record_sha256": intent["record_sha256"],
            "qualification_record_sha256": qual["record_sha256"],
            "blocked_plan_record_sha256": state["record_sha256"],
            "predecessor_baseline_sha256": saved["predecessor_baseline_sha256"],
            "candidate_baseline_sha256": saved["candidate_baseline_sha256"],
            "confirmation": "RELEASE_REVIEWED_WORK"}
    body["preview_sha256"] = _digest(body)
    return body


def release(project: Path, expected_preview: str, preview_sha256: str, confirm: str) -> dict[str, Any]:
    _require_qualification_replay()
    if confirm != "RELEASE_REVIEWED_WORK":
        raise RecoveryRefused("explicit --confirm RELEASE_REVIEWED_WORK required")
    preview = release_preview(project, expected_preview)
    if preview["preview_sha256"] != preview_sha256:
        raise RecoveryRefused("release preview is stale")
    root, state, intent, saved, prefix = _pending(project, expected_preview)
    proof = intent.get("manifest_proof")
    if not isinstance(proof, dict) or not isinstance(proof.get("proof_sha256"), str):
        raise RecoveryRefused("missing full-chain Stage B1 reviewed attribution proof")
    body = {"schema": RELEASE_SCHEMA, "reviewed_origin": expected_preview,
            "intent_record_sha256": intent["record_sha256"],
            "qualification_record_sha256": preview["qualification_record_sha256"],
            "predecessor_plan_record_sha256": saved["plan_record_sha256"],
            "quarantined_plan_record_sha256": state["record_sha256"],
            "original_baseline_sha256": saved["predecessor_baseline_sha256"],
            "reviewed_baseline_sha256": saved["candidate_baseline_sha256"],
            "classification": "HUMAN_REVIEWED_UNATTRIBUTED_INTERRUPTED_WORK",
            "manifest_proof_sha256": proof["proof_sha256"],
            "provider_pass_fabricated": False, "retrospective_grant_fabricated": False,
            "released_at": _now()}
    receipt = _write(root, prefix + "-release.json", body)
    updated = dict(state)
    updated["status"] = "APPROVED"
    updated["execution_authority_granted"] = True
    updated["step_authority_baseline_sha256"] = saved["candidate_baseline_sha256"]
    updated["direct_interruption_pending"] = None
    history = list(updated.get("direct_interruption_recoveries") or [])
    if history:
        raise RecoveryRefused("additional reviewed-interruption epoch requires a separately qualified replay contract")
    updated["direct_interruption_recoveries"] = [receipt]
    updated["step_resume"] = {"step": updated["current_step"], "gate_id": None,
                              "reason": "Explicit operator-reviewed interrupted source adopted; independent regressions passed; origin provider turn FAILED",
                              "allowed_new_tests": [], "recorded_at": _now(), "decision_sha256": receipt["record_sha256"]}
    written = planning._write(root, updated)
    return {"result": "HUMAN_REVIEWED_INTERRUPTION_RECOVERED", "new_plan_record_sha256": written["record_sha256"],
            "checkpoint_baseline_sha256": saved["candidate_baseline_sha256"],
            "original_provider_turn_remains_failed": True,
            "review_receipt_sha256": receipt["record_sha256"]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stygnox direct-interruption", description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    def base(x: argparse.ArgumentParser) -> None:
        x.add_argument("--project", type=Path, required=True)
        x.add_argument("--origin-preview-sha256", required=True)
    for cmd in ("review-preview", "adopt"):
        c = sub.add_parser(cmd)
        base(c)
        c.add_argument("--origin-file", type=Path, required=True)
        c.add_argument("--review-path", action="append", default=[], required=True)
        if cmd == "adopt":
            c.add_argument("--reason", required=True)
            c.add_argument("--preview", required=True)
            c.add_argument("--confirm", required=True)
    q = sub.add_parser("qualify"); base(q); q.add_argument("--test-python", type=Path, required=True)
    v = sub.add_parser("release-preview"); base(v)
    r = sub.add_parser("release"); base(r); r.add_argument("--preview", required=True); r.add_argument("--confirm", required=True)
    return p


def cli_main(argv: Sequence[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    try:
        if args.action == "review-preview":
            result = review_preview(args.project, args.origin_file, args.origin_preview_sha256, args.review_path)
        elif args.action == "adopt":
            result = adopt(args.project, args.origin_file, args.origin_preview_sha256, args.review_path,
                           args.reason, args.preview, args.confirm)
        elif args.action == "qualify":
            result = qualify(args.project, args.origin_preview_sha256, args.test_python)
        elif args.action == "release-preview":
            result = release_preview(args.project, args.origin_preview_sha256)
        else:
            result = release(args.project, args.origin_preview_sha256, args.preview, args.confirm)
    except (RecoveryRefused, OSError, ValueError, planning.PlanningError, controller.ControllerError,
            adoption.AdoptionError, scheduler.SchedulerError, transactions.TransactionError) as exc:
        print(f"stygnox: direct interruption refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
