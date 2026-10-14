"""End-to-end evidence for native predecessor/successor write release.

The predecessor wheel is assembled solely from committed ``1379422`` source;
the successor wheel comes from this candidate.  They are installed into two
temporary, isolated locations.  The integration path therefore proves actual
installed-wheel behaviour without changing a persistent environment or a real
runtime directory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OLD_REVISION = "1379422c9e443350b2c3661a94558f9baa637c42"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, controller, planning, provider_codex, provider_release, provider_usage, provider_write_release, transactions


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _hash(payload: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True)


def _catalog() -> dict[str, object]:
    value: dict[str, object] = {"schema": provider_codex.MODEL_CATALOG_SCHEMA, "provider": "codex", "models": [{"id": "gpt-test", "reasoning_efforts": ["high"]}]}
    value["catalog_sha256"] = provider_codex._digest(value)
    return value


def _proposal() -> dict[str, object]:
    return {"provider": "codex", "model": "gpt-test", "effort": "high", "sandbox": "read-only",
        "payload": {"steps": [{"id": 1, "title": "Bounded write", "objective": "Apply the approved write", "acceptance": ["bounded"], "test_change_policy": "none"}],
                    "files_inspected": ["README.md"], "repository_mutation_scope": ["README.md"]},
        "metrics": {"commands_executed": 1, "input_tokens": 1, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0, "codex_seconds": 0.1}}


def _wheel_sources(revision: str | None) -> dict[str, bytes]:
    if revision is None:
        return {
            str(source.relative_to(SRC)).replace(os.sep, "/"): source.read_bytes()
            for source in sorted((SRC / "stygnox").rglob("*.py"))
        }
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision, "--", "src/stygnox"],
        cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout.splitlines()
    return {
        path.removeprefix("src/"): subprocess.run(
            ["git", "show", f"{revision}:{path}"], cwd=ROOT, check=True, capture_output=True,
        ).stdout
        for path in listed if path.endswith(".py")
    }


def _wheel(tmp_path: Path, name: str, *, revision: str | None) -> Path:
    wheel = tmp_path / f"stygnox-0.1.0-{name}-py3-none-any.whl"
    entries = _wheel_sources(revision)
    metadata = b"Metadata-Version: 2.1\nName: stygnox\nVersion: 0.1.0\n"
    entries["stygnox-0.1.0.dist-info/METADATA"] = metadata
    rows = [f"{entry},{_hash(payload)},{len(payload)}" for entry, payload in sorted(entries.items())]
    entries["stygnox-0.1.0.dist-info/RECORD"] = ("\n".join(rows + ["stygnox-0.1.0.dist-info/RECORD,,"]) + "\n").encode()
    with zipfile.ZipFile(wheel, "w") as archive:
        for entry, payload in entries.items():
            archive.writestr(entry, payload)
    return wheel


def _wheel_contents(wheel: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name.startswith("stygnox/")}


def _install(wheel: Path, root: Path, *, successor: bool) -> adoption.CommandIdentity:
    site = root / "site"
    bin_dir = root / "bin"
    site.mkdir(parents=True)
    bin_dir.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site)
    executable = bin_dir / "stygnox"
    launcher = [
        "#!" + sys.executable,
        "import os, sys",
        f"sys.path.insert(0, {str(site)!r})",
    ]
    if successor:
        launcher += [
            "from stygnox import provider_write_release as write_release",
            "write_release.TARGET_BASELINE_REVISION = os.environ['STYGNOX_TEST_HEAD']",
            "write_release.TARGET_TRANSACTION_ID = os.environ['STYGNOX_TEST_TX']",
            "write_release.TARGET_PLAN_HASH = os.environ['STYGNOX_TEST_PLAN']",
            "if os.environ.get('STYGNOX_TEST_QUOTA_ADMISSION') == '1':",
            "    import json",
            "    from pathlib import Path",
            "    from stygnox import provider_usage",
            "    if write_release.dispatch_allowed(Path(os.environ['STYGNOX_TEST_PROJECT']), 'write-turn'):",
            "        raise SystemExit(93)",
            "    print(json.dumps(provider_usage.ensure_capacity(Path(os.environ['STYGNOX_TEST_PROJECT']), plan_state={'plan_hash': os.environ['STYGNOX_TEST_PLAN']}, model='gpt-test', reserve_percent=5.0, wait=False, poll_seconds=1), sort_keys=True))",
            "    raise SystemExit(0)",
        ]
    launcher += ["from stygnox.cli import main", "raise SystemExit(main())"]
    executable.write_text("\n".join(launcher) + "\n", encoding="utf-8")
    executable.chmod(0o755)
    record = site / "stygnox-0.1.0.dist-info" / "RECORD"
    payload = executable.read_bytes()
    record.write_text(record.read_text(encoding="utf-8") + f"../bin/stygnox,{_hash(payload)},{len(payload)}\n", encoding="utf-8")
    return adoption.CommandIdentity(executable.resolve(), (site / "stygnox" / "adoption.py").resolve(), "0.1.0")


def _run(command: Path, args: list[str], env: dict[str, str], *, path_first: Path | None = None) -> subprocess.CompletedProcess[str]:
    clean = {key: value for key, value in env.items() if key != "PYTHONPATH"}
    clean["PATH"] = str(path_first or command.parent) + os.pathsep + clean.get("PATH", "")
    return subprocess.run([str(command), *args], text=True, capture_output=True, env=clean, check=False)


def _preview(prepared: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return _run(
        prepared["successor"],
        ["provider-write-release", "preview", "--project", str(prepared["repo"]), "--operator", "Operator", "--artifact", str(prepared["new_wheel"])],
        prepared["env"],
    )


def _quota_only_codex(tmp_path: Path) -> tuple[Path, Path]:
    """Return an app-server stub that refuses every operation except quota read."""
    bin_dir = tmp_path / "quota-bin"
    bin_dir.mkdir()
    log = tmp_path / "quota-methods.jsonl"
    codex = bin_dir / "codex"
    raw_limits = {
        "ordinaryUsageAllowed": True,
        "rateLimitsByLimitId": {
            "codex": {
                "planType": "test",
                "primary": {"usedPercent": 20, "windowDurationMins": 300, "resetsAt": 2_000_000_000},
                "secondary": {"usedPercent": 30, "windowDurationMins": 10_080, "resetsAt": 2_000_100_000},
            }
        },
    }
    codex.write_text(
        "#!" + sys.executable + "\n"
        "import json, os, sys\n"
        "if sys.argv[1:] != ['app-server', '--stdio']:\n"
        "    raise SystemExit(91)\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    method = request.get('method')\n"
        "    if method == 'account/rateLimits/read':\n"
        "        with open(os.environ['STYGNOX_TEST_QUOTA_LOG'], 'a', encoding='utf-8') as handle:\n"
        "            handle.write(json.dumps(method) + '\\n')\n"
        "        result = " + repr(raw_limits) + "\n"
        "    elif method == 'initialize':\n"
        "        result = {}\n"
        "    elif method == 'initialized':\n"
        "        continue\n"
        "    else:\n"
        "        raise SystemExit(92)\n"
        "    if request.get('id') is not None:\n"
        "        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    return codex, log


def _record_authorised_continuation(prepared: dict[str, object]) -> None:
    """Create the same sealed plan/receipt evidence a completed turn leaves."""
    repo = prepared["repo"]
    before = planning.approved_step_context(repo, "Operator")
    assert before is not None
    (repo / "README.md").write_text("authorised continuation\n", encoding="utf-8")
    after = adoption.capture_baseline(repo).public()
    origin = "a" * 64
    continuation = planning.record_same_step_continuation(
        repo,
        "Operator",
        plan_binding={
            "plan_hash": before["plan_hash"],
            "plan_record_sha256": before["plan_record_sha256"],
            "current_step": before["current_step"],
            "repository_mutation_scope": before["repository_mutation_scope"],
            "repository_mutation_scope_sha256": before["repository_mutation_scope_sha256"],
        },
        origin_preview_sha256=origin,
        before_baseline_sha256=before["step_authority_baseline_sha256"],
        after_baseline=after,
        summary="authorised bounded continuation",
    )
    receipt = {
        "schema": controller.RUN_RESULT_SCHEMA,
        "operator": "Operator",
        "transaction_id": before["transaction_id"],
        "preview_sha256": origin,
        "repository_authority": "write",
        "plan_binding": {
            "plan_hash": before["plan_hash"],
            "current_step": before["current_step"],
            "repository_mutation_scope": before["repository_mutation_scope"],
            "repository_mutation_scope_sha256": before["repository_mutation_scope_sha256"],
            "step_authority_baseline_sha256": before["step_authority_baseline_sha256"],
        },
        "provider_result": {"status": "PASS"},
        "blocker_class": "continuation",
        "continuation": continuation,
        "before_baseline_sha256": before["step_authority_baseline_sha256"],
        "after_baseline_sha256": after["sha256"],
        "project_changed": True,
        "human_gate": None,
        "next_action": "continue-same-step",
    }
    receipt["record_sha256"] = controller._digest(receipt)
    adoption.write_runtime_record(repo, f"controller-run-{origin[:16]}.json", receipt, actor="controller")


@pytest.fixture
def prepared(tmp_path: Path) -> dict[str, object]:
    old_wheel = _wheel(tmp_path, "old", revision=OLD_REVISION)
    new_wheel = _wheel(tmp_path, "new", revision=None)
    old_contents = _wheel_contents(old_wheel)
    new_contents = _wheel_contents(new_wheel)
    assert old_contents != new_contents
    assert "stygnox/provider_write_release.py" not in old_contents
    assert "stygnox/provider_write_release.py" in new_contents
    predecessor = _install(old_wheel, tmp_path / "predecessor", successor=False)
    successor = _install(new_wheel, tmp_path / "successor", successor=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "native write release")
    _git(repo, "config", "user.email", "native@example.invalid")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "baseline")
    with (mock.patch.object(adoption, "resolve_installed_command", return_value=predecessor),
          mock.patch.object(provider_codex, "model_catalog", return_value=_catalog()),
          mock.patch.object(provider_usage, "ensure_capacity", return_value={"guard": "SAFE"})):
        handoff = adoption.build_preview(repo, "Operator", provider="codex", model="gpt-test", effort="high", reviewer="Operator")
        adoption.handoff_adoption(repo, "Operator", handoff["preview_sha256"], "HANDOFF", provider="codex", model="gpt-test", effort="high", reviewer="Operator")
        tx = transactions.begin_transaction(repo, "Operator", "BEGIN")
        controller.activate_controller(repo, "Operator", "ACTIVATE")
        planning_preview = provider_release.preview(repo, "Operator")
        provider_release.release(repo, "Operator", planning_preview["preview_sha256"], "RELEASE_PLANNING")
        proposal_preview = planning.build_proposal_preview(repo, "Operator", "Apply the approved write", "write", min_steps=1, max_steps=1)
        with mock.patch.object(provider_codex, "execute_structured", return_value=_proposal()):
            proposed = planning.propose_plan(repo, "Operator", "Apply the approved write", "write", proposal_preview["preview_sha256"], "PROPOSE", min_steps=1, max_steps=1)
        approved = planning.approve_plan(repo, "Operator", proposed["plan_hash"], "APPROVE")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
    env = {"PATH": os.environ.get("PATH", ""), "STYGNOX_TEST_HEAD": head, "STYGNOX_TEST_TX": tx["transaction_id"], "STYGNOX_TEST_PLAN": approved["plan_hash"]}
    old_status = _run(predecessor.executable, ["provider-release", "status", "--project", str(repo), "--operator", "Operator"], env)
    assert old_status.returncode == 0, old_status.stderr
    old_evidence = json.loads(old_status.stdout)
    assert old_evidence["planning_ready"] is True
    assert old_evidence["release"] == provider_release._record(repo)
    return {"repo": repo, "predecessor": predecessor.executable, "successor": successor.executable, "old_wheel": old_wheel, "new_wheel": new_wheel, "env": env}


@pytest.fixture
def transferred(prepared: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    preview = _preview(prepared)
    assert preview.returncode == 0, preview.stderr
    preview_record = json.loads(preview.stdout)
    assert preview_record["predecessor_installed"]["executable"] == str(prepared["predecessor"])
    assert preview_record["successor_installed"]["executable"] == str(prepared["successor"])
    receipt = _run(
        prepared["successor"],
        ["provider-write-release", "release", "--project", str(prepared["repo"]), "--operator", "Operator", "--artifact", str(prepared["new_wheel"]), "--preview", preview_record["preview_sha256"], "--confirm", "RELEASE_WRITE", "--successor", str(prepared["successor"])],
        prepared["env"],
    )
    assert receipt.returncode == 0, receipt.stderr
    return prepared, json.loads(receipt.stdout)


def test_old_and_new_wheels_transfer_only_from_the_new_successor(transferred: tuple[dict[str, object], dict[str, object]]) -> None:
    prepared, receipt = transferred
    assert receipt["predecessor_execution_authorised"] is False
    assert receipt["successor_execution_authorised"] is True
    assert receipt["fresh_process"]["executable"] == str(prepared["successor"])
    status = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert status.returncode == 0
    assert json.loads(status.stdout)["write_execution_ready"] is True
    admission = _run(prepared["successor"], ["controller", "run-preview", "--project", str(prepared["repo"]), "--operator", "Operator", "--objective", "Apply the approved write", "--repository-authority", "write"], prepared["env"])
    assert admission.returncode == 0, admission.stderr
    assert json.loads(admission.stdout)["plan_binding"]["current_step"] == 1


def test_successor_quota_admission_uses_only_rate_limit_metadata(
    transferred: tuple[dict[str, object], dict[str, object]], tmp_path: Path,
) -> None:
    """Quota admission happens before a write-turn context and cannot run a model."""
    prepared, _ = transferred
    codex, log = _quota_only_codex(tmp_path)
    env = {
        **prepared["env"],
        "PATH": str(codex.parent) + os.pathsep + prepared["env"]["PATH"],
        "STYGNOX_TEST_QUOTA_ADMISSION": "1",
        "STYGNOX_TEST_PROJECT": str(prepared["repo"]),
        "STYGNOX_TEST_QUOTA_LOG": str(log),
    }
    admitted = _run(prepared["successor"], [], env)
    assert admitted.returncode == 0, admitted.stderr
    assert json.loads(admitted.stdout)["guard"] == "SAFE"
    assert [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] == ["account/rateLimits/read"]


def test_mismatched_installations_and_missing_predecessor_fail_closed(prepared: dict[str, object]) -> None:
    wrong_path = _run(prepared["successor"], ["provider-write-release", "preview", "--project", str(prepared["repo"]), "--operator", "Operator", "--artifact", str(prepared["new_wheel"])], prepared["env"], path_first=prepared["predecessor"].parent)
    assert wrong_path.returncode == 2
    old_artifact = _run(prepared["successor"], ["provider-write-release", "preview", "--project", str(prepared["repo"]), "--operator", "Operator", "--artifact", str(prepared["old_wheel"])], prepared["env"])
    assert old_artifact.returncode == 2
    prepared["predecessor"].unlink()
    missing = _preview(prepared)
    assert missing.returncode == 2


def test_changed_planning_evidence_and_approval_lineage_revoke_admission(transferred: tuple[dict[str, object], dict[str, object]]) -> None:
    prepared, _ = transferred
    controller_path = prepared["repo"] / adoption.RUNTIME_NAME / controller.CONTROLLER_RECORD
    controller_record = json.loads(controller_path.read_text(encoding="utf-8"))
    controller_record["operator"] = "Other"
    controller_record["record_sha256"] = _digest({key: value for key, value in controller_record.items() if key != "record_sha256"})
    controller_path.write_text(json.dumps(controller_record), encoding="utf-8")
    denied = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert json.loads(denied.stdout)["write_execution_ready"] is False


def test_changed_planning_release_evidence_refuses_successor_preview(prepared: dict[str, object]) -> None:
    release_path = prepared["repo"] / adoption.RUNTIME_NAME / provider_release.RECORD
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["scope"] = "WRITE"
    release["record_sha256"] = _digest({key: value for key, value in release.items() if key != "record_sha256"})
    release_path.write_text(json.dumps(release), encoding="utf-8")
    denied = _preview(prepared)
    assert denied.returncode == 2


def test_interrupted_pending_transfer_denies_both_admission_and_reentry(prepared: dict[str, object]) -> None:
    preview = _preview(prepared)
    assert preview.returncode == 0, preview.stderr
    value = json.loads(preview.stdout)
    binding = {key: item for key, item in value.items() if key not in {"preview_sha256", "requires_explicit_confirmation"}}
    with provider_write_release._transfer_lock(prepared["repo"]):
        provider_write_release._write_pending(prepared["repo"], binding, value["preview_sha256"], os.getpid())
    status = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert json.loads(status.stdout)["write_execution_ready"] is False
    denied = _preview(prepared)
    assert denied.returncode == 2


def test_mutable_current_step_receipt_is_revalidated_not_frozen(transferred: tuple[dict[str, object], dict[str, object]]) -> None:
    prepared, _ = transferred
    before = planning.approved_step_context(prepared["repo"], "Operator")
    assert before is not None
    planning.record_same_step_continuation(prepared["repo"], "Operator", plan_binding={"plan_hash": before["plan_hash"], "plan_record_sha256": before["plan_record_sha256"], "current_step": before["current_step"], "repository_mutation_scope": before["repository_mutation_scope"], "repository_mutation_scope_sha256": before["repository_mutation_scope_sha256"]}, origin_preview_sha256="a" * 64, before_baseline_sha256=before["step_authority_baseline_sha256"], after_baseline=adoption.capture_baseline(prepared["repo"]).public(), summary="bounded continuation")
    status = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert json.loads(status.stdout)["write_execution_ready"] is True


def test_authorised_tracked_continuation_preserves_successor_after_predecessor_readiness_expires(
    transferred: tuple[dict[str, object], dict[str, object]],
) -> None:
    prepared, _ = transferred
    _record_authorised_continuation(prepared)
    predecessor_status = _run(
        prepared["predecessor"],
        ["provider-release", "status", "--project", str(prepared["repo"]), "--operator", "Operator"],
        prepared["env"],
    )
    assert predecessor_status.returncode == 0, predecessor_status.stderr
    assert json.loads(predecessor_status.stdout)["planning_ready"] is False
    successor_status = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert successor_status.returncode == 0, successor_status.stderr
    assert json.loads(successor_status.stdout)["write_execution_ready"] is True


def test_unrecorded_tracked_baseline_change_revokes_successor_admission(
    transferred: tuple[dict[str, object], dict[str, object]],
) -> None:
    prepared, _ = transferred
    (prepared["repo"] / "README.md").write_text("hostile baseline change\n", encoding="utf-8")
    status = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["write_execution_ready"] is False


def test_source_identity_is_the_full_committed_predecessor_hash() -> None:
    committed = subprocess.run(
        ["git", "rev-parse", OLD_REVISION], cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout.strip()
    assert provider_write_release.TARGET_BASELINE_REVISION == committed
    assert len(provider_write_release.TARGET_BASELINE_REVISION) == 40


@pytest.mark.parametrize("mutation", ["preview", "write-flag", "scope"])
def test_resealed_inconsistent_release_does_not_grant_write_authority(
    transferred: tuple[dict[str, object], dict[str, object]], mutation: str,
) -> None:
    """A valid outer checksum cannot repair contradictory release intent."""
    prepared, _ = transferred
    record_path = prepared["repo"] / adoption.RUNTIME_NAME / provider_write_release.RECORD
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if mutation == "preview":
        record["preview_sha256"] = "f" * 64
    elif mutation == "write-flag":
        record["binding"]["provider_write_turn"] = False
        record["preview_sha256"] = _digest(record["binding"])
    else:
        record["binding"]["scope"] = "READ_ONLY"
        record["preview_sha256"] = _digest(record["binding"])
    record["record_sha256"] = _digest({key: value for key, value in record.items() if key != "record_sha256"})
    record_path.write_text(json.dumps(record), encoding="utf-8")

    status = _run(prepared["successor"], ["provider-write-release", "status", "--project", str(prepared["repo"])], prepared["env"])
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["write_execution_ready"] is False

    admitted = _run(prepared["successor"], ["controller", "run-preview", "--project", str(prepared["repo"]),
        "--operator", "Operator", "--objective", "Apply the approved write", "--repository-authority", "write"], prepared["env"])
    assert admitted.returncode != 0, "contradictory release must not reach controller admission"


def test_no_write_preview_before_successor_transfer(prepared: dict[str, object]) -> None:
    """Planning/catalogue readiness must never substitute for a write release."""
    preview = _run(prepared["successor"], ["controller", "run-preview", "--project", str(prepared["repo"]),
        "--operator", "Operator", "--objective", "Apply the approved write", "--repository-authority", "write"], prepared["env"])
    assert preview.returncode != 0, "write preview was accepted without a successor release"
