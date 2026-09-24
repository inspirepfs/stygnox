"""D8.4 installed-product support, upgrade compatibility, and uninstall preparation.

Package installation/removal remains an external environment operation.  This
module owns the project-side compatibility contract: validate supported media
and platform, preserve runtime evidence during upgrade, and make uninstall
safe/idempotent without changing tracked project content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping, Sequence

from . import adoption, migration, transactions
from .product import PRODUCT


SUPPORT_POLICY_SCHEMA = "stygnox_support_policy_v1"
UPGRADE_PREVIEW_SCHEMA = "stygnox_upgrade_preview_v1"
UPGRADE_SCHEMA = "stygnox_upgrade_acceptance_v1"
UNINSTALL_PREVIEW_SCHEMA = "stygnox_uninstall_preview_v1"
UNINSTALL_SCHEMA = "stygnox_uninstall_preparation_v1"
UPGRADE_RECORD = "upgrade.json"
UNINSTALL_RECORD = "uninstall.json"
_VERSION_RE = re.compile(r"^0\.1\.0\.dev(?P<dev>[0-9]+)$")


class LifecycleError(RuntimeError):
    """Fail-closed D8.4 lifecycle error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _version_dev(value: str) -> int | None:
    match = _VERSION_RE.fullmatch(str(value or ""))
    return int(match.group("dev")) if match else None


def support_policy() -> dict[str, Any]:
    current_dev = _version_dev(PRODUCT.version)
    python_tuple = tuple(sys.version_info[:3])
    linux = sys.platform.startswith("linux")
    python_supported = (3, 11) <= python_tuple[:2] < (3, 14)
    git_path = shutil.which("git")
    return {
        "schema": SUPPORT_POLICY_SCHEMA,
        "product_version": PRODUCT.version,
        "supported": bool(linux and python_supported and git_path),
        "platform": {
            "os": "Linux",
            "current": sys.platform,
            "supported": linux,
        },
        "python": {
            "supported_range": ">=3.11,<3.14",
            "current": ".".join(str(part) for part in python_tuple),
            "supported": python_supported,
        },
        "git": {
            "required": True,
            "resolved": git_path,
            "supported": bool(git_path),
        },
        "install_media": {
            "supported": ["Python wheel installed with pip into an isolated/user-managed environment"],
            "source_tree_dependency": False,
            "system_package_manager": False,
        },
        "project_state_compatibility": {
            "package_only_upgrade_from": ["0.1.0.dev1", "0.1.0.dev2", "0.1.0.dev3"],
            "runtime_upgrade_from_dev_min": 2,
            "runtime_upgrade_through_dev": current_dev,
            "known_schemas": {
                "adoption": adoption.HANDOFF_SCHEMA,
                "transaction": transactions.TRANSACTION_SCHEMA,
                "recovery": transactions.RECOVERY_RESULT_SCHEMA,
                "migration": migration.MIGRATION_SCHEMA,
                "upgrade": UPGRADE_SCHEMA,
                "uninstall": UNINSTALL_SCHEMA,
            },
            "unknown_authority_schema": "REFUSE_BEFORE_CHANGE",
            "opaque_non_authority_evidence": "RETAIN_UNCHANGED",
        },
        "controller_execution": False,
    }


def _environment_blockers() -> list[str]:
    policy = support_policy()
    blockers: list[str] = []
    if not policy["platform"]["supported"]:
        blockers.append(f"unsupported operating system: {policy['platform']['current']}")
    if not policy["python"]["supported"]:
        blockers.append(f"unsupported Python version: {policy['python']['current']}")
    if not policy["git"]["supported"]:
        blockers.append("git executable is required")
    return blockers


