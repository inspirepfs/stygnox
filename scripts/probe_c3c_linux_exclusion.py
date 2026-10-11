#!/usr/bin/env python3
"""Disposable Linux C3c DAC enforcement probe. NEVER edits an existing project.

Run as root only with --simulate and an explicit real legacy UID; it creates a
new fixture under /run, drops privileges for *real* subprocess write attempts,
then removes that fixture. It does not publish recovery or execution authority.
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

from stygnox.direct_interruption_exclusion import ExclusionRefused, verify_dac_boundary

# The child is real, unmocked kernel identity and filesystem access.
INFLIGHT_CHILD = r"""
import os, sys
path = sys.argv[1]
with open(path, 'ab', buffering=0) as handle:
    print('READY', flush=True)
    if sys.stdin.readline().strip() == 'GO':
        handle.write(b'\nINFLIGHT-LEGACY-WROTE-AFTER-SEAL')
"""

CHILD = r"""
import errno, json, os, sys
from pathlib import Path
base = Path(sys.argv[1]); mode = sys.argv[2]
if mode == 'successor':
    created = base/'successor-created.json'
    created.write_text('{}')
    created.rename(base/'successor-renamed.json')
    print(json.dumps({'successor_write_succeeded': (base/'successor-renamed.json').is_file()}))
else:
    blocked = {}
    for name, op in (
        ('create', lambda: (base/'legacy-created.json').write_text('{}')),
        ('overwrite', lambda: (base/'authority.json').write_text('compromised')),
        ('unlink', lambda: (base/'authority.json').unlink()),
        ('chmod', lambda: (base/'authority.json').chmod(0o777)),
        ('rename', lambda: (base/'authority.json').rename(base/'legacy-renamed.json')),
    ):
        try:
            op()
            blocked[name] = False
        except OSError as exc:
            blocked[name] = exc.errno in (errno.EACCES, errno.EPERM)
    print(json.dumps({'legacy_denials': blocked}))
