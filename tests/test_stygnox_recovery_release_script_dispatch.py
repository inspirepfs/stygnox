"""02O: legacy-script Codex dispatch is denied before any process starts.

These checks execute production entrypoints with inert local canaries. They do
not grant permission, use provider credentials, or contact a network endpoint.
"""
from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
DENIAL = "recovery script provider dispatch blocked"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ralph = _load("stygnox_ralph_02o_security", SCRIPTS / "ralph.py")
codex = ralph.codex


def _inert_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "PROCESS_EXECUTED"
    exe = bindir / "codex"
    exe.write_text(f'#!/bin/sh\nprintf started > "{marker}"\n', encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f'{bindir}{os.pathsep}{os.environ.get("PATH", "")}')
    monkeypatch.setenv("STYGNOX_PROVIDER_RELEASE", "FAKE_APPROVED")
    monkeypatch.setenv("OPENAI_API_KEY", "INERT_CREDENTIAL_CANARY")
    return marker


@pytest.mark.parametrize("method", [
    "script_stream", "script_sandbox", "script_turn", "ralph_stream",
    "ralph_sandbox_cached", "ralph_turn", "ralph_rate_limits",
    "ralph_models", "ralph_reset_credit",
])
def test_legacy_script_paths_refuse_before_spawn(tmp_path, monkeypatch, method):
    marker = _inert_codex(tmp_path, monkeypatch)
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append("spawn")
        raise AssertionError("unapproved subprocess was reached")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(ralph, "_CODEX_PREFIX", ["codex"])

    def fake_stream(command):
        attempts.append("stream")
        raise AssertionError("unapproved stream process was reached")

    def fake_run_process(command):
        attempts.append("sandbox")
        raise AssertionError("unapproved sandbox subprocess was reached")

    def fake_live_write(*args):
        attempts.append("side-effect")
        raise AssertionError("unapproved live output was reached")

    noop = lambda *a, **k: None
    call = {
        "script_stream": lambda: codex.stream_codex_process(
            ["codex", "exec"], cwd=tmp_path, render_event=lambda event: [],
            clip=lambda text, limit: text, live_write=noop),
        "script_sandbox": lambda: codex.codex_command_prefix(
            run_process=fake_run_process, live_write=fake_live_write,
            which=lambda name: str(tmp_path / "bin" / name)),
        "script_turn": lambda: codex.run_codex(
            "INERT", {"type": "object"}, "workspace-write", cwd=tmp_path,
            prefix=["codex"], stream_process=fake_stream, normalize_failure=str,
            clip=lambda text, limit: text, live_write=noop),
        "ralph_stream": lambda: ralph.stream_codex_process(["codex", "exec"]),
        "ralph_sandbox_cached": lambda: ralph.codex_command_prefix(),
        "ralph_turn": lambda: ralph.run_codex("INERT", {"type": "object"}, "workspace-write"),
        "ralph_rate_limits": lambda: ralph.query_codex_rate_limits(),
        "ralph_models": lambda: ralph.query_codex_models(),
        "ralph_reset_credit": lambda: ralph.consume_codex_reset_credit("INERT"),
    }[method]
    with pytest.raises(codex.EnvironmentBlocked, match=DENIAL):
        call()
    assert attempts == []
    assert not marker.exists()


def test_script_provider_subprocess_inventory_is_intentionally_bounded():
    """Flag new direct launch sites so they require explicit review."""
    expected = {
        "stygnox_codex.py": {("stream_codex_process", "Popen")},
        "ralph.py": {
            ("query_codex_rate_limits", "Popen"),
            ("query_codex_models", "Popen"),
            ("consume_codex_reset_credit", "Popen"),
        },
    }
    for filename, launches in expected.items():
        source = (SCRIPTS / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = set()
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess" and node.func.attr == "Popen"):
                    found.add((fn.name, node.func.attr))
        assert found == launches
