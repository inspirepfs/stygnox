from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import runtime


EPOCH = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def disposable_runtime(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    controller = root / "installed-controller"
    controller.write_bytes(b"controller-v1\n")
    identity = runtime.RuntimeIdentity.create(runtime.CanonicalProjectRoot.from_path(root), EPOCH)
    installed = runtime.InstalledControllerIdentity.capture(controller)
    return root, controller, identity, installed


def evidence(identity: runtime.RuntimeIdentity, controller: runtime.InstalledControllerIdentity):
    return runtime.seal(
        runtime.EvidenceRecord("controller", "event-1", 0, "2026-10-13T20:00:00Z", {"observed": "given"}),
        runtime=identity,
        controller=controller,
    )


def test_canonical_digest_and_integrity_envelope_round_trip(disposable_runtime):
    _, _, identity, controller = disposable_runtime
    envelope = evidence(identity, controller)

    assert runtime.sha256({"b": 2, "a": [1]}) == runtime.sha256({"a": [1], "b": 2})
    assert runtime.verify_envelope(envelope.to_mapping(), expected_runtime=identity, expected_controller=controller) == envelope


def test_safe_path_refuses_a_real_symlink_in_a_disposable_project(disposable_runtime):
    root, _, identity, _ = disposable_runtime
    outside = root.parent / "outside"
    outside.write_text("not runtime data", encoding="utf-8")
    (root / "alias").symlink_to(outside)

    with pytest.raises(runtime.RuntimeContractError, match="symlink"):
        runtime.SafeRelativePath.parse("alias").within(identity.root)


def test_verification_refuses_a_wrong_canonical_root(disposable_runtime, tmp_path: Path):
    _, _, identity, controller = disposable_runtime
    envelope = evidence(identity, controller)
    other = tmp_path / "other-project"
    other.mkdir()
    wrong_root = runtime.RuntimeIdentity.create(runtime.CanonicalProjectRoot.from_path(other), EPOCH)

    with pytest.raises(runtime.RuntimeContractError, match="root or epoch"):
        runtime.verify_envelope(envelope.to_mapping(), expected_runtime=wrong_root, expected_controller=controller)


def test_verification_refuses_invalid_payload_digest(disposable_runtime):
    _, _, identity, controller = disposable_runtime
    encoded = evidence(identity, controller).to_mapping()
    encoded["payload_sha256"] = hashlib.sha256(b"substituted").hexdigest()

    with pytest.raises(runtime.RuntimeContractError, match="payload digest"):
        runtime.verify_envelope(encoded, expected_runtime=identity, expected_controller=controller)


def test_verification_refuses_substituted_controller_bytes(disposable_runtime):
    _, controller_path, identity, controller = disposable_runtime
    envelope = evidence(identity, controller)
    controller_path.write_bytes(b"controller-v2-substituted\n")

    with pytest.raises(runtime.RuntimeContractError, match="controller bytes changed"):
        runtime.verify_envelope(envelope.to_mapping(), expected_runtime=identity, expected_controller=controller)


def test_verification_refuses_a_wrong_epoch_and_snapshots_remain_passive(disposable_runtime):
    _, _, identity, controller = disposable_runtime
    envelope = evidence(identity, controller)
    wrong_epoch = runtime.RuntimeIdentity.create(identity.root, "fedcba9876543210fedcba9876543210")

    with pytest.raises(runtime.RuntimeContractError, match="root or epoch"):
        runtime.verify_envelope(envelope.to_mapping(), expected_runtime=wrong_epoch, expected_controller=controller)

    snapshot = runtime.seal(
        runtime.PassiveSnapshot("2026-10-13T20:00:00Z", {"provider_status": "UNAVAILABLE"}),
        runtime=identity,
        controller=controller,
    )
    assert snapshot.kind is runtime.RecordKind.PASSIVE_SNAPSHOT
    assert snapshot.payload["passive"] is True
    assert "telemetry" not in snapshot.payload


def test_direct_relative_path_construction_cannot_escape_root(disposable_runtime, tmp_path: Path):
    root, _, identity, _ = disposable_runtime
    outside = tmp_path / "outside"
    outside.write_text("private", encoding="utf-8")
    with pytest.raises(runtime.RuntimeContractError):
        runtime.SafeRelativePath(PurePosixPath("../outside"))
    with pytest.raises(runtime.RuntimeContractError):
        runtime.SafeRelativePath(PurePosixPath("."))


def test_direct_identity_construction_cannot_bypass_factories(disposable_runtime, tmp_path: Path):
    root, controller_path, identity, controller = disposable_runtime
    with pytest.raises(runtime.RuntimeContractError):
        runtime.RuntimeIdentity(identity.root, "INVALID-EPOCH")
    with pytest.raises(runtime.RuntimeContractError):
        runtime.CanonicalProjectRoot(tmp_path / "missing")
    with pytest.raises(runtime.RuntimeContractError):
        runtime.InstalledControllerIdentity(controller_path, "not-a-digest")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(runtime.RuntimeContractError):
        runtime.CanonicalProjectRoot(alias)


def test_schema_version_rejects_boolean_and_malformed_types(disposable_runtime):
    _, _, identity, controller = disposable_runtime
    data = evidence(identity, controller).to_mapping()
    for value in (True, 1.0, "1"):
        candidate = dict(data)
        candidate["version"] = value
        with pytest.raises(runtime.RuntimeContractError, match="schema"):
            runtime.parse_envelope(candidate)


def test_verified_envelopes_are_deeply_immutable(disposable_runtime):
    _, _, identity, controller = disposable_runtime
    original = runtime.seal(
        runtime.EvidenceRecord("controller", "event-2", 1, "2026-10-13T20:00:00Z",
                               {"events": [{"name": "first"}]}),
        runtime=identity, controller=controller,
    )
    verified = runtime.verify_envelope(original.to_mapping(), expected_runtime=identity, expected_controller=controller)
    with pytest.raises(TypeError):
        verified.payload["record_kind"] = "authority"
    with pytest.raises(TypeError):
        verified.payload["body"]["events"][0]["name"] = "second"
    # Outbound serialization is still a plain JSON-compatible, independent copy.
    external = verified.to_mapping()
    external["payload"]["body"]["events"][0]["name"] = "changed"
    assert verified.to_mapping()["payload"]["body"]["events"][0]["name"] == "first"


def test_direct_invalid_envelope_construction_refuses(disposable_runtime):
    _, _, identity, controller = disposable_runtime
    original = evidence(identity, controller)
    with pytest.raises(runtime.RuntimeContractError, match="payload digest"):
        runtime.IntegrityEnvelope(original.kind, identity, controller,
                                  {**original.to_mapping()["payload"], "sequence": 999},
                                  original.payload_sha256, original.envelope_sha256)


def test_path_read_revalidates_root_before_use(disposable_runtime):
    root, _, identity, _ = disposable_runtime
    moved = root.with_name("renamed-project")
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(runtime.RuntimeContractError, match="symlink"):
        runtime.SafeRelativePath.parse("installed-controller").within(identity.root)


def test_sealing_rejects_stale_installed_controller(disposable_runtime):
    _, controller_path, identity, controller = disposable_runtime
    controller_path.write_bytes(b"modified after capture")
    with pytest.raises(runtime.RuntimeContractError, match="controller bytes changed"):
        runtime.seal(runtime.AuthorityRecord("A", "ACTIVE"), runtime=identity, controller=controller)
