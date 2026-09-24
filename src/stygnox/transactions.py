"""D8.3 transactional authority, safe stop, and baseline restoration."""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import adoption
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
    path = root / adoption.RUNTIME_NAME / name
    if not path.is_file():
        if required:
            raise TransactionError(f"required Stygnox runtime record is missing: {name}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransactionError(f"invalid Stygnox runtime record {name}: {exc}") from exc
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
