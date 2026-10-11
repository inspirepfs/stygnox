"""C3c kernel-enforced predecessor write-exclusion primitive.

This is NOT authority to publish a transfer, and cannot stop a predecessor that
already has a writable file descriptor. A protected checkout and its runtime
must be rooted under trusted non-predecessor-owned ancestors and served to a
separate unprivileged successor UID. This verifier never changes a live path.
"""
from __future__ import annotations

from pathlib import Path
import os
import stat
from typing import Any

SCHEMA = "stygnox_c3c_linux_dac_boundary_v1"


class ExclusionRefused(RuntimeError):
    """The OS boundary cannot prevent non-cooperating legacy writes."""


def verify_dac_boundary(path: Path, *, predecessor_uid: int, successor_uid: int) -> dict[str, Any]:
    """Audit the Linux directory chain for a separately owned private tree.

    No evidence returned here proves process quiescence, open-fd revocation,
    a transfer lock, human consent or installed-successor identity. In
    particular this result must never be used as execution authority.
    """
    if os.name != "posix" or not Path("/proc/self/status").exists():
        raise ExclusionRefused("Linux process/UID isolation is required")
    if not isinstance(predecessor_uid, int) or not isinstance(successor_uid, int):
        raise ExclusionRefused("UIDs must be integers")
    if predecessor_uid <= 0 or successor_uid <= 0 or predecessor_uid == successor_uid:
        raise ExclusionRefused("distinct non-root predecessor and successor UIDs required")
    directory = Path(path)
    if not directory.is_absolute() or ".." in directory.parts:
        raise ExclusionRefused("absolute, canonical directory path required")
    # Do not resolve symlinks: doing so would disguise a substituted ancestor.
    ancestors = list(reversed(directory.parents)) + [directory]
    checked: list[dict[str, Any]] = []
    for idx, entry in enumerate(ancestors):
        try:
            info = entry.lstat()
        except OSError as exc:
            raise ExclusionRefused(f"unreadable or missing directory {entry}: {exc}") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise ExclusionRefused(f"symlink or non-directory ancestor: {entry}")
        permissions = stat.S_IMODE(info.st_mode)
        if idx != len(ancestors) - 1:
            if info.st_uid not in (0, successor_uid):
                raise ExclusionRefused(f"ancestor owned by an untrusted UID: {entry}")
            if permissions & 0o022:
                raise ExclusionRefused(f"group/other writable ancestor: {entry}")
        else:
            if info.st_uid != successor_uid:
                raise ExclusionRefused("sealed directory must belong to successor UID")
            if permissions & 0o077 or permissions & 0o700 != 0o700:
                raise ExclusionRefused("sealed directory must be private owner-rwx (0700)")
        checked.append({"path": str(entry), "uid": info.st_uid,
                        "mode": oct(permissions), "device": info.st_dev, "inode": info.st_ino})
    # This is a snapshot, not a lease; an independently trusted publisher must
    # recheck under process exclusion before and after any atomic publication.
    return {
        "schema": SCHEMA,
        "path": str(directory),
        "predecessor_uid": predecessor_uid,
        "successor_uid": successor_uid,
        "ancestors": checked,
        "ordinary_unprivileged_predecessor_new_writes_denied_by_dac": True,
        "predecessor_capabilities_excluded": False,
        "predecessor_processes_quiescent": False,
        "preexisting_writable_descriptors_excluded": False,
        "exclusive_handoff_proved": False,
        "handoff_admissible": False,
        "authority_changed": False,
    }
