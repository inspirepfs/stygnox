#!/usr/bin/env python3
"""Release 02: attest a separate, root-owned system service control process.

Run ONLY from an independently launched systemd *system* service, with this
script and its isolation dependency installed under trusted root-controlled
ancestry. No cgroup.freeze, process termination, filesystem retirement,
authority transfer, or installed controller execution occurs here.

A passing attestation proves a point-in-time *supervisor boundary*, NOT
exclusive predecessor exclusion: all UID processes still require an explicit
supervised quiescence protocol and a crash-safe namespace retirement.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

SCHEMA = 'stygnox_recovery_release02_root_service_boundary_v1'
UNIT = re.compile(r'^/system\.slice/stygnox-recovery-release02-[a-zA-Z0-9_.-]+\.service$')


class SupervisorBoundaryRefused(RuntimeError):
    """Isolated, trusted service execution cannot be established."""


def _trusted_file(path: Path) -> str:
    """Check exact physical root-controlled ancestry before loading any code.

    The path is expected to be staged by the operator to a root-private service
    directory, not executed with sudo from a mutable home checkout.
    """
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        raise SupervisorBoundaryRefused('absolute physical trusted source required')
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (info.st_mode & 0o022):
            raise SupervisorBoundaryRefused(f'untrusted source ancestor: {parent}')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or (info.st_mode & 0o022)
            or info.st_mode & 0o6000):
        raise SupervisorBoundaryRefused(f'untrusted service source file: {path}')
    # Open with O_NOFOLLOW; revalidate identity through the descriptor, not
    # merely an untrusted pathname check.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        pinned = os.fstat(fd)
        if (pinned.st_dev, pinned.st_ino) != (info.st_dev, info.st_ino):
            raise SupervisorBoundaryRefused('service source changed during inspection')
        digest = hashlib.sha256()
        while True:
            part = os.read(fd, 1024 * 1024)
            if not part:
                break
            digest.update(part)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _load_trusted_isolation(path: Path) -> Any:
    _trusted_file(path)
    spec = importlib.util.spec_from_file_location('_stygnox_trusted_isolation', path)
    if spec is None or spec.loader is None:
        raise SupervisorBoundaryRefused('isolation helper cannot load')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_supervisor(group: str, predecessor_groups: list[str], *, incomplete: int) -> None:
    if not UNIT.fullmatch(group):
        raise SupervisorBoundaryRefused('not running in dedicated systemd system service scope')
    if incomplete:
        raise SupervisorBoundaryRefused('incomplete process/cgroup scan')
    for target in predecessor_groups:
        if target == group or target.startswith(group + '/') or group.startswith(target + '/'):
            raise SupervisorBoundaryRefused('predecessor process shares supervisor subtree')


def collect(predecessor_uid: int, *, proc: Path = Path('/proc'),
            supervisor_pid: int | None = None,
            script: Path | None = None) -> dict[str, Any]:
    if os.name != 'posix' or os.geteuid() != 0:
        raise SupervisorBoundaryRefused('root service required')
    if predecessor_uid <= 0:
        raise SupervisorBoundaryRefused('non-root predecessor UID required')
    if supervisor_pid is None:
        supervisor_pid = os.getpid()
    if script is None:
        script = Path(__file__).absolute()
    script = Path(script)
    source_hash = _trusted_file(script)
    dependency = script.with_name('probe_recovery_release_isolation.py')
    dependency_hash = _trusted_file(dependency)
    isolation = _load_trusted_isolation(dependency)
    try:
        state = isolation.collect(predecessor_uid, proc=proc,
                                  supervisor_pid=supervisor_pid, require_root=True)
    except (OSError, ValueError, isolation.IsolationRefused) as exc:
        raise SupervisorBoundaryRefused(f'process topology cannot be verified: {exc}') from exc
    topology = state['process_topology']
    group = topology['supervisor_cgroup']
    targets = [entry['cgroup'] for entry in topology['predecessor_cgroup_counts']]
    _validate_supervisor(group, targets,
                         incomplete=topology['process_scan_incomplete_count'])
    return {
        'schema': SCHEMA,
        'predecessor_uid': predecessor_uid,
        'supervisor_pid': supervisor_pid,
        'supervisor_cgroup': group,
        'predecessor_cgroup_count': len(targets),
        'predecessor_uid_process_count': topology['predecessor_uid_process_count'],
        'process_scan_complete': True,
        'supervisor_source_sha256': source_hash,
        'isolation_helper_sha256': dependency_hash,
        'independent_system_service_scope_proved': True,
        'dedicated_source_root_controlled': True,
        'point_in_time_only': True,
        'processes_frozen': False,
        'predecessor_processes_excluded': False,
        'old_controller_relaunch_excluded': False,
        'original_binding_retired': False,
        'authority_changed': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'live_runtime_modified': False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.predecessor_uid), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, SupervisorBoundaryRefused) as exc:
        print(f'Recovery Release 02 supervisor REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
