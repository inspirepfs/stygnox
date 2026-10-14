"""One-shot predecessor-to-successor native write-authority transfer.

The separately installed successor initiates and completes the transfer.  It
proves the unchanged predecessor by asking that predecessor's existing,
planning-only ``provider-release status`` command for its exact evidence; it
never asks the predecessor to import this new command.  The seal binds
transaction, operator, source revision, controller, plan hash, approval
baseline and plan-wide scope.  It does *not* bind the mutable plan-record
digest or current step: each successor admission revalidates the live step.
Pending, corrupt, symlinked, or contended transfers grant neither process.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator, Mapping, Sequence

from . import adoption, controller, execution_policy, lifecycle, planning, provider_codex, provider_release, transactions
from .direct_interruption_execution_guard import QuarantinedRuntime, refuse_quarantined_runtime

SCHEMA = "stygnox_native_provider_write_release_v2"
PREVIEW_SCHEMA = "stygnox_native_provider_write_release_preview_v2"
RECORD = "provider-write-release.json"
PENDING = "provider-write-release.pending.json"
# This must remain the immutable source commit that supplied the predecessor
# wheel.  A short prefix is not source identity: another commit may share it.
TARGET_BASELINE_REVISION = "1379422c9e443350b2c3661a94558f9baa637c42"
TARGET_TRANSACTION_ID = "TX-89e434dab18e67fe"
TARGET_PLAN_HASH = "9883eabe689e3b17fdd36a9002cf7db76b9ac9c7b24ea27d73945e70d7bda187"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_write_turn: ContextVar[tuple[str, str] | None] = ContextVar("stygnox_native_write_turn", default=None)


class ProviderWriteReleaseError(RuntimeError):
    """The separately approved native write release is not admissible."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _sealed(value: Mapping[str, Any], description: str) -> dict[str, Any]:
    body = dict(value)
    recorded = body.pop("record_sha256", None)
    if not isinstance(recorded, str) or not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise ProviderWriteReleaseError(f"{description} integrity check failed")
    return dict(value)


def _runtime_file(root: Path, name: str) -> Path:
    runtime = root / adoption.RUNTIME_NAME
    if os.path.islink(runtime) or not runtime.is_dir():
        raise ProviderWriteReleaseError("native write-release runtime directory must be regular")
    path = runtime / name
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise ProviderWriteReleaseError(f"native write-release record must be regular: {name}")
    return path


