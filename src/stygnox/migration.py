"""D8.4 reversible migration from legacy RALPH runtime to neutral Stygnox evidence.

The migration surface is intentionally narrow.  It recognises only an idle
``zen_ralph_lite_state_v1`` runtime, requires an already-confirmed Stygnox
handoff plus an ACTIVE D8.3 transaction, archives the legacy runtime byte/mode
exactly under controller-owned ``.stygnox`` evidence, removes the legacy
runtime and supported legacy ignore rules from the live project, and provides a
safe-stop-gated rollback that restores the pre-migration Git baseline.

No legacy schema is promoted into active Stygnox authority.  Legacy material is
retained as opaque evidence only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from . import adoption, transactions
from .product import PRODUCT


LEGACY_RUNTIME_NAME = ".ralph"
LEGACY_STATE_SCHEMA = "zen_ralph_lite_state_v1"
MIGRATION_PREVIEW_SCHEMA = "stygnox_legacy_migration_preview_v1"
MIGRATION_SCHEMA = "stygnox_legacy_migration_v1"
MIGRATION_ROLLBACK_PREVIEW_SCHEMA = "stygnox_legacy_migration_rollback_preview_v1"
MIGRATION_ROLLBACK_SCHEMA = "stygnox_legacy_migration_rollback_v1"
MIGRATION_RECORD = "migration.json"
MIGRATIONS_DIR = "migrations"
SUPPORTED_LEGACY_IGNORE_LINES = {
    ".ralph/",
    "/.ralph/",
    ".ralph/*",
    "/.ralph/*",
    "!.ralph/policy.md",
    "!/.ralph/policy.md",
}


class MigrationError(RuntimeError):
    """Fail-closed D8.4 migration error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise MigrationError(f"git {' '.join(args)} failed: {stderr or result.returncode}")
    return result


def _safe_mode(path: Path) -> str:
    return f"{path.lstat().st_mode & 0o7777:04o}"


