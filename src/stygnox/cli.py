"""Installed Stygnox command surface.

D8.3 extends the installed product boundary with bounded transaction and
baseline-recovery semantics.  The installed package still has no dependency on
the legacy ``ralph`` controller modules or on a Stygnox source checkout.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .product import PRODUCT


_CONTROLLER_BOUNDARY = (
    "autonomous controller execution commands are not enabled by the D8.3 "
    "transaction/recovery surface; D8.3 proves authority binding, safe stop, "
    "and operator-approved restoration before controller neutralisation"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRODUCT.command,
        description=(
            "Stygnox installed product with D8.2 adoption and D8.3 transaction/recovery surfaces. "
            "Use 'stygnox adopt --help' or 'stygnox transaction --help'."
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
    if namespace.command in {"transaction", "recover"}:
        from .transactions import cli_main

        return cli_main(namespace.args)
    parser.error(_CONTROLLER_BOUNDARY)
    return 2  # pragma: no cover - argparse.error exits
