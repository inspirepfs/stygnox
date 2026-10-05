#!/usr/bin/env python3
"""Retired source-tree Stygnox wrapper.

The supported command is the independently installed ``stygnox`` console
script declared by the package. This compatibility filename deliberately does
not discover, import, or execute a controller: source trees and target
worktrees are not installed command authority.
"""
from __future__ import annotations

from collections.abc import Sequence
import sys


_MIGRATION_INSTRUCTION = (
    "stygnox: the source-tree wrapper is retired and will not execute commands; "
    "install Stygnox independently and invoke its installed 'stygnox' command directly"
)
_WEB_REFUSAL = "stygnox: retired wrapper refuses serve/Web; " + _MIGRATION_INSTRUCTION


def main(argv: Sequence[str] | None = None) -> int:
    """Fail closed without selecting or transferring controller authority."""
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if any(argument in {"serve", "web", "web-auth"} for argument in arguments):
        raise SystemExit(_WEB_REFUSAL)
    raise SystemExit(_MIGRATION_INSTRUCTION)


if __name__ == "__main__":
    main()
