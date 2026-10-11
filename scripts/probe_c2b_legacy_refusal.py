#!/usr/bin/env python3
"""Isolated fresh-process evidence of the installed predecessor's plan-status refusal.

This probe NEVER reads/writes the live .stygnox runtime, creates only a fresh
throwaway Git repository, and NEVER runs a provider.  It exercises the real
old installed package's planning admission function in a fresh interpreter.
It is deliberately NOT a full old CLI controller/scheduler fencing proof.
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


def probe(installed_cli: Path) -> dict:
    if not installed_cli.is_absolute() or installed_cli.is_symlink() or not installed_cli.is_file():
        raise RuntimeError("old installed executable must be an absolute regular non-symlink file")
    interpreter = installed_cli.parent / "python3"
    if not interpreter.is_file():
        raise RuntimeError("old installed Python interpreter not found beside executable")
    old_sha = hashlib.sha256(installed_cli.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="stygnox-c2b-old-refusal-") as temporary:
        root = Path(temporary)
        init = subprocess.run(["git", "init", "-q", str(root)], capture_output=True, text=True)
        if init.returncode:
            raise RuntimeError("failed to create isolated Git fixture: " + init.stderr)
        runtime = root / ".stygnox"
        runtime.mkdir()
        plan = {"schema": "stygnox_plan_state_v1", "status": STATUS,
                "execution_authority_granted": False, "operator": "c2b-probe",
                "transaction_id": "TX-c2b-fixture", "plan": None}
        plan["record_sha256"] = hashlib.sha256(json.dumps(
            plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()).hexdigest()
        (runtime / "plan.json").write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
        # Exercise the original installed launcher against only the synthetic
        # fixture. Its report must observe non-authority before the separate
        # fresh-interpreter planning admission check.
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        status = subprocess.run([str(installed_cli), "plan", "status", "--project", str(root)],
                                capture_output=True, text=True, cwd=root, env=env)
        if status.returncode:
            raise RuntimeError("original installed CLI cannot read fixture: " + (status.stdout + status.stderr)[-1000:])
        try:
            observed = json.loads(status.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("original installed CLI returned no structured plan status") from exc
        if (observed.get("plan", {}).get("status") != STATUS
            or observed.get("execution_authority_granted") is not False):
            raise RuntimeError("original installed CLI did not observe successor-only non-authority status")
        code = '''
import pathlib, sys, stygnox
from stygnox import planning
root = pathlib.Path(sys.argv[1])
try:
    planning.approved_step_context(root, "c2b-probe")
except planning.PlanningError as exc:
    if "unsupported active plan status" in str(exc) and "RECOVERY_SUCCESSOR_APPROVED_V1" in str(exc):
        print("FRESH_PROCESS_OLD_PLANNING_REFUSAL: PASS")
        print("INSTALLED_MODULE:", planning.__file__)
        sys.exit(0)
    print("INCONCLUSIVE: unexpected planning refusal:", exc)
    sys.exit(3)
print("FAIL: original controller planning admitted successor-only state")
sys.exit(4)
'''
        run = subprocess.run([str(interpreter), "-I", "-c", code, str(root)],
                             capture_output=True, text=True, cwd=root, env=env)
        # Ensure the probe ran the package from the original install, rather
        # than another globally installed Stygnox distribution.
        location = None
        for line in run.stdout.splitlines():
            if line.startswith("INSTALLED_MODULE: "):
                location = Path(line.partition(": ")[2]).resolve()
        if run.returncode != 0 or location is None or installed_cli.parent.parent.resolve() not in location.parents:
            raise RuntimeError("original installed package refusal not proved: " + (run.stdout + run.stderr)[-1000:])
        return {"schema": "stygnox_c2b_old_installed_planning_refusal_v1",
                "installed_cli": str(installed_cli), "installed_cli_sha256": old_sha,
                "installed_planning_module": str(location), "fixture_type": "isolated_synthetic",
                "tested_status": STATUS, "old_cli_plan_status_observed": True, "old_planning_refused": True,
                "old_full_controller_scheduler_fenced": False,
                "live_runtime_modified": False,
                "authority_changed": False, "handoff_admissible": False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old-installed-cli", type=Path, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(probe(args.old_installed_cli), indent=2, sort_keys=True))
    except (RuntimeError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
