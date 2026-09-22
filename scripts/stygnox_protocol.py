"""Standalone, passive data contracts for Stygnox Protocol version 1.

This module deliberately describes data and interfaces only.  It does not
select providers, verify evidence, execute work, or grant authority.
"""

from dataclasses import asdict, dataclass, fields, is_dataclass
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Protocol, TypeAlias, runtime_checkable


STYGNOX_PROTOCOL_FAMILY = "stygnox"
STYGNOX_PROTOCOL_MAJOR_VERSION = 1

CanonicalValue: TypeAlias = (
    None | bool | int | float | str | tuple["CanonicalValue", ...] | Mapping[str, "CanonicalValue"]
)


def _freeze_value(value: Any) -> CanonicalValue:
    """Return a recursively immutable JSON-compatible value, or reject it."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("canonical JSON does not permit non-finite floats")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, CanonicalValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mapping keys must be strings")
            frozen[key] = _freeze_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    raise TypeError(f"value is not canonical JSON data: {type(value).__name__}")


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, CanonicalValue]:
    frozen = _freeze_value(value)
    assert isinstance(frozen, Mapping)
    return frozen


def _text_tuple(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result = tuple(values)
    if not all(isinstance(value, str) for value in result):
        raise TypeError("scope and check values must be strings")
    return result


def canonical_data(value: Any) -> CanonicalValue:
    """Project a contract or JSON-compatible value into canonical data."""
    if isinstance(value, _Contract):
        return {field.name: canonical_data(getattr(value, field.name)) for field in fields(value)}
    if is_dataclass(value):
        return canonical_data(asdict(value))
    if isinstance(value, Mapping):
        return {key: canonical_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(canonical_data(item) for item in value)
    return _freeze_value(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize supported data deterministically as UTF-8 JSON bytes."""
    return json.dumps(
        canonical_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_fingerprint(value: Any) -> str:
    """Return the SHA-256 fingerprint of canonical JSON bytes."""
    return sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class _Contract:
    """Shared marker for passive, canonicalizable protocol data."""

    @property
    def protocol_family(self) -> str:
        return STYGNOX_PROTOCOL_FAMILY

    @property
    def protocol_major_version(self) -> int:
        return STYGNOX_PROTOCOL_MAJOR_VERSION

    def canonical_data(self) -> CanonicalValue:
        return canonical_data(self)

    def canonical_json_bytes(self) -> bytes:
        return canonical_json_bytes(self)

    def fingerprint(self) -> str:
        return sha256_fingerprint(self)


@dataclass(frozen=True)
class EffectIntent(_Contract):
    effect_id: str
    kind: str
    declared_scope: tuple[str, ...] = ()
    parameters: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "declared_scope", _text_tuple(self.declared_scope))
        object.__setattr__(self, "parameters", _frozen_mapping(self.parameters))


@dataclass(frozen=True)
class Capability(_Contract):
    name: str
    declared_scope: tuple[str, ...] = ()
    constraints: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "declared_scope", _text_tuple(self.declared_scope))
        object.__setattr__(self, "constraints", _frozen_mapping(self.constraints))


@dataclass(frozen=True)
class AgentWorkOrder(_Contract):
    work_order_id: str
    task_id: str
    declared_scope: tuple[str, ...] = ()
    inputs: Mapping[str, CanonicalValue] = MappingProxyType({})
    effect_intents: tuple[EffectIntent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "declared_scope", _text_tuple(self.declared_scope))
        object.__setattr__(self, "inputs", _frozen_mapping(self.inputs))
        object.__setattr__(self, "effect_intents", tuple(self.effect_intents))
        if not all(isinstance(intent, EffectIntent) for intent in self.effect_intents):
            raise TypeError("effect_intents must contain EffectIntent values")


# WorkOrder is retained as the protocol's concise compatibility name.
WorkOrder = AgentWorkOrder


@dataclass(frozen=True)
class StateFingerprint(_Contract):
    scope: tuple[str, ...]
    digest: str
    algorithm: str = "sha256"

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _text_tuple(self.scope))

    @classmethod
    def from_state(cls, state: Mapping[str, Any], scope: tuple[str, ...] = ()) -> "StateFingerprint":
        """Fingerprint supplied state data; no state is read or verified here."""
        return cls(scope=scope, digest=sha256_fingerprint(state))


@dataclass(frozen=True)
class KnowledgeRef(_Contract):
    reference: str
    label: str = ""
    metadata: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))


@dataclass(frozen=True)
class EvidenceBundle(_Contract):
    evidence_id: str
    references: tuple[KnowledgeRef, ...] = ()
    annotations: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "annotations", _frozen_mapping(self.annotations))
        if not all(isinstance(reference, KnowledgeRef) for reference in self.references):
            raise TypeError("references must contain KnowledgeRef values")


