"""R3D.2 root registry: real state, filesystem and broker-admission tests."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import tempfile

import pytest

from stygnox import direct_interruption_authority_cutover as cut
from stygnox import direct_interruption_epoch_reservation as epoch
from stygnox import direct_interruption_custody_intake as intake
from stygnox import direct_interruption_successor_broker as broker

BOOT = '11223344-1234-1234-1234-123456789abc'


def prepared(**changes):
    r = epoch.build_reservation(
        original_workspace_identity=(64512, 454849),
        isolated_manifest_sha256='a'*64, custody_sha256='b'*64,
        source_archive_sha256='c'*64, installed_source_files=680,
        successor_uid=995, boot_id=BOOT, epoch_nonce='d'*32)
    kwargs = {'reservation': r, 'custody_sha256': 'b'*64,
              'isolated_manifest_sha256': 'a'*64, 'installed_source_sha256': 'c'*64,
              'project_identity': (64512, 454849), 'boot_id': BOOT}
    kwargs.update(changes)
    return cut.build_prepared(**kwargs)


def test_prepared_record_is_denied_and_retains_exact_transaction():
    r = prepared()
    cut.validate_record(r)
    assert r['transaction_id'] == intake.TX
    assert r['approved_plan_hash'] == intake.PLAN
    assert r['current_step'] == 2 and r['recorded_continuations'] == 8
    assert r['completed_step_results'] == 1
    assert r['historic_state_trusted_by_new_broker'] is False
    assert r['legacy_process_launch_forbidden'] is False
    assert r['preopened_fds_revoked'] is False
    assert r['execution_authority'] == 'NONE'


def test_transitions_preserve_denial_and_bind_exact_owner():
    r0 = prepared()
    r1 = cut.build_transition(r0, phase=cut.PHASES[1])
    cut.validate_record(r1, previous=r0)
    r2 = cut.build_transition(r1, phase=cut.PHASES[2], pid=1234, process_start=5678)
    cut.validate_record(r2, previous=r1)
    assert r2['attested_pid'] == 1234
    for r in (r0, r1, r2):
        assert r['provider_executed'] is False
        assert r['successor_controller_execution_allowed'] is False
        assert r['operator_release_approved'] is False


@pytest.mark.parametrize('invalid', [
    {'custody_sha256': 'f'*64},
    {'isolated_manifest_sha256': 'e'*64},
    {'installed_source_sha256': '0'*64},
    {'project_identity': (64512, 555)},
    {'boot_id': '22222222-1234-1234-1234-123456789abc'},
])
def test_mismatched_protected_inputs_refuse(invalid):
    with pytest.raises(cut.AuthorityCutoverRefused):
        prepared(**invalid)


@pytest.mark.parametrize('phase,kwargs', [
    (cut.PHASES[2], {'pid': 123, 'process_start': 20}),
    (cut.PHASES[1], {'pid': 123, 'process_start': 20}),
    (cut.PHASES[2], {}),
    (cut.PHASES[1], {'pid': None, 'process_start': 999}),
])
def test_out_of_order_or_unbound_transitions_refuse(phase, kwargs):
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.build_transition(prepared(), phase=phase, **kwargs)


@pytest.mark.parametrize('key,value', [
    ('execution_authority', 'ACTIVE'), ('provider_executed', True),
    ('operator_release_approved', True),
    ('historic_state_trusted_by_new_broker', True),
    ('preopened_fds_revoked', True),
    ('successor_controller_execution_allowed', True),
    ('transaction_id', 'TX-forged'),
    ('recorded_continuations', 7),
    ('current_step', 1), ('original_project_path', '/tmp/new'),
])
def test_resealed_authority_escalation_or_wrong_binding_is_rejected(key, value):
    r = prepared()
    r[key] = value
    r = cut._seal({k: v for k, v in r.items() if k != 'record_sha256'})
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.validate_record(r)


def test_extra_key_resealed_is_rejected():
    r = prepared()
    r['operator_override'] = True
    r = cut._seal({k: v for k, v in r.items() if k != 'record_sha256'})
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.validate_record(r)


def test_broker_refuses_any_unrecorded_identity_even_with_known_epoch(monkeypatch):
    recorded = prepared()
    chain = [recorded, cut.build_transition(recorded, phase=cut.PHASES[1])]
    chain.append(cut.build_transition(chain[-1], phase=cut.PHASES[2], pid=345, process_start=876))
    monkeypatch.setattr(cut, 'read_chain', lambda *args, **kwargs: tuple(chain))
    inputs = {'owner': 0, 'peer_uid': 995, 'peer_pid': 345, 'peer_start': 876,
              'boot_id': BOOT, 'transaction_id': intake.TX, 'plan_hash': intake.PLAN,
              'source_sha256': 'c'*64, 'runtime_epoch': 'd'*32}
    assert cut.broker_admission(Path('/var/lib/stygnox'), **inputs)['execution_authority'] == 'NONE'
    for field, wrong in [('peer_uid', 1000), ('peer_uid', 0), ('peer_uid', 996),
                         ('peer_pid', 346), ('peer_start', 877),
                         ('boot_id', '11111111-1234-1234-1234-123456789abc'),
                         ('transaction_id', 'TX-old'), ('plan_hash', '0'*64),
                         ('source_sha256', '0'*64), ('runtime_epoch', '0'*32)]:
        with pytest.raises(cut.AuthorityCutoverRefused):
            cut.broker_admission(Path('/var/lib/stygnox'), **{**inputs, field: wrong})
    chain.pop()
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.broker_admission(Path('/var/lib/stygnox'), **inputs)


def test_kernel_start_parser_handles_spaced_parentheses(tmp_path):
    folder = tmp_path / '123'
    folder.mkdir()
    (folder / 'stat').write_text('123 (strange ) (process) here) S ' + ' '.join(
        str(i) if i != 22 else '987654' for i in range(4, 53)))
    assert broker.linux_process_start(123, proc=tmp_path) == 987654


@pytest.fixture
def private_root():
    if os.geteuid() != 0 or os.name != 'posix':
        pytest.skip('filesystem ancestry test requires isolated Linux root fixture')
    # Use / rather than /tmp; /tmp is world-writable and correctly refused.
    root = Path(tempfile.mkdtemp(prefix='.stygnox-cutover-test-', dir='/'))
    root.chmod(0o700)
    try:
        yield root
    finally:
        import shutil
        shutil.rmtree(root)


def test_chain_one_winner_reboot_and_full_root_barrier(private_root):
    root = private_root
    first = prepared()
    cut.publish_prepared(root, first, owner=0)
    assert [x['phase'] for x in cut.read_chain(root, owner=0)] == [cut.PHASES[0]]
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.publish_prepared(root, first, owner=0)

    def claim():
        try:
            cut.advance(root, owner=0, next_phase=cut.PHASES[1])
            return 1
        except cut.AuthorityCutoverRefused:
            return 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(lambda _: claim(), range(8))) == 1
    cut.advance(root, owner=0, next_phase=cut.PHASES[2],
                pid=os.getpid(), process_start=broker.linux_process_start(os.getpid()))
    assert len(cut.read_chain(root, owner=0)) == 3
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.advance(root, owner=0, next_phase=cut.PHASES[2], pid=4, process_start=5)
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.broker_admission(root, owner=0, peer_uid=1000,
            peer_pid=os.getpid(), peer_start=broker.linux_process_start(os.getpid()),
            boot_id=BOOT, transaction_id=intake.TX, plan_hash=intake.PLAN,
            source_sha256='c'*64, runtime_epoch='d'*32)


@pytest.mark.parametrize('attack', ['pending', 'extra', 'symlink', 'hardlink',
                                    'changed-hash', 'writable', 'missing'])
def test_root_chain_rejects_tamper_and_partial_cutover(private_root, attack):
    root = private_root
    cut.publish_prepared(root, prepared(), owner=0)
    folder = root / cut.SLOT
    member = folder / cut.MEMBERS[0]
    if attack == 'pending':
        (folder / (cut.MEMBERS[1]+'.pending')).touch()
    elif attack == 'extra':
        (folder / 'old-owner-approved.json').touch()
    elif attack == 'symlink':
        member.unlink()
        member.symlink_to('/etc/passwd')
    elif attack == 'hardlink':
        os.link(member, root / 'extra-hardlink')
    elif attack == 'changed-hash':
        member.chmod(0o600)
        member.write_bytes(b'{}\n')
        member.chmod(0o400)
    elif attack == 'writable':
        member.chmod(0o600)
    else:
        member.unlink()
    with pytest.raises((cut.AuthorityCutoverRefused, OSError)):
        cut.read_chain(root, owner=0)


def test_old_open_fd_cannot_change_independent_protected_inode(private_root):
    root = private_root
    old = root / 'old-history.txt'
    old.write_text('historical')
    held = os.open(old, os.O_RDWR)
    try:
        cut.publish_prepared(root, prepared(), owner=0)
        record = root / cut.SLOT / cut.MEMBERS[0]
        before = record.read_bytes()
        os.write(held, b'changed')
        assert old.read_bytes() != b'historical'
        assert record.read_bytes() == before
        assert old.stat().st_ino != record.stat().st_ino
    finally:
        os.close(held)


def test_pending_written_on_crash_remains_denied(private_root, monkeypatch):
    root = private_root
    cut.publish_prepared(root, prepared(), owner=0)
    def fail_rename(*args, **kwargs):
        raise OSError('injected pre-commit crash')
    monkeypatch.setattr(cut.os, 'link', fail_rename)
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.advance(root, owner=0, next_phase=cut.PHASES[1])
    assert (root / cut.SLOT / (cut.MEMBERS[1] + '.pending')).exists()
    with pytest.raises(cut.AuthorityCutoverRefused):
        cut.read_chain(root, owner=0)


def test_peer_service_check_requires_protected_script_and_named_cgroup(tmp_path):
    proc = tmp_path / '222'
    proc.mkdir()
    script = Path('/usr/local/libexec/stygnox-recovery-successor-new/scripts/stygnox_recovery_denied_worker.py')
    unit = 'stygnox-recovery-denied-worker.service'
    (proc / 'cmdline').write_bytes(b'/usr/bin/python3\0-I\0-B\0' + str(script).encode() + b'\0--denied-only\0')
    (proc / 'cgroup').write_text('0::/system.slice/stygnox-recovery-denied-worker.service\n')
    broker.verify_peer_service(222, script=script, unit=unit, proc=tmp_path)
    (proc / 'cgroup').write_text('0::/user.slice/user-1000.slice\n')
    with pytest.raises(broker.BrokerRefused):
        broker.verify_peer_service(222, script=script, unit=unit, proc=tmp_path)
    (proc / 'cgroup').write_text('0::/system.slice/stygnox-recovery-denied-worker.service\n')
    (proc / 'cmdline').write_bytes(b'/usr/bin/python3\0-I\0-B\0/tmp/copied-stygnox.py\0')
    with pytest.raises(broker.BrokerRefused):
        broker.verify_peer_service(222, script=script, unit=unit, proc=tmp_path)


def test_live_cutover_cli_rejects_mutable_checkout_before_loading_custody():
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/stygnox_recovery_integrated_cutover.py'
    run = subprocess.run([
        sys.executable, '-I', '-B', str(script), '--preview',
        '--installed-source', str(script.parents[1]),
        '--installed-archive', '/missing/untrusted', '--source-sha256', '0'*64],
        capture_output=True, text=True, timeout=10)
    assert run.returncode != 0
    assert 'require exact protected installed source' in run.stderr


def test_disposable_kernel_peer_refuses_legacy_uid_without_claim(private_root):
    """Real AF_UNIX/SO_PEERCRED test; no impersonation or broker mock."""
    if os.environ.get('STYGNOX_DISPOSABLE_LINUX_ROOT_TESTS') != 'YES_I_AM_DISPOSABLE':
        pytest.skip('requires explicitly opted-in disposable Linux root host')
    import socket
    import shutil
    folder = private_root.parent / (private_root.name + '-socket')
    folder.mkdir(mode=0o711)
    socket_path = folder / 'broker.sock'
    context = broker.DeniedContext(
        transaction_id=intake.TX, plan_sha256=intake.PLAN,
        epoch='d'*32, successor_uid=1201, source_sha256='c'*64,
        host_boot_id=BOOT, reservation_sha256='f'*64,
        authority_root=private_root, authority_owner=0,
        worker_script=Path('/usr/local/libexec/stygnox-recovery-successor-test/scripts/stygnox_recovery_denied_worker.py'),
        worker_unit='stygnox-recovery-denied-worker.service')
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(socket_path))
        socket_path.chmod(0o666)
        server.listen(1)
        report_read, report_write = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(report_read)
            try:
                os.setgroups([])
                os.setgid(1000)
                os.setuid(1000)
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(5)
                    client.connect(str(socket_path))
                    client.sendall(b'{}\n')
                    try:
                        reply = client.recv(512)
                    except ConnectionResetError:
                        reply = b''  # Kernel closes unread unauthorized socket.
                    if reply != b'':
                        os._exit(44)
                os._exit(0)
            except BaseException as exc:
                os.write(report_write, repr(exc).encode())
                os._exit(45)
        try:
            conn, _ = server.accept()
            broker.handle_connection(conn, context)
            _, status = os.waitpid(child, 0)
            os.close(report_write)
            diagnostic = os.read(report_read, 2048).decode()
            assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, diagnostic
            assert not (private_root / cut.SLOT).exists()
        finally:
            try:
                os.waitpid(child, os.WNOHANG)
            except ChildProcessError:
                pass
            os.close(report_read)
            socket_path.unlink()
            folder.rmdir()