"""


def _child(uid: int, directory: Path, mode: str) -> dict:
    def drop():
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    result = subprocess.run(
        [sys.executable, '-c', CHILD, str(directory), mode],
        text=True, capture_output=True, timeout=10, preexec_fn=drop, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"UID {uid} child failed: {result.stderr[-800:]}")
    return json.loads(result.stdout)


def _unused_uid(excluded: int) -> int:
    for uid in range(61001, 62000):
        if uid == excluded:
            continue
        try:
            pwd.getpwuid(uid)
        except KeyError:
            return uid
    raise RuntimeError("no unused synthetic successor UID")


def simulate(legacy_uid: int) -> dict:
    if os.geteuid() != 0 or legacy_uid <= 0:
        raise ExclusionRefused('simulation requires root and a real non-root legacy UID')
    try:
        pwd.getpwuid(legacy_uid)
    except KeyError as exc:
        raise ExclusionRefused('legacy UID must exist on this host') from exc
    successor_uid = _unused_uid(legacy_uid)
    if not Path('/run').is_dir():
        raise ExclusionRefused('/run is required for isolated trusted-directory simulation')
    with tempfile.TemporaryDirectory(prefix='stygnox-c3c-', dir='/run') as root:
        base = Path(root)
        # Secure temporary root is created by root, and only the newly-created
        # fixture is made traversable. Never chmod or chown pre-existing paths.
        base.chmod(0o755)
        source = base/'source'
        runtime = base/'runtime'
        for directory in (source, runtime):
            directory.mkdir(mode=0o700)
            os.chown(directory, successor_uid, successor_uid)
            (directory/'authority.json').write_text('{"original":true}')
            os.chown(directory/'authority.json', successor_uid, successor_uid)
            (directory/'authority.json').chmod(0o600)

        before = {str(d): (d/'authority.json').read_text() for d in (source, runtime)}
        attestation = [verify_dac_boundary(d, predecessor_uid=legacy_uid, successor_uid=successor_uid)
                       for d in (source, runtime)]
        predecessor = {d.name: _child(legacy_uid, d, 'predecessor')['legacy_denials']
                       for d in (source, runtime)}
        successor = {d.name: _child(successor_uid, d, 'successor')['successor_write_succeeded']
                     for d in (source, runtime)}
        after = {str(d): (d/'authority.json').read_text() for d in (source, runtime)}
        all_denied = all(all(result.values()) for result in predecessor.values())
        # A process that *already* opened a writable descriptor is not
        # fenced by ownership changes. Preserve this negative evidence.
        inflight_dir = base/'inflight'
        inflight_dir.mkdir(mode=0o700)
        os.chown(inflight_dir, legacy_uid, legacy_uid)
        inflight_file = inflight_dir/'preopened.txt'
        inflight_file.write_bytes(b'BEFORE')
        os.chown(inflight_file, legacy_uid, legacy_uid)
        inflight_file.chmod(0o600)
        def drop_legacy():
            os.setgroups([])
            os.setgid(legacy_uid)
            os.setuid(legacy_uid)
        proc = subprocess.Popen([sys.executable, '-c', INFLIGHT_CHILD, str(inflight_file)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, preexec_fn=drop_legacy)
        try:
            if proc.stdout.readline().strip() != 'READY':
                raise RuntimeError('preexisting descriptor child never reached READY')
            os.chown(inflight_dir, successor_uid, successor_uid)
            os.chmod(inflight_dir, 0o700)
            os.chown(inflight_file, successor_uid, successor_uid)
            output, error = proc.communicate('GO\n', timeout=10)
            if proc.returncode:
                raise RuntimeError(f'inflight child failed: {error[-800:]}')
            survived = b'INFLIGHT-LEGACY-WROTE-AFTER-SEAL' in inflight_file.read_bytes()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=5)
        result = {
            'schema': 'stygnox_c3c_kernel_exclusion_simulation_v1',
            'fixture_type': 'disposable_root_owned_linux_dac',
            'legacy_uid': legacy_uid,
            'successor_uid': successor_uid,
            'legacy_mutation_denials': predecessor,
            'successor_mutations_succeeded': successor,
            'authority_files_unchanged': before == after,
            'dac_boundaries_verified': len(attestation) == 2,
            'predecessor_new_writes_excluded': all_denied,
            'preopened_legacy_fd_can_still_write': survived,
            'inflight_predecessor_excluded': False,
            'actual_host_checkout_isolated': False,
            'handoff_admissible': False,
            'authority_changed': False,
            'live_runtime_modified': False,
        }
        if not all_denied or not all(successor.values()) or before != after or not survived:
            raise ExclusionRefused(f'kernel write exclusion simulation failed: {result}')
        return result


def assess_worktree(worktree: Path, legacy_uid: int, successor_uid: int) -> dict:
    """Read-only current-path admission check, never a publication approval."""
    findings = {}
    for name, path in (("source", worktree), ("runtime", worktree/'.stygnox')):
        try:
            verified = verify_dac_boundary(path, predecessor_uid=legacy_uid, successor_uid=successor_uid)
            findings[name] = {"sealed": True, "path": str(path), "device": verified['ancestors'][-1]['device'],
                              "inode": verified['ancestors'][-1]['inode']}
        except ExclusionRefused as exc:
            findings[name] = {"sealed": False, "path": str(path), "reason": str(exc)}
    return {
        'schema': 'stygnox_c3c_existing_path_assessment_v1',
        'fixture_type': 'existing_paths_read_only',
        'legacy_uid': legacy_uid, 'proposed_successor_uid': successor_uid,
        'findings': findings,
        'kernel_path_boundary_sealed': all(x['sealed'] for x in findings.values()),
        'inflight_predecessor_excluded': False,
        'handoff_admissible': False, 'authority_changed': False,
        'live_runtime_modified': False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--simulate', action='store_true')
    modes.add_argument('--assess-worktree', type=Path)
    parser.add_argument('--legacy-uid', type=int, required=True)
    parser.add_argument('--successor-uid', type=int, help='proposed separate unprivileged successor UID for read-only assessment')
    args = parser.parse_args(argv)
    try:
        if args.simulate:
            if args.successor_uid is not None:
                parser.error('--successor-uid is not used during the disposable simulation')
            result = simulate(args.legacy_uid)
        else:
            if args.successor_uid is None:
                parser.error('--successor-uid required for existing worktree assessment')
            result = assess_worktree(args.assess_worktree, args.legacy_uid, args.successor_uid)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get('kernel_path_boundary_sealed', True) else 2
    except (ExclusionRefused, OSError, RuntimeError) as exc:
        print(f'C3c refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
