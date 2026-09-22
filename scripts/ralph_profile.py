"""Compatibility facade for ZEN Control's accepted project adapter.

Legacy controller imports remain stable while the configured ZEN profile lives
in its host-specific adapter module.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ``scripts/ralph.py`` also imports this module as top-level ``ralph_profile``.
# Make the package adapter resolvable in that established direct-script mode.
_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

from scripts.stygnox_zen import PROJECT_PROFILE, ZEN_PROFILE, ZenControlProfile as ProjectProfile

__all__ = ("ProjectProfile", "ZEN_PROFILE", "PROJECT_PROFILE")
