#!/usr/bin/env python3
"""First-class Stygnox entrypoint for the existing local web console."""
from __future__ import annotations

import sys


def main() -> int:
    """Delegate all web-console options to the compatibility implementation."""
    import ralph_web

    return int(ralph_web.main(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
