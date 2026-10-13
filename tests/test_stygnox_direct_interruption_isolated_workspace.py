"""Hostile behavioural tests for DENY-ONLY isolated successor worktree staging."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

from stygnox import direct_interruption_custody_cutover as custody
from stygnox import direct_interruption_custody_intake as intake
from stygnox import direct_interruption_isolated_workspace as workspace
from test_stygnox_direct_interruption_custody_cutover import inputs


def fixture():
    original, payload = inputs()
    files = {
        '.stygnox/plan.json': custody._canonical(original['plan']),
        '.stygnox/controller.json': custody._canonical(original['controller']),
        '.stygnox/transaction.json': custody._canonical(original['transaction']),
        '.stygnox/qualification.json': b'{"historical":true}\n',
        'src/stygnox/example.py': b'raise RuntimeError("never execute reconstructed historical source")\n',
        'docs/retained.md': b'historical record\n',
    }
    records, manifest = workspace._prepare(
        files, payload['projection'],
        custody_sha256=payload['cutover']['record_sha256'],
        candidate_manifest_sha256=intake.EXPECTED['candidate'],
    )
    return files, records, manifest


def publish(tmp_path):
    source, records, manifest = fixture()
    receipt = workspace._publish(tmp_path, records, manifest, uid=os.geteuid())
    return source, records, manifest, receipt


def test_workspace_inodes_and_quarantine_records_are_independent(tmp_path):
    source, staged, manifest, receipt = publish(tmp_path)
    assert receipt['phase'] == 'ISOLATED_WORKSPACE_STAGED_EXECUTION_DENIED'
    assert receipt['successor_execution_authorised'] is False
    assert staged['src/stygnox/example.py'] == source['src/stygnox/example.py']
    assert staged['.stygnox/plan.json'] != source['.stygnox/plan.json']
    assert len(manifest['workspace_files']) == len(source) + 1
    result = workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())
    assert result['file_count'] == len(source) + 1
    assert result['legacy_controller_excluded'] is False
    assert stat.S_IMODE((tmp_path / workspace.SLOT).stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o400 for p in
               (tmp_path / workspace.SLOT / 'workspace').rglob('*') if p.is_file())
    assert not (tmp_path / workspace.SLOT / 'workspace/.stygnox' /
                'direct-interruption-quarantined-binding.json').stat().st_mode & 0o222


def test_copy_disjoint_from_old_candidate_fd_and_does_not_mutate_original(tmp_path):
    source, records, manifest = fixture()
    original = tmp_path / 'old-candidate'
    original.mkdir()
    (original / 'src').mkdir()
    old_file = original / 'src' / 'example.py'
    old_file.write_bytes(source['src/stygnox/example.py'])
    fd = os.open(old_file, os.O_RDWR)
    try:
        workspace._publish(tmp_path, records, manifest, uid=os.geteuid())
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, b'changed historical holder bytes')
        os.fsync(fd)
        new_file = (tmp_path / workspace.SLOT / 'workspace/src/stygnox/example.py')
        assert new_file.read_bytes() == source['src/stygnox/example.py']
        assert old_file.stat().st_ino != new_file.stat().st_ino
    finally:
        os.close(fd)
    # Test does not claim the original FD was revoked: that is the unresolved
    # legacy authority problem; only the fresh stage is inaccessible to it.


@pytest.mark.parametrize('target', [
    'src/stygnox/example.py', '.stygnox/plan.json',
    '.stygnox/controller.json', '.stygnox/transaction.json',
    '.stygnox/direct-interruption-quarantined-binding.json',
])
def test_tamper_of_staged_inode_is_detected(tmp_path, target):
    publish(tmp_path)
    path = tmp_path / workspace.SLOT / 'workspace' / target
    path.chmod(0o600)
    path.write_bytes(b'corrupt authority or source')
    path.chmod(0o400)
    with pytest.raises(workspace.IsolatedWorkspaceRefused):
        workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())


def test_duplicate_publication_and_preexisting_pending_are_refused(tmp_path):
    _, records, manifest, _ = publish(tmp_path)
    with pytest.raises(workspace.IsolatedWorkspaceRefused, match='exists'):
        workspace._publish(tmp_path, records, manifest, uid=os.geteuid())
    assert workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())
    (tmp_path / (workspace.SLOT + '.pending')).mkdir()
    with pytest.raises(workspace.IsolatedWorkspaceRefused, match='pending'):
        workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())


def test_interrupt_leaves_pending_never_retry_or_automatically_clean(tmp_path, monkeypatch):
    _, records, manifest = fixture()
    real_write = workspace._write_new
    calls = 0

    def fail_after_first(fd, name, raw):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('simulated process death mid-copy')
        return real_write(fd, name, raw)

    monkeypatch.setattr(workspace, '_write_new', fail_after_first)
    with pytest.raises(workspace.IsolatedWorkspaceRefused, match='interrupted'):
        workspace._publish(tmp_path, records, manifest, uid=os.geteuid())
    assert (tmp_path / (workspace.SLOT + '.pending')).is_dir()
    assert not (tmp_path / workspace.SLOT).exists()
    monkeypatch.setattr(workspace, '_write_new', real_write)
    with pytest.raises(workspace.IsolatedWorkspaceRefused, match='interrupted'):
        workspace._publish(tmp_path, records, manifest, uid=os.geteuid())


def test_concurrent_claims_only_one_publishes(tmp_path):
    _, records, manifest = fixture()

    def claim(_):
        try:
            workspace._publish(tmp_path, records, manifest, uid=os.geteuid())
            return 'STAGED'
        except workspace.IsolatedWorkspaceRefused:
            return 'DENIED'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == ['DENIED', 'STAGED']
    assert workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())


@pytest.mark.parametrize('name', [
    '../escape', '/absolute', 'a//b', 'a/../b', 'a/./b',
    'a\\b', '.stygnox/direct-interruption-quarantined-binding.json',
])
def test_untrusted_source_path_never_published(tmp_path, name):
    _, payload = inputs()
    files = {'.stygnox/plan.json': b'p', '.stygnox/controller.json': b'c',
             '.stygnox/transaction.json': b't', name: b'suspect'}
    with pytest.raises(workspace.IsolatedWorkspaceRefused):
        workspace._prepare(files, payload['projection'],
                           custody_sha256=payload['cutover']['record_sha256'],
                           candidate_manifest_sha256=intake.EXPECTED['candidate'])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('hostile', ['wrong-mode', 'symlink', 'hardlink',
                                     'extra-member', 'missing', 'manifest', 'authority',
                                     'wrong-dir-owner', 'extra-directory'])
def test_hostile_staged_workspace_refused(tmp_path, hostile):
    publish(tmp_path)
    slot = tmp_path / workspace.SLOT
    path = slot / 'workspace/docs/retained.md'
    if hostile == 'wrong-mode':
        path.chmod(0o600)
    elif hostile == 'symlink':
        path.unlink()
        path.symlink_to(slot / 'isolated-workspace.json')
    elif hostile == 'hardlink':
        os.link(path, tmp_path / 'alias')
    elif hostile == 'extra-member':
        (slot / 'workspace/malicious.txt').touch()
    elif hostile == 'missing':
        path.unlink()
    elif hostile == 'manifest':
        target = slot / 'isolated-workspace.json'
        target.chmod(0o600)
        payload = json.loads(target.read_text())
        payload['successor_execution_authorised'] = True
        target.write_bytes(workspace._canonical(payload))
        target.chmod(0o400)
    elif hostile == 'authority':
        path = slot / 'workspace/.stygnox/plan.json'
        path.chmod(0o600)
        payload = json.loads(path.read_text())
        payload['execution_authority_granted'] = True
        payload.pop('record_sha256')
        payload['record_sha256'] = hashlib.sha256(intake._canonical(payload)).hexdigest()
        path.write_bytes(workspace._canonical(payload))
        path.chmod(0o400)
    elif hostile == 'wrong-dir-owner':
        (slot / 'workspace').chmod(0o755)
    elif hostile == 'extra-directory':
        (slot / 'workspace/extra').mkdir()
    with pytest.raises(workspace.IsolatedWorkspaceRefused):
        workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())


def test_copy_alias_detection_requires_distinct_inodes(tmp_path):
    source, records, manifest = fixture()
    _, _, _, _ = publish(tmp_path)
    original = tmp_path / 'original-candidate'
    (original / 'src/stygnox').mkdir(parents=True)
    copied = tmp_path / workspace.SLOT / 'workspace/src/stygnox/example.py'
    # Build a hardlink to the staged file, simulating a link to the original.
    os.link(copied, original / 'src/stygnox/example.py')
    with pytest.raises(workspace.IsolatedWorkspaceRefused):
        workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid(), old_candidate=original)


def test_mutated_manifest_rehash_never_enables_authority(tmp_path):
    _, records, manifest = fixture()
    forbidden = deepcopy(manifest)
    forbidden['successor_execution_authorised'] = True
    forbidden.pop('record_sha256')
    forbidden['record_sha256'] = hashlib.sha256(intake._canonical(forbidden)).hexdigest()
    with pytest.raises(workspace.IsolatedWorkspaceRefused):
        workspace._publish(tmp_path, records, forbidden, uid=os.geteuid())


def test_cli_release_attempts_and_sudo_mutable_checkout_refuse(tmp_path):
    cli = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_isolated_workspace.py'
    for argv in ([], ['--prepare-data-only'], ['--verify-data-only'],
                 ['--release'], ['--execute'], ['--override']):
        completed = subprocess.run([sys.executable, '-I', '-B', str(cli), *argv],
                                   capture_output=True, text=True, check=False)
        assert completed.returncode == 75, completed.stderr
        assert completed.stderr == ''
        data = json.loads(completed.stdout)
        assert data['successor_execution_authorised'] is False
        assert data['provider_executed'] is False
    if os.geteuid() == 0:
        fake = tmp_path / 'untrusted-copy'
        (fake / 'scripts').mkdir(parents=True)
        (fake / 'src/stygnox').mkdir(parents=True)
        shutil.copyfile(cli, fake / 'scripts/stygnox_recovery_isolated_workspace.py')
        sentinel = tmp_path / 'unsafe-import-detected'
        (fake / 'src/stygnox/direct_interruption_isolated_workspace.py').write_text(
            f'from pathlib import Path\nPath({str(sentinel)!r}).touch()\n')
        result = subprocess.run([sys.executable, '-I', '-B',
                                 str(fake / 'scripts/stygnox_recovery_isolated_workspace.py'),
                                 '--prepare-data-only'], capture_output=True, text=True)
        assert result.returncode == 75
        assert not sentinel.exists()


def test_real_unprivileged_uid_cannot_read_isolated_staged_worktree(tmp_path):
    """Real OS check: a distinct UID cannot open root-private new files."""
    if os.geteuid() != 0 or not hasattr(os, 'setgroups'):
        pytest.skip('requires disposable Linux root test host')
    import tempfile
    with tempfile.TemporaryDirectory(prefix='stygnox-denial-', dir='/tmp') as parent:
        root = Path(parent)
        _, records, manifest = fixture()
        workspace._publish(root, records, manifest, uid=0)
        sealed = root / workspace.SLOT / 'workspace/.stygnox/plan.json'
        assert sealed.read_bytes()
        # A traversable staging PARENT isolates the proof to the 0700 slot.
        root.chmod(0o711)
        script = ('import sys\n'
                  'from pathlib import Path\n'
                  'try: Path(sys.argv[1]).read_bytes()\n'
                  'except PermissionError: sys.exit(77)\n'
                  'else: sys.exit(0)\n')

        def drop_identity():
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)

        try:
            outcome = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                                      str(sealed)], preexec_fn=drop_identity,
                                     capture_output=True, text=True, check=False)
            assert outcome.returncode == 77, outcome.stderr
        finally:
            root.chmod(0o700)


def test_ordinary_execution_guard_denies_staged_workspace(tmp_path):
    from stygnox import direct_interruption_execution_guard as execution_guard
    publish(tmp_path)
    project = tmp_path / workspace.SLOT / 'workspace'
    with pytest.raises(execution_guard.QuarantinedRuntime, match='RECOVERY_QUARANTINED'):
        execution_guard.refuse_quarantined_runtime(project)


def test_fifo_and_disguised_member_refused_without_blocking(tmp_path):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('host lacks POSIX fifo')
    publish(tmp_path)
    target = tmp_path / workspace.SLOT / 'workspace/docs/retained.md'
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(workspace.IsolatedWorkspaceRefused):
        workspace.verify_isolated_workspace(tmp_path, uid=os.geteuid())