def _load_json(path: Path, *, schema: str | None = None) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise LifecycleError(f"runtime record must be a regular file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"invalid runtime record {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise LifecycleError(f"runtime record must be a JSON object: {path.name}")
    if schema is not None and value.get("schema") != schema:
        raise LifecycleError(f"unsupported authority schema in {path.name}: {value.get('schema')!r}")
    return value


def _runtime_inventory(root: Path, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    runtime = root / adoption.RUNTIME_NAME
    if not runtime.exists():
        return []
    if runtime.is_symlink() or not runtime.is_dir():
        raise LifecycleError("Stygnox runtime must be a regular directory")
    excluded = exclude or set()
    rows: list[dict[str, Any]] = []
    for directory, dirnames, filenames in os.walk(runtime, topdown=True, followlinks=False):
        current = Path(directory)
        kept: list[str] = []
        for name in sorted(dirnames):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise LifecycleError(f"runtime evidence symlink is unsupported: {relative}")
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = current / name
            relative = path.relative_to(root).as_posix()
            if relative in excluded:
                continue
            if path.is_symlink() or not path.is_file():
                raise LifecycleError(f"runtime evidence non-regular file is unsupported: {relative}")
            rows.append(
                {
                    "path": relative,
                    "mode": f"{path.lstat().st_mode & 0o7777:04o}",
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return rows


def _authority_records(root: Path) -> dict[str, dict[str, Any] | None]:
    runtime = root / adoption.RUNTIME_NAME
    return {
        "adoption": _load_json(runtime / "adoption.json", schema=adoption.HANDOFF_SCHEMA),
        "transaction": _load_json(runtime / transactions.TRANSACTION_RECORD, schema=transactions.TRANSACTION_SCHEMA),
        "recovery": _load_json(runtime / transactions.RECOVERY_RESULT_RECORD, schema=transactions.RECOVERY_RESULT_SCHEMA),
        "migration": _load_json(runtime / migration.MIGRATION_RECORD, schema=migration.MIGRATION_SCHEMA),
        "upgrade": _load_json(runtime / UPGRADE_RECORD, schema=UPGRADE_SCHEMA),
        "uninstall": _load_json(runtime / UNINSTALL_RECORD, schema=UNINSTALL_SCHEMA),
    }


def _runtime_version_blockers(records: Mapping[str, dict[str, Any] | None]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    versions: set[str] = set()
    current_dev = _version_dev(PRODUCT.version)
    assert current_dev is not None
    for name, record in records.items():
        if record is None:
            continue
        version = str(record.get("product_version") or "")
        if not version:
            continue
        versions.add(version)
        dev = _version_dev(version)
        if dev is None or dev < 2 or dev > current_dev:
            blockers.append(
                f"{name} runtime version {version!r} is outside the supported D8.4 compatibility line"
            )
    transaction = records.get("transaction")
    if transaction is not None and transaction.get("state") == "ACTIVE":
        blockers.append("ACTIVE transaction must be safely stopped before upgrade/uninstall")
    migration_record = records.get("migration")
    if migration_record is not None and migration_record.get("state") in {"PREPARED", "FAILED_ROLLED_BACK"}:
        blockers.append(
            f"migration is in operator-review state {migration_record.get('state')!r}; resolve it before lifecycle change"
        )
    uninstall = records.get("uninstall")
    if uninstall is not None and uninstall.get("activity_disabled") is True:
        blockers.append("project is already prepared for uninstall; upgrade requires a future explicit reactivation path")
    return blockers, sorted(versions)


def build_upgrade_preview(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    name = adoption._validated_operator(operator)
    blockers = _environment_blockers()
    try:
        records = _authority_records(root)
        record_blockers, versions = _runtime_version_blockers(records)
        blockers.extend(record_blockers)
        inventory = _runtime_inventory(root, exclude={f"{adoption.RUNTIME_NAME}/{UPGRADE_RECORD}"})
    except LifecycleError as exc:
        records = {}
        versions = []
        inventory = []
        blockers.append(str(exc))
    adoption_record = records.get("adoption") if records else None
    if adoption_record is not None and adoption_record.get("operator") != name:
        blockers.append("upgrade operator does not match confirmed adoption handoff")
    baseline = adoption.capture_baseline(root).public()
    body: dict[str, Any] = {
        "schema": UPGRADE_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "project_baseline": baseline,
        "detected_runtime_versions": versions,
        "runtime_inventory": inventory,
        "runtime_inventory_sha256": _digest(inventory),
        "compatibility_policy": support_policy()["project_state_compatibility"],
        "preservation": {
            "authority_records_rewritten": False,
            "retained_evidence_rewritten": False,
            "tracked_project_mutation": False,
            "unknown_authority_schema": "REFUSE_BEFORE_CHANGE",
        },
        "blockers": blockers,
        "admissible": not blockers,
        "requires_explicit_confirmation": True,
        "confirmation": "UPGRADE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def accept_upgrade(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "UPGRADE":
        raise LifecycleError("explicit confirmation required: --confirm UPGRADE")
    expected = transactions._require_digest(preview_sha256, "--preview")
    preview = build_upgrade_preview(project, operator)
    if preview["preview_sha256"] != expected:
        raise LifecycleError("upgrade preview is stale; project state or retained evidence changed")
    if not preview["admissible"]:
        raise LifecycleError("upgrade refused: " + "; ".join(preview["blockers"]))
    root = Path(preview["worktree"])
    record = {
        "schema": UPGRADE_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "preview_sha256": expected,
        "accepted_runtime_versions": preview["detected_runtime_versions"],
        "retained_evidence_inventory_sha256": preview["runtime_inventory_sha256"],
        "compatibility_policy_schema": SUPPORT_POLICY_SCHEMA,
        "tracked_project_mutation": False,
        "authority_records_rewritten": False,
        "retained_evidence_rewritten": False,
        "controller_execution": False,
        "result": "UPGRADE_COMPATIBILITY_ACCEPTED",
    }
    record["record_sha256"] = _digest(record)
    adoption.write_runtime_record(root, UPGRADE_RECORD, record, actor="controller")
    after = adoption.capture_baseline(root).public()
    if after.get("sha256") != preview["project_baseline"].get("sha256"):
        raise LifecycleError("upgrade acceptance changed tracked project state")
    return record


def _tracked_ownership(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in (".gitignore", adoption.CONFIG_NAME, adoption.POLICY_NAME):
        path = root / name
        if not path.exists():
            rows.append({"path": name, "present": False})
            continue
        if path.is_symlink() or not path.is_file():
            raise LifecycleError(f"tracked ownership path must be a regular file: {name}")
        rows.append(
            {
                "path": name,
                "present": True,
                "sha256": _sha256_file(path),
                "mode": f"{path.lstat().st_mode & 0o7777:04o}",
            }
        )
    return rows


def build_uninstall_preview(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    name = adoption._validated_operator(operator)
    blockers = _environment_blockers()
    try:
        records = _authority_records(root)
        record_blockers, versions = _runtime_version_blockers(records)
        # Existing uninstall preparation is not itself a blocker for an idempotent prepare.
        record_blockers = [item for item in record_blockers if not item.startswith("project is already prepared for uninstall")]
        blockers.extend(record_blockers)
        runtime_inventory = _runtime_inventory(root, exclude={f"{adoption.RUNTIME_NAME}/{UNINSTALL_RECORD}"})
        ownership = _tracked_ownership(root)
    except LifecycleError as exc:
        records = {}
        versions = []
        runtime_inventory = []
        ownership = []
        blockers.append(str(exc))
    adoption_record = records.get("adoption") if records else None
    if adoption_record is not None and adoption_record.get("operator") != name:
        blockers.append("uninstall operator does not match confirmed adoption handoff")
    baseline = adoption.capture_baseline(root).public()
    body: dict[str, Any] = {
        "schema": UNINSTALL_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "project_baseline": baseline,
        "detected_runtime_versions": versions,
        "tracked_project_ownership": ownership,
        "retained_runtime_inventory": runtime_inventory,
        "retained_runtime_inventory_sha256": _digest(runtime_inventory),
        "evidence_ownership_after_package_removal": {
            "tracked_project_files": "remain project-owned and unchanged",
            "runtime_directory": f"{adoption.RUNTIME_NAME}/ remains operator-owned retained evidence",
            "legacy_migration_archives": "remain operator-owned retained evidence",
            "automatic_evidence_deletion": False,
        },
        "package_removal": {
            "external": True,
            "supported_media": "pip-installed wheel",
            "command_pattern": "<environment-python> -m pip uninstall -y stygnox",
        },
        "planned_result": {
            "activity_disabled": True,
            "tracked_project_mutation": False,
            "retained_evidence_deleted": False,
            "package_removal_external": True,
            "controller_execution": False,
        },
        "blockers": blockers,
        "admissible": not blockers,
        "requires_explicit_confirmation": True,
        "confirmation": "UNINSTALL",
    }
    body["preview_sha256"] = _digest(body)
    return body


def prepare_uninstall(project: Path, operator: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "UNINSTALL":
        raise LifecycleError("explicit confirmation required: --confirm UNINSTALL")
    expected = transactions._require_digest(preview_sha256, "--preview")
    preview = build_uninstall_preview(project, operator)
    if preview["preview_sha256"] != expected:
        raise LifecycleError("uninstall preview is stale; project state or retained evidence changed")
    if not preview["admissible"]:
        raise LifecycleError("uninstall refused: " + "; ".join(preview["blockers"]))
    root = Path(preview["worktree"])
    existing = _load_json(root / adoption.RUNTIME_NAME / UNINSTALL_RECORD, schema=UNINSTALL_SCHEMA)
    if existing is not None and existing.get("preview_sha256") == expected and existing.get("activity_disabled") is True:
        return {**existing, "result": "UNINSTALL_ALREADY_PREPARED"}
    record = {
        "schema": UNINSTALL_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "preview_sha256": expected,
        "project_baseline_sha256": preview["project_baseline"]["sha256"],
        "retained_runtime_inventory_sha256": preview["retained_runtime_inventory_sha256"],
        "tracked_project_ownership": preview["tracked_project_ownership"],
        "evidence_ownership_after_package_removal": preview["evidence_ownership_after_package_removal"],
        "activity_disabled": True,
        "controller_execution": False,
        "tracked_project_mutation": False,
        "retained_evidence_deleted": False,
        "package_removal_external": True,
        "result": "UNINSTALL_PREPARED",
    }
    record["record_sha256"] = _digest(record)
    adoption.write_runtime_record(root, UNINSTALL_RECORD, record, actor="controller")
    after = adoption.capture_baseline(root).public()
    if after.get("sha256") != preview["project_baseline"].get("sha256"):
        raise LifecycleError("uninstall preparation changed tracked project state")
    return record


def build_upgrade_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox upgrade",
        description="D8.4 project-state compatibility acceptance after installing a supported Stygnox wheel.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("preview", "inspect runtime compatibility without changing project state"),
        ("accept", "record explicit compatibility acceptance without rewriting retained evidence"),
    ):
        command = sub.add_parser(action, help=help_text)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--operator", required=True)
        if action == "accept":
            command.add_argument("--preview", required=True)
            command.add_argument("--confirm", required=True, help="must be UPGRADE")
    return parser


def upgrade_cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_upgrade_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview":
            result = build_upgrade_preview(args.project, args.operator)
        else:
            result = accept_upgrade(args.project, args.operator, args.preview, args.confirm)
    except (LifecycleError, adoption.AdoptionError, transactions.TransactionError) as exc:
        print(f"stygnox: upgrade refused: {exc}", file=sys.stderr)
        return 2
    print(_render(result), end="")
    return 0


def build_uninstall_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox uninstall",
        description=(
            "D8.4 project-side uninstall preparation. It disables project activity and preserves all project/evidence "
            "material; package removal is a separate pip operation."
        ),
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("preview", "preview retained ownership and preconditions without changing project state"),
        ("prepare", "record safe uninstall preparation; never delete project/evidence material"),
    ):
        command = sub.add_parser(action, help=help_text)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--operator", required=True)
        if action == "prepare":
            command.add_argument("--preview", required=True)
            command.add_argument("--confirm", required=True, help="must be UNINSTALL")
    return parser


def uninstall_cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_uninstall_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview":
            result = build_uninstall_preview(args.project, args.operator)
        else:
            result = prepare_uninstall(args.project, args.operator, args.preview, args.confirm)
    except (LifecycleError, adoption.AdoptionError, transactions.TransactionError) as exc:
        print(f"stygnox: uninstall refused: {exc}", file=sys.stderr)
        return 2
    print(_render(result), end="")
    return 0


def support_cli_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stygnox support", description="Show the D8.4 supported platform/install media and compatibility policy.")
    parser.parse_args(list(argv) if argv is not None else None)
    result = support_policy()
    print(_render(result), end="")
    return 0 if result["supported"] else 2
