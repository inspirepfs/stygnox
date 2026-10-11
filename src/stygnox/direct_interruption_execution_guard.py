"""C3k: refuse every ordinary execution/mutation entry in quarantined runtime.

This is a conservative additional tripwire, NOT a handoff lock or authority
publisher. It deliberately cannot interpret, repair or release quarantine.
Absence of a receipt does not itself establish execution authority; all
ordinary controller, transaction and plan checks still apply.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


QUARANTINE_MARKER = 'direct-interruption-quarantined-binding.json'


class QuarantinedRuntime(RuntimeError):
    """Protected recovery state cannot be used by ordinary runtime commands."""


def refuse_quarantined_runtime(project: Path) -> None:
    """Fail closed on any quarantine marker, even a malformed or symlinked one.

    This is a read-only early admission check. Filesystem/identity protection
    and exclusion of in-flight predecessor processes remain separate duties.
    """
    runtime = Path(project) / '.stygnox'
    try:
        info = os.lstat(runtime)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise QuarantinedRuntime(f'cannot inspect protected runtime: {exc}') from exc
    if not stat.S_ISDIR(info.st_mode):
        raise QuarantinedRuntime('protected runtime directory is not a real directory')
    try:
        os.lstat(runtime / QUARANTINE_MARKER)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise QuarantinedRuntime(f'cannot inspect quarantine barrier: {exc}') from exc
    raise QuarantinedRuntime('RECOVERY_QUARANTINED: ordinary controller/scheduler operations are forbidden')
