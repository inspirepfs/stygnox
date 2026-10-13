#!/usr/bin/env python3
"""ROOT-PROTECTED-only one-shot isolated worktree stage; always exit 75.

Not an execution gate. Requires separate root-controlled installation before
any privileged use. Never run sudo against the mutable development checkout.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import types

ROOT = Path(__file__).absolute().parent.parent
STY = ROOT / 'src/stygnox'


def _protected_source() -> bool:
    dirs = (*reversed(ROOT.parents), ROOT, ROOT / 'scripts', ROOT / 'src', STY)
    files = (Path(__file__), STY / 'direct_interruption_isolated_workspace.py',
             STY / 'direct_interruption_host_readiness.py',
             STY / 'direct_interruption_custody_cutover.py',
             STY / 'direct_interruption_custody_intake.py',
             STY / 'direct_interruption_blocked_commissioning.py')
    try:
        return (all(stat.S_ISDIR((s := p.lstat()).st_mode) and s.st_uid == 0 and
                    not s.st_mode & 0o022 for p in dirs) and
                all(stat.S_ISREG((s := p.lstat()).st_mode) and s.st_uid == 0 and
                    not s.st_mode & 0o022 for p in files))
    except OSError:
        return False


def _deny(phase: str = 'ISOLATED_WORKSPACE_REFUSED') -> int:
    print(json.dumps({'phase': phase, 'legacy_controller_excluded': False,
                      'successor_execution_authorised': False,
                      'provider_executed': False}, sort_keys=True))
    return 75


if os.geteuid() == 0 and not _protected_source():
    raise SystemExit(_deny())

if 'stygnox' not in sys.modules:
    package = types.ModuleType('stygnox')
    package.__path__ = [str(STY)]
    sys.modules['stygnox'] = package
spec = importlib.util.spec_from_file_location(
    'stygnox.direct_interruption_isolated_workspace',
    STY / 'direct_interruption_isolated_workspace.py')
if spec is None or spec.loader is None:
    raise SystemExit(_deny())
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ['--prepare-data-only']:
            if os.geteuid() == 0 and _protected_source():
                return _deny(module.prepare_live_denied_workspace()['phase'])
        elif argv == ['--verify-data-only']:
            if os.geteuid() == 0 and _protected_source():
                module.commissioning._trusted_root(module.intake.ROOT)
                return _deny(module.verify_isolated_workspace(
                    module.intake.ROOT, uid=0,
                    old_candidate=module.intake.ROOT / module.intake.CANDIDATE)['phase'])
    except (module.IsolatedWorkspaceRefused, module.readiness.ReadinessRefused,
            module.commissioning.BlockedCommissioningRefused,
            module.intake.CustodyIntakeRefused, OSError, ValueError, KeyError, TypeError):
        pass
    return _deny()


if __name__ == '__main__':
    raise SystemExit(main())
