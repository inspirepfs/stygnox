"""02I: startup denial is unconditional, even if earlier boot evidence is valid."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_boot_interlock.py'
TOKEN = 'a' * 32


def _module():
    spec = importlib.util.spec_from_file_location('boot_interlock_02i', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=10)


def test_refuses_path_injection_and_unknown_modes():
    for args in (
        ('--gate', '--fixture-id', '../original'),
        ('--gate', '--fixture-id', '/home/example'),
        ('--gate', '--fixture-id', TOKEN, '--workspace', '/home/example'),
        ('--inspect', '--gate', '--fixture-id', TOKEN),
        ('--release', '--fixture-id', TOKEN),
        ('--help',),
    ):
        result = _run(*args)
        assert result.returncode != 0
        if '--gate' in args and '--inspect' not in args and '--release' not in args and '--workspace' not in args:
            assert json.loads(result.stdout)['startup_admissible'] is False


def test_gate_denies_absent_journal_or_untrusted_supervisor():
    result = _run('--gate', '--fixture-id', TOKEN)
    assert result.returncode == 75
    data = json.loads(result.stdout)
    assert data['startup_admissible'] is False
    assert data['successor_execution_authorised'] is False
    assert data['handoff_admissible'] is False
    assert data['execution_authority'] == 'NONE'
    if os.getuid() != 0:
        assert data['reason'] == 'BootInterlockRefused'


def test_no_successful_inspect_mode_exists():
    result = _run('--inspect', '--fixture-id', TOKEN)
    assert result.returncode == 2
    assert not result.stdout
    assert 'unrecognized arguments' in result.stderr or 'required' in result.stderr


def test_data_only_blocked_report_has_no_release_path():
    module = _module()
    assert not hasattr(module, 'release')
    assert not hasattr(module, 'authorize')
    assert module.SCHEMA == 'stygnox_release02i_boot_startup_interlock_v1'
    with pytest.raises(module.BootInterlockRefused):
        module._token('a' * 31)


def test_root_system_service_host_inspection_is_separate_qualification():
    pytest.skip('root-owned dedicated systemd service probe requires Linux host')
