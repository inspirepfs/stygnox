#!/usr/bin/env python3
"""02I: never-authorising boot/startup interlock for the 02H disposable fixture.

The source must be installed in a root-private Release 02I stage and invoked
from an independent root systemd system service. Only a 32-hex fixture ID is
accepted; the code cannot accept a live workspace path or release token.

--gate reports the old disposable journal/mount state and ALWAYS exits
EX_TEMPFAIL (75), even if its journal and mount checks succeed. No inspection
or release mode can accidentally succeed as a mandatory ExecStartPre.
No real successor unit is modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = 'stygnox_release02i_boot_startup_interlock_v1'
_TOKEN = re.compile(r'^[0-9a-f]{32}$')
_SYSTEM_UNIT = re.compile(
    r'[0-9]+:[^:]*:/system\.slice/stygnox-recovery-release02i-[A-Za-z0-9_.-]+\.service'
)
_STAGE = Path(__file__).absolute().parent
_OLD_STAGE = Path('/var/lib/stygnox/recovery-release02h-b288dd7')


class BootInterlockRefused(RuntimeError):
    """Insufficient trust to inspect; startup is always forbidden."""


def _token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise BootInterlockRefused('invalid disposable fixture identifier')
    return value


def _trusted_root_path(path: Path, *, private: bool = False) -> None:
    if not path.is_absolute() or '..' in path.parts:
        raise BootInterlockRefused('nonabsolute trusted path')
    for component in (*reversed(path.parents), path):
        st = component.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise BootInterlockRefused('untrusted root path ancestry')
    if private and path.stat().st_mode & 0o077:
        raise BootInterlockRefused('root-private state required')


def _supervisor() -> None:
    if os.name != 'posix' or os.getuid() != 0 or os.geteuid() != 0:
        raise BootInterlockRefused('root system service required')
    if os.readlink('/proc/self/ns/mnt') != os.readlink('/proc/1/ns/mnt'):
        raise BootInterlockRefused('host mount namespace required')
    lines = Path('/proc/self/cgroup').read_text(encoding='ascii').splitlines()
    if not any(_SYSTEM_UNIT.fullmatch(line) for line in lines):
        raise BootInterlockRefused('dedicated Release 02I system service required')
    _trusted_root_path(_STAGE, private=True)
    _trusted_root_path(_OLD_STAGE, private=True)
    source = Path(__file__)
    st = source.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != 0 or st.st_mode & 0o022:
        raise BootInterlockRefused('untrusted root-owned probe')
    _trusted_root_path(_STAGE / 'stygnox', private=True)
    for name in ('__init__.py', '_version.py', 'direct_interruption_durable_exclusion.py'):
        member = _STAGE / 'stygnox' / name
        info = member.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise BootInterlockRefused('untrusted staged package member')


def _pid1_mount(target: Path) -> bool:
    # Exact mountpoint token; generated fixture paths have no escaped chars.
    return any(len(fields := line.split(' ')) >= 5 and fields[4] == str(target)
               for line in Path('/proc/1/mountinfo').read_text(encoding='utf-8').splitlines())


def _blocked_report(fixture_id: str) -> dict:
    _supervisor()
    # python -I deliberately omits script directory; add it only after the
    # root-owned source stage and package members have been checked.
    sys.path.insert(0, str(_STAGE))
    from stygnox.direct_interruption_durable_exclusion import inspect_blocked_journal
    token = _token(fixture_id)
    journal = _OLD_STAGE / 'state' / token
    _trusted_root_path(journal, private=True)
    evidence = inspect_blocked_journal(journal)
    target = Path('/run') / ('stygnox-rr02h-' + token) / 'legacy-parent' / 'original'
    mount_present = _pid1_mount(target)
    reasons = ['REAL_PREDECESSOR_NOT_EXCLUDED', 'ALTERNATIVE_ALIASES_UNPROVED',
               'REBOOT_ENFORCEMENT_UNPROVED', 'SUCCESSOR_RELEASE_NOT_AUTHORISED']
    if evidence['boot_id_matches'] is not True:
        reasons.append('JOURNAL_FROM_DIFFERENT_BOOT')
    if evidence['phase'] != 'PREPARED_BLOCKED':
        reasons.append('JOURNAL_REQUIRES_RECONCILIATION')
    if not mount_present:
        reasons.append('HOST_DENIAL_NOT_MOUNTED')
    return {
        'schema': SCHEMA, 'fixture_id': token,
        'journal_record_sha256': evidence['record_sha256'],
        'journal_phase': evidence['phase'],
        'boot_id_matches': evidence['boot_id_matches'],
        'pid1_disposable_denial_mount_present': mount_present,
        'blocked_reasons': sorted(reasons),
        'execution_authority': 'NONE', 'startup_admissible': False,
        'host_wide_real_predecessor_excluded': False,
        'reboot_persistent_denial_proved': False,
        'live_runtime_modified': False, 'provider_executed': False,
        'authority_changed': False, 'successor_execution_authorised': False,
        'handoff_admissible': False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--gate', required=True, action='store_true')
    parser.add_argument('--fixture-id', required=True)
    args = parser.parse_args()
    # A mandatory systemd ExecStartPre must *never* return success from this
    # release, including on trust failure, lost files, or unexpected exceptions.
    try:
        result = _blocked_report(_token(args.fixture_id))
    except BaseException as exc:
        # No exception, including a journal parsing failure, can grant startup.
        result = {
            'schema': SCHEMA, 'startup_admissible': False,
            'handoff_admissible': False, 'successor_execution_authorised': False,
            'execution_authority': 'NONE', 'inspection_failed': True,
            'reason': type(exc).__name__,
        }
        print(json.dumps(result, sort_keys=True))
        return 75
    print(json.dumps(result, sort_keys=True))
    return 75


if __name__ == '__main__':
    sys.exit(main())
