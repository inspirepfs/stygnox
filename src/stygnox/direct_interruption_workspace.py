"""C3e read-only protected-workspace snapshot verification.

This verifier is deliberately NOT a relocation, live write barrier, trusted
publisher, authority handoff, or proof of process quiescence. It rejects
cross-owner aliases that could let the old UID modify a 'sealed' replica.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any

from .direct_interruption_exclusion import ExclusionRefused, verify_dac_boundary

SCHEMA = 'stygnox_c3e_protected_workspace_inspection_v1'


class WorkspaceRefused(RuntimeError):
    """Insufficient assurance that the proposed workspace has private inodes."""


def inspect_protected_tree(root: Path, *, predecessor_uid: int, successor_uid: int,
                           max_entries: int = 100_000) -> dict[str, Any]:
    """Inspect a candidate private tree, without following links or changing files.

    DAC assurance requires every nested object to be successor-owned. A hard
    link could otherwise give the predecessor a writable alias outside the
    private directory. Cross-filesystem mounts and directory replacement races
    still require independent trusted supervisor checks and are NOT covered.
    """
    try:
        boundary = verify_dac_boundary(root, predecessor_uid=predecessor_uid,
                                       successor_uid=successor_uid)
    except ExclusionRefused as exc:
        raise WorkspaceRefused(str(exc)) from exc
    root_stat = root.lstat()
    dev = root_stat.st_dev
    dirs, files, entries = 0, 0, 0
    seen: set[tuple[int, int]] = set()
    todo = [root]
    while todo:
        current = todo.pop()
        entries += 1
        if entries > max_entries:
            raise WorkspaceRefused('workspace entry count exceeds scan limit')
        try:
            info = current.lstat()
        except OSError as exc:
            raise WorkspaceRefused(f'workspace entry unavailable: {current}: {exc}') from exc
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise WorkspaceRefused(f'symlink or special file not admitted: {current}')
        if info.st_uid != successor_uid:
            raise WorkspaceRefused(f'non-successor-owned entry: {current}')
        if info.st_dev != dev:
            raise WorkspaceRefused(f'cross-device entry: {current}')
        key = (info.st_dev, info.st_ino)
        if key in seen:
            raise WorkspaceRefused(f'duplicate inode: {current}')
        seen.add(key)
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            if mode != 0o700:
                raise WorkspaceRefused(f'non-private directory: {current}')
            dirs += 1
            try:
                with os.scandir(current) as scan:
                    children = [Path(item.path) for item in scan]
            except OSError as exc:
                raise WorkspaceRefused(f'unreadable directory: {current}: {exc}') from exc
            todo.extend(children)
        elif stat.S_ISREG(info.st_mode):
            if mode & 0o077 or mode & 0o7000 or not (mode & 0o400):
                raise WorkspaceRefused(f'unsafe file permissions: {current}')
            relative = current.relative_to(root).parts
            if relative and relative[0] == '.stygnox' and mode & 0o100:
                raise WorkspaceRefused(f'executable authority data file: {current}')
            if info.st_nlink != 1:
                raise WorkspaceRefused(f'externally linkable inode (nlink != 1): {current}')
            files += 1
        else:
            raise WorkspaceRefused(f'symlink or special file not admitted: {current}')
    return {
        'schema': SCHEMA,
        'protected_path': str(root),
        'protected_dev': dev,
        'protected_inode': root_stat.st_ino,
        'ancestors': boundary['ancestors'],
        'directories_examined': dirs,
        'regular_files_examined': files,
        'tree_snapshot_private': True,
        'mount_aliases_excluded': False,
        'concurrent_replacement_excluded': False,
        'preopened_legacy_fds_excluded': False,
        'authority_changed': False,
        'handoff_admissible': False,
    }


def inspect_transition_candidate(original: Path, protected: Path, *,
                                 predecessor_uid: int, successor_uid: int) -> dict[str, Any]:
    """Refuse to treat a relocated copy as authoritative without a binding transfer.

    Rewriting controller/worktree path references would constitute a separate
    authority-changing action. Even an entirely private copy remains blocked
    while the old source path is independently writable to the legacy UID.
    """
    if not original.is_absolute() or '..' in original.parts:
        raise WorkspaceRefused('original must be an absolute, canonical directory')
    try:
        old = original.lstat()
    except OSError as exc:
        raise WorkspaceRefused(f'original source unavailable: {exc}') from exc
    if not stat.S_ISDIR(old.st_mode):
        raise WorkspaceRefused('original source not a physical directory')
    candidate = inspect_protected_tree(protected,
                                       predecessor_uid=predecessor_uid,
                                       successor_uid=successor_uid)
    if os.path.commonpath((str(original), str(protected))) in (str(original), str(protected)):
        raise WorkspaceRefused('protected and original trees must be disjoint')
    if (old.st_dev, old.st_ino) == (candidate['protected_dev'], candidate['protected_inode']):
        raise WorkspaceRefused('original and protected directory share an inode')
    return {
        'schema': 'stygnox_c3e_relocation_candidate_v1',
        'original': str(original),
        'original_dev': old.st_dev,
        'original_inode': old.st_ino,
        'protected': candidate,
        'old_path_retired': False,
        'old_controller_mutations_excluded': False,
        'original_worktree_binding_transferred': False,
        'installed_successor_binding_qualified': False,
        'dual_authority_proved_absent': False,
        'handoff_admissible': False,
        'authority_changed': False,
        'live_runtime_modified': False,
    }
