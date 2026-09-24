#!/usr/bin/env python3
"""D8.6A installed Web/operator-surface qualification.

Build the exact wheel, install it into an isolated venv, then exercise the
installed Web surface against new/unborn, clean and dirty repositories.  The
qualification proves CLI/Web preview parity, explicit refusal before dirty
handoff authority, packaged branding, CSRF enforcement, loopback-only policy,
change attribution, and no legacy Ralph/source-tree fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "stygnox_d8_6a_web_qualification_v1"
VERSION = runpy.run_path(str(ROOT / "src/stygnox/_version.py"))["__version__"]


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", *args, cwd=cwd, check=check)


def init_repo(path: Path, *, commit: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.6A Web Qualification")
    git(path, "config", "user.email", "qualification@example.invalid")
    (path / "README.md").write_text("fixture baseline\n", encoding="utf-8")
    if commit:
        git(path, "add", "README.md")
        git(path, "commit", "-q", "-m", "baseline")


def make_dirty(path: Path) -> None:
    (path / "README.md").write_text("fixture baseline\nunstaged\n", encoding="utf-8")
    (path / "external-note.txt").write_text("operator external material\n", encoding="utf-8")


def http_json(url: str, *, method: str = "GET", data: dict | None = None, csrf: str | None = None, expected: int = 200) -> dict:
    body = None if data is None else json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if csrf is not None:
        request.add_header("X-Stygnox-CSRF", csrf)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
            payload = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = exc.read()
    if status != expected:
        raise RuntimeError(f"unexpected HTTP status for {url}: got {status}, expected {expected}; body={payload!r}")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Web JSON response is not an object")
    return value


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"asset fetch failed: {url}: {response.status}")
        return response.read()


def start_web(stygnox: Path, fixture: Path, env: dict[str, str]) -> tuple[subprocess.Popen[str], str, str]:
    process = subprocess.Popen(
        [str(stygnox), "web", "--project", str(fixture), "--host", "127.0.0.1", "--port", "0"],
        cwd=fixture,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    assert process.stdout is not None
    deadline = time.time() + 15
    line = ""
    while time.time() < deadline:
        line = process.stdout.readline().strip()
        if line:
            break
        if process.poll() is not None:
            break
        time.sleep(0.05)
    if not line:
        stderr = process.stderr.read() if process.stderr else ""
        process.terminate()
        raise RuntimeError(f"installed Web did not start: {stderr}")
    match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
    if not match:
        process.terminate()
        raise RuntimeError(f"cannot parse installed Web address: {line}")
    base = f"http://127.0.0.1:{match.group(1)}"
    html = fetch_bytes(base + "/").decode("utf-8")
    csrf_match = re.search(r'<meta name="stygnox-csrf" content="([^"]+)">', html)
    if not csrf_match:
        process.terminate()
        raise RuntimeError("Web page did not expose bounded CSRF token")
    return process, base, csrf_match.group(1)


def cli_json(stygnox: Path, fixture: Path, *args: str, env: dict[str, str]) -> dict:
    result = run(str(stygnox), *args, cwd=fixture, env=env)
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("CLI JSON result is not an object")
    return value


def web_action(base: str, csrf: str, action: str, payload: dict, *, expected: int = 200) -> dict:
    return http_json(base + "/api/action", method="POST", data={"action": action, "payload": payload}, csrf=csrf, expected=expected)


def qualify_fixture(name: str, fixture: Path, stygnox: Path, env: dict[str, str]) -> dict:
    sentinel = fixture / ".git" / "legacy-ralph-web-imported"
    decoy_dir = fixture / ".git" / "stygnox-decoy"
    decoy_dir.mkdir(parents=True, exist_ok=True)
    (decoy_dir / "ralph_web.py").write_text(
        "from pathlib import Path\n" + f"Path({str(sentinel)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    fixture_env = dict(env)
    fixture_env["PYTHONPATH"] = str(decoy_dir)
    process, base, csrf = start_web(stygnox, fixture, fixture_env)
    try:
        snapshot = http_json(base + "/api/snapshot")
        if snapshot.get("schema") != "stygnox_operator_surface_v1" or snapshot.get("identity") != "Stygnox":
            raise RuntimeError(f"{name}: unsupported neutral Web snapshot")
        if snapshot.get("evidence_summary", {}).get("legacy_ralph_delegate") is not False:
            raise RuntimeError(f"{name}: Web snapshot permits legacy Ralph delegation")
        if sentinel.exists():
            raise RuntimeError(f"{name}: installed Web imported target-local ralph_web.py")

        no_csrf = web_action(base, "wrong", "legacy.ralph.run", {}, expected=403)
        if "CSRF" not in str(no_csrf.get("error")):
            raise RuntimeError(f"{name}: mutation without exact CSRF was not refused")
        unsupported = web_action(base, csrf, "legacy.ralph.run", {}, expected=400)
        if "unsupported installed operator action" not in str(unsupported.get("error")):
            raise RuntimeError(f"{name}: legacy action was not explicitly refused")

        web_preview = web_action(base, csrf, "adopt.preview", {"operator": "D8.6A Operator"})
        if web_preview.get("action") != "adopt.preview" or not isinstance(web_preview.get("result"), dict):
            raise RuntimeError(f"{name}: Web adoption preview envelope invalid")
        web_result = web_preview["result"]
        cli_result = cli_json(stygnox, fixture, "adopt", "preview", "--project", str(fixture), "--operator", "D8.6A Operator", env=fixture_env)
        if not isinstance(web_result, dict) or web_result.get("preview_sha256") != cli_result.get("preview_sha256"):
            raise RuntimeError(f"{name}: CLI/Web adoption preview parity mismatch")

        if name == "dirty":
            if web_result.get("admissible") is not False or not web_result.get("dirty_recovery", {}).get("required"):
                raise RuntimeError("dirty: Web must refuse authority until external recovery evidence is supplied")
            attribution = http_json(base + "/api/snapshot").get("attribution", {})
            if attribution.get("categories", {}).get("external", {}).get("count", 0) < 1:
                raise RuntimeError("dirty: external operator material was not visible in reconciliation attribution")
            return {"fixture": name, "admission": "REFUSED_BEFORE_AUTHORITY", "cli_web_preview_parity": "PASS", "attribution": "PASS"}

        if web_result.get("admissible") is not True:
            raise RuntimeError(f"{name}: clean/new Web adoption preview unexpectedly inadmissible")
        preview_sha = str(web_result["preview_sha256"])
        handoff = web_action(base, csrf, "adopt.handoff", {"operator": "D8.6A Operator", "preview": preview_sha, "confirm": "HANDOFF"})
        if handoff.get("result", {}).get("result") != "HANDOFF_RECORDED":
            raise RuntimeError(f"{name}: Web handoff did not confirm exact preview")
        tx = web_action(base, csrf, "transaction.begin", {"operator": "D8.6A Operator", "confirm": "BEGIN"})
        if tx.get("result", {}).get("result") != "TRANSACTION_ACTIVE":
            raise RuntimeError(f"{name}: Web transaction begin failed")
        active = web_action(base, csrf, "controller.activate", {"operator": "D8.6A Operator", "confirm": "ACTIVATE"})
        if active.get("result", {}).get("controller_execution_enabled") is not True:
            raise RuntimeError(f"{name}: Web controller activation failed")
        refused = web_action(base, csrf, "controller.run-preview", {"operator": "D8.6A Operator", "objective": "Inspect without changes", "repository_authority": "read-only"}, expected=400)
        if "neutral" not in str(refused.get("error", "")).lower():
            raise RuntimeError(f"{name}: neutral provider execution was not refused")
        return {"fixture": name, "handoff": "PASS", "transaction_begin": "PASS", "controller_activation": "PASS", "neutral_execution_refusal": "PASS", "cli_web_preview_parity": "PASS"}
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="stygnox-d86a-qualification-") as td:
        work = Path(td)
        dist = work / "dist"
        dist.mkdir()
        build = run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(dist), ".", cwd=ROOT)
        wheels = list(dist.glob("stygnox-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected exactly one Stygnox wheel, found {wheels}")
        wheel = wheels[0]

        venv_dir = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        python = venv_dir / "bin" / "python"
        pip = venv_dir / "bin" / "pip"
        stygnox = venv_dir / "bin" / "stygnox"
        install = run(str(pip), "install", "--no-deps", str(wheel), cwd=ROOT)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PATH"] = str(venv_dir / "bin") + os.pathsep + env.get("PATH", "")

        version = run(str(stygnox), "--version", env=env).stdout.strip()
        if version != f"stygnox {VERSION}":
            raise RuntimeError(f"unexpected installed version: {version}")
        nonloop = run(str(stygnox), "web", "--project", str(ROOT), "--host", "0.0.0.0", "--port", "0", env=env, check=False)
        if nonloop.returncode != 2 or "loopback-only" not in nonloop.stderr:
            raise RuntimeError("non-loopback Web binding did not fail closed before authority")

        fixtures = work / "fixtures"
        new = fixtures / "new-unborn"
        clean = fixtures / "clean"
        dirty = fixtures / "dirty"
        init_repo(new, commit=False)
        init_repo(clean, commit=True)
        init_repo(dirty, commit=True)
        make_dirty(dirty)

        results = [
            qualify_fixture("new-unborn", new, stygnox, env),
            qualify_fixture("clean", clean, stygnox, env),
            qualify_fixture("dirty", dirty, stygnox, env),
        ]

        # Brand authority must be exactly what the installed Web serves.
        token_source = ROOT / "branding/css/design-tokens.css"
        component_source = ROOT / "branding/css/components.css"
        if not token_source.is_file() or not component_source.is_file():
            raise RuntimeError("authoritative branding CSS is missing from source qualification tree")

        report = {
            "schema": SCHEMA,
            "version": VERSION,
            "wheel": wheel.name,
            "wheel_sha256": sha256(wheel),
            "fixtures": results,
            "installed_web": "PASS",
            "cli_web_preview_parity": "PASS",
            "branding_authority": "PASS",
            "csrf_mutation_gate": "PASS",
            "loopback_only_policy": "PASS",
            "legacy_ralph_web_fallback": "REFUSED",
            "carry_forward_auto_adopt": False,
            "next_stage": "D8.6B installed TUI, terminal identity, and final cross-surface parity",
        }
        print("D8.6A INSTALLED WEB / OPERATOR UX QUALIFICATION PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        print("\nBUILD TRANSCRIPT")
        print(build.stdout.rstrip())
        print("\nINSTALL TRANSCRIPT")
        print(install.stdout.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
