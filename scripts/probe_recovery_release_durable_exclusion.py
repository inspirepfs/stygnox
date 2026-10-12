#!/usr/bin/env python3
"""Release 02F: prove durable fail-closed blocked journal in a disposable root fixture.

Must run as a dedicated root systemd system service from verified root-only
staging. It NEVER accepts live workspace paths or authority actions. All
persistent test files are confined to a unique /run fixture and removed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

_STAGE = Path(__file__).absolute().parent
sys.path.insert(0, str(_STAGE))
from stygnox import direct_interruption_durable_exclusion as journal


class ProbeRefused(RuntimeError):
    pass


def _trusted_service() -> None:
    if os.geteuid() != 0 or os.getuid() != 0:
        raise ProbeRefused('root service required')
    cgroup = Path('/proc/self/cgroup').read_text(encoding='utf-8')
    if not any('/system.slice/stygnox-recovery-release02f-' in line and
               line.rstrip().endswith('.service') for line in cgroup.splitlines()):
        raise ProbeRefused('dedicated root system service required')
    for directory in (*reversed(_STAGE.parents), _STAGE):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ProbeRefused(f'untrusted stage parent: {directory}')
    if stat.S_IMODE(_STAGE.stat().st_mode) & 0o077:
        raise ProbeRefused('stage must be root private')
    for source in (_STAGE / Path(__file__).name,
                   _STAGE / 'stygnox' / '__init__.py',
                   _STAGE / 'stygnox' / 'direct_interruption_durable_exclusion.py'):
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ProbeRefused(f'untrusted staged file: {source}')


def _replay(directory: Path) -> dict:
    code = '''import json,sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from stygnox.direct_interruption_durable_exclusion import inspect_blocked_journal
print(json.dumps(inspect_blocked_journal(Path(sys.argv[2])), sort_keys=True))
'''
    child = subprocess.run([sys.executable, '-I', '-c', code, str(_STAGE), str(directory)],
                           capture_output=True, text=True, timeout=10)
    if child.returncode != 0:
        raise ProbeRefused(f'fresh-process journal inspection failed: {child.stderr}')
    return json.loads(child.stdout)


def simulate() -> dict:
    _trusted_service()
    with tempfile.TemporaryDirectory(prefix='stygnox-rr02f-', dir='/run') as folder:
        directory = Path(folder)
        os.chmod(directory, 0o700)
        digest = hashlib.sha256(b'inert-fixture-only').hexdigest()
        original = directory / 'inert-original'
        original.mkdir(mode=0o700)
        identity = original.stat()
        record = journal.prepare_blocked_journal(
            directory, original_path=str(original),
            installed_predecessor_path='/opt/stygnox-inert-predecessor',
            predecessor_uid=1000, original_device=identity.st_dev,
            original_inode=identity.st_ino, installed_sha256=digest,
            plan_sha256=digest, transaction_sha256=digest)
        first = _replay(directory)
        if first['phase'] != 'PREPARED_BLOCKED' or first['handoff_admissible']:
            raise ProbeRefused('blocked initial replay failed')
        after = journal.require_reconciliation(directory, reason='SUPERVISOR_INTERRUPTED')
        fresh = _replay(directory)
        if (after['phase'] != 'NEEDS_RECONCILIATION' or
                fresh['phase'] != 'NEEDS_RECONCILIATION' or fresh['handoff_admissible']):
            raise ProbeRefused('durable one-way reconciliation failed')
        return {
            'schema': 'stygnox_release02f_disposable_durable_exclusion_v1',
            'record_sha256': record['record_sha256'],
            'root_private_durable_journal_published': True,
            'fresh_process_initial_replay_blocked': True,
            'fresh_process_reconciliation_replay_blocked': True,
            'one_way_reconciliation_record_written': True,
            'reboot_denial_proved': False,
            'host_wide_relaunch_excluded': False,
            'original_binding_retired': False,
            'live_runtime_modified': False,
            'provider_executed': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
        }


def main() -> int:
    if sys.argv[1:] != ['--simulate']:
        print('Release 02F accepts only --simulate', file=sys.stderr)
        return 2
    try:
        print(json.dumps(simulate(), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, journal.DurableExclusionRefused, ProbeRefused) as exc:
        print(f'Release 02F REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
