#!/usr/bin/env python3
"""First-class Stygnox entrypoint for the existing controller CLI."""
from __future__ import annotations


def main() -> int:
    """Delegate without changing the controller's argument or state handling."""
    import ralph

    return int(ralph.main())


if __name__ == "__main__":
    raise SystemExit(main())
