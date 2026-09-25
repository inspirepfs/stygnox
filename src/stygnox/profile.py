"""Neutral installed-product profile for Stygnox D8.5.

The installed product owns this profile.  Host/source-tree compatibility
profiles are deliberately not imported here and cannot become an installed
default by import side effect.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PROFILE_SCHEMA = "stygnox_profile_v1"


@dataclass(frozen=True, slots=True)
class InstalledProfile:
    schema: str = PROFILE_SCHEMA
    name: str = "stygnox-default"
    identity: str = "Stygnox"
    command: str = "stygnox"
    controller_command: str = "stygnox controller"
    runtime_directory: str = ".stygnox"
    tracked_config: str = "stygnox.toml"
    tracked_policy: str = "stygnox.policy.md"
    qualification_config: str = "stygnox.qualification.toml"
    artifact_namespace: str = "stygnox"
    completion_commit_prefix: str = "chore(stygnox):"
    host_adapter: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_PROFILE = InstalledProfile()


def profile_record() -> dict[str, Any]:
    """Return a fresh JSON/TOML-safe representation of the installed default."""
    return DEFAULT_PROFILE.public()


def cli_main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="stygnox profile",
        description="Show the neutral installed Stygnox profile selected by default.",
    )
    parser.add_argument("action", nargs="?", choices=["show"], default="show")
    parser.parse_args(list(argv) if argv is not None else None)
    print(json.dumps(profile_record(), indent=2, sort_keys=True))
    return 0
