"""Controller-owned Git finalization and external reconciliation.

Finalization consumes only READY_TO_COMMIT provenance emitted by qualification.
Native commit/push use exact preview + confirmation semantics. External commit or
push work is never trusted implicitly: reconciliation independently verifies the
same qualified path/content and remote evidence before advancing plan state.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

from . import adoption, planning, qualification, scheduler
from .product import PRODUCT


COMMIT_PREVIEW_SCHEMA = "stygnox_finalization_commit_preview_v1"
PUSH_PREVIEW_SCHEMA = "stygnox_finalization_push_preview_v1"
RECONCILE_COMMIT_PREVIEW_SCHEMA = "stygnox_reconcile_commit_preview_v1"
RECONCILE_PUSH_PREVIEW_SCHEMA = "stygnox_reconcile_push_preview_v1"
COMMIT_RECORD_SCHEMA = "stygnox_finalization_commit_v1"
PUSH_RECORD_SCHEMA = "stygnox_finalization_push_v1"
_HEX40_64 = re.compile(r"^[0-9a-f]{40,64}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FinalizationError(RuntimeError):
    """Fail-closed Git finalization/reconciliation error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = adoption._git(root, *args, check=check, text=True)
    if check and result.returncode != 0:  # adoption._git normally raises first
        raise FinalizationError(f"git {' '.join(args)} failed")
    return result.stdout


