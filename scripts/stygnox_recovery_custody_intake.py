#!/usr/bin/env python3
"""Root-only R3D.2 evidence intake; NEVER usable as a startup approval gate.

Install this and the matching source module in an independently reviewed,
root-owned directory. Do not execute this script via sudo from a user-writable
checkout. Its only modes are read-only audit or deny-only receipt publication.
Both return EX_TEMPFAIL (75), even on a successful evidence-only operation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

# Load EXACT protected sibling module even under python -I; do not import an
# arbitrary installed `stygnox` package or the old controller/provider graph.
MODULE = Path(__file__).absolute().parent.parent / 'src/stygnox/direct_interruption_custody_intake.py'
_spec = importlib.util.spec_from_file_location('stygnox_recovery_custody_intake', MODULE)
if _spec is None or _spec.loader is None:
    raise RuntimeError('protected custody source unavailable')
_custody = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_custody)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--audit', action='store_true', help='root-only read-only integrity reconciliation')
    modes.add_argument('--seal-blocked', action='store_true', help='root-only one-shot deny-only custody intake')
    options = parser.parse_args(argv)
    try:
        result = _custody.seal_blocked_intake() if options.seal_blocked else _custody.audit_protected_intake()
    except (_custody.CustodyIntakeRefused, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'phase': 'EVIDENCE_RECONCILIATION_REFUSED',
                          'execution_authority': 'NONE',
                          'successor_execution_authorised': False,
                          'reason_class': type(exc).__name__}, sort_keys=True))
        return 75
    print(json.dumps(result, sort_keys=True))
    return 75  # NEVER a successful service ExecStartPre/approval gate.


if __name__ == '__main__':
    sys.exit(main())
