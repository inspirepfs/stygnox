"""02N narrow release of installed Codex catalogue and approved proposal-only execution.

A release never carries authority across a worktree, transaction, source revision,
installed package, or policy change. The release has no write-turn permission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import adoption, transactions, execution_policy
from .direct_interruption_execution_guard import refuse_quarantined_runtime, QuarantinedRuntime

SCHEMA = "stygnox_provider_planning_release_v1"
PREVIEW_SCHEMA = "stygnox_provider_planning_release_preview_v1"
RECORD = "provider-planning-release.json"
_catalog_probe: ContextVar[str | None] = ContextVar("stygnox_release_catalog_probe", default=None)
_proposal_turn: ContextVar[str | None] = ContextVar("stygnox_release_proposal_turn", default=None)

class ProviderReleaseError(RuntimeError):
    """Fail-closed provider planning release."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _installed_tree_sha256(package: Path) -> str:
    """Bind all installed Stygnox Python modules, not just the adoption module."""
    root = package.parent
    paths = sorted(root.rglob("*.py"))
    if not paths or package not in paths:
        raise ProviderReleaseError("installed package source inventory is incomplete")
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ProviderReleaseError("installed package contains non-regular Python source")
    return _digest({str(path.relative_to(root)): adoption.sha256_file(path) for path in paths})


def _record(root: Path) -> dict[str, Any] | None:
    path = root / adoption.RUNTIME_NAME / RECORD
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProviderReleaseError("provider planning release record must be regular")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ProviderReleaseError("invalid provider planning release record") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ProviderReleaseError("unsupported provider planning release record")
    body = dict(data)
    recorded = body.pop("record_sha256", None)
    if _digest(body) != recorded:
        raise ProviderReleaseError("provider planning release record integrity failure")
    return data


def _inputs(project: Path, operator: str) -> dict[str, Any]:
    root = adoption.resolve_worktree(project)
    try:
        refuse_quarantined_runtime(root)
    except QuarantinedRuntime as exc:
        raise ProviderReleaseError("quarantined worktree cannot obtain provider authority") from exc
    tx = transactions._transaction(root)
    if tx is None or tx.get("state") != "ACTIVE":
        raise ProviderReleaseError("provider release requires ACTIVE transaction")
    tx_body = dict(tx)
    tx_sha = tx_body.pop("record_sha256", None)
    if _digest(tx_body) != tx_sha:
        raise ProviderReleaseError("transaction integrity check failed")
    handoff = transactions._load_adoption(root)
    if tx.get("operator") != operator or handoff.get("operator") != operator:
        raise ProviderReleaseError("operator is not the transaction owner")
    if tx.get("handoff_preview_sha256") != handoff.get("preview_sha256"):
        raise ProviderReleaseError("transaction adoption identity mismatch")
    baseline = adoption.capture_baseline(root).public()
    if baseline["sha256"] != tx.get("authority_baseline_sha256"):
        raise ProviderReleaseError("project baseline has changed after transaction begin")
    command = adoption.resolve_installed_command(root)
    if str(command.executable) != tx.get("installed_command"):
        raise ProviderReleaseError("installed Stygnox command does not match transaction")
    expected = execution_policy.config_policy(root)
    review = handoff.get("execution_policy_review") or {}
    review_body = dict(review) if isinstance(review, dict) else {}
    review_sha = review_body.pop("review_sha256", None)
    if (review_body.get("schema") != execution_policy.POLICY_REVIEW_SCHEMA
        or review_sha != _digest(review_body)
        or any(review.get(key) != expected.get(key) for key in ("provider", "model", "effort"))
        or expected.get("provider") != "codex" or not expected.get("model")
        or review.get("reviewer") != operator):
        raise ProviderReleaseError("matching, integrity-checked Codex reviewer policy required")
    config_sha = hashlib.sha256((root / adoption.CONFIG_NAME).read_bytes()).hexdigest()
    package = command.package_file
    return {
        "schema": PREVIEW_SCHEMA,
        "worktree": str(root),
        "transaction_id": tx["transaction_id"],
        "transaction_record_sha256": tx_sha,
        "handoff_preview_sha256": tx["handoff_preview_sha256"],
        "baseline_sha256": baseline["sha256"],
        "operator": operator,
        "installed_command": str(command.executable),
        "installed_package": str(package),
        "installed_package_sha256": adoption.sha256_file(package),
        "installed_package_tree_sha256": _installed_tree_sha256(package),
        "config_sha256": config_sha,
        "review_sha256": review_sha,
        "provider": "codex",
        "model": expected["model"],
        "effort": expected.get("effort"),
        "scope": "catalogue-and-confirmed-plan-proposal-only",
        "provider_write_turn": False,
        "confirmation": "RELEASE_PLANNING",
    }


def preview(project: Path, operator: str) -> dict[str, Any]:
    if _record(adoption.resolve_worktree(project)) is not None:
        raise ProviderReleaseError("provider planning release already exists; no silent overwrite")
    body = _inputs(project, operator)
    return {**body, "preview_sha256": _digest(body), "requires_explicit_confirmation": True}


