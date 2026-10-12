#!/usr/bin/env python3
"""C3n: read-only Linux predecessor exposure inventory.

Root is required for meaningful visibility. This is a point-in-time diagnostic,
NOT process exclusion, predecessor retirement, handoff, or release authority.
Never writes the inspected paths or invokes the installed controller/provider.
Only emits selected metadata; never emits full command lines or environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import sys
from typing import Any

SCHEMA = "stygnox_c3n_live_predecessor_inventory_v1"
MAX_INODES = 250_000
MAX_PROCESSES = 100_000
MAX_FDS_PER_PROCESS = 65536
MAX_FINDINGS = 150


def _canonical_absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or str(path) == '/':
        raise ValueError('expected a non-root absolute path with no parent traversal')
    return path


def _stat_key(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _inode_catalog(worktree: Path) -> tuple[set[tuple[int, int]], dict[str, Any]]:
    """Build bounded inode set without following symlinks or reading file content."""
    inodes: set[tuple[int, int]] = set()
    errors: list[str] = []
    walked = 0
    symlinks = 0
    def walk(dirname: Path) -> None:
        nonlocal walked, symlinks
        with os.scandir(dirname) as entries:
            for entry in entries:
                if walked >= MAX_INODES:
                    raise RuntimeError('inode catalog limit exceeded; incomplete inventory')
                walked += 1
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    errors.append(f'entry-stat:{type(exc).__name__}')
                    continue
                if stat.S_ISLNK(info.st_mode):
                    symlinks += 1
                    continue
                inodes.add(_stat_key(info))
                if stat.S_ISDIR(info.st_mode):
                    try:
                        walk(Path(entry.path))
                    except OSError as exc:
                        errors.append(f'directory-scan:{type(exc).__name__}')
    base = worktree.lstat()
    if not stat.S_ISDIR(base.st_mode):
        raise ValueError('worktree is not a real directory')
    inodes.add(_stat_key(base))
    try:
        walk(worktree)
    except OSError as exc:
        errors.append(f'directory-scan:{type(exc).__name__}')
    return inodes, {'catalogued_inodes': len(inodes), 'entries_seen': walked,
                    'symlinks_skipped': symlinks, 'errors': errors}


def _read_executable_hash(path: Path) -> dict[str, Any]:
    """Use O_NOFOLLOW and an inode pin while hashing. No execution or mutation."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return {'available': False, 'error': type(exc).__name__}
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return {'available': False, 'error': 'not_regular'}
        digest = hashlib.sha256()
        with os.fdopen(os.dup(fd), 'rb') as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
        return {'available': True, 'sha256': digest.hexdigest(),
                'device': info.st_dev, 'inode': info.st_ino, 'owner_uid': info.st_uid,
                'mode': oct(stat.S_IMODE(info.st_mode))}
    finally:
        os.close(fd)


def _ancestor_audit(path: Path) -> list[dict[str, Any]]:
    chain = list(reversed(path.parents)) + [path]
    rows = []
    for item in chain:
        try:
            info = item.lstat()
            rows.append({'path': str(item), 'owner_uid': info.st_uid,
                         'mode': oct(stat.S_IMODE(info.st_mode)),
                         'dev': info.st_dev, 'inode': info.st_ino,
                         'real_directory': stat.S_ISDIR(info.st_mode),
                         'trusted_root_ancestor': (stat.S_ISDIR(info.st_mode)
                            and info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o022)})
        except OSError as exc:
            rows.append({'path': str(item), 'error': type(exc).__name__,
                         'trusted_root_ancestor': False})
    return rows


def _read_starttime(proc_dir: Path) -> str:
    content = (proc_dir / 'stat').read_text(encoding='ascii', errors='replace')
    after = content.rsplit(')', 1)[1].split()
    if len(after) < 20:
        raise ValueError('short proc stat')
    return after[19]  # field 22 of /proc/pid/stat