def _read(root: Path, name: str, *, required: bool = False) -> dict[str, Any] | None:
    path = _runtime_file(root, name)
    if not os.path.lexists(path):
        if required:
            raise ProviderWriteReleaseError(f"required native write-release record is missing: {name}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProviderWriteReleaseError(f"invalid native write-release record: {name}") from exc
    if not isinstance(value, dict):
        raise ProviderWriteReleaseError(f"native write-release record must be an object: {name}")
    return value


@contextmanager
def _transfer_lock(root: Path) -> Iterator[None]:
    runtime = root / adoption.RUNTIME_NAME
    if os.path.islink(runtime) or not runtime.is_dir():
        raise ProviderWriteReleaseError("native write-release runtime directory must be regular")
    try:
        fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ProviderWriteReleaseError("native write-release transfer lock is unavailable") from exc
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ProviderWriteReleaseError("native write-release transfer is already in progress") from exc
        yield
    finally:
        os.close(fd)


def _git_head(root: Path) -> str:
    try:
        value = str(adoption._git(root, "rev-parse", "HEAD", text=True).stdout).strip()
    except (adoption.AdoptionError, OSError, subprocess.SubprocessError) as exc:
        raise ProviderWriteReleaseError("cannot determine worktree source revision") from exc
    if not value:
        raise ProviderWriteReleaseError("worktree has no immutable source revision")
    return value


def _release_record(root: Path) -> dict[str, Any]:
    value = _read(root, RECORD, required=True)
    assert value is not None
    if value.get("schema") != SCHEMA:
        raise ProviderWriteReleaseError("unsupported native write-release schema")
    return _sealed(value, "native write-release record")


def _planning_record(root: Path) -> dict[str, Any]:
    value = provider_release._record(root)
    if value is None or value.get("scope") != "PLANNING_ONLY" or value.get("provider_write_turn") is not False:
        raise ProviderWriteReleaseError("planning release must remain explicitly planning-only")
    return value


def _lineage(root: Path, operator: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    try:
        refuse_quarantined_runtime(root)
    except QuarantinedRuntime as exc:
        raise ProviderWriteReleaseError("quarantined historical worktree cannot obtain write authority") from exc
    tx = transactions._transaction(root)
    assert tx is not None
    _sealed(tx, "transaction")
    if tx.get("state") != "ACTIVE" or tx.get("transaction_id") != TARGET_TRANSACTION_ID:
        raise ProviderWriteReleaseError("native write release requires the preserved ACTIVE transaction")
    if _git_head(root) != TARGET_BASELINE_REVISION:
        raise ProviderWriteReleaseError("worktree source revision changed from the preserved release baseline")
    handoff = transactions._load_adoption(root)
    name = controller._operator(operator)
    if tx.get("operator") != name or handoff.get("operator") != name or tx.get("handoff_preview_sha256") != handoff.get("preview_sha256"):
        raise ProviderWriteReleaseError("transaction/adoption operator lineage changed")
    return tx, handoff, name


def _context(root: Path, operator: str, tx: Mapping[str, Any]) -> dict[str, Any]:
    try:
        context = planning.approved_step_context(root, operator)
    except planning.PlanningError as exc:
        raise ProviderWriteReleaseError(str(exc)) from exc
    if context is None or context.get("plan_hash") != TARGET_PLAN_HASH or context.get("repository_authority") != "write":
        raise ProviderWriteReleaseError("native write release is bound to a different approved write plan")
    state = planning._record(root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True or context.get("transaction_id") != tx.get("transaction_id"):
        raise ProviderWriteReleaseError("approved plan does not presently grant execution authority")
    return context


def _policy(root: Path, *, predecessor: bool) -> tuple[dict[str, Any], Mapping[str, Any]]:
    release = _planning_record(root)
    if predecessor and not provider_release.planning_ready(root):
        raise ProviderWriteReleaseError("02N planning release is absent or no longer exact for the predecessor")
    status = controller._policy_status(root)
    policy = status.get("policy") or {}
    selection = release.get("model_selection") if isinstance(release.get("model_selection"), Mapping) else {}
    if (policy.get("provider") != provider_codex.PROVIDER_NAME or not policy.get("model") or not status.get("approved")
        or (predecessor and not status.get("provider_catalog_bound"))
        or selection.get("provider") != provider_codex.PROVIDER_NAME
        or selection.get("selected_model") != policy.get("model")
        or selection.get("selected_effort") != policy.get("effort")
        or not isinstance(selection.get("catalog_sha256"), str)):
        raise ProviderWriteReleaseError("reviewed planning-release provider selection changed")
    return release, selection


def _predecessor_status(
    root: Path,
    operator: str,
    tx: Mapping[str, Any],
    handoff: Mapping[str, Any],
    *,
    require_ready: bool,
) -> tuple[dict[str, Any], bool]:
    """Prove the original installed planning authority in its own process.

    ``provider-release`` predates this module.  Its status operation performs
    the predecessor's own installed-package, transaction, and planning-release
    validation.  Keep its process free of source-tree imports and put its
    executable first on PATH so this proof cannot accidentally resolve the
    successor installation.
    """
    raw_command = tx.get("installed_command")
    if not isinstance(raw_command, str):
        raise ProviderWriteReleaseError("predecessor installed command is missing from the transaction")
    command = Path(raw_command)
    if not command.is_absolute() or command.is_symlink() or not command.is_file():
        raise ProviderWriteReleaseError("predecessor installed command is not a regular absolute file")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PATH"] = str(command.parent) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [str(command), "provider-release", "status", "--project", str(root), "--operator", operator],
        cwd=str(root), env=env, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ProviderWriteReleaseError(
            "predecessor planning-release status verification failed: "
            + ((result.stderr or result.stdout).strip() or str(result.returncode))
        )
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderWriteReleaseError("predecessor planning-release status returned invalid JSON") from exc
    if not isinstance(status, Mapping) or not isinstance(status.get("planning_ready"), bool):
        raise ProviderWriteReleaseError("predecessor planning-release readiness evidence is malformed")
    ready = status["planning_ready"]
    if require_ready and not ready:
        raise ProviderWriteReleaseError("predecessor planning release is not presently ready")
    release = status.get("release")
    if not isinstance(release, Mapping) or dict(release) != _planning_record(root):
        raise ProviderWriteReleaseError("predecessor planning-release evidence differs from the preserved record")
    _sealed(release, "predecessor planning release")
    authority = release.get("authority")
    if not isinstance(authority, Mapping):
        raise ProviderWriteReleaseError("predecessor planning release lacks installed identity")
    required = {
        "transaction_id": tx.get("transaction_id"),
        "transaction_record_sha256": tx.get("record_sha256"),
        "handoff_preview_sha256": handoff.get("preview_sha256"),
        "operator": operator,
        "installed_command": str(command),
    }
    if status.get("transaction_operator") != operator or any(authority.get(key) != value for key, value in required.items()):
        raise ProviderWriteReleaseError("predecessor planning release transaction or installed identity changed")
    identity = {
        "executable": authority.get("installed_command"),
        "package_file": authority.get("installed_package"),
        "package_sha256": authority.get("installed_package_sha256"),
        "package_tree_sha256": authority.get("installed_package_tree_sha256"),
    }
    if any(not isinstance(value, str) or not value for value in identity.values()):
        raise ProviderWriteReleaseError("predecessor planning release installed identity is incomplete")
    return identity, ready


def _successor_identity(root: Path, artifact: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        successor = lifecycle._installed_identity(root)
        candidate = lifecycle._wheel_identity(Path(artifact), successor)
    except (lifecycle.LifecycleError, OSError) as exc:
        raise ProviderWriteReleaseError(f"successor installation is not exact: {exc}") from exc
    if not _current_is(str(successor["executable"])):
        raise ProviderWriteReleaseError("write release must be initiated by the installed successor executable")
    return successor, candidate


def _predecessor_inputs(project: Path, operator: str, artifact: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    if _read(root, PENDING) is not None:
        raise ProviderWriteReleaseError("interrupted native write-release transfer requires manual reconciliation")
    if _read(root, RECORD) is not None:
        raise ProviderWriteReleaseError("native write release already exists; no silent overwrite")
    tx, handoff, name = _lineage(root, operator)
    baseline = adoption.capture_baseline(root).public()
    if baseline.get("sha256") != tx.get("authority_baseline_sha256"):
        raise ProviderWriteReleaseError("project baseline changed after the preserved transaction began")
    predecessor, _ = _predecessor_status(root, name, tx, handoff, require_ready=True)
    successor, candidate = _successor_identity(root, artifact)
    release, selection = _policy(root, predecessor=False)
    active = controller._controller(root)
    assert active is not None
    if active.get("enabled") is not True or active.get("operator") != name or active.get("transaction_id") != tx.get("transaction_id"):
        raise ProviderWriteReleaseError("controller lineage is not active for the preserved transaction")
    context = _context(root, name, tx)
    return {
        "schema": PREVIEW_SCHEMA, "worktree": str(root), "source_revision": _git_head(root),
        "transaction_id": tx["transaction_id"], "transaction_record_sha256": tx["record_sha256"],
        "transaction_authority_baseline_sha256": tx["authority_baseline_sha256"], "operator": name,
        "handoff_preview_sha256": handoff["preview_sha256"], "controller_record_sha256": active["record_sha256"],
        "approved_plan_hash": context["plan_hash"], "predecessor_plan_record_sha256": context["plan_record_sha256"],
        "approval_baseline_sha256": context["approval_baseline_sha256"],
        "approved_mutation_scope": list(context[planning.REPOSITORY_MUTATION_SCOPE_FIELD]),
        "approved_mutation_scope_sha256": context[planning.REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD],
        "provider": provider_codex.PROVIDER_NAME, "model": selection["selected_model"], "effort": selection.get("selected_effort"),
        "planning_release_record_sha256": release["record_sha256"], "planning_catalog_sha256": selection["catalog_sha256"],
        "predecessor_installed": predecessor, "successor_installed": successor, "successor_artifact": candidate,
        "scope": "ONE_APPROVED_PLAN_WRITE_TURN_PER_CURRENT_VALID_STEP", "provider_write_turn": True,
        "confirmation": "RELEASE_WRITE",
    }


def preview(project: Path, operator: str, artifact: Path) -> dict[str, Any]:
    body = _predecessor_inputs(project, operator, artifact)
    return {**body, "preview_sha256": _digest(body), "requires_explicit_confirmation": True}


def _same(left: Any, right: Any) -> bool:
    return isinstance(left, Mapping) and isinstance(right, Mapping) and dict(left) == dict(right)


def _completed_transfer(record: Mapping[str, Any]) -> bool:
    """Return whether this is the exact persisted successor handoff state."""
    return (
        record.get("transition_complete") is True
        and record.get("predecessor_execution_authorised") is False
        and record.get("successor_execution_authorised") is True
        and record.get("final_qualification_claimed") is False
        and record.get("installed_successor_transition_claimed") is False
    )


def _authorised_current_step_progression(
    root: Path, binding: Mapping[str, Any], context: Mapping[str, Any], name: str, tx: Mapping[str, Any],
) -> None:
    """Prove the current baseline came from completed successor controller turns.

    The predecessor's planning readiness intentionally binds its original
    transaction baseline, so it becomes false after a valid write.  That fact
    alone grants nothing: every post-transfer baseline must be a sealed,
    continuous same-step progression with its matching controller receipt.
    """
    try:
        state = planning._record(root)
    except planning.PlanningError as exc:
        raise ProviderWriteReleaseError("current approved plan evidence is invalid") from exc
    assert state is not None
    initial = binding.get("approval_baseline_sha256")
    current = initial
    if not isinstance(initial, str) or not _HEX64.fullmatch(initial):
        raise ProviderWriteReleaseError("transfer lacks its original approved baseline")
    history = state.get("continuation_history")
    if not isinstance(history, list) or not history:
        raise ProviderWriteReleaseError("post-transfer predecessor readiness requires an authorised continuation")
    for item in history:
        if not isinstance(item, Mapping):
            raise ProviderWriteReleaseError("continuation history is malformed")
        row = dict(item)
        recorded = row.pop("record_sha256", None)
        if not isinstance(recorded, str) or not _HEX64.fullmatch(recorded) or recorded != _digest(row):
            raise ProviderWriteReleaseError("continuation history integrity check failed")
        origin = row.get("origin_preview_sha256")
        if (
            row.get("plan_hash") != context.get("plan_hash")
            or row.get("step") != context.get("current_step")
            or row.get("before_baseline_sha256") != current
            or not isinstance(origin, str)
            or not _HEX64.fullmatch(origin)
            or not isinstance(row.get("after_baseline_sha256"), str)
            or not _HEX64.fullmatch(row["after_baseline_sha256"])
        ):
            raise ProviderWriteReleaseError("continuation history does not form the current approved-step baseline chain")
        try:
            receipt = controller._controller_receipt(root, origin)
        except controller.ControllerError as exc:
            raise ProviderWriteReleaseError("continuation lacks its controller-authorised receipt") from exc
        receipt_binding = receipt.get("plan_binding")
        receipt_continuation = receipt.get("continuation")
        if (
            not isinstance(receipt_binding, Mapping)
            or not isinstance(receipt_continuation, Mapping)
            or receipt.get("operator") != name
            or receipt.get("transaction_id") != tx.get("transaction_id")
            or receipt.get("repository_authority") != "write"
            or receipt.get("before_baseline_sha256") != current
            or receipt.get("after_baseline_sha256") != row["after_baseline_sha256"]
            or receipt.get("project_changed") is not True
            or receipt.get("human_gate") is not None
            or receipt.get("next_action") != "continue-same-step"
            or not isinstance(receipt.get("provider_result"), Mapping)
            or receipt["provider_result"].get("status") != "PASS"
            or receipt.get("blocker_class") != "continuation"
            or receipt_binding.get("plan_hash") != context.get("plan_hash")
            or receipt_binding.get("current_step") != context.get("current_step")
            or receipt_binding.get("repository_mutation_scope") != list(context[planning.REPOSITORY_MUTATION_SCOPE_FIELD])
            or receipt_binding.get("repository_mutation_scope_sha256") != context.get(planning.REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD)
            or receipt_binding.get("step_authority_baseline_sha256") != current
            or any(receipt_continuation.get(key) != value for key, value in item.items())
        ):
            raise ProviderWriteReleaseError("continuation receipt is not an authorised current-step progression")
        current = row["after_baseline_sha256"]
    if current == initial or current != context.get("step_authority_baseline_sha256"):
        raise ProviderWriteReleaseError("continuation chain does not reach the live approved-step baseline")


def _successor_inputs(root: Path, record: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    binding_value = record.get("binding")
    if not isinstance(binding_value, Mapping):
        raise ProviderWriteReleaseError("native write-release binding is malformed")
    binding = dict(binding_value)
    # An outer record checksum cannot legitimise a contradictory transfer
    # intent. The approved scope and write flag are immutable release claims.
    if record.get("preview_sha256") != _digest(binding):
        raise ProviderWriteReleaseError("native write-release preview does not seal its exact binding")
    if (binding.get("schema") != PREVIEW_SCHEMA
        or binding.get("scope") != "ONE_APPROVED_PLAN_WRITE_TURN_PER_CURRENT_VALID_STEP"
        or binding.get("provider_write_turn") is not True
        or binding.get("confirmation") != "RELEASE_WRITE"):
        raise ProviderWriteReleaseError("native write-release binding does not grant the exact reviewed scope")
    tx, handoff, name = _lineage(root, str(record.get("operator") or ""))
    required = {"worktree": str(root), "source_revision": _git_head(root), "transaction_id": tx.get("transaction_id"),
        "transaction_record_sha256": tx.get("record_sha256"), "transaction_authority_baseline_sha256": tx.get("authority_baseline_sha256"),
        "operator": name, "handoff_preview_sha256": handoff.get("preview_sha256")}
    if any(binding.get(key) != value for key, value in required.items()):
        raise ProviderWriteReleaseError("preserved transaction or source lineage changed")
    predecessor, predecessor_ready = _predecessor_status(root, name, tx, handoff, require_ready=False)
    if not _same(binding.get("predecessor_installed"), predecessor):
        raise ProviderWriteReleaseError("original predecessor installed identity changed")
    release, selection = _policy(root, predecessor=False)
    required = {"planning_release_record_sha256": release.get("record_sha256"), "provider": provider_codex.PROVIDER_NAME,
        "model": selection.get("selected_model"), "effort": selection.get("selected_effort"), "planning_catalog_sha256": selection.get("catalog_sha256")}
    if any(binding.get(key) != value for key, value in required.items()):
        raise ProviderWriteReleaseError("preserved provider selection changed")
    active = controller._controller(root)
    assert active is not None
    if (active.get("enabled") is not True or active.get("operator") != name or active.get("transaction_id") != tx.get("transaction_id")
        or active.get("record_sha256") != binding.get("controller_record_sha256")):
        raise ProviderWriteReleaseError("controller lineage changed after predecessor transfer approval")
    context = _context(root, name, tx)
    required = {"approved_plan_hash": context.get("plan_hash"), "approval_baseline_sha256": context.get("approval_baseline_sha256"),
        "approved_mutation_scope": list(context[planning.REPOSITORY_MUTATION_SCOPE_FIELD]),
        "approved_mutation_scope_sha256": context.get(planning.REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD)}
    if any(binding.get(key) != value for key, value in required.items()):
        raise ProviderWriteReleaseError("approved plan identity or scope changed")
    if not predecessor_ready:
        if not _completed_transfer(record):
            raise ProviderWriteReleaseError("only a completed successor transfer may continue after predecessor readiness changes")
        _authorised_current_step_progression(root, binding, context, name, tx)
    predecessor = binding.get("predecessor_installed")
    expected_successor = binding.get("successor_installed")
    artifact = binding.get("successor_artifact")
    if (not isinstance(predecessor, Mapping) or tx.get("installed_command") != predecessor.get("executable")
        or not isinstance(expected_successor, Mapping) or not isinstance(artifact, Mapping)
        or not isinstance(artifact.get("path"), str)):
        raise ProviderWriteReleaseError("original predecessor or successor artifact identity is malformed")
    successor, actual = _successor_identity(root, Path(str(artifact["path"])))
    if not _same(successor, expected_successor):
        raise ProviderWriteReleaseError("successor installed identity changed after transfer preview")
    if not _same(actual, artifact):
        raise ProviderWriteReleaseError("successor wheel differs from the predecessor-approved artifact")
    if successor.get("executable") == predecessor.get("executable") or successor.get("package_file") == predecessor.get("package_file"):
        raise ProviderWriteReleaseError("successor must be a separate installed command and package")
    return binding, context


def _current_is(path: str) -> bool:
    try:
        return Path(path).resolve() == Path(sys.argv[0]).resolve()
    except OSError:
        return False


def _pending(root: Path) -> dict[str, Any]:
    value = _read(root, PENDING, required=True)
    assert value is not None
    if value.get("schema") != SCHEMA + "_pending":
        raise ProviderWriteReleaseError("unsupported native write-release pending schema")
    return _sealed(value, "native write-release pending record")


def _write_pending(root: Path, binding: Mapping[str, Any], digest: str, parent: int) -> None:
    pending = {"schema": SCHEMA + "_pending", "preview_sha256": digest, "parent_pid": parent, "binding": dict(binding),
        "predecessor_execution_authorised": False, "successor_execution_authorised": False}
    pending["record_sha256"] = _digest(pending)
    adoption.write_runtime_record(root, PENDING, pending, actor="controller")
    if _pending(root) != pending:
        raise ProviderWriteReleaseError("native write-release pending transfer did not persist exactly")


def _commit(project: Path, operator: str, artifact: Path, preview_sha256: str, confirmation: str, parent_pid: int) -> dict[str, Any]:
    if confirmation != "COMPLETE_WRITE_TRANSFER":
        raise ProviderWriteReleaseError("fresh successor confirmation required: COMPLETE_WRITE_TRANSFER")
    expected = transactions._require_digest(preview_sha256, "--preview")
    root = adoption.resolve_worktree(project)
    if parent_pid <= 0 or parent_pid == os.getpid() or parent_pid != os.getppid():
        raise ProviderWriteReleaseError("write-release commit requires a separately started parent process")
    with _transfer_lock(root):
        pending = _pending(root)
        if pending.get("preview_sha256") != expected or pending.get("parent_pid") != parent_pid:
            raise ProviderWriteReleaseError("fresh successor received a different transfer intent")
        binding = pending.get("binding") if isinstance(pending.get("binding"), Mapping) else {}
        if binding.get("operator") != controller._operator(operator) or str(binding.get("successor_artifact", {}).get("path") or "") != str(Path(artifact).resolve()):
            raise ProviderWriteReleaseError("fresh successor differs from transfer intent")
        binding, _ = _successor_inputs(root, {"operator": operator, "binding": binding, "preview_sha256": expected})
        successor = lifecycle._installed_identity(root)
        if not _current_is(str(successor["executable"])):
            raise ProviderWriteReleaseError("fresh process executable differs from installed successor")
        record = {"schema": SCHEMA, "preview_sha256": expected, "operator": binding["operator"], "parent_pid": parent_pid,
            "fresh_process": {"pid": os.getpid(), "executable": successor["executable"], "package_file": successor["package_file"]},
            "binding": binding, "transition_complete": True, "predecessor_execution_authorised": False,
            "successor_execution_authorised": True, "final_qualification_claimed": False, "installed_successor_transition_claimed": False}
        record["record_sha256"] = _digest(record)
        adoption.write_runtime_record(root, RECORD, record, actor="controller")
        if _release_record(root) != record:
            raise ProviderWriteReleaseError("native write-release receipt did not persist exactly")
        path = _runtime_file(root, PENDING)
        if path.is_symlink() or not path.is_file():
            raise ProviderWriteReleaseError("native write-release pending transfer changed during completion")
        try:
            path.unlink()
        except OSError as exc:
            raise ProviderWriteReleaseError("native write-release transfer interrupted; authority remains denied") from exc
    return record


def release(project: Path, operator: str, artifact: Path, preview_sha256: str, confirmation: str, successor: Path) -> dict[str, Any]:
    if confirmation != "RELEASE_WRITE":
        raise ProviderWriteReleaseError("explicit confirmation required: RELEASE_WRITE")
    expected = transactions._require_digest(preview_sha256, "--preview")
    successor = Path(successor)
    if not successor.is_absolute() or successor.is_symlink() or not successor.is_file():
        raise ProviderWriteReleaseError("successor executable must be a separate regular absolute file")
    root = adoption.resolve_worktree(project)
    with _transfer_lock(root):
        current = preview(root, operator, artifact)
        if current["preview_sha256"] != expected:
            raise ProviderWriteReleaseError("native write-release preview is stale; binding or artifact changed")
        if str(successor.resolve()) != str(current["successor_installed"]["executable"]):
            raise ProviderWriteReleaseError("fresh successor executable differs from the previewed successor")
        _write_pending(root, {k: v for k, v in current.items() if k not in {"preview_sha256", "requires_explicit_confirmation"}}, expected, os.getpid())
    env = os.environ.copy()
    env["PATH"] = str(successor.parent) + os.pathsep + env.get("PATH", "")
    child = subprocess.run([str(successor), "provider-write-release", "commit", "--project", str(root), "--operator", current["operator"],
        "--artifact", str(Path(artifact).resolve()), "--preview", expected, "--confirm", "COMPLETE_WRITE_TRANSFER", "--parent-pid", str(os.getpid())],
        cwd=str(root), env=env, text=True, capture_output=True, check=False)
    if child.returncode != 0:
        raise ProviderWriteReleaseError("fresh installed write-release validation failed: " + ((child.stderr or child.stdout).strip() or str(child.returncode)))
    try:
        received = json.loads(child.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderWriteReleaseError("fresh installed write-release returned an invalid receipt") from exc
    committed = _release_record(root)
    if _read(root, PENDING) is not None or received != committed or committed.get("preview_sha256") != expected or committed.get("parent_pid") != os.getpid():
        raise ProviderWriteReleaseError("fresh installed write-release receipt is not the committed exact receipt")
    fresh = committed.get("fresh_process") if isinstance(committed.get("fresh_process"), Mapping) else {}
    if fresh.get("pid") == os.getpid() or fresh.get("executable") != str(successor):
        raise ProviderWriteReleaseError("fresh installed write-release did not prove the named successor")
    return committed


def execution_ready(project: Path, *, preview_sha256: str | None = None) -> bool:
    try:
        root = adoption.resolve_worktree(project)
        if _read(root, PENDING) is not None:
            return False
        record = _release_record(root)
        if not _completed_transfer(record):
            return False
        _successor_inputs(root, record)
        return preview_sha256 is None or record.get("preview_sha256") == preview_sha256
    except (ProviderWriteReleaseError, adoption.AdoptionError, controller.ControllerError, execution_policy.ExecutionPolicyError, transactions.TransactionError, OSError, TypeError, ValueError):
        return False


def require_controller_authority(project: Path, *, operator: str, plan_binding: Mapping[str, Any]) -> None:
    root = adoption.resolve_worktree(project)
    if _read(root, PENDING) is not None:
        raise ProviderWriteReleaseError("native write authority is interrupted")
    record = _release_record(root)
    binding, context = _successor_inputs(root, record)
    supplied = {"operator": controller._operator(operator), "transaction_id": plan_binding.get("transaction_id"),
        "approved_plan_hash": plan_binding.get("plan_hash"), "current_step": plan_binding.get("current_step"),
        "step_id": plan_binding.get("step_id"), "step_objective": plan_binding.get("step_objective"),
        "approved_mutation_scope": plan_binding.get("repository_mutation_scope"),
        "approved_mutation_scope_sha256": plan_binding.get("repository_mutation_scope_sha256"),
        "step_authority_baseline_sha256": plan_binding.get("step_authority_baseline_sha256")}
    actual = {"operator": binding.get("operator"), "transaction_id": context.get("transaction_id"), "approved_plan_hash": context.get("plan_hash"),
        "current_step": context.get("current_step"), "step_id": context.get("step", {}).get("id"),
        "step_objective": context.get("step", {}).get("objective"),
        "approved_mutation_scope": list(context[planning.REPOSITORY_MUTATION_SCOPE_FIELD]),
        "approved_mutation_scope_sha256": context.get(planning.REPOSITORY_MUTATION_SCOPE_DIGEST_FIELD),
        "step_authority_baseline_sha256": context.get("step_authority_baseline_sha256")}
    if supplied != actual:
        raise ProviderWriteReleaseError("controller turn is not the current exact released transaction/plan/step/scope")


@contextmanager
def authorised_write_turn(project: Path, *, operator: str, plan_binding: Mapping[str, Any]) -> Iterator[None]:
    root = adoption.resolve_worktree(project)
    require_controller_authority(root, operator=operator, plan_binding=plan_binding)
    token = _write_turn.set((str(root), _release_record(root)["preview_sha256"]))
    try:
        yield
    finally:
        _write_turn.reset(token)


def dispatch_allowed(cwd: Path, purpose: str) -> bool:
    try:
        candidate = Path(cwd).resolve()
        # This gate is reached for every provider launch attempt.  An
        # arbitrary path with no regular runtime directory cannot possibly
        # hold a completed transfer, so reject it without spawning Git.
        runtime = candidate / adoption.RUNTIME_NAME
        if runtime.is_symlink() or not runtime.is_dir():
            return False
        root = adoption.resolve_worktree(candidate)
        state = _write_turn.get()
        # Quota admission occurs before the controller enters the write-turn
        # context.  It may read only rate-limit metadata, and only after the
        # completed successor transfer has independently revalidated all of
        # its immutable lineage and the live approved step.
        if purpose == "quota":
            return root == candidate and execution_ready(root)
        return (purpose in {"catalogue", "sandbox", "write-turn"} and root == candidate and state is not None
            and state[0] == str(root) and execution_ready(root, preview_sha256=state[1]))
    except (ProviderWriteReleaseError, adoption.AdoptionError, OSError, ValueError):
        return False


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stygnox provider-write-release")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("preview", "release", "commit", "status"):
        item = sub.add_parser(action)
        item.add_argument("--project", type=Path, required=True)
        if action != "status": item.add_argument("--operator", required=True)
        if action != "status": item.add_argument("--artifact", type=Path, required=True)
        if action == "release": item.add_argument("--successor", type=Path, required=True)
        if action in {"release", "commit"}:
            item.add_argument("--preview", required=True); item.add_argument("--confirm", required=True)
        if action == "commit": item.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview": result = preview(args.project, args.operator, args.artifact)
        elif args.action == "release": result = release(args.project, args.operator, args.artifact, args.preview, args.confirm, args.successor)
        elif args.action == "commit": result = _commit(args.project, args.operator, args.artifact, args.preview, args.confirm, args.parent_pid)
        else:
            root = adoption.resolve_worktree(args.project)
            result = {"write_execution_ready": execution_ready(root), "release": _read(root, RECORD), "pending": _read(root, PENDING)}
    except (ProviderWriteReleaseError, adoption.AdoptionError, controller.ControllerError, execution_policy.ExecutionPolicyError, transactions.TransactionError) as exc:
        parser.exit(2, f"stygnox: provider write release refused: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0
