"""D8.4 installed-product support, upgrade compatibility, and uninstall preparation.

Package installation/removal remains an external environment operation.  This
module owns the project-side compatibility contract: validate supported media
and platform, preserve runtime evidence during upgrade, and make uninstall
safe/idempotent without changing tracked project content.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence
import zipfile

from . import adoption, controller, migration, planning, transactions
from .product import PRODUCT


SUPPORT_POLICY_SCHEMA = "stygnox_support_policy_v1"
UPGRADE_PREVIEW_SCHEMA = "stygnox_upgrade_preview_v1"
UPGRADE_SCHEMA = "stygnox_upgrade_acceptance_v1"
UNINSTALL_PREVIEW_SCHEMA = "stygnox_uninstall_preview_v1"
UNINSTALL_SCHEMA = "stygnox_uninstall_preparation_v1"
UPGRADE_RECORD = "upgrade.json"
REBIND_RECORD = "rebind.json"
REBIND_PREVIEW_SCHEMA = "stygnox_upgrade_rebind_preview_v1"
REBIND_SCHEMA = "stygnox_upgrade_rebind_v1"
UNINSTALL_RECORD = "uninstall.json"
_VERSION_RE = re.compile(r"^0\.1\.0\.dev(?P<dev>[0-9]+)$")
_STABLE_VERSION = "0.1.0"
_STABLE_COMPAT_DEV_CEILING = 8
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


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


def _regular_file(path: Path, description: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise LifecycleError(f"{description} must be a regular file: {path}")
    return path.resolve()


def _record_rows(data: str, description: str) -> list[tuple[str, str, str]]:
    rows = list(csv.reader(data.splitlines()))
    if not rows or any(len(row) != 3 or not row[0] for row in rows):
        raise LifecycleError(f"invalid {description} RECORD")
    return [(row[0], row[1], row[2]) for row in rows]


def _record_hash(value: str, path: Path, description: str) -> None:
    if not value:
        return
    try:
        algorithm, encoded = value.split("=", 1)
        expected = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError) as exc:
        raise LifecycleError(f"invalid hash in {description} RECORD: {path}") from exc
    try:
        actual = hashlib.new(algorithm, path.read_bytes()).digest()
    except ValueError as exc:
        raise LifecycleError(f"unsupported hash in {description} RECORD: {algorithm}") from exc
    if actual != expected:
        raise LifecycleError(f"{description} RECORD digest mismatch: {path}")


def _installed_identity(worktree: Path) -> dict[str, Any]:
    """Return a verified identity for this *installed* interpreter package.

    Metadata lookup is deliberately tied to the imported package and its RECORD,
    rather than to PATH alone.  That prevents a copied launcher or a source-tree
    import from being treated as an upgrade target.
    """
    command = adoption.resolve_installed_command(worktree)
    executable = _regular_file(command.executable, "installed Stygnox executable")
    package_file = _regular_file(command.package_file, "installed Stygnox package")
    try:
        distribution = metadata.distribution("stygnox")
    except metadata.PackageNotFoundError as exc:
        raise LifecycleError("installed Stygnox distribution metadata is unavailable") from exc
    package_root = package_file.parent.parent.resolve()
    distribution_root = Path(distribution.locate_file("")).resolve()
    if distribution_root != package_root:
        raise LifecycleError("installed Stygnox distribution does not own the imported package")
    candidates = sorted(package_root.glob("stygnox-*.dist-info/RECORD"))
    if len(candidates) != 1:
        raise LifecycleError("installed Stygnox requires exactly one adjacent dist-info RECORD")
    record = _regular_file(candidates[0], "installed Stygnox RECORD")
    dist_info = record.parent
    metadata_file = _regular_file(dist_info / "METADATA", "installed Stygnox METADATA")
    installed_name = str(distribution.metadata.get("Name") or "").lower()
    installed_version = str(distribution.version)
    if installed_name != "stygnox" or installed_version != command.version:
        raise LifecycleError("installed Stygnox metadata does not match the imported package identity")
    rows = _record_rows(record.read_text(encoding="utf-8"), "installed")
    package_relative = package_file.relative_to(package_root).as_posix()
    names = {name for name, _, _ in rows}
    if package_relative not in names:
        raise LifecycleError("installed Stygnox package is absent from its RECORD")
    for name, digest, _size in rows:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            # pip records a console launcher relative to site-packages (normally
            # ../../../bin/stygnox).  The launcher is the only RECORD member
            # allowed outside the installed package root, and must be the exact
            # executable selected for the handoff.
            target = (package_root / relative).resolve()
            if target != executable:
                raise LifecycleError("installed RECORD contains an unsafe path")
        else:
            target = package_root / relative
        if not digest:
            continue
        _regular_file(target, "installed RECORD member")
        _record_hash(digest, target, "installed")
    installed_manifest = [
        {"path": name, "hash": digest, "size": size}
        for name, digest, size in sorted(rows)
    ]
    return {
        "executable": str(executable),
        "package_file": str(package_file),
        "package_sha256": _sha256_file(package_file),
        "package_version": command.version,
        "distribution_name": installed_name,
        "record": str(record),
        "record_sha256": _sha256_file(record),
        "record_manifest": installed_manifest,
        "record_manifest_sha256": _digest(installed_manifest),
        "metadata_sha256": _sha256_file(metadata_file),
        "site_packages": str(package_root),
    }


def _wheel_identity(wheel: Path, installed: Mapping[str, Any]) -> dict[str, Any]:
    wheel = _regular_file(wheel, "candidate Stygnox wheel")
    if wheel.suffix != ".whl":
        raise LifecycleError("candidate artifact must be a wheel (.whl)")
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise LifecycleError("candidate wheel contains duplicate members")
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                raise LifecycleError("candidate wheel contains an unsafe member path")
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            record_names = [name for name in names if name.endswith(".dist-info/RECORD")]
            if len(metadata_names) != 1 or len(record_names) != 1:
                raise LifecycleError("candidate wheel must contain one METADATA and one RECORD")
            wheel_metadata = archive.read(metadata_names[0]).decode("utf-8")
            wheel_record = _record_rows(archive.read(record_names[0]).decode("utf-8"), "candidate wheel")
            fields = dict(line.split(": ", 1) for line in wheel_metadata.splitlines() if ": " in line)
            if fields.get("Name", "").lower() != "stygnox" or fields.get("Version") != installed["package_version"]:
                raise LifecycleError("candidate wheel package identity does not match the installed Stygnox package")
            listed = {name for name, _, _ in wheel_record}
            package_members = {
                name for name in names
                if name.startswith("stygnox/") and not name.endswith("/")
            }
            if not package_members or not package_members.issubset(listed):
                raise LifecycleError("candidate wheel has package members absent from its RECORD")
            installed_package = Path(str(installed["site_packages"])) / "stygnox"
            if installed_package.is_symlink() or not installed_package.is_dir():
                raise LifecycleError("installed Stygnox package directory is invalid")
            installed_members = {
                path.relative_to(Path(str(installed["site_packages"]))).as_posix()
                for path in installed_package.rglob("*")
                if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
            }
            if package_members != installed_members:
                raise LifecycleError("candidate wheel package members do not match the installed Stygnox package")
            for name, digest, _size in wheel_record:
                if not digest:
                    continue
                if name not in names:
                    raise LifecycleError(f"candidate wheel RECORD member is missing: {name}")
                payload = archive.read(name)
                try:
                    algorithm, encoded = digest.split("=", 1)
                    expected = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                    actual = hashlib.new(algorithm, payload).digest()
                except (ValueError, TypeError) as exc:
                    raise LifecycleError(f"invalid hash in candidate wheel RECORD: {name}") from exc
                if actual != expected:
                    raise LifecycleError(f"candidate wheel RECORD digest mismatch: {name}")
                if name in package_members:
                    installed_member = Path(str(installed["site_packages"])) / name
                    _regular_file(installed_member, "installed candidate package member")
                    if installed_member.read_bytes() != payload:
                        raise LifecycleError(f"candidate wheel does not match installed package member: {name}")
            if "stygnox/adoption.py" not in package_members:
                raise LifecycleError("candidate wheel lacks the Stygnox package identity module")
            package_manifest = [
                {"path": name, "sha256": hashlib.sha256(archive.read(name)).hexdigest(), "size": len(archive.read(name))}
                for name in sorted(package_members)
            ]
            wheel_record_manifest = [
                {"path": name, "hash": digest, "size": size}
                for name, digest, size in sorted(wheel_record)
            ]
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, LifecycleError):
            raise
        raise LifecycleError(f"invalid candidate Stygnox wheel: {exc}") from exc
    return {
        "path": str(wheel),
        "sha256": _sha256_file(wheel),
        "package_version": installed["package_version"],
        "package_manifest": package_manifest,
        "package_manifest_sha256": _digest(package_manifest),
        "wheel_record_manifest": wheel_record_manifest,
        "wheel_record_manifest_sha256": _digest(wheel_record_manifest),
    }


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _version_dev(value: str) -> int | None:
    match = _VERSION_RE.fullmatch(str(value or ""))
    return int(match.group("dev")) if match else None


def _compatibility_dev_ceiling(value: str) -> int | None:
    dev = _version_dev(value)
    if dev is not None:
        return dev
    if value == _STABLE_VERSION:
        return _STABLE_COMPAT_DEV_CEILING
    return None


def _package_upgrade_dev_max(value: str) -> int:
    dev = _version_dev(value)
    if dev is not None:
        return max(0, dev - 1)
    if value == _STABLE_VERSION:
        return _STABLE_COMPAT_DEV_CEILING
    return 0


def support_policy() -> dict[str, Any]:
    current_dev = _compatibility_dev_ceiling(PRODUCT.version)
    package_upgrade_dev_max = _package_upgrade_dev_max(PRODUCT.version)
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
            "package_only_upgrade_from": [
                f"0.1.0.dev{dev}" for dev in range(1, package_upgrade_dev_max + 1)
            ],
            "runtime_upgrade_from_dev_min": 2,
            "runtime_upgrade_through_dev": current_dev,
            "runtime_upgrade_through_version": PRODUCT.version,
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
        "controller": _load_json(runtime / controller.CONTROLLER_RECORD, schema=controller.CONTROLLER_SCHEMA),
        "recovery": _load_json(runtime / transactions.RECOVERY_RESULT_RECORD, schema=transactions.RECOVERY_RESULT_SCHEMA),
        "plan": _load_json(runtime / planning.PLAN_RECORD, schema=planning.PLAN_SCHEMA),
        "migration": _load_json(runtime / migration.MIGRATION_RECORD, schema=migration.MIGRATION_SCHEMA),
        "upgrade": _load_json(runtime / UPGRADE_RECORD, schema=UPGRADE_SCHEMA),
        "uninstall": _load_json(runtime / UNINSTALL_RECORD, schema=UNINSTALL_SCHEMA),
        "rebind": _load_json(runtime / REBIND_RECORD, schema=REBIND_SCHEMA),
    }


def _verified_record(record: Mapping[str, Any], name: str) -> None:
    body = dict(record)
    recorded = body.pop("record_sha256", None)
    if not isinstance(recorded, str) or not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise LifecycleError(f"{name} authority record integrity check failed")


def _qualified_successor_binding(root: Path, records: Mapping[str, dict[str, Any] | None], artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the installed wheel to the exact qualified source state, not its name."""
    plan = records.get("plan")
    transaction = records.get("transaction")
    predecessor = records.get("controller")
    if plan is None or transaction is None or predecessor is None:
        raise LifecycleError("rebind requires qualified plan, predecessor transaction, and predecessor controller records")
    _verified_record(plan, "plan")
    _verified_record(transaction, "transaction")
    _verified_record(predecessor, "controller")
    scope = plan.get("repository_mutation_scope")
    scope_sha256 = plan.get("repository_mutation_scope_sha256")
    if not isinstance(scope, list) or scope_sha256 != _digest(scope):
        raise LifecycleError("rebind plan scope is stale or malformed")

    # Validate the already-authoritative qualification/source evidence before
    # interpreting the newer pending-transition contract.  This preserves the
    # historical fail-closed reasons for stale qualification and substituted
    # artifacts while still requiring the installed-successor transition for
    # any handoff that reaches the authority-transfer boundary.
    final = plan.get("final_qualification") if isinstance(plan.get("final_qualification"), Mapping) else None
    if final is None or final.get("state") != "PASS":
        raise LifecycleError("rebind requires a passing final qualification")
    final_body = dict(final)
    final_sha = str(final_body.pop("provenance_sha256", "") or "")
    if not _HEX64.fullmatch(final_sha) or final_sha != _digest(final_body):
        raise LifecycleError("rebind final qualification integrity check failed")
    if final.get("repository_mutation_scope_sha256") not in {None, scope_sha256}:
        raise LifecycleError("rebind qualification scope is stale or malformed")

    current = adoption.capture_baseline(root).public()
    if final.get("repository_baseline_sha256") != current.get("sha256"):
        raise LifecycleError("rebind qualification is stale against the current source baseline")
    source_manifest: list[dict[str, Any]] = []
    package_manifest = artifact.get("package_manifest")
    if not isinstance(package_manifest, list) or artifact.get("package_manifest_sha256") != _digest(package_manifest):
        raise LifecycleError("candidate artifact package manifest is malformed")
    for member in package_manifest:
        if not isinstance(member, Mapping) or not isinstance(member.get("path"), str):
            raise LifecycleError("candidate artifact package manifest is malformed")
        source = _regular_file(root / "src" / member["path"], "qualified successor source member")
        row = {"path": f"src/{member['path']}", "sha256": _sha256_file(source), "size": source.stat().st_size}
        if row["sha256"] != member.get("sha256") or row["size"] != member.get("size"):
            raise LifecycleError(f"candidate wheel does not match qualified source member: {member['path']}")
        source_manifest.append(row)
    source_manifest_sha256 = _digest(source_manifest)

    try:
        transition = planning.pending_required_transition(plan)
    except planning.PlanningError as exc:
        raise LifecycleError(str(exc)) from exc
    if transition is None or transition.get("kind") != planning.INSTALLED_SUCCESSOR_HANDOFF:
        raise LifecycleError("rebind requires a pending installed-successor post-qualification transition")
    if transition.get("qualified_baseline_sha256") != current.get("sha256"):
        raise LifecycleError("rebind qualification is stale against the current source baseline")

    return {
        "plan_hash": plan.get("plan_hash"),
        "plan_record_sha256": plan.get("record_sha256"),
        "plan_step": plan.get("current_step"),
        "repository_mutation_scope": list(scope),
        "repository_mutation_scope_sha256": scope_sha256,
        "required_post_qualification_transition": transition,
        "qualification_binding_sha256": transition["qualification_binding_sha256"],
        "qualified_source_manifest": source_manifest,
        "qualified_source_manifest_sha256": source_manifest_sha256,
        "qualified_source_baseline_sha256": current["sha256"],
        "predecessor_transaction_record_sha256": transaction["record_sha256"],
        "predecessor_controller_record_sha256": predecessor["record_sha256"],
    }


