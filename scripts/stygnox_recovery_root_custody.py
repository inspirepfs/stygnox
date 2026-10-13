#!/usr/bin/env python3
"""One-shot root-only R3D.2 custody publication. Every exit denies startup."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).absolute().parent.parent
STY = ROOT / 'src/stygnox'
if 'stygnox' not in sys.modules:
    package = types.ModuleType('stygnox')
    package.__path__ = [str(STY)]
    sys.modules['stygnox'] = package
spec = importlib.util.spec_from_file_location('stygnox.direct_interruption_custody_cutover',
                                               STY / 'direct_interruption_custody_cutover.py')
if spec is None or spec.loader is None:
    raise SystemExit(75)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv != ['--seal-blocked-root-custody']:
        print(json.dumps({'phase': 'ROOT_CUSTODY_REFUSED',
                          'successor_execution_authorised': False}))
        return 75
    try:
        print(json.dumps(module.seal_root_custody(), sort_keys=True))
    except (module.CutoverRefused,
            module.commissioning.BlockedCommissioningRefused,
            module.intake.CustodyIntakeRefused, OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'phase': 'ROOT_CUSTODY_REFUSED',
                          'successor_execution_authorised': False}, sort_keys=True))
    return 75


if __name__ == '__main__':
    raise SystemExit(main())
