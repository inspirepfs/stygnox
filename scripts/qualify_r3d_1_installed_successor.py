#!/usr/bin/env python3
"""Qualify R3D.1 successor handoff from one freshly installed exact wheel."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import venv
import zipfile

VERSION = "0.1.0"
SCHEMA = "stygnox_r3d_1_installed_successor_qualification_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(argv: list[str], *, cwd: Path, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stderr or result.stdout}")
    return result


def decoded(value: str) -> dict[str, object]:
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("installed command did not return JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("installed command did not return an object")
    return result


# The installed interpreter creates a deterministic accepted held-step fixture.
# It deliberately carries no CAP-011 provider or executable authority.
FIXTURE = r'''
import json, subprocess, sys, zipfile
from pathlib import Path
from stygnox import adoption, controller, lifecycle, planning, transactions
root, wheel, command = map(Path, sys.argv[1:4]); root.mkdir()
def git(*args): subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.DEVNULL)
git("init", "-q"); git("config", "user.name", "Qualifier"); git("config", "user.email", "qualifier@example.invalid")
(root / ".gitignore").write_text("/.stygnox/\n"); (root / "README.md").write_text("fixture\n")
(root / "stygnox.toml").write_text("schema = 'stygnox_project_config_v1'\n"); (root / "stygnox.policy.md").write_text("# bootstrap\n")
with zipfile.ZipFile(wheel) as archive:
 for name in archive.namelist():
  if name.startswith("stygnox/") and not name.endswith("/"):
   target=root / "src" / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(archive.read(name))
git("add", "."); git("commit", "-q", "-m", "baseline")
baseline=adoption.capture_baseline(root).public(); digest=lifecycle._digest
installed=lifecycle._installed_identity(root); artifact=lifecycle._wheel_identity(wheel, installed)
tx={"schema":transactions.TRANSACTION_SCHEMA,"product_version":lifecycle.PRODUCT.version,"transaction_id":"R3D1-predecessor","state":"ACTIVE","operator":"Qualifier","authority_baseline_sha256":baseline["sha256"]}; tx["record_sha256"]=digest(tx)
ctrl={"schema":controller.CONTROLLER_SCHEMA,"product_version":lifecycle.PRODUCT.version,"enabled":True,"controller_execution_enabled":True,"operator":"Qualifier","transaction_id":tx["transaction_id"],"authority_baseline_sha256":baseline["sha256"],"installed_command":installed["executable"]}; ctrl["record_sha256"]=digest(ctrl)
scope=["README.md"]
final={"state":"PASS","repository_baseline_sha256":baseline["sha256"],"repository_mutation_scope_sha256":digest(scope),"accepted_controller_attribution":{"attribution_sha256":"a"*64}}; final["provenance_sha256"]=digest(final)
step={"id":1,"title":"Installed successor","objective":"Qualify successor","acceptance":["fresh handoff"],"test_change_policy":"add-only",planning.POST_QUALIFICATION_TRANSITION_FIELD:planning.INSTALLED_SUCCESSOR_HANDOFF}
plan={"goal":"fixture","planning":{"min_steps":1,"max_steps":1},"steps":[step],"repository_authority":"write","repository_mutation_scope":scope,"repository_mutation_scope_sha256":digest(scope)}; plan_hash=planning._digest(plan)
binding="b"*64; transition={"schema":"stygnox_post_qualification_transition_v1","kind":planning.INSTALLED_SUCCESSOR_HANDOFF,"state":"PENDING","plan_hash":plan_hash,"plan_step":1,"qualification_binding_sha256":binding,"qualified_baseline_sha256":baseline["sha256"],"plan_record_sha256":"c"*64,"controller_record_sha256":ctrl["record_sha256"],"transaction_id":tx["transaction_id"],"transaction_record_sha256":tx["record_sha256"]}
state={"schema":planning.PLAN_SCHEMA,"product_version":lifecycle.PRODUCT.version,"status":"APPROVED","operator":"Qualifier","plan":plan,"plan_hash":plan_hash,"current_step":1,"repository_mutation_scope":scope,"repository_mutation_scope_sha256":digest(scope),"transaction_id":tx["transaction_id"],"transaction_record_sha256":tx["record_sha256"],"controller_record_sha256":ctrl["record_sha256"],"execution_authority_granted":False,"step_results":[{"step":1,"result":"PASS","qualification_binding_sha256":binding,"post_qualification_transition":transition}],"final_qualification":final}; state["record_sha256"]=digest(state)
adopt={"schema":adoption.HANDOFF_SCHEMA,"product_version":lifecycle.PRODUCT.version,"operator":"Qualifier","baseline":baseline,"authority_baseline":baseline,"baseline_sha256":baseline["sha256"],"journey":"clean","recovery_source":{"kind":"fixture"},"preview_sha256":"d"*64,"command":{"executable":installed["executable"]}}
for name,value in (("adoption.json",adopt),(transactions.TRANSACTION_RECORD,tx),(controller.CONTROLLER_RECORD,ctrl),(planning.PLAN_RECORD,state)): adoption.write_runtime_record(root,name,value,actor="controller")
# The pending handoff is created from an adopted ACTIVE fixture, then the
# installed command performs the required safe stop before the preview.  The
# pending plan state records that exact stopped predecessor identity.
subprocess.run([str(command), "transaction", "stop", "--project", str(root), "--operator", "Qualifier", "--reason", "qualification", "--confirm", "STOP"], check=True, stdout=subprocess.DEVNULL)
stopped=json.loads((root / ".stygnox" / transactions.TRANSACTION_RECORD).read_text())
state=json.loads((root / ".stygnox" / planning.PLAN_RECORD).read_text())
state["transaction_record_sha256"]=stopped["record_sha256"]
state["step_results"][0]["post_qualification_transition"]["transaction_record_sha256"]=stopped["record_sha256"]
state.pop("record_sha256",None); state["record_sha256"]=digest(state)
adoption.write_runtime_record(root,planning.PLAN_RECORD,state,actor="controller")
print(json.dumps({"worktree":str(root),"installed_identity":installed,"candidate_artifact":artifact},sort_keys=True))
'''


def environment(venv_dir: Path) -> tuple[Path, Path, dict[str, str]]:
    command = venv_dir / "bin" / "stygnox"
    return venv_dir / "bin" / "python", command, {"PATH": str(command.parent), "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}


def fixture(python: Path, wheel: Path, root: Path, env: dict[str, str]) -> dict[str, object]:
    command = root.parent / "venv" / "bin" / "stygnox"
    return decoded(run([str(python), "-c", FIXTURE, str(root), str(wheel), str(command)], cwd=root.parent, env=env).stdout)


def records(root: Path) -> dict[str, str]:
    return {name: sha256(root / ".stygnox" / name) for name in ("transaction.json", "controller.json", "plan.json")}


def preview(command: Path, case: dict[str, object], wheel: Path, env: dict[str, str]) -> dict[str, object]:
    return decoded(run([str(command), "upgrade", "rebind-preview", "--project", str(case["worktree"]), "--operator", "Qualifier", "--wheel", str(wheel)], cwd=command.parent, env=env).stdout)


def must_refuse(name: str, argv: list[str], root: Path, cwd: Path, env: dict[str, str]) -> dict[str, object]:
    before = records(root); result = run(argv, cwd=cwd, env=env, check=False)
    if result.returncode == 0 or records(root) != before:
        raise RuntimeError(f"{name} did not fail closed with predecessor authority retained")
    return {"result": "REFUSED_PREDECESSOR_RETAINED", "returncode": result.returncode}


def qualify(wheel: Path) -> dict[str, object]:
    wheel = wheel.resolve()
    if wheel.is_symlink() or not wheel.is_file() or wheel.suffix != ".whl":
        raise RuntimeError("qualification requires one regular Stygnox wheel")
    with tempfile.TemporaryDirectory(prefix="stygnox-r3d1-installed-") as directory:
        temp = Path(directory); venv_dir = temp / "venv"; venv.EnvBuilder(with_pip=True).create(venv_dir)
        python, command, env = environment(venv_dir)
        # The rebind child deliberately receives only this directory on PATH.
        # Provide the system Git executable there so its baseline verification
        # remains available without admitting the source checkout or a decoy.
        system_git = shutil.which("git")
        if system_git is None:
            raise RuntimeError("installed-successor qualification requires git")
        (command.parent / "git").symlink_to(system_git)
        run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)], cwd=temp, env=env)
        normal = fixture(python, wheel, temp / "normal", env); handoff_preview = preview(command, normal, wheel, env)
        if handoff_preview.get("admissible") is not True:
            raise RuntimeError(f"installed fixture is inadmissible: {handoff_preview.get('blockers')}")
        receipt = decoded(run([str(command), "upgrade", "rebind", "--project", str(normal["worktree"]), "--operator", "Qualifier", "--wheel", str(wheel), "--preview", str(handoff_preview["preview_sha256"]), "--confirm", "REBIND"], cwd=command.parent, env=env).stdout)
        root = Path(str(normal["worktree"])); plan = json.loads((root / ".stygnox" / "plan.json").read_text())
        if receipt.get("result") != "REBIND_COMPLETED_BY_FRESH_INSTALLED_PROCESS" or plan.get("current_step") != 2 or plan.get("execution_authority_granted") is not True:
            raise RuntimeError("fresh successor did not become live before later work opened")
        hostile: dict[str, dict[str, object]] = {}
        for name in (
            "pythonpath_ralph_decoy",
            "copied_launcher",
            "source_tree_substitution",
            "stale_or_substituted_artifact",
            "failing_handoff",
        ):
            case = fixture(python, wheel, temp / name, env)
            case_root = Path(str(case["worktree"]))
            case_wheel = wheel
            if name == "stale_or_substituted_artifact":
                case_wheel = temp / f"{name}.whl"
                shutil.copy2(wheel, case_wheel)
            candidate_preview = preview(command, case, case_wheel, env)
            if candidate_preview.get("admissible") is not True:
                raise RuntimeError(f"{name} fixture unexpectedly inadmissible before hostile mutation: {candidate_preview.get('blockers')}")
            if name == "pythonpath_ralph_decoy":
                decoy = temp / "decoy" / "stygnox"
                decoy.mkdir(parents=True)
                (decoy / "__init__.py").write_text("raise RuntimeError('Ralph decoy')\n")
                argv = [str(command), "upgrade", "rebind", "--project", str(case_root), "--operator", "Qualifier", "--wheel", str(case_wheel), "--preview", str(candidate_preview["preview_sha256"]), "--confirm", "REBIND"]
                case_env = {**env, "PYTHONPATH": str(decoy.parent)}
            elif name == "copied_launcher":
                copied = temp / "copied-stygnox"
                shutil.copy2(command, copied)
                copied.chmod(0o755)
                argv = [str(copied), "upgrade", "rebind", "--project", str(case_root), "--operator", "Qualifier", "--wheel", str(case_wheel), "--preview", str(candidate_preview["preview_sha256"]), "--confirm", "REBIND"]
                case_env = env
            elif name == "source_tree_substitution":
                source = case_root / "src" / "stygnox" / "lifecycle.py"
                source.write_bytes(source.read_bytes() + b"\n# hostile source substitution\n")
                argv = [str(command), "upgrade", "rebind", "--project", str(case_root), "--operator", "Qualifier", "--wheel", str(case_wheel), "--preview", str(candidate_preview["preview_sha256"]), "--confirm", "REBIND"]
                case_env = env
            elif name == "stale_or_substituted_artifact":
                case_wheel.write_bytes(case_wheel.read_bytes() + b"substituted")
                argv = [str(command), "upgrade", "rebind", "--project", str(case_root), "--operator", "Qualifier", "--wheel", str(case_wheel), "--preview", str(candidate_preview["preview_sha256"]), "--confirm", "REBIND"]
                case_env = env
            else:
                argv = [str(command), "upgrade", "rebind", "--project", str(case_root), "--operator", "Qualifier", "--wheel", str(case_wheel), "--preview", "0" * 64, "--confirm", "REBIND"]
                case_env = env
            hostile[name] = must_refuse(name, argv, case_root, command.parent, case_env)
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "wheel_sha256": sha256(wheel),
            "installed_successor": {
                "result": "PASS",
                "wheel": receipt["candidate_artifact"],
                "installed_identity": receipt["installed_identity"],
                "canonical_worktree": str(root),
                "plan_scope_provenance_checkpoint_lineage": receipt["successor_binding"],
                "transaction": receipt["successor_transaction"],
                "controller": receipt["successor_controller"],
                "runtime_epoch": receipt["new_runtime_epoch"],
                "bootstrap_disposition": receipt["bootstrap_disposition"],
                "source_tree_fallback": receipt["source_tree_fallback"],
                "ralph_fallback": receipt["ralph_fallback"],
                "successor_receipt_sha256": receipt["record_sha256"],
            },
            "hostile_cases": hostile,
            "cap_011": {"provider_owned": False, "executable_authority": False},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=os.environ.get("STYGNOX_QUALIFICATION_WHEEL"))
    args = parser.parse_args()
    if args.wheel is None:
        raise SystemExit("--wheel or STYGNOX_QUALIFICATION_WHEEL is required")
    print(json.dumps(qualify(args.wheel), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
