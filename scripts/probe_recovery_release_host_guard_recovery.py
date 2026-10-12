#!/usr/bin/env python3
"""02H: crash-restart lifecycle of a *disposable* host-visible denial.

Establish a mount on an isolated root-controlled /run fixture and intentionally
leave it active after the establishing systemd service exits. A second root
systemd service must verify it. A third explicitly retires the mount and records
one-way reconciliation. This is neither a real predecessor guard nor a release.

Only a root-owned systemd system service in PID 1's mount namespace may run it.
All target paths are generated here; caller input is restricted to a fixture id
and a distinct predecessor UID. Never accepts a live project path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

_STAGE = Path(__file__).absolute().parent
sys.path.insert(0, str(_STAGE))

from probe_recovery_release_mount_denial import (  # noqa: E402
    _mount, _umount, _child_access_probe, MS_BIND,
)
from stygnox.direct_interruption_durable_exclusion import (  # noqa: E402
    prepare_blocked_journal, inspect_blocked_journal, require_reconciliation,
)

SCHEMA = 'stygnox_release02h_disposable_guard_restart_v1'
_TOKEN = re.compile(r'^[0-9a-f]{32}$')
_SYSTEM_UNIT = re.compile(
    r'[0-9]+:[^:]*:/system\.slice/stygnox-recovery-release02h-[A-Za-z0-9_.-]+\.service'
)


class GuardRestartRefused(RuntimeError):
    """Fail closed: the fixture cannot establish any release permission."""


def _validate_token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise GuardRestartRefused('invalid disposable fixture identifier')
    return value


def _paths(fixture_id: str) -> tuple[Path, Path, Path, Path]:
    token = _validate_token(fixture_id)
    root = Path('/run') / ('stygnox-rr02h-' + token)
    target = root / 'legacy-parent' / 'original'
    gate = root / 'denial'
    journal = _STAGE / 'state' / token
    return root, target, gate, journal


def _require_supervisor() -> None:
    if os.name != 'posix' or os.getuid() != 0 or os.geteuid() != 0:
        raise GuardRestartRefused('root system service required')
    if os.readlink('/proc/self/ns/mnt') != os.readlink('/proc/1/ns/mnt'):
        raise GuardRestartRefused('host mount namespace required')
    if not any(_SYSTEM_UNIT.fullmatch(line) for line in
               Path('/proc/self/cgroup').read_text(encoding='ascii').splitlines()):
        raise GuardRestartRefused('dedicated Release 02H system service required')
    source = Path(__file__).absolute()
    if source.is_symlink():
        raise GuardRestartRefused('symlinked source refused')
    for p in (*reversed(source.parent.parents), source.parent, source):
        st = p.lstat()
        if st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022:
            raise GuardRestartRefused('untrusted supervisor source ancestry')
        if p == source:
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise GuardRestartRefused('untrusted supervisor entry')
        elif not stat.S_ISDIR(st.st_mode):
            raise GuardRestartRefused('untrusted source directory')
    if stat.S_IMODE(source.parent.stat().st_mode) & 0o077:
        raise GuardRestartRefused('source stage must be root private')
    state = _STAGE / 'state'
    st = state.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        raise GuardRestartRefused('root-private durable state directory required')


def _present_in_pid1(target: Path) -> bool:
    # Exact mountpoint field only; our generated paths contain no escapes.
    return any(len(parts := line.split(' ')) >= 5 and parts[4] == str(target)
               for line in Path('/proc/1/mountinfo').read_text(encoding='utf-8').splitlines())


def _root_owned(path: Path, mode: int) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != mode):
        raise GuardRestartRefused('untrusted root-controlled fixture')


def _load_identity(fixture_id: str) -> tuple[Path, Path, Path, Path, int, dict]:
    root, target, gate, journal = _paths(fixture_id)
    _root_owned(root, 0o755)
    _root_owned(gate, 0o700)
    _root_owned(journal, 0o700)
    _root_owned(root / 'legacy-parent', 0o755)
    # Verify the sealed canonical root journal before looking up old-UID access.
    blocked = inspect_blocked_journal(journal)
    if blocked['boot_id_matches'] is not True:
        try:
            require_reconciliation(journal, reason='REBOOT_DETECTED')
        except (OSError, RuntimeError):
            pass  # Remain blocked even if persistent reconciliation cannot publish.
        raise GuardRestartRefused('journal belongs to a previous boot; reconciliation required')
    if blocked['phase'] != 'PREPARED_BLOCKED':
        raise GuardRestartRefused('journal is blocked for reconciliation')
    # Read only trusted root-controlled immutable journal data. The journal
    # module independently checked file owner, canonical JSON and fingerprint.
    record_path = journal / 'blocked-exclusion.json'
    fd = os.open(record_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        record = json.loads(os.read(fd, 32768))
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
            raise GuardRestartRefused('untrusted journal record')
    finally:
        os.close(fd)
    uid = record['predecessor_uid']
    if (record['original_path'] != str(target) or
            record['installed_predecessor_path'] != str(root / 'installed' / 'inert.py') or
            not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 or uid == 65534):
        raise GuardRestartRefused('journal fixture identity mismatch')
    p = root / 'legacy-parent'
    if p.lstat().st_uid != 0:
        raise GuardRestartRefused('fixture parent replaced')
    return root, target, gate, journal, uid, blocked


def _require_live_denial(target: Path, gate: Path, uid: int) -> None:
    if not _present_in_pid1(target):
        raise GuardRestartRefused('host-visible denial missing')
    # An unrelated mount on the path is not proof of our precise bound inode.
    a, b = target.stat(), gate.stat()
    if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
        raise GuardRestartRefused('host mount does not bind expected gate inode')
    access = _child_access_probe(target, uid)
    if any(access.values()):
        raise GuardRestartRefused(f'old UID regained fresh path access: {access}')


def _flags() -> dict:
    return {
        'real_predecessor_excluded': False,
        'alternative_path_aliases_excluded': False,
        'reboot_persistent_denial_proved': False,
        'original_binding_retired': False,
        'authority_changed': False,
        'provider_executed': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'live_runtime_modified': False,
    }


def establish(uid: int) -> dict:
    if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 or uid == 65534:
        raise GuardRestartRefused('distinct non-root predecessor UID required')
    _require_supervisor()
    if uid == os.getuid():
        raise GuardRestartRefused('distinct non-root predecessor UID required')
    token = secrets.token_hex(16)
    root, target, gate, journal = _paths(token)
    # Exclusive names. Do not follow or reuse an existing path.
    root.mkdir(mode=0o700)
    mounted = False
    try:
        os.chmod(root, 0o755)
        parent = target.parent
        parent.mkdir(mode=0o755)
        target.mkdir(mode=0o700)
        os.chown(target, uid, uid)
        runtime = target / '.stygnox'
        runtime.mkdir(mode=0o700)
        os.chown(runtime, uid, uid)
        plan = runtime / 'plan.json'
        transaction = runtime / 'transaction.json'
        plan.write_bytes(b'{"disposable":"02h","authority":false}\n')
        transaction.write_bytes(b'{"disposable":true,"execution_authority":"NONE"}\n')
        for p in (plan, transaction):
            os.chown(p, uid, uid)
            os.chmod(p, 0o600)
        gate.mkdir(mode=0o700)
        installed_dir = root / 'installed'
        installed_dir.mkdir(mode=0o700)
        installed = installed_dir / 'inert.py'
        installed.write_bytes(b'# inert fixture; not executable\n')
        os.chmod(installed, 0o400)
        journal.mkdir(mode=0o700)
        st = target.stat()
        prepared = prepare_blocked_journal(
            journal, original_path=str(target),
            installed_predecessor_path=str(installed),
            predecessor_uid=uid, original_device=st.st_dev, original_inode=st.st_ino,
            installed_sha256=hashlib.sha256(installed.read_bytes()).hexdigest(),
            plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
            transaction_sha256=hashlib.sha256(transaction.read_bytes()).hexdigest(),
        )
        if _present_in_pid1(target):
            raise GuardRestartRefused('fixture unexpectedly mounted before denial')
        _mount(str(gate), str(target), MS_BIND)
        mounted = True
        _require_live_denial(target, gate, uid)
        blocked = inspect_blocked_journal(journal)
        if blocked['record_sha256'] != prepared['record_sha256']:
            raise GuardRestartRefused('journal digest differs after host mount')
        # Intentionally leave the host-visible mount after this process exits.
        # The separate --verify system service must prove it survived.
        return {
            'schema': SCHEMA, 'phase': 'ESTABLISHED_BLOCKED',
            'fixture_id': token, 'journal_record_sha256': prepared['record_sha256'],
            'host_denial_visible_to_pid1': True,
            'fresh_access_denied': True,
            'survived_establishing_service_exit': False,
            **_flags(),
        }
    except BaseException:
        if mounted:
            try:
                _umount(str(target))
                mounted = False
            except (OSError, RuntimeError):
                pass
        if journal.exists():
            try:
                require_reconciliation(journal, reason='SUPERVISOR_INTERRUPTED')
            except (OSError, RuntimeError):
                pass
        raise


def verify(fixture_id: str) -> dict:
    _validate_token(fixture_id)
    _require_supervisor()
    root, target, gate, journal, uid, blocked = _load_identity(fixture_id)
    try:
        _require_live_denial(target, gate, uid)
    except GuardRestartRefused:
        try:
            require_reconciliation(journal, reason='KERNEL_DENIAL_LOST')
        except (OSError, RuntimeError):
            pass  # Denial is unproved and no execution authority is available.
        raise
    return {
        'schema': SCHEMA, 'phase': 'VERIFIED_BLOCKED',
        'fixture_id': fixture_id,
        'journal_record_sha256': blocked['record_sha256'],
        'host_denial_visible_to_pid1': True,
        'fresh_access_denied_after_service_exit': True,
        # The caller must run this in a SECOND, exited-systemd predecessor flow.
        'establishing_service_exit_independently_attested': False,
        **_flags(),
    }


def retire(fixture_id: str) -> dict:
    verified = verify(fixture_id)
    _, target, _, journal, _, _ = _load_identity(fixture_id)
    _umount(str(target))
    if _present_in_pid1(target):
        raise GuardRestartRefused('denial still mounted after unmount')
    reconciled = require_reconciliation(journal, reason='KERNEL_DENIAL_LOST')
    if reconciled['phase'] != 'NEEDS_RECONCILIATION':
        raise GuardRestartRefused('retirement did not enter reconciliation state')
    return {
        'schema': SCHEMA, 'phase': 'RETIRED_NEEDS_RECONCILIATION',
        'fixture_id': fixture_id,
        'journal_record_sha256': verified['journal_record_sha256'],
        'denial_removed_from_pid1': True,
        'reconciliation_required': True,
        **_flags(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--establish', action='store_true')
    group.add_argument('--verify', action='store_true')
    group.add_argument('--retire', action='store_true')
    parser.add_argument('--predecessor-uid', type=int)
    parser.add_argument('--fixture-id')
    args = parser.parse_args()
    try:
        if args.establish:
            if args.predecessor_uid is None or args.fixture_id is not None:
                raise GuardRestartRefused('establish requires UID and no fixture ID')
            evidence = establish(args.predecessor_uid)
        else:
            if args.fixture_id is None or args.predecessor_uid is not None:
                raise GuardRestartRefused('verify/retire require only a fixture ID')
            evidence = verify(args.fixture_id) if args.verify else retire(args.fixture_id)
    except (GuardRestartRefused, OSError, ValueError, RuntimeError) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(evidence, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
