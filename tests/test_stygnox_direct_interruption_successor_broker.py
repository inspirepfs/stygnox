"""Hostile broker protocol and kernel-credential tests; no mocked provider."""
import json
import os
from pathlib import Path
import socket
import sys
import stat
import threading

import pytest

from stygnox import direct_interruption_epoch_reservation as epoch
from stygnox import direct_interruption_successor_broker as broker


BOOT = '00000000-1111-2222-3333-444444444444'


def reserved(uid=995, **overrides):
    params = dict(original_workspace_identity=(64512, 454849),
                  isolated_manifest_sha256='a'*64, custody_sha256='b'*64,
                  source_archive_sha256='c'*64, installed_source_files=674,
                  successor_uid=uid, boot_id=BOOT, epoch_nonce='d'*32)
    params.update(overrides)
    return epoch.build_reservation(**params)


def context(uid=995):
    return broker.DeniedContext.from_reservation(reserved(uid),
               pinned_source_sha256='c'*64, boot_id=BOOT)


def request(**changes):
    r = dict(schema=broker.SCHEMA, operation='attest-denial',
             transaction_id=epoch.intake.TX,
             approved_plan_hash=epoch.intake.PLAN, runtime_epoch='d'*32,
             installed_source_archive_sha256='c'*64)
    r.update(changes)
    return r


def test_successful_attestation_never_grants_authority():
    answer = json.loads(context().answer(peer_uid=995, message=request()))
    assert answer['phase'] == 'SUCCESSOR_IDENTITY_ATTESTED_EXECUTION_DENIED'
    assert answer['execution_authority'] == 'NONE'
    assert answer['legacy_controller_excluded'] is False
    assert answer['controller_admitted'] is False
    assert answer['successor_execution_authorised'] is False
    assert answer['provider_executed'] is False


@pytest.mark.parametrize('uid', [0, 1000, 1, 994, -1])
def test_no_other_uid_can_attest(uid):
    with pytest.raises(broker.BrokerRefused, match='UNAUTHORISED_PEER'):
        context().answer(peer_uid=uid, message=request())


@pytest.mark.parametrize('bad', [
    {'operation':'execute'}, {'operation':'approve'}, {'operation':'continue-step'},
    {'runtime_epoch':'f'*32}, {'transaction_id':'TX-other'},
    {'approved_plan_hash':'a'*64}, {'installed_source_archive_sha256':'f'*64},
    {'schema':'old'}, {'caller_uid':995},
])
def test_privilege_extension_and_replay_fail(bad):
    with pytest.raises(broker.BrokerRefused):
        context().answer(peer_uid=995, message=request(**bad))


def test_source_and_boot_identity_mismatch_are_denied():
    with pytest.raises(broker.BrokerRefused):
        broker.DeniedContext.from_reservation(reserved(), pinned_source_sha256='e'*64,
                                              boot_id=BOOT)
    with pytest.raises(broker.BrokerRefused):
        broker.DeniedContext.from_reservation(reserved(), pinned_source_sha256='c'*64,
                                              boot_id='12345678-1234-1234-1234-123456789abc')


def _roundtrip(data, *, accepted=True, ctx=None):
    left, right = socket.socketpair()
    ctx = ctx or context(os.getuid())
    # socketpair uses *real kernel* credentials, never caller-supplied UID.
    thread = threading.Thread(target=broker.handle_connection, args=(left, ctx))
    thread.start()
    try:
        right.settimeout(5.0)
        try:
            right.sendall(data)
            right.shutdown(socket.SHUT_WR)
            result = right.recv(4096)
        except BrokenPipeError:
            result = b''
    finally:
        right.close()
        thread.join(timeout=6.0)
    assert not thread.is_alive()
    if accepted:
        assert json.loads(result)['execution_authority'] == 'NONE'
    else:
        assert result == b''


@pytest.mark.skipif(os.getuid() in (0, 1000), reason='needs a non-root/non-legacy UID')
def test_socket_kernel_peer_creds_and_protocol():
    _roundtrip(broker._canonical(request()))
    _roundtrip(broker._canonical(request(operation='run')), accepted=False)
    _roundtrip(broker._canonical(request())[:-1], accepted=False)
    _roundtrip(b'{}\n', accepted=False)
    _roundtrip(b' ' + broker._canonical(request()), accepted=False)
    _roundtrip(b'x'*4100 + b'\n', accepted=False)


def test_real_socket_denies_uid_other_than_successor():
    if os.getuid() != 995:
        _roundtrip(broker._canonical(request()), accepted=False, ctx=context(995))


