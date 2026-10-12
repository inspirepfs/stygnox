"""Release 02: real filesystem checks and a strict service cgroup boundary."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/probe_recovery_release_supervisor.py'
spec = importlib.util.spec_from_file_location('release_supervisor', SCRIPT)
assert spec and spec.loader
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def test_only_a_dedicated_system_service_is_allowed():
    target = ['/user.slice/user-1000.slice/session-18.scope',
              '/system.slice/docker-123.scope']
    service._validate_supervisor('/system.slice/stygnox-recovery-release02-check.service', target,
                                 incomplete=0)
    for group in ('/', '/system.slice',
                  '/user.slice/user-1000.slice/session-18.scope',
                  '/system.slice/docker-123.scope',
                  '/system.slice/stygnox-other.service',
                  '/user.slice/stygnox-recovery-release02-check.service'):
        with pytest.raises(service.SupervisorBoundaryRefused):
            service._validate_supervisor(group, target, incomplete=0)


def test_uninspectable_process_refuses_attestation():
    with pytest.raises(service.SupervisorBoundaryRefused, match='incomplete'):
        service._validate_supervisor('/system.slice/stygnox-recovery-release02-check.service',
                                     [], incomplete=1)


def test_user_process_under_supervisor_refused():
    group = '/system.slice/stygnox-recovery-release02-check.service'
    with pytest.raises(service.SupervisorBoundaryRefused):
        service._validate_supervisor(group, [group + '/task'], incomplete=0)


def test_untrusted_checkout_refused_even_for_root(tmp_path):
    source = tmp_path / 'probe.py'
    source.write_text('print("not executed")\n')
    with pytest.raises(service.SupervisorBoundaryRefused, match='untrusted'):
        service._trusted_file(source)


def test_symlink_source_refused(tmp_path):
    symlink = tmp_path / 'link.py'
    symlink.symlink_to(SCRIPT)
    with pytest.raises(service.SupervisorBoundaryRefused):
        service._trusted_file(symlink)


def test_command_never_runs_in_user_session():
    p = subprocess.run([sys.executable, str(SCRIPT), '--predecessor-uid', str(os.getuid() or 1000)],
                       capture_output=True, text=True, check=False)
    assert p.returncode == 2
    assert 'REFUSED' in p.stderr
    assert 'handoff_admissible' not in p.stdout
