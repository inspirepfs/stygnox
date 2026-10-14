from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, planning, qualification, reconciliation, runtime, scheduler, transactions


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


def test_adoption_and_transactions_read_a_normal_runtime_record_through_the_runtime_seam(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    record = root / adoption.RUNTIME_NAME / "adoption.json"
    record.parent.mkdir()
    record.write_text('{"schema":"stygnox_adoption_handoff_v1","reserve_percent":12.5}', encoding="utf-8")

    canonical_root = adoption.resolve_worktree(root)

    assert canonical_root == root
    assert transactions._runtime_json(canonical_root, "adoption.json") == {
        "schema": "stygnox_adoption_handoff_v1",
        "reserve_percent": 12.5,
    }


def test_adoption_refuses_substituted_project_identity_and_transactions_refuse_record_substitution(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    alias = tmp_path / "substituted-project"
    alias.symlink_to(root, target_is_directory=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"schema":"stygnox_adoption_handoff_v1"}', encoding="utf-8")
    runtime_dir = root / adoption.RUNTIME_NAME
    runtime_dir.mkdir()
    (runtime_dir / "adoption.json").symlink_to(outside)

    with pytest.raises(adoption.AdoptionError, match="project root"):
        adoption.resolve_worktree(alias)
    with pytest.raises(transactions.TransactionError, match="substituted"):
        transactions._runtime_json(root, "adoption.json")


def test_runtime_seam_refuses_fifo_without_blocking(tmp_path: Path):
    root = tmp_path / "project"
    runtime_dir = root / ".stygnox"
    runtime_dir.mkdir(parents=True)
    fifo = runtime_dir / "transaction.json"
    os.mkfifo(fifo)
    with pytest.raises(runtime.RuntimeContractError, match="regular file"):
        runtime.read_json_object(
            runtime.CanonicalProjectRoot.from_path(root),
            runtime.SafeRelativePath.parse(".stygnox/transaction.json"),
        )


@pytest.mark.parametrize("raw", [
    b'{"state": "ACTIVE", "state": "STOPPED"}',
    b'{"usage": NaN}',
    b'{"usage": Infinity}',
    b'{"nested": {"id": "a", "id": "b"}}',
])
def test_runtime_seam_refuses_ambiguous_json(tmp_path: Path, raw: bytes):
    root = tmp_path / "project"
    runtime_dir = root / ".stygnox"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "transaction.json").write_bytes(raw)
    with pytest.raises(runtime.RuntimeContractError, match="duplicate key|non-finite"):
        runtime.read_json_object(
            runtime.CanonicalProjectRoot.from_path(root),
            runtime.SafeRelativePath.parse(".stygnox/transaction.json"),
        )


def test_runtime_seam_rejects_oversize_json_before_read(tmp_path: Path):
    root = tmp_path / "project"
    runtime_dir = root / ".stygnox"
    runtime_dir.mkdir(parents=True)
    record = runtime_dir / "transaction.json"
    with record.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(runtime.RuntimeContractError, match="size limit"):
        runtime.read_json_object(
            runtime.CanonicalProjectRoot.from_path(root),
            runtime.SafeRelativePath.parse(".stygnox/transaction.json"),
        )


def _write_runtime_record(root: Path, name: str, body: dict[str, object]) -> None:
    path = root / adoption.RUNTIME_NAME / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def _plan_record(*, epoch: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {"schema": planning.PLAN_SCHEMA}
    if epoch is not None:
        body["runtime_epoch"] = epoch
    body["record_sha256"] = planning._digest(body)
    return body


def _scheduler_record(*, epoch: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {"schema": scheduler.SCHEDULER_SCHEMA}
    if epoch is not None:
        body["runtime_epoch"] = epoch
    body["record_sha256"] = scheduler._digest(body)
    return body


def test_controller_planning_and_scheduler_authority_reads_allow_identity_bootstrap(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    _write_runtime_record(root, "controller.json", {"schema": controller.CONTROLLER_SCHEMA})
    _write_runtime_record(root, planning.PLAN_RECORD, _plan_record())
    _write_runtime_record(root, scheduler.SCHEDULER_RECORD, _scheduler_record())

    assert controller._runtime_json(root, "controller.json") == {"schema": controller.CONTROLLER_SCHEMA}
    assert planning._record(root) is not None
    assert scheduler._record(root) is not None


def test_authority_readers_bind_established_runtime_epoch_and_refuse_stale_records(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    identity = runtime.RuntimeIdentity.create(runtime.CanonicalProjectRoot.from_path(root), EPOCH)
    _write_runtime_record(root, runtime.RUNTIME_IDENTITY_RECORD, identity.to_mapping())
    _write_runtime_record(root, "controller.json", {"schema": controller.CONTROLLER_SCHEMA, "runtime_epoch": EPOCH})
    _write_runtime_record(root, planning.PLAN_RECORD, _plan_record(epoch=EPOCH))
    _write_runtime_record(root, scheduler.SCHEDULER_RECORD, _scheduler_record(epoch=EPOCH))

    assert controller._runtime_json(root, "controller.json")["runtime_epoch"] == EPOCH
    assert planning._record(root) is not None
    assert scheduler._record(root) is not None

    _write_runtime_record(root, planning.PLAN_RECORD, _plan_record(epoch="f" * 32))
    with pytest.raises(planning.PlanningError, match="runtime epoch.*stale|substituted"):
        planning._record(root)


@pytest.mark.parametrize(("name", "reader", "body"), [
    ("controller.json", controller._runtime_json, {"schema": controller.CONTROLLER_SCHEMA}),
    (planning.PLAN_RECORD, planning._record, _plan_record()),
    (scheduler.SCHEDULER_RECORD, scheduler._record, _scheduler_record()),
])
def test_authority_readers_refuse_symlink_substitution(tmp_path: Path, name, reader, body):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / f"{name}.json"
    outside.write_text(json.dumps(body), encoding="utf-8")
    runtime_dir = root / adoption.RUNTIME_NAME
    runtime_dir.mkdir()
    (runtime_dir / name).symlink_to(outside)

    with pytest.raises((controller.ControllerError, planning.PlanningError, scheduler.SchedulerError), match="substituted|unavailable"):
        if reader is controller._runtime_json:
            reader(root, name)
        else:
            reader(root)


@pytest.mark.parametrize(("name", "reader"), [
    ("controller.json", controller._runtime_json),
    (planning.PLAN_RECORD, planning._record),
    (scheduler.SCHEDULER_RECORD, scheduler._record),
])
def test_authority_readers_refuse_ambiguous_json(tmp_path: Path, name, reader):
    root = tmp_path / "project"
    runtime_dir = root / adoption.RUNTIME_NAME
    runtime_dir.mkdir(parents=True)
    (runtime_dir / name).write_bytes(b'{"schema":"first","schema":"second"}')

    with pytest.raises((controller.ControllerError, planning.PlanningError, scheduler.SchedulerError), match="duplicate key"):
        if reader is controller._runtime_json:
            reader(root, name)
        else:
            reader(root)


def test_epoch_bearing_authority_does_not_downgrade_to_bootstrap_if_identity_missing(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    identity = runtime.RuntimeIdentity.create(runtime.CanonicalProjectRoot.from_path(root), EPOCH)
    _write_runtime_record(root, runtime.RUNTIME_IDENTITY_RECORD, identity.to_mapping())
    _write_runtime_record(root, planning.PLAN_RECORD, _plan_record(epoch="f" * 32))
    with pytest.raises(planning.PlanningError, match="runtime epoch"):
        planning._record(root)
    (root / adoption.RUNTIME_NAME / runtime.RUNTIME_IDENTITY_RECORD).unlink()
    with pytest.raises(planning.PlanningError, match="runtime identity is missing"):
        planning._record(root)


def test_controller_recovery_receipt_missing_is_distinct_from_substituted(tmp_path: Path):
    root = tmp_path / "project"
    runtime_dir = root / adoption.RUNTIME_NAME
    runtime_dir.mkdir(parents=True)
    preview = "a" * 64
    assert scheduler._controller_receipt(root, preview) is None
    receipt = runtime_dir / f"controller-run-{preview[:16]}.json"
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    receipt.symlink_to(target)
    with pytest.raises(scheduler.SchedulerError, match="invalid|substituted"):
        scheduler._controller_receipt(root, preview)


def test_controller_recovery_receipt_with_invalid_digest_refuses(tmp_path: Path):
    root = tmp_path / "project"
    runtime_dir = root / adoption.RUNTIME_NAME
    runtime_dir.mkdir(parents=True)
    preview = "b" * 64
    receipt = runtime_dir / f"controller-run-{preview[:16]}.json"
    receipt.write_text(json.dumps({
        "schema": controller.RUN_RESULT_SCHEMA,
        "preview_sha256": preview,
        "record_sha256": "0" * 64,
    }), encoding="utf-8")
    with pytest.raises(scheduler.SchedulerError, match="integrity"):
        scheduler._controller_receipt(root, preview)


def _controller_receipt(*, epoch: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": controller.RUN_RESULT_SCHEMA,
        "preview_sha256": "c" * 64,
        "operator": "Operator One",
        "transaction_id": "TX-disposable",
        "plan_binding": {"plan_hash": "d" * 64, "current_step": 1},
        "actual_delta": {"paths": []},
    }
    if epoch is not None:
        body["runtime_epoch"] = epoch
    body["record_sha256"] = controller._digest(body)
    return body


def test_qualification_receipt_discovery_preserves_bootstrap_and_absence(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()

    assert qualification._controller_receipts(root) == []
    receipt = _controller_receipt()
    _write_runtime_record(root, "controller-run-cccccccccccccccc.json", receipt)

    assert qualification._controller_receipts(root) == [receipt]


@pytest.mark.parametrize(("mutation", "message"), [
    ("wrong-epoch", "runtime epoch"),
    ("symlink", "substituted|unavailable"),
    ("malformed", "malformed|duplicate key"),
])
def test_qualification_receipt_discovery_refuses_unproven_runtime_evidence(tmp_path: Path, mutation: str, message: str):
    root = tmp_path / "project"
    root.mkdir()
    identity = runtime.RuntimeIdentity.create(runtime.CanonicalProjectRoot.from_path(root), EPOCH)
    _write_runtime_record(root, runtime.RUNTIME_IDENTITY_RECORD, identity.to_mapping())
    name = "controller-run-cccccccccccccccc.json"
    _write_runtime_record(root, name, _controller_receipt(epoch=EPOCH))

    path = root / adoption.RUNTIME_NAME / name
    if mutation == "wrong-epoch":
        _write_runtime_record(root, name, _controller_receipt(epoch="f" * 32))
    elif mutation == "symlink":
        outside = tmp_path / "receipt.json"
        outside.write_text(json.dumps(_controller_receipt(epoch=EPOCH)), encoding="utf-8")
        path.unlink()
        path.symlink_to(outside)
    else:
        path.write_bytes(b'{"schema":"first","schema":"second"}')

    with pytest.raises(qualification.QualificationError, match=message):
        qualification._controller_receipts(root)


def test_qualification_does_not_treat_wrong_controller_lineage_as_current_authority(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    receipt = _controller_receipt()
    receipt.update({
        "operator": "Other Operator",
        "transaction_id": "TX-other",
        "plan_binding": {"plan_hash": "d" * 64, "current_step": 1, "plan_record_sha256": "e" * 64},
        "before_baseline_sha256": "a" * 64,
        "after_baseline_sha256": "b" * 64,
        "next_action": "turn-complete",
        "human_gate": None,
    })
    receipt["record_sha256"] = controller._digest({key: value for key, value in receipt.items() if key != "record_sha256"})
    _write_runtime_record(root, "controller-run-cccccccccccccccc.json", receipt)

    with pytest.raises(qualification.QualificationError, match="no exact completed controller turn"):
        qualification._step_receipt(root, {
            "current_step": 1,
            "plan_hash": "d" * 64,
            "record_sha256": "e" * 64,
            "step_authority_baseline_sha256": "a" * 64,
            "operator": "Operator One",
            "transaction_id": "TX-current",
        }, "b" * 64)


def test_reconciliation_receipt_discovery_refuses_substituted_current_evidence(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    runtime_dir = root / adoption.RUNTIME_NAME
    runtime_dir.mkdir()
    name = "controller-run-dddddddddddddddd.json"
    outside = tmp_path / "receipt.json"
    outside.write_text("{}", encoding="utf-8")
    (runtime_dir / name).symlink_to(outside)

    with pytest.raises(reconciliation.ReconciliationError, match="controller receipt.*substituted|controller receipt.*unavailable"):
        reconciliation._authorised_adopted_delta(
            root,
            {"plan_hash": "d" * 64, "current_step": 1, "transaction_id": "TX-disposable"},
            {"disposition": reconciliation.ADOPTED, "classification": "retired-carry-forward", "path": "README.md", "inherited_fingerprint": "before"},
            {"path": "README.md", "content_fingerprint": "after"},
        )


def test_reconciliation_refuses_corrupt_competing_receipt_after_valid_match(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    valid = _controller_receipt()
    valid.update({
        "actual_delta": {"paths": [{
            "path": "README.md", "before_fingerprint": "before",
            "after_fingerprint": "after", "kind": "modified",
        }]},
        "next_action": "qualification-required",
        "provider_result": {"status": "PASS"},
    })
    valid["record_sha256"] = controller._digest({k: v for k, v in valid.items() if k != "record_sha256"})
    _write_runtime_record(root, "controller-run-aaaaaaaaaaaaaaaa.json", valid)
    state = {"plan_hash": "d" * 64, "current_step": 1, "operator": "Operator One", "transaction_id": "TX-disposable"}
    action = {"disposition": reconciliation.ADOPTED, "classification": "retired-carry-forward",
              "path": "README.md", "inherited_fingerprint": "before"}
    candidate = {"path": "README.md", "content_fingerprint": "after"}
    assert reconciliation._authorised_adopted_delta(root, state, action, candidate) is not None

    corrupt = dict(valid)
    corrupt["record_sha256"] = "0" * 64
    _write_runtime_record(root, "controller-run-bbbbbbbbbbbbbbbb.json", corrupt)
    with pytest.raises(reconciliation.ReconciliationError, match="integrity"):
        reconciliation._authorised_adopted_delta(root, state, action, candidate)


def test_reconciliation_unsupported_receipt_schema_is_not_invisible(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    _write_runtime_record(root, "controller-run-aaaaaaaaaaaaaaaa.json", {"schema": "unexpected", "record_sha256": "0" * 64})
    with pytest.raises(reconciliation.ReconciliationError, match="schema"):
        reconciliation._authorised_adopted_delta(
            root,
            {"plan_hash": "d" * 64, "current_step": 1, "operator": "Operator One", "transaction_id": "TX-disposable"},
            {"disposition": reconciliation.ADOPTED, "classification": "retired-carry-forward",
             "path": "README.md", "inherited_fingerprint": "before"},
            {"path": "README.md", "content_fingerprint": "after"},
        )


def test_reconciliation_malformed_signed_step_is_not_coerced(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    receipt = _controller_receipt()
    receipt["plan_binding"] = {"plan_hash": "d" * 64, "current_step": "not-a-step"}
    receipt["record_sha256"] = controller._digest({k: v for k, v in receipt.items() if k != "record_sha256"})
    _write_runtime_record(root, "controller-run-aaaaaaaaaaaaaaaa.json", receipt)
    assert reconciliation._authorised_adopted_delta(
        root,
        {"plan_hash": "d" * 64, "current_step": 1, "operator": "Operator One", "transaction_id": "TX-disposable"},
        {"disposition": reconciliation.ADOPTED, "classification": "retired-carry-forward",
         "path": "README.md", "inherited_fingerprint": "before"},
        {"path": "README.md", "content_fingerprint": "after"},
    ) is None


def test_completion_report_binds_persisted_runtime_identity(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    identity = runtime.RuntimeIdentity.create(runtime.CanonicalProjectRoot.from_path(root), EPOCH)
    _write_runtime_record(root, runtime.RUNTIME_IDENTITY_RECORD, identity.to_mapping())
    plan_hash = "d" * 64
    monkeypatch.setattr(adoption, "resolve_worktree", lambda _project: root)
    monkeypatch.setattr(planning, "_record", lambda _root: {"plan_hash": plan_hash})
    report = {"schema": qualification.REPORT_SCHEMA, "plan_hash": plan_hash}
    report["report_sha256"] = qualification._digest(report)
    _write_runtime_record(root, qualification.REPORT_JSON, report)
    with pytest.raises(qualification.QualificationError, match="runtime epoch"):
        qualification.completion_report(root, plan_hash)
    report["runtime_epoch"] = EPOCH
    report["report_sha256"] = qualification._digest({k: v for k, v in report.items() if k != "report_sha256"})
    _write_runtime_record(root, qualification.REPORT_JSON, report)
    assert qualification.completion_report(root, plan_hash) == report
