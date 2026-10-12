"""02H guard restart safety: no authority grant and no untrusted fixture paths."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_host_guard_recovery.py'


def _probe():
    spec = importlib.util.spec_from_file_location('stygnox_rr02h_probe', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('token', [
    '', '../outside', '/run/foo', 'A'*32, 'abc', '0'*31, 'f'*33,
    '0'*31 + '/', '0'*31 + '\x00', '0'*31 + '\n',
])
def test_refuses_untrusted_fixture_identifiers_before_access(token):
    probe = _probe()
    with pytest.raises(probe.GuardRestartRefused, match='identifier'):
        probe._paths(token)


def test_fixture_paths_are_exact_disposable_locations():
    probe = _probe()
    token = '0' * 32
    root, target, gate, journal = probe._paths(token)
    assert root == Path('/run/stygnox-rr02h-' + token)
    assert target == root / 'legacy-parent' / 'original'
    assert gate == root / 'denial'
    assert journal == SCRIPT.parent / 'state' / token
    assert journal != root


def test_refuses_root_and_reserved_uid_before_any_host_action():
    probe = _probe()
    for uid in (0, -1, 65534, True, False):
        with pytest.raises(probe.GuardRestartRefused, match='distinct non-root'):
            probe.establish(uid)


def test_unprivileged_cannot_start_any_service_phase():
    if os.getuid() == 0:
        pytest.skip('root-only system-service guard is checked in separate host qualification')
    probe = _probe()
    with pytest.raises(probe.GuardRestartRefused, match='root system service'):
        probe.establish(1001)
    for phase in (probe.verify, probe.retire):
        with pytest.raises(probe.GuardRestartRefused, match='root system service'):
            phase('0' * 32)


def test_evidence_never_claims_authority_or_real_relaunch_exclusion():
    probe = _probe()
    expected = {
        'real_predecessor_excluded', 'alternative_path_aliases_excluded',
        'reboot_persistent_denial_proved', 'original_binding_retired',
        'authority_changed', 'provider_executed',
        'successor_execution_authorised', 'handoff_admissible',
        'live_runtime_modified',
    }
    flags = probe._flags()
    assert set(flags) == expected
    assert all(value is False for value in flags.values())


def test_rejects_extra_paths_and_ambiguous_phase_options():
    p = subprocess.run(
        [sys.executable, str(SCRIPT), '--verify', '--fixture-id', '../real-workspace'],
        capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(SCRIPT.parents[1] / 'src')},
    )
    assert p.returncode == 2
    assert 'invalid disposable fixture identifier' in p.stderr
    p = subprocess.run(
        [sys.executable, str(SCRIPT), '--verify', '--establish', '--fixture-id', '0' * 32],
        capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(SCRIPT.parents[1] / 'src')},
    )
    assert p.returncode != 0
    assert 'not allowed' in p.stderr


def test_real_kernel_lifecycle_requires_root_system_service():
    # This test is qualified via THREE separate systemd-run invocations on the
    # Linux host: establish, verify from a new service, and retire + reconcile.
    pytest.skip('privileged 02H host-visible multi-service qualification is external')
