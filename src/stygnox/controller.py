"""Neutral installed Stygnox controller authority for D8.5.

Controller activation is a separate human gate after adoption and transaction
binding.  Provider execution is impossible with neutral defaults and is bound
to an exact, reviewer-approved tracked execution policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from . import adoption, execution_policy, transactions
from .product import PRODUCT
from .profile import DEFAULT_PROFILE, profile_record
from . import provider_codex


CONTROLLER_SCHEMA = "stygnox_controller_state_v1"
RUN_PREVIEW_SCHEMA = "stygnox_controller_run_preview_v1"
RUN_RESULT_SCHEMA = "stygnox_controller_run_result_v1"
CONTROLLER_RECORD = "controller.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ControllerError(RuntimeError):
    """Fail-closed neutral-controller error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _runtime_json(root: Path, name: str, *, required: bool = True) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / name
    if not path.exists():
        if required:
            raise ControllerError(f"controller runtime record is missing: {name}")
        return None
    if path.is_symlink() or not path.is_file():
        raise ControllerError(f"controller runtime record must be a regular file: {name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControllerError(f"invalid controller runtime record {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControllerError(f"controller runtime record must be a JSON object: {name}")
    return value


def _handoff(root: Path) -> dict[str, Any]:
    value = _runtime_json(root, "adoption.json")
    assert value is not None
    if value.get("schema") != adoption.HANDOFF_SCHEMA:
        raise ControllerError("unsupported adoption authority schema")
    return value


def _transaction(root: Path) -> dict[str, Any]:
    value = transactions._transaction(root)
    assert value is not None
    if value.get("state") != "ACTIVE":
        raise ControllerError("controller activation/execution requires an ACTIVE transaction")
    return value


def _operator(value: str) -> str:
    try:
        return adoption._validated_operator(value)
    except adoption.AdoptionError as exc:
        raise ControllerError(str(exc)) from exc


def _controller(root: Path, *, required: bool = True) -> dict[str, Any] | None:
    value = _runtime_json(root, CONTROLLER_RECORD, required=required)
    if value is None:
        return None
    if value.get("schema") != CONTROLLER_SCHEMA:
        raise ControllerError("unsupported installed controller state schema")
    return value


def _policy_status(root: Path) -> dict[str, Any]:
    try:
        status = execution_policy.show_policy(root)
    except execution_policy.ExecutionPolicyError as exc:
        raise ControllerError(str(exc)) from exc
    policy = status["policy"]
    if policy.get("provider") and not status.get("approved"):
        raise ControllerError("non-neutral execution policy is not bound to an approved reviewer record")
    return status


def activate_controller(project: Path, operator: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "ACTIVATE":
        raise ControllerError("explicit confirmation required: --confirm ACTIVATE")
    root = adoption.resolve_worktree(project)
    handoff = _handoff(root)
    tx = _transaction(root)
    name = _operator(operator)
    if handoff.get("operator") != name or tx.get("operator") != name:
        raise ControllerError("controller operator does not match adoption/transaction authority")
    command = adoption.resolve_installed_command(root)
    policy_status = _policy_status(root)
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") != tx.get("authority_baseline_sha256"):
        raise ControllerError("project changed after transaction begin; controller activation requires fresh authority")
    existing = _controller(root, required=False)
    if existing is not None and existing.get("enabled") is True:
        if existing.get("transaction_id") == tx.get("transaction_id"):
            return {**existing, "result": "CONTROLLER_ALREADY_ACTIVE"}
        raise ControllerError("a controller is already active for a different transaction")
    body: dict[str, Any] = {
        "schema": CONTROLLER_SCHEMA,
        "product_version": PRODUCT.version,
        "enabled": True,
        "controller_execution_enabled": True,
        "operator": name,
        "transaction_id": tx["transaction_id"],
        "authority_baseline_sha256": tx["authority_baseline_sha256"],
        "profile": profile_record(),
        "installed_command": str(command.executable),
        "source_tree_dependency": False,
        "local_controller_fallback": False,
        "execution_policy": policy_status["policy"],
        "execution_policy_review": policy_status.get("review"),
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "provider_execution_ready": bool(
            policy_status["policy"].get("provider") and policy_status["policy"].get("model") and policy_status.get("approved")
        ),
    }
    body["record_sha256"] = _digest(body)
    adoption.write_runtime_record(root, CONTROLLER_RECORD, body, actor="controller")
    return {**body, "result": "CONTROLLER_ACTIVE"}


def deactivate_controller(project: Path, operator: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "DEACTIVATE":
        raise ControllerError("explicit confirmation required: --confirm DEACTIVATE")
    root = adoption.resolve_worktree(project)
    current = _controller(root)
    assert current is not None
    name = _operator(operator)
    if current.get("operator") != name:
        raise ControllerError("controller operator does not match active authority")
    updated = dict(current)
    updated["enabled"] = False
    updated["controller_execution_enabled"] = False
    updated["deactivation_reason"] = "operator-confirmed"
    updated.pop("record_sha256", None)
    updated["record_sha256"] = _digest(updated)
    adoption.write_runtime_record(root, CONTROLLER_RECORD, updated, actor="controller")
    return {**updated, "result": "CONTROLLER_INACTIVE"}


def controller_status(project: Path) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    status = _controller(root, required=False)
    policy = _policy_status(root)
    return {
        "schema": "stygnox_controller_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "profile": profile_record(),
        "controller": status,
        "execution_policy": policy,
        "controller_execution_enabled": bool(status and status.get("enabled") is True),
    }


def _objective(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 20_000 or "\x00" in text:
        raise ControllerError("--objective must be 1-20000 characters")
    return text


def build_run_preview(
    project: Path,
    operator: str,
    objective: str,
    repository_authority: str,
) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    controller = _controller(root)
    assert controller is not None
    if controller.get("enabled") is not True:
        raise ControllerError("controller execution is not active")
    tx = _transaction(root)
    name = _operator(operator)
    if controller.get("operator") != name or tx.get("operator") != name:
        raise ControllerError("run operator does not match active controller authority")
    if controller.get("transaction_id") != tx.get("transaction_id"):
        raise ControllerError("controller activation is stale for the active transaction")
    authority = str(repository_authority or "").strip().lower()
    if authority not in {"read-only", "write"}:
        raise ControllerError("--repository-authority must be read-only or write")
    policy_status = _policy_status(root)
    policy = policy_status["policy"]
    provider = policy.get("provider")
    model = policy.get("model")
    if not provider or not model:
        raise ControllerError("provider execution refused: tracked provider/model defaults are neutral")
    if provider != provider_codex.PROVIDER_NAME:
        raise ControllerError(f"unsupported installed provider adapter: {provider!r}")
    if not policy_status.get("approved"):
        raise ControllerError("provider execution refused: non-neutral policy is not reviewer-approved")
    if int(policy.get("max_loops") or 1) != 1:
        raise ControllerError("D8.5 installed controller executes exactly one reviewed loop; max_loops must be 1")
    current = adoption.capture_baseline(root).public()
    body: dict[str, Any] = {
        "schema": RUN_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "profile": profile_record(),
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": controller["record_sha256"],
        "project_baseline": current,
        "objective": _objective(objective),
        "repository_authority": authority,
        "provider": provider,
        "model": model,
        "effort": policy.get("effort"),
        "execution_controls": {
            key: policy[key]
            for key in ("efficiency_mode", "reserve_percent", "wait_for_limits", "usage_poll_seconds", "max_loops")
        },
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "review_sha256": (policy_status.get("review") or {}).get("review_sha256"),
        "requires_explicit_confirmation": True,
        "confirmation": "RUN",
    }
    body["preview_sha256"] = _digest(body)
    return body


def _prompt(preview: Mapping[str, Any]) -> str:
    authority = preview["repository_authority"]
    return (
        "You are an implementation worker invoked by the installed Stygnox controller. "
        "The controller, not you, owns authority and runtime evidence. "
        "Never create, edit, delete, rename, or adopt content under .stygnox/. "
        f"Repository authority for this single reviewed turn is {authority}. "
        "Do not access secrets, credentials, or external production systems. "
        "Return only the requested structured result.\n\n"
        f"Objective:\n{preview['objective']}\n"
    )


def run_controller(
    project: Path,
    operator: str,
    objective: str,
    repository_authority: str,
    preview_sha256: str,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != "RUN":
        raise ControllerError("explicit confirmation required: --confirm RUN")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise ControllerError("--preview must be the exact 64-character preview SHA-256")
    preview = build_run_preview(project, operator, objective, repository_authority)
    if preview["preview_sha256"] != expected:
        raise ControllerError("controller run preview is stale; authority, policy, objective, or project baseline changed")
    root = Path(preview["worktree"])
    before = adoption.capture_baseline(root).public()
    try:
        provider_result = provider_codex.execute(
            cwd=root,
            prompt=_prompt(preview),
            model=str(preview["model"]),
            effort=preview.get("effort"),
            repository_authority=str(preview["repository_authority"]),
        )
    except provider_codex.ProviderError as exc:
        raise ControllerError(str(exc)) from exc
    after = adoption.capture_baseline(root).public()
    if preview["repository_authority"] == "read-only" and after.get("sha256") != before.get("sha256"):
        raise ControllerError("read-only provider turn changed the project baseline")
    from .operator import status_attribution

    attribution = status_attribution(before, after) if preview["repository_authority"] == "write" else {
        "controller_native_paths": [],
        "operator_baseline_paths": [],
        "overlap_unresolved_paths": [],
        "removed_preexisting_paths": [],
    }
    result: dict[str, Any] = {
        "schema": RUN_RESULT_SCHEMA,
        "product_version": PRODUCT.version,
        "controller_execution_enabled": True,
        "operator": preview["operator"],
        "transaction_id": preview["transaction_id"],
        "preview_sha256": expected,
        "profile": preview["profile"],
        "repository_authority": preview["repository_authority"],
        "provider_result": provider_result,
        "before_baseline_sha256": before["sha256"],
        "after_baseline_sha256": after["sha256"],
        "project_changed": before["sha256"] != after["sha256"],
        "change_attribution": attribution,
        "next_action": "qualification-required" if before["sha256"] != after["sha256"] else "turn-complete",
    }
    result["record_sha256"] = _digest(result)
    adoption.write_runtime_record(root, f"controller-run-{expected[:16]}.json", result, actor="controller")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox controller",
        description="Neutral installed controller authority and one-turn provider execution surface.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    def project_arg(command: argparse.ArgumentParser) -> None:
        command.add_argument("--project", type=Path, default=Path.cwd())

    status = sub.add_parser("status", help="show neutral installed controller state")
    project_arg(status)

    activate = sub.add_parser("activate", help="activate installed controller authority for the active transaction")
    project_arg(activate)
    activate.add_argument("--operator", required=True)
    activate.add_argument("--confirm", required=True)

    deactivate = sub.add_parser("deactivate", help="revoke installed controller execution authority")
    project_arg(deactivate)
    deactivate.add_argument("--operator", required=True)
    deactivate.add_argument("--confirm", required=True)

    preview = sub.add_parser("run-preview", help="preview one exact provider turn without execution")
    project_arg(preview)
    preview.add_argument("--operator", required=True)
    preview.add_argument("--objective", required=True)
    preview.add_argument("--repository-authority", required=True, choices=["read-only", "write"])

    run = sub.add_parser("run", help="execute one exact reviewed provider turn")
    project_arg(run)
    run.add_argument("--operator", required=True)
    run.add_argument("--objective", required=True)
    run.add_argument("--repository-authority", required=True, choices=["read-only", "write"])
    run.add_argument("--preview", required=True)
    run.add_argument("--confirm", required=True)
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    import sys

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "status":
            result = controller_status(args.project)
        elif args.action == "activate":
            result = activate_controller(args.project, args.operator, args.confirm)
        elif args.action == "deactivate":
            result = deactivate_controller(args.project, args.operator, args.confirm)
        elif args.action == "run-preview":
            result = build_run_preview(args.project, args.operator, args.objective, args.repository_authority)
        else:
            result = run_controller(
                args.project,
                args.operator,
                args.objective,
                args.repository_authority,
                args.preview,
                args.confirm,
            )
    except (ControllerError, adoption.AdoptionError, transactions.TransactionError) as exc:
        print(f"stygnox: controller refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
