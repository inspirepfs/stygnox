"""D8.3 transactional authority, safe stop, and baseline restoration."""
from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
from typing import Any

from . import adoption, runtime
from .direct_interruption_execution_guard import QuarantinedRuntime, refuse_quarantined_runtime
from .product import PRODUCT
from .recovery import (
    RecoveryError,
    ensure_runtime_local_ignore,
    load_internal_checkpoint,
    restore_external,
    restore_internal,
    sha256_file,
    verify_operator_dirty_package,
)


TRANSACTION_SCHEMA = "stygnox_transaction_v1"
RECOVERY_PREVIEW_SCHEMA = "stygnox_recovery_preview_v1"
RENEWAL_PREVIEW_SCHEMA = "stygnox_transaction_renewal_preview_v1"
RECOVERY_RESULT_SCHEMA = "stygnox_recovery_result_v1"
TRANSACTION_RECORD = "transaction.json"
RECOVERY_RESULT_RECORD = "recovery-result.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_STOP_REASONS = {"interrupted", "operator-abort", "authority-revoked", "qualification"}


class TransactionError(RuntimeError):
    """Fail-closed transaction/recovery error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), indent=2, sort_keys=True) + "\n"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _operator(value: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 128 or any(ord(char) < 32 for char in name):
        raise TransactionError("--operator must be 1-128 printable characters")
    return name


def _require_digest(value: str, option: str) -> str:
    digest = str(value or "").strip().lower()
    if not _HEX64.fullmatch(digest):
        raise TransactionError(f"{option} must be an exact 64-character SHA-256")
    return digest


def _runtime_json(root: Path, name: str, *, required: bool = True) -> dict[str, Any] | None:
    try:
        value = runtime.read_json_object(
            runtime.CanonicalProjectRoot.from_path(root),
            runtime.SafeRelativePath.parse(f"{adoption.RUNTIME_NAME}/{name}"),
            required=required,
        )
    except runtime.RuntimeRecordMissing as exc:
        raise TransactionError(f"required Stygnox runtime record is missing: {name}") from exc
    except runtime.RuntimeContractError as exc:
        raise TransactionError(f"invalid Stygnox runtime record {name}: {exc}") from exc
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TransactionError(f"Stygnox runtime record {name} must be an object")
    return value


def _load_adoption(root: Path) -> dict[str, Any]:
    record = _runtime_json(root, "adoption.json")
    assert record is not None
    if record.get("schema") != adoption.HANDOFF_SCHEMA:
        raise TransactionError("unsupported adoption handoff record")
    if not isinstance(record.get("baseline"), dict) or not isinstance(record.get("authority_baseline"), dict):
        raise TransactionError("handoff predates D8.3 recovery bindings; perform a fresh adoption handoff")
    if record.get("baseline_sha256") != record["baseline"].get("sha256"):
        raise TransactionError("adoption baseline binding is invalid")
    return record


def _transaction(root: Path, *, required: bool = True) -> dict[str, Any] | None:
    value = _runtime_json(root, TRANSACTION_RECORD, required=required)
    if value is None:
        return None
    if value.get("schema") != TRANSACTION_SCHEMA:
        raise TransactionError("unsupported transaction runtime record")
    return value


def _renewal_record(root: Path, name: str, schema: str) -> dict[str, Any]:
    """Read a required, integrity-bound renewal input without repairing it."""
    try:
        record = _runtime_json(root, name)
    except TransactionError as exc:
        raise TransactionError(f"renewal requires a regular predecessor record: {name}: {exc}") from exc
    assert record is not None
    if record.get("schema") != schema:
        raise TransactionError(f"unsupported renewal predecessor schema: {name}")
    body = dict(record)
    recorded = body.pop("record_sha256", None)
    if not isinstance(recorded, str) or not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise TransactionError(f"renewal predecessor integrity check failed: {name}")
    return record


def _renewal_stopped_transaction(root: Path, operator: str) -> dict[str, Any]:
    """Read and validate safe-stop evidence, without granting renewal authority.

    Renewal must additionally validate adoption/recovery lineage, revoked
    controller authority, terminal plan proof, scheduler ownership, outstanding
    obligations and installed identity before publishing any successor.
    """
    transaction = _renewal_record(root, TRANSACTION_RECORD, TRANSACTION_SCHEMA)
    if transaction.get("state") != "STOPPED":
        raise TransactionError("renewal requires a STOPPED predecessor transaction")
    if transaction.get("operator") != _operator(operator):
        raise TransactionError("renewal operator does not match predecessor transaction")
    identifier = transaction.get("transaction_id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise TransactionError("renewal predecessor transaction identifier is missing")
    for key in ("handoff_preview_sha256", "pre_authority_baseline_sha256", "authority_baseline_sha256"):
        value = transaction.get(key)
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise TransactionError(f"renewal predecessor lacks exact {key}")
    command = transaction.get("installed_command")
    if not isinstance(command, str) or not Path(command).is_absolute():
        raise TransactionError("renewal predecessor installed command is invalid")
    journey = transaction.get("journey")
    if journey not in ("clean", "dirty", "new-unborn"):
        raise TransactionError("renewal predecessor recovery journey is invalid")
    source = transaction.get("recovery_source")
    if not isinstance(source, dict) or source.get("baseline_sha256") != transaction["pre_authority_baseline_sha256"]:
        raise TransactionError("renewal predecessor recovery lineage is missing or inconsistent")
    source_kind = "operator-external" if journey == "dirty" else "controller-internal"
    if source.get("kind") != source_kind:
        raise TransactionError("renewal predecessor recovery source kind is inconsistent")
    digests = ("attestation_sha256", "capture_sha256", "manifest_sha256") if journey == "dirty" else ("checkpoint_sha256",)
    for key in digests:
        if not isinstance(source.get(key), str) or not _HEX64.fullmatch(source[key]):
            raise TransactionError(f"renewal predecessor recovery source lacks {key}")
    if journey == "dirty":
        for key in ("attestation_path", "capture_path", "manifest_path"):
            if not isinstance(source.get(key), str) or not Path(source[key]).is_absolute():
                raise TransactionError(f"renewal predecessor recovery source lacks {key}")
    authority = transaction.get("authority")
    if (
        not isinstance(authority, dict)
        or authority.get("scope") != "d8.3-transaction-and-recovery-only"
        or authority.get("controller_execution") is not False
        or authority.get("safe_stop_required_before_restore") is not True
    ):
        raise TransactionError("renewal predecessor transaction authority is invalid")
    stop = transaction.get("safe_stop")
    if not isinstance(stop, dict):
        raise TransactionError("renewal requires valid safe-stop evidence")
    reason = stop.get("reason")
    if (
        not isinstance(reason, str) or reason not in _ALLOWED_STOP_REASONS
        or stop.get("authority_revoked") is not True
        or stop.get("project_mutation") is not False
    ):
        raise TransactionError("renewal safe-stop revocation evidence is invalid")
    stopped_at = stop.get("stopped_at")
    opened_at = transaction.get("opened_at")
    try:
        if not isinstance(stopped_at, str) or datetime.fromisoformat(stopped_at).utcoffset() is None:
            raise ValueError("missing timezone")
        if not isinstance(opened_at, str) or datetime.fromisoformat(opened_at).utcoffset() is None:
            raise ValueError("missing opening timestamp/timezone")
        if datetime.fromisoformat(opened_at) > datetime.fromisoformat(stopped_at):
            raise ValueError("safe stop predates transaction")
    except ValueError as exc:
        raise TransactionError("renewal safe-stop timestamp is invalid") from exc
    baseline = stop.get("baseline")
    required = {
        "worktree", "journey", "head", "branch", "status", "index_sha256",
        "staged_sha256", "unstaged_sha256", "untracked", "dirty_categories", "sha256",
    }
    if not isinstance(baseline, dict) or not required.issubset(baseline):
        raise TransactionError("renewal safe-stop baseline is incomplete")
    baseline_body = dict(baseline)
    baseline_digest = baseline_body.pop("sha256")
    if baseline.get("worktree") != str(root.resolve()) or baseline_digest != _digest(baseline_body):
        raise TransactionError("renewal safe-stop project/baseline binding is invalid")
    if (
        baseline.get("journey") not in ("clean", "dirty", "new-unborn")
        or not isinstance(baseline.get("branch"), str) or not baseline["branch"]
        or not isinstance(baseline.get("status"), str)
        or not isinstance(baseline.get("untracked"), list)
        or not isinstance(baseline.get("dirty_categories"), list)
        or any(not isinstance(baseline[key], str) or not _HEX64.fullmatch(baseline[key])
               for key in ("index_sha256", "staged_sha256", "unstaged_sha256"))
    ):
        raise TransactionError("renewal safe-stop baseline fields are invalid")
    head = baseline["head"]
    if head is not None and (not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head)):
        raise TransactionError("renewal safe-stop Git head is invalid")
    expected_journey = "new-unborn" if head is None else "dirty" if baseline["status"] else "clean"
    if baseline["journey"] != expected_journey or baseline["dirty_categories"] != list(adoption._status_categories(baseline["status"])):
        raise TransactionError("renewal safe-stop Git baseline is inconsistent")
    if bool(baseline["untracked"]) != ("untracked" in baseline["dirty_categories"]):
        raise TransactionError("renewal safe-stop untracked evidence is inconsistent")
    seen: set[str] = set()
    for row in baseline["untracked"]:
        if not isinstance(row, dict):
            raise TransactionError("renewal safe-stop untracked evidence is malformed")
        relative = row.get("path")
        if (
            not isinstance(relative, str) or not relative or "\x00" in relative
            or Path(relative).is_absolute() or ".." in Path(relative).parts
            or relative in seen or row.get("type") not in ("file", "symlink")
            or not isinstance(row.get("mode"), str) or not re.fullmatch(r"[0-7]{4}", row["mode"])
            or not isinstance(row.get("sha256"), str) or not _HEX64.fullmatch(row["sha256"])
        ):
            raise TransactionError("renewal safe-stop untracked evidence is malformed")
        seen.add(relative)
    return transaction


def _renewal_predecessor_authority(root: Path, operator: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate stopped/revoked authority; this alone does not permit renewal.

    Adoption and recovery artifacts, terminal plan proof, obligations, scheduler
    quiescence, Git and installed identity still need independent validation.
    """
    from . import controller

    transaction = _renewal_stopped_transaction(root, operator)
    revoked = _renewal_record(root, controller.CONTROLLER_RECORD, controller.CONTROLLER_SCHEMA)
    if (
        revoked.get("enabled") is not False
        or revoked.get("controller_execution_enabled") is not False
        or revoked.get("deactivation_reason") != "operator-confirmed"
    ):
        raise TransactionError("renewal requires explicitly revoked controller execution")
    for key in ("operator", "transaction_id", "authority_baseline_sha256", "installed_command"):
        if revoked.get(key) != transaction[key]:
            raise TransactionError(f"renewal predecessor controller/transaction lineage changed: {key}")
    return transaction, revoked