def _read_uid(proc_dir: Path) -> int:
    content = (proc_dir / 'status').read_text(encoding='ascii', errors='replace')
    for line in content.splitlines():
        if line.startswith('Uid:'):
            return int(line.split()[1])
    raise ValueError('missing Uid in proc status')


def _as_candidate(value: str, paths: tuple[str, ...]) -> bool:
    return any(value == p or value.startswith(p + '/') or
               value.startswith(p + ' (deleted)') for p in paths)


def _process_inventory(proc_root: Path, worktree: Path, old_installed: Path,
                       inode_keys: set[tuple[int, int]], predecessor_uid: int
                       ) -> dict[str, Any]:
    target_paths = (str(worktree), str(old_installed))
    findings: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    gone = 0
    processes = 0
    predecessor_processes = 0
    related_total = 0
    fd_checks = 0
    # Neither a zero-match scan nor an empty error list proves process exclusion.
    entries = sorted((p for p in proc_root.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    if len(entries) > MAX_PROCESSES:
        raise RuntimeError('process inventory limit exceeded')
    for directory in entries:
        pid = int(directory.name)
        if pid == os.getpid():
            continue
        try:
            initial = _read_starttime(directory)
            uid = _read_uid(directory)
        except FileNotFoundError:
            gone += 1
            continue
        except (OSError, ValueError, IndexError) as exc:
            unreadable.append({'pid': pid, 'reason': f'process-metadata:{type(exc).__name__}'})
            continue
        processes += 1
        if uid == predecessor_uid:
            predecessor_processes += 1
        match_fields: list[str] = []
        errors: list[str] = []
        try:
            raw = (directory / 'cmdline').read_bytes()
            # Never expose command-line arguments; only report whether a target path
            # is present (avoids accidentally capturing credentials).
            if any(_as_candidate(x.decode('utf-8', errors='replace'), target_paths)
                   for x in raw.split(b'\x00') if x):
                match_fields.append('cmdline-path')
        except (OSError, ValueError) as exc:
            errors.append(f'cmdline:{type(exc).__name__}')
        for part in ('exe', 'cwd', 'root'):
            try:
                link = os.readlink(directory / part)
                if _as_candidate(link, target_paths):
                    match_fields.append(part + '-path')
                try:
                    info = os.stat(directory / part)
                    if _stat_key(info) in inode_keys:
                        match_fields.append(part + '-inode')
                except FileNotFoundError:
                    pass
            except FileNotFoundError:
                pass
            except (PermissionError, OSError) as exc:
                errors.append(f'{part}:{type(exc).__name__}')
        fd_path = directory / 'fd'
        try:
            with os.scandir(fd_path) as handles:
                count = 0
                for handle in handles:
                    count += 1
                    if count > MAX_FDS_PER_PROCESS:
                        errors.append('fd-limit-exceeded')
                        break
                    fd_checks += 1
                    try:
                        linked = os.readlink(handle.path)
                        if _as_candidate(linked, target_paths):
                            match_fields.append('fd-path')
                        info = os.stat(handle.path)
                        if _stat_key(info) in inode_keys:
                            match_fields.append('fd-inode')
                    except FileNotFoundError:
                        continue  # process closed this descriptor while enumerating
                    except (OSError, ValueError) as exc:
                        errors.append(f'fd-entry:{type(exc).__name__}')
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            errors.append(f'fd-directory:{type(exc).__name__}')
        # mappings may include old executables/mapped files with no open FD.
        try:
            with (directory / 'maps').open(encoding='utf-8', errors='replace') as f:
                for line in f:
                    # Extract only mapped path, never include arbitrary map contents.
                    parts = line.split(maxsplit=5)
                    if len(parts) == 6 and _as_candidate(parts[5].strip(), target_paths):
                        match_fields.append('mapping-path')
                        break
        except (OSError, ValueError) as exc:
            errors.append(f'maps:{type(exc).__name__}')
        try:
            if _read_starttime(directory) != initial:
                errors.append('pid-reused-during-scan')
        except FileNotFoundError:
            gone += 1
        except (OSError, ValueError, IndexError) as exc:
            errors.append(f'end-process-metadata:{type(exc).__name__}')
        if errors:
            unreadable.append({'pid': pid, 'uid': uid, 'reasons': sorted(set(errors))[:12]})
        if match_fields:
            related_total += 1
            if len(findings) < MAX_FINDINGS:
                findings.append({'pid': pid, 'uid': uid, 'starttime': initial,
                                 'references': sorted(set(match_fields))})
    return {'processes_examined': processes, 'predecessor_uid_processes': predecessor_processes,
            'related_process_count': related_total, 'related_processes': findings,
            'related_list_truncated': related_total > len(findings),
            'uninspectable_count': len(unreadable), 'uninspectable_processes': unreadable[:MAX_FINDINGS],
            'uninspectable_list_truncated': len(unreadable) > MAX_FINDINGS,
            'processes_gone_during_scan': gone, 'descriptor_checks': fd_checks}


def inventory(worktree: Path, old_installed: Path, predecessor_uid: int,
              *, proc_root: Path = Path('/proc'), enforce_root: bool = True,
              expected_installed_sha256: str | None = None) -> dict[str, Any]:
    """Root-operated, no mutation. Always returns negative transfer-authority flags."""
    worktree = _canonical_absolute(str(worktree))
    old_installed = _canonical_absolute(str(old_installed))
    if enforce_root and os.geteuid() != 0:
        raise PermissionError('root required for process visibility; refusal is mandatory')
    if predecessor_uid <= 0:
        raise ValueError('predecessor UID must be non-root positive integer')
    if expected_installed_sha256 is not None and not re.fullmatch(r'[a-f0-9]{64}', expected_installed_sha256):
        raise ValueError('expected executable SHA-256 must be 64 lower-case hex characters')
    before = worktree.lstat()
    inodes, catalog = _inode_catalog(worktree)
    ancestors = _ancestor_audit(worktree.parent)
    process_scan = _process_inventory(proc_root, worktree, old_installed, inodes, predecessor_uid)
    root_anchored = all(x['trusted_root_ancestor'] for x in ancestors)
    try:
        after = worktree.lstat()
        identity_stable = _stat_key(before) == _stat_key(after)
    except OSError:
        identity_stable = False
    executable = _read_executable_hash(old_installed)
    executable['matches_expected_sha256'] = (
        expected_installed_sha256 is not None and executable.get('sha256') == expected_installed_sha256)
    return {'schema': SCHEMA,
            'worktree': str(worktree), 'installed_predecessor_path': str(old_installed),
            'predecessor_uid': predecessor_uid,
            'worktree_identity': {'device': before.st_dev,
                                  'inode': before.st_ino,
                                  'owner_uid': before.st_uid},
            'original_identity_stable_during_scan': identity_stable,
            'installed_predecessor_identity': executable,
            'original_parent_ancestors': ancestors,
            'original_parent_root_controlled': root_anchored,
            'inode_catalog': catalog,
            'process_scan': process_scan,
            'scan_complete': identity_stable and not catalog['errors'] and process_scan['uninspectable_count'] == 0
                             and not process_scan['related_list_truncated']
                             and not process_scan['uninspectable_list_truncated'],
            'point_in_time_only': True,
            'unknown_predecessor_holders_excluded': False,
            'real_predecessor_exclusion_proved': False,
            'original_binding_retired': False,
            'authority_changed': False,
            'provider_executed': False,
            'live_runtime_modified': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--installed-predecessor', type=Path, required=True)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    parser.add_argument('--expected-installed-sha256', type=str, required=True)
    args = parser.parse_args()
    try:
        output = inventory(args.original, args.installed_predecessor, args.predecessor_uid,
                           expected_installed_sha256=args.expected_installed_sha256)
        print(json.dumps(output, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'C3n read-only predecessor inventory REFUSED: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
