"""Release 02D: kernel path denial must NOT be mistaken for FD revocation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_mount_denial.py'


def _module():
    spec = importlib.util.spec_from_file_location('rr02d_probe', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invalid_uid_rejected_without_touching_filesystems():
    probe = _module()
    with pytest.raises(probe.MountDenialRefused):
        probe.simulate(0)


def test_executable_does_not_accept_live_workspace_path():
    result = subprocess.run([sys.executable, str(SCRIPT), '--simulate',
                             '--predecessor-uid', '1000', '--original', '/home/somebody/project'],
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert 'unrecognized arguments' in result.stderr


def test_no_root_or_no_namespace_fails_closed():
    probe = _module()
    if os.geteuid() != 0:
        with pytest.raises(probe.MountDenialRefused, match='Linux root'):
            probe._private_namespace()
        return
    # Root but no CAP_SYS_ADMIN should refuse rather than falling back to host.
    child = subprocess.run([sys.executable, str(SCRIPT), '--simulate',
                            '--predecessor-uid', '12345'], text=True,
                           capture_output=True, timeout=12)
    if child.returncode != 0:
        assert 'REFUSED' in child.stderr
        assert not child.stdout.strip()
    else:
        evidence = json.loads(child.stdout)
        assert evidence['legacy_fresh_plan_open_denied'] is True
        assert evidence['legacy_fresh_write_denied'] is True
        assert evidence['legacy_mountpoint_rename_denied'] is True
        assert evidence['preopened_legacy_fd_still_writable'] is True
        assert evidence['host_wide_legacy_relaunch_excluded'] is False
        assert evidence['handoff_admissible'] is False


def test_kernel_denial_in_isolated_namespace_when_available():
    if os.geteuid() != 0:
        pytest.skip('root mount namespace fixture requires Linux CAP_SYS_ADMIN')
    run = subprocess.run([sys.executable, str(SCRIPT), '--simulate',
                          '--predecessor-uid', '12345'], capture_output=True,
                         text=True, timeout=12)
    if run.returncode != 0 and ('Operation not permitted' in run.stderr or
                                'cannot isolate mount namespace' in run.stderr):
        pytest.skip('CAP_SYS_ADMIN/unshare unavailable in this environment')
    assert run.returncode == 0, run.stderr
    evidence = json.loads(run.stdout)
    assert evidence['mount_namespace_isolated_from_pid1'] is True
    assert evidence['legacy_fresh_plan_open_denied'] is True
    assert evidence['legacy_fresh_write_denied'] is True
    assert evidence['legacy_mountpoint_rename_denied'] is True
    assert evidence['preopened_legacy_fd_still_writable'] is True
    assert evidence['old_open_fds_excluded'] is False
    assert evidence['authority_changed'] is False
