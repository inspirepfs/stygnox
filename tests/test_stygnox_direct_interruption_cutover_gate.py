"""Hostile behavioural regression of the read-only exclusive cutover gate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import io

import pytest

from stygnox import direct_interruption_cutover_gate as gate


def test_path_match_is_absolute_and_boundary_correct():
    original = gate.ORIGINAL
    assert gate._inside(str(original), original)
    assert gate._inside(str(original / '.stygnox' / 'plan.json'), original)
    assert gate._inside(str(original) + ' (deleted)', original)
    assert not gate._inside(str(original) + '-copy/.stygnox/plan.json', original)
    assert not gate._inside('relative/stygnox-r3d2-astra', original)


def test_proc_scanner_observes_real_live_fd_and_cwd(tmp_path):
    old = tmp_path / 'live-project'
    old.mkdir()
    path = old / 'plan.json'
    path.write_text('historical work, never executable')
    runner = subprocess.Popen(
        [sys.executable, '-c',
         'import os,sys,time; h=open(sys.argv[1]); os.chdir(sys.argv[2]); '
         'print("READY", flush=True); time.sleep(15)', str(path), str(old)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert runner.stdout is not None
        assert runner.stdout.readline().strip() == 'READY'
        result = gate.scan_live_holders(original=old, uid=os.getuid())
        found = [r for r in result['workspace_holders'] if r['pid'] == runner.pid]
        assert found, 'live inode holder was omitted from process inventory'
        assert 'cwd' in found[0]['references']
        assert any(ref.startswith('fd:') for ref in found[0]['references'])
        assert result['preopened_fds_revoked'] is False
        assert result['future_predecessor_relaunch_excluded'] is False
    finally:
        runner.terminate()
        runner.wait(timeout=5)


def test_proc_scanner_uncertain_task_is_not_treated_as_clean(tmp_path):
    proc = tmp_path / 'proc'
    task = proc / '123'
    task.mkdir(parents=True)
    (task / 'status').write_text('Name:\tx\nUid:\t1000\t1000\t1000\t1000\n')
    # No cwd/root/exe/fd/maps: process cannot be inspected completely.
    result = gate.scan_live_holders(proc=proc)
    assert result['uncertain_processes'] == [123]
    assert result['all_visible_processes_observed'] is False
    assert result['future_predecessor_relaunch_excluded'] is False


def test_proc_scanner_rejects_relative_project(tmp_path):
    with pytest.raises(gate.CutoverGateRefused):
        gate.scan_live_holders(proc=tmp_path, original=Path('relative'))


def _fixture():
    if os.geteuid() != 0 or not Path('/root').is_dir():
        pytest.skip('requires disposable root-owned Linux filesystem fixture')
    return tempfile.TemporaryDirectory(dir='/root', prefix='stygnox-cutover-test-')


def _write_fixture(root: Path, *, members=None):
    source = root / 'installed'
    source.mkdir(mode=0o555)
    archived = root / 'source.tar'
    mapping = members or {'src/stygnox/example.py': b'not executable',
                          'scripts/deny.py': b'print("denied")'}
    with tarfile.open(archived, 'w:') as tar:
        for name, raw in sorted(mapping.items()):
            parent = source / name
            parent.parent.mkdir(parents=True, exist_ok=True)
            parent.write_bytes(raw)
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o444
            tar.addfile(info, io.BytesIO(raw))
    for d in source.rglob('*'):
        if d.is_dir():
            d.chmod(0o555)
        else:
            d.chmod(0o444)
    source.chmod(0o555)
    archived.chmod(0o400)
    return source, archived, hashlib.sha256(archived.read_bytes()).hexdigest()


def test_artifact_audit_matches_real_readonly_source_files():
    with _fixture() as location:
        source, archive, sha = _write_fixture(Path(location))
        result = gate.installed_artifact_audit(source=source, archive=archive, expected_sha=sha)
        assert result['installed_source_file_count'] == 2
        assert result['installed_artifact_bytes_verified'] is True


@pytest.mark.parametrize('attack', ['changed', 'extra', 'removed', 'symlink',
                                    'hardlink', 'writable', 'bad-digest', 'extra-dir', 'writable-dir'])
def test_artifact_hostile_member_refused(attack):
    with _fixture() as location:
        root = Path(location)
        source, archive, sha = _write_fixture(root)
        victim = source / 'scripts/deny.py'
        if attack == 'changed':
            victim.chmod(0o600)
            victim.write_bytes(b'allow provider execution!')
            victim.chmod(0o444)
        elif attack == 'extra':
            path = source / 'extra.py'
            path.write_text('x')
            path.chmod(0o444)
        elif attack == 'removed':
            victim.unlink()
        elif attack == 'symlink':
            victim.unlink()
            victim.symlink_to(source / 'src/stygnox/example.py')
        elif attack == 'hardlink':
            os.link(victim, root / 'file-link')
        elif attack == 'writable':
            victim.chmod(0o644)
        elif attack == 'bad-digest':
            sha = 'f' * 64
        elif attack == 'extra-dir':
            (source / 'undeclared').mkdir(mode=0o555)
        elif attack == 'writable-dir':
            (source / 'scripts').chmod(0o755)
        with pytest.raises(gate.CutoverGateRefused):
            gate.installed_artifact_audit(source=source, archive=archive, expected_sha=sha)


def test_invalid_source_digest_rejected_without_touching_files():
    with pytest.raises(gate.CutoverGateRefused):
        gate.installed_artifact_audit(expected_sha='invalid')


def test_cutover_cli_denies_all_paths_from_mutable_checkout():
    cli = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_cutover_gate.py'
    for args in ([], ['--audit-read-only'], ['--release'], ['--commission'],
                 ['--retire-original'], ['--approve']):
        result = subprocess.run([sys.executable, '-I', '-B', str(cli), *args],
                                text=True, capture_output=True, check=False)
        assert result.returncode == 75
        assert result.stderr == ''
        report = json.loads(result.stdout)
        assert report['phase'] == 'HOST_CUTOVER_REFUSED'
        assert report['successor_execution_authorised'] is False
        assert report['provider_executed'] is False


def test_privileged_checkout_guard_blocks_import_side_effect(tmp_path):
    if os.geteuid() != 0:
        pytest.skip('requires root to prove import guard')
    cli = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_cutover_gate.py'
    source = tmp_path / 'fake'
    (source / 'scripts').mkdir(parents=True)
    (source / 'src/stygnox').mkdir(parents=True)
    dest = source / 'scripts/stygnox_recovery_cutover_gate.py'
    dest.write_bytes(cli.read_bytes())
    marker = tmp_path / 'untrusted-imported'
    (source / 'src/stygnox/direct_interruption_cutover_gate.py').write_text(
        f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
    result = subprocess.run([sys.executable, '-I', '-B', str(dest), '--audit-read-only'],
                            text=True, capture_output=True, check=False)
    assert result.returncode == 75
    assert not marker.exists()


def test_gate_contract_never_invents_authority():
    report = gate.denied_report()
    assert report['execution_authority'] == 'NONE'
    assert report['successor_execution_authorised'] is False
    assert report['provider_executed'] is False


def test_denied_successor_probe_cannot_claim_execution():
    probe = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_successor_denied_probe.py'
    for args in (['--probe-denied-only'], ['--execute-provider'], [], ['--release']):
        completed = subprocess.run([sys.executable, '-I', '-B', str(probe), *args],
                                   text=True, capture_output=True, check=False)
        assert completed.returncode == 75
        assert completed.stderr == ''
        report = json.loads(completed.stdout)
        assert report['controller_admitted'] is False
        assert report['root_custody_access_attempted'] is False
        assert report['provider_executed'] is False
        assert report['successor_execution_authorised'] is False


def test_denied_successor_systemd_template_has_no_live_source_or_provider():
    template = (Path(__file__).resolve().parents[1] /
                'docs/recovery-r3d2-denied-successor.service.in').read_text()
    assert 'ExecStart=/usr/bin/python3 -I -B @@SOURCE@@/scripts/stygnox_recovery_successor_denied_probe.py --probe-denied-only' in template
    for expected in ('DynamicUser=yes', 'PrivateNetwork=yes', 'ProtectHome=yes',
                     'NoNewPrivileges=yes', 'ProtectSystem=strict',
                     'CapabilityBoundingSet=', 'SuccessExitStatus=75',
                     'Restart=no'):
        assert expected in template
    assert 'stygnox-r3d2-astra' not in template
    assert 'User=pfsykes' not in template
    assert '@@SOURCE@@' in template
