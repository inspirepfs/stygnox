"""Behavioural coverage for redacted, read-only local credential-source inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from stygnox.direct_interruption_provider_inventory import (
    ProviderInventoryRefused, collect_provider_authority_inventory,
    canonical_report,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = ROOT / 'src/stygnox/provider_codex.py'


def _run(tmp_path: Path, environment: dict[str, str] | None = None, *, source: Path = REAL_SOURCE):
    return collect_provider_authority_inventory(
        provider_source=source,
        expected_provider_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        home=tmp_path,
        environment=environment or {},
        inspection_uid=1000,
        cli_on_path=False,
    )


def test_actual_adapter_path_and_inherited_environment_are_reported(tmp_path):
    report = _run(tmp_path)
    assert report['reviewed_adapter_subprocess_call_count'] >= 2
    assert report['adapter_subprocess_environment_inherited_by_default'] is True
    assert report['reviewed_launch_markers_present'] is True
    assert report['scope'] == 'CURRENT_UID_ONLY_NOT_HISTORICAL_PREDECESSOR'
    assert report['legacy_process_environment_verified'] is False
    assert report['all_legacy_provider_authority_excluded'] is False
    assert report['handoff_admissible'] is False


def test_does_not_read_or_report_environment_value_or_credential_contents(tmp_path):
    secret = 'FAKE_AUTH_SECRET_MUST_NEVER_LEAK_9081221'
    directory = tmp_path / '.codex'
    directory.mkdir(mode=0o700)
    login = directory / 'auth.json'
    login.write_text(secret, encoding='utf-8')
    report = _run(tmp_path, {'OPENAI_API_KEY': secret, 'CODEX_HOME': secret, 'OTHER_SECRET': secret})
    text = canonical_report(report)
    assert secret not in text
    assert str(tmp_path) not in text
    assert 'OTHER_SECRET' not in text
    assert report['candidate_environment_names_present'] == ['CODEX_HOME', 'OPENAI_API_KEY']
    assert report['default_codex_auth_json_metadata']['kind'] == 'regular'
    assert report['custom_codex_home_present_uninspected'] is True
    assert 'CUSTOM_CODEX_HOME_NOT_INSPECTED' in report['required_followup']
    assert login.read_text(encoding='utf-8') == secret


def test_symlinked_codex_directory_is_not_traversed(tmp_path):
    target = tmp_path / 'elsewhere'
    target.mkdir()
    (target / 'auth.json').write_text('DO_NOT_READ_THIS_SECRET', encoding='utf-8')
    (tmp_path / '.codex').symlink_to(target, target_is_directory=True)
    report = _run(tmp_path)
    assert report['default_codex_directory_metadata']['kind'] == 'symlink'
    assert report['default_codex_auth_json_metadata']['status'] == 'not_inspected_parent_untrusted'
    assert 'DO_NOT_READ_THIS_SECRET' not in canonical_report(report)


def test_provider_source_integrity_mismatch_blocks(tmp_path):
    with pytest.raises(ProviderInventoryRefused, match='digest mismatch'):
        collect_provider_authority_inventory(
            provider_source=REAL_SOURCE, expected_provider_sha256='0' * 64,
            home=tmp_path, environment={}, inspection_uid=1000, cli_on_path=False,
        )


def test_non_root_scope_is_required(tmp_path):
    with pytest.raises(ProviderInventoryRefused, match='non-root'):
        collect_provider_authority_inventory(
            provider_source=REAL_SOURCE,
            expected_provider_sha256=hashlib.sha256(REAL_SOURCE.read_bytes()).hexdigest(),
            home=tmp_path, environment={}, inspection_uid=0, cli_on_path=False,
        )


def test_uncertain_adapter_env_override_is_identified(tmp_path):
    original = REAL_SOURCE.read_text(encoding='utf-8')
    needle = '        check=False,\n'
    assert needle in original
    # Change only source under inspection: the AST must flag explicit env handling.
    changed = original.replace(needle, '        env={},\n' + needle, 1)
    candidate = tmp_path / 'adapter.py'
    candidate.write_text(changed, encoding='utf-8')
    report = _run(tmp_path, source=candidate)
    assert report['adapter_explicit_subprocess_environment_override'] is True
    assert report['adapter_subprocess_environment_inherited_by_default'] is False
    assert 'ADAPTER_ENVIRONMENT_OVERRIDE_REVIEW_REQUIRED' in report['required_followup']


def test_report_never_grants_successor_release_even_if_no_candidates(tmp_path):
    r = _run(tmp_path)
    assert r['default_codex_auth_json_metadata'] == {'status': 'absent'}
    assert r['candidate_environment_names_present'] == []
    for key in ('inventory_complete', 'successor_execution_authorised', 'handoff_admissible', 'authority_changed', 'provider_executed'):
        assert r[key] is False
    assert json.loads(canonical_report(r)) == r
