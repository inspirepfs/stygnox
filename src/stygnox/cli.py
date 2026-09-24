"""Installed Stygnox command surface for D8.1 product identity closure.

This module intentionally has no dependency on the legacy ``ralph`` controller
modules or on a source checkout.  Controller/adoption commands are introduced
by later D8 stages after their authority and runtime contracts are qualified.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .product import PRODUCT


_CONTROLLER_BOUNDARY = (
    "installed controller/adoption commands are not enabled by the D8.1 "
    "product-identity surface; use the tracked source compatibility entrypoint "
    "only for pre-D8.2 development workflows"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRODUCT.command,
        description=(
            "Stygnox installed product identity and command-resolution surface. "
            "D8.1 intentionally exposes product help/version only."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PRODUCT.version}",
    )
    parser.add_argument(
        "command",
        nargs="?",
        help="reserved for a later qualified installed-controller stage",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    if namespace.command is None:
        parser.print_help()
        return 0
    parser.error(_CONTROLLER_BOUNDARY)
    return 2  # pragma: no cover - argparse.error exits