@dataclass(frozen=True)
class SemanticResult(_Contract):
    result_id: str
    status: str
    output: Mapping[str, CanonicalValue] = MappingProxyType({})
    claimed_checks: tuple[str, ...] = ()
    evidence: tuple[EvidenceBundle, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output", _frozen_mapping(self.output))
        object.__setattr__(self, "claimed_checks", _text_tuple(self.claimed_checks))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if not all(isinstance(bundle, EvidenceBundle) for bundle in self.evidence):
            raise TypeError("evidence must contain EvidenceBundle values")


@dataclass(frozen=True)
class ExecutionReceipt(_Contract):
    receipt_id: str
    work_order_id: str
    status: str
    observed_checks: tuple[str, ...] = ()
    observations: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_checks", _text_tuple(self.observed_checks))
        object.__setattr__(self, "observations", _frozen_mapping(self.observations))


@dataclass(frozen=True)
class Task(_Contract):
    task_id: str
    title: str
    declared_scope: tuple[str, ...] = ()
    details: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "declared_scope", _text_tuple(self.declared_scope))
        object.__setattr__(self, "details", _frozen_mapping(self.details))


@dataclass(frozen=True)
class TaskBackend(_Contract):
    backend_id: str
    backend_kind: str
    declared_scope: tuple[str, ...] = ()
    configuration: Mapping[str, CanonicalValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "declared_scope", _text_tuple(self.declared_scope))
        object.__setattr__(self, "configuration", _frozen_mapping(self.configuration))


@runtime_checkable
class AgentAdapter(Protocol):
    """Interface only; implementations decide whether and how to perform work."""

    def execute(self, work_order: AgentWorkOrder) -> SemanticResult:
        ...


@runtime_checkable
class Evaluator(Protocol):
    """Interface only; this protocol makes no evidence-verification claim."""

    def evaluate(self, result: SemanticResult, receipt: ExecutionReceipt) -> tuple[str, ...]:
        ...


# These are local copies so protocol users need not import a controller module.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "steps": {
            "type": "array", "minItems": 1, "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "objective": {"type": "string"},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                    "test_change_policy": {"type": "string", "enum": ["none", "add-only", "modify"]},
                },
                "required": ["id", "title", "objective", "acceptance", "test_change_policy"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["goal", "steps"],
    "additionalProperties": False,
}

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "ideas": {"type": "array", "items": {"type": "string"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "needs_human": {"type": "boolean"},
        "blocker_class": {"type": "string", "enum": ["none", "validation-only", "continuation", "human-decision", "policy"]},
        "validation_notes": {"type": "array", "items": {"type": "string"}},
        "context": {
            "type": "object",
            "properties": {
                "relevant_files": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "accepted_findings": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "files_inspected": {"type": "array", "maxItems": 16, "items": {"type": "string"}},
            },
            "required": ["relevant_files", "accepted_findings", "files_inspected"],
            "additionalProperties": False,
        },
    },
    "required": ["summary", "ideas", "blockers", "needs_human", "blocker_class", "validation_notes", "context"],
    "additionalProperties": False,
}


_V1_CONTRACTS = MappingProxyType({
    "AgentWorkOrder": AgentWorkOrder,
    "WorkOrder": WorkOrder,
    "StateFingerprint": StateFingerprint,
    "SemanticResult": SemanticResult,
    "ExecutionReceipt": ExecutionReceipt,
    "EffectIntent": EffectIntent,
    "Capability": Capability,
    "Task": Task,
    "TaskBackend": TaskBackend,
    "EvidenceBundle": EvidenceBundle,
    "KnowledgeRef": KnowledgeRef,
    "PLAN_SCHEMA": PLAN_SCHEMA,
    "RESULT_SCHEMA": RESULT_SCHEMA,
})
PROTOCOL_REGISTRY = MappingProxyType({
    (STYGNOX_PROTOCOL_FAMILY, STYGNOX_PROTOCOL_MAJOR_VERSION): _V1_CONTRACTS,
})


def resolve_contract(name: str, major_version: int = STYGNOX_PROTOCOL_MAJOR_VERSION) -> Any:
    """Resolve exactly a registered v1 contract; unknown versions and names fail closed."""
    if not isinstance(name, str):
        raise TypeError("contract name must be a string")
    contracts = PROTOCOL_REGISTRY.get((STYGNOX_PROTOCOL_FAMILY, major_version))
    if contracts is None:
        raise ValueError(f"unsupported Stygnox protocol major version: {major_version!r}")
    try:
        return contracts[name]
    except KeyError as error:
        raise LookupError(f"unknown Stygnox v{major_version} contract: {name}") from error


__all__ = [
    "AgentAdapter", "AgentWorkOrder", "Capability", "CanonicalValue", "EffectIntent",
    "Evaluator", "EvidenceBundle", "ExecutionReceipt", "KnowledgeRef", "PLAN_SCHEMA",
    "PROTOCOL_REGISTRY", "RESULT_SCHEMA", "STYGNOX_PROTOCOL_FAMILY",
    "STYGNOX_PROTOCOL_MAJOR_VERSION", "SemanticResult", "StateFingerprint", "Task",
    "TaskBackend", "WorkOrder", "canonical_data", "canonical_json_bytes", "resolve_contract",
    "sha256_fingerprint",
]
