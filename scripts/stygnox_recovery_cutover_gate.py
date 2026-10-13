#!/usr/bin/env python3
"""Read-only hostile R3D.2 host cutover audit; exit code 75 ALWAYS.

Run privileged only from a separate root-owned readonly installed artifact.
Refuses mutable source at the bootstrap before importing project Python.
No CLI option can commission, release, retire, mount, or run a provider.
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
FILES = (
    Path(__file__),
    *(STY / ('direct_interruption_' + name + '.py') for name in (
        'cutover_gate', 'custody_intake', 'custody_cutover', 'blocked_commissioning',
        'host_readiness', 'isolated_workspace')),
)


def _protected_source() -> bool:
    try:
        dirs = (*reversed(ROOT.parents), ROOT, ROOT / 'scripts', ROOT / 'src', STY)
        return (all(stat.S_ISDIR((info := d.lstat()).st_mode) and info.st_uid == 0 and
                    not info.st_mode & 0o022 for d in dirs) and
                all(stat.S_ISREG((info := f.lstat()).st_mode) and info.st_uid == 0 and
                    not info.st_mode & 0o022 for f in FILES))
    except OSError:
        return False


def _refuse() -> int:
    print(json.dumps({'phase': 'HOST_CUTOVER_REFUSED', 'execution_authority': 'NONE',
                      'successor_execution_authorised': False, 'provider_executed': False},
                     sort_keys=True))
    return 75


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # No unguarded import, no valid invocation from the development checkout.
    if argv != ['--audit-read-only'] or os.geteuid() != 0 or not _protected_source():
        return _refuse()
    try:
        if 'stygnox' not in sys.modules:
            package = types.ModuleType('stygnox')
            package.__path__ = [str(STY)]
            sys.modules['stygnox'] = package
        spec = importlib.util.spec_from_file_location(
            'stygnox.direct_interruption_cutover_gate',
            STY / 'direct_interruption_cutover_gate.py')
        if spec is None or spec.loader is None:
            return _refuse()
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        report = module.audit_live_host()
        print(json.dumps(report, sort_keys=True))
    except Exception:
        # Fail closed rather than exposing sensitive process/custody paths.
        return _refuse()
    return 75


if __name__ == '__main__':
    raise SystemExit(main())
