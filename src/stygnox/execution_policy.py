"""Tracked, reviewer-bound execution policy for Stygnox D8.5.

Provider/model/effort are deliberately neutral by default.  Any non-neutral
selection must be present in tracked configuration and bound to a named reviewer
before controller activation or provider execution can occur.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping, Sequence

from . import efficiency
from .profile import DEFAULT_PROFILE, profile_record
from .product import PRODUCT


CONFIG_SCHEMA = "stygnox_project_config_v1"
POLICY_PREVIEW_SCHEMA = "stygnox_execution_policy_preview_v1"
POLICY_REVIEW_SCHEMA = "stygnox_execution_policy_review_v1"
POLICY_RECORD = "execution-policy.json"
MODES = ("STRICT", "NORMAL", "RELAXED", "OFF")
DEFAULT_EXECUTION = {
    "efficiency_mode": "RELAXED",
    "reserve_percent": 5.0,
    "wait_for_limits": True,
    "usage_poll_seconds": 60,
    "max_loops": 1,
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_EFFORT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")


class ExecutionPolicyError(RuntimeError):
    """Fail-closed execution-policy error."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: str | None, name: str, *, allow_empty: bool = True) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return None
        raise ExecutionPolicyError(f"{name} must be non-empty")
    if not _NAME_RE.fullmatch(raw):
        raise ExecutionPolicyError(f"{name} contains unsupported characters")
    return raw


def _reviewer(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) > 128 or any(ord(char) < 32 for char in raw):
        raise ExecutionPolicyError("--reviewer must be 1-128 printable characters")
    return raw


