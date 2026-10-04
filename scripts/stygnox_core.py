"""Pure, standalone policy primitives for Stygnox controller integrations.

This module deliberately has no runtime, provider, repository, or persistence
dependency.  Callers supply all policy inputs and apply its returned values.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

PLAN_MIN_STEPS_DEFAULT = 5
PLAN_MAX_STEPS_DEFAULT = 10
PLAN_MAX_STEPS_LIMIT = 20
REPOSITORY_AUTHORITY_FIELD = "repository_authority"
REPOSITORY_AUTHORITIES = frozenset({"read-only", "write"})
REPOSITORY_MUTATION_SCOPE_FIELD = "repository_mutation_scope"
REPOSITORY_MUTATION_SCOPE_MAX_PATHS = 64
APPROVED_PLAN_V1 = "v1"
APPROVED_PLAN_V2 = "v2"
APPROVED_PLAN_V3 = "v3"
APPROVED_PLAN_V2_SCHEMA = "zen_ralph_plan_v2"
APPROVED_PLAN_V3_SCHEMA = "zen_ralph_plan_v3"
OUTCOME_RESULT_CONTRACT_FIELD = "outcome_result_contract"
OUTCOME_RESULT_CONTRACT_NAME = "OUTCOME_RESULT_SCHEMA"
OUTCOME_RESULT_BINDING_SCHEMA = "zen_ralph_outcome_result_contract_binding_v1"
# This protocol literal is intentionally duplicated here: core is a pure
# standard-library policy boundary and must not import protocol modules.
OUTCOME_COMPLETED = "completed"


@dataclass(frozen=True)
class ProjectPathPolicy:
    """Immutable, caller-provided path policy; paths are repository-relative."""

    protected_prefixes: tuple[str, ...] = ()
    protected_exact: frozenset[str] = frozenset()
    protected_dir_prefixes: tuple[str, ...] = ()
    protected_suffixes: tuple[str, ...] = ()
    tooling_paths: frozenset[str] = frozenset()
    tooling_prefixes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "protected_prefixes", _normalized_prefixes(self.protected_prefixes))
        object.__setattr__(self, "protected_exact", frozenset(normalize_repo_path(value) for value in self.protected_exact))
        object.__setattr__(self, "protected_dir_prefixes", _normalized_prefixes(self.protected_dir_prefixes))
        object.__setattr__(self, "protected_suffixes", tuple(str(value) for value in self.protected_suffixes))
        object.__setattr__(self, "tooling_paths", frozenset(normalize_repo_path(value) for value in self.tooling_paths))
        object.__setattr__(self, "tooling_prefixes", tuple(normalize_repo_path(value) for value in self.tooling_prefixes))


def _normalized_prefixes(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(normalize_repo_path(value).rstrip("/") + "/" for value in values)


def normalize_repo_path(value: object) -> str:
    """Lexically normalize one relative POSIX-like repository path.

    This neither reads the filesystem nor resolves symlinks.  Escaping the
    repository and absolute paths are rejected instead of being silently folded.
    """
    path = str(value or "").strip().replace("\\", "/")
    if "\x00" in path or path.startswith("/") or re.match(r"^[A-Za-z]:/", path):
        raise ValueError("path must be a relative repository path")
    parts: list[str] = []
    for part in path.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            if not parts:
                raise ValueError("path must not escape the repository")
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def canonical_data(value: Any) -> Any:
    """Return JSON data after rejecting non-canonical mapping keys and floats."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("canonical JSON does not permit non-finite floats")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mapping keys must be strings")
            result[key] = canonical_data(item)
        return result
    if isinstance(value, (list, tuple)):
        return [canonical_data(item) for item in value]
    raise TypeError(f"value is not canonical JSON data: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(canonical_data(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_fingerprint(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def canonical_plan(plan: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(plan)


def plan_hash(plan: Mapping[str, Any]) -> str:
    return sha256_fingerprint(plan)


def proposal_step_bounds(min_steps: object = None, max_steps: object = None) -> tuple[int, int]:
    minimum = PLAN_MIN_STEPS_DEFAULT if min_steps is None else int(min_steps)
    maximum = PLAN_MAX_STEPS_DEFAULT if max_steps is None else int(max_steps)
    if minimum < 1:
        raise ValueError("minimum plan steps must be at least 1")
    if maximum < minimum:
        raise ValueError("maximum plan steps must be greater than or equal to minimum plan steps")
    if maximum > PLAN_MAX_STEPS_LIMIT:
        raise ValueError(f"maximum plan steps must not exceed {PLAN_MAX_STEPS_LIMIT}")
    return minimum, maximum


def plan_step_bounds(plan: Mapping[str, Any]) -> tuple[int, int]:
    planning = plan.get("planning")
    return proposal_step_bounds(*(planning.get(key) for key in ("min_steps", "max_steps"))) if isinstance(planning, Mapping) else proposal_step_bounds()


def validate_plan(plan: object) -> None:
    if not isinstance(plan, Mapping):
        raise ValueError("plan must be an object")
    goal, steps = plan.get("goal"), plan.get("steps")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("plan goal must be a non-empty string")
    minimum, maximum = plan_step_bounds(plan)
    if not isinstance(steps, list) or not minimum <= len(steps) <= maximum:
        raise ValueError(f"plan must contain {minimum}-{maximum} steps")
    for index, step in enumerate(steps, 1):
        if not isinstance(step, Mapping) or step.get("id") != index:
            raise ValueError("plan step ids must be sequential starting at 1")
        for key in ("title", "objective"):
            if not isinstance(step.get(key), str) or not step[key].strip():
                raise ValueError(f"step {index} {key} must be non-empty")
        acceptance = step.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance or not all(isinstance(item, str) and item.strip() for item in acceptance):
            raise ValueError(f"step {index} acceptance must contain at least one item")
        if step.get("test_change_policy") not in {"none", "add-only", "modify"}:
            raise ValueError(f"step {index} has invalid test_change_policy")


def controller_inject_repository_authority(proposal: object, authority: object) -> dict[str, Any]:
    """Return a derived authority-bound plan without mutating the proposal."""
    if not isinstance(proposal, Mapping):
        raise ValueError("model proposal must be an object")
    if REPOSITORY_AUTHORITY_FIELD in proposal:
        raise ValueError("model proposal must not supply repository authority")
    if authority not in REPOSITORY_AUTHORITIES:
        raise ValueError("proposal requires repository authority: read-only or write")
    return {**proposal, REPOSITORY_AUTHORITY_FIELD: authority}


def controller_inject_outcome_result_contract(proposal: object) -> dict[str, Any]:
    """Derive the v3 outcome-contract commitment without accepting model input."""
    if not isinstance(proposal, Mapping):
        raise ValueError("model proposal must be an object")
    if OUTCOME_RESULT_CONTRACT_FIELD in proposal:
        raise ValueError("model proposal must not supply an outcome result contract")
    if proposal.get("schema") != APPROVED_PLAN_V2_SCHEMA:
        raise ValueError("model proposal must use the v2 proposal schema")
    return {
        **proposal,
        "schema": APPROVED_PLAN_V3_SCHEMA,
        OUTCOME_RESULT_CONTRACT_FIELD: OUTCOME_RESULT_CONTRACT_NAME,
    }


def normalize_repository_mutation_scope(scope: object) -> tuple[str, ...]:
    """Return one finite, canonical representation of exact repository paths."""
    if not isinstance(scope, list):
        raise ValueError("repository mutation scope must be an array")
    if len(scope) > REPOSITORY_MUTATION_SCOPE_MAX_PATHS:
        raise ValueError(f"repository mutation scope must contain at most {REPOSITORY_MUTATION_SCOPE_MAX_PATHS} paths")
    normalized: list[str] = []
    for raw_path in scope:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("repository mutation scope paths must be non-empty strings")
        if any(token in raw_path for token in ("*", "?", "[", "]", "{", "}")):
            raise ValueError("repository mutation scope paths must be exact, not glob patterns")
        path = normalize_repo_path(raw_path)
        if not path:
            raise ValueError("repository mutation scope paths must not name the repository root")
        normalized.append(path)
    if len(set(normalized)) != len(normalized):
        raise ValueError("repository mutation scope paths must be unique")
    return tuple(sorted(normalized))


def validate_v2_repository_mutation_scope(plan: Mapping[str, Any]) -> tuple[str, ...]:
    """Fail closed unless a v2 authority candidate carries its canonical scope."""
    if REPOSITORY_MUTATION_SCOPE_FIELD not in plan:
        raise ValueError("v2 plan is missing repository mutation scope")
    scope = normalize_repository_mutation_scope(plan[REPOSITORY_MUTATION_SCOPE_FIELD])
    if plan[REPOSITORY_MUTATION_SCOPE_FIELD] != list(scope):
        raise ValueError("v2 repository mutation scope must use its normalized representation")
    authority = plan.get(REPOSITORY_AUTHORITY_FIELD)
    if authority == "write" and not scope:
        raise ValueError("v2 write plan requires a non-empty repository mutation scope")
    if authority == "read-only" and scope:
        raise ValueError("v2 read-only plan requires an explicit empty repository mutation scope")
    return scope


def plan_requires_repository_mutation_scope(plan: object) -> bool:
    """Return whether this approved execution contract binds an exact path scope."""
    return approved_plan_version(plan) in {APPROVED_PLAN_V2, APPROVED_PLAN_V3}


def validate_complete_plan(plan: object, expected_hash: str | None = None) -> None:
    validate_plan(plan)
    assert isinstance(plan, Mapping)
    if plan.get(REPOSITORY_AUTHORITY_FIELD) not in REPOSITORY_AUTHORITIES:
        raise ValueError("plan is missing controller-injected repository authority")
    version = approved_plan_version(plan)
    if plan_requires_repository_mutation_scope(plan):
        validate_v2_repository_mutation_scope(plan)
    if version == APPROVED_PLAN_V3 and plan.get(OUTCOME_RESULT_CONTRACT_FIELD) != OUTCOME_RESULT_CONTRACT_NAME:
        raise ValueError("v3 plan has an unsupported outcome result contract")
    if expected_hash is not None and (not str(expected_hash).strip() or plan_hash(plan) != str(expected_hash).strip()):
        raise ValueError("approved plan hash does not match controller state")


def approved_plan_version(plan: object) -> str:
    """Return the explicit execution contract for an approved plan.

    Plans created before plan schemas were named are deliberately v1.  This is
    the only compatibility discriminator: callers must not infer a new
    contract from optional fields added by a future version.
    """
    if not isinstance(plan, Mapping):
        raise ValueError("plan must be an object")
    schema = plan.get("schema")
    if schema is None or schema == "zen_ralph_plan_v1":
        return APPROVED_PLAN_V1
    if schema == APPROVED_PLAN_V2_SCHEMA:
        return APPROVED_PLAN_V2
    if schema == APPROVED_PLAN_V3_SCHEMA:
        return APPROVED_PLAN_V3
    raise ValueError("approved plan has an unsupported schema")


def dispatch_approved_plan(plan: object, expected_hash: str | None = None) -> str:
    """Validate one approved plan through its explicit version contract.

    Proposal and approval admission apply the complete v2 mutation-scope
    contract.  This evidence-first execution seam retains the common approved
    contract for already artifact-verified bootstrap-era v2 records, whose
    schema name predates that v2-only field.
    """
    version = approved_plan_version(plan)
    if version == APPROVED_PLAN_V1:
        validate_complete_plan(plan, expected_hash)
    elif version == APPROVED_PLAN_V2:
        validate_plan(plan)
        assert isinstance(plan, Mapping)
        if plan.get(REPOSITORY_AUTHORITY_FIELD) not in REPOSITORY_AUTHORITIES:
            raise ValueError("plan is missing controller-injected repository authority")
        if expected_hash is not None and (not str(expected_hash).strip() or plan_hash(plan) != str(expected_hash).strip()):
            raise ValueError("approved plan hash does not match controller state")
    elif version == APPROVED_PLAN_V3:
        validate_complete_plan(plan, expected_hash)
    else:  # Defensive guard for future discriminator extensions.
        raise ValueError("approved plan has an unsupported execution contract")
    return version


def sandbox_for_dispatched_approved_plan(plan: object, version: str) -> str:
    """Select the sandbox after ``dispatch_approved_plan`` has validated it."""
    if version not in {APPROVED_PLAN_V1, APPROVED_PLAN_V2, APPROVED_PLAN_V3}:
        raise ValueError("approved plan has an unsupported execution contract")
    assert isinstance(plan, Mapping)
    return "read-only" if plan[REPOSITORY_AUTHORITY_FIELD] == "read-only" else "workspace-write"


def sandbox_for_approved_plan(plan: object, expected_hash: str | None = None) -> str:
    return sandbox_for_dispatched_approved_plan(plan, dispatch_approved_plan(plan, expected_hash))


def _active_step_authority(plan: Mapping[str, Any], current_step: object) -> dict[str, Any]:
    if isinstance(current_step, bool) or not isinstance(current_step, int):
        raise ValueError("active step authority is invalid")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not 1 <= current_step <= len(steps):
        raise ValueError("active step authority is invalid")
    step = steps[current_step - 1]
    if not isinstance(step, Mapping) or step.get("id") != current_step:
        raise ValueError("active step authority does not match the approved plan")
    return {"id": current_step, "sha256": sha256_fingerprint(step)}


def outcome_result_contract_bindings(
    plan: object, expected_hash: str, approved_plan_artifact: object, recovery_checkpoint: object,
    dispatch_version: str, contract_digest: object,
) -> list[dict[str, Any]]:
    """Create immutable per-step outcome-contract witnesses for a v3 approval."""
    if dispatch_version != APPROVED_PLAN_V3 or dispatch_approved_plan(plan, expected_hash) != dispatch_version:
        raise ValueError("outcome result contracts require a verified v3 dispatch")
    if not isinstance(plan, Mapping) or plan.get(OUTCOME_RESULT_CONTRACT_FIELD) != OUTCOME_RESULT_CONTRACT_NAME:
        raise ValueError("approved plan does not select the required outcome result contract")
    if not isinstance(approved_plan_artifact, Mapping) or approved_plan_artifact.get("plan_hash") != expected_hash:
        raise ValueError("outcome result contract artifact does not match the approved plan")
    checkpoint = str(recovery_checkpoint or "")
    digest = str(contract_digest or "")
    if not checkpoint or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("outcome result contract evidence is malformed")
    bindings: list[dict[str, Any]] = []
    for step_number in range(1, len(plan["steps"]) + 1):
        payload = {
            "schema": OUTCOME_RESULT_BINDING_SCHEMA,
            "plan_hash": expected_hash,
            "approved_plan_artifact_sha256": sha256_fingerprint(approved_plan_artifact),
            "recovery_checkpoint": checkpoint,
            "dispatch_version": dispatch_version,
            "active_step": _active_step_authority(plan, step_number),
            "contract_name": OUTCOME_RESULT_CONTRACT_NAME,
            "contract_sha256": digest,
        }
        bindings.append({**payload, "binding_sha256": sha256_fingerprint(payload)})
    return bindings


def select_outcome_result_contract(
    plan: object, expected_hash: str, approved_plan_artifact: object, recovery_checkpoint: object,
    dispatch_version: str, current_step: object, bindings: object, contract_digest: object,
) -> str | None:
    """Verify and select the only result contract usable by this dispatch."""
    if dispatch_approved_plan(plan, expected_hash) != dispatch_version:
        raise ValueError("result contract dispatch version is stale or invalid")
    if dispatch_version in {APPROVED_PLAN_V1, APPROVED_PLAN_V2}:
        if bindings is not None:
            raise ValueError("legacy dispatch has substituted outcome result-contract evidence")
        return None
    if dispatch_version != APPROVED_PLAN_V3 or not isinstance(plan, Mapping):
        raise ValueError("result contract dispatch version is unsupported")
    if not isinstance(bindings, list) or len(bindings) != len(plan.get("steps") or []):
        raise ValueError("outcome result-contract evidence is missing or stale")
    expected = outcome_result_contract_bindings(
        plan, expected_hash, approved_plan_artifact, recovery_checkpoint, dispatch_version, contract_digest,
    )
    if bindings != expected:
        raise ValueError("outcome result-contract evidence is substituted, stale, or digest-mismatched")
    active = _active_step_authority(plan, current_step)
    record = bindings[active["id"] - 1]
    if record["active_step"] != active:
        raise ValueError("outcome result-contract active step authority is stale")
    return OUTCOME_RESULT_CONTRACT_NAME


def result_reports_explicit_completed_outcome(result: object, selected_contract: object) -> bool:
    """Accept completion only from the immutable selected outcome contract.

    Summaries, blockers, and successful controller gates can explain a result,
    but cannot manufacture its completion evidence. A legacy/no-contract
    dispatch is therefore never PASS-eligible.
    """
    return (
        selected_contract == OUTCOME_RESULT_CONTRACT_NAME
        and isinstance(result, Mapping)
        and result.get("outcome") == OUTCOME_COMPLETED
        and result.get("blocker_class") in {"none", "validation-only"}
        and result.get("needs_human") is False
        and (result.get("blocker_class") == "validation-only" or not result.get("blockers"))
    )


def is_protected_path(path: object, policy: ProjectPathPolicy) -> bool:
    normalized = normalize_repo_path(path)
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized == ".env" or normalized.startswith(".env.")
        or normalized in policy.protected_exact
        or normalized.startswith(policy.protected_prefixes)
        or normalized.startswith(policy.protected_dir_prefixes)
        or name.endswith(policy.protected_suffixes)
    )


