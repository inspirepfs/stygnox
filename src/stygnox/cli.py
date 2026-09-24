"""Installed Stygnox command surface.

D8.4 extends the installed product boundary with reversible legacy migration,
explicit upgrade compatibility, and non-destructive uninstall preparation.
The installed package still has no dependency on legacy ``ralph`` controller
modules or on a Stygnox source checkout.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .product import PRODUCT


_CONTROLLER_BOUNDARY = (
    "autonomous controller execution commands are not enabled by the D8.4 "
    "migration/lifecycle surface; D8.4 proves extraction, compatibility, "
    "uninstall safety, and rollback before controller neutralisation"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRODUCT.command,
        description=(
            "Stygnox installed product with adoption, transaction/recovery, migration, upgrade, and uninstall surfaces. "
            "Autonomous controller execution remains disabled pending D8.5."
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
    if namespace.command == "migrate":
        from .migration import cli_main

        return cli_main(namespace.args)
    if namespace.command == "upgrade":
        from .lifecycle import upgrade_cli_main

        return upgrade_cli_main(namespace.args)
    if namespace.command == "uninstall":
        from .lifecycle import uninstall_cli_main

        return uninstall_cli_main(namespace.args)
    if namespace.command == "support":
        from .lifecycle import support_cli_main

        return support_cli_main(namespace.args)
    parser.error(_CONTROLLER_BOUNDARY)
    return 2  # pragma: no cover - argparse.error exits
