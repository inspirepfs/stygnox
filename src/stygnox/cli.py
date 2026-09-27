"""Installed Stygnox command surface.

The installed command exposes the neutral TUI and presentation-neutral operator
surfaces through the shared Stygnox authority model. The retired Web UI and
legacy source-tree Web/controller modules are not installed command surfaces.
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
            "installed controller, bounded planning, scheduler/recovery, human gates, carry-forward reconciliation, scoped self-development authority, controller-owned qualification, controlled Git finalization/reconciliation, usage accounting, operator, and terminal TUI surfaces."
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
    if namespace.command == "usage":
        from .usage import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"provider-usage", "quota"}:
        from .provider_usage import cli_main
        return cli_main(namespace.args)
    if namespace.command == "scheduler":
        from .scheduler import cli_main
        return cli_main(namespace.args)
    if namespace.command == "plan":
        from .planning import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"retirement", "retire-plan"}:
        from .retirement import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"gate", "human"}:
        from .human_control import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"reconcile", "carry-forward"}:
        from .reconciliation import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"self-development", "self-hosting"}:
        from .self_development import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"qualification", "qualify", "requalify", "report"}:
        from .qualification import cli_main
        args = list(namespace.args)
        if namespace.command == "requalify":
            args = ["requalify", *args]
        elif namespace.command == "report":
            args = ["report", *args]
        return cli_main(args)
    if namespace.command in {"finalization", "finalize", "reconcile-commit", "reconcile-push"}:
        from .finalization import cli_main
        args = list(namespace.args)
        if namespace.command == "reconcile-commit":
            args = ["reconcile-commit", *args]
        elif namespace.command == "reconcile-push":
            args = ["reconcile-push", *args]
        return cli_main(args)
    if namespace.command == "operator":
        from .operator import cli_main
        return cli_main(namespace.args)
    if namespace.command in {"tui", "terminal"}:
        from .tui import cli_main
        return cli_main(namespace.args)
    parser.error(_UNKNOWN_COMMAND)
    return 2  # pragma: no cover
