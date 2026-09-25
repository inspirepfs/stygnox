#!/usr/bin/env python3
"""D8.6B installed TUI/terminal identity and cross-surface parity qualification."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
from stygnox_qualification_artifact import provided_build_result, provided_wheel

SCHEMA = "stygnox_d8_6b_tui_qualification_v1"
VERSION = runpy.run_path(str(ROOT / "src/stygnox/_version.py"))["__version__"]


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def git(cwd: Path, *args: str) -> None:
    run("git", *args, cwd=cwd)


def init_repo(path: Path, *, commit: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.6B TUI Qualification")
    git(path, "config", "user.email", "qualification@example.invalid")
    (path / "README.md").write_text("fixture baseline\n", encoding="utf-8")
    if commit:
        git(path, "add", "README.md")
        git(path, "commit", "-q", "-m", "baseline")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: dict) -> dict:
    out = json.loads(json.dumps(value))
    if isinstance(out.get("server"), dict):
        out["server"]["pid"] = 0
    return out


def command_json(stygnox: Path, fixture: Path, env: dict[str, str], *args: str) -> dict:
    result = run(str(stygnox), *args, cwd=fixture, env=env)
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("installed command did not return a JSON object")
    return value


def start_web(stygnox: Path, fixture: Path, env: dict[str, str]):
    proc = subprocess.Popen(
        [str(stygnox), "web", "--project", str(fixture), "--host", "127.0.0.1", "--port", "0"],
        cwd=fixture, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
    )
    assert proc.stdout is not None
    deadline = time.time() + 15
    line = ""
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
    if not match:
        stderr = proc.stderr.read() if proc.stderr else ""
        proc.terminate()
        raise RuntimeError(f"installed Web did not start for parity gate: {line} {stderr}")
    return proc, f"http://127.0.0.1:{match.group(1)}"


def http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Web snapshot was not an object")
    return value


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="stygnox-d86b-qualification-") as td:
        work = Path(td)
        dist = work / "dist"
        dist.mkdir()
        wheel = provided_wheel()
        if wheel is None:
            build = run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(dist), ".", cwd=ROOT)
            wheels = list(dist.glob("stygnox-*.whl"))
            if len(wheels) != 1:
                raise RuntimeError(f"expected one wheel, found {wheels}")
            wheel = wheels[0]
        else:
            build = provided_build_result(wheel)

        venv_dir = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        pip = venv_dir / "bin" / "pip"
        stygnox = venv_dir / "bin" / "stygnox"
        install = run(str(pip), "install", "--no-deps", str(wheel), cwd=ROOT)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PATH"] = str(venv_dir / "bin") + os.pathsep + env.get("PATH", "")

        version = run(str(stygnox), "--version", env=env).stdout.strip()
        if version != f"stygnox {VERSION}":
            raise RuntimeError(f"unexpected installed version: {version}")

        fixtures = work / "fixtures"
        new = fixtures / "new-unborn"
        clean = fixtures / "clean"
        dirty = fixtures / "dirty"
        init_repo(new, commit=False)
        init_repo(clean, commit=True)
        init_repo(dirty, commit=True)
        (dirty / "README.md").write_text("fixture baseline\noperator edit\n", encoding="utf-8")
        (dirty / "external-note.txt").write_text("external\n", encoding="utf-8")

        results = []
        for name, fixture in (("new-unborn", new), ("clean", clean), ("dirty", dirty)):
            decoy = fixture / ".git" / "tui-decoy"
            decoy.mkdir(parents=True, exist_ok=True)
            sentinel = fixture / ".git" / "RALPH_TUI_IMPORTED"
            (decoy / "ralph_tui.py").write_text(
                "from pathlib import Path\n" + f"Path({str(sentinel)!r}).write_text('imported', encoding='utf-8')\n",
                encoding="utf-8",
            )
            fixture_env = dict(env)
            fixture_env["PYTHONPATH"] = str(decoy)

            op = command_json(stygnox, fixture, fixture_env, "operator", "snapshot", "--project", str(fixture))
            tui = command_json(stygnox, fixture, fixture_env, "tui", "--project", str(fixture), "--json")
            if canonical(op) != canonical(tui):
                raise RuntimeError(f"{name}: operator/TUI snapshot parity mismatch")

            proc, base = start_web(stygnox, fixture, fixture_env)
            try:
                web = http_json(base + "/api/snapshot")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=5)
            if canonical(op) != canonical(web):
                raise RuntimeError(f"{name}: operator/Web/TUI snapshot parity mismatch")
            if sentinel.exists():
                raise RuntimeError(f"{name}: installed TUI imported target-local ralph_tui.py")

            direct_preview = command_json(stygnox, fixture, fixture_env, "adopt", "preview", "--project", str(fixture), "--operator", "D8.6B Operator")
            payload = json.dumps({"operator": "D8.6B Operator"})
            operator_preview = command_json(stygnox, fixture, fixture_env, "operator", "action", "--project", str(fixture), "--name", "adopt.preview", "--payload-json", payload)
            tui_preview = command_json(stygnox, fixture, fixture_env, "tui", "action", "--project", str(fixture), "--name", "adopt.preview", "--payload-json", payload, "--json")
            digests = {
                str(direct_preview.get("preview_sha256")),
                str(operator_preview.get("result", {}).get("preview_sha256")),
                str(tui_preview.get("result", {}).get("preview_sha256")),
            }
            if len(digests) != 1:
                raise RuntimeError(f"{name}: CLI/operator/TUI adoption-preview parity mismatch: {digests}")

            results.append({
                "fixture": name,
                "snapshot_parity": "PASS",
                "preview_parity": "PASS",
                "legacy_ralph_tui_fallback": "REFUSED",
            })

        # Exact terminal brand assets and narrow fallback.
        plain = run(str(stygnox), "tui", "--project", str(clean), "--color", "never", "--width", "100", cwd=clean, env=env).stdout
        ansi_env = dict(env); ansi_env.pop("NO_COLOR", None)
        ansi = run(str(stygnox), "tui", "--project", str(clean), "--color", "always", "--width", "100", cwd=clean, env=ansi_env).stdout
        narrow = run(str(stygnox), "tui", "--project", str(clean), "--color", "never", "--width", "55", cwd=clean, env=env).stdout
        plain_source = (ROOT / "branding/assets/ascii/stygnox-ascii.txt").read_text(encoding="utf-8").rstrip("\n")
        ansi_source = (ROOT / "branding/assets/ascii/stygnox-ascii-ansi.txt").read_text(encoding="utf-8").rstrip("\n")
        if not plain.startswith(plain_source):
            raise RuntimeError("installed TUI plain identity does not match authoritative ASCII")
        if not ansi.startswith(ansi_source):
            raise RuntimeError("installed TUI ANSI identity does not match authoritative ANSI asset")
        if not narrow.startswith("Stygnox ") or "AUTONOMOUS DEVELOPMENT-LOOP PLATFORM" in narrow:
            raise RuntimeError("narrow-terminal compact identity failed")
        no_color_env = dict(env); no_color_env["NO_COLOR"] = "1"
        no_color = run(str(stygnox), "tui", "--project", str(clean), "--color", "always", "--width", "100", cwd=clean, env=no_color_env).stdout
        if "\x1b[" in no_color:
            raise RuntimeError("NO_COLOR did not override forced terminal colour")

        report = {
            "schema": SCHEMA,
            "version": VERSION,
            "wheel": wheel.name,
            "wheel_sha256": sha(wheel),
            "fixtures": results,
            "installed_tui": "PASS",
            "operator_web_tui_snapshot_parity": "PASS",
            "cli_operator_tui_preview_parity": "PASS",
            "plain_ascii_authority": "PASS",
            "ansi_ascii_authority": "PASS",
            "narrow_terminal_fallback": "PASS",
            "no_color_policy": "PASS",
            "legacy_ralph_tui_fallback": "REFUSED",
            "next_stage": "D8.7 release packaging, documentation, and installed-artifact qualification",
        }
        print("D8.6B INSTALLED TUI / TERMINAL IDENTITY / CROSS-SURFACE PARITY QUALIFICATION PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        print("\nBUILD TRANSCRIPT")
        print(build.stdout.rstrip())
        print("\nINSTALL TRANSCRIPT")
        print(install.stdout.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
