#!/usr/bin/env python3
"""Inspect pre-existing R3D.2 root custody. Read-only; returns 75 always."""
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
    # This bootstrap MUST refuse a mutable checkout BEFORE importing ANY
    # repository Python with root privileges. Read-only metadata only.
    dirs = (*reversed(ROOT.parents), ROOT, ROOT / 'scripts', ROOT / 'src', STY)
    files = (Path(__file__), STY / 'direct_interruption_host_readiness.py',
             STY / 'direct_interruption_custody_cutover.py',
             STY / 'direct_interruption_custody_intake.py',
             STY / 'direct_interruption_blocked_commissioning.py')
    try:
        for path in dirs:
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or not stat.S_ISDIR(info.st_mode):
                return False
        for path in files:
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022 or not stat.S_ISREG(info.st_mode):
                return False
    except OSError:
        return False
    return True


if os.geteuid() == 0 and not _protected_source():
    print(json.dumps({'schema': 'stygnox_r3d2_host_readiness_denied_v1',
                      'phase': 'HOST_READINESS_REFUSED', 'execution_authority': 'NONE',
                      'successor_execution_authorised': False, 'provider_executed': False},
                     sort_keys=True))
    raise SystemExit(75)

if 'stygnox' not in sys.modules:
    package = types.ModuleType('stygnox')
    package.__path__ = [str(STY)]
    sys.modules['stygnox'] = package
spec = importlib.util.spec_from_file_location(
    'stygnox.direct_interruption_host_readiness',
    STY / 'direct_interruption_host_readiness.py')
if spec is None or spec.loader is None:
    raise SystemExit(75)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    report = module.denied_report()
    if argv == ['--audit-existing-root-custody']:
        try:
            report = module.audit_live_host()
        except (module.ReadinessRefused, OSError, ValueError, KeyError, TypeError):
            pass
    print(json.dumps(report, sort_keys=True))
    return module.EXIT_DENIED


if __name__ == '__main__':
    raise SystemExit(main())
