"""Actual filesystem-based denied-epoch publication tests, no provider mocks."""
import json
import subprocess
import sys
import os
from pathlib import Path
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from stygnox import direct_interruption_epoch_reservation as epoch


BOOT = '00000000-1111-2222-3333-444444444444'


def record(**changes):
    args = {
        'original_workspace_identity': (64512, 454849),
        'isolated_manifest_sha256': 'a' * 64,
        'custody_sha256': 'b' * 64,
        'source_archive_sha256': 'c' * 64,
        'installed_source_files': 674,
        'successor_uid': 995,
        'boot_id': BOOT,
        'epoch_nonce': 'd' * 32,
    }
    args.update(changes)
    return epoch.build_reservation(**args)


def directory(tmp_path):
    root = tmp_path / 'custody'
    root.mkdir(mode=0o700)
    return root


def test_record_is_exact_identity_bound_and_never_admits_provider():
    r = record()
    epoch.validate_reservation(r)
    assert r['execution_authority'] == 'NONE'
    assert r['controller_admitted'] is False
    assert r['predecessor_execution_excluded'] is False
    assert r['provider_executed'] is False
    assert r['step'] == 2 and r['recorded_continuations'] == 8


@pytest.mark.parametrize('change', [
    {'successor_uid': 1000}, {'successor_uid': 0},
    {'successor_uid': True}, {'successor_uid': -1},
    {'original_workspace_identity': (0, 11)},
    {'original_workspace_identity': (11, -1)},
    {'epoch_nonce': 'wrong'}, {'epoch_nonce': 'd' * 30},
    {'boot_id': 'not-a-boot-uuid'},
    {'isolated_manifest_sha256': 'bad'},
    {'source_archive_sha256': 'bad'},
    {'installed_source_files': 0},
])
def test_invalid_preconditions_cannot_reserve(change):
    with pytest.raises(epoch.EpochReservationRefused):
        record(**change)


@pytest.mark.parametrize('key, value', [
    ('provider_executed', True), ('predecessor_execution_excluded', True),
    ('controller_admitted', True), ('successor_execution_authorised', True),
    ('operator_release_approved', True), ('execution_authority', 'ACTIVE'),
    ('transaction_id', 'TX-forged'), ('runtime_epoch', 'invalid'),
    ('approved_plan_hash', '9'*64), ('step', 1),
])
def test_reservation_tampering_fails_even_with_valid_recomputed_digest(key, value):
    r = record()
    r[key] = value
    r = epoch._seal({k: v for k, v in r.items() if k != 'record_sha256'})
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.validate_reservation(r)


def test_real_filesystem_one_shot_and_readback(tmp_path):
    root = directory(tmp_path)
    r = record()
    result = epoch.publish_reservation(root, r, owner=os.getuid())
    assert result['successor_execution_authorised'] is False
    assert result['provider_executed'] is False
    saved = epoch.read_reservation(root, owner=os.getuid())
    assert saved == r
    assert stat.S_IMODE((root / epoch.SLOT).stat().st_mode) == 0o700
    assert stat.S_IMODE((root / epoch.SLOT / 'epoch-reservation.json').stat().st_mode) == 0o400
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.publish_reservation(root, record(epoch_nonce='e'*32), owner=os.getuid())
    assert epoch.read_reservation(root, owner=os.getuid()) == r


def test_concurrent_claims_only_one_wins(tmp_path):
    root = directory(tmp_path)
    claims = [record(epoch_nonce=f'{i:032x}') for i in range(1, 9)]

    def attempt(r):
        try:
            epoch.publish_reservation(root, r, owner=os.getuid())
            return r['runtime_epoch']
        except epoch.EpochReservationRefused:
            return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        outcomes = list(workers.map(attempt, claims))
    winners = [x for x in outcomes if x is not None]
    assert len(winners) == 1
    assert epoch.read_reservation(root, owner=os.getuid())['runtime_epoch'] == winners[0]


def test_interrupted_pending_is_not_recovered_or_overwritten(tmp_path):
    root = directory(tmp_path)
    (root / (epoch.SLOT + '.pending')).mkdir(mode=0o700)
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.publish_reservation(root, record(), owner=os.getuid())
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.read_reservation(root, owner=os.getuid())
    assert (root / (epoch.SLOT + '.pending')).is_dir()


def test_invalid_private_parent_refuses_without_publishing(tmp_path):
    root = directory(tmp_path)
    root.chmod(0o755)
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.publish_reservation(root, record(), owner=os.getuid())
    assert not (root / epoch.SLOT).exists()


