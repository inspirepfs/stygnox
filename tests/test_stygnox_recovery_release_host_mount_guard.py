"""02G host-visible disposable denial; never touches the live StygNox tree."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_host_mount_guard.py'


def _probe():
    spec = importlib.util.spec_from_file_location('release02g', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_invalid_uid_never_creates_mount_or_journal():
    probe = _probe()
    for uid in (-1, 0, None, False, True, 65534):
        with pytest.raises(probe.HostMountGuardRefused, match='predecessor UID'):
            probe.simulate(uid)


def test_cli_accepts_only_disposable_fixture_parameters():
    for arg in ('--original', '--workspace', '--installed-predecessor',
                '--release', '--successor', '--real-target'):
        run = subprocess.run(
            [sys.executable, str(SCRIPT), '--simulate', '--predecessor-uid',
             '1000', arg, '/home/anyone/stygnox'],
            text=True, capture_output=True, timeout=10,
        )
        assert run.returncode != 0
        assert 'unrecognized arguments' in run.stderr
        assert not run.stdout


def test_refuses_untrusted_supervisor_without_attempting_mount():
    probe = _probe()
    # UID 1000 is often the invoking user; using it exercises the distinct-UID
    # precondition instead of the intended supervisor authentication guard.
    predecessor_uid = 12345 if os.getuid() != 12345 else 12346
    if os.getuid() != 0:
        with pytest.raises(probe.HostMountGuardRefused, match='root system service'):
            probe.simulate(predecessor_uid)
    else:
        # This pytest run must not be inside the dedicated systemd service.
        with pytest.raises(probe.HostMountGuardRefused, match='dedicated Release 02G'):
            probe.simulate(predecessor_uid)


def test_mountinfo_checker_rejects_any_nondisposable_target():
    probe = _probe()
    for target in ('/home/user/stygnox', '/run', '/var/lib/stygnox',
                   '/run/stygnox-rr02e-live/original'):
        with pytest.raises(probe.HostMountGuardRefused, match='non-disposable'):
            probe._pid1_mountpoint_present(Path(target))


def test_host_mount_fixture_only_in_root_service():
    if os.geteuid() != 0:
        pytest.skip('requires CAP_SYS_ADMIN and dedicated systemd system service')
    # This is a deliberately guarded real-kernel test: the code refuses
    # execution from interactive sudo or from pytest's root container.
    run = subprocess.run([sys.executable, str(SCRIPT), '--simulate',
                          '--predecessor-uid', '12345'],
                         capture_output=True, text=True, timeout=30)
    if run.returncode != 0 and ('dedicated Release 02G' in run.stderr or
                                'root system service required' in run.stderr):
        pytest.skip('dedicated system service not available in test environment')
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data['host_visible_denial_mount_observed'] is True
    assert data['exact_inert_predecessor_drained'] is True
    assert data['journal_reconciled_after_denial_removed'] is True
    assert data['handoff_admissible'] is False