def catalogue_probe(project: Path, operator: str, preview_sha: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "PROBE":
        raise ProviderReleaseError("explicit confirmation required: PROBE")
    current = preview(project, operator)
    if current["preview_sha256"] != preview_sha:
        raise ProviderReleaseError("stale or incorrect provider release preview")
    from . import provider_codex
    root = Path(current["worktree"])
    token = _catalog_probe.set(str(root))
    try:
        catalogue = provider_codex.model_catalog(root)
    except provider_codex.ProviderError as exc:
        raise ProviderReleaseError(str(exc)) from exc
    finally:
        _catalog_probe.reset(token)
    if preview(project, operator)["preview_sha256"] != preview_sha:
        raise ProviderReleaseError("release authority changed during catalogue query")
    return {"result": "CATALOGUE_INSPECTED_NO_RELEASE", "catalog": catalogue, "preview_sha256": preview_sha}


def release(project: Path, operator: str, preview_sha: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "RELEASE_PLANNING":
        raise ProviderReleaseError("explicit confirmation required: RELEASE_PLANNING")
    current = preview(project, operator)
    if preview_sha != current["preview_sha256"]:
        raise ProviderReleaseError("stale or incorrect provider release preview")
    root = Path(current["worktree"])
    from . import provider_codex
    token = _catalog_probe.set(str(root))
    try:
        catalogue = provider_codex.model_catalog(root)
        selection = provider_codex.selection_from_catalog(catalogue, current["model"], current["effort"])
    except provider_codex.ProviderError as exc:
        raise ProviderReleaseError(str(exc)) from exc
    finally:
        _catalog_probe.reset(token)
    # Refuse changed authority while the metadata subprocess was running.
    if preview(project, operator)["preview_sha256"] != preview_sha:
        raise ProviderReleaseError("release authority changed during catalogue query")
    body = {
        "schema": SCHEMA,
        "preview_sha256": preview_sha,
        "authority": {key: value for key, value in current.items() if key not in {"preview_sha256", "requires_explicit_confirmation"}},
        "model_selection": selection,
        "scope": "PLANNING_ONLY",
        "provider_write_turn": False,
    }
    body["record_sha256"] = _digest(body)
    adoption.write_runtime_record(root, RECORD, body, actor="controller")
    return {"result": "PLANNING_RELEASE_RECORDED", "transaction_id": current["transaction_id"], "scope": "PLANNING_ONLY", "record_sha256": body["record_sha256"]}


def planning_ready(project: Path) -> bool:
    """Used for controller readiness; never treats an invalid record as authority."""
    try:
        root = adoption.resolve_worktree(project)
        saved = _record(root)
        if saved is None or saved.get("scope") != "PLANNING_ONLY" or saved.get("provider_write_turn") is not False:
            return False
        auth = saved["authority"]
        current = _inputs(root, auth["operator"])
        selection = saved.get("model_selection") or {}
        return (
            current == auth
            and saved.get("preview_sha256") == _digest(current)
            and selection.get("provider") == "codex"
            and selection.get("selected_model") == current["model"]
            and selection.get("selected_effort") == current["effort"]
            and isinstance(selection.get("catalog_sha256"), str)
            and len(selection["catalog_sha256"]) == 64
        )
    except (ProviderReleaseError, OSError, KeyError, TypeError, ValueError):
        return False


@contextmanager
def approved_proposal_turn(project: Path, preview_sha: str):
    """Permit a proposal turn only inside verified planning.py confirmation."""
    root = adoption.resolve_worktree(project)
    # A planning test may replace the provider, but the real subprocess gate
    # still requires planning_ready() and this confirmation context.
    if not isinstance(preview_sha, str) or len(preview_sha) != 64:
        raise ProviderReleaseError("exact proposal preview required")
    token = _proposal_turn.set(str(root))
    try:
        yield
    finally:
        _proposal_turn.reset(token)


def dispatch_allowed(cwd: Path, purpose: str) -> bool:
    """02N gate called at the three actual provider subprocess boundaries."""
    try:
        candidate = Path(cwd).resolve()
        # Cheap local guard before any Git executable can be reached. This
        # also protects the original 02N inert-subprocess-canary tests.
        if purpose == "catalogue" and _catalog_probe.get() == str(candidate):
            return True
        # A completed successor transfer owns its own tightly-scoped write
        # context.  Do this before checking predecessor planning readiness:
        # that readiness intentionally binds predecessor installed bytes.
        from . import provider_write_release
        if provider_write_release.dispatch_allowed(candidate, purpose):
            return True
        if not (candidate / adoption.RUNTIME_NAME / RECORD).is_file():
            return False
        root = adoption.resolve_worktree(candidate)
        if root != candidate:
            return False
        if not planning_ready(root):
            return False
        if purpose in {"catalogue", "quota", "sandbox"}:
            return True
        if purpose == "read-only-turn":
            return _proposal_turn.get() == str(root)
        if purpose == "write-turn":
            # 02N itself never grants a write turn.
            return False
        return False  # Always deny write turns and unknown dispatch types.
    except (ProviderReleaseError, OSError, ValueError):
        return False


def cli_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stygnox provider-release")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("preview", "catalogue", "release", "status"):
        item = sub.add_parser(action)
        item.add_argument("--project", type=Path, required=True)
        item.add_argument("--operator", required=True)
        if action in {"release", "catalogue"}:
            item.add_argument("--preview", required=True)
            item.add_argument("--confirm", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.action == "preview":
            result = preview(args.project, args.operator)
        elif args.action == "release":
            result = release(args.project, args.operator, args.preview, args.confirm)
        elif args.action == "catalogue":
            result = catalogue_probe(args.project, args.operator, args.preview, args.confirm)
        else:
            root = adoption.resolve_worktree(args.project)
            result = {"transaction_operator": args.operator, "planning_ready": planning_ready(root), "release": _record(root)}
    except (ProviderReleaseError, adoption.AdoptionError, transactions.TransactionError, execution_policy.ExecutionPolicyError) as exc:
        parser.exit(2, f"stygnox: provider release refused: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0