def _bootstrap_disposition(root: Path) -> dict[str, Any]:
    """Bind bootstrap material as operator-owned input, never provider evidence."""
    material: list[dict[str, str]] = []
    for name in (adoption.CONFIG_NAME, adoption.POLICY_NAME):
        path = _regular_file(root / name, "bootstrap adoption material")
        material.append({"path": name, "sha256": _sha256_file(path)})
    return {
        "disposition": "OPERATOR_ADOPTION_MATERIAL",
        "material": material,
        "material_sha256": _digest(material),
        "provider_attribution": "EXCLUDED",
        "accepted_provider_delta": False,
        "qualified_provider_delta": False,
        "finalized_provider_delta": False,
    }


def _lineage(records: Mapping[str, dict[str, Any] | None], inventory_sha256: str) -> dict[str, Any]:
    adoption_record = records.get("adoption") or {}
    transaction = records.get("transaction") or {}
    recovery = records.get("recovery") or {}
    plan = records.get("plan") or {}
    if plan:
        recorded = str(plan.get("record_sha256") or "")
        plan_body = dict(plan)
        plan_body.pop("record_sha256", None)
        if not _HEX64.fullmatch(recorded) or recorded != _digest(plan_body):
            raise LifecycleError("plan lineage record integrity check failed")
        scope = plan.get("repository_mutation_scope")
        scope_digest = plan.get("repository_mutation_scope_sha256")
        if not isinstance(scope, list) or not isinstance(scope_digest, str) or scope_digest != _digest(scope):
            raise LifecycleError("plan lineage scope evidence is stale or malformed")
    else:
        scope = []
        scope_digest = None
    recovery_source = transaction.get("recovery_source") or adoption_record.get("recovery_source")
    final_qualification = plan.get("final_qualification") if isinstance(plan.get("final_qualification"), Mapping) else {}
    return {
        "adoption_preview_sha256": adoption_record.get("preview_sha256"),
        "transaction_id": transaction.get("transaction_id"),
        "transaction_record_sha256": transaction.get("record_sha256"),
        "authority_scope": (transaction.get("authority") or adoption_record.get("authority") or {}).get("scope"),
        "recovery_source": recovery_source,
        "recovery_record_sha256": recovery.get("record_sha256"),
        "recovery_checkpoint_sha256": recovery_source.get("checkpoint_sha256") if isinstance(recovery_source, Mapping) else None,
        "plan_hash": plan.get("plan_hash"),
        "plan_record_sha256": plan.get("record_sha256"),
        "plan_current_step": plan.get("current_step"),
        "repository_mutation_scope": scope,
        "repository_mutation_scope_sha256": scope_digest,
        "qualification_provenance_sha256": final_qualification.get("provenance_sha256"),
        "accepted_attribution": final_qualification.get("accepted_controller_attribution"),
        "runtime_inventory_sha256": inventory_sha256,
    }