def _operator(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise FinalizationError("--operator is required")
    return text


def _plan_hash(value: str) -> str:
    text = str(value or "").strip().lower()
    if not _HEX64.fullmatch(text):
        raise FinalizationError("plan hash must be an exact 64-character SHA-256")
    return text


def _message(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 500 or "\x00" in text:
        raise FinalizationError("commit message must be 1-500 characters")
    return text


def _reason(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 2000 or "\x00" in text:
        raise FinalizationError("reconciliation reason must be 1-2000 characters")
    return text


def _authority(project: Path, operator: str, plan_hash: str, statuses: set[str]) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
    try:
        root, active, tx, policy, name = planning._active_context(project, _operator(operator))
    except Exception as exc:
        raise FinalizationError(str(exc)) from exc
    state = planning._record(root)
    assert state is not None
    if str(state.get("status") or "") == "READ_ONLY_COMPLETE":
        raise FinalizationError("Git finalization/reconciliation is prohibited for READ_ONLY_COMPLETE plans")
    if str(state.get("status") or "") not in statuses:
        raise FinalizationError(f"Git finalization requires plan status in {sorted(statuses)}, found {state.get('status')}")
    plan = planning._validate_plan(state.get("plan"))
    expected = planning._plan_hash(plan)
    supplied = _plan_hash(plan_hash)
    if supplied != expected or state.get("plan_hash") != expected:
        raise FinalizationError("finalization plan hash does not match current plan")
    if plan.get("repository_authority") != "write":
        raise FinalizationError("Git finalization requires repository_authority=write")
    if state.get("operator") != name or state.get("transaction_id") != tx.get("transaction_id"):
        raise FinalizationError("finalization authority does not match active transaction/operator")
    if state.get("controller_record_sha256") != active.get("record_sha256"):
        raise FinalizationError("controller authority changed after plan approval")
    if state.get("tracked_config_sha256") != policy.get("tracked_config_sha256") or state.get("review_sha256") != (policy.get("review") or {}).get("review_sha256"):
        raise FinalizationError("execution policy changed after plan approval")
    if state.get("transaction_recovery_baseline_sha256") != tx.get("authority_baseline_sha256"):
        raise FinalizationError("transaction recovery authority changed after plan approval")
    if state.get("active_gate") is not None or state.get("self_development_grant") is not None:
        raise FinalizationError("finalization refuses unresolved human/self-development authority")
    active_sched = scheduler.active_scheduler_authority(root)
    if active_sched is not None:
        raise FinalizationError("finalization refuses active scheduler authority")
    return root, state, active, tx, policy, name


def _final_qualification(state: Mapping[str, Any]) -> dict[str, Any]:
    final = state.get("final_qualification") if isinstance(state.get("final_qualification"), Mapping) else None
    if not isinstance(final, Mapping) or final.get("state") != "PASS":
        raise FinalizationError("READY_TO_COMMIT requires PASS final qualification")
    value = dict(final)
    recorded = str(value.get("provenance_sha256") or "")
    body = dict(value)
    body.pop("provenance_sha256", None)
    if not _HEX64.fullmatch(recorded) or qualification._digest(body) != recorded:
        raise FinalizationError("final qualification provenance integrity check failed")
    required = ("qualified_head", "qualified_branch", "qualified_path_fingerprints")
    if any(key not in value for key in required):
        raise FinalizationError("final qualification predates Git-finalization evidence; run explicit requalification")
    if not value.get("qualified_head") or value.get("qualified_branch") in {None, "", "(detached)"}:
        raise FinalizationError("final qualification requires a named branch and qualified base HEAD")
    paths = sorted(map(str, value.get("plan_owned_paths") or []))
    fingerprints = value.get("qualified_path_fingerprints")
    if not isinstance(fingerprints, Mapping) or sorted(map(str, fingerprints.keys())) != paths:
        raise FinalizationError("final qualification path fingerprints do not match qualified path set")
    if qualification._qualified_delta_sha256({str(k): str(v) for k, v in fingerprints.items()}, paths) != value.get("qualified_delta_sha256"):
        raise FinalizationError("final qualification delta fingerprint is invalid")
    return value


def _git_path_fingerprint(root: Path, commit: str, path: str) -> str:
    raw = adoption._git(root, "ls-tree", "-z", commit, "--", path).stdout
    if not raw:
        return "missing"
    row = raw.split(b"\0", 1)[0]
    try:
        meta, recorded_path = row.split(b"\t", 1)
        mode_b, type_b, sha_b = meta.split(b" ", 2)
    except ValueError as exc:
        raise FinalizationError(f"cannot parse Git tree entry for {path}") from exc
    if recorded_path.decode("utf-8", errors="surrogateescape") != path or type_b != b"blob":
        raise FinalizationError(f"unsupported Git tree object for qualified path: {path}")
    content = adoption._git(root, "cat-file", "blob", sha_b.decode()).stdout
    mode = mode_b.decode()
    digest = hashlib.sha256()
    if mode == "120000":
        digest.update(b"symlink:777:")
        digest.update(content)
        return digest.hexdigest()
    if mode == "100755":
        fs_mode = 0o755
    elif mode == "100644":
        fs_mode = 0o644
    else:
        raise FinalizationError(f"unsupported Git mode {mode} for qualified path: {path}")
    digest.update(f"file:{fs_mode:o}:".encode())
    digest.update(content)
    return digest.hexdigest()


def _resolve_commit(root: Path, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise FinalizationError("commit SHA is required")
    result = adoption._git(root, "rev-parse", "--verify", f"{text}^{{commit}}", check=False, text=True)
    if result.returncode != 0:
        raise FinalizationError(f"commit does not exist: {text}")
    sha = result.stdout.strip()
    if not _HEX40_64.fullmatch(sha):
        raise FinalizationError("resolved commit SHA is invalid")
    return sha


def _commit_parent(root: Path, commit: str) -> str:
    parts = _git(root, "rev-list", "--parents", "-n", "1", commit).strip().split()
    if len(parts) != 2:
        raise FinalizationError("qualified finalization requires exactly one commit parent")
    return parts[1]


def _commit_changed_paths(root: Path, parent: str, commit: str) -> list[str]:
    raw = adoption._git(root, "diff", "--name-only", "-z", parent, commit).stdout
    return sorted(item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item)


def _verify_commit(root: Path, state: Mapping[str, Any], final: Mapping[str, Any], commit: str) -> dict[str, Any]:
    parent = _commit_parent(root, commit)
    if parent != final.get("qualified_head"):
        raise FinalizationError("commit parent does not match the qualified base HEAD")
    expected_paths = sorted(map(str, final.get("plan_owned_paths") or []))
    changed = _commit_changed_paths(root, parent, commit)
    if changed != expected_paths:
        raise FinalizationError(f"commit scope differs from qualified provenance: expected={expected_paths}, actual={changed}")
    commit_fingerprints = {path: _git_path_fingerprint(root, commit, path) for path in expected_paths}
    expected_fingerprints = {str(k): str(v) for k, v in dict(final.get("qualified_path_fingerprints") or {}).items()}
    if commit_fingerprints != expected_fingerprints:
        raise FinalizationError("commit contents/modes differ from qualified provenance")
    if qualification._qualified_delta_sha256(commit_fingerprints, expected_paths) != final.get("qualified_delta_sha256"):
        raise FinalizationError("commit qualified-delta fingerprint mismatch")
    return {"parent": parent, "paths": expected_paths, "path_fingerprints": commit_fingerprints}


def _current_qualified_tree(root: Path, final: Mapping[str, Any]) -> dict[str, Any]:
    current = adoption.capture_baseline(root).public()
    if current.get("head") != final.get("qualified_head") or current.get("branch") != final.get("qualified_branch"):
        raise FinalizationError("qualified HEAD/branch changed after READY_TO_COMMIT")
    if current.get("sha256") != final.get("repository_baseline_sha256"):
        raise FinalizationError("repository baseline changed after READY_TO_COMMIT; requalify before finalization")
    paths = sorted(map(str, final.get("plan_owned_paths") or []))
    fingerprints = {path: qualification._git_finalization_path_fingerprint(root / path) for path in paths}
    if fingerprints != {str(k): str(v) for k, v in dict(final.get("qualified_path_fingerprints") or {}).items()}:
        raise FinalizationError("current plan-owned contents no longer match qualified provenance")
    if qualification._qualified_delta_sha256(fingerprints, paths) != final.get("qualified_delta_sha256"):
        raise FinalizationError("current qualified-delta fingerprint changed")
    return current


def _staged_paths(root: Path) -> list[str]:
    raw = adoption._git(root, "diff", "--cached", "--name-only", "-z").stdout
    return sorted(item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item)


def _approval_overlap(root: Path, state: Mapping[str, Any], final: Mapping[str, Any]) -> list[str]:
    approval = state.get("approval_repository_manifest") if isinstance(state.get("approval_repository_manifest"), Mapping) else None
    if approval is None:
        raise FinalizationError("approved plan lacks repository manifest evidence")
    head = str(final.get("qualified_head") or "")
    overlaps: list[str] = []
    for path in sorted(map(str, final.get("plan_owned_paths") or [])):
        approval_fp = str(approval.get(path, "missing"))
        head_fp = _git_path_fingerprint(root, head, path)
        if approval_fp != head_fp:
            overlaps.append(path)
    return overlaps


def _history(state: Mapping[str, Any], row: Mapping[str, Any]) -> list[dict[str, Any]]:
    prior = [dict(item) for item in state.get("finalization_history") or [] if isinstance(item, Mapping)]
    return [*prior[-99:], dict(row)]


def _record_commit_state(root: Path, state: Mapping[str, Any], row: Mapping[str, Any], *, reconciled: bool) -> dict[str, Any]:
    record = dict(row)
    record["record_sha256"] = _digest(record)
    updated = dict(state)
    updated["status"] = "COMMITTED"
    updated["commit_sha"] = record["commit_sha"]
    updated["commit_record"] = record
    updated["commit_reconciled"] = bool(reconciled)
    updated["finalization_history"] = _history(updated, {"kind": "commit", "commit_sha": record["commit_sha"], "reconciled": bool(reconciled), "record_sha256": record["record_sha256"], "completed_at": record["completed_at"]})
    return planning._write(root, updated)


def _record_push_state(root: Path, state: Mapping[str, Any], row: Mapping[str, Any], *, reconciled: bool) -> dict[str, Any]:
    record = dict(row)
    record["record_sha256"] = _digest(record)
    updated = dict(state)
    updated["status"] = "PUSHED"
    updated["push_record"] = record
    updated["push_reconciled"] = bool(reconciled)
    updated["finalization_history"] = _history(updated, {"kind": "push", "commit_sha": record["commit_sha"], "reconciled": bool(reconciled), "record_sha256": record["record_sha256"], "completed_at": record["completed_at"]})
    return planning._write(root, updated)


def build_commit_preview(project: Path, operator: str, plan_hash: str, message: str) -> dict[str, Any]:
    root, state, active, tx, policy, name = _authority(project, operator, plan_hash, {"READY_TO_COMMIT"})
    final = _final_qualification(state)
    current = _current_qualified_tree(root, final)
    staged = _staged_paths(root)
    if staged:
        raise FinalizationError(f"native commit refuses pre-staged paths; use manual commit + reconcile-commit: {staged}")
    overlaps = _approval_overlap(root, state, final)
    if overlaps:
        raise FinalizationError(f"native commit refuses approval-baseline overlap; use manual commit + reconcile-commit: {overlaps}")
    body = {
        "schema": COMMIT_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "final_provenance_sha256": final["provenance_sha256"],
        "qualified_delta_sha256": final["qualified_delta_sha256"],
        "qualified_head": final["qualified_head"],
        "qualified_branch": final["qualified_branch"],
        "plan_owned_paths": list(final["plan_owned_paths"]),
        "repository_baseline_sha256": current["sha256"],
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "tracked_config_sha256": policy["tracked_config_sha256"],
        "review_sha256": (policy.get("review") or {}).get("review_sha256"),
        "message": _message(message),
        "requires_explicit_confirmation": True,
        "confirmation": "COMMIT",
    }
    body["preview_sha256"] = _digest(body)
    return body


def commit(project: Path, operator: str, plan_hash: str, message: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    preview = build_commit_preview(project, operator, plan_hash, message)
    expected = str(preview_sha256 or "").strip().lower()
    if preview["preview_sha256"] != expected:
        raise FinalizationError("commit preview is stale; qualification, authority, message, or repository evidence changed")
    if confirmation != "COMMIT":
        raise FinalizationError("explicit confirmation required: --confirm COMMIT")
    root = Path(preview["worktree"])
    paths = list(preview["plan_owned_paths"])
    if not paths:
        raise FinalizationError("write plan has no qualified plan-owned delta to commit")
    try:
        adoption._git(root, "add", "-A", "--", *paths)
        staged = _staged_paths(root)
        if staged != sorted(paths):
            raise FinalizationError(f"staged commit scope differs from qualified paths: expected={sorted(paths)}, actual={staged}")
        adoption._git(root, "diff", "--cached", "--check")
        result = adoption._git(root, "-c", "commit.gpgSign=false", "commit", "--no-verify", "-m", preview["message"], check=False, text=True)
        if result.returncode != 0:
            raise FinalizationError(f"git commit failed: {(result.stderr or result.stdout).strip()}")
        commit_sha = _resolve_commit(root, "HEAD")
        state = planning._record(root)
        assert state is not None
        final = _final_qualification(state)
        verified = _verify_commit(root, state, final, commit_sha)
    except Exception:
        # If no commit was created, restore the previously empty index. If an invalid
        # commit was created, return HEAD to the exact qualified parent while keeping
        # worktree contents for operator review.
        try:
            head = _git(root, "rev-parse", "HEAD").strip()
            if head != preview["qualified_head"] and _commit_parent(root, head) == preview["qualified_head"]:
                adoption._git(root, "reset", "--mixed", preview["qualified_head"])
            else:
                adoption._git(root, "reset", "--mixed", "HEAD", "--", *paths)
        except Exception:
            pass
        raise
    state = planning._record(root)
    assert state is not None
    row = {
        "schema": COMMIT_RECORD_SCHEMA,
        "kind": "controller",
        "operator": preview["operator"],
        "plan_hash": preview["plan_hash"],
        "final_provenance_sha256": preview["final_provenance_sha256"],
        "qualified_delta_sha256": preview["qualified_delta_sha256"],
        "preview_sha256": expected,
        "qualified_parent": verified["parent"],
        "commit_sha": commit_sha,
        "branch": preview["qualified_branch"],
        "message": preview["message"],
        "plan_owned_paths": verified["paths"],
        "completed_at": _utc_now(),
    }
    written = _record_commit_state(root, state, row, reconciled=False)
    return {"schema": COMMIT_RECORD_SCHEMA, "result": "COMMITTED", "commit_sha": commit_sha, "plan_status": written["status"], "record_sha256": written["commit_record"]["record_sha256"]}


def _commit_record(state: Mapping[str, Any]) -> dict[str, Any]:
    record = state.get("commit_record") if isinstance(state.get("commit_record"), Mapping) else None
    if not isinstance(record, Mapping) or record.get("schema") != COMMIT_RECORD_SCHEMA:
        raise FinalizationError("COMMITTED plan lacks valid commit evidence")
    value = dict(record)
    recorded = str(value.pop("record_sha256", ""))
    if not _HEX64.fullmatch(recorded) or _digest(value) != recorded:
        raise FinalizationError("commit evidence integrity check failed")
    if record.get("commit_sha") != state.get("commit_sha"):
        raise FinalizationError("commit evidence does not match plan commit_sha")
    return dict(record)


def _plan_owned_dirty(root: Path, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    raw = adoption._git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths).stdout
    rows = [item for item in raw.split(b"\0") if item]
    return sorted(item[3:].decode("utf-8", errors="surrogateescape") if len(item) >= 4 else item.decode("utf-8", errors="surrogateescape") for item in rows)


def _upstream(root: Path, branch: str) -> tuple[str, str, str | None]:
    remote_result = adoption._git(root, "config", "--get", f"branch.{branch}.remote", check=False, text=True)
    merge_result = adoption._git(root, "config", "--get", f"branch.{branch}.merge", check=False, text=True)
    if remote_result.returncode != 0 or merge_result.returncode != 0:
        raise FinalizationError(f"branch {branch!r} has no configured upstream; configure upstream before push")
    remote = remote_result.stdout.strip()
    ref = merge_result.stdout.strip()
    if not remote or remote == "." or not ref.startswith("refs/heads/"):
        raise FinalizationError("configured upstream is not a remote branch")
    result = adoption._git(root, "ls-remote", "--heads", remote, ref, check=False, text=True)
    if result.returncode != 0:
        raise FinalizationError(f"cannot query upstream {remote} {ref}: {(result.stderr or result.stdout).strip()}")
    line = result.stdout.strip().splitlines()
    remote_head = line[0].split()[0] if line else None
    return remote, ref, remote_head


def build_push_preview(project: Path, operator: str, plan_hash: str) -> dict[str, Any]:
    root, state, active, tx, policy, name = _authority(project, operator, plan_hash, {"COMMITTED"})
    final = _final_qualification(state)
    commit_record = _commit_record(state)
    commit_sha = _resolve_commit(root, str(state.get("commit_sha") or ""))
    head = _resolve_commit(root, "HEAD")
    if head != commit_sha:
        raise FinalizationError("local HEAD changed after recorded commit")
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    if not branch or branch != commit_record.get("branch"):
        raise FinalizationError("local branch changed after recorded commit")
    _verify_commit(root, state, final, commit_sha)
    dirty = _plan_owned_dirty(root, final["plan_owned_paths"])
    if dirty:
        raise FinalizationError(f"plan-owned paths changed after commit: {dirty}")
    remote, remote_ref, remote_head = _upstream(root, branch)
    body = {
        "schema": PUSH_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "final_provenance_sha256": final["provenance_sha256"],
        "commit_record_sha256": commit_record["record_sha256"],
        "commit_sha": commit_sha,
        "branch": branch,
        "remote": remote,
        "remote_ref": remote_ref,
        "remote_head": remote_head,
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "tracked_config_sha256": policy["tracked_config_sha256"],
        "review_sha256": (policy.get("review") or {}).get("review_sha256"),
        "requires_explicit_confirmation": True,
        "confirmation": "PUSH",
    }
    body["preview_sha256"] = _digest(body)
    return body


def push(project: Path, operator: str, plan_hash: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    preview = build_push_preview(project, operator, plan_hash)
    expected = str(preview_sha256 or "").strip().lower()
    if preview["preview_sha256"] != expected:
        raise FinalizationError("push preview is stale; local/remote authority changed")
    if confirmation != "PUSH":
        raise FinalizationError("explicit confirmation required: --confirm PUSH")
    root = Path(preview["worktree"])
    result = adoption._git(root, "push", "--porcelain", preview["remote"], f"{preview['commit_sha']}:{preview['remote_ref']}", check=False, text=True)
    if result.returncode != 0:
        raise FinalizationError(f"git push failed: {(result.stderr or result.stdout).strip()}")
    _remote, _ref, remote_head = _upstream(root, preview["branch"])
    if remote_head != preview["commit_sha"]:
        raise FinalizationError("remote branch does not point to the recorded qualified commit after push")
    state = planning._record(root)
    assert state is not None
    row = {
        "schema": PUSH_RECORD_SCHEMA,
        "kind": "controller",
        "operator": preview["operator"],
        "plan_hash": preview["plan_hash"],
        "final_provenance_sha256": preview["final_provenance_sha256"],
        "commit_sha": preview["commit_sha"],
        "preview_sha256": expected,
        "remote": preview["remote"],
        "remote_ref": preview["remote_ref"],
        "remote_before": preview["remote_head"],
        "remote_after": remote_head,
        "completed_at": _utc_now(),
    }
    written = _record_push_state(root, state, row, reconciled=False)
    return {"schema": PUSH_RECORD_SCHEMA, "result": "PUSHED", "commit_sha": preview["commit_sha"], "plan_status": written["status"], "record_sha256": written["push_record"]["record_sha256"]}


def build_reconcile_commit_preview(project: Path, operator: str, plan_hash: str, commit_sha: str, reason: str) -> dict[str, Any]:
    root, state, active, tx, policy, name = _authority(project, operator, plan_hash, {"READY_TO_COMMIT"})
    final = _final_qualification(state)
    commit_id = _resolve_commit(root, commit_sha)
    head = _resolve_commit(root, "HEAD")
    if head != commit_id:
        raise FinalizationError("reconcile-commit requires supplied commit to be current HEAD")
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    if not branch or branch != final.get("qualified_branch"):
        raise FinalizationError("manual commit branch differs from qualified branch")
    verified = _verify_commit(root, state, final, commit_id)
    dirty = _plan_owned_dirty(root, verified["paths"])
    if dirty:
        raise FinalizationError(f"plan-owned paths differ from manual commit: {dirty}")
    body = {
        "schema": RECONCILE_COMMIT_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "final_provenance_sha256": final["provenance_sha256"],
        "qualified_delta_sha256": final["qualified_delta_sha256"],
        "commit_sha": commit_id,
        "qualified_parent": verified["parent"],
        "branch": branch,
        "plan_owned_paths": verified["paths"],
        "reason": _reason(reason),
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "tracked_config_sha256": policy["tracked_config_sha256"],
        "review_sha256": (policy.get("review") or {}).get("review_sha256"),
        "requires_explicit_confirmation": True,
        "confirmation": "RECONCILE_COMMIT",
    }
    body["preview_sha256"] = _digest(body)
    return body


def reconcile_commit(project: Path, operator: str, plan_hash: str, commit_sha: str, reason: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    preview = build_reconcile_commit_preview(project, operator, plan_hash, commit_sha, reason)
    expected = str(preview_sha256 or "").strip().lower()
    if preview["preview_sha256"] != expected:
        raise FinalizationError("reconcile-commit preview is stale")
    if confirmation != "RECONCILE_COMMIT":
        raise FinalizationError("explicit confirmation required: --confirm RECONCILE_COMMIT")
    root = Path(preview["worktree"])
    state = planning._record(root)
    assert state is not None
    row = {
        "schema": COMMIT_RECORD_SCHEMA,
        "kind": "reconciled",
        "operator": preview["operator"],
        "plan_hash": preview["plan_hash"],
        "final_provenance_sha256": preview["final_provenance_sha256"],
        "qualified_delta_sha256": preview["qualified_delta_sha256"],
        "preview_sha256": expected,
        "qualified_parent": preview["qualified_parent"],
        "commit_sha": preview["commit_sha"],
        "branch": preview["branch"],
        "message": _git(root, "show", "-s", "--format=%s", preview["commit_sha"]).strip(),
        "plan_owned_paths": preview["plan_owned_paths"],
        "reason": preview["reason"],
        "completed_at": _utc_now(),
    }
    written = _record_commit_state(root, state, row, reconciled=True)
    return {"schema": COMMIT_RECORD_SCHEMA, "result": "COMMIT_RECONCILED", "commit_sha": preview["commit_sha"], "plan_status": written["status"], "record_sha256": written["commit_record"]["record_sha256"]}


def build_reconcile_push_preview(project: Path, operator: str, plan_hash: str) -> dict[str, Any]:
    root, state, active, tx, policy, name = _authority(project, operator, plan_hash, {"COMMITTED"})
    final = _final_qualification(state)
    commit_record = _commit_record(state)
    commit_sha = _resolve_commit(root, str(state.get("commit_sha") or ""))
    if _resolve_commit(root, "HEAD") != commit_sha:
        raise FinalizationError("local HEAD changed after recorded commit")
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    if not branch or branch != commit_record.get("branch"):
        raise FinalizationError("local branch changed after recorded commit")
    _verify_commit(root, state, final, commit_sha)
    dirty = _plan_owned_dirty(root, final["plan_owned_paths"])
    if dirty:
        raise FinalizationError(f"plan-owned paths changed after commit: {dirty}")
    remote, remote_ref, remote_head = _upstream(root, branch)
    if remote_head != commit_sha:
        raise FinalizationError("recorded commit is not the exact current upstream branch head")
    body = {
        "schema": RECONCILE_PUSH_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "plan_hash": state["plan_hash"],
        "plan_record_sha256": state["record_sha256"],
        "final_provenance_sha256": final["provenance_sha256"],
        "commit_record_sha256": commit_record["record_sha256"],
        "commit_sha": commit_sha,
        "branch": branch,
        "remote": remote,
        "remote_ref": remote_ref,
        "remote_head": remote_head,
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": active["record_sha256"],
        "tracked_config_sha256": policy["tracked_config_sha256"],
        "review_sha256": (policy.get("review") or {}).get("review_sha256"),
        "requires_explicit_confirmation": True,
        "confirmation": "RECONCILE_PUSH",
    }
    body["preview_sha256"] = _digest(body)
    return body


def reconcile_push(project: Path, operator: str, plan_hash: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    preview = build_reconcile_push_preview(project, operator, plan_hash)
    expected = str(preview_sha256 or "").strip().lower()
    if preview["preview_sha256"] != expected:
        raise FinalizationError("reconcile-push preview is stale")
    if confirmation != "RECONCILE_PUSH":
        raise FinalizationError("explicit confirmation required: --confirm RECONCILE_PUSH")
    root = Path(preview["worktree"])
    state = planning._record(root)
    assert state is not None
    row = {
        "schema": PUSH_RECORD_SCHEMA,
        "kind": "reconciled",
        "operator": preview["operator"],
        "plan_hash": preview["plan_hash"],
        "final_provenance_sha256": preview["final_provenance_sha256"],
        "commit_sha": preview["commit_sha"],
        "preview_sha256": expected,
        "remote": preview["remote"],
        "remote_ref": preview["remote_ref"],
        "remote_before": preview["remote_head"],
        "remote_after": preview["remote_head"],
        "completed_at": _utc_now(),
    }
    written = _record_push_state(root, state, row, reconciled=True)
    return {"schema": PUSH_RECORD_SCHEMA, "result": "PUSH_RECONCILED", "commit_sha": preview["commit_sha"], "plan_status": written["status"], "record_sha256": written["push_record"]["record_sha256"]}


def finalization_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    state = planning._record(root, required=False)
    return {
        "schema": "stygnox_finalization_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "plan_status": state.get("status") if isinstance(state, Mapping) else None,
        "plan_hash": state.get("plan_hash") if isinstance(state, Mapping) else None,
        "commit_sha": state.get("commit_sha") if isinstance(state, Mapping) else None,
        "commit_record": state.get("commit_record") if isinstance(state, Mapping) else None,
        "push_record": state.get("push_record") if isinstance(state, Mapping) else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stygnox finalization", description="Controlled Git commit/push finalization and external reconciliation.")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--project", type=Path, default=Path.cwd())
    cp = sub.add_parser("commit-preview")
    cp.add_argument("plan_hash"); cp.add_argument("--project", type=Path, default=Path.cwd()); cp.add_argument("--operator", required=True); cp.add_argument("--message", required=True)
    cm = sub.add_parser("commit")
    cm.add_argument("plan_hash"); cm.add_argument("--project", type=Path, default=Path.cwd()); cm.add_argument("--operator", required=True); cm.add_argument("--message", required=True); cm.add_argument("--preview", required=True); cm.add_argument("--confirm", required=True)
    pp = sub.add_parser("push-preview")
    pp.add_argument("plan_hash"); pp.add_argument("--project", type=Path, default=Path.cwd()); pp.add_argument("--operator", required=True)
    pu = sub.add_parser("push")
    pu.add_argument("plan_hash"); pu.add_argument("--project", type=Path, default=Path.cwd()); pu.add_argument("--operator", required=True); pu.add_argument("--preview", required=True); pu.add_argument("--confirm", required=True)
    rcp = sub.add_parser("reconcile-commit-preview")
    rcp.add_argument("plan_hash"); rcp.add_argument("--project", type=Path, default=Path.cwd()); rcp.add_argument("--operator", required=True); rcp.add_argument("--commit", required=True); rcp.add_argument("--reason", required=True)
    rc = sub.add_parser("reconcile-commit")
    rc.add_argument("plan_hash"); rc.add_argument("--project", type=Path, default=Path.cwd()); rc.add_argument("--operator", required=True); rc.add_argument("--commit", required=True); rc.add_argument("--reason", required=True); rc.add_argument("--preview", required=True); rc.add_argument("--confirm", required=True)
    rpp = sub.add_parser("reconcile-push-preview")
    rpp.add_argument("plan_hash"); rpp.add_argument("--project", type=Path, default=Path.cwd()); rpp.add_argument("--operator", required=True)
    rp = sub.add_parser("reconcile-push")
    rp.add_argument("plan_hash"); rp.add_argument("--project", type=Path, default=Path.cwd()); rp.add_argument("--operator", required=True); rp.add_argument("--preview", required=True); rp.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = finalization_status(args.project)
        elif args.action == "commit-preview":
            result = build_commit_preview(args.project, args.operator, args.plan_hash, args.message)
        elif args.action == "commit":
            result = commit(args.project, args.operator, args.plan_hash, args.message, args.preview, args.confirm)
        elif args.action == "push-preview":
            result = build_push_preview(args.project, args.operator, args.plan_hash)
        elif args.action == "push":
            result = push(args.project, args.operator, args.plan_hash, args.preview, args.confirm)
        elif args.action == "reconcile-commit-preview":
            result = build_reconcile_commit_preview(args.project, args.operator, args.plan_hash, args.commit, args.reason)
        elif args.action == "reconcile-commit":
            result = reconcile_commit(args.project, args.operator, args.plan_hash, args.commit, args.reason, args.preview, args.confirm)
        elif args.action == "reconcile-push-preview":
            result = build_reconcile_push_preview(args.project, args.operator, args.plan_hash)
        else:
            result = reconcile_push(args.project, args.operator, args.plan_hash, args.preview, args.confirm)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (FinalizationError, planning.PlanningError, qualification.QualificationError, adoption.AdoptionError, OSError, ValueError) as exc:
        print(f"stygnox: finalization refused: {exc}", file=sys.stderr)
        return 2
