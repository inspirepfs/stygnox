#!/usr/bin/env python3
"""Qualify D8.5 neutral authority/profile/controller policy from one wheel.

The qualifier builds and installs one exact Stygnox wheel, then exercises the
installed neutral profile, reviewed execution policy, controller activation,
and one-turn Codex provider path across new/unborn, clean, and dirty Git
fixtures.  A fake Codex executable records the exact selected model/effort and
sandbox without consuming a real model turn.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
from stygnox_qualification_artifact import provided_build_result, provided_wheel

SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qualify_d8_2_bootstrap import (  # type: ignore  # noqa: E402
    git,
    init_repo,
    installed_env,
    make_dirty,
    parse_json,
    run,
    sha256,
    tree_snapshot,
    venv_bin,
)
from qualify_d8_3_transactions import external_capture as d83_external_capture  # type: ignore  # noqa: E402

EXPECTED_VERSION = runpy.run_path(str(ROOT / "src" / "stygnox" / "_version.py"))["__version__"]
OPERATOR = "D8.5 Operator"
REVIEWER = "D8.5 Reviewer"
MODEL = "gpt-5.6-terra"
POLICY_ARGS = [
    "--provider", "codex",
    "--model", MODEL,
    "--effort", "high",
    "--reviewer", REVIEWER,
    "--efficiency-mode", "RELAXED",
    "--reserve-percent", "5",
    "--wait-for-limits",
    "--usage-poll-seconds", "60",
    "--max-loops", "1",
]


def cmd(stygnox: Path, fixture: Path, env: dict[str, str], *args: str, check: bool = True):
    return run([str(stygnox), *args], cwd=fixture, env=env, check=check)


def adopt(stygnox: Path, fixture: Path, env: dict[str, str], action: str, *args: str, reviewed: bool = False, check: bool = True):
    policy = POLICY_ARGS if reviewed else []
    return cmd(
        stygnox,
        fixture,
        env,
        "adopt",
        action,
        "--project",
        str(fixture),
        "--operator",
        OPERATOR,
        *policy,
        *args,
        check=check,
    )


def tx(stygnox: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True):
    return cmd(
        stygnox,
        fixture,
        env,
        "transaction",
        action,
        "--project",
        str(fixture),
        *( ["--operator", OPERATOR] if action in {"begin", "stop", "recover-preview", "restore"} else [] ),
        *args,
        check=check,
    )


def ctl(stygnox: Path, fixture: Path, env: dict[str, str], action: str, *args: str, check: bool = True):
    base = [str(stygnox), "controller", action, "--project", str(fixture)]
    if action in {"activate", "deactivate", "run-preview", "run"}:
        base += ["--operator", OPERATOR]
    return run([*base, *args], cwd=fixture, env=env, check=check)


def assert_neutral_profile(stygnox: Path, fixture: Path, env: dict[str, str]) -> dict:
    profile = parse_json(cmd(stygnox, fixture, env, "profile", "show"))
    expected = {
        "identity": "Stygnox",
        "name": "stygnox-default",
        "runtime_directory": ".stygnox",
        "controller_command": "stygnox controller",
        "artifact_namespace": "stygnox",
        "completion_commit_prefix": "chore(stygnox):",
    }
    for key, value in expected.items():
        if profile.get(key) != value:
            raise RuntimeError(f"neutral profile mismatch for {key}: {profile.get(key)!r}")
    rendered = json.dumps(profile, sort_keys=True).upper()
    for forbidden in ("RALPH", "ZEN CONTROL", "SCRIPTS/RALPH.PY", "CHORE(ZEN)"):
        if forbidden in rendered:
            raise RuntimeError(f"neutral installed profile leaked legacy identity: {forbidden}")
    if profile.get("host_adapter") is not None:
        raise RuntimeError("installed neutral profile unexpectedly selected a host adapter")
    return profile


def make_fake_codex(fakebin: Path, log: Path) -> Path:
    fakebin.mkdir(parents=True, exist_ok=True)
    path = fakebin / "codex"
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args=sys.argv[1:]\n"
        "log=Path(os.environ['STYGNOX_FAKE_CODEX_LOG'])\n"
        "with log.open('a', encoding='utf-8') as f: f.write(json.dumps(args)+'\\n')\n"
        "if args and args[0]=='sandbox': raise SystemExit(0)\n"
        "if not args or args[0] != 'exec': raise SystemExit(64)\n"
        "try: out=Path(args[args.index('-o')+1])\n"
        "except Exception: raise SystemExit(65)\n"
        "out.write_text(json.dumps({'status':'PASS','summary':'D8.5 fake provider turn complete'}), encoding='utf-8')\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def assert_fake_invocation(log: Path, *, minimum_execs: int) -> int:
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    execs = [row for row in rows if row and row[0] == "exec"]
    if len(execs) < minimum_execs:
        raise RuntimeError(f"expected at least {minimum_execs} fake Codex exec invocations, got {len(execs)}")
    for args in execs:
        if "--model" not in args or args[args.index("--model") + 1] != MODEL:
            raise RuntimeError(f"controller did not invoke reviewed model: {args}")
        if "--config" not in args or args[args.index("--config") + 1] != 'model_reasoning_effort="high"':
            raise RuntimeError(f"controller did not invoke reviewed effort: {args}")
        if "--sandbox" not in args or args[args.index("--sandbox") + 1] != "read-only":
            raise RuntimeError(f"qualification controller run was not read-only: {args}")
    return len(execs)


def handoff_and_begin(
    stygnox: Path,
    fixture: Path,
    env: dict[str, str],
    *,
    reviewed: bool,
    evidence_root: Path | None = None,
) -> dict:
    initial = parse_json(adopt(stygnox, fixture, env, "preview", reviewed=reviewed))
    evidence: Path | None = None
    if initial["baseline"]["journey"] == "dirty":
        if initial["admissible"]:
            raise RuntimeError("dirty D8.5 fixture admitted without external recovery evidence")
        if evidence_root is None:
            raise RuntimeError("dirty D8.5 fixture requires evidence root")
        evidence = d83_external_capture(fixture, initial, evidence_root)
        preview = parse_json(
            adopt(
                stygnox,
                fixture,
                env,
                "preview",
                "--dirty-recovery-evidence",
                str(evidence),
                reviewed=reviewed,
            )
        )
    else:
        preview = initial
    if not preview["admissible"]:
        raise RuntimeError(f"D8.5 adoption unexpectedly refused: {preview}")
    args = ["--preview", preview["preview_sha256"], "--confirm", "HANDOFF"]
    if evidence is not None:
        args = ["--dirty-recovery-evidence", str(evidence), *args]
    handoff = parse_json(adopt(stygnox, fixture, env, "handoff", *args, reviewed=reviewed))
    if handoff.get("controller_execution") is not False:
        raise RuntimeError("adoption handoff must remain controller-execution=false before D8.5 activation")
    begun = parse_json(tx(stygnox, fixture, env, "begin", "--confirm", "BEGIN"))
    if begun.get("state") != "ACTIVE":
        raise RuntimeError("D8.5 transaction did not become ACTIVE")
    active = parse_json(ctl(stygnox, fixture, env, "activate", "--confirm", "ACTIVATE"))
    if active.get("controller_execution_enabled") is not True:
        raise RuntimeError("D8.5 controller activation did not enable installed controller execution")
    if active.get("profile", {}).get("identity") != "Stygnox":
        raise RuntimeError("D8.5 activated controller identity is not neutral Stygnox")
    return {"preview": preview, "handoff": handoff, "transaction": begun, "controller": active}


def run_read_only_turn(stygnox: Path, fixture: Path, env: dict[str, str], objective: str) -> dict:
    before = tree_snapshot(fixture)
    preview = parse_json(
        ctl(
            stygnox,
            fixture,
            env,
            "run-preview",
            "--objective",
            objective,
            "--repository-authority",
            "read-only",
        )
    )
    result = parse_json(
        ctl(
            stygnox,
            fixture,
            env,
            "run",
            "--objective",
            objective,
            "--repository-authority",
            "read-only",
            "--preview",
            preview["preview_sha256"],
            "--confirm",
            "RUN",
        )
    )
    if result.get("controller_execution_enabled") is not True or result.get("project_changed") is not False:
        raise RuntimeError("D8.5 read-only provider turn did not preserve project baseline")
    # Runtime evidence is expected to change; compare Git-visible project state only.
    status = git(fixture, "status", "--porcelain=v1", "--untracked-files=all").stdout
    if ".stygnox" in status:
        raise RuntimeError("D8.5 controller runtime leaked into native Git delta")
    return {"preview_sha256": preview["preview_sha256"], "result": "PASS", "provider": result["provider_result"]}


def qualify_new(stygnox: Path, fixture: Path, env: dict[str, str]) -> dict:
    assert_neutral_profile(stygnox, fixture, env)
    state = handoff_and_begin(stygnox, fixture, env, reviewed=False)
    if state["controller"].get("provider_execution_ready") is not False:
        raise RuntimeError("neutral D8.5 policy unexpectedly enabled provider execution")
    refused = ctl(
        stygnox,
        fixture,
        env,
        "run-preview",
        "--objective",
        "Inspect the project",
        "--repository-authority",
        "read-only",
        check=False,
    )
    if refused.returncode == 0 or "defaults are neutral" not in refused.stderr:
        raise RuntimeError("neutral provider/model/effort did not refuse provider execution")
    status = parse_json(ctl(stygnox, fixture, env, "status"))
    if status.get("controller_execution_enabled") is not True:
        raise RuntimeError("new/unborn installed controller status is not active")
    return {
        "fixture": "new-unborn",
        "identity": status["profile"]["identity"],
        "controller_execution_enabled": True,
        "provider_execution": "REFUSED_NEUTRAL_DEFAULTS",
        "provider": None,
        "model": None,
        "effort": None,
    }


def qualify_clean(stygnox: Path, fixture: Path, env: dict[str, str]) -> dict:
    assert_neutral_profile(stygnox, fixture, env)
    before = tree_snapshot(fixture)
    unreviewed = adopt(
        stygnox,
        fixture,
        env,
        "preview",
        "--provider",
        "codex",
        "--model",
        MODEL,
        "--effort",
        "high",
        check=False,
    )
    if unreviewed.returncode == 0 or "reviewer" not in unreviewed.stderr.lower():
        raise RuntimeError("unreviewed model/effort selection was not refused")
    if tree_snapshot(fixture) != before:
        raise RuntimeError("unreviewed override refusal mutated clean fixture")

    reviewed_preview = parse_json(adopt(stygnox, fixture, env, "preview", reviewed=True))
    changed = adopt(
        stygnox,
        fixture,
        env,
        "handoff",
        "--preview",
        reviewed_preview["preview_sha256"],
        "--confirm",
        "HANDOFF",
        "--provider",
        "codex",
        "--model",
        "gpt-different",
        "--effort",
        "high",
        "--reviewer",
        REVIEWER,
        check=False,
    )
    if changed.returncode == 0 or "preview is stale" not in changed.stderr:
        raise RuntimeError("changed reviewed override did not invalidate adoption confirmation")
    state = handoff_and_begin(stygnox, fixture, env, reviewed=True)
    if state["controller"].get("provider_execution_ready") is not True:
        raise RuntimeError("reviewed D8.5 provider policy did not become execution-ready")
    turn = run_read_only_turn(stygnox, fixture, env, "Inspect the clean fixture and make no changes")
    return {
        "fixture": "clean",
        "identity": state["controller"]["profile"]["identity"],
        "reviewer": state["controller"]["execution_policy_review"]["reviewer"],
        "provider": state["controller"]["execution_policy"]["provider"],
        "model": state["controller"]["execution_policy"]["model"],
        "effort": state["controller"]["execution_policy"]["effort"],
        "controller_execution_enabled": True,
        "provider_turn": turn,
        "unreviewed_override_refusal": "PASS",
        "changed_override_reconfirmation": "PASS",
    }


def qualify_dirty(stygnox: Path, fixture: Path, env: dict[str, str], evidence_root: Path) -> dict:
    assert_neutral_profile(stygnox, fixture, env)
    state = handoff_and_begin(stygnox, fixture, env, reviewed=True, evidence_root=evidence_root)
    turn = run_read_only_turn(stygnox, fixture, env, "Inspect the dirty fixture and preserve all operator material")
    categories = state["preview"]["baseline"]["dirty_categories"]
    required = {"staged", "unstaged", "renamed", "deleted", "untracked"}
    if not required.issubset(set(categories)):
        raise RuntimeError(f"dirty D8.5 fixture misses expected categories: {categories}")
    return {
        "fixture": "dirty",
        "identity": state["controller"]["profile"]["identity"],
        "dirty_categories": categories,
        "controller_execution_enabled": True,
        "provider_turn": turn,
        "operator_material_preserved": "PASS",
    }


def qualify_policy_set_reset(stygnox: Path, fixture: Path, env: dict[str, str]) -> dict:
    preview = parse_json(adopt(stygnox, fixture, env, "preview"))
    parse_json(adopt(stygnox, fixture, env, "handoff", "--preview", preview["preview_sha256"], "--confirm", "HANDOFF"))
    show = parse_json(cmd(stygnox, fixture, env, "execution-policy", "show", "--project", str(fixture)))
    if any(show["policy"].get(key) for key in ("provider", "model", "effort")):
        raise RuntimeError("execution-policy show did not start neutral")
    set_preview = parse_json(
        cmd(
            stygnox,
            fixture,
            env,
            "execution-policy",
            "preview",
            "--project",
            str(fixture),
            "--operator",
            OPERATOR,
            *POLICY_ARGS,
        )
    )
    stale = cmd(
        stygnox,
        fixture,
        env,
        "execution-policy",
        "set",
        "--project",
        str(fixture),
        "--operator",
        OPERATOR,
        "--preview",
        set_preview["preview_sha256"],
        "--confirm",
        "SET",
        "--provider",
        "codex",
        "--model",
        MODEL,
        "--effort",
        "high",
        "--reviewer",
        REVIEWER,
        "--reserve-percent",
        "9",
        check=False,
    )
    if stale.returncode == 0 or "stale" not in stale.stderr.lower():
        raise RuntimeError("changed execution-policy set did not invalidate confirmation")
    parse_json(
        cmd(
            stygnox,
            fixture,
            env,
            "execution-policy",
            "set",
            "--project",
            str(fixture),
            "--operator",
            OPERATOR,
            "--preview",
            set_preview["preview_sha256"],
            "--confirm",
            "SET",
            *POLICY_ARGS,
        )
    )
    selected = parse_json(cmd(stygnox, fixture, env, "execution-policy", "show", "--project", str(fixture)))
    if not selected.get("approved") or selected["policy"].get("model") != MODEL:
        raise RuntimeError("reviewed execution-policy set was not effective")
    reset_preview = parse_json(
        cmd(
            stygnox,
            fixture,
            env,
            "execution-policy",
            "preview",
            "--project",
            str(fixture),
            "--operator",
            OPERATOR,
            "--reset",
        )
    )
    parse_json(
        cmd(
            stygnox,
            fixture,
            env,
            "execution-policy",
            "reset",
            "--project",
            str(fixture),
            "--operator",
            OPERATOR,
            "--preview",
            reset_preview["preview_sha256"],
            "--confirm",
            "RESET",
        )
    )
    neutral = parse_json(cmd(stygnox, fixture, env, "execution-policy", "show", "--project", str(fixture)))
    if any(neutral["policy"].get(key) for key in ("provider", "model", "effort")):
        raise RuntimeError("execution-policy reset did not restore neutral defaults")
    return {
        "fixture": "policy-set-reset",
        "atomic_set": "PASS",
        "changed_confirmation_refusal": "PASS",
        "reset_to_neutral": "PASS",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="stygnox-d85-qualification-") as temp:
        work = Path(temp)
        dist = args.output_dir.expanduser().resolve() if args.output_dir else work / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        if args.output_dir and any(dist.iterdir()):
            raise SystemExit(f"refusing non-empty --output-dir: {dist}")
        wheel = provided_wheel()
        if wheel is None:
            build = run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--disable-pip-version-check",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(dist),
                    ".",
                ],
                cwd=ROOT,
            )
            wheels = sorted(dist.glob("stygnox-*.whl"))
            if len(wheels) != 1:
                raise RuntimeError(f"expected one Stygnox wheel, found: {wheels}")
            wheel = wheels[0]
        else:
            build = provided_build_result(wheel)

        environment = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = venv_bin(environment, "python")
        install = run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(wheel)], cwd=work)
        stygnox = venv_bin(environment, "stygnox")
        if not stygnox.is_file():
            raise RuntimeError("installed stygnox executable missing")

        hostile = work / "hostile-pythonpath"
        hostile.mkdir()
        legacy_sentinel = work / "LEGACY_IMPORT_EXECUTED"
        legacy_payload = (
            "from pathlib import Path\n"
            f"Path({str(legacy_sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            "raise RuntimeError('legacy decoy imported')\n"
        )
        (hostile / "ralph.py").write_text(legacy_payload, encoding="utf-8")
        (hostile / "ralph_profile.py").write_text(legacy_payload, encoding="utf-8")
        env = installed_env(environment, hostile)
        fakebin = work / "fakebin"
        provider_log = work / "fake-codex.jsonl"
        make_fake_codex(fakebin, provider_log)
        env["PATH"] = os.pathsep.join((str(fakebin), env["PATH"]))
        env["STYGNOX_FAKE_CODEX_LOG"] = str(provider_log)

        fixtures = work / "fixtures"
        new = fixtures / "new-unborn"
        clean = fixtures / "clean"
        dirty = fixtures / "dirty"
        policy_fixture = fixtures / "policy"
        init_repo(new, commit=False, decoy=False)
        clean_sentinel = init_repo(clean, commit=True, decoy=True)
        dirty_sentinel = init_repo(dirty, commit=True, decoy=True)
        init_repo(policy_fixture, commit=True, decoy=False)
        assert clean_sentinel is not None and dirty_sentinel is not None
        make_dirty(dirty)

        results = [
            qualify_new(stygnox, new, env),
            qualify_clean(stygnox, clean, env),
            qualify_dirty(stygnox, dirty, env, work / "dirty-evidence"),
            qualify_policy_set_reset(stygnox, policy_fixture, env),
        ]
        if clean_sentinel.exists() or dirty_sentinel.exists() or legacy_sentinel.exists():
            raise RuntimeError("legacy/source-tree controller decoy executed during D8.5 qualification")
        exec_count = assert_fake_invocation(provider_log, minimum_execs=2)
        version = run([str(stygnox), "--version"], cwd=work, env=env).stdout.strip()
        if version != f"stygnox {EXPECTED_VERSION}":
            raise RuntimeError(f"installed version mismatch: {version}")

        evidence = {
            "schema": "stygnox_d8_5_controller_qualification_v1",
            "version": EXPECTED_VERSION,
            "wheel": wheel.name,
            "wheel_sha256": sha256(wheel),
            "profile": "stygnox-default",
            "runtime_directory": ".stygnox",
            "controller_command": "stygnox controller",
            "controller_execution_enabled": True,
            "neutral_defaults": "PASS",
            "reviewed_override_gate": "PASS",
            "override_reconfirmation": "PASS",
            "execution_policy_show_set_reset": "PASS",
            "installed_controller_invocation": "PASS",
            "provider_adapter": "codex",
            "provider_exec_invocations": exec_count,
            "legacy_source_fallback": "REFUSED",
            "fixtures": results,
            "next_stage": "D8.6 external Web/TUI, carry-forward/adoption, and operator UX",
        }
        rendered = json.dumps(evidence, indent=2, sort_keys=True)
        if args.output_dir:
            (dist / "qualification.json").write_text(rendered + "\n", encoding="utf-8")
        print("D8.5 NEUTRAL AUTHORITY / CONTROLLER / EXECUTION POLICY QUALIFICATION PASS")
        print(rendered)
        print("\nBUILD TRANSCRIPT")
        print(build.stdout.rstrip())
        print("\nINSTALL TRANSCRIPT")
        print((install.stdout + install.stderr).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