def _runtime_epoch(record: Mapping[str, dict[str, Any] | None]) -> int:
    previous = record.get("rebind") or {}
    value = previous.get("new_runtime_epoch", 0)
    if not isinstance(value, int) or value < 0:
        raise LifecycleError("existing rebind runtime epoch is invalid")
    return value


def build_rebind_preview(project: Path, operator: str, wheel: Path) -> dict[str, Any]:
    """Preview a strictly installed, quiescent authority transfer.

    This is intentionally separate from compatibility ``upgrade accept``.  It
    never attributes bootstrap configuration to a provider and makes no write.
    """
    root = adoption.resolve_worktree(project)
    name = adoption._validated_operator(operator)
    blockers = _environment_blockers()
    try:
        bootstrap = _bootstrap_disposition(root)
        installed = _installed_identity(root)
        artifact = _wheel_identity(wheel, installed)
        records = _authority_records(root)
        record_blockers, versions = _runtime_version_blockers(records)
        blockers.extend(record_blockers)
        inventory = _runtime_inventory(root, exclude={f"{adoption.RUNTIME_NAME}/{REBIND_RECORD}"})
        adoption_record = records.get("adoption")
        if adoption_record is None:
            blockers.append("rebind requires a confirmed installed adoption handoff")
        elif adoption_record.get("operator") != name:
            blockers.append("rebind operator does not match confirmed adoption handoff")
        epoch = _runtime_epoch(records)
        qualified = _qualified_successor_binding(root, records, artifact)
    except (LifecycleError, adoption.AdoptionError) as exc:
        bootstrap = {}
        installed = {}
        artifact = {}
        records = {}
        versions = []
        inventory = []
        epoch = 0
        qualified = {}
        blockers.append(str(exc))
    baseline = adoption.capture_baseline(root).public()
    inventory_sha256 = _digest(inventory)
    lineage = _lineage(records, inventory_sha256)
    successor_binding = {
        **qualified,
        "installed_identity": installed,
        "candidate_artifact": artifact,
        "new_runtime_epoch": epoch + 1,
        "authority_lineage": lineage,
    }
    body: dict[str, Any] = {
        "schema": REBIND_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "project_baseline": baseline,
        "bootstrap_disposition": bootstrap,
        "installed_identity": installed,
        "candidate_artifact": artifact,
        "detected_runtime_versions": versions,
        "immutable_runtime_inventory": inventory,
        "immutable_runtime_inventory_sha256": inventory_sha256,
        "authority_lineage": lineage,
        "successor_binding": successor_binding,
        "current_runtime_epoch": epoch,
        "new_runtime_epoch": epoch + 1,
        "quiescent": not any("ACTIVE transaction" in blocker for blocker in blockers),
        "no_source_or_ralph_fallback": True,
        "blockers": blockers,
        "admissible": not blockers,
        "requires_explicit_confirmation": True,
        "confirmation": "REBIND",
    }
    body["preview_sha256"] = _digest(body)
    return body


