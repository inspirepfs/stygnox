#!/usr/bin/env python3
"""02M non-authorising pre-execution barrier: always exits 75, never runs Codex."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from stygnox.direct_interruption_provider_preflight import (
    DENIED_EXIT, SCHEMA, blocked_preflight,
)


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Caller input might contain a credential; never echo rejected arguments.
        raise ValueError('invalid arguments')


def main() -> int:
    try:
        parser = _QuietParser(add_help=False)
        parser.add_argument('--check', action='store_true', required=True)
        parser.add_argument('--evidence-directory', type=Path, required=True)
        options = parser.parse_args()
        report = blocked_preflight(options.evidence_directory)
    except BaseException:
        report = {
            'schema': SCHEMA,
            'blocked_reasons': ['PREEXECUTION_INSPECTION_FAILED'],
            'inspection_failed': True,
            'provider_executed': False,
            'external_provider_contacted': False,
            'live_runtime_modified': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'preexecution_admissible': False,
            'handoff_admissible': False,
            'execution_authority': 'NONE',
        }
    print(json.dumps(report, sort_keys=True))
    return DENIED_EXIT


if __name__ == '__main__':
    sys.exit(main())
