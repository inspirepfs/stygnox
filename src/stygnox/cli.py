"""Installed Stygnox command surface.

D8.6A adds the neutral installed Web operator surface and shared presentation-
neutral operator/reconciliation model. Legacy source-tree Web/controller
modules are compatibility/development surfaces only and are never imported by
the installed command.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from .product import PRODUCT


_UNKNOWN_COMMAND = (
    "unknown installed Stygnox command; legacy/source-tree controller fallbacks "
    "are not permitted by the installed product boundary"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PRODUCT.command,
        description=(
            "Stygnox installed product with adoption, recovery, lifecycle, neutral execution-policy, "
            "installed controller, Web, operator, and terminal TUI surfaces."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PRODUCT.version}")
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
    if namespace.command == "profile":
        from .profile import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"execution-policy", "policy"}:
        from .execution_policy import cli_main
        return cli_main(namespace.args)
    if namespace.command == "controller":
        from .controller import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"web", "serve"}:
        from .web import cli_main
        return cli_main(namespace.args)
    if namespace.command == "operator":
        from .operator import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"tui", "terminal"}:
        from .tui import cli_main
        return cli_main(namespace.args)
    parser.error(_UNKNOWN_COMMAND)
    return 2  # pragma: no cover
