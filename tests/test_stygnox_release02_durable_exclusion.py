"""Release 02F: durable blocked authority journal, with no release path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from stygnox import direct_interruption_durable_exclusion as guard


ARGS = dict(
    original_path='/home/legacy/approved-worktree',
    installed_predecessor_path='/opt/legacy/bin/stygnox',
    predecessor_uid=1000,
    original_device=7654,
    original_inode=4123,
    installed_sha256='1' * 64,
    plan_sha256='2' * 64,
    transaction_sha256='3' * 64,
)


def _root_fixture():
    if os.geteuid() != 0 or not Path('/run').is_dir():
        pytest.skip('trusted root-only /run fixture requires Linux root')
    return tempfile.TemporaryDirectory(prefix='stygnox-rr02f-test-', dir='/run')


def test_no_release_api_exists():
    assert not hasattr(guard, 'release')
    assert not hasattr(guard, 'authorize')
    assert not hasattr(guard, 'retire_workspace')
    data = guard._sealed({
        'schema': guard.SCHEMA, 'phase': 'PREPARED_BLOCKED',
        'execution_authority': 'NONE', 'boot_id': guard._boot_id(),
        **ARGS, **guard._UNSAFE_FLAGS,
    })
    guard._validate_prepared(data)
    for field in ('handoff_admissible', 'host_wide_relaunch_excluded',
                  'successor_execution_authorised', 'authority_changed'):
        tampered = dict(data)
        tampered[field] = True
        tampered['record_sha256'] = guard._digest({k: v for k, v in tampered.items() if k != 'record_sha256'})
        with pytest.raises(guard.DurableExclusionRefused):
            guard._validate_prepared(tampered)


def test_preparation_refuses_invalid_fields_without_creating_files():
    if os.geteuid() != 0:
        pytest.skip('root-only journal fixture')
    with _root_fixture() as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        for args in (
            dict(ARGS, original_path='../relative'),
            dict(ARGS, original_path='/home/legacy/../forged'),
            dict(ARGS, plan_sha256='not-a-digest'),
            dict(ARGS, predecessor_uid=True),
            dict(ARGS, original_inode=0),
        ):
            with pytest.raises(guard.DurableExclusionRefused):
                guard.prepare_blocked_journal(directory, **args)
        assert list(directory.iterdir()) == []


def test_prepare_fresh_process_replay_and_oneway_reconcile():
    with _root_fixture() as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        sealed = guard.prepare_blocked_journal(directory, **ARGS)
        assert sealed['record_sha256']
        assert (directory / guard._NAME).stat().st_mode & 0o777 == 0o600
        outcome = guard.inspect_blocked_journal(directory)
        assert outcome['phase'] == 'PREPARED_BLOCKED'
        assert not outcome['handoff_admissible']
        assert not outcome['host_wide_kernel_denial_proved']
        script = (
            'import json,sys; from stygnox.direct_interruption_durable_exclusion import '
            'inspect_blocked_journal; from pathlib import Path; '
            'print(json.dumps(inspect_blocked_journal(Path(sys.argv[1]))))'
        )
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        child = subprocess.run([sys.executable, '-c', script, str(directory)],
                               env=env, capture_output=True, text=True, check=True)
        assert json.loads(child.stdout)['record_sha256'] == sealed['record_sha256']
        with pytest.raises(guard.DurableExclusionRefused):
            guard.prepare_blocked_journal(directory, **ARGS)
        switched = guard.require_reconciliation(directory, reason='SUPERVISOR_INTERRUPTED')
        assert switched['phase'] == 'NEEDS_RECONCILIATION'
        assert switched['reconciliation_record_present']
        assert not switched['handoff_admissible']
        with pytest.raises(guard.DurableExclusionRefused):
            guard.require_reconciliation(directory, reason='SUPERVISOR_INTERRUPTED')
        child = subprocess.run([sys.executable, '-c', script, str(directory)],
                               env=env, capture_output=True, text=True, check=True)
        assert json.loads(child.stdout)['phase'] == 'NEEDS_RECONCILIATION'


def test_interrupted_publish_blocks_replay(monkeypatch):
    with _root_fixture() as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        def interrupted(*_args, **_kwargs):
            raise OSError('injected interruption before final rename')
        with monkeypatch.context() as patch:
            patch.setattr(guard.os, 'rename', interrupted)
            with pytest.raises(guard.DurableExclusionRefused, match='reconcile'):
                guard.prepare_blocked_journal(directory, **ARGS)
        assert (directory / guard._TEMP).exists()
        assert not (directory / guard._NAME).exists()
        with pytest.raises(guard.DurableExclusionRefused, match='interrupted'):
            guard.inspect_blocked_journal(directory)
        with pytest.raises(guard.DurableExclusionRefused, match='interrupted publication'):
            guard.prepare_blocked_journal(directory, **ARGS)


def test_symlink_and_world_writable_ancestry_refused():
    with _root_fixture() as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        other = directory / 'private'
        other.mkdir(mode=0o700)
        target = directory / 'redirect'
        target.symlink_to(other, target_is_directory=True)
        with pytest.raises(guard.DurableExclusionRefused):
            guard.prepare_blocked_journal(target, **ARGS)
        os.chmod(directory, 0o777)
        with pytest.raises(guard.DurableExclusionRefused):
            guard.prepare_blocked_journal(other, **ARGS)


def test_integrity_rejects_modified_record_even_with_digest_recomputed():
    with _root_fixture() as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        guard.prepare_blocked_journal(directory, **ARGS)
        path = directory / guard._NAME
        record = json.loads(path.read_text())
        record['host_wide_relaunch_excluded'] = True
        record = guard._sealed({k: v for k, v in record.items() if k != 'record_sha256'})
        path.write_bytes(guard._canonical(record))
        with pytest.raises(guard.DurableExclusionRefused, match='falsely asserts'):
            guard.inspect_blocked_journal(directory)


def test_different_boot_id_forces_reconciliation(monkeypatch):
    with _root_fixture() as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        guard.prepare_blocked_journal(directory, **ARGS)
        monkeypatch.setattr(guard, '_boot_id', lambda: '00000000-0000-0000-0000-000000000001')
        state = guard.inspect_blocked_journal(directory)
        assert state['phase'] == 'NEEDS_RECONCILIATION'
        assert not state['boot_id_matches']
        assert not state['handoff_admissible']


def test_non_root_refuses_even_when_home_directory_is_private():
    if os.geteuid() == 0:
        pytest.skip('non-root guard verified by normal Linux user host regression')
    with tempfile.TemporaryDirectory() as folder:
        with pytest.raises(guard.DurableExclusionRefused, match='root supervisor'):
            guard.prepare_blocked_journal(Path(folder), **ARGS)


def test_probe_rejects_live_path_or_release_switches():
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_recovery_release_durable_exclusion.py'
    for args in (['--release'], ['--simulate', '--original', '/home/legacy'],
                 ['--simulate', '--successor', '/tmp/foo']):
        run = subprocess.run([sys.executable, str(script), *args],
                             capture_output=True, text=True, timeout=10)
        assert run.returncode == 2
        assert 'only --simulate' in run.stderr
        assert not run.stdout