def _renewal_adoption_lineage(root: Path, transaction: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the original handoff and recovery material without publishing.

    Handoffs predate record_sha256. Their embedded baselines and recovery
    bindings must therefore be checked against the integrity-validated stopped
    transaction, rather than treating a handoff schema label as evidence.
    Terminal proof and current installed identity are separate prerequisites.
    """
    from . import recovery

    runtime_dir = root / adoption.RUNTIME_NAME
    try:
        try:
            handoff = _load_adoption(root)
        except TransactionError as exc:
            raise TransactionError("renewal requires a regular adoption handoff") from exc
        for key, transaction_key in (
            ("operator", "operator"), ("preview_sha256", "handoff_preview_sha256"),
            ("baseline_sha256", "pre_authority_baseline_sha256"), ("journey", "journey"),
        ):
            if handoff.get(key) != transaction.get(transaction_key):
                raise TransactionError(f"renewal adoption/transaction lineage changed: {key}")
        for key in ("baseline", "authority_baseline"):
            baseline = dict(handoff[key])
            recorded = baseline.pop("sha256", None)
            if (
                not isinstance(recorded, str) or not _HEX64.fullmatch(recorded)
                or recorded != _digest(baseline)
                or baseline.get("worktree") != str(root.resolve())
            ):
                raise TransactionError(f"renewal adoption {key} integrity/project binding is invalid")
        if handoff["baseline"].get("journey") != transaction["journey"]:
            raise TransactionError("renewal adoption recovery journey changed")
        if handoff["authority_baseline"]["sha256"] != transaction.get("authority_baseline_sha256"):
            raise TransactionError("renewal adoption authority baseline differs from predecessor transaction")
        source = handoff.get("recovery_source")
        original = transaction.get("recovery_source")
        if not isinstance(source, dict) or not isinstance(original, dict):
            raise TransactionError("renewal adoption recovery source is missing")
        # The handoff stores fewer external-package fields than begin records.
        keys = ("kind", "baseline_sha256", "attestation_path", "attestation_sha256",
                "capture_path", "capture_sha256") if transaction["journey"] == "dirty" else (
                    "kind", "baseline_sha256", "checkpoint_sha256",
                )
        if any(key not in source or source[key] != original.get(key) for key in keys):
            raise TransactionError("renewal adoption recovery source changed")
        if transaction["journey"] != "dirty":
            directory = runtime_dir / recovery.INTERNAL_RECOVERY_DIR
            if directory.is_symlink() or not directory.is_dir():
                raise TransactionError("renewal requires a regular recovery directory")
            for filename in (recovery.INTERNAL_METADATA, recovery.INTERNAL_ARCHIVE, recovery.INTERNAL_INDEX):
                if (directory / filename).is_symlink():
                    raise TransactionError("renewal recovery artifacts must not be symlinks")
            # Validate paths before the existing loader can follow metadata.
            metadata_path = directory / recovery.INTERNAL_METADATA
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if (
                not isinstance(metadata, dict)
                or metadata.get("archive") != recovery.INTERNAL_ARCHIVE
                or metadata.get("index") not in (None, recovery.INTERNAL_INDEX)
                or metadata.get("baseline") != handoff["baseline"]
            ):
                raise TransactionError("renewal recovery checkpoint lineage/paths are invalid")
        else:
            for key in ("attestation_path", "capture_path", "manifest_path"):
                artifact = Path(original[key])
                if artifact.is_symlink() or not artifact.is_file():
                    raise TransactionError("renewal external recovery artifact is not a regular file")
        verified = _recovery_source(root, handoff)
        if verified != original:
            raise TransactionError("renewal verified recovery source differs from original transaction")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise TransactionError("malformed renewal adoption/recovery evidence") from exc
    return handoff


def _renewal_installed_identity(root: Path, transaction: Mapping[str, Any]) -> dict[str, Any]:
    """Capture verified distribution and launcher bytes for a renewal digest.

    This read-only prerequisite grants no authority. The eventual renewal
    preview must bind this entire value and recapture it before publication.
    Reuse the installed rebind verifier without changing its identity contract;
    renewal additionally hashes the launcher, which pip may omit from RECORD.
    """
    from . import lifecycle

    try:
        identity = lifecycle._installed_identity(root)
        if identity["executable"] != transaction.get("installed_command"):
            raise TransactionError("renewal installed command differs from predecessor transaction")
        executable = Path(identity["executable"])
        if executable.is_symlink() or not executable.is_file():
            raise TransactionError("renewal installed command must be a regular file")
        return {**identity, "executable_sha256": sha256_file(executable)}
    except (lifecycle.LifecycleError, adoption.AdoptionError, OSError, UnicodeError, ValueError) as exc:
        raise TransactionError(f"renewal installed identity verification failed: {exc}") from exc


def build_renewal_preview(project: Path, operator: str) -> dict[str, Any]:
    """Bind a proposed fresh epoch without writing or granting any authority.

    Publication must rebuild this preview and require its exact digest. The
    runtime inventory binds historical evidence as well as the live records;
    capturing it twice refuses changes during the read-only validation pass.
    """
    from . import finalization, lifecycle, planning, qualification, scheduler

    root = adoption.resolve_worktree(project)
    try:
        refuse_quarantined_runtime(root)
    except QuarantinedRuntime as exc:
        raise TransactionError(str(exc)) from exc
    name = _operator(operator)
    try:
        inventory = lifecycle._runtime_inventory(root)
        transaction, revoked = _renewal_predecessor_authority(root, name)
        handoff = _renewal_adoption_lineage(root, transaction)
        state = planning._renewal_plan_obligations(
            root, name, transaction_id=transaction["transaction_id"],
        )
        baseline = adoption.capture_baseline(root).public()
        if baseline != transaction["safe_stop"]["baseline"]:
            raise TransactionError("renewal Git baseline changed after safe stop")
        if state.get("transaction_recovery_baseline_sha256") != transaction["authority_baseline_sha256"]:
            raise TransactionError("renewal plan recovery lineage differs from predecessor transaction")
        released = scheduler.renewal_quiescence(
            root, name, transaction_id=transaction["transaction_id"], plan_hash=state["plan_hash"],
        )
        # These cases remain closed until their receipt/rebase semantics are
        # integrated. An IDLE label or COMPLETE transition label is not proof.
        if state["status"] == "IDLE":
            raise TransactionError("renewal retired-plan proof is not yet supported")
        if any(row.get("post_qualification_transition") is not None for row in state["step_results"]):
            raise TransactionError("renewal required-transition receipt validation is not yet supported")
        final = finalization._final_qualification(state)
        if final.get("plan_hash") != state["plan_hash"]:
            raise TransactionError("renewal final qualification belongs to another plan")
        proof: dict[str, Any] = {"status": state["status"], "final_qualification": final}
        if state["status"] == "READ_ONLY_COMPLETE":
            if final["plan_owned_paths"] or final["qualified_path_fingerprints"]:
                raise TransactionError("renewal read-only completion contains repository mutations")
            finalization._current_qualified_tree(root, final)
        else:
            commit = finalization._commit_record(state)
            if (
                commit.get("commit_sha") != baseline["head"]
                or commit.get("branch") != baseline["branch"]
                or commit.get("plan_hash") != state["plan_hash"]
            ):
                raise TransactionError("renewal commit evidence differs from current Git/plan baseline")
            finalization._verify_commit(root, state, final, commit["commit_sha"])
            if finalization._plan_owned_dirty(root, final["plan_owned_paths"]):
                raise TransactionError("renewal committed paths changed after qualification")
            proof["commit"] = commit
            if state["status"] == "PUSHED":
                push = state.get("push_record")
                if not isinstance(push, dict) or push.get("schema") != finalization.PUSH_RECORD_SCHEMA:
                    raise TransactionError("renewal PUSHED predecessor lacks push evidence")
                body = dict(push)
                recorded = body.pop("record_sha256", None)
                if (
                    recorded != _digest(body) or push.get("commit_sha") != commit["commit_sha"]
                    or push.get("plan_hash") != state["plan_hash"]
                    or push.get("commit_record_sha256") != commit["record_sha256"]
                ):
                    raise TransactionError("renewal push evidence integrity/lineage changed")
                # Bind recorded push evidence only; never contact a remote here.
                proof["push"] = push
        attribution = qualification._attribution_guard(root)
        recovery_result = root / adoption.RUNTIME_NAME / RECOVERY_RESULT_RECORD
        if recovery_result.exists() or recovery_result.is_symlink():
            raise TransactionError("renewal refuses an unreconciled recovery result")
        installed = _renewal_installed_identity(root, transaction)
        epoch = transaction.get("plan_epoch", 0)
        if type(epoch) is not int or epoch < 0:
            raise TransactionError("renewal predecessor plan epoch is invalid")
        preview: dict[str, Any] = {
            "schema": RENEWAL_PREVIEW_SCHEMA,
            "operator": name,
            "worktree": str(root),
            "predecessor": {"transaction": transaction, "controller": revoked, "plan": state},
            "adoption": handoff,
            "recovery_source": transaction["recovery_source"],
            "terminal_proof": proof,
            "obligations": {"scheduler": released, "attribution": attribution, "recovery_result": None},
            "baseline": baseline,
            "installed_identity": installed,
            "runtime_inventory": inventory,
            "successor": {
                "plan_epoch": epoch + 1,
                "plan_status": "IDLE",
                "transaction_state": "ACTIVE",
                "authority_baseline_sha256": baseline["sha256"],
                "pre_authority_baseline_sha256": transaction["pre_authority_baseline_sha256"],
                "controller_execution_enabled": False,
                "execution_authority_granted": False,
                "plan_approval": None,
                "self_development_grant": None,
                "provider_attribution": None,
                "historical_path_ownership": [],
            },
            "requires_explicit_confirmation": True,
            "confirmation": "RENEW",
        }
        successor_binding = _digest(preview)
        preview["successor"]["transaction_id"] = "TX-" + successor_binding[:16]
        preview["successor"]["plan_epoch_id"] = "PE-" + successor_binding
        if (
            inventory != lifecycle._runtime_inventory(root)
            or baseline != adoption.capture_baseline(root).public()
            or installed != _renewal_installed_identity(root, transaction)
        ):
            raise TransactionError("renewal evidence changed while building preview; retry")
        preview["preview_sha256"] = _digest(preview)
        return preview
    except (
        finalization.FinalizationError, lifecycle.LifecycleError, planning.PlanningError,
        qualification.QualificationError, scheduler.SchedulerError, RecoveryError,
        OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError,
    ) as exc:
        raise TransactionError(f"renewal preview refused: {exc}") from exc


def renew_transaction(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    """Archive exact predecessor bytes, then publish an unapproved fresh epoch.

    The ACTIVE transaction is the final publication write. Until it succeeds,
    the stopped transaction prevents activation. Afterwards the unchanged,
    revoked controller and IDLE plan still prevent execution. No rollback can
    resurrect predecessor authority after an interrupted publication.
    """
    from . import lifecycle, planning

    if confirmation != "RENEW":
        raise TransactionError("explicit confirmation required: --confirm RENEW")
    expected = _require_digest(preview_sha256, "--preview")
    root = adoption.resolve_worktree(project)
    try:
        refuse_quarantined_runtime(root)
    except QuarantinedRuntime as exc:
        raise TransactionError(str(exc)) from exc
    runtime = root / adoption.RUNTIME_NAME
    if runtime.is_symlink() or not runtime.is_dir():
        raise TransactionError("renewal requires a regular runtime directory")
    # Lock the directory inode: no lock file is added to preview evidence.
    descriptor = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preview = build_renewal_preview(root, operator)
        if preview["preview_sha256"] != expected:
            raise TransactionError("renewal preview is stale; preview and confirm again")
        predecessor = preview["predecessor"]["transaction"]
        successor = preview["successor"]
        archive_name = f"renewal-predecessor-{expected}.json"
        archive_path = runtime / archive_name
        if archive_path.exists() or archive_path.is_symlink():
            raise TransactionError("renewal predecessor archive already exists")
        files = []
        for row in preview["runtime_inventory"]:
            payload = (root / row["path"]).read_bytes()
            if len(payload) != row["size"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise TransactionError("renewal evidence changed while preserving predecessor")
            files.append({**row, "content_base64": base64.b64encode(payload).decode("ascii")})
        archive = {
            "schema": "stygnox_transaction_renewal_archive_v1",
            "preview": preview, "files": files, "historical_evidence_only": True,
        }
        archive["record_sha256"] = _digest(archive)
        # Recapture all bindings immediately before the first persistence write.
        if build_renewal_preview(root, operator) != preview:
            raise TransactionError("renewal evidence changed before preservation")
        adoption.write_runtime_record(root, archive_name, archive, actor="controller")
        if _renewal_record(root, archive_name, archive["schema"]) != archive:
            raise TransactionError("renewal predecessor preservation failed verification")
        if (
            lifecycle._runtime_inventory(root, exclude={f"{adoption.RUNTIME_NAME}/{archive_name}"})
            != preview["runtime_inventory"]
            or adoption.capture_baseline(root).public() != preview["baseline"]
            or _renewal_installed_identity(root, predecessor) != preview["installed_identity"]
        ):
            raise TransactionError("renewal evidence changed before publication")
        # Build from an allowlist: grants and provider attribution never carry.
        transaction = {
            key: predecessor[key] for key in (
                "schema", "operator", "handoff_preview_sha256", "pre_authority_baseline_sha256",
                "journey", "installed_command", "recovery_source", "authority",
            )
        }
        transaction.update({
            "product_version": PRODUCT.version, "state": "ACTIVE", "opened_at": _now(),
            "safe_stop": None, "transaction_id": successor["transaction_id"],
            "plan_epoch": successor["plan_epoch"], "plan_epoch_id": successor["plan_epoch_id"],
            "authority_baseline_sha256": preview["baseline"]["sha256"],
            "predecessor_transaction_id": predecessor["transaction_id"],
            "renewal_preview_sha256": expected, "predecessor_archive": archive_name,
            "predecessor_archive_sha256": archive["record_sha256"],
        })
        transaction["record_sha256"] = _digest(transaction)
        adoption.write_runtime_record(root, planning.PLAN_RECORD, planning._renewal_epoch(preview), actor="controller")
        adoption.write_runtime_record(root, TRANSACTION_RECORD, transaction, actor="controller")
        return {**transaction, "result": "TRANSACTION_RENEWED"}
    except (OSError, lifecycle.LifecycleError, planning.PlanningError) as exc:
        raise TransactionError(f"renewal publication refused: {exc}") from exc
    finally:
        os.close(descriptor)


def successor_transaction(predecessor: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    """Create, but do not persist, a successor authority record for a rebind."""
    previous = dict(predecessor)
    recorded = previous.pop("record_sha256", None)
    if not isinstance(recorded, str) or recorded != _digest(previous):
        raise TransactionError("predecessor transaction integrity check failed")
    artifact = binding.get("candidate_artifact")
    identity = binding.get("installed_identity")
    if not isinstance(artifact, Mapping) or not isinstance(identity, Mapping):
        raise TransactionError("successor transaction lacks installed artifact identity")
    body = dict(previous)
    body.update({
        "transaction_id": "TX-RB-" + _digest({"predecessor": recorded, "epoch": binding.get("new_runtime_epoch"), "artifact": artifact.get("sha256")})[:16],
        "state": "ACTIVE",
        "installed_command": identity.get("executable"),
        "successor_of_transaction_record_sha256": recorded,
        "rebind_binding": dict(binding),
    })
    body["record_sha256"] = _digest(body)
    return body


def _recovery_source(root: Path, handoff: Mapping[str, Any]) -> dict[str, Any]:
    source = handoff.get("recovery_source")
    if not isinstance(source, dict):
        raise TransactionError("handoff lacks a D8.3 recovery source binding")
    try:
        if handoff.get("journey") == "dirty":
            attestation = Path(str(source.get("attestation_path") or "")).expanduser().resolve()
            if not attestation.is_file() or sha256_file(attestation) != source.get("attestation_sha256"):
                raise TransactionError("dirty recovery attestation changed after confirmed handoff")
            verified = verify_operator_dirty_package(root, attestation, handoff["baseline"])
            if verified.get("capture_sha256") != source.get("capture_sha256"):
                raise TransactionError("dirty recovery capture changed after confirmed handoff")
            return verified
        metadata = load_internal_checkpoint(root, str(source.get("checkpoint_sha256") or ""))
        return {
            "kind": "controller-internal",
            "checkpoint_sha256": metadata["checkpoint_sha256"],
            "baseline_sha256": metadata["baseline"]["sha256"],
        }
    except RecoveryError as exc:
        raise TransactionError(str(exc)) from exc


def begin_transaction(project: Path, operator: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "BEGIN":
        raise TransactionError("explicit confirmation required: --confirm BEGIN")
    root = adoption.resolve_worktree(project)
    handoff = _load_adoption(root)
    name = _operator(operator)
    if name != handoff.get("operator"):
        raise TransactionError("transaction operator must match the confirmed adoption handoff")
    existing = _transaction(root, required=False)
    if existing is not None and existing.get("state") not in {"RECOVERED"}:
        raise TransactionError(f"transaction already exists in state {existing.get('state')}")

    current = adoption.capture_baseline(root).public()
    if current.get("sha256") != handoff["authority_baseline"].get("sha256"):
        raise TransactionError("project changed after handoff; transaction begin requires a fresh adoption baseline")
    source = _recovery_source(root, handoff)
    command = adoption.resolve_installed_command(root)
    body: dict[str, Any] = {
        "schema": TRANSACTION_SCHEMA,
        "product_version": PRODUCT.version,
        "transaction_id": "TX-" + _digest({"handoff": handoff["preview_sha256"], "authority": current["sha256"], "operator": name})[:16],
        "operator": name,
        "state": "ACTIVE",
        "opened_at": _now(),
        "handoff_preview_sha256": handoff["preview_sha256"],
        "pre_authority_baseline_sha256": handoff["baseline_sha256"],
        "authority_baseline_sha256": current["sha256"],
        "journey": handoff["journey"],
        "installed_command": str(command.executable),
        "recovery_source": source,
        "authority": {
            "scope": "d8.3-transaction-and-recovery-only",
            "controller_execution": False,
            "safe_stop_required_before_restore": True,
        },
        "safe_stop": None,
    }
    body["record_sha256"] = _digest(body)
    adoption.write_runtime_record(root, TRANSACTION_RECORD, body, actor="controller")
    return {**body, "result": "TRANSACTION_ACTIVE"}


def transaction_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    handoff = _load_adoption(root)
    transaction = _transaction(root, required=False)
    return {
        "schema": "stygnox_transaction_status_v1",
        "worktree": str(root),
        "journey": handoff["journey"],
        "handoff_preview_sha256": handoff["preview_sha256"],
        "transaction": transaction,
    }


def stop_transaction(project: Path, operator: str, reason: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "STOP":
        raise TransactionError("explicit confirmation required: --confirm STOP")
    root = adoption.resolve_worktree(project)
    handoff = _load_adoption(root)
    transaction = _transaction(root)
    assert transaction is not None
    name = _operator(operator)
    if name != handoff.get("operator") or name != transaction.get("operator"):
        raise TransactionError("safe-stop operator does not match transaction authority")
    if transaction.get("state") != "ACTIVE":
        raise TransactionError(f"safe stop requires ACTIVE transaction, found {transaction.get('state')}")
    reason_value = str(reason or "").strip()
    if reason_value not in _ALLOWED_STOP_REASONS:
        raise TransactionError(f"--reason must be one of: {', '.join(sorted(_ALLOWED_STOP_REASONS))}")
    current = adoption.capture_baseline(root).public()
    updated = dict(transaction)
    updated["state"] = "STOPPED"
    updated["safe_stop"] = {
        "reason": reason_value,
        "stopped_at": _now(),
        "baseline": current,
        "authority_revoked": True,
        "project_mutation": False,
    }
    updated.pop("record_sha256", None)
    updated["record_sha256"] = _digest(updated)
    adoption.write_runtime_record(root, TRANSACTION_RECORD, updated, actor="controller")
    return {**updated, "result": "SAFE_STOP_RECORDED"}


def build_recovery_preview(project: Path, operator: str, disposition: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    handoff = _load_adoption(root)
    transaction = _transaction(root)
    assert transaction is not None
    name = _operator(operator)
    if name != handoff.get("operator") or name != transaction.get("operator"):
        raise TransactionError("recovery operator does not match transaction authority")
    if transaction.get("state") != "STOPPED":
        raise TransactionError("recovery preview requires a recorded safe stop")
    if disposition != "discard":
        raise TransactionError("D8.3 supports only explicit --post-handoff-disposition discard; preserve work externally first")
    source = _recovery_source(root, handoff)
    current = adoption.capture_baseline(root).public()
    body: dict[str, Any] = {
        "schema": RECOVERY_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "transaction_id": transaction["transaction_id"],
        "transaction_record_sha256": transaction["record_sha256"],
        "journey": handoff["journey"],
        "current_baseline": current,
        "target_baseline": handoff["baseline"],
        "recovery_source": source,
        "post_handoff_disposition": disposition,
        "safe_stop": transaction["safe_stop"],
        "requires_explicit_confirmation": True,
        "confirmation": "RESTORE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def restore_baseline(project: Path, operator: str, preview_sha256: str, confirmation: str, disposition: str) -> dict[str, Any]:
    if confirmation != "RESTORE":
        raise TransactionError("explicit confirmation required: --confirm RESTORE")
    expected = _require_digest(preview_sha256, "--preview")
    preview = build_recovery_preview(project, operator, disposition)
    if preview["preview_sha256"] != expected:
        raise TransactionError("recovery preview is stale; project, transaction, or recovery evidence changed")

    root = adoption.resolve_worktree(project)
    handoff = _load_adoption(root)
    transaction = _transaction(root)
    assert transaction is not None
    ensure_runtime_local_ignore(root)
    try:
        if handoff["journey"] == "dirty":
            restore_external(root, preview["recovery_source"], handoff["baseline"])
        else:
            metadata = load_internal_checkpoint(root, str(handoff["recovery_source"].get("checkpoint_sha256") or ""))
            restore_internal(root, metadata)
    except RecoveryError as exc:
        raise TransactionError(str(exc)) from exc

    restored = adoption.capture_baseline(root).public()
    if restored.get("sha256") != handoff["baseline"].get("sha256"):
        raise TransactionError(
            "post-restoration baseline verification failed; controller evidence retained for operator recovery"
        )

    result = {
        "schema": RECOVERY_RESULT_SCHEMA,
        "result": "BASELINE_RESTORED",
        "operator": preview["operator"],
        "transaction_id": transaction["transaction_id"],
        "preview_sha256": expected,
        "journey": handoff["journey"],
        "target_baseline_sha256": handoff["baseline"]["sha256"],
        "restored_baseline_sha256": restored["sha256"],
        "post_handoff_disposition": disposition,
        "verified": True,
        "runtime_evidence_retained": True,
        "runtime_ignore_boundary": ".git/info/exclude",
        "restored_at": _now(),
    }
    adoption.write_runtime_record(root, RECOVERY_RESULT_RECORD, result, actor="controller")
    updated = dict(transaction)
    updated["state"] = "RECOVERED"
    updated["recovery"] = result
    updated.pop("record_sha256", None)
    updated["record_sha256"] = _digest(updated)
    adoption.write_runtime_record(root, TRANSACTION_RECORD, updated, actor="controller")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox transaction",
        description=(
            "D8.3 transaction/recovery surface. Controller execution remains disabled; "
            "this stage proves authority binding, safe stop, and operator-approved baseline restoration."
        ),
    )
    sub = parser.add_subparsers(dest="action", required=True)

    def project_arg(command: argparse.ArgumentParser) -> None:
        command.add_argument("--project", type=Path, default=Path.cwd(), help="adopted Git worktree")

    begin = sub.add_parser("begin", help="bind D8.3 transaction authority to the exact handoff baseline")
    project_arg(begin)
    begin.add_argument("--operator", required=True)
    begin.add_argument("--confirm", required=True, help="must be BEGIN")

    status = sub.add_parser("status", help="show the recorded transaction state")
    project_arg(status)

    stop = sub.add_parser("stop", help="revoke authority at a safe boundary")
    project_arg(stop)
    stop.add_argument("--operator", required=True)
    stop.add_argument("--reason", required=True, choices=sorted(_ALLOWED_STOP_REASONS))
    stop.add_argument("--confirm", required=True, help="must be STOP")

    preview = sub.add_parser("recover-preview", help="preview exact baseline restoration without changing the project")
    project_arg(preview)
    preview.add_argument("--operator", required=True)
    preview.add_argument("--post-handoff-disposition", required=True, choices=["discard"])

    renewal = sub.add_parser("renew-preview", help="preview a fresh transaction and plan epoch without mutation")
    project_arg(renewal)
    renewal.add_argument("--operator", required=True)

    renew = sub.add_parser("renew", help="confirm an exact renewal preview and publish a fresh epoch")
    project_arg(renew)
    renew.add_argument("--operator", required=True)
    renew.add_argument("--preview", required=True)
    renew.add_argument("--confirm", required=True, help="must be RENEW")

    restore = sub.add_parser("restore", help="restore the exact pre-authority baseline after safe stop")
    project_arg(restore)
    restore.add_argument("--operator", required=True)
    restore.add_argument("--preview", required=True)
    restore.add_argument("--confirm", required=True, help="must be RESTORE")
    restore.add_argument("--post-handoff-disposition", required=True, choices=["discard"])
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "begin":
            result = begin_transaction(args.project, args.operator, args.confirm)
        elif args.action == "status":
            result = transaction_status(args.project)
        elif args.action == "stop":
            result = stop_transaction(args.project, args.operator, args.reason, args.confirm)
        elif args.action == "recover-preview":
            result = build_recovery_preview(args.project, args.operator, args.post_handoff_disposition)
        elif args.action == "renew-preview":
            result = build_renewal_preview(args.project, args.operator)
        elif args.action == "renew":
            result = renew_transaction(args.project, args.operator, args.preview, args.confirm)
        else:
            result = restore_baseline(
                args.project,
                args.operator,
                args.preview,
                args.confirm,
                args.post_handoff_disposition,
            )
    except (TransactionError, adoption.AdoptionError) as exc:
        print(f"stygnox: transaction refused: {exc}", file=__import__("sys").stderr)
        return 2
    print(_render(result), end="")
    return 0
