"""02N behavioural boundary: every real adapter subprocess start is denied.

Never invokes a provider. Fake local executables are inert marker canaries.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from stygnox import provider_codex

DENIAL = 'recovery provider dispatch blocked'


def _fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    marker = tmp_path / 'PROVIDER_SUBPROCESS_RAN'
    executable = bin_dir / 'codex'
    executable.write_text('#!/bin/sh\nprintf RAN > "' + str(marker) + '"\n', encoding='utf-8')
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
    # No environment override, manufactured authorisation or candidate session can release 02N.
    monkeypatch.setenv('STYGNOX_PROVIDER_RELEASE', 'APPROVED_BUT_UNTRUSTED')
    monkeypatch.setenv('OPENAI_API_KEY', 'INERT_TEST_CANARY')
    return marker


@pytest.mark.parametrize('name', [
    'model_catalog', 'rate_limits', '_app_server_request', '_preflight', '_run',
    'execute', 'execute_structured', 'reset_credit_preview', 'redeem_reset_credit',
])
def test_every_public_and_internal_provider_launch_path_denied(tmp_path, monkeypatch, name):
    marker = _fake_codex(tmp_path, monkeypatch)
    options = {
        'model_catalog': lambda: provider_codex.model_catalog(tmp_path),
        'rate_limits': lambda: provider_codex.rate_limits(tmp_path),
        '_app_server_request': lambda: provider_codex._app_server_request(tmp_path, 'account/rateLimits/read'),
        '_preflight': lambda: provider_codex._preflight(tmp_path),
        '_run': lambda: provider_codex._run(['codex', 'exec', 'INERT_TEST_CANARY'], cwd=tmp_path),
        'execute': lambda: provider_codex.execute(cwd=tmp_path, prompt='INERT_TEST_CANARY', model='gpt-test', effort=None, repository_authority='read-only'),
        'execute_structured': lambda: provider_codex.execute_structured(cwd=tmp_path, prompt='INERT_TEST_CANARY', model='gpt-test', effort=None, repository_authority='write', result_schema={'type': 'object'}),
        'reset_credit_preview': lambda: provider_codex.reset_credit_preview(tmp_path, 'operator'),
        'redeem_reset_credit': lambda: provider_codex.redeem_reset_credit(tmp_path, 'operator', 'a'*64, 'REDEEM'),
    }
    # An unguarded Popen or subprocess.run, regardless of executable, is a fatal regression.
    original_run = subprocess.run
    original_popen = subprocess.Popen
    observed = []
    def rejected_run(*args, **kwargs):
        observed.append('run')
        raise AssertionError('actual subprocess.run reached')
    def rejected_popen(*args, **kwargs):
        observed.append('Popen')
        raise AssertionError('actual subprocess.Popen reached')
    monkeypatch.setattr(subprocess, 'run', rejected_run)
    monkeypatch.setattr(subprocess, 'Popen', rejected_popen)
    try:
        with pytest.raises(provider_codex.ProviderError, match=DENIAL):
            options[name]()
        assert observed == []
        assert not marker.exists()
    finally:
        monkeypatch.setattr(subprocess, 'run', original_run)
        monkeypatch.setattr(subprocess, 'Popen', original_popen)


def test_adapter_has_no_unguarded_subprocess_call_sites():
    """Fail when the adapter grows a new subprocess call without deliberate review."""
    import ast
    source = Path(provider_codex.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    found = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess'
                and node.func.attr in {'run', 'Popen'}):
                found.append((fn.name, node.func.attr))
    assert sorted(found) == sorted([
        ('model_catalog', 'Popen'),
        ('_app_server_request', 'Popen'),
        ('_run', 'run'),
    ])