def _commit_rebind(project: Path, operator: str, wheel: Path, preview_sha256: str, parent_pid: int) -> dict[str, Any]:
    """Write the transfer receipt only in the separately-started executable."""
    if parent_pid <= 0 or parent_pid == os.getpid() or parent_pid != os.getppid():
        raise LifecycleError("rebind commit requires a separately started installed executable")
    expected = transactions._require_digest(preview_sha256, "--preview")
    preview = build_rebind_preview(project, operator, wheel)
    if preview["preview_sha256"] != expected:
        raise LifecycleError("rebind preview is stale; identity, artifact, project, or authority lineage changed")
    if not preview["admissible"]:
        raise LifecycleError("rebind refused: " + "; ".join(preview["blockers"]))
    identity = preview["installed_identity"]
    if Path(identity["executable"]).resolve() != Path(sys.argv[0]).resolve():
        # Console wrappers frequently use an absolute argv[0]; a copied wrapper
        # cannot silently claim the previewed installed executable.
        raise LifecycleError("rebind commit executable differs from the previewed installed executable")
    records = _authority_records(Path(preview["worktree"]))
    predecessor_transaction = records.get("transaction")
    predecessor_controller = records.get("controller")
    if predecessor_transaction is None or predecessor_controller is None:
        raise LifecycleError("rebind predecessor transaction/controller authority is unavailable")
    binding = preview["successor_binding"]
    try:
        successor_transaction = transactions.successor_transaction(predecessor_transaction, binding)
        successor_controller = controller.successor_controller(predecessor_controller, successor_transaction, binding)
    except (transactions.TransactionError, controller.ControllerError) as exc:
        raise LifecycleError(str(exc)) from exc
    record = {
        "schema": REBIND_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "preview_sha256": expected,
        "parent_process": parent_pid,
        "fresh_process": {"pid": os.getpid(), "executable": identity["executable"]},
        "new_runtime_epoch": preview["new_runtime_epoch"],
        "installed_identity": identity,
        "candidate_artifact": preview["candidate_artifact"],
        "bootstrap_disposition": preview["bootstrap_disposition"],
        "authority_lineage": preview["authority_lineage"],
        "successor_binding": binding,
        "successor_transaction": successor_transaction,
        "successor_controller": successor_controller,
        "immutable_runtime_inventory_sha256": preview["immutable_runtime_inventory_sha256"],
        "quiescent_handoff": True,
        "source_tree_fallback": False,
        "ralph_fallback": False,
        "result": "REBIND_COMPLETED_BY_FRESH_INSTALLED_PROCESS",
    }
    record["record_sha256"] = _digest(record)
    root = Path(preview["worktree"])
    try:
        adoption.write_runtime_record(root, transactions.TRANSACTION_RECORD, successor_transaction, actor="controller")
        adoption.write_runtime_record(root, controller.CONTROLLER_RECORD, successor_controller, actor="controller")
    except OSError as exc:
        # A successor is never allowed to strand a partially replaced authority.
        adoption.write_runtime_record(root, transactions.TRANSACTION_RECORD, predecessor_transaction, actor="controller")
        adoption.write_runtime_record(root, controller.CONTROLLER_RECORD, predecessor_controller, actor="controller")
        raise LifecycleError("fresh installed rebind handoff failed before authority transfer") from exc
    try:
        live_identity = _installed_identity(root)
        live_records = _authority_records(root)
        if (
            live_identity != identity
            or live_records.get("transaction", {}).get("record_sha256") != successor_transaction["record_sha256"]
            or live_records.get("controller", {}).get("record_sha256") != successor_controller["record_sha256"]
        ):
            raise LifecycleError("fresh installed rebind successor authority or identity is not live")
    except (LifecycleError, adoption.AdoptionError) as exc:
        raise LifecycleError("fresh installed rebind successor authority or identity is not live") from exc
    adoption.write_runtime_record(root, REBIND_RECORD, record, actor="controller")
    try:
        planning.complete_required_transition(root, preview["operator"], attestation=record)
    except planning.PlanningError as exc:
        raise LifecycleError(f"fresh installed rebind did not complete its required transition: {exc}") from exc
    return record