def _legacy_inventory(root: Path) -> list[dict[str, Any]]:
    legacy = root / LEGACY_RUNTIME_NAME
    if legacy.is_symlink() or not legacy.is_dir():
        raise MigrationError(f"legacy runtime must be a regular directory: {LEGACY_RUNTIME_NAME}/")
    entries: list[dict[str, Any]] = [
        {"type": "dir", "path": LEGACY_RUNTIME_NAME, "mode": _safe_mode(legacy)}
    ]
    for directory, dirnames, filenames in os.walk(legacy, topdown=True, followlinks=False):
        current = Path(directory)
        rel_dir = current.relative_to(root)
        kept: list[str] = []
        for name in sorted(dirnames):
            path = current / name
            relative = (rel_dir / name).as_posix()
            if path.is_symlink():
                raise MigrationError(f"legacy runtime symlink is unsupported: {relative}")
            if not path.is_dir():
                raise MigrationError(f"legacy runtime special entry is unsupported: {relative}")
            kept.append(name)
            entries.append({"type": "dir", "path": relative, "mode": _safe_mode(path)})
        dirnames[:] = kept
        for name in sorted(filenames):
            path = current / name
            relative = (rel_dir / name).as_posix()
            if path.is_symlink() or not path.is_file():
                raise MigrationError(f"legacy runtime non-regular file is unsupported: {relative}")
            entries.append(
                {
                    "type": "file",
                    "path": relative,
                    "mode": _safe_mode(path),
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return sorted(entries, key=lambda item: (item["path"], item["type"]))


def _legacy_state(root: Path) -> dict[str, Any]:
    state_path = root / LEGACY_RUNTIME_NAME / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise MigrationError("legacy migration requires .ralph/state.json")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read legacy state: {exc}") from exc
    if not isinstance(state, dict):
        raise MigrationError("legacy state must be a JSON object")
    if state.get("schema") != LEGACY_STATE_SCHEMA:
        raise MigrationError(
            f"unsupported legacy state schema {state.get('schema')!r}; operator-directed migration is required"
        )
    if state.get("status") != "IDLE":
        raise MigrationError(
            f"legacy state must be IDLE before extraction, found {state.get('status')!r}"
        )
    if state.get("controller_runtime") not in (None, {}):
        raise MigrationError("legacy controller_runtime must be inactive before extraction")
    return state


def _parse_legacy_index(root: Path) -> list[dict[str, str]]:
    result = _git(root, "ls-files", "-s", "-z", "--", LEGACY_RUNTIME_NAME, check=True)
    entries: list[dict[str, str]] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            metadata, path_raw = raw.split(b"\t", 1)
            mode_raw, blob_raw, stage_raw = metadata.split(b" ", 2)
            mode = mode_raw.decode("ascii")
            blob = blob_raw.decode("ascii")
            stage = stage_raw.decode("ascii")
            path = path_raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise MigrationError("legacy Git index contains an unsupported path/entry") from exc
        if stage != "0":
            raise MigrationError(f"legacy migration refuses conflicted index stage {stage}: {path}")
        if mode not in {"100644", "100755"}:
            raise MigrationError(f"legacy migration refuses unsupported tracked mode {mode}: {path}")
        if not blob or set(blob) == {"0"}:
            raise MigrationError(f"legacy migration refuses intent-to-add/empty index identity: {path}")
        entries.append({"mode": mode, "blob": blob, "stage": stage, "path": path})
    return entries


def _gitignore_plan(root: Path) -> dict[str, Any]:
    path = root / ".gitignore"
    if path.is_symlink():
        raise MigrationError("refusing symlink .gitignore")
    existed = path.is_file()
    before = path.read_bytes() if existed else b""
    kept: list[bytes] = []
    removed: list[str] = []
    unsupported: list[str] = []
    for raw_line in before.splitlines(keepends=True):
        text = raw_line.decode("utf-8", errors="strict")
        stripped = text.strip()
        if stripped and not stripped.startswith("#") and ".ralph" in stripped:
            if stripped not in SUPPORTED_LEGACY_IGNORE_LINES:
                unsupported.append(stripped)
                kept.append(raw_line)
            else:
                removed.append(stripped)
        else:
            kept.append(raw_line)
    if unsupported:
        raise MigrationError(
            "unsupported legacy .gitignore rule(s) require operator-directed migration: "
            + ", ".join(sorted(set(unsupported)))
        )
    after = b"".join(kept)
    return {
        "existed": existed,
        "before_sha256": _sha256_bytes(before),
        "after_sha256": _sha256_bytes(after),
        "before_size": len(before),
        "after_size": len(after),
        "removed_rules": removed,
        "before": before,
        "after": after,
    }


def _transaction_context(root: Path, operator: str, *, required_state: str) -> tuple[dict[str, Any], dict[str, Any]]:
    status = transactions.transaction_status(root)
    transaction = status.get("transaction")
    if not isinstance(transaction, dict):
        raise MigrationError("D8.4 migration requires a D8.3 transaction")
    if transaction.get("state") != required_state:
        raise MigrationError(
            f"D8.4 migration requires transaction state {required_state}, found {transaction.get('state')!r}"
        )
    handoff = transactions._load_adoption(root)  # package-internal shared authority record
    if operator != handoff.get("operator") or operator != transaction.get("operator"):
        raise MigrationError("migration operator does not match confirmed transaction authority")
    return handoff, transaction


def _runtime_record(root: Path) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / MIGRATION_RECORD
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise MigrationError("migration runtime record must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"invalid migration runtime record: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != MIGRATION_SCHEMA:
        raise MigrationError("unsupported migration runtime record")
    return value


def build_preview(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    name = adoption._validated_operator(operator)
    handoff, transaction = _transaction_context(root, name, required_state="ACTIVE")
    existing = _runtime_record(root)
    blockers: list[str] = []
    if existing is not None and existing.get("state") == "APPLIED":
        blockers.append("legacy runtime has already been migrated")
    legacy = root / LEGACY_RUNTIME_NAME
    inventory: list[dict[str, Any]] = []
    state_summary: dict[str, Any] | None = None
    index_entries: list[dict[str, str]] = []
    gitignore: dict[str, Any] | None = None
    try:
        if not legacy.exists():
            blockers.append("legacy .ralph runtime is absent; migration is not required")
        else:
            state = _legacy_state(root)
            inventory = _legacy_inventory(root)
            index_entries = _parse_legacy_index(root)
            gitignore = _gitignore_plan(root)
            state_summary = {
                "schema": state.get("schema"),
                "status": state.get("status"),
                "controller_runtime": state.get("controller_runtime"),
                "updated_at": state.get("updated_at"),
            }
    except MigrationError as exc:
        blockers.append(str(exc))

    baseline = adoption.capture_baseline(root).public()
    command = adoption.resolve_installed_command(root)
    body: dict[str, Any] = {
        "schema": MIGRATION_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "transaction_id": transaction.get("transaction_id"),
        "transaction_record_sha256": transaction.get("record_sha256"),
        "handoff_preview_sha256": handoff.get("preview_sha256"),
        "current_baseline": baseline,
        "legacy_runtime": LEGACY_RUNTIME_NAME,
        "legacy_state": state_summary,
        "legacy_inventory": inventory,
        "legacy_inventory_sha256": _digest(inventory) if inventory else None,
        "legacy_index_entries": index_entries,
        "legacy_gitignore": None
        if gitignore is None
        else {
            key: value
            for key, value in gitignore.items()
            if key not in {"before", "after"}
        },
        "planned_result": {
            "active_runtime": adoption.RUNTIME_NAME,
            "legacy_runtime_removed": bool(inventory),
            "legacy_index_entries_removed": [entry["path"] for entry in index_entries],
            "legacy_ignore_rules_removed": [] if gitignore is None else gitignore["removed_rules"],
            "legacy_evidence_retained_under": f"{adoption.RUNTIME_NAME}/{MIGRATIONS_DIR}/",
            "legacy_schema_promoted_to_active_authority": False,
            "controller_execution": False,
        },
        "installed_command": str(command.executable),
        "blockers": blockers,
        "admissible": not blockers,
        "requires_explicit_confirmation": True,
        "confirmation": "MIGRATE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def _write_bytes(path: Path, data: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, value: Mapping[str, Any], *, mode: int = 0o600) -> None:
    _write_bytes(path, _render(value).encode("utf-8"), mode=mode)


def _validate_archive_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or not path.parts or path.parts[0] != LEGACY_RUNTIME_NAME:
        raise MigrationError(f"unsafe legacy archive member: {member.name!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise MigrationError(f"unsafe legacy archive member: {member.name!r}")
    if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
        raise MigrationError(f"unsupported legacy archive member type: {member.name!r}")


def _verify_archive(archive_path: Path, inventory: list[dict[str, Any]]) -> None:
    with tempfile.TemporaryDirectory(prefix="stygnox-d84-migration-verify-") as temp:
        destination = Path(temp)
        with tarfile.open(archive_path, "r") as archive:
            for member in archive.getmembers():
                _validate_archive_member(member)
            archive.extractall(destination, filter="fully_trusted")
        actual = _legacy_inventory(destination)
        if actual != inventory:
            raise MigrationError("legacy archive round-trip does not reproduce exact content/modes")


def _capture_migration(root: Path, preview: Mapping[str, Any], gitignore: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    migration_id = "MIG-" + str(preview["preview_sha256"])[:16]
    evidence_dir = root / adoption.RUNTIME_NAME / MIGRATIONS_DIR / migration_id
    if evidence_dir.exists():
        raise MigrationError(f"migration evidence already exists: {migration_id}")
    evidence_dir.mkdir(parents=True, mode=0o700)
    os.chmod(evidence_dir.parent, 0o700)
    archive_path = evidence_dir / "legacy-ralph.tar"
    legacy = root / LEGACY_RUNTIME_NAME
    with tarfile.open(archive_path, "w") as archive:
        archive.add(legacy, arcname=LEGACY_RUNTIME_NAME, recursive=True)
    os.chmod(archive_path, 0o600)
    inventory = list(preview["legacy_inventory"])
    _verify_archive(archive_path, inventory)

    gitignore_before = evidence_dir / "gitignore.before"
    _write_bytes(gitignore_before, bytes(gitignore["before"]), mode=0o600)
    metadata: dict[str, Any] = {
        "schema": MIGRATION_SCHEMA,
        "state": "PREPARED",
        "migration_id": migration_id,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "preview_sha256": preview["preview_sha256"],
        "transaction_id": preview["transaction_id"],
        "pre_migration_baseline": preview["current_baseline"],
        "legacy_runtime": LEGACY_RUNTIME_NAME,
        "legacy_state": preview["legacy_state"],
        "legacy_inventory": inventory,
        "legacy_inventory_sha256": preview["legacy_inventory_sha256"],
        "legacy_index_entries": list(preview["legacy_index_entries"]),
        "archive": str(archive_path.relative_to(root)),
        "archive_sha256": _sha256_file(archive_path),
        "gitignore_before": str(gitignore_before.relative_to(root)),
        "gitignore_before_sha256": _sha256_file(gitignore_before),
        "gitignore_after_sha256": gitignore["after_sha256"],
        "legacy_ignore_rules_removed": list(gitignore["removed_rules"]),
        "legacy_schema_promoted_to_active_authority": False,
    }
    metadata["record_sha256"] = _digest(metadata)
    _write_json(evidence_dir / "migration.json", metadata)
    return evidence_dir, metadata


def _remove_legacy_index_entries(root: Path, entries: Iterable[Mapping[str, str]]) -> None:
    for entry in entries:
        _git(root, "update-index", "--force-remove", "--", str(entry["path"]))


def _restore_legacy_index_entries(root: Path, entries: Iterable[Mapping[str, str]]) -> None:
    current = _parse_legacy_index(root)
    _remove_legacy_index_entries(root, current)
    for entry in entries:
        argument = f"{entry['mode']},{entry['blob']},{entry['path']}"
        _git(root, "update-index", "--add", "--cacheinfo", argument)


def _restore_capture(root: Path, metadata: Mapping[str, Any]) -> None:
    archive_path = root / str(metadata["archive"])
    gitignore_before = root / str(metadata["gitignore_before"])
    if not archive_path.is_file() or _sha256_file(archive_path) != metadata.get("archive_sha256"):
        raise MigrationError("migration rollback archive digest mismatch")
    if not gitignore_before.is_file() or _sha256_file(gitignore_before) != metadata.get("gitignore_before_sha256"):
        raise MigrationError("migration rollback .gitignore evidence digest mismatch")
    _verify_archive(archive_path, list(metadata["legacy_inventory"]))

    legacy = root / LEGACY_RUNTIME_NAME
    if legacy.exists() or legacy.is_symlink():
        if legacy.is_symlink() or not legacy.is_dir():
            legacy.unlink()
        else:
            shutil.rmtree(legacy)
    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            _validate_archive_member(member)
        archive.extractall(root, filter="fully_trusted")

    _write_bytes(root / ".gitignore", gitignore_before.read_bytes(), mode=0o644)
    _restore_legacy_index_entries(root, list(metadata["legacy_index_entries"]))

    if _legacy_inventory(root) != list(metadata["legacy_inventory"]):
        raise MigrationError("legacy rollback verification failed: runtime inventory differs")


def apply_migration(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "MIGRATE":
        raise MigrationError("explicit confirmation required: --confirm MIGRATE")
    root = adoption.resolve_worktree(project)
    expected = transactions._require_digest(preview_sha256, "--preview")
    preview = build_preview(root, operator)
    if preview["preview_sha256"] != expected:
        raise MigrationError("migration preview is stale; project, transaction, legacy state, or evidence changed")
    if not preview["admissible"]:
        raise MigrationError("migration refused: " + "; ".join(preview["blockers"]))
    gitignore = _gitignore_plan(root)
    evidence_dir, metadata = _capture_migration(root, preview, gitignore)
    mutation_started = False
    try:
        mutation_started = True
        if gitignore["after"] != gitignore["before"]:
            _write_bytes(root / ".gitignore", bytes(gitignore["after"]), mode=0o644)
        _remove_legacy_index_entries(root, list(preview["legacy_index_entries"]))
        shutil.rmtree(root / LEGACY_RUNTIME_NAME)
        if (root / LEGACY_RUNTIME_NAME).exists():
            raise MigrationError("legacy runtime removal did not complete")
        if _parse_legacy_index(root):
            raise MigrationError("legacy tracked index entries remain after migration")
        after_plan = _gitignore_plan(root)
        if after_plan["removed_rules"]:
            raise MigrationError("legacy ignore rules remain authoritative after migration")

        applied = dict(metadata)
        applied["state"] = "APPLIED"
        applied["post_migration_baseline"] = adoption.capture_baseline(root).public()
        applied["retained_evidence_readable"] = True
        applied["active_runtime"] = adoption.RUNTIME_NAME
        applied["controller_execution"] = False
        applied.pop("record_sha256", None)
        applied["record_sha256"] = _digest(applied)
        _write_json(evidence_dir / "migration.json", applied)
        adoption.write_runtime_record(root, MIGRATION_RECORD, applied, actor="controller")
        return {**applied, "result": "LEGACY_RUNTIME_MIGRATED"}
    except Exception as exc:
        if mutation_started:
            try:
                _restore_capture(root, metadata)
                failed = dict(metadata)
                failed["state"] = "FAILED_ROLLED_BACK"
                failed["failure"] = str(exc)
                failed.pop("record_sha256", None)
                failed["record_sha256"] = _digest(failed)
                _write_json(evidence_dir / "migration.json", failed)
                adoption.write_runtime_record(root, MIGRATION_RECORD, failed, actor="controller")
            except Exception as rollback_exc:
                raise MigrationError(
                    f"migration failed and automatic rollback also failed: {exc}; rollback: {rollback_exc}"
                ) from rollback_exc
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError(f"migration failed: {exc}") from exc


def _load_evidence_metadata(root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    migration_id = str(record.get("migration_id") or "")
    if not migration_id.startswith("MIG-"):
        raise MigrationError("invalid migration identifier")
    path = root / adoption.RUNTIME_NAME / MIGRATIONS_DIR / migration_id / "migration.json"
    if path.is_symlink() or not path.is_file():
        raise MigrationError("migration evidence metadata is missing")
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"invalid migration evidence metadata: {exc}") from exc
    if not isinstance(metadata, dict) or metadata.get("schema") != MIGRATION_SCHEMA:
        raise MigrationError("unsupported migration evidence metadata")
    if metadata.get("record_sha256") != record.get("record_sha256"):
        raise MigrationError("migration evidence metadata does not match active runtime record")
    body = dict(metadata)
    recorded = body.pop("record_sha256", None)
    if recorded != _digest(body):
        raise MigrationError("migration evidence metadata digest mismatch")
    return metadata


def build_rollback_preview(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    name = adoption._validated_operator(operator)
    _, transaction = _transaction_context(root, name, required_state="STOPPED")
    record = _runtime_record(root)
    if record is None or record.get("state") != "APPLIED":
        raise MigrationError("migration rollback requires an APPLIED migration")
    metadata = _load_evidence_metadata(root, record)
    if (root / LEGACY_RUNTIME_NAME).exists():
        raise MigrationError("legacy runtime reappeared after migration; rollback refuses to overwrite it")
    current = adoption.capture_baseline(root).public()
    expected_post = record.get("post_migration_baseline") or {}
    if current.get("sha256") != expected_post.get("sha256"):
        raise MigrationError("project changed after migration; rollback requires the exact post-migration baseline")
    archive = root / str(metadata["archive"])
    if not archive.is_file() or _sha256_file(archive) != metadata.get("archive_sha256"):
        raise MigrationError("migration rollback archive changed")
    _verify_archive(archive, list(metadata["legacy_inventory"]))
    body: dict[str, Any] = {
        "schema": MIGRATION_ROLLBACK_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "transaction_id": transaction.get("transaction_id"),
        "transaction_record_sha256": transaction.get("record_sha256"),
        "migration_id": record.get("migration_id"),
        "migration_record_sha256": record.get("record_sha256"),
        "current_baseline": current,
        "target_baseline": record.get("pre_migration_baseline"),
        "legacy_inventory_sha256": record.get("legacy_inventory_sha256"),
        "archive_sha256": record.get("archive_sha256"),
        "requires_explicit_confirmation": True,
        "confirmation": "ROLLBACK",
    }
    body["preview_sha256"] = _digest(body)
    return body


def rollback_migration(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "ROLLBACK":
        raise MigrationError("explicit confirmation required: --confirm ROLLBACK")
    root = adoption.resolve_worktree(project)
    expected = transactions._require_digest(preview_sha256, "--preview")
    preview = build_rollback_preview(root, operator)
    if preview["preview_sha256"] != expected:
        raise MigrationError("migration rollback preview is stale")
    record = _runtime_record(root)
    assert record is not None
    metadata = _load_evidence_metadata(root, record)
    _restore_capture(root, metadata)
    restored = adoption.capture_baseline(root).public()
    target = record.get("pre_migration_baseline") or {}
    if restored.get("sha256") != target.get("sha256"):
        raise MigrationError("migration rollback failed to restore the exact pre-migration Git baseline")
    result = {
        "schema": MIGRATION_ROLLBACK_SCHEMA,
        "product_version": PRODUCT.version,
        "result": "LEGACY_MIGRATION_ROLLED_BACK",
        "operator": preview["operator"],
        "migration_id": record["migration_id"],
        "preview_sha256": expected,
        "restored_baseline_sha256": restored["sha256"],
        "legacy_inventory_sha256": record["legacy_inventory_sha256"],
        "legacy_runtime_restored": True,
        "legacy_index_restored": True,
        "legacy_gitignore_restored": True,
        "retained_neutral_evidence": True,
        "controller_execution": False,
    }
    rolled = dict(record)
    rolled["state"] = "ROLLED_BACK"
    rolled["rollback"] = result
    rolled.pop("record_sha256", None)
    rolled["record_sha256"] = _digest(rolled)
    adoption.write_runtime_record(root, MIGRATION_RECORD, rolled, actor="controller")
    evidence_dir = root / adoption.RUNTIME_NAME / MIGRATIONS_DIR / str(record["migration_id"])
    _write_json(evidence_dir / "migration.json", rolled)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox migrate",
        description=(
            "D8.4 reversible extraction of supported idle RALPH runtime into neutral Stygnox retained evidence. "
            "Autonomous controller execution remains disabled."
        ),
    )
    sub = parser.add_subparsers(dest="action", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--project", type=Path, default=Path.cwd(), help="adopted Git worktree")
        command.add_argument("--operator", required=True)

    preview = sub.add_parser("preview", help="inspect supported legacy state without changing the project")
    common(preview)

    apply = sub.add_parser("apply", help="archive and remove supported legacy authority paths")
    common(apply)
    apply.add_argument("--preview", required=True)
    apply.add_argument("--confirm", required=True, help="must be MIGRATE")

    rollback_preview = sub.add_parser("rollback-preview", help="preview exact migration rollback after safe stop")
    common(rollback_preview)

    rollback = sub.add_parser("rollback", help="restore exact legacy runtime/index/ignore state")
    common(rollback)
    rollback.add_argument("--preview", required=True)
    rollback.add_argument("--confirm", required=True, help="must be ROLLBACK")
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview":
            result = build_preview(args.project, args.operator)
        elif args.action == "apply":
            result = apply_migration(args.project, args.operator, args.preview, args.confirm)
        elif args.action == "rollback-preview":
            result = build_rollback_preview(args.project, args.operator)
        else:
            result = rollback_migration(args.project, args.operator, args.preview, args.confirm)
    except (MigrationError, adoption.AdoptionError, transactions.TransactionError) as exc:
        print(f"stygnox: migration refused: {exc}", file=sys.stderr)
        return 2
    print(_render(result), end="")
    return 0
