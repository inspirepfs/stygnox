"""Installed Stygnox command surface.

D8.2 extends the neutral installed D8.1 product boundary with a bounded
bootstrap/admission surface.  The installed package still has no dependency on
the legacy ``ralph`` controller modules or on a Stygnox source checkout.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .product import PRODUCT


_CONTROLLER_BOUNDARY = (
    "installed controller execution commands are not enabled by the D8.2 "
    "bootstrap/admission surface; D8.2 grants only the reviewed tracked-policy "
    "and ignored-runtime bootstrap boundary"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRODUCT.command,
        description=(
            "Stygnox installed product and D8.2 bootstrap/admission surface. "
            "Use 'stygnox adopt --help' for the fail-closed handoff workflow."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PRODUCT.version}",
    )
    parser.add_argument("command", nargs="?", help="installed product command")
    parser.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    if namespace.command is None:
        parser.print_help()
        return 0
    if namespace.command in {"adopt", "bootstrap"}:
        from .adoption import cli_main

        return cli_main(namespace.args)
    parser.error(_CONTROLLER_BOUNDARY)
    return 2  # pragma: no cover - argparse.error exits
