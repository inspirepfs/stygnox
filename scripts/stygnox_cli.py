#!/usr/bin/env python3
"""First-class Stygnox entrypoint for the existing controller CLI."""
from __future__ import annotations

import sys
from pathlib import Path


_EXTERNAL_PROJECT_COMMANDS = frozenset({
    "init", "propose", "approve", "reject", "retire-plan",
    "inspect-carry-forward", "adopt-carry-forward", "leave-carry-forward-outside",
    "reject-carry-forward", "run", "efficiency-policy", "model-policy", "models",
    "redeem-reset", "usage-reset-stats", "steer", "authorize-self-hosting", "resume",
    "resolve-gate", "recover-interrupted-run", "recover-self-upgrade",
    "recover-validation-block", "checkpoints", "checkpoint-info", "report", "requalify",
    "finalize", "reconcile-commit", "reconcile-push", "adopt-test-reconciliation",
    "usage", "operator-snapshot", "status",
})
_SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _establish_pycache_prefix(root: Path) -> None:
    sys.pycache_prefix = str((root / ".ralph" / "pycache").resolve())


def _remove_project_root(argv: list[str]) -> tuple[str | None, list[str]]:
    """Remove the wrapper-only explicit-root option without parsing controller args."""
    locations = [index for index, value in enumerate(argv) if value == "--project-root"]
    if not locations:
        return None, list(argv)
    if len(locations) != 1:
        raise SystemExit("stygnox: --project-root may be supplied only once")
    location = locations[0]
    if location + 1 == len(argv):
        raise SystemExit("stygnox: --project-root requires PATH")
    return argv[location + 1], argv[:location] + argv[location + 2:]


def _external_command(argv: list[str]) -> str:
    """Return the controller command after wrapper options have been removed."""
    if not argv or argv[0].startswith("-"):
        raise SystemExit("stygnox: --project-root requires an allowlisted controller command")
    return argv[0]


def _print_wrapper_help() -> None:
    print("Stygnox wrapper option: --project-root PATH (explicit external Git worktree; Web is refused).")


def main() -> int:
    """Delegate, admitting an external project only through explicit binding."""
    project_root, controller_argv = _remove_project_root(sys.argv[1:])
    if project_root is None:
        _establish_pycache_prefix(_SOURCE_ROOT)
        import ralph
        if sys.argv[1:] in (["--help"], ["-h"]):
            _print_wrapper_help()
        return int(ralph.main())

    command = _external_command(controller_argv)
    if command == "serve":
        raise SystemExit("stygnox: --project-root explicitly refuses serve/Web")
    if command not in _EXTERNAL_PROJECT_COMMANDS:
        raise SystemExit(f"stygnox: --project-root refuses non-allowlisted command {command!r}")

    original_dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        from stygnox_project_root import ProjectRootError, resolve_project_root
    finally:
        sys.dont_write_bytecode = original_dont_write_bytecode

    try:
        resolved_root: Path = resolve_project_root(project_root)
    except ProjectRootError as error:
        raise SystemExit(f"stygnox: --project-root refused: {error}") from error
    _establish_pycache_prefix(resolved_root)
    import ralph
    ralph.bind_controller_root(resolved_root)
    sys.argv[:] = [sys.argv[0], *controller_argv]
    return int(ralph.main())


if __name__ == "__main__":
    raise SystemExit(main())
