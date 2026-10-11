"""C3f narrow root-supervised predecessor path retirement primitive.

This physically retires a path in a *trusted root-controlled namespace*; it does
NOT drain processes, revoke preopened FDs, publish controller authority, or
qualify a new worktree binding. Callers must hold their own supervisory process
boundary. Deliberately not wired into any CLI/recovery mutation command.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any


class RetirementRefused(RuntimeError):
    """Cannot establish the preconditions for safe root-owned path retirement."""


def _trusted_ancestor_chain(path: Path) -> None:
    if not path.is_absolute() or '..' in path.parts or str(path) == '/':
        raise RetirementRefused('absolute non-root canonical path required')
    for entry in (*reversed(path.parents), path):
        try:
            info = entry.lstat()
        except OSError as exc:
            raise RetirementRefused(f'unsafe or missing ancestor: {entry}: {exc}') from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (stat.S_IMODE(info.st_mode) & 0o022):
            raise RetirementRefused(f'ancestor is not a trusted root-controlled directory: {entry}')


def _open_trusted_parent(parent: Path, *, vault: bool) -> int:
    _trusted_ancestor_chain(parent)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(parent, flags)
    except OSError as exc:
        raise RetirementRefused(f'cannot pin trusted parent {parent}: {exc}') from exc
    info = os.fstat(fd)
    if info.st_uid != 0 or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o022:
        os.close(fd)
        raise RetirementRefused(f'parent identity changed: {parent}')
    if vault and stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise RetirementRefused('retirement vault must be root-only (0700 or stricter)')
    return fd


def retire_predecessor_path(original: Path, retired: Path, *,
                            predecessor_uid: int,
                            expected_dev: int, expected_inode: int) -> dict[str, Any]:
    """Atomically withdraw a predecessor path into a root-only vault.

    An exact filesystem identity must be supplied by the trusted operator, not
    discovered and silently adopted by this operation. Both parent directories
    and their entire ancestor chains must be root-controlled. Same-filesystem
    rename and parent-directory fsync bound the namespace mutation. An
    interrupted caller MUST use separate verification/reconciliation before
    any later authority action; this result is never a handoff receipt.
    """
    if os.name != 'posix' or not Path('/proc/self/status').exists() or os.geteuid() != 0:
        raise RetirementRefused('Linux root supervisor required')
    if predecessor_uid <= 0 or expected_dev <= 0 or expected_inode <= 0:
        raise RetirementRefused('valid predecessor UID and positive inode identity required')
    original, retired = Path(original), Path(retired)
    if (not original.is_absolute() or not retired.is_absolute()
            or '..' in original.parts or '..' in retired.parts
            or original == retired or original.parent == retired.parent
            or original.name in ('', '.', '..') or retired.name in ('', '.', '..')):
        raise RetirementRefused('distinct absolute original and vault destinations required')
    old_fd = _open_trusted_parent(original.parent, vault=False)
    try:
        vault_fd = _open_trusted_parent(retired.parent, vault=True)
        try:
            if os.fstat(old_fd).st_dev != os.fstat(vault_fd).st_dev:
                raise RetirementRefused('retirement must remain on one filesystem')
            try:
                old = os.stat(original.name, dir_fd=old_fd, follow_symlinks=False)
            except OSError as exc:
                raise RetirementRefused(f'predecessor path unavailable: {exc}') from exc
            if (not stat.S_ISDIR(old.st_mode) or old.st_uid != predecessor_uid
                    or (old.st_dev, old.st_ino) != (expected_dev, expected_inode)):
                raise RetirementRefused('predecessor directory identity or owner mismatch')
            try:
                os.stat(retired.name, dir_fd=vault_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise RetirementRefused('vault destination already exists')
            # Destination directory is root-owned/private, so an unprivileged
            # predecessor cannot race creation of the checked absent name.
            try:
                os.rename(original.name, retired.name,
                          src_dir_fd=old_fd, dst_dir_fd=vault_fd)
                os.fsync(vault_fd)
                os.fsync(old_fd)
            except OSError as exc:
                raise RetirementRefused(
                    f'retirement write failed, reconcile original/vault paths before proceeding: {exc}'
                ) from exc
            try:
                moved = os.stat(retired.name, dir_fd=vault_fd, follow_symlinks=False)
                os.stat(original.name, dir_fd=old_fd, follow_symlinks=False)
            except FileNotFoundError:
                old_name_absent = True
            else:
                old_name_absent = False
            if not old_name_absent or (moved.st_dev, moved.st_ino) != (expected_dev, expected_inode):
                raise RetirementRefused('post-rename identity mismatch; authority stays blocked')
            return {
                'schema': 'stygnox_c3f_supervised_namespace_retirement_v1',
                'original_path': str(original),
                'retired_path': str(retired),
                'original_device': expected_dev,
                'original_inode': expected_inode,
                'old_path_missing': True,
                'root_only_vault': True,
                'parent_directories_synced': True,
                'preopened_descriptors_revoked': False,
                'other_legacy_processes_excluded': False,
                'original_controller_authority_retired': False,
                'successor_binding_transferred': False,
                'handoff_admissible': False,
            }
        finally:
            os.close(vault_fd)
    finally:
        os.close(old_fd)
