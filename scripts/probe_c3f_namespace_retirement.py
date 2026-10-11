#!/usr/bin/env python3
"""Cross-UID C3f retirement/drain probe. Root-owned *disposable* /run fixture only.

Never runs against a user-supplied checkout. No live authority record is read or
changed. Proves path withdrawal and known-child drain, not unknown holder/UID
revocation, runtime binding transfer, or permission to publish authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import select
import subprocess
import sys
import tempfile
import time

from stygnox.direct_interruption_process import read_process_identity, drain_exact_child
from stygnox.direct_interruption_retirement import retire_predecessor_path

_WRITER = r'''
import os,sys,time
f=os.open(sys.argv[1], os.O_WRONLY | os.O_APPEND)
print('READY',flush=True)
while True:
    os.write(f,b'x')
    os.fsync(f)
    time.sleep(0.01)
'''
_ATTEMPT = r'''
import json,sys
from pathlib import Path
old,vault,protected=map(Path,sys.argv[1:4])
result={}
for name,path in [('old_path',old/'authority.json'),('vault_path',vault/'authority.json'),('protected_path',protected/'authority.json')]:
    try:
        path.write_text('FORBIDDEN')
        result[name+'_write_denied']=False
    except (OSError,PermissionError):
        result[name+'_write_denied']=True
print(json.dumps(result))
'''


def _drop(uid: int):
    def drop() -> None:
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    return drop


def _unused_uid(legacy: int) -> int:
    for uid in range(61001, 62000):
        if uid == legacy:
            continue
        try:
            pwd.getpwuid(uid)
        except KeyError:
            return uid
    raise RuntimeError('no unused test UID available')


def simulate(legacy_uid: int) -> dict:
    if os.name != 'posix' or os.geteuid() != 0 or legacy_uid <= 0 or not Path('/run').is_dir():
        raise RuntimeError('root on Linux with /run and a non-root legacy UID required')
    pwd.getpwuid(legacy_uid)
    successor_uid = _unused_uid(legacy_uid)
    with tempfile.TemporaryDirectory(dir='/run', prefix='stygnox-c3f-') as temp:
        base = Path(temp)
        base.chmod(0o755)
        active = base / 'active'
        active.mkdir(mode=0o711)
        vault = base / 'vault'
        vault.mkdir(mode=0o700)
        successor = base / 'successor'
        successor.mkdir(mode=0o700)
        os.chown(successor, successor_uid, successor_uid)
        old = active / 'original'
        old.mkdir(mode=0o700)
        os.chown(old, legacy_uid, legacy_uid)
        old_file = old / 'authority.json'
        old_file.write_text('ORIGINAL')
        os.chown(old_file, legacy_uid, legacy_uid)
        old_file.chmod(0o600)
        successor_file = successor / 'authority.json'
        successor_file.write_text('SUCCESSOR')
        os.chown(successor_file, successor_uid, successor_uid)
        successor_file.chmod(0o600)
        process = subprocess.Popen(
            [sys.executable, '-c', _WRITER, str(old_file)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            preexec_fn=_drop(legacy_uid),
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 5)
            if not ready or process.stdout.readline().strip() != 'READY':
                raise RuntimeError('predecessor writer did not open its FD')
            identity = read_process_identity(process.pid)
            old_stat = old.lstat()
            output = retire_predecessor_path(
                old, vault / 'quarantined', predecessor_uid=legacy_uid,
                expected_dev=old_stat.st_dev, expected_inode=old_stat.st_ino,
            )
            quarantined_file = vault / 'quarantined' / 'authority.json'
            before = quarantined_file.stat().st_size
            time.sleep(0.15)
            after = quarantined_file.stat().st_size
            preopened_fd_wrote_after_rename = after > before
            drained = drain_exact_child(process, expected=identity, timeout=5)
            stopped_at = quarantined_file.stat().st_size
            time.sleep(0.08)
            stable_after_drain = stopped_at == quarantined_file.stat().st_size
            denied = subprocess.run(
                [sys.executable, '-c', _ATTEMPT, str(old), str(vault/'quarantined'), str(successor)],
                capture_output=True, text=True, timeout=5, preexec_fn=_drop(legacy_uid),
            )
            if denied.returncode:
                raise RuntimeError(f'legacy mutation check failed: {denied.stderr}')
            denials = json.loads(denied.stdout)
            result = {
                'schema': 'stygnox_c3f_disposable_namespace_retirement_probe_v1',
                'fixture_type': 'root_owned_run_cross_uid',
                'legacy_uid': legacy_uid,
                'successor_uid': successor_uid,
                'root_owned_parent_retired_original': output['old_path_missing'],
                'preopened_fd_wrote_after_rename': preopened_fd_wrote_after_rename,
                'tracked_predecessor_drained': drained['direct_child_reaped'],
                'preopened_fd_stable_after_drain': stable_after_drain,
                'legacy_access_denied_after_retirement': all(denials.values()),
                'successor_data_preserved': successor_file.read_text() == 'SUCCESSOR',
                'unknown_predecessor_holders_excluded': False,
                'new_legacy_launches_globally_blocked': False,
                'original_controller_binding_retired': False,
                'successor_binding_transferred': False,
                'handoff_admissible': False,
                'authority_changed': False,
                'live_runtime_modified': False,
            }
            if not (result['root_owned_parent_retired_original']
                    and result['preopened_fd_wrote_after_rename']
                    and result['tracked_predecessor_drained']
                    and result['preopened_fd_stable_after_drain']
                    and result['legacy_access_denied_after_retirement']
                    and result['successor_data_preserved']):
                raise RuntimeError(f'kernel retirement probe failed: {result}')
            return result
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--simulate', action='store_true', required=True)
    p.add_argument('--legacy-uid', required=True, type=int)
    args = p.parse_args()
    try:
        print(json.dumps(simulate(args.legacy_uid), sort_keys=True, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'C3f REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
