#!/usr/bin/env python3
"""02K local inspector; source metadata only, no login material or network IO."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from stygnox.direct_interruption_provider_inventory import (
    ProviderInventoryRefused, canonical_report, current_user_inventory,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only, redacted local Codex authority surface inventory')
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--provider-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        record = current_user_inventory(
            args.source_root / 'src/stygnox/provider_codex.py', args.provider_sha256,
        )
    except ProviderInventoryRefused:
        print('BLOCKED: provider inventory preconditions failed (no credential contents inspected)', file=sys.stderr)
        return 2
    print(canonical_report(record))
    # 02K is REPORTING ONLY, never an execution-authorising gate.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
