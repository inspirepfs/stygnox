#!/usr/bin/env python3
"""C3e disposable, cross-UID protected workspace and split-authority probe.

Only --simulate is supported. No existing checkout, mount, installed controller,
or live .stygnox state is modified. Runs as root to create isolated /run paths
and execute real Linux write attempts under separate non-root UIDs.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

from stygnox.direct_interruption_workspace import inspect_transition_candidate

_CHILD = r'''
import errno,json,os,sys
from pathlib import Path
base = Path(sys.argv[1]); mode = sys.argv[2]
result = {}
if mode == 'predecessor':
    try:
        (base/'old'/'authority.json').write_text('LEGACY-STILL-WRITABLE')
        result['original_write_succeeded'] = True
    except OSError:
        result['original_write_succeeded'] = False
    for name, operation in (
        ('protected_overwrite', lambda: (base/'new'/'.stygnox'/'authority.json').write_text('CORRUPT')),
        ('protected_create', lambda: (base/'new'/'old-created').write_text('CORRUPT')),
        ('protected_rename', lambda: (base/'new').rename(base/'replacement')),
    ):
        try:
            operation()
            result[name+'_denied'] = False
        except OSError as exc:
            result[name+'_denied'] = exc.errno in (errno.EACCES,errno.EPERM)
else:
    path=base/'new'/'successor.txt'
    path.write_text('SUCCESSOR-ONLY')
    path.chmod(0o600)
    result['protected_successor_write_succeeded'] = path.read_text() == 'SUCCESSOR-ONLY'
print(json.dumps(result))
'''


def _unused_uid(legacy_uid: int) -> int:
    for uid in range(61001, 62000):
        if uid == legacy_uid:
            continue
        try:
            pwd.getpwuid(uid)
        except KeyError:
            return uid
    raise RuntimeError('no free synthetic successor UID')


def _child(uid: int, base: Path, kind: str) -> dict:
    def drop() -> None:
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    execution = subprocess.run(
        [sys.executable, '-c', _CHILD, str(base), kind],
        capture_output=True, text=True, timeout=10,
        check=False, preexec_fn=drop,
    )
    if execution.returncode:
        raise RuntimeError(f'UID {uid} kernel attempt failed: {execution.stderr[-500:]}')
    return json.loads(execution.stdout)


def simulate(legacy_uid: int) -> dict:
    if os.name != 'posix' or os.geteuid() != 0 or legacy_uid <= 0:
        raise RuntimeError('requires Linux root, and a non-root legacy UID')
    pwd.getpwuid(legacy_uid)
    successor_uid = _unused_uid(legacy_uid)
    if not Path('/run').is_dir():
        raise RuntimeError('/run unavailable')
    with tempfile.TemporaryDirectory(dir='/run', prefix='stygnox-c3e-') as dirname:
        root = Path(dirname)
        root.chmod(0o755)
        old = root / 'old'
        old.mkdir(mode=0o700)
        os.chown(old, legacy_uid, legacy_uid)
        legacy_file = old / 'authority.json'
        legacy_file.write_text('ORIGINAL')
        os.chown(legacy_file, legacy_uid, legacy_uid)
        legacy_file.chmod(0o600)
        protected = root / 'new'
        protected.mkdir(mode=0o700)
        os.chown(protected, successor_uid, successor_uid)
        runtime = protected / '.stygnox'
        runtime.mkdir(mode=0o700)
        os.chown(runtime, successor_uid, successor_uid)
        protected_file = runtime / 'authority.json'
        protected_file.write_text('ORIGINAL')
        os.chown(protected_file, successor_uid, successor_uid)
        protected_file.chmod(0o600)
        predecessor = _child(legacy_uid, root, 'predecessor')
        successor = _child(successor_uid, root, 'successor')
        candidate = inspect_transition_candidate(old, protected,
                                                 predecessor_uid=legacy_uid,
                                                 successor_uid=successor_uid)
        denials = all(predecessor.get(item) is True for item in (
            'protected_overwrite_denied', 'protected_create_denied',
            'protected_rename_denied'))
        result = {
            'schema': 'stygnox_c3e_kernel_protected_workspace_probe_v1',
            'fixture_type': 'isolated_root_anchored_cross_uid',
            'legacy_uid': legacy_uid,
            'successor_uid': successor_uid,
            'legacy_original_write_still_possible': predecessor['original_write_succeeded'],
            'protected_legacy_operations_denied': denials,
            'successor_private_write_succeeded': successor['protected_successor_write_succeeded'],
            'protected_bytes_unchanged_by_predecessor': protected_file.read_text() == 'ORIGINAL',
            'protected_tree_snapshot_private': candidate['protected']['tree_snapshot_private'],
            'original_worktree_binding_transferred': candidate['original_worktree_binding_transferred'],
            'dual_authority_proved_absent': candidate['dual_authority_proved_absent'],
            'handoff_admissible': candidate['handoff_admissible'],
            'authority_changed': False,
            'live_runtime_modified': False,
        }
        if not (denials and result['legacy_original_write_still_possible']
                and result['successor_private_write_succeeded']
                and result['protected_bytes_unchanged_by_predecessor']
                and result['protected_tree_snapshot_private']
                and not result['handoff_admissible']):
            raise RuntimeError(f'disposable kernel isolation evidence failed: {result}')
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--legacy-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(simulate(args.legacy_uid), indent=2, sort_keys=True))
        return 0
    except (RuntimeError, OSError, KeyError) as exc:
        print(f'C3e refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
