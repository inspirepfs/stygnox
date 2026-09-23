"""Read-only resolution of an explicitly supplied Stygnox project root."""
from __future__ import annotations

from pathlib import Path
import subprocess


class ProjectRootError(ValueError):
    """An explicitly supplied project root cannot be used."""


def resolve_project_root(root: str | Path) -> Path:
    """Return *root*'s canonical Git worktree root without changing it.

    Relative paths are interpreted from the caller's current directory.  The
    supplied path must name the worktree top level exactly; accepting a nested
    directory would make the selected project ambiguous.
    """
    if not isinstance(root, (str, Path)):
        raise ProjectRootError("Project root must be a non-empty path string or Path.")

    supplied = str(root)
    if not supplied.strip():
        raise ProjectRootError("Project root must not be empty.")
    if "\x00" in supplied:
        raise ProjectRootError("Project root contains an invalid NUL character.")

    try:
        candidate = Path(supplied).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise ProjectRootError(f"Project root {supplied!r} is malformed: {error}") from error

    if not candidate.exists():
        raise ProjectRootError(f"Project root does not exist: {candidate}")
    if not candidate.is_dir():
        raise ProjectRootError(f"Project root must be a directory, not a file: {candidate}")

    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise ProjectRootError(f"Could not execute Git while checking {candidate}: {error}") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise ProjectRootError(
            f"Project root is not a usable Git worktree: {candidate} "
            f"(git rev-parse exited {result.returncode}: {detail})"
        )

    reported = result.stdout.strip()
    if not reported:
        raise ProjectRootError(f"Git returned no worktree top level for {candidate}.")
    try:
        git_root = Path(reported).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise ProjectRootError(f"Git returned a malformed worktree root {reported!r}: {error}") from error

    if candidate != git_root:
        raise ProjectRootError(
            f"Project root must be the Git worktree top level, not a nested directory: "
            f"{candidate} (Git reports {git_root})"
        )
    return candidate
