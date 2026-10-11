#!/usr/bin/env python3
"""Hostile, read-only predecessor controller/scheduler execution-entry probe.

Exercise the *installed predecessor* code in a fresh Python process using a
throwaway Git worktree and a sealed successor-only plan-state fixture. No
provider invocation, installation or live Stygnox runtime is permitted.

Only the unrelated active controller/transaction/policy prerequisites are
stubbed to allow controller run-preview to reach the REAL installed planning
admission method. That method is not replaced or wrapped. The probe cannot
establish exclusive runtime transfer, in-flight turn fencing, or mutation
protection for every other legacy command; it does not issue authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STATUS = "RECOVERY_SUCCESSOR_APPROVED_V1"
REJECTION = "unsupported active plan status for execution"


class ProbeRefused(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=root, env=env, capture_output=True,
                              text=True, timeout=20, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProbeRefused("installed predecessor did not terminate within probe timeout") from exc


def probe(installed_cli: Path) -> dict[str, object]:
    if (not installed_cli.is_absolute() or installed_cli.is_symlink()
        or not installed_cli.is_file()):
        raise ProbeRefused("predecessor CLI must be an absolute, regular, non-symlink installed executable")
    interpreter = installed_cli.parent / "python3"
    if not interpreter.is_file():
        raise ProbeRefused("predecessor installed interpreter is missing")
    exe_hash = _sha256(installed_cli)
    with tempfile.TemporaryDirectory(prefix="stygnox-c2c-old-execution-fence-") as tmp:
        root = Path(tmp)
        init = subprocess.run(["git", "init", "-q", str(root)], capture_output=True, text=True, check=False)
        if init.returncode:
            raise ProbeRefused("cannot initialise disposable fixture: " + init.stderr[-250:])
        runtime = root / ".stygnox"
        runtime.mkdir()
        plan = {
            "schema": "stygnox_plan_state_v1", "status": STATUS,
            "execution_authority_granted": False,
            "operator": "c2c-probe", "transaction_id": "TX-c2c-fixture", "plan": None,
        }
        plan["record_sha256"] = hashlib.sha256(json.dumps(
            plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest()
        path = runtime / "plan.json"
        path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
        plan_hash_before = _sha256(path)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # The installed executable must read the exact successor-only fixture.
        status = _run([str(installed_cli), "plan", "status", "--project", str(root)], root=root, env=env)
        if status.returncode:
            raise ProbeRefused("installed plan status refused disposable fixture: " + (status.stdout + status.stderr)[-500:])
        try:
            observed = json.loads(status.stdout)
        except json.JSONDecodeError as exc:
            raise ProbeRefused("installed CLI returned non-JSON plan status") from exc
        if (observed.get("plan", {}).get("status") != STATUS
            or observed.get("execution_authority_granted") is not False):
            raise ProbeRefused("installed CLI did not observe denied successor-only plan state")

        # The installed planning function and all four tested execution-entry
        # functions are real. Only preceding prerequisites that cannot affect
        # the successor-status decision are supplied in-process. No provider
        # or scheduler execution is permitted by this probe.
        code = r'''
import json, pathlib, sys
from unittest import mock
from stygnox import controller, planning, scheduler
root = pathlib.Path(sys.argv[1])
name = "c2c-probe"
checks = {}

def refused(label, call, exception):
    try:
        call()
    except exception as exc:
        message = str(exc)
        if "unsupported active plan status for execution" not in message or "RECOVERY_SUCCESSOR_APPROVED_V1" not in message:
            raise RuntimeError(f"{label}: inconclusive refusal: {message}") from exc
        checks[label] = True
    else:
        raise RuntimeError(f"{label}: installed entry admitted forbidden successor-only state")

# Test real installed scheduler admission (no stubs needed).
refused("scheduler_preview", lambda: scheduler.build_schedule_preview(root, name), scheduler.SchedulerError)
refused("scheduler_run", lambda: scheduler.run_schedule(root, name, "0" * 64, "SCHEDULE"), scheduler.SchedulerError)

# Controller checks before invoking planning depend on neutral policy and
# active transaction; patch only these prerequisites. Do not patch planning
# or controller.run_controller or scheduler.run_schedule.
with (mock.patch.object(controller, "_controller", return_value={
          "enabled": True, "operator": name, "transaction_id": "TX-c2c-fixture"}),
      mock.patch.object(controller, "_transaction", return_value={
          "operator": name, "transaction_id": "TX-c2c-fixture"}),
      mock.patch.object(controller, "_policy_status", return_value={
          "approved": True, "policy": {"provider": controller.provider_codex.PROVIDER_NAME, "model": "synthetic"}}),
      mock.patch.object(scheduler, "active_scheduler_authority", return_value=None),
      mock.patch.object(controller.provider_codex, "execute", side_effect=AssertionError("provider was executed"))):
    refused("controller_preview", lambda: controller.build_run_preview(root, name, "probe", "write"), controller.ControllerError)
    refused("controller_run", lambda: controller.run_controller(root, name, "probe", "write", "0" * 64, "RUN"), controller.ControllerError)

print(json.dumps({"checks": checks,
                  "controller_module": str(pathlib.Path(controller.__file__).resolve()),
                  "planning_module": str(pathlib.Path(planning.__file__).resolve()),
                  "scheduler_module": str(pathlib.Path(scheduler.__file__).resolve())}, sort_keys=True))
'''
        process = _run([str(interpreter), "-I", "-c", code, str(root)], root=root, env=env)
        if process.returncode:
            raise ProbeRefused("installed execution-entry probe failed: " + (process.stdout + process.stderr)[-1200:])
        try:
            evidence = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ProbeRefused("installed execution probe returned non-JSON evidence") from exc
        if evidence.get("checks") != dict.fromkeys(
            ("scheduler_preview", "scheduler_run", "controller_preview", "controller_run"), True
        ):
            raise ProbeRefused("not all four installed execution entries refused")
        installation = installed_cli.parent.parent.resolve()
        for key in ("controller_module", "planning_module", "scheduler_module"):
            module = Path(evidence[key]).resolve()
            if installation not in module.parents:
                raise ProbeRefused(f"{key} escaped predecessor installation")
        if _sha256(path) != plan_hash_before or list(runtime.iterdir()) != [path]:
            raise ProbeRefused("disposable runtime was mutated during refusal checks")
        if _sha256(installed_cli) != exe_hash:
            raise ProbeRefused("installed executable fingerprint changed during probe")
        return {
            "schema": "stygnox_c2c_old_installed_execution_entry_refusal_v1",
            "installed_cli": str(installed_cli),
            "installed_cli_sha256": exe_hash,
            "fixture_type": "isolated_synthetic",
            "tested_status": STATUS,
            "fresh_process": True,
            "installed_entry_refusals": evidence["checks"],
            "module_paths": {key: evidence[key] for key in ("controller_module", "planning_module", "scheduler_module")},
            "controller_prerequisites_stubbed": True,
            "plan_fixture_unchanged": True,
            "provider_executed": False,
            "live_runtime_modified": False,
            "old_full_controller_scheduler_fenced": False,
            "exclusive_handoff_proved": False,
            "authority_changed": False,
            "handoff_admissible": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-installed-cli", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.old_installed_cli), indent=2, sort_keys=True))
    except (ProbeRefused, OSError, ValueError, KeyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
