#!/usr/bin/env python3
"""C3d real Linux PIDFD drain + DAC test, disposable under /run ONLY.

This is intentionally NOT a live process-drain or permission-change command.
Never targets the installed Codex app servers, a real provider or a worktree.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

from stygnox.direct_interruption_process import (
    ProcessDrainRefused, drain_exact_child, read_process_identity,
    assess_worktree_holders,
)
from stygnox.direct_interruption_exclusion import verify_dac_boundary

WRITER = r"""
import sys
with open(sys.argv[1], 'ab', buffering=0) as out:
    print('LEGACY_WRITER_READY', flush=True)
    for command in sys.stdin:
        if command.strip() == 'WRITE':
            out.write(b'UNAUTHORIZED-LEGACY-AFTER-SEAL')
        elif command.strip() == 'QUIT':
            break
"""

ACCESS = r"""
import json, sys
from pathlib import Path
p = Path(sys.argv[1]); mode = sys.argv[2]
try:
    if mode == 'successor':
        (p/'successor-proof').write_text('successor')
    else:
        with (p/'authority').open('ab') as f:
            f.write(b'legacy-unauthorized')
    print(json.dumps({'write_succeeded': True}))
except (OSError, PermissionError) as exc:
    print(json.dumps({'write_succeeded': False, 'errno': getattr(exc, 'errno', None)}))
"""


def _drop(uid):
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)


def _run_as(uid, cmd):
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=10,
                          preexec_fn=lambda: _drop(uid), check=False)
    if proc.returncode:
        raise ProcessDrainRefused(f'UID {uid} helper failed: {proc.stderr[-400:]}')
    return json.loads(proc.stdout)


def _unused_successor_uid(legacy_uid: int) -> int:
    for uid in range(61001, 62000):
        if uid == legacy_uid:
            continue
        try:
            pwd.getpwuid(uid)
        except KeyError:
            return uid
    raise ProcessDrainRefused('no available synthetic UID')


def simulate(legacy_uid: int) -> dict:
    successor_uid = _unused_successor_uid(legacy_uid)
    if os.name != 'posix' or os.geteuid() != 0:
        raise ProcessDrainRefused('root required for disposable cross-UID simulation')
    if legacy_uid <= 0 or successor_uid <= 0 or legacy_uid == successor_uid:
        raise ProcessDrainRefused('distinct non-root UIDs required')
    try:
        pwd.getpwuid(legacy_uid)
    except KeyError as exc:
        raise ProcessDrainRefused('existing legacy UID required') from exc
    if not Path('/run').is_dir():
        raise ProcessDrainRefused('/run required')
    with tempfile.TemporaryDirectory(prefix='stygnox-c3d-', dir='/run') as directory:
        base = Path(directory)
        base.chmod(0o755)  # fixture only; parent /run is trusted
        protected = base/'protected'
        protected.mkdir(mode=0o700)
        os.chown(protected, legacy_uid, legacy_uid)
        target = protected/'authority'
        target.write_bytes(b'UNMODIFIED')
        os.chown(target, legacy_uid, legacy_uid)
        target.chmod(0o600)
        writer = subprocess.Popen(
            [sys.executable, '-c', WRITER, str(target)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
            preexec_fn=lambda: _drop(legacy_uid),
        )
        try:
            if writer.stdout.readline().strip() != 'LEGACY_WRITER_READY':
                raise ProcessDrainRefused('legacy writer not ready')
            identity = read_process_identity(writer.pid)
            if identity.uid != legacy_uid:
                raise ProcessDrainRefused('tracked writer has wrong UID')
            # Prevent new opens first. Preopened fd still exists until drained.
            os.chown(protected, successor_uid, successor_uid)
            os.chown(target, successor_uid, successor_uid)
            verify_dac_boundary(protected, predecessor_uid=legacy_uid,
                                successor_uid=successor_uid)
            late_legacy = _run_as(legacy_uid,
                [sys.executable, '-c', ACCESS, str(protected), 'legacy'])
            if late_legacy['write_succeeded']:
                raise ProcessDrainRefused('new legacy writer bypassed DAC')
            # Pin and stop the *only* launched tracked legacy writer before any
            # successor access or simulated authority publication.
            evidence = drain_exact_child(writer, expected=identity)
            if writer.poll() is None:
                raise ProcessDrainRefused('legacy writer not terminated')
            successor = _run_as(successor_uid,
                [sys.executable, '-c', ACCESS, str(protected), 'successor'])
            if not successor['write_succeeded'] or target.read_bytes() != b'UNMODIFIED':
                raise ProcessDrainRefused('post-drain file contents or successor access invalid')
            return {
                'schema': 'stygnox_c3d_disposable_pidfd_drain_v1',
                'fixture_type': 'disposable_root_supervised_process',
                'successor_uid': successor_uid,
                'predecessor_identity': {
                    'pid': identity.pid, 'uid': identity.uid,
                    'start_ticks': identity.start_ticks,
                },
                'predecessor_drained': evidence['terminated_via_pidfd'],
                'predecessor_new_writes_excluded': True,
                'successor_write_succeeded': successor['write_succeeded'],
                'preopened_writer_could_not_publish_after_drain': target.read_bytes() == b'UNMODIFIED',
                'unknown_host_processes_excluded': False,
                'new_legacy_process_launches_blocked': False,
                'original_worktree_isolated': False,
                'exclusive_handoff_proved': False,
                'handoff_admissible': False,
                'authority_changed': False,
                'live_runtime_modified': False,
            }
        finally:
            if writer.poll() is None:
                writer.kill()
                writer.wait(timeout=5)
            if writer.stdin:
                writer.stdin.close()
            if writer.stdout:
                writer.stdout.close()
            if writer.stderr:
                writer.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--simulate', action='store_true')
    modes.add_argument('--assess-worktree', type=Path)
    parser.add_argument('--legacy-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        if args.simulate:
            result = simulate(args.legacy_uid)
        else:
            result = assess_worktree_holders(args.assess_worktree,
                                             predecessor_uid=args.legacy_uid)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ProcessDrainRefused, OSError, subprocess.SubprocessError) as exc:
        print(f'C3d refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