def is_tooling_path(path: object, policy: ProjectPathPolicy) -> bool:
    normalized = normalize_repo_path(path)
    return normalized in policy.tooling_paths or normalized.startswith(policy.tooling_prefixes)


def classify_changes(paths: Iterable[object], policy: ProjectPathPolicy) -> str:
    normalized = [normalize_repo_path(path) for path in paths]
    if not normalized:
        return "no-change"
    if any(is_protected_path(path, policy) for path in normalized):
        return "protected"
    tooling = any(is_tooling_path(path, policy) for path in normalized)
    product = any(not is_tooling_path(path, policy) for path in normalized)
    if tooling and product:
        return "mixed"
    return "tooling" if tooling else "product"


def test_policy_violations(changed_paths: Iterable[object], policy: str, baseline_path_kinds: Mapping[str, str], allowed_new_test_paths: Iterable[object] = ()) -> list[str]:
    """Return changed test paths outside the supplied approval-time authority."""
    if policy not in {"none", "add-only", "modify"}:
        raise ValueError("invalid test change policy")
    changed = sorted({normalize_repo_path(path) for path in changed_paths if normalize_repo_path(path) == "tests" or normalize_repo_path(path).startswith("tests/")})
    if policy == "modify":
        return []
    allowed = {normalize_repo_path(path) for path in allowed_new_test_paths}
    violations: list[str] = []
    for path in changed:
        if path in allowed:
            continue
        if policy == "add-only" and baseline_path_kinds.get(path) == "absent":
            continue
        violations.append(path)
    return violations