@pytest.mark.parametrize('attack', [
    'extra-member', 'symlink-member', 'hardlink-member', 'writable-member',
    'changed-bytes', 'wrong-parent-mode', 'wrong-record-schema',
])
def test_substituted_published_records_fail_closed(tmp_path, attack):
    root = directory(tmp_path)
    epoch.publish_reservation(root, record(), owner=os.getuid())
    slot = root / epoch.SLOT
    member = slot / 'epoch-reservation.json'
    if attack == 'extra-member':
        (slot / 'unexpected').write_text('no')
    elif attack == 'symlink-member':
        member.unlink()
        member.symlink_to('/etc/hosts')
    elif attack == 'hardlink-member':
        os.link(member, root / 'other')
    elif attack == 'writable-member':
        member.chmod(0o600)
    elif attack == 'changed-bytes':
        member.chmod(0o600)
        member.write_text('{}\n')
        member.chmod(0o400)
    elif attack == 'wrong-parent-mode':
        slot.chmod(0o755)
    elif attack == 'wrong-record-schema':
        member.chmod(0o600)
        r = json.loads(member.read_bytes())
        r['schema'] = 'other'
        r = epoch._seal({k: v for k, v in r.items() if k != 'record_sha256'})
        member.write_bytes(epoch._canonical(r))
        member.chmod(0o400)
    with pytest.raises((epoch.EpochReservationRefused, OSError)):
        epoch.read_reservation(root, owner=os.getuid())


def test_wrong_pinned_archive_or_uid_cannot_be_admitted(tmp_path):
    root = directory(tmp_path)
    epoch.publish_reservation(root, record(), owner=os.getuid())
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.read_reservation(root, owner=os.getuid(),
                               expected={'installed_source_archive_sha256': 'f'*64})
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.read_reservation(root, owner=os.getuid(), expected={'successor_uid': 777})


def test_live_reservation_does_not_run_from_mutable_checkout():
    # No user-run path can create live authority. Even a root invocation of a
    # checkout is forbidden until deployed as independently audited source.
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.prepare_live_reservation(successor_uid=995, successor_archive=Path('/uninstalled'),
                                       successor_source=Path('/not-the-installed-module'),
                                       expected_source_sha256='f'*64)


def test_resealed_unknown_extra_field_denied():
    r = record()
    r['authorised_by_alternate_controller'] = True
    sealed = epoch._seal({k: v for k, v in r.items() if k != 'record_sha256'})
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.validate_reservation(sealed)


def test_changed_boot_id_rejected_by_pinned_host_context(tmp_path):
    root = directory(tmp_path)
    epoch.publish_reservation(root, record(), owner=os.getuid())
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.read_reservation(root, owner=os.getuid(),
                               expected={'host_boot_id': '12345678-1234-1234-1234-123456789abc'})


def test_interruption_during_write_preserves_blocking_pending(monkeypatch, tmp_path):
    root = directory(tmp_path)

    def partial_and_crash(fd, name, raw):
        os.mkdir('crash-material', 0o700, dir_fd=fd)
        raise OSError('injected crash before immutable record committed')

    monkeypatch.setattr(epoch, '_new_file', partial_and_crash)
    with pytest.raises(epoch.EpochReservationRefused):
        epoch.publish_reservation(root, record(), owner=os.getuid())
    assert (root / (epoch.SLOT + '.pending')).is_dir()
    assert not (root / epoch.SLOT).exists()


def test_disposable_host_unprivileged_uid_cannot_read_reserved_record(tmp_path):
    if (os.name != 'posix' or os.geteuid() != 0 or
            os.environ.get('STYGNOX_DISPOSABLE_LINUX_ROOT_TESTS') != 'YES_I_AM_DISPOSABLE'):
        pytest.skip('requires explicit disposable Linux root test host opt-in')
    root = directory(tmp_path)
    epoch.publish_reservation(root, record(), owner=0)
    path = root / epoch.SLOT / 'epoch-reservation.json'
    snippet = ("import os,sys; os.setgroups([]); os.setgid(65534); os.setuid(65534); "
               "open(sys.argv[1], 'rb').read()")
    proc = subprocess.run([sys.executable, '-I', '-c', snippet, str(path)],
                          text=True, capture_output=True, check=False)
    assert proc.returncode != 0
    assert 'PermissionError' in proc.stderr
    assert epoch.read_reservation(root, owner=0)['successor_execution_authorised'] is False
