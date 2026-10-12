#!/usr/bin/env python3
"""Data-only R3D.2 blocked commissioning. Always exits 75; never an execution gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

# -I compatible. Imports ONLY the two exact sibling data-only recovery modules.
ROOT = Path(__file__).absolute().parent.parent
STY = ROOT / 'src/stygnox'
PKG = 'stygnox'
if PKG not in sys.modules:
    import types
    package = types.ModuleType(PKG)
    package.__path__ = [str(STY)]
    sys.modules[PKG] = package
source = STY / 'direct_interruption_blocked_commissioning.py'
spec = importlib.util.spec_from_file_location(PKG + '.direct_interruption_blocked_commissioning', source)
if spec is None or spec.loader is None:
    raise RuntimeError('protected commissioning module not found')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv != ['--seal-blocked']:
        print(json.dumps({'phase': 'BLOCKED_COMMISSIONING_REFUSED',
                          'reason_class': 'INVALID_ARGUMENT',
                          'successor_execution_authorised': False}))
        return 75
    try:
        print(json.dumps(module.seal_blocked_commissioning(), sort_keys=True))
    except (module.BlockedCommissioningRefused, OSError, ValueError, KeyError, TypeError,
            module.custody.CustodyIntakeRefused):
        print(json.dumps({'phase': 'BLOCKED_COMMISSIONING_REFUSED',
                          'successor_execution_authorised': False}, sort_keys=True))
    return 75


if __name__ == '__main__':
    sys.exit(main())