def declared_human_block(result: Mapping[str, Any]) -> str:
    match = re.match(r"^BLOCKED_HUMAN\s*:\s*(.*)$", str(result.get("summary") or "").strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip() or "Approved step requires human-owned evidence before it can advance"


def approved_step_delegates_human_gate(step: object) -> bool:
    if not isinstance(step, Mapping):
        return False
    acceptance = step.get("acceptance")
    text = " ".join((str(step.get("objective") or ""), *(str(item) for item in acceptance if isinstance(item, str)))) if isinstance(acceptance, list) else str(step.get("objective") or "")
    lowered = text.lower()
    return "blocked_human" in lowered and any(marker in lowered for marker in ("operator", "runtime", "evidence", "human-owned", "human owned"))


def agent_requires_human_before_qualification(result: Mapping[str, Any], approved_step: object = None) -> tuple[bool, str]:
    """Honor only an approved step's explicit BLOCKED_HUMAN delegation."""
    declared = declared_human_block(result)
    if declared and approved_step_delegates_human_gate(approved_step):
        return True, declared
    return False, ""


def agent_requests_continuation(result: Mapping[str, Any], approved_step: object = None) -> tuple[bool, str]:
    if agent_requires_human_before_qualification(result, approved_step)[0]:
        return False, ""
    blockers = [str(item).strip() for item in result.get("blockers", ()) if str(item).strip()]
    summary = str(result.get("summary") or "").strip()
    if str(result.get("blocker_class") or "none") == "continuation":
        return True, "; ".join(blockers) or summary or "approved step requires another bounded implementation turn"
    return False, ""


def agent_disposition(result: Mapping[str, Any], approved_step: object = None) -> str:
    if agent_requires_human_before_qualification(result, approved_step)[0]:
        return "human-review"
    if agent_requests_continuation(result, approved_step)[0]:
        return "continuation"
    return "qualification"


def normalize_failure(text: object) -> str:
    useful = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if re.search(r"^(FAIL|ERROR):|AssertionError|Traceback|FAILED|ERRORS?\b", stripped):
            useful.append(stripped)
    if not useful:
        useful = [line.strip() for line in str(text or "").splitlines() if line.strip()][-20:]
    normalized = "\n".join(useful)
    normalized = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", normalized)
    normalized = re.sub(r"/tmp/[^\s:]+", "/tmp/TMP", normalized)
    return re.sub(r"\b\d+\.\d+s\b", "TIME", normalized)[:8000]


def failure_fingerprint(gate: object, output: object, returncode: object) -> str:
    return sha256(f"{gate}\n{returncode}\n{normalize_failure(output)}".encode("utf-8")).hexdigest()[:20]
