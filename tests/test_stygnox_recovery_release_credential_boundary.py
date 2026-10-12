"""02J: real kernel DAC isolation; no mock credentials, no provider turns."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import subprocess
import sys

import pytest

from stygnox.direct_interruption_credential_isolation import (
    CredentialIsolationRefused, qualify_disposable_credential_boundary,
)

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_credential_boundary.py'


def _probe(*args: str):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          text=True, capture_output=True, timeout=10)


def test_normal_user_cannot_run_credential_boundary_without_root_service():
    outcome = _probe('--simulate', '--predecessor-uid', str(os.getuid() or 65534))
    assert outcome.returncode != 0
    result = json.loads(outcome.stdout)
    assert result['inspection_failed'] is True
    assert result['handoff_admissible'] is False
    assert result['provider_executed'] is False


def test_does_not_expose_success_or_real_credential_modes():
    for args in (('--help',), ('--release',), ('--provider', 'astra'),
                 ('--simulate', '--predecessor-uid', '0'),
                 ('--simulate', '--predecessor-uid', '1000', '--secret', 'key')):
        outcome = _probe(*args)
        assert outcome.returncode != 0
        assert not ('--provider' in args and 'key' in outcome.stdout)


def test_uid_validation_rejects_root_and_nonroot_callers():
    with pytest.raises(CredentialIsolationRefused, match='(root required|distinct non-root)'):
        qualify_disposable_credential_boundary(0)
    with pytest.raises(CredentialIsolationRefused, match='(root required|distinct non-root)'):
        qualify_disposable_credential_boundary(True)


def test_actual_old_uid_denied_direct_and_alias_access_if_root():
    if os.geteuid() != 0:
        pytest.skip('real cross-UID kernel credential isolation requires root')
    target = next((p.pw_uid for p in pwd.getpwall() if p.pw_uid > 0 and p.pw_name == 'nobody'), None)
    if target is None:
        pytest.skip('no disposable unprivileged UID')
    result = qualify_disposable_credential_boundary(target)
    assert result['root_can_open_disposable_credential'] is True
    assert result['predecessor_direct_open_denied'] is True
    assert result['predecessor_alias_open_denied'] is True
    assert result['disposable_fixture_removed'] is True
    assert result['external_provider_credential_revocation_proved'] is False
    assert result['all_legacy_provider_authority_excluded'] is False
    assert result['successor_execution_authorised'] is False
    assert result['handoff_admissible'] is False


def test_real_publisher_never_accepts_a_provider_credential_argument():
    outcome = _probe('--simulate', '--predecessor-uid', '65534', '--api-key', 'SENTINEL-DO-NOT-STORE')
    assert outcome.returncode != 0
    assert 'SENTINEL-DO-NOT-STORE' not in outcome.stdout
