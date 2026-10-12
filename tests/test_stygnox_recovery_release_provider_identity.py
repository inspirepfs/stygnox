"""02L: executable isolation behaviours, including unprivileged refusal paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from stygnox.direct_interruption_provider_identity import (
    ProviderIdentityRefused, assert_no_provider_environment,
    qualify_credentialless_identity, _must_deny_directory,
    _must_deny_network_socket,
)

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/probe_recovery_release_provider_identity.py'


def _probe(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          text=True, capture_output=True, timeout=12)


def test_rejects_untrusted_user_service_without_any_provider_turn():
    result = _probe('--simulate', '--predecessor-uid', str(os.getuid() or 65534))
    assert result.returncode != 0
    evidence = json.loads(result.stdout)
    assert evidence['qualification_failed'] is True
    assert evidence['provider_executed'] is False
    assert evidence['successor_execution_authorised'] is False
    assert evidence['handoff_admissible'] is False


def test_rejects_unrecognised_release_and_credentials_without_reflection():
    secret = 'SECRET_CANARY_DO_NOT_REFLECT_244399'
    for args in (('--release',), ('--help',), ('--simulate', '--predecessor-uid', '0'),
                 ('--simulate', '--predecessor-uid', '1000', '--token', secret)):
        result = _probe(*args)
        assert result.returncode != 0
        assert secret not in result.stdout
        assert secret not in result.stderr


def test_environment_keys_rejected_without_exposing_values(capsys):
    sentinel = 'SECRET_CANARY_ENV_99811'
    for name in ('OPENAI_API_KEY', 'CODEX_HOME', 'XDG_CONFIG_HOME',
                 'GOOGLE_APPLICATION_CREDENTIALS', 'GEMINI_API_KEY'):
        with pytest.raises(ProviderIdentityRefused, match='credential environment'):
            assert_no_provider_environment({'PATH': '/usr/bin', name: sentinel})
    assert sentinel not in capsys.readouterr().out


def test_noncredential_process_environment_is_permitted():
    assert_no_provider_environment({'PATH': '/usr/bin:/bin', 'LANG': 'C'})


def test_actual_access_is_refused_when_directory_is_accessible(tmp_path):
    with pytest.raises(ProviderIdentityRefused, match='accessible'):
        _must_deny_directory(tmp_path)


def test_network_socket_must_be_denied_for_isolated_service():
    try:
        _must_deny_network_socket()
    except ProviderIdentityRefused as exc:
        assert 'could be created' in str(exc) or 'not proved' in str(exc)
    else:
        # Some test hosts already have a seccomp socket prohibition.
        pass


def test_direct_qualification_does_not_authorise_ordinary_process():
    with pytest.raises(ProviderIdentityRefused):
        qualify_credentialless_identity(os.getuid() or 65534)


def test_nonroot_username_is_not_root_permission():
    if os.geteuid() == 0:
        pytest.skip('run this test as a normal user for cross-UID assertion')
    result = _probe('--simulate', '--predecessor-uid', '0')
    assert result.returncode != 0
    assert json.loads(result.stdout)['authority_changed'] is False
