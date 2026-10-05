"""Neutral installed Stygnox controller authority for D8.5.

Controller activation is a separate human gate after adoption and transaction
binding.  Provider execution is impossible with neutral defaults and is bound
to an exact, reviewer-approved tracked execution policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping, Sequence

from . import adoption, efficiency, execution_policy, transactions
from . import provider_usage
from .product import PRODUCT
from .profile import DEFAULT_PROFILE, profile_record
from . import provider_codex, usage


CONTROLLER_SCHEMA = "stygnox_controller_state_v1"
RUN_PREVIEW_SCHEMA = "stygnox_controller_run_preview_v1"
RUN_RESULT_SCHEMA = "stygnox_controller_run_result_v1"
PENDING_PROVENANCE_PREVIEW_SCHEMA = "stygnox_pending_provenance_preview_v1"
PENDING_PROVENANCE_WITNESS_SCHEMA = "stygnox_pending_provenance_witness_v1"
CONTROLLER_RECORD = "controller.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ControllerError(RuntimeError):
    """Fail-closed neutral-controller error."""


class ControllerUsageBlocked(ControllerError):
    """Zero-model provider admission refused the turn without interrupting authority."""


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


def _actual_delta(before: Mapping[str, str], after: Mapping[str, str]) -> dict[str, Any]:
    """Return immutable evidence for every repository file changed by one turn."""
    paths: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        previous, current = before.get(path), after.get(path)
        if previous != current:
            paths.append({"path": path, "kind": "created" if previous is None else "deleted" if current is None else "modified", "before_fingerprint": previous, "after_fingerprint": current})
    evidence: dict[str, Any] = {"before_manifest_sha256": _digest(dict(before)), "after_manifest_sha256": _digest(dict(after)), "paths": paths}
    evidence["delta_sha256"] = _digest(evidence)
    return evidence


def _snapshot_manifest(root: Path, manifest: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """Capture reversible pre-turn content for the repository manifest only."""
    snapshot: dict[str, dict[str, Any]] = {}
    for path in manifest:
        target = root / path
        try:
            mode = target.lstat().st_mode
        except FileNotFoundError:
            # ``git ls-files`` retains tracked paths that an earlier approved
            # turn deliberately removed.  Their pre-turn state is absence;
            # leaving them out makes a later unauthorised recreation removable
            # by _restore_manifest_snapshot without inventing file content.
            continue
        try:
            if stat.S_ISLNK(mode):
                snapshot[path] = {"kind": "symlink", "target": os.readlink(target)}
            elif stat.S_ISREG(mode):
                snapshot[path] = {"kind": "file", "content": target.read_bytes(), "mode": stat.S_IMODE(mode)}
            else:
                raise ControllerError(f"repository manifest contains unsupported path type: {path}")
        except OSError as exc:
            raise ControllerError(f"cannot snapshot repository path {path}: {exc}") from exc
    return snapshot


def _restore_manifest_snapshot(root: Path, snapshot: Mapping[str, Mapping[str, Any]], changed_paths: Sequence[str]) -> list[str]:
    """Restore every changed manifest path, including unauthorised creations/deletions."""
    restored: list[str] = []
    for path in sorted(set(changed_paths)):
        target = root / path
        original = snapshot.get(path)
        try:
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                raise ControllerError(f"cannot restore unauthorised non-file path: {path}")
            if original is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                if original.get("kind") == "symlink":
                    target.symlink_to(str(original["target"]))
                else:
                    target.write_bytes(bytes(original["content"]))
                    target.chmod(int(original["mode"]))
            restored.append(path)
        except OSError as exc:
            raise ControllerError(f"cannot restore unauthorised repository path {path}: {exc}") from exc
    return restored


def build_run_preview(
    project: Path,
    operator: str,
    objective: str,
    repository_authority: str,
    *,
    _scheduler_authority: str | None = None,
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
    from . import scheduler
    scheduler_authority = scheduler.active_scheduler_authority(root)
    if scheduler_authority is not None and _scheduler_authority != scheduler_authority.get("schedule_preview_sha256"):
        raise ControllerError("active scheduler owns controller execution; direct turn bypass is refused")
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
    current = adoption.capture_baseline(root).public()
    objective_value = _objective(objective)
    plan_binding = None
    try:
        from . import planning
        plan_context = planning.approved_step_context(root, name)
    except planning.PlanningError as exc:
        raise ControllerError(str(exc)) from exc
    if plan_context is not None:
        step = plan_context["step"]
        if objective_value != step["objective"]:
            raise ControllerError("--objective must exactly match the current approved plan step objective")
        if authority != plan_context["repository_authority"]:
            raise ControllerError("--repository-authority must exactly match the approved plan authority")
        plan_binding = {
            "schema": "stygnox_controller_plan_binding_v1",
            "plan_hash": plan_context["plan_hash"],
            "plan_record_sha256": plan_context["plan_record_sha256"],
            "current_step": plan_context["current_step"],
            "total_steps": plan_context["total_steps"],
            "step_id": step["id"],
            "step_title": step["title"],
            "step_objective": step["objective"],
            "acceptance": list(step["acceptance"]),
            "test_change_policy": step["test_change_policy"],
            "repository_mutation_scope": list(plan_context["repository_mutation_scope"]),
            "repository_mutation_scope_sha256": plan_context["repository_mutation_scope_sha256"],
            "approval_baseline_sha256": plan_context["approval_baseline_sha256"],
            "step_authority_baseline_sha256": plan_context["step_authority_baseline_sha256"],
            "human_direction": plan_context.get("human_direction"),
            "resume_reason": plan_context.get("resume_reason"),
            "allowed_new_tests": list(plan_context.get("allowed_new_tests") or []),
            "resumed_from_gate": plan_context.get("resumed_from_gate"),
            "self_development_grant": dict(plan_context.get("self_development_grant")) if isinstance(plan_context.get("self_development_grant"), Mapping) else None,
        }
        if plan_binding["self_development_grant"] is not None:
            from . import self_development
            state = planning._record(root)
            assert state is not None
            try:
                grant = self_development.active_grant_for_context(
                    root,
                    state,
                    plan_hash=str(plan_binding["plan_hash"]),
                    step=int(plan_binding["current_step"]),
                    baseline_sha256=str(plan_binding["step_authority_baseline_sha256"]),
                )
            except self_development.SelfDevelopmentError as exc:
                raise ControllerError(str(exc)) from exc
            plan_binding["self_development_grant"] = grant
    body: dict[str, Any] = {
        "schema": RUN_PREVIEW_SCHEMA,
        "product_version": PRODUCT.version,
        "operator": name,
        "worktree": str(root),
        "profile": profile_record(),
        "transaction_id": tx["transaction_id"],
        "controller_record_sha256": controller["record_sha256"],
        "project_baseline": current,
        "objective": objective_value,
        "repository_authority": authority,
        "plan_binding": plan_binding,
        "provider": provider,
        "model": model,
        "effort": policy.get("effort"),
        "execution_controls": {
            key: policy[key]
            for key in (
                "efficiency_mode", "reserve_percent", "wait_for_limits", "usage_poll_seconds", "max_loops",
                *efficiency.DETAIL_FIELDS,
            )
        },
        "tracked_config_sha256": policy_status["tracked_config_sha256"],
        "review_sha256": (policy_status.get("review") or {}).get("review_sha256"),
        "scheduler_authority": _scheduler_authority,
        "requires_explicit_confirmation": True,
        "confirmation": "RUN",
    }
    body["preview_sha256"] = _digest(body)
    return body


def _prompt(preview: Mapping[str, Any]) -> str:
    authority = preview["repository_authority"]
    controls = preview.get("execution_controls") if isinstance(preview.get("execution_controls"), Mapping) else {}
    budget = efficiency.mode_limits(controls).get("prompt_commands", 6)
    binding = preview.get("plan_binding") if isinstance(preview.get("plan_binding"), Mapping) else None
    plan_text = ""
    if binding is not None:
        acceptance = "\n".join(f"- {item}" for item in binding.get("acceptance", []))
        steering = ""
        if binding.get("human_direction"):
            steering += f"Bounded human direction for this retry: {binding['human_direction']}\n"
        if binding.get("resume_reason"):
            steering += f"Human resume context: {binding['resume_reason']}\n"
        allowed_tests = list(binding.get("allowed_new_tests") or [])
        if allowed_tests:
            steering += "Exact human-authorised new test paths: " + ", ".join(allowed_tests) + "\n"
        self_grant = binding.get("self_development_grant") if isinstance(binding.get("self_development_grant"), Mapping) else None
        if self_grant is not None:
            steering += "Exact supervised Stygnox self-development paths for this retry only: " + ", ".join(self_grant.get("paths") or []) + "\n"
        plan_text = (
            f"This turn is bound to approved plan {binding['plan_hash']}, "
            f"step {binding['current_step']} of {binding['total_steps']} ({binding['step_title']}). "
            f"The step test-change policy is {binding['test_change_policy']}. "
            "Its immutable repository mutation scope is "
            f"{', '.join(binding['repository_mutation_scope']) or '[]'} "
            f"(digest {binding['repository_mutation_scope_sha256']}). "
            "Do not perform work outside this exact approved step.\n"
            f"{steering}"
            f"Acceptance criteria:\n{acceptance}\n\n"
        )
    return (
        "You are an implementation worker invoked by the installed Stygnox controller. "
        "The controller, not you, owns authority and runtime evidence. "
        "Never create, edit, delete, rename, or adopt content under .stygnox/. "
        f"Repository authority for this single reviewed turn is {authority}. "
        f"Use at most {budget} shell command executions for this reviewed turn. "
        "Report every repository file you inspected in files_inspected. "
        "Do not access secrets, credentials, or external production systems. "
        "When safe work remains inside this exact approved step but cannot fit this turn, return status PASS with blocker_class continuation; "
        "ordinary continuation is controller scheduling and must not be presented as human authority. "
        "Use blocker_class human-decision or policy only for genuine authority boundaries. "
        "Return only the requested structured result.\n\n"
        f"{plan_text}"
        f"Objective:\n{preview['objective']}\n"
    )


def run_controller(
    project: Path,
    operator: str,
    objective: str,
    repository_authority: str,
    preview_sha256: str,
    confirmation: str,
    *,
    _scheduler_authority: str | None = None,
) -> dict[str, Any]:
    if confirmation != "RUN":
        raise ControllerError("explicit confirmation required: --confirm RUN")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise ControllerError("--preview must be the exact 64-character preview SHA-256")
    preview = build_run_preview(
        project, operator, objective, repository_authority, _scheduler_authority=_scheduler_authority
    )
    if preview["preview_sha256"] != expected:
        raise ControllerError("controller run preview is stale; authority, policy, objective, or project baseline changed")
    root = Path(preview["worktree"])
    plan_binding = preview.get("plan_binding") if isinstance(preview.get("plan_binding"), Mapping) else None
    controls = preview.get("execution_controls") if isinstance(preview.get("execution_controls"), Mapping) else {}
    plan_state = None
    if plan_binding is not None:
        from . import planning as planning_module
        plan_state = planning_module._record(root)
    try:
        provider_usage.ensure_capacity(
            root,
            plan_state=plan_state,
            model=str(preview["model"]),
            reserve_percent=float(controls.get("reserve_percent", 5.0)),
            wait=bool(controls.get("wait_for_limits", True)),
            poll_seconds=int(controls.get("usage_poll_seconds", 60)),
        )
    except provider_usage.ProviderUsageError as exc:
        raise ControllerUsageBlocked(str(exc)) from exc
    before = adoption.capture_baseline(root).public()
    before_paths: set[str] = set()
    before_manifest: dict[str, str] = {}
    before_snapshot: dict[str, dict[str, Any]] = {}
    self_snapshot: dict[str, dict[str, Any]] = {}
    active_self_grant = plan_binding.get("self_development_grant") if isinstance(plan_binding, Mapping) and isinstance(plan_binding.get("self_development_grant"), Mapping) else None
    if preview["repository_authority"] == "write":
        from . import scheduler, self_development
        before_manifest = scheduler.repository_manifest(root)
        before_snapshot = _snapshot_manifest(root, before_manifest)
        self_snapshot = self_development.authority_snapshot(root)
        if plan_binding is not None:
            from . import human_control
            before_paths = human_control.repository_paths(root)
    else:
        # The provider adapter is separately configured as read-only, but the
        # controller remains the enforcement point.  Preserve enough evidence
        # to undo a compromised or faulty adapter before refusing the turn.
        from . import scheduler
        before_manifest = scheduler.repository_manifest(root)
        before_snapshot = _snapshot_manifest(root, before_manifest)
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
    attempted_after = adoption.capture_baseline(root).public()
    if preview["repository_authority"] == "read-only":
        from . import scheduler
        attempted_manifest = scheduler.repository_manifest(root)
        read_only_delta = _actual_delta(before_manifest, attempted_manifest)
        changed_paths = [str(item["path"]) for item in read_only_delta["paths"]]
        if changed_paths:
            restored = _restore_manifest_snapshot(root, before_snapshot, changed_paths)
            if scheduler.repository_manifest(root) != before_manifest:
                raise ControllerError("read-only provider mutation could not be restored exactly")
            raise ControllerError(f"read-only provider turn changed repository paths; restored paths: {restored}")

    self_development_evidence: dict[str, Any] | None = None
    self_development_candidates: list[dict[str, Any]] = []
    after = attempted_after
    actual_delta: dict[str, Any] = {"before_manifest_sha256": None, "after_manifest_sha256": None, "paths": [], "delta_sha256": _digest([])}
    if preview["repository_authority"] == "write":
        from . import scheduler, self_development
        attempted_manifest = scheduler.repository_manifest(root)
        actual_delta = _actual_delta(before_manifest, attempted_manifest)
        changed_paths = [str(item["path"]) for item in actual_delta["paths"]]
        if plan_binding is None:
            restored = _restore_manifest_snapshot(root, before_snapshot, changed_paths)
            if scheduler.repository_manifest(root) != before_manifest:
                raise ControllerError("write turn without approved scope changed the repository and restoration was incomplete")
            raise ControllerError(
                "write execution requires an approved immutable scope; "
                "provider mutation is without an approved plan/gate authority; "
                f"restored paths: {restored}"
            )
        approved_scope = set(plan_binding["repository_mutation_scope"])
        outside_scope = sorted({str(item["path"]) for item in actual_delta["paths"]} - approved_scope)
        if outside_scope:
            restored = _restore_manifest_snapshot(root, before_snapshot, changed_paths)
            if scheduler.repository_manifest(root) != before_manifest:
                raise ControllerError("out-of-scope repository delta could not be restored exactly")
            raise ControllerError(f"write execution exceeded approved repository scope: {outside_scope}; restored paths: {restored}")
        self_development_candidates = self_development.candidate_evidence(root, before_manifest, attempted_manifest)
        if self_development_candidates:
            changed_self = [str(row["path"]) for row in self_development_candidates]
            allowed = False
            grant_reason = "no approved plan-bound self-development authority"
            grant = None
            if plan_binding is not None:
                from . import planning as planning_module
                state = planning_module._record(root)
                assert state is not None
                allowed, grant_reason, grant = self_development.grant_allows_paths(
                    root,
                    state,
                    plan_hash=str(plan_binding["plan_hash"]),
                    step=int(plan_binding["current_step"]),
                    baseline_sha256=str(before["sha256"]),
                    paths=changed_self,
                )
            if not allowed:
                try:
                    restored = self_development.restore_authority_snapshot(root, self_snapshot, changed_self)
                except self_development.SelfDevelopmentError as exc:
                    raise ControllerError(str(exc)) from exc
                after = adoption.capture_baseline(root).public()
                self_development_evidence = {
                    "status": "RESTORED_UNAUTHORIZED",
                    "changed_paths": changed_self,
                    "restored_paths": restored,
                    "grant_reason": grant_reason,
                    "grant_sha256": grant.get("grant_sha256") if isinstance(grant, Mapping) else None,
                    "candidates": self_development_candidates,
                }
                if plan_binding is None:
                    raise ControllerError(
                        "provider attempted Stygnox self-development without an approved plan/gate authority; original contents restored"
                    )
            else:
                self_development_evidence = {
                    "status": "AUTHORIZED",
                    "changed_paths": changed_self,
                    "restored_paths": [],
                    "grant_reason": grant_reason,
                    "grant_sha256": grant.get("grant_sha256") if isinstance(grant, Mapping) else None,
                    "candidates": self_development_candidates,
                }

    from .operator import status_attribution

    attribution = status_attribution(before, after) if preview["repository_authority"] == "write" else {
        "controller_native_paths": [],
        "operator_baseline_paths": [],
        "overlap_unresolved_paths": [],
        "removed_preexisting_paths": [],
    }
    usage_record = usage.record_controller_turn(
        root,
        preview_sha256=expected,
        transaction_id=str(preview["transaction_id"]),
        repository_authority=str(preview["repository_authority"]),
        provider_result=provider_result,
    )
    efficiency_result = efficiency.assess(provider_result, preview["execution_controls"])
    blocker_class = str(provider_result.get("blocker_class") or "none")
    human_gate = None
    if plan_binding is not None:
        from . import human_control
        violations: list[str] = []
        candidates: list[str] = []
        if preview["repository_authority"] == "write":
            violations, candidates = human_control.test_policy_violations(
                attribution,
                str(plan_binding.get("test_change_policy") or "none"),
                before_paths,
                plan_binding.get("allowed_new_tests") or [],
            )
        if self_development_evidence is not None and self_development_evidence.get("status") == "RESTORED_UNAUTHORIZED":
            human_gate = human_control.open_gate(
                root,
                str(preview["operator"]),
                plan_binding=plan_binding,
                origin_preview_sha256=expected,
                blocked_baseline=after,
                kind="self-development-authority",
                reason=f"provider attempted to change Stygnox controller/tooling authority: {self_development_evidence.get('changed_paths')!r}; original contents restored",
                human_resolvable=False,
                self_development_candidates=self_development_candidates,
            )
        elif violations:
            reason = f"policy violation: test paths {violations!r}"
            human_gate = human_control.open_gate(
                root,
                str(preview["operator"]),
                plan_binding=plan_binding,
                origin_preview_sha256=expected,
                blocked_baseline=after,
                kind="test-policy",
                reason=reason,
                human_resolvable=False,
                allowed_new_test_candidates=candidates,
            )
        elif str(provider_result.get("status") or "") == "BLOCKED":
            step_view = {
                "objective": plan_binding.get("step_objective"),
                "acceptance": list(plan_binding.get("acceptance") or []),
            }
            human_gate = human_control.open_gate(
                root,
                str(preview["operator"]),
                plan_binding=plan_binding,
                origin_preview_sha256=expected,
                blocked_baseline=after,
                kind="provider-blocked",
                reason=str(provider_result.get("summary") or "provider blocked"),
                human_resolvable=human_control.provider_block_human_resolvable(step_view, str(provider_result.get("summary") or "")),
            )
    continuation = None
    if (
        plan_binding is not None
        and human_gate is None
        and str(provider_result.get("status") or "") == "PASS"
        and blocker_class == "continuation"
        and not efficiency_result["requires_review_before_automatic_continuation"]
    ):
        try:
            from . import planning as planning_module
            continuation = planning_module.record_same_step_continuation(
                root,
                str(preview["operator"]),
                plan_binding=plan_binding,
                origin_preview_sha256=expected,
                before_baseline_sha256=before["sha256"],
                after_baseline=after,
                summary=str(provider_result.get("summary") or ""),
            )
        except planning_module.PlanningError as exc:
            raise ControllerError(str(exc)) from exc
    self_development_expiration = None
    if active_self_grant is not None:
        from . import self_development
        try:
            self_development_expiration = self_development.expire_active_grant(
                root,
                str(preview["operator"]),
                expected_grant_sha256=str(active_self_grant.get("grant_sha256") or ""),
                reason="single reviewed controller retry completed",
            )
        except self_development.SelfDevelopmentError as exc:
            raise ControllerError(str(exc)) from exc
    result: dict[str, Any] = {
        "schema": RUN_RESULT_SCHEMA,
        "product_version": PRODUCT.version,
        "controller_execution_enabled": True,
        "operator": preview["operator"],
        "transaction_id": preview["transaction_id"],
        "preview_sha256": expected,
        "profile": preview["profile"],
        "repository_authority": preview["repository_authority"],
        "plan_binding": preview.get("plan_binding"),
        "provider_result": provider_result,
        "usage_record_sha256": usage_record["record_sha256"],
        "efficiency": efficiency_result,
        "blocker_class": blocker_class,
        "continuation": continuation,
        "before_baseline_sha256": before["sha256"],
        "after_baseline_sha256": after["sha256"],
        "project_changed": before["sha256"] != after["sha256"],
        "change_attribution": attribution,
        "actual_delta": actual_delta,
        "self_development": self_development_evidence,
        "self_development_expiration": self_development_expiration,
        "human_gate": human_gate,
        "next_action": (
            "human-gate-required" if human_gate is not None
            else "turn-blocked" if str(provider_result.get("status") or "") == "BLOCKED"
            else "efficiency-review-required" if efficiency_result["requires_review_before_automatic_continuation"]
            else "continue-same-step" if continuation is not None
            else "qualification-required" if before["sha256"] != after["sha256"]
            else "turn-complete"
        ),
    }
    result["record_sha256"] = _digest(result)
    adoption.write_runtime_record(root, f"controller-run-{expected[:16]}.json", result, actor="controller")
    return result


def _controller_receipt(root: Path, turn_preview_sha256: str) -> dict[str, Any]:
    """Load one exact controller-produced receipt; scheduler records are never inputs."""
    turn = str(turn_preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(turn):
        raise ControllerError("--turn-preview must be the exact 64-character controller turn preview SHA-256")
    receipt = _runtime_json(root, f"controller-run-{turn[:16]}.json")
    assert receipt is not None
    recorded = str(receipt.get("record_sha256") or "")
    body = dict(receipt)
    body.pop("record_sha256", None)
    if receipt.get("schema") != RUN_RESULT_SCHEMA or receipt.get("preview_sha256") != turn or not _HEX64.fullmatch(recorded) or recorded != _digest(body):
        raise ControllerError("controller receipt is missing, malformed, or has failed its integrity check")
    return receipt


def _pending_provenance_witness(project: Path, operator: str, turn_preview_sha256: str) -> tuple[Path, dict[str, Any]]:
    """Derive one recovery witness from a receipt and live state, never operator paths."""
    root = adoption.resolve_worktree(project)
    name = _operator(operator)
    receipt = _controller_receipt(root, turn_preview_sha256)
    binding = receipt.get("plan_binding")
    if not isinstance(binding, Mapping) or receipt.get("repository_authority") != "write":
        raise ControllerError("pending provenance recovery requires a plan-bound write controller receipt")
    if receipt.get("operator") != name or receipt.get("provider_result", {}).get("status") != "PASS":
        raise ControllerError("pending provenance recovery requires an accepted PASS controller receipt for this operator")
    if receipt.get("human_gate") is not None or receipt.get("next_action") != "qualification-required":
        raise ControllerError("pending provenance recovery refuses controller receipts with a gate, continuation, or non-qualification outcome")

    from . import planning, scheduler, self_development
    try:
        bound_root, active, tx, policy_status, active_operator = planning._active_context(root, name)
    except planning.PlanningError as exc:
        raise ControllerError(str(exc)) from exc
    state = planning._record(bound_root)
    assert state is not None
    if state.get("status") != "APPROVED" or state.get("execution_authority_granted") is not True:
        raise ControllerError("pending provenance recovery requires the same approved executable plan")
    prior = state.get("pending_provenance_witnesses") if isinstance(state.get("pending_provenance_witnesses"), list) else []
    if any(isinstance(item, Mapping) and item.get("controller_receipt_sha256") == receipt.get("record_sha256") for item in prior):
        raise ControllerError("controller receipt has already originated a pending-provenance witness")
    plan = planning._validate_plan(state.get("plan"))
    step = int(state.get("current_step") or 0)
    authority_before = state.get("step_authority_baseline_sha256") or state.get("approval_baseline_sha256")
    required = {
        "plan_hash": state.get("plan_hash"),
        "current_step": step,
        "repository_mutation_scope": plan["repository_mutation_scope"],
        "repository_mutation_scope_sha256": plan["repository_mutation_scope_sha256"],
        "approval_baseline_sha256": state.get("approval_baseline_sha256"),
        "step_authority_baseline_sha256": authority_before,
    }
    if any(binding.get(key) != value for key, value in required.items()):
        raise ControllerError("controller receipt plan, step, scope, or checkpoint evidence is stale")
    if state.get("operator") != active_operator or state.get("transaction_id") != tx.get("transaction_id") or receipt.get("transaction_id") != tx.get("transaction_id"):
        raise ControllerError("controller receipt transaction/operator authority changed")
    if state.get("controller_record_sha256") != active.get("record_sha256") or receipt.get("plan_binding", {}).get("plan_record_sha256") != binding.get("plan_record_sha256"):
        # The receipt binding below is separately constrained by immutable plan/step/checkpoint evidence;
        # this comparison merely rejects an obviously foreign or hand-spliced receipt.
        raise ControllerError("controller receipt authority lineage changed")
    if state.get("tracked_config_sha256") != policy_status.get("tracked_config_sha256") or state.get("review_sha256") != (policy_status.get("review") or {}).get("review_sha256"):
        raise ControllerError("execution policy changed after controller receipt")
    if receipt.get("before_baseline_sha256") != authority_before:
        raise ControllerError("controller receipt does not begin at the current step checkpoint")

    delta = receipt.get("actual_delta")
    if not isinstance(delta, Mapping):
        raise ControllerError("controller receipt lacks exact manifest delta evidence")
    delta_body = {key: delta.get(key) for key in ("before_manifest_sha256", "after_manifest_sha256", "paths")}
    if delta.get("delta_sha256") != _digest(delta_body) or not isinstance(delta.get("paths"), list) or not delta["paths"]:
        raise ControllerError("controller receipt manifest delta evidence is malformed or empty")
    current_manifest = scheduler.repository_manifest(root)
    if _digest(current_manifest) != delta.get("after_manifest_sha256"):
        raise ControllerError("live checkpoint-relative state no longer exactly matches the controller receipt")
    current = adoption.capture_baseline(root).public()
    if current.get("sha256") != receipt.get("after_baseline_sha256"):
        raise ControllerError("live repository baseline no longer matches the controller receipt")
    scope = set(plan["repository_mutation_scope"])
    witnessed_paths: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in delta["paths"]:
        if not isinstance(raw, Mapping):
            raise ControllerError("controller receipt contains malformed path evidence")
        path, kind = raw.get("path"), raw.get("kind")
        before_fingerprint, after_fingerprint = raw.get("before_fingerprint"), raw.get("after_fingerprint")
        if not isinstance(path, str) or path in seen or kind not in {"created", "modified", "deleted"}:
            raise ControllerError("controller receipt contains duplicate or malformed path evidence")
        seen.add(path)
        if path not in scope or self_development.is_runtime_or_protected(path) or self_development.is_secret_path(path):
            raise ControllerError(f"pending provenance recovery refuses unapproved or protected path: {path}")
        expected_kind = "created" if before_fingerprint is None else "deleted" if after_fingerprint is None else "modified"
        if kind != expected_kind or current_manifest.get(path) != after_fingerprint:
            raise ControllerError(f"controller receipt fingerprint evidence is stale or malformed: {path}")
        witnessed_paths.append({"path": path, "kind": kind, "before_fingerprint": before_fingerprint, "after_fingerprint": after_fingerprint})
    if sorted(seen) != sorted(item["path"] for item in delta["paths"]):
        raise ControllerError("controller receipt path evidence is not canonical")

    self_paths = sorted(path for path in seen if self_development.is_self_development_path(root, path))
    grant_lineage: dict[str, Any] | None = None
    if self_paths:
        evidence = receipt.get("self_development")
        grant_sha = evidence.get("grant_sha256") if isinstance(evidence, Mapping) else None
        history = state.get("self_development_grant_history") if isinstance(state.get("self_development_grant_history"), list) else []
        expirations = state.get("self_development_expirations") if isinstance(state.get("self_development_expirations"), list) else []
        grant = next((item for item in history if isinstance(item, Mapping) and item.get("grant_sha256") == grant_sha), None)
        expired = next((item for item in expirations if isinstance(item, Mapping) and item.get("grant_sha256") == grant_sha), None)
        if not isinstance(evidence, Mapping) or evidence.get("status") != "AUTHORIZED" or sorted(evidence.get("changed_paths") or []) != self_paths or not isinstance(grant, Mapping) or not isinstance(expired, Mapping):
            raise ControllerError("pending provenance recovery lacks applicable self-development grant lineage")
        if grant.get("plan_hash") != state.get("plan_hash") or int(grant.get("step") or 0) != step or grant.get("repository_mutation_scope_sha256") != plan["repository_mutation_scope_sha256"]:
            raise ControllerError("self-development grant lineage is stale for the current plan authority")
        grant_lineage = {"grant_sha256": grant_sha, "grant": dict(grant), "expiration": dict(expired)}
    elif receipt.get("self_development") is not None:
        raise ControllerError("controller receipt self-development evidence does not match its pending delta")

    witness: dict[str, Any] = {
        "schema": PENDING_PROVENANCE_WITNESS_SCHEMA,
        "plan_hash": state["plan_hash"], "current_step": step,
        "repository_mutation_scope": list(plan["repository_mutation_scope"]),
        "repository_mutation_scope_sha256": plan["repository_mutation_scope_sha256"],
        "approval_baseline_sha256": state["approval_baseline_sha256"],
        "step_checkpoint_baseline_sha256": authority_before,
        "before_baseline_sha256": receipt["before_baseline_sha256"],
        "after_baseline_sha256": receipt["after_baseline_sha256"],
        "controller_turn_preview_sha256": receipt["preview_sha256"],
        "controller_receipt_sha256": receipt["record_sha256"],
        "paths": witnessed_paths,
        "self_development_grant_lineage": grant_lineage,
    }
    witness["witness_sha256"] = _digest(witness)
    return root, witness


def build_pending_provenance_recovery_preview(project: Path, operator: str, turn_preview_sha256: str) -> dict[str, Any]:
    root, witness = _pending_provenance_witness(project, operator, turn_preview_sha256)
    body: dict[str, Any] = {
        "schema": PENDING_PROVENANCE_PREVIEW_SCHEMA, "product_version": PRODUCT.version,
        "operator": _operator(operator), "worktree": str(root), "witness": witness,
        "requires_explicit_confirmation": True, "confirmation": "RECOVER_PENDING_PROVENANCE",
    }
    body["preview_sha256"] = _digest(body)
    return body


def recover_pending_provenance(project: Path, operator: str, turn_preview_sha256: str, preview_sha256: str, confirmation: str) -> dict[str, Any]:
    if confirmation != "RECOVER_PENDING_PROVENANCE":
        raise ControllerError("explicit confirmation required: --confirm RECOVER_PENDING_PROVENANCE")
    expected = str(preview_sha256 or "").strip().lower()
    if not _HEX64.fullmatch(expected):
        raise ControllerError("--preview must be the exact 64-character recovery preview SHA-256")
    preview = build_pending_provenance_recovery_preview(project, operator, turn_preview_sha256)
    if preview["preview_sha256"] != expected:
        raise ControllerError("pending provenance recovery preview is stale; authority or live evidence changed")
    root = Path(preview["worktree"])
    witness = dict(preview["witness"])
    adoption.write_runtime_record(root, f"pending-provenance-{witness['controller_turn_preview_sha256'][:16]}.json", witness, actor="controller")
    from . import planning
    try:
        recovered = planning.recover_pending_provenance_same_step(root, _operator(operator), witness=witness)
    except planning.PlanningError as exc:
        raise ControllerError(str(exc)) from exc
    return {"schema": "stygnox_pending_provenance_recovery_result_v1", "preview_sha256": expected, "witness": witness, "plan_record_sha256": recovered["plan_record_sha256"], "result": "PENDING_PROVENANCE_RECOVERED"}


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

    pending_preview = sub.add_parser("recover-pending-provenance-preview", help="preview controller-receipt-bound pending provenance recovery")
    project_arg(pending_preview)
    pending_preview.add_argument("--operator", required=True)
    pending_preview.add_argument("--turn-preview", required=True)
    pending = sub.add_parser("recover-pending-provenance", help="apply one exact controller-receipt-bound pending provenance recovery")
    project_arg(pending)
    pending.add_argument("--operator", required=True)
    pending.add_argument("--turn-preview", required=True)
    pending.add_argument("--preview", required=True)
    pending.add_argument("--confirm", required=True)
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
        elif args.action == "recover-pending-provenance-preview":
            result = build_pending_provenance_recovery_preview(args.project, args.operator, args.turn_preview)
        elif args.action == "recover-pending-provenance":
            result = recover_pending_provenance(args.project, args.operator, args.turn_preview, args.preview, args.confirm)
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