def accept_rebind(project: Path, operator: str, wheel: Path, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "REBIND":
        raise LifecycleError("explicit confirmation required: --confirm REBIND")
    expected = transactions._require_digest(preview_sha256, "--preview")
    preview = build_rebind_preview(project, operator, wheel)
    if preview["preview_sha256"] != expected:
        raise LifecycleError("rebind preview is stale; identity, artifact, project, or authority lineage changed")
    if not preview["admissible"]:
        raise LifecycleError("rebind refused: " + "; ".join(preview["blockers"]))
    command = preview["installed_identity"]["executable"]
    if Path(command).resolve() != Path(sys.argv[0]).resolve():
        raise LifecycleError("rebind must be initiated by the previewed installed Stygnox executable")
    # The transfer must not inherit a source checkout through the working
    # directory or Python's import environment.  The child receives only an
    # absolute installed launcher, absolute inputs, and a neutral cwd.
    # The child must be able to rediscover this exact launcher through its
    # normal installed-identity guard, including venv/user installations that
    # are intentionally outside the platform-default PATH.
    child_environment = {"PATH": str(Path(command).parent)}
    child = subprocess.run(
        [command, "upgrade", "rebind-commit", "--project", preview["worktree"], "--operator", preview["operator"],
         "--wheel", str(wheel.resolve()), "--preview", expected, "--confirm", "REBIND", "--parent-pid", str(os.getpid())],
        cwd=preview["installed_identity"]["site_packages"], env=child_environment, text=True, capture_output=True, check=False,
    )
    if child.returncode != 0:
        detail = (child.stderr or child.stdout).strip()
        raise LifecycleError(f"fresh installed rebind handoff failed before transfer: {detail or child.returncode}")
    try:
        receipt = json.loads(child.stdout)
    except json.JSONDecodeError as exc:
        raise LifecycleError("fresh installed rebind handoff returned invalid receipt") from exc
    if not isinstance(receipt, dict) or receipt.get("preview_sha256") != expected or receipt.get("fresh_process", {}).get("pid") == os.getpid():
        raise LifecycleError("fresh installed rebind handoff did not prove a new process")
    root = Path(preview["worktree"])
    committed = _load_json(root / adoption.RUNTIME_NAME / REBIND_RECORD, schema=REBIND_SCHEMA)
    if committed is None or committed.get("record_sha256") != _digest({key: value for key, value in committed.items() if key != "record_sha256"}):
        raise LifecycleError("fresh installed rebind handoff did not leave a valid transfer receipt")
    if receipt != committed:
        raise LifecycleError("fresh installed rebind handoff receipt differs from its committed authority record")
    if (
        committed.get("preview_sha256") != expected
        or committed.get("parent_process") != os.getpid()
        or committed.get("fresh_process", {}).get("executable") != preview["installed_identity"]["executable"]
        or committed.get("new_runtime_epoch") != preview["new_runtime_epoch"]
        or committed.get("installed_identity") != preview["installed_identity"]
        or committed.get("candidate_artifact") != preview["candidate_artifact"]
        or committed.get("bootstrap_disposition") != preview["bootstrap_disposition"]
        or committed.get("authority_lineage") != preview["authority_lineage"]
        or committed.get("successor_binding") != preview["successor_binding"]
        or committed.get("immutable_runtime_inventory_sha256") != preview["immutable_runtime_inventory_sha256"]
        or committed.get("quiescent_handoff") is not True
        or committed.get("source_tree_fallback") is not False
        or committed.get("ralph_fallback") is not False
    ):
        raise LifecycleError("fresh installed rebind handoff changed the bound authority lineage")
    return receipt


def _runtime_version_blockers(records: Mapping[str, dict[str, Any] | None]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    versions: set[str] = set()
    current_dev = _compatibility_dev_ceiling(PRODUCT.version)
    assert current_dev is not None
    for name, record in records.items():
        if record is None:
            continue
        version = str(record.get("product_version") or "")
        if not version:
            continue
        versions.add(version)
        if version == PRODUCT.version:
            continue
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
        ("rebind-preview", "bind an installed wheel and quiescent authority lineage without changing state"),
        ("rebind", "confirm a fresh-process installed authority rebind"),
        ("rebind-commit", argparse.SUPPRESS),
    ):
        command = sub.add_parser(action, help=help_text)
        command.add_argument("--project", type=Path, default=Path.cwd())
        command.add_argument("--operator", required=True)
        if action == "accept":
            command.add_argument("--preview", required=True)
            command.add_argument("--confirm", required=True, help="must be UPGRADE")
        if action.startswith("rebind"):
            command.add_argument("--wheel", type=Path, required=True)
        if action in {"rebind", "rebind-commit"}:
            command.add_argument("--preview", required=True)
            command.add_argument("--confirm", required=True, help="must be REBIND")
        if action == "rebind-commit":
            command.add_argument("--parent-pid", type=int, required=True)
    return parser


def upgrade_cli_main(argv: Sequence[str] | None = None) -> int:
    parser = build_upgrade_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview":
            result = build_upgrade_preview(args.project, args.operator)
        elif args.action == "accept":
            result = accept_upgrade(args.project, args.operator, args.preview, args.confirm)
        elif args.action == "rebind-preview":
            result = build_rebind_preview(args.project, args.operator, args.wheel)
        elif args.action == "rebind":
            result = accept_rebind(args.project, args.operator, args.wheel, args.preview, args.confirm)
        else:
            if args.confirm != "REBIND":
                raise LifecycleError("explicit confirmation required: --confirm REBIND")
            result = _commit_rebind(args.project, args.operator, args.wheel, args.preview, args.parent_pid)
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