def test_same_uid_cannot_forge_kernel_identity():
    # Client's declared UID isn't an accepted parameter at all.
    with pytest.raises(broker.BrokerRefused):
        context(os.getuid() if os.getuid() not in (0,1000) else 995).answer(
            peer_uid=1000, message=request(caller_uid=995))


def test_root_only_socket_rejects_user_owned_ancestors(tmp_path):
    target = tmp_path / 'broker.sock'
    with pytest.raises(broker.BrokerRefused):
        broker.bind_private_socket(target, successor_gid=995)
    assert not target.exists()


def test_real_root_socket_inode_and_race_refusal(tmp_path):
    if os.geteuid() != 0:
        pytest.skip('requires Linux root fixture')
    # temp parent normally has user-owned ancestors on some hosts; root in
    # container verifies only when all ancestors are trusted.
    directory = tmp_path / 'broker'
    directory.mkdir()
    os.chown(directory, 0, 995)
    directory.chmod(0o710)
    target = directory / 'broker.sock'
    try:
        server = broker.bind_private_socket(target, successor_gid=995)
    except broker.BrokerRefused as exc:
        pytest.skip(f'root-owned ancestry is unavailable in fixture: {exc}')
    try:
        st = target.lstat()
        assert stat.S_ISSOCK(st.st_mode)
        assert st.st_uid == 0 and st.st_gid == 995
        assert stat.S_IMODE(st.st_mode) == 0o660
        with pytest.raises(broker.BrokerRefused):
            broker.bind_private_socket(target, successor_gid=995)
    finally:
        server.close()


def test_disposable_linux_kernel_uid_and_path_enforcement():
    """Real root-created AF_UNIX socket, peer credentials and unrelated UID."""
    if (sys.platform != 'linux' or os.geteuid() != 0 or
            os.environ.get('STYGNOX_DISPOSABLE_LINUX_ROOT_TESTS') != 'YES_I_AM_DISPOSABLE'):
        pytest.skip('requires explicitly opted-in disposable root Linux environment')
    import tempfile
    import subprocess
    with tempfile.TemporaryDirectory(prefix='stygnox-broker-', dir='/run') as tmp:
        directory = Path(tmp)
        os.chown(directory, 0, 65533)
        directory.chmod(0o710)
        target = directory / 'denied.sock'
        server = broker.bind_private_socket(target, successor_gid=65533)
        def process_one():
            incoming, _ = server.accept()
            broker.handle_connection(incoming, context(65533))
        try:
            req = broker._canonical(request())
            code = ('import socket,sys; s=socket.socket(socket.AF_UNIX); '
                    's.connect(sys.argv[1]); s.sendall(sys.stdin.buffer.read()); '
                    's.shutdown(socket.SHUT_WR); sys.stdout.buffer.write(s.recv(4096))')
            def drop():
                os.setgroups([])
                os.setgid(65533)
                os.setuid(65533)
            t = threading.Thread(target=process_one)
            t.start()
            ok = subprocess.run([sys.executable, '-I', '-c', code, str(target)],
                                input=req, capture_output=True, timeout=10,
                                preexec_fn=drop)
            t.join(timeout=10)
            assert not t.is_alive()
            assert ok.returncode == 0, ok.stderr.decode()
            assert json.loads(ok.stdout)['phase'] == 'SUCCESSOR_IDENTITY_ATTESTED_EXECUTION_DENIED'
            # A disallowed UID cannot access the socket via filesystem mode.
            def old_uid():
                os.setgroups([])
                os.setgid(1000)
                os.setuid(1000)
            denied = subprocess.run([sys.executable, '-I', '-c', code, str(target)],
                                    input=req, capture_output=True, timeout=10,
                                    preexec_fn=old_uid)
            assert denied.returncode != 0
            assert b'PermissionError' in denied.stderr
            assert stat.S_IMODE(target.lstat().st_mode) == 0o660
            with pytest.raises(broker.BrokerRefused):
                broker.bind_private_socket(target, successor_gid=65533)
            # Root can bypass socket file mode, but kernel credentials still
            # prevent it from pretending to be the successor UID.
            t2 = threading.Thread(target=process_one)
            t2.start()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as root_client:
                root_client.settimeout(5)
                root_client.connect(str(target))
                try:
                    root_client.sendall(req)
                except BrokenPipeError:
                    pass
                try:
                    assert root_client.recv(4096) == b''
                except ConnectionResetError:
                    pass  # Kernel reset because unauthorised peer sent unread bytes.
            t2.join(timeout=10)
            assert not t2.is_alive()
        finally:
            server.close()
            target.unlink()
