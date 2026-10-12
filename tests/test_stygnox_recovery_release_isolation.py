"""Behavioural proof that process/cgroup inspection never grants handoff."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/probe_recovery_release_isolation.py'
spec = importlib.util.spec_from_file_location('release_isolation', SCRIPT)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def add_process(proc, pid, uid, cgroup, start='1234'):
    directory = proc / str(pid)
    directory.mkdir()
    (directory / 'cgroup').write_text('0::' + cgroup + '\n')
    (directory / 'status').write_text(f'Name:\tpython\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n')
    (directory / 'stat').write_text(f'{pid} (python) ' + ' '.join(['S'] * 19) + f' {start}\n')


def test_same_scope_refuses_freeze_in_current_supervisor(tmp_path):
    add_process(tmp_path, 101, 0, '/user.slice/user-1000.slice/session.scope')
    add_process(tmp_path, 102, 1000, '/user.slice/user-1000.slice/session.scope')
    result = preflight.collect(1000, proc=tmp_path, supervisor_pid=101, require_root=False)
    assert result['process_topology']['candidate_freeze_would_suspend_supervisor'] is True
    assert result['process_topology']['dedicated_root_supervisor_scope_required'] is True
    assert result['process_topology']['predecessor_uid_process_count'] == 1
    assert result['handoff_admissible'] is False
    assert result['authority_changed'] is False


def test_supervisor_elsewhere_does_not_claim_freeze_happened(tmp_path):
    add_process(tmp_path, 101, 0, '/system.slice/recovery-supervisor.service')
    add_process(tmp_path, 102, 1000, '/user.slice/user-1000.slice/session-a.scope')
    add_process(tmp_path, 103, 1000, '/user.slice/user-1000.slice/session-b.scope')
    result = preflight.collect(1000, proc=tmp_path, supervisor_pid=101, require_root=False)
    state = result['process_topology']
    assert state['candidate_common_freeze_subtree'] == '/user.slice/user-1000.slice'
    assert state['candidate_freeze_would_suspend_supervisor'] is False
    assert result['predecessor_processes_excluded'] is False
    assert result['original_binding_retired'] is False


def test_mixed_scopes_reject_hostwide_freeze(tmp_path):
    add_process(tmp_path, 101, 0, '/system.slice/recovery.service')
    add_process(tmp_path, 102, 1000, '/system.slice/misc.scope')
    add_process(tmp_path, 103, 1000, '/user.slice/user-1000.slice/user.scope')
    state = preflight.collect(1000, proc=tmp_path, supervisor_pid=101, require_root=False)['process_topology']
    assert state['candidate_common_freeze_subtree'] == '/'
    assert state['dedicated_root_supervisor_scope_required'] is True


def test_wrong_uid_and_unprivileged_refused(tmp_path, monkeypatch):
    with pytest.raises(preflight.IsolationRefused):
        preflight.collect(0, proc=tmp_path, require_root=False)
    add_process(tmp_path, 101, 0, '/system.slice/service')
    monkeypatch.setattr(preflight.os, 'geteuid', lambda: 1000)
    with pytest.raises(preflight.IsolationRefused):
        preflight.collect(1000, proc=tmp_path, supervisor_pid=101)


def test_malformed_cgroup_fails_closed(tmp_path):
    add_process(tmp_path, 101, 0, '/system.slice/supervisor')
    add_process(tmp_path, 102, 1000, '/user.slice/member')
    (tmp_path / '102' / 'cgroup').write_text('1:name=systemd:/x\n')
    report = preflight.collect(1000, proc=tmp_path, supervisor_pid=101, require_root=False)
    assert report['process_topology']['process_scan_incomplete_count'] == 1
    assert report['handoff_admissible'] is False


def test_actual_subprocess_stays_disallowed():
    result = subprocess.run([sys.executable, str(SCRIPT), '--predecessor-uid', '0'],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert 'REFUSED' in result.stderr
