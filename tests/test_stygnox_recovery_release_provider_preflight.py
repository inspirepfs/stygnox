"""02M admission denial behaviours, not merely field-presence tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from stygnox.direct_interruption_provider_preflight import (
    DENIED_EXIT, REPORTS, blocked_preflight, check_evidence,
)

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/probe_recovery_release_provider_preflight.py'


def _run(*arguments: str, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True, text=True, timeout=8, env=env,
    )


def test_unavailable_evidence_denies_without_any_execution(tmp_path):
    result = _run('--check', '--evidence-directory', str(tmp_path))
    assert result.returncode == DENIED_EXIT
    report = json.loads(result.stdout)
    assert report['preexecution_admissible'] is False
    assert report['handoff_admissible'] is False
    assert report['provider_executed'] is False
    assert any(code in report['blocked_reasons'] for code in ('HISTORICAL_REPORTS_INCOMPLETE_OR_UNTRUSTED', 'NONROOT_READONLY_INSPECTION_REQUIRED'))


def test_untrusted_report_symlink_denies_without_following_content(tmp_path):
    secret = tmp_path / 'private-material'
    secret.write_text('SECRET_NEVER_COPY_INTO_REPORT', encoding='utf-8')
    target = tmp_path / REPORTS['02i'][0]
    target.symlink_to(secret)
    result = _run('--check', '--evidence-directory', str(tmp_path))
    assert result.returncode == DENIED_EXIT
    assert 'SECRET_NEVER_COPY_INTO_REPORT' not in result.stdout + result.stderr
    assert json.loads(result.stdout)['preexecution_admissible'] is False


def test_fake_reports_cannot_become_authority(tmp_path):
    for name, (filename, _sha, schema) in REPORTS.items():
        (tmp_path / filename).write_text(json.dumps({
            'schema': schema, 'successor_execution_authorised': True,
            'handoff_admissible': True, 'authority_changed': True,
            'provider_executed': True, 'legacy_provider_authority_revoked': True,
        }), encoding='utf-8')
    report = blocked_preflight(tmp_path)
    assert report['historical_reports_are_release_credentials'] is False
    assert report['preexecution_admissible'] is False
    assert report['successor_execution_authorised'] is False
    assert report['execution_authority'] == 'NONE'
    assert report['blocked_reasons']


def test_candidate_codex_command_is_never_run(tmp_path):
    fake_exe = tmp_path / 'codex'
    marker = tmp_path / 'EXECUTION_MARKER'
    fake_exe.write_text('#!/bin/sh\nprintf yes > "' + str(marker) + '"\n', encoding='utf-8')
    fake_exe.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get('PATH', ''))
    result = _run('--check', '--evidence-directory', str(tmp_path), env=env)
    assert result.returncode == DENIED_EXIT
    assert not marker.exists()
    assert json.loads(result.stdout)['provider_executed'] is False


def test_unexpected_command_and_secret_like_arguments_do_not_echo(tmp_path):
    canary = 'SECRET_DO_NOT_REFLECT_2026'
    for args in (
        ('--execute', canary),
        ('--check', '--evidence-directory', str(tmp_path), '--token', canary),
        ('--help',),
    ):
        result = _run(*args)
        assert result.returncode == DENIED_EXIT
        assert canary not in result.stdout + result.stderr
        assert json.loads(result.stdout)['successor_execution_authorised'] is False


def test_denial_has_no_release_branch_even_for_valid_local_scope(tmp_path):
    report = blocked_preflight(tmp_path)
    assert report['preexecution_admissible'] is False
    assert 'NO_AUTHORISING_PROVIDER_DISPATCH_IMPLEMENTED' in report['blocked_reasons']
    assert report['handoff_admissible'] is False


def test_root_or_setuid_inspection_is_rejected(tmp_path):
    if os.getuid() == 0:
        assert check_evidence(tmp_path) == (False, ['NONROOT_READONLY_INSPECTION_REQUIRED'])
    else:
        pytest.skip('root rejection needs an actual root test process')