def _effort(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if not _EFFORT_RE.fullmatch(raw):
        raise ExecutionPolicyError("effort contains unsupported characters")
    return raw


def _reserve(value: float | int | str | None) -> float:
    if value is None:
        return float(DEFAULT_EXECUTION["reserve_percent"])
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionPolicyError("reserve_percent must be numeric") from exc
    if not 0.0 <= number <= 50.0:
        raise ExecutionPolicyError("reserve_percent must be between 0 and 50")
    return number


def _positive_int(value: int | str | None, name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionPolicyError(f"{name} must be an integer") from exc
    if not 1 <= number <= maximum:
        raise ExecutionPolicyError(f"{name} must be between 1 and {maximum}")
    return number


def normalize_policy(
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    efficiency_mode: str | None = None,
    reserve_percent: float | int | str | None = None,
    wait_for_limits: bool | None = None,
    usage_poll_seconds: int | str | None = None,
    max_loops: int | str | None = None,
    reviewer: str | None = None,
    detailed_limits: Mapping[str, Any] | None = None,
    require_reviewer: bool = True,
) -> dict[str, Any]:
    selected_provider = _text(provider, "provider")
    selected_model = _text(model, "model")
    selected_effort = _effort(effort)
    selected_reviewer = _reviewer(reviewer)
    if bool(selected_provider) != bool(selected_model):
        raise ExecutionPolicyError("provider and model must be selected together")
    if selected_effort and not selected_model:
        raise ExecutionPolicyError("effort requires an explicitly selected provider and model")
    non_neutral = any((selected_provider, selected_model, selected_effort))
    if non_neutral and require_reviewer and not selected_reviewer:
        raise ExecutionPolicyError("non-neutral provider/model/effort requires a named --reviewer")
    mode = str(efficiency_mode or DEFAULT_EXECUTION["efficiency_mode"]).strip().upper()
    if mode not in MODES:
        raise ExecutionPolicyError(f"efficiency_mode must be one of: {', '.join(MODES)}")
    try:
        details = efficiency.normalize_details(detailed_limits)
    except efficiency.EfficiencyError as exc:
        raise ExecutionPolicyError(str(exc)) from exc
    return {
        "provider": selected_provider,
        "model": selected_model,
        "effort": selected_effort,
        "reviewer": selected_reviewer,
        "non_neutral": non_neutral,
        "efficiency_mode": mode,
        "reserve_percent": _reserve(reserve_percent),
        "wait_for_limits": DEFAULT_EXECUTION["wait_for_limits"] if wait_for_limits is None else bool(wait_for_limits),
        "usage_poll_seconds": _positive_int(
            usage_poll_seconds, "usage_poll_seconds", int(DEFAULT_EXECUTION["usage_poll_seconds"]), 3600
        ),
        "max_loops": _positive_int(max_loops, "max_loops", int(DEFAULT_EXECUTION["max_loops"]), 1000),
        **details,
    }


def neutral_policy() -> dict[str, Any]:
    return normalize_policy()


def _toml_string(value: str | None) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def render_config(policy: Mapping[str, Any]) -> str:
    normalized = normalize_policy(
        provider=policy.get("provider"),
        model=policy.get("model"),
        effort=policy.get("effort"),
        efficiency_mode=policy.get("efficiency_mode"),
        reserve_percent=policy.get("reserve_percent"),
        wait_for_limits=policy.get("wait_for_limits"),
        usage_poll_seconds=policy.get("usage_poll_seconds"),
        max_loops=policy.get("max_loops"),
        reviewer=policy.get("reviewer"),
        detailed_limits=policy,
    )
    profile = DEFAULT_PROFILE
    return (
        f'schema = "{CONFIG_SCHEMA}"\n'
        f'runtime_directory = "{profile.runtime_directory}"\n'
        f'policy_file = "{profile.tracked_policy}"\n'
        "\n[profile]\n"
        f'name = "{profile.name}"\n'
        f'identity = "{profile.identity}"\n'
        f'controller_command = "{profile.controller_command}"\n'
        f'artifact_namespace = "{profile.artifact_namespace}"\n'
        "\n[defaults]\n"
        f'provider = {_toml_string(normalized["provider"])}\n'
        f'model = {_toml_string(normalized["model"])}\n'
        f'effort = {_toml_string(normalized["effort"])}\n'
        "\n[execution]\n"
        f'efficiency_mode = "{normalized["efficiency_mode"]}"\n'
        f'reserve_percent = {normalized["reserve_percent"]:.1f}\n'
        f'wait_for_limits = {str(normalized["wait_for_limits"]).lower()}\n'
        f'usage_poll_seconds = {normalized["usage_poll_seconds"]}\n'
        f'max_loops = {normalized["max_loops"]}\n'
        + "".join(f'{key} = {normalized[key]}\n' for key in efficiency.DETAIL_FIELDS)
        + "\n[authority]\n"
        'stage = "neutral-controller-authority"\n'
        "controller_execution = false\n"
    )


def config_policy(root: Path) -> dict[str, Any]:
    path = root / DEFAULT_PROFILE.tracked_config
    if path.is_symlink() or not path.is_file():
        raise ExecutionPolicyError(f"tracked configuration is missing or non-regular: {path.name}")
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExecutionPolicyError(f"cannot parse tracked configuration: {exc}") from exc
    if value.get("schema") != CONFIG_SCHEMA:
        raise ExecutionPolicyError(f"unsupported tracked configuration schema: {value.get('schema')!r}")
    profile = value.get("profile") if isinstance(value.get("profile"), dict) else {}
    expected_profile = profile_record()
    for key in ("name", "identity", "controller_command", "artifact_namespace"):
        if profile.get(key) != expected_profile[key]:
            raise ExecutionPolicyError(f"tracked configuration overrides installed neutral profile field {key!r}")
    defaults = value.get("defaults") if isinstance(value.get("defaults"), dict) else {}
    execution = value.get("execution") if isinstance(value.get("execution"), dict) else {}
    return normalize_policy(
        provider=defaults.get("provider"),
        model=defaults.get("model"),
        effort=defaults.get("effort"),
        efficiency_mode=execution.get("efficiency_mode"),
        reserve_percent=execution.get("reserve_percent"),
        wait_for_limits=execution.get("wait_for_limits"),
        usage_poll_seconds=execution.get("usage_poll_seconds"),
        max_loops=execution.get("max_loops"),
        reviewer=None,
        detailed_limits=execution,
        require_reviewer=False,
    )


def policy_review(policy: Mapping[str, Any], reviewer: str | None) -> dict[str, Any]:
    selected_reviewer = _reviewer(reviewer)
    non_neutral = any(policy.get(key) for key in ("provider", "model", "effort"))
    if non_neutral and not selected_reviewer:
        raise ExecutionPolicyError("non-neutral provider/model/effort requires a named reviewer")
    body = {
        "schema": POLICY_REVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "profile": DEFAULT_PROFILE.name,
        "reviewer": selected_reviewer,
        "neutral_defaults": not non_neutral,
        "provider": policy.get("provider"),
        "model": policy.get("model"),
        "effort": policy.get("effort"),
        "execution": {
            key: policy[key]
            for key in (
                "efficiency_mode", "reserve_percent", "wait_for_limits", "usage_poll_seconds", "max_loops",
                *efficiency.DETAIL_FIELDS,
            )
        },
    }
    body["review_sha256"] = _digest(body)
    return body


def _load_runtime_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ExecutionPolicyError(f"runtime policy record must be a regular file: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionPolicyError(f"invalid runtime policy record: {exc}") from exc
    if not isinstance(value, dict):
        raise ExecutionPolicyError("runtime policy record must be a JSON object")
    return value


def show_policy(project: Path) -> dict[str, Any]:
    from . import adoption

    root = adoption.resolve_worktree(project)
    policy = config_policy(root)
    config_text = (root / adoption.CONFIG_NAME).read_text(encoding="utf-8")
    adoption_record = _load_runtime_json(root / adoption.RUNTIME_NAME / "adoption.json")
    runtime_record = _load_runtime_json(root / adoption.RUNTIME_NAME / POLICY_RECORD)
    review = runtime_record or (adoption_record or {}).get("execution_policy_review")
    approved = False
    if isinstance(review, dict) and review.get("schema") == POLICY_REVIEW_SCHEMA:
        approved = all(review.get(key) == policy.get(key) for key in ("provider", "model", "effort"))
        if policy.get("provider") and not review.get("reviewer"):
            approved = False
    return {
        "schema": "stygnox_execution_policy_status_v1",
        "product_version": PRODUCT.version,
        "worktree": str(root),
        "profile": profile_record(),
        "policy": policy,
        "tracked_config_sha256": _sha256_text(config_text),
        "review": review,
        "approved": approved if policy.get("provider") else True,
        "controller_execution_default": False,
    }


def _merge_current(
    current: Mapping[str, Any],
    *,
    provider: str | None,
    model: str | None,
    effort: str | None,
    efficiency_mode: str | None,
    reserve_percent: float | None,
    wait_for_limits: bool | None,
    usage_poll_seconds: int | None,
    max_loops: int | None,
    detailed_limits: Mapping[str, Any] | None,
    reviewer: str | None,
    reset: bool,
) -> dict[str, Any]:
    if reset:
        return neutral_policy()
    selected_provider = current.get("provider") if provider is None else provider
    selected_model = current.get("model") if model is None else model
    selected_effort = current.get("effort") if effort is None else effort
    return normalize_policy(
        provider=selected_provider,
        model=selected_model,
        effort=selected_effort,
        efficiency_mode=current.get("efficiency_mode") if efficiency_mode is None else efficiency_mode,
        reserve_percent=current.get("reserve_percent") if reserve_percent is None else reserve_percent,
        wait_for_limits=current.get("wait_for_limits") if wait_for_limits is None else wait_for_limits,
        usage_poll_seconds=current.get("usage_poll_seconds") if usage_poll_seconds is None else usage_poll_seconds,
        max_loops=current.get("max_loops") if max_loops is None else max_loops,
        detailed_limits={
            key: (dict(detailed_limits or {}).get(key) if dict(detailed_limits or {}).get(key) is not None else current.get(key))
            for key in efficiency.DETAIL_FIELDS
        },
        reviewer=reviewer,
    )


def build_policy_preview(
    project: Path,
    operator: str,
    *,
    reviewer: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    efficiency_mode: str | None = None,
    reserve_percent: float | None = None,
    wait_for_limits: bool | None = None,
    usage_poll_seconds: int | None = None,
    max_loops: int | None = None,
    detailed_limits: Mapping[str, Any] | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    from . import adoption, transactions

    root = adoption.resolve_worktree(project)
    name = adoption._validated_operator(operator)
    handoff = _load_runtime_json(root / adoption.RUNTIME_NAME / "adoption.json")
    if not isinstance(handoff, dict) or handoff.get("schema") != adoption.HANDOFF_SCHEMA:
        raise ExecutionPolicyError("execution policy requires a confirmed Stygnox adoption handoff")
    if handoff.get("operator") != name:
        raise ExecutionPolicyError("execution-policy operator does not match adoption handoff")
    transaction = transactions._transaction(root, required=False)
    if transaction is not None:
        raise ExecutionPolicyError("execution policy can change only before the first transaction begins; re-adopt after recovery")
    current_baseline = adoption.capture_baseline(root).public()
    expected_baseline = (handoff.get("authority_baseline") or {}).get("sha256")
    if current_baseline.get("sha256") != expected_baseline:
        raise ExecutionPolicyError("project changed after handoff; execution-policy confirmation is stale")
    current = config_policy(root)
    desired = _merge_current(
        current,
        provider=provider,
        model=model,
        effort=effort,
        efficiency_mode=efficiency_mode,
        reserve_percent=reserve_percent,
        wait_for_limits=wait_for_limits,
        usage_poll_seconds=usage_poll_seconds,
        max_loops=max_loops,
        detailed_limits=detailed_limits,
        reviewer=reviewer,
        reset=reset,
    )
    selected_reviewer = None if reset else _reviewer(reviewer)
    review = policy_review(desired, selected_reviewer)
    before = (root / adoption.CONFIG_NAME).read_text(encoding="utf-8")
    after = render_config({**desired, "reviewer": selected_reviewer})
    body = {
        "schema": POLICY_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "profile": profile_record(),
        "action": "reset" if reset else "set",
        "baseline_sha256": current_baseline["sha256"],
        "before_config_sha256": _sha256_text(before),
        "after_config_sha256": _sha256_text(after),
        "current": current,
        "proposed": desired,
        "review": review,
        "tracked_change": before != after,
        "controller_execution": False,
        "requires_explicit_confirmation": True,
        "confirmation": "RESET" if reset else "SET",
    }
    body["preview_sha256"] = _digest(body)
    return body


def apply_policy(
    project: Path,
    operator: str,
    preview_sha256: str,
    confirmation: str,
    **kwargs: Any,
) -> dict[str, Any]:
    from . import adoption

    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise ExecutionPolicyError("--preview must be the exact 64-character preview SHA-256")
    reset = bool(kwargs.get("reset"))
    required = "RESET" if reset else "SET"
    if confirmation != required:
        raise ExecutionPolicyError(f"explicit confirmation required: --confirm {required}")
    preview = build_policy_preview(project, operator, **kwargs)
    if preview["preview_sha256"] != expected:
        raise ExecutionPolicyError("execution-policy preview is stale; baseline, configuration, or requested policy changed")
    root = Path(preview["worktree"])
    after = render_config({**preview["proposed"], "reviewer": preview["review"].get("reviewer")})
    adoption._atomic_write(root / adoption.CONFIG_NAME, after)
    new_baseline = adoption.capture_baseline(root).public()
    handoff_path = root / adoption.RUNTIME_NAME / "adoption.json"
    handoff = _load_runtime_json(handoff_path)
    assert isinstance(handoff, dict)
    handoff["authority_baseline"] = new_baseline
    handoff["execution_policy_review"] = preview["review"]
    handoff["execution_policy_preview_sha256"] = expected
    handoff["controller_execution"] = False
    handoff["next_stage"] = "D8.5 neutral controller activation after transaction begin"
    handoff["product_version"] = PRODUCT.version
    adoption.write_runtime_record(root, "adoption.json", handoff, actor="controller")
    record = {
        "schema": POLICY_REVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": preview["operator"],
        "action": preview["action"],
        "preview_sha256": expected,
        "tracked_config_sha256": _sha256_text(after),
        "authority_baseline_sha256": new_baseline["sha256"],
        **preview["review"],
    }
    record["record_sha256"] = _digest(record)
    adoption.write_runtime_record(root, POLICY_RECORD, record, actor="controller")
    return {
        **record,
        "result": "EXECUTION_POLICY_RESET" if reset else "EXECUTION_POLICY_SET",
        "tracked_change": preview["tracked_change"],
        "controller_execution": False,
    }


def _add_policy_values(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--reviewer")
    parser.add_argument("--efficiency-mode", choices=MODES)
    parser.add_argument("--reserve-percent", type=float)
    wait = parser.add_mutually_exclusive_group()
    wait.add_argument("--wait-for-limits", dest="wait_for_limits", action="store_true")
    wait.add_argument("--no-wait-for-limits", dest="wait_for_limits", action="store_false")
    parser.set_defaults(wait_for_limits=None)
    parser.add_argument("--usage-poll-seconds", type=int)
    parser.add_argument("--max-loops", type=int)
    for key in efficiency.DETAIL_FIELDS:
        parser.add_argument("--" + key.replace("_", "-"), dest=key, type=int)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stygnox execution-policy",
        description="Reviewer-bound tracked execution policy; provider/model/effort default to neutral.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show", help="show effective tracked execution policy and review binding")
    show.add_argument("--project", type=Path, default=Path.cwd())

    preview = sub.add_parser("preview", help="preview an atomic tracked policy set/reset without mutation")
    preview.add_argument("--project", type=Path, default=Path.cwd())
    preview.add_argument("--operator", required=True)
    preview.add_argument("--reset", action="store_true")
    _add_policy_values(preview)

    set_cmd = sub.add_parser("set", help="apply exactly one reviewed execution-policy preview")
    set_cmd.add_argument("--project", type=Path, default=Path.cwd())
    set_cmd.add_argument("--operator", required=True)
    set_cmd.add_argument("--preview", required=True)
    set_cmd.add_argument("--confirm", required=True)
    _add_policy_values(set_cmd)

    reset = sub.add_parser("reset", help="reset to neutral defaults using an exact reset preview")
    reset.add_argument("--project", type=Path, default=Path.cwd())
    reset.add_argument("--operator", required=True)
    reset.add_argument("--preview", required=True)
    reset.add_argument("--confirm", required=True)
    return parser


def _kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "reviewer": getattr(args, "reviewer", None),
        "provider": getattr(args, "provider", None),
        "model": getattr(args, "model", None),
        "effort": getattr(args, "effort", None),
        "efficiency_mode": getattr(args, "efficiency_mode", None),
        "reserve_percent": getattr(args, "reserve_percent", None),
        "wait_for_limits": getattr(args, "wait_for_limits", None),
        "usage_poll_seconds": getattr(args, "usage_poll_seconds", None),
        "max_loops": getattr(args, "max_loops", None),
        "detailed_limits": {key: getattr(args, key, None) for key in efficiency.DETAIL_FIELDS},
    }


def cli_main(argv: Sequence[str] | None = None) -> int:
    import sys

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "show":
            result = show_policy(args.project)
        elif args.action == "preview":
            result = build_policy_preview(args.project, args.operator, reset=args.reset, **_kwargs(args))
        elif args.action == "set":
            result = apply_policy(args.project, args.operator, args.preview, args.confirm, reset=False, **_kwargs(args))
        else:
            result = apply_policy(args.project, args.operator, args.preview, args.confirm, reset=True)
    except ExecutionPolicyError as exc:
        print(f"stygnox: execution policy refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
