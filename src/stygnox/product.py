"""Neutral installed-product identity."""

from __future__ import annotations

from dataclasses import dataclass

from ._version import __version__


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    name: str
    command: str
    version: str
    stage: str


PRODUCT = ProductIdentity(
    name="Stygnox",
    command="stygnox",
    version=__version__,
    stage="D8.5 neutral authority, profile, controller, and execution policy",
)
