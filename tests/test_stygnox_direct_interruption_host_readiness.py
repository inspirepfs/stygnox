"""Hostile tests for read-only published-custody inspection and denial."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from stygnox import direct_interruption_blocked_commissioning as commissioning
from stygnox import direct_interruption_custody_cutover as cutover
from stygnox import direct_interruption_host_readiness as readiness
from test_stygnox_direct_interruption_custody_cutover import inputs


def published(tmp_path):
    _, payload = inputs()
    cutover._publish(tmp_path, payload)
    return tmp_path / cutover.SLOT


def inspect(tmp_path):
    return readiness.verify_published_slot(tmp_path, uid=os.geteuid())


def test_published_history_is_verified_but_never_authorises_execution(tmp_path):
    slot = published(tmp_path)
    before = {
        str(p.relative_to(slot)): p.read_bytes()
        for p in slot.rglob('*') if p.is_file()
    }
    result = inspect(tmp_path)
    assert result['transaction_id'] == 'TX-a6379f065ce68138'
    assert result['current_step'] == 2
    assert result['recorded_continuations'] == 8
    assert result['historical_step_result_count'] == 1
    assert result['blocked_root_custody_intact'] is True
    assert before == {
        str(p.relative_to(slot)): p.read_bytes()
        for p in slot.rglob('*') if p.is_file()
    }
    assert readiness.denied_report()['successor_execution_authorised'] is False
    assert readiness.denied_report()['provider_executed'] is False


@pytest.mark.parametrize('target', [
    'root-custody.json', 'custody-intake.json',
    '.stygnox/plan.json', '.stygnox/controller.json',
    '.stygnox/transaction.json',
    '.stygnox/' + commissioning.MARKER,
])
def test_any_custody_record_mutation_refuses(tmp_path, target):
    slot = published(tmp_path)
    path = slot / target
    data = json.loads(path.read_bytes())
    data['intruder'] = True
    path.chmod(0o600)
    path.write_text(json.dumps(data) + '\n')
    path.chmod(0o400)
    with pytest.raises(readiness.ReadinessRefused):
        inspect(tmp_path)


def test_rehashed_false_authority_refused(tmp_path):
    slot = published(tmp_path)
    path = slot / 'root-custody.json'
    data = json.loads(path.read_bytes())
    data['legacy_controller_excluded'] = True
    data.pop('record_sha256')
    revised = cutover._seal(data)
    path.chmod(0o600)
    path.write_bytes(readiness._canonical(revised))
    path.chmod(0o400)
    with pytest.raises(readiness.ReadinessRefused, match='lineage or deny-state'):
        inspect(tmp_path)


def test_wrong_transaction_with_valid_record_hash_refuses(tmp_path):
    slot = published(tmp_path)
    path = slot / 'root-custody.json'
    data = json.loads(path.read_bytes())
    data['transaction_id'] = 'TX-other'
    data.pop('record_sha256')
    path.chmod(0o600)
    path.write_bytes(readiness._canonical(cutover._seal(data)))
    path.chmod(0o400)
    with pytest.raises(readiness.ReadinessRefused, match='lineage or deny-state'):
        inspect(tmp_path)


@pytest.mark.parametrize('failure', ['extra-file', 'missing-file', 'symlink',
                                     'wrong-mode', 'hardlink', 'directory-mode',
                                     'interrupted-stage', 'broken-old-publish'])
def test_hostile_filesystem_and_crash_states_refuse(tmp_path, failure):
    slot = published(tmp_path)
    target = slot / 'root-custody.json'
    if failure == 'extra-file':
        (slot / 'rogue.json').touch()
    elif failure == 'missing-file':
        target.unlink()
    elif failure == 'symlink':
        target.unlink()
        target.symlink_to(slot / 'custody-intake.json')
    elif failure == 'wrong-mode':
        target.chmod(0o600)
    elif failure == 'hardlink':
        os.link(target, tmp_path / 'outside-alias')
    elif failure == 'directory-mode':
        (slot / '.stygnox').chmod(0o755)
    elif failure == 'interrupted-stage':
        (tmp_path / (cutover.SLOT + '.pending')).mkdir()
    else:
        from stygnox import direct_interruption_blocked_commissioning as commissioning
        (tmp_path / (commissioning.STAGE + '.pending')).mkdir()
    with pytest.raises(readiness.ReadinessRefused):
        inspect(tmp_path)


def test_canonical_bytes_needed_even_if_json_hash_matches(tmp_path):
    slot = published(tmp_path)
    target = slot / 'root-custody.json'
    original = target.read_bytes()
    target.chmod(0o600)
    target.write_bytes(original + b'\n')
    target.chmod(0o400)
    with pytest.raises(readiness.ReadinessRefused, match='noncanonical'):
        inspect(tmp_path)


def test_nonroot_and_unavailable_host_cannot_produce_release(monkeypatch):
    monkeypatch.setattr(readiness.os, 'geteuid', lambda: 1000)
    with pytest.raises(readiness.ReadinessRefused, match='Linux root'):
        readiness.audit_live_host()


def test_readiness_cli_never_issues_release(tmp_path):
    cli = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_host_readiness.py'
    for argv in ([], ['--audit-existing-root-custody'], ['--release'], ['--seal-blocked-root-custody']):
        completed = subprocess.run([sys.executable, '-I', '-B', str(cli), *argv],
                                   capture_output=True, text=True, check=False)
        assert completed.returncode == 75
        assert completed.stderr == ''
        report = json.loads(completed.stdout)
        assert report['successor_execution_authorised'] is False
        assert report['provider_executed'] is False
        assert report['phase'] in ('HOST_READINESS_REFUSED', 'EXCLUSIVE_CUSTODY_NOT_PROVED')
        assert report.get('execution_authority') == 'NONE'


def test_privileged_bootstrap_refuses_mutable_source_before_import(tmp_path):
    if os.geteuid() != 0:
        pytest.skip('root-only bootstrap denial check')
    source = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_host_readiness.py'
    fake = tmp_path / 'mutable-recovery'
    (fake / 'scripts').mkdir(parents=True)
    (fake / 'src/stygnox').mkdir(parents=True)
    script = fake / 'scripts/stygnox_recovery_host_readiness.py'
    shutil.copy2(source, script)
    sentinel = tmp_path / 'imported-untrusted-source'
    # If root ever imports this module, it writes the sentinel. The guard
    # must deny before importing user-controlled Python.
    (fake / 'src/stygnox/direct_interruption_host_readiness.py').write_text(
        f'from pathlib import Path\nPath({str(sentinel)!r}).touch()\n')
    completed = subprocess.run([sys.executable, '-I', '-B', str(script),
                                '--audit-existing-root-custody'],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 75
    assert json.loads(completed.stdout)['phase'] == 'HOST_READINESS_REFUSED'
    assert not sentinel.exists()
