"""Shared exact-artifact selection for installed Stygnox qualification scripts.

D8.7 can set STYGNOX_QUALIFICATION_WHEEL to force every predecessor qualifier
to install the same immutable wheel. With the variable unset, each qualifier
retains its historical standalone behaviour and builds its own wheel.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

ENV_NAME = "STYGNOX_QUALIFICATION_WHEEL"


def provided_wheel() -> Path | None:
    value = os.environ.get(ENV_NAME, "").strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{ENV_NAME} must name an existing regular wheel file")
    if path.suffix != ".whl" or not path.name.startswith("stygnox-"):
        raise RuntimeError(f"{ENV_NAME} must name a Stygnox .whl artifact")
    return path


def provided_build_result(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["exact-release-wheel", str(path)],
        returncode=0,
        stdout=f"EXACT RELEASE WHEEL PROVIDED: {path}\n",
        stderr="",
    )
