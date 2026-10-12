"""02E checks actual inert process/FDS and refuses unsafe privilege/scope."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_coordinated_exclusion.py'


def _module():
    spec = importlib.util.spec_from_file_location('rr02e_probe', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rejects_invalid_uid_without_entering_a_mount_namespace():
    probe = _module()
    for uid in (0, -1, 65534, None, True):
        with pytest.raises(probe.CoordinatedExclusionRefused):
            probe.simulate(uid)


def test_cli_rejects_any_real_paths_or_release_requests():
    for injected in ('--original', '--installed-predecessor', '--release', '--successor'):
        run = subprocess.run([sys.executable, str(SCRIPT), '--simulate',
                              '--predecessor-uid', '1000', injected, '/home/user/stygnox'],
                             capture_output=True, text=True, timeout=10)
        assert run.returncode != 0
        assert 'unrecognized arguments' in run.stderr
        assert not run.stdout


def test_descriptor_proof_uses_actual_writable_process_fd(tmp_path):
    probe = _module()
    plan = tmp_path / 'plan.json'
    plan.write_text('inert')
    script = tmp_path / 'legacy.py'
    script.write_text(probe._INERT_CHILD)
    child = subprocess.Popen([sys.executable, str(script), str(plan)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        probe._ready_child(child)
        assert probe._preopened_write_descriptor_verified(child.pid, plan) is True
        assert probe._preopened_write_descriptor_verified(child.pid, tmp_path / 'absent') is False
    finally:
        child.terminate()
        child.wait(timeout=5)
        if child.stdout:
            child.stdout.close()
        if child.stderr:
            child.stderr.close()


def test_unprivileged_execution_refuses_without_live_mutation():
    probe = _module()
    if os.geteuid() == 0:
        pytest.skip('requires ordinary non-root user; separately run kernel probe as root')
    with pytest.raises(probe.CoordinatedExclusionRefused, match='root process'):
        probe.simulate(12345)


def test_kernel_coordinated_fixture_when_supported():
    if os.geteuid() != 0:
        pytest.skip('requires Linux CAP_SYS_ADMIN, root namespace; kernel probe is separate')
    run = subprocess.run([sys.executable, str(SCRIPT), '--simulate',
                          '--predecessor-uid', '12345'],
                         capture_output=True, text=True, timeout=20)
    if run.returncode != 0 and ('Operation not permitted' in run.stderr or
                                'cannot isolate mount namespace' in run.stderr or
                                'dedicated systemd root-service scope required' in run.stderr):
        pytest.skip('trusted root service / mount namespace unavailable in this container')
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data['preexisting_writable_fd_observed_before_drain'] is True
    assert data['fresh_path_access_denied_before_drain'] is True
    assert data['exact_installed_predecessor_identity_pinned'] is True
    assert data['exact_predecessor_pidfd_drained'] is True
    assert data['fresh_path_access_denied_after_drain'] is True
    assert data['predecessor_reaped'] is True
    for key in ('old_fds_revoked_systemwide', 'all_predecessor_processes_excluded',
                'host_wide_relaunch_excluded', 'reboot_persistent_denial_proved',
                'original_binding_retired', 'successor_execution_authorised',
                'handoff_admissible', 'authority_changed', 'provider_executed',
                'live_runtime_modified'):
        assert data[key] is False
