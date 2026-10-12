#!/usr/bin/env python3
"""Read-only Linux cgroup isolation preflight for the R3D.2 recovery release.

The supervisor MUST NOT freeze user processes from a sudo invocation still in
that user's cgroup: the freeze may suspend the supervisor itself. This report
shows the constraint; it does not stop processes, relocate namespaces, grant
release authority or assert that a cgroup scan is a durable exclusion proof.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

SCHEMA = 'stygnox_recovery_release_cgroup_preflight_v1'
MAX_PIDS = 100_000


class IsolationRefused(RuntimeError):
    """No trustworthy, complete point-in-time cgroup topology."""


def _cgroup_of(proc: Path, pid: int) -> str:
    """Read unified cgroup v2 membership, rejecting hybrid or malformed rows."""
    rows = (proc / str(pid) / 'cgroup').read_text(encoding='utf-8').splitlines()
    unified = [r[3:] for r in rows if r.startswith('0::')]
    if len(unified) != 1:
        raise IsolationRefused('missing or ambiguous unified cgroup membership')
    raw = unified[0]
    if not raw.startswith('/') or '\x00' in raw or '\\' in raw:
        raise IsolationRefused('invalid unified cgroup path')
    parts = PurePosixPath(raw).parts
    if '..' in parts or '.' in raw.split('/') or '//' in raw:
        raise IsolationRefused('noncanonical unified cgroup path')
    return str(PurePosixPath(raw))


def _uid_of(proc: Path, pid: int) -> int:
    body = (proc / str(pid) / 'status').read_text(encoding='utf-8')
    field = re.search(r'^Uid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$', body, re.M)
    if not field:
        raise IsolationRefused('process UID field missing')
    return int(field.group(1))


def _starttime_of(proc: Path, pid: int) -> str:
    raw = (proc / str(pid) / 'stat').read_text(encoding='utf-8')
    pos = raw.rfind(')')
    if pos < 0:
        raise IsolationRefused('invalid proc stat')
    tail = raw[pos + 2:].split()
    if len(tail) < 20:
        raise IsolationRefused('incomplete proc stat')
    return tail[19]  # procfs field 22


def _ancestor_or_same(ancestor: str, child: str) -> bool:
    return ancestor == '/' or child == ancestor or child.startswith(ancestor + '/')


def _common_ancestor(paths: set[str]) -> str:
    if not paths:
        raise IsolationRefused('no predecessor processes identified')
    split = [PurePosixPath(p).parts for p in paths]
    shared = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    return str(PurePosixPath(*shared)) if shared else '/'


def _processes(proc: Path, target_uid: int, supervisor_pid: int) -> dict[str, Any]:
    grouped: dict[str, int] = {}
    total = 0
    incomplete: list[dict[str, Any]] = []
    supervisor_cgroup = _cgroup_of(proc, supervisor_pid)
    scanned = 0
    with os.scandir(proc) as entries:
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            scanned += 1
            if scanned > MAX_PIDS:
                raise IsolationRefused('process count exceeded bounded scan')
            pid = int(entry.name)
            try:
                before = _starttime_of(proc, pid)
                uid = _uid_of(proc, pid)
                group = _cgroup_of(proc, pid) if uid == target_uid else None
                after = _starttime_of(proc, pid)
                if before != after:
                    incomplete.append({'pid': pid, 'reason': 'pid-reused'})
                    continue
            except FileNotFoundError:
                # A process that exited cannot hold a live fd, but this is
                # still a snapshot rather than a process-exclusion barrier.
                continue
            except (OSError, ValueError, IsolationRefused) as exc:
                incomplete.append({'pid': pid, 'reason': type(exc).__name__})
                continue
            if group is not None:
                total += 1
                grouped[group] = grouped.get(group, 0) + 1
    if not grouped:
        common = None
        freezes_supervisor = None
        external_service_required = True
    else:
        common = _common_ancestor(set(grouped))
        freezes_supervisor = _ancestor_or_same(common, supervisor_cgroup)
        # A root-owned systemd service in an independent cgroup is needed
        # when the supervisor is inside the target's subtree. Never suggest
        # freezing / (which would suspend the entire host).
        external_service_required = freezes_supervisor or common == '/'
    return {
        'predecessor_uid_process_count': total,
        'predecessor_cgroup_counts': [{'cgroup': key, 'processes': value}
                                      for key, value in sorted(grouped.items())],
        'candidate_common_freeze_subtree': common,
        'supervisor_cgroup': supervisor_cgroup,
        'candidate_freeze_would_suspend_supervisor': freezes_supervisor,
        'dedicated_root_supervisor_scope_required': external_service_required,
        'process_scan_incomplete_count': len(incomplete),
        'process_scan_incomplete_sample': incomplete[:20],
        'point_in_time_only': True,
    }


def collect(predecessor_uid: int, *, proc: Path = Path('/proc'),
            supervisor_pid: int | None = None, require_root: bool = True) -> dict[str, Any]:
    if not isinstance(predecessor_uid, int) or predecessor_uid <= 0:
        raise IsolationRefused('predecessor UID must be non-root')
    if require_root and (os.name != 'posix' or os.geteuid() != 0):
        raise IsolationRefused('root required for unfiltered procfs scan')
    if supervisor_pid is None:
        supervisor_pid = os.getpid()
    if not (proc / str(supervisor_pid) / 'cgroup').is_file():
        raise IsolationRefused('supervisor cgroup membership not visible')
    scan = _processes(proc, predecessor_uid, supervisor_pid)
    # The process snapshot can never authorise a freeze or an actual transfer.
    return {
        'schema': SCHEMA,
        'predecessor_uid': predecessor_uid,
        'cgroup_mode': 'unified-v2',
        'process_topology': scan,
        'probe_wrote_runtime': False,
        'processes_frozen': False,
        'predecessor_processes_excluded': False,
        'exclusive_supervision_proved': False,
        'original_binding_retired': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'authority_changed': False,
        'live_runtime_modified': False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.predecessor_uid), indent=2, sort_keys=True))
        return 0
    except (OSError, IsolationRefused) as exc:
        print(f'Recovery isolation preflight REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
