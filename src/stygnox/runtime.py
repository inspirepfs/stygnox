"""R3D.2's versioned, read-only canonical runtime contract.

This module is deliberately a seam, not a runtime controller.  It performs no
runtime discovery, writes no records, acquires no operating-system lock, and
does not turn an authority-shaped record or a passive snapshot into authority.
Callers must supply the project root, epoch, and installed-controller identity
they expect; absence or disagreement is refused rather than inferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from types import MappingProxyType
import re
import stat
from typing import Any, ClassVar, Mapping, TypeAlias


RUNTIME_IDENTITY_SCHEMA = "stygnox_runtime_identity_v1"
RUNTIME_IDENTITY_RECORD = "runtime-identity.json"
INSTALLED_CONTROLLER_SCHEMA = "stygnox_installed_controller_identity_v1"
ENVELOPE_SCHEMA = "stygnox_runtime_envelope_v1"
CONTRACT_VERSION = 1

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_EPOCH = re.compile(r"[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}\Z")
JsonValue: TypeAlias = None | bool | int | str | list["JsonValue"] | dict[str, "JsonValue"]


class RuntimeContractError(ValueError):
    """A contract input is absent, ambiguous, substituted, or malformed."""


class RuntimeRecordMissing(RuntimeContractError):
    """A caller-requested optional runtime record does not exist."""


_MAX_RUNTIME_JSON_BYTES = 64 * 1024 * 1024


def _reject_json_constant(value: str) -> None:
    _refuse(f"runtime JSON contains non-finite constant: {value}")


def _unique_json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _refuse(f"runtime JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _refuse(message: str) -> None:
    raise RuntimeContractError(message)


def _json_value(value: Any) -> JsonValue:
    """Copy the small, unambiguous JSON subset used by the hashed contract."""
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            _refuse("canonical JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    _refuse("canonical JSON permits only null, booleans, integers, strings, arrays, and objects")


def canonical_json(value: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes, rejecting ambiguous Python values."""
    return json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256(value: Any) -> str:
    """Return the canonical SHA-256 digest for a supported JSON value."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _immutable_json(value: JsonValue) -> Any:
    """Defensively freeze nested JSON objects and arrays after verification."""
    if isinstance(value, dict):
        return MappingProxyType({key: _immutable_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_immutable_json(item) for item in value)
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        _refuse(f"{label} must be a lowercase 64-character SHA-256 digest")
    return value


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        _refuse(f"{label} is missing or unsafe")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        _refuse(f"{label} must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RuntimeContractError(f"{label} must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None:
        _refuse(f"{label} must be an RFC 3339 UTC timestamp")
    return value


def _absolute_without_symlink(path: Path, label: str, *, directory: bool) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        parts = candidate.parts
        current = Path(parts[0])
        for part in parts[1:]:
            current /= part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                _refuse(f"{label} must not traverse a symlink")
        final = candidate.lstat()
    except OSError as exc:
        raise RuntimeContractError(f"{label} is unavailable") from exc
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(final.st_mode):
        _refuse(f"{label} must be a {'directory' if directory else 'regular file'}")
    return candidate


@dataclass(frozen=True, slots=True)
class CanonicalProjectRoot:
    """A pre-existing, absolute project root with no symlink component."""

    path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            _refuse("project root must be a canonical Path")
        canonical = _absolute_without_symlink(self.path, "project root", directory=True)
        if self.path != canonical:
            _refuse("project root must be an absolute normalized path")

    @classmethod
    def from_path(cls, candidate: str | os.PathLike[str]) -> "CanonicalProjectRoot":
        return cls(_absolute_without_symlink(Path(candidate), "project root", directory=True))

    def as_posix(self) -> str:
        return self.path.as_posix()


@dataclass(frozen=True, slots=True)
class SafeRelativePath:
    """A normalized project-relative POSIX path; it never names a root or parent."""

    value: PurePosixPath

    def __post_init__(self) -> None:
        if not isinstance(self.value, PurePosixPath):
            _refuse("runtime relative path must be a POSIX path")
        candidate = self.value.as_posix()
        if candidate in ("", ".") or self.value.is_absolute() or ".." in self.value.parts:
            _refuse("runtime path is not normalized and project-relative")
        if "\\" in candidate or "\x00" in candidate:
            _refuse("runtime path is not a safe POSIX path")

    @classmethod
    def parse(cls, candidate: str) -> "SafeRelativePath":
        if not isinstance(candidate, str) or not candidate or "\x00" in candidate or "\\" in candidate:
            _refuse("runtime path must be a non-empty POSIX relative path")
        path = PurePosixPath(candidate)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts) or path.as_posix() != candidate:
            _refuse("runtime path is not normalized and project-relative")
        return cls(path)

    def within(self, root: CanonicalProjectRoot, *, require_regular_file: bool = True) -> Path:
        """Resolve a safe existing member without following any symlink."""
        if not isinstance(root, CanonicalProjectRoot):
            _refuse("runtime path requires a canonical project root")
        _absolute_without_symlink(root.path, "project root", directory=True)
        candidate = root.path.joinpath(*self.value.parts)
        try:
            current = root.path
            for part in self.value.parts:
                current /= part
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode):
                    _refuse("runtime path must not traverse a symlink")
            if require_regular_file and not stat.S_ISREG(candidate.lstat().st_mode):
                _refuse("runtime path must name a regular file")
        except OSError as exc:
            raise RuntimeContractError("runtime path is unavailable") from exc
        return candidate


def read_json_object(
    root: CanonicalProjectRoot,
    relative: SafeRelativePath,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    """Read one project-local JSON object without following substituted paths.

    This is a read-only seam: it neither discovers a project root nor infers
    authority from a record.  Callers retain ownership of record schemas and
    authority decisions after this function has established the exact root and
    regular-file path from which their bytes were read.
    """
    if not isinstance(root, CanonicalProjectRoot) or not isinstance(relative, SafeRelativePath):
        _refuse("runtime JSON read requires canonical root and safe relative path")
    _absolute_without_symlink(root.path, "project root", directory=True)
    # O_NONBLOCK prevents a substituted FIFO from hanging a controller read
    # before fstat can reject the non-regular descriptor.
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(root.path, flags | os.O_DIRECTORY)
        for index, part in enumerate(relative.value.parts):
            parent = descriptor
            descriptor = os.open(
                part,
                flags | (os.O_DIRECTORY if index < len(relative.value.parts) - 1 else 0),
                dir_fd=parent,
            )
            os.close(parent)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _refuse("runtime JSON path must name a regular file")
        if info.st_size > _MAX_RUNTIME_JSON_BYTES:
            _refuse("runtime JSON record exceeds size limit")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            raw = stream.read(_MAX_RUNTIME_JSON_BYTES + 1)
        if len(raw) > _MAX_RUNTIME_JSON_BYTES:
            _refuse("runtime JSON record exceeds size limit")
    except FileNotFoundError as exc:
        if not required:
            return None
        raise RuntimeRecordMissing("runtime JSON record is missing") from exc
    except OSError as exc:
        raise RuntimeContractError("runtime JSON path is unavailable or substituted") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeContractError("runtime JSON record is malformed") from exc
    if not isinstance(value, dict):
        _refuse("runtime JSON record must be an object")
    return value


def established_runtime_identity(root: CanonicalProjectRoot) -> "RuntimeIdentity | None":
    """Return the persisted runtime identity when this project has one.

    Early adoption records intentionally predate this contract.  Their absence
    is therefore a valid bootstrap state, but once an identity is published it
    becomes an exact root/epoch binding for every authority-bearing record
    read through :func:`read_authority_json`.
    """
    record = read_json_object(
        root, SafeRelativePath.parse(f".stygnox/{RUNTIME_IDENTITY_RECORD}"), required=False,
    )
    if record is None:
        return None
    identity = RuntimeIdentity.from_mapping(record)
    if identity.root != root:
        _refuse("persisted runtime identity does not match the canonical project root")
    return identity


def read_authority_json(
    root: CanonicalProjectRoot,
    relative: SafeRelativePath,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    """Read an authority-bearing record through the canonical runtime seam.

    The filesystem and JSON protections of :func:`read_json_object` are
    applied first.  A project without a persisted runtime identity remains a
    valid bootstrap state.  After identity publication, records must carry
    its exact epoch; an omitted or substituted epoch is refused rather than
    being inferred.  Domain modules retain ownership of their schemas,
    integrity digests, approval rules, and controller/transaction/plan
    lineage checks.
    """
    value = read_json_object(root, relative, required=required)
    if value is None:
        return None
    identity = established_runtime_identity(root)
    if identity is None:
        # Legacy bootstrap records lack an epoch.  An epoch-bearing record is
        # not a bootstrap record: loss of the identity anchor must not turn a
        # previously rejected stale record into accepted legacy authority.
        if "runtime_epoch" in value:
            _refuse("authority record declares a runtime epoch but runtime identity is missing")
    elif value.get("runtime_epoch") != identity.epoch:
        _refuse("authority record runtime epoch is missing, stale, or substituted")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    """The sole binding for a project root and its opaque runtime epoch."""

    root: CanonicalProjectRoot
    epoch: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, CanonicalProjectRoot):
            _refuse("runtime identity requires a canonical project root")
        if not isinstance(self.epoch, str) or not _EPOCH.fullmatch(self.epoch):
            _refuse("runtime epoch must be 32 lowercase hexadecimal characters")

    @classmethod
    def create(cls, root: CanonicalProjectRoot, epoch: str) -> "RuntimeIdentity":
        if not isinstance(root, CanonicalProjectRoot):
            _refuse("runtime identity requires a canonical project root")
        if not isinstance(epoch, str) or not _EPOCH.fullmatch(epoch):
            _refuse("runtime epoch must be 32 lowercase hexadecimal characters")
        return cls(root=root, epoch=epoch)

    def to_mapping(self) -> dict[str, JsonValue]:
        return {"schema": RUNTIME_IDENTITY_SCHEMA, "project_root": self.root.as_posix(), "runtime_epoch": self.epoch}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RuntimeIdentity":
        if set(data) != {"schema", "project_root", "runtime_epoch"} or data.get("schema") != RUNTIME_IDENTITY_SCHEMA:
            _refuse("unsupported runtime identity schema")
        return cls.create(CanonicalProjectRoot.from_path(data["project_root"]), data["runtime_epoch"])


@dataclass(frozen=True, slots=True)
class InstalledControllerIdentity:
    """Exact regular-file controller bytes; this is identity, not authority."""

    executable: Path
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path):
            _refuse("installed controller must be a canonical file path")
        canonical = _absolute_without_symlink(self.executable, "installed controller", directory=False)
        if canonical != self.executable:
            _refuse("installed controller must have an absolute normalized path")
        _digest(self.sha256, "installed controller digest")

    @classmethod
    def capture(cls, executable: str | os.PathLike[str]) -> "InstalledControllerIdentity":
        path = _absolute_without_symlink(Path(executable), "installed controller", directory=False)
        return cls(executable=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def to_mapping(self) -> dict[str, JsonValue]:
        return {"schema": INSTALLED_CONTROLLER_SCHEMA, "executable": self.executable.as_posix(), "sha256": self.sha256}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "InstalledControllerIdentity":
        if set(data) != {"schema", "executable", "sha256"} or data.get("schema") != INSTALLED_CONTROLLER_SCHEMA:
            _refuse("unsupported installed-controller identity schema")
        path = _absolute_without_symlink(Path(data["executable"]), "installed controller", directory=False)
        return cls(executable=path, sha256=_digest(data["sha256"], "installed controller digest"))

    def verify_current_bytes(self) -> None:
        current = type(self).capture(self.executable)
        if current != self:
            _refuse("installed controller bytes changed or were substituted")


class RecordKind(str, Enum):
    """Distinct record roles.  Only an AuthorityRecord describes authority."""

    AUTHORITY = "authority"
    EVIDENCE = "evidence"
    CHECKPOINT = "checkpoint"
    LOCK = "lock"
    LEASE = "lease"
    PASSIVE_SNAPSHOT = "passive_snapshot"


class RuntimeRecord:
    kind: ClassVar[RecordKind]

    def payload(self) -> dict[str, JsonValue]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AuthorityRecord(RuntimeRecord):
    """An authority claim.  Its presence never grants execution by itself."""

    authority_id: str
    state: str
    kind: ClassVar[RecordKind] = RecordKind.AUTHORITY

    def payload(self) -> dict[str, JsonValue]:
        return {"authority_id": _token(self.authority_id, "authority id"), "state": _token(self.state, "authority state")}


@dataclass(frozen=True, slots=True)
class EvidenceRecord(RuntimeRecord):
    """Append-oriented evidence metadata; payload content is supplied, never inferred."""

    source: str
    event_id: str
    sequence: int
    observed_at: str
    body: Mapping[str, Any]
    kind: ClassVar[RecordKind] = RecordKind.EVIDENCE

    def payload(self) -> dict[str, JsonValue]:
        if type(self.sequence) is not int or self.sequence < 0:
            _refuse("evidence sequence must be a non-negative integer")
        return {"source": _token(self.source, "evidence source"), "event_id": _token(self.event_id, "evidence event id"),
                "sequence": self.sequence, "observed_at": _timestamp(self.observed_at, "evidence timestamp"),
                "body": _json_value(self.body)}


@dataclass(frozen=True, slots=True)
class CheckpointRecord(RuntimeRecord):
    checkpoint_id: str
    evidence_sha256: str
    kind: ClassVar[RecordKind] = RecordKind.CHECKPOINT

    def payload(self) -> dict[str, JsonValue]:
        return {"checkpoint_id": _token(self.checkpoint_id, "checkpoint id"),
                "evidence_sha256": _digest(self.evidence_sha256, "checkpoint evidence digest")}


@dataclass(frozen=True, slots=True)
class LockRecord(RuntimeRecord):
    lock_id: str
    holder: str
    kind: ClassVar[RecordKind] = RecordKind.LOCK

    def payload(self) -> dict[str, JsonValue]:
        return {"lock_id": _token(self.lock_id, "lock id"), "holder": _token(self.holder, "lock holder")}


@dataclass(frozen=True, slots=True)
class LeaseRecord(RuntimeRecord):
    lease_id: str
    holder: str
    expires_at: str
    kind: ClassVar[RecordKind] = RecordKind.LEASE

    def payload(self) -> dict[str, JsonValue]:
        return {"lease_id": _token(self.lease_id, "lease id"), "holder": _token(self.holder, "lease holder"),
                "expires_at": _timestamp(self.expires_at, "lease expiry")}


@dataclass(frozen=True, slots=True)
class PassiveSnapshot(RuntimeRecord):
    """Caller-provided read-only observation; it is neither telemetry nor authority."""

    captured_at: str
    observations: Mapping[str, Any]
    kind: ClassVar[RecordKind] = RecordKind.PASSIVE_SNAPSHOT

    def payload(self) -> dict[str, JsonValue]:
        return {"captured_at": _timestamp(self.captured_at, "snapshot timestamp"),
                "observations": _json_value(self.observations), "passive": True}


@dataclass(frozen=True, slots=True)
class IntegrityEnvelope:
    """An integrity-bound, versioned wrapper around one typed runtime record."""

    kind: RecordKind
    runtime: RuntimeIdentity
    controller: InstalledControllerIdentity
    payload: Mapping[str, JsonValue]
    payload_sha256: str
    envelope_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RecordKind):
            _refuse("runtime envelope requires a record kind")
        if not isinstance(self.runtime, RuntimeIdentity) or not isinstance(self.controller, InstalledControllerIdentity):
            _refuse("runtime envelope requires validated identities")
        payload = _json_value(self.payload)
        if not isinstance(payload, dict):
            _refuse("runtime envelope payload must be an object")
        _validate_payload(self.kind, payload)
        digest = _digest(self.payload_sha256, "payload digest")
        if sha256(payload) != digest:
            _refuse("runtime envelope payload digest is invalid")
        body = {"schema": ENVELOPE_SCHEMA, "version": CONTRACT_VERSION, "kind": self.kind.value,
                "runtime": self.runtime.to_mapping(), "controller": self.controller.to_mapping(),
                "payload": payload, "payload_sha256": digest}
        if sha256(body) != _digest(self.envelope_sha256, "envelope digest"):
            _refuse("runtime envelope digest is invalid")
        object.__setattr__(self, "payload", _immutable_json(payload))

    def _body(self) -> dict[str, JsonValue]:
        return {"schema": ENVELOPE_SCHEMA, "version": CONTRACT_VERSION, "kind": self.kind.value,
                "runtime": self.runtime.to_mapping(), "controller": self.controller.to_mapping(),
                "payload": _json_value(self.payload), "payload_sha256": self.payload_sha256}

    def to_mapping(self) -> dict[str, JsonValue]:
        return {**self._body(), "envelope_sha256": self.envelope_sha256}


def _validate_payload(kind: RecordKind, payload: Mapping[str, JsonValue]) -> None:
    """Reject a resealed but semantically malformed typed payload."""
    common = {"record_kind"}
    if payload.get("record_kind") != kind.value:
        _refuse("runtime envelope record kind does not match its typed payload")
    if kind is RecordKind.AUTHORITY:
        if set(payload) != common | {"authority_id", "state"}:
            _refuse("authority payload schema is invalid")
        AuthorityRecord(payload["authority_id"], payload["state"]).payload()
    elif kind is RecordKind.EVIDENCE:
        if set(payload) != common | {"source", "event_id", "sequence", "observed_at", "body"}:
            _refuse("evidence payload schema is invalid")
        if not isinstance(payload["body"], Mapping):
            _refuse("evidence body must be an object")
        EvidenceRecord(payload["source"], payload["event_id"], payload["sequence"], payload["observed_at"], payload["body"]).payload()
    elif kind is RecordKind.CHECKPOINT:
        if set(payload) != common | {"checkpoint_id", "evidence_sha256"}:
            _refuse("checkpoint payload schema is invalid")
        CheckpointRecord(payload["checkpoint_id"], payload["evidence_sha256"]).payload()
    elif kind is RecordKind.LOCK:
        if set(payload) != common | {"lock_id", "holder"}:
            _refuse("lock payload schema is invalid")
        LockRecord(payload["lock_id"], payload["holder"]).payload()
    elif kind is RecordKind.LEASE:
        if set(payload) != common | {"lease_id", "holder", "expires_at"}:
            _refuse("lease payload schema is invalid")
        LeaseRecord(payload["lease_id"], payload["holder"], payload["expires_at"]).payload()
    elif kind is RecordKind.PASSIVE_SNAPSHOT:
        if set(payload) != common | {"captured_at", "observations", "passive"} or payload.get("passive") is not True:
            _refuse("passive snapshot payload schema is invalid")
        if not isinstance(payload["observations"], Mapping):
            _refuse("passive snapshot observations must be an object")
        PassiveSnapshot(payload["captured_at"], payload["observations"]).payload()
    else:  # pragma: no cover - enum exhaustiveness is still a fail-closed guard.
        _refuse("unsupported runtime record kind")


def seal(record: RuntimeRecord, *, runtime: RuntimeIdentity, controller: InstalledControllerIdentity) -> IntegrityEnvelope:
    """Create an in-memory envelope.  Persistence and authority decisions are out of scope."""
    if not isinstance(record, RuntimeRecord):
        _refuse("envelope requires a typed runtime record")
    if not isinstance(runtime, RuntimeIdentity) or not isinstance(controller, InstalledControllerIdentity):
        _refuse("envelope requires runtime and installed-controller identities")
    _absolute_without_symlink(runtime.root.path, "project root", directory=True)
    controller.verify_current_bytes()
    payload = record.payload()
    payload["record_kind"] = record.kind.value
    _validate_payload(record.kind, payload)
    payload_digest = sha256(payload)
    body: dict[str, JsonValue] = {"schema": ENVELOPE_SCHEMA, "version": CONTRACT_VERSION, "kind": record.kind.value,
                                   "runtime": runtime.to_mapping(), "controller": controller.to_mapping(),
                                   "payload": payload, "payload_sha256": payload_digest}
    return IntegrityEnvelope(record.kind, runtime, controller, payload, payload_digest, sha256(body))


def parse_envelope(data: Mapping[str, Any]) -> IntegrityEnvelope:
    """Parse only the exact v1 shape, rejecting unknown fields and bad digests."""
    fields = {"schema", "version", "kind", "runtime", "controller", "payload", "payload_sha256", "envelope_sha256"}
    if not isinstance(data, Mapping) or set(data) != fields or data.get("schema") != ENVELOPE_SCHEMA or type(data.get("version")) is not int or data.get("version") != CONTRACT_VERSION:
        _refuse("unsupported runtime envelope schema")
    try:
        kind = RecordKind(data["kind"])
    except (TypeError, ValueError) as exc:
        raise RuntimeContractError("unsupported runtime envelope record kind") from exc
    if not isinstance(data["runtime"], Mapping) or not isinstance(data["controller"], Mapping) or not isinstance(data["payload"], Mapping):
        _refuse("runtime envelope has malformed nested records")
    runtime = RuntimeIdentity.from_mapping(data["runtime"])
    controller = InstalledControllerIdentity.from_mapping(data["controller"])
    payload = _json_value(data["payload"])
    if not isinstance(payload, dict):
        _refuse("runtime envelope payload must be an object")
    _validate_payload(kind, payload)
    payload_digest = _digest(data["payload_sha256"], "payload digest")
    if sha256(payload) != payload_digest:
        _refuse("runtime envelope payload digest is invalid")
    envelope_digest = _digest(data["envelope_sha256"], "envelope digest")
    body = {"schema": ENVELOPE_SCHEMA, "version": CONTRACT_VERSION, "kind": kind.value,
            "runtime": runtime.to_mapping(), "controller": controller.to_mapping(),
            "payload": payload, "payload_sha256": payload_digest}
    if sha256(body) != envelope_digest:
        _refuse("runtime envelope digest is invalid")
    return IntegrityEnvelope(kind, runtime, controller, payload, payload_digest, envelope_digest)


def verify_envelope(data: Mapping[str, Any], *, expected_runtime: RuntimeIdentity,
                    expected_controller: InstalledControllerIdentity) -> IntegrityEnvelope:
    """Verify bytes and exact root/epoch/controller bindings; never infer replacements."""
    if not isinstance(expected_runtime, RuntimeIdentity) or not isinstance(expected_controller, InstalledControllerIdentity):
        _refuse("verification requires explicit expected runtime and controller identities")
    envelope = parse_envelope(data)
    if envelope.runtime != expected_runtime:
        _refuse("runtime envelope root or epoch does not match the expected runtime")
    if envelope.controller != expected_controller:
        _refuse("runtime envelope installed controller identity was substituted")
    expected_controller.verify_current_bytes()
    return envelope
