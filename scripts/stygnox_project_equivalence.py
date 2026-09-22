"""Deterministic, dependency-free ZEN profile facade equivalence checks.

The observations deliberately use a synthetic repository.  This makes the
profile contract portable and avoids consulting either the working tree or a
Git executable.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

# Permit ``python3 scripts/stygnox_project_equivalence.py`` without requiring
# callers to supply a package-oriented PYTHONPATH.
_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

from scripts import ralph_profile
from scripts import stygnox_zen


SCHEMA = "stygnox_project_equivalence_v1"
BASELINE_METADATA = "4f5fb11"
MAX_DIFFERENCES = 24
MAX_PATH_LENGTH = 160


def canonical(value: Any, *, root: Path | None = None) -> Any:
    """Return a recursively sorted value which ``json.dumps`` can encode."""
    if isinstance(value, Path):
        if root is not None:
            try:
                return value.relative_to(root).as_posix() or "."
            except ValueError:
                pass
        return value.as_posix()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: canonical(getattr(value, field.name), root=root) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): canonical(item, root=root) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [canonical(item, root=root) for item in value]
    if isinstance(value, (frozenset, set)):
        return sorted((canonical(item, root=root) for item in value), key=_canonical_key)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _canonical_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _path(parent: str, segment: str) -> str:
    candidate = f"{parent}.{segment}" if parent else segment
    return candidate if len(candidate) <= MAX_PATH_LENGTH else candidate[: MAX_PATH_LENGTH - 3] + "..."


def differences(left: Any, right: Any, *, limit: int = MAX_DIFFERENCES) -> list[dict[str, Any]]:
    """Compare canonical values, reporting bounded deterministic leaf paths."""
    found: list[dict[str, Any]] = []

    def visit(first: Any, second: Any, path: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(first, dict) and isinstance(second, dict):
            for key in sorted(set(first) | set(second)):
                marker = _path(path, str(key))
                if key not in first or key not in second:
                    found.append({"path": marker, "facade": first.get(key), "adapter": second.get(key)})
                else:
                    visit(first[key], second[key], marker)
                if len(found) >= limit:
                    return
            return
        if isinstance(first, list) and isinstance(second, list):
            for index in range(max(len(first), len(second))):
                marker = _path(path, str(index))
                if index >= len(first) or index >= len(second):
                    found.append({"path": marker, "facade": first[index] if index < len(first) else None, "adapter": second[index] if index < len(second) else None})
                else:
                    visit(first[index], second[index], marker)
                if len(found) >= limit:
                    return
            return
        if first != second:
            found.append({"path": path or "$", "facade": first, "adapter": second})

    visit(canonical(left), canonical(right), "")
    return found


def _synthetic_repository(root: Path) -> None:
    for relative, text in {
        "app/main.py": "value = 1\n",
        "scripts/helper.py": "value = 2\n",
        "scripts/ux_validate.py": "pass\n",
        "scripts/env_validate.py": "pass\n",
        "scripts/supply_chain_validate.py": "pass\n",
        "scripts/public_release_audit.py": "pass\n",
        "tests/test_profile.py": "pass\n",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def observe(profile: Any, root: Path) -> dict[str, Any]:
    """Observe all profile behavior required at the facade boundary."""
    changed = replace(profile, runtime_dir_name=".replacement")
    data = {
        "class": {"name": type(profile).__name__, "module": type(profile).__module__},
        "frozen_dataclass": {
            "frozen": getattr(type(profile).__dataclass_params__, "frozen", False),
            "fields": {field.name: getattr(profile, field.name) for field in fields(profile)},
            "replace": {
                "original_runtime": profile.runtime_dir_name,
                "replacement_runtime": changed.runtime_dir_name,
                "preserves_class": type(changed) is type(profile),
            },
        },
        "runtime_artifacts_recovery_policy": {
            "runtime_directory": profile.runtime_directory(root),
            "runtime_relative": profile.runtime_relative_path("nested/item.json"),
            "runtime_path": profile.is_runtime_path("./.ralph/state.json"),
            "state": profile.artifact(root, "state"),
            "policy": profile.policy_reference(),
            "recovery": profile.recovery_manifest(root, "checkpoint-1"),
            "storage": profile.policy_storage_kwargs(root),
        },
        "source_test_discovery": {
            "sources": profile.python_sources(root),
            "test_directory": profile.test_directory(root),
            "excluded": profile.excluded_dirs,
        },
        "protection_tooling_policy": {
            "prefixes": profile.protected_prefixes,
            "exact": profile.protected_exact,
            "directory_prefixes": profile.protected_dir_prefixes,
            "suffixes": profile.protected_suffixes,
            "tooling": profile.tooling_paths,
        },
        "validator_gates": {
            "qualification": profile.qualification_gates(root, "python3"),
            "final": profile.final_validator_gates(root, "python3"),
            "nonrecoverable": profile.validation_block_is_nonrecoverable("credential policy violation"),
        },
        "git_controller_metadata": {
            "worktree": profile.git_worktree(root),
            "command": profile.git_command("status", "--short"),
            "controller": profile.controller_cli(root),
            "display": profile.controller_display_command(root),
        },
        "rendered_metadata": profile.project_metadata(root),
        "prompt_gate_guidance": {
            "prompt": profile.prompt_guardrails(),
            "rules": profile.gate_rules(),
            "policy_review": profile.policy_review_guidance,
            "incident": profile.incident_gate_guidance,
            "performance": profile.performance_gate_guidance,
        },
        "incident_performance_compatibility": {
            "incident_keyword": profile.incident_reason_keyword,
            "performance_keyword": profile.performance_reason_keyword,
            "incident_summary": profile.incident_runtime_summary,
        },
        "web_presentation": {
            "login_subtitle": profile.web_login_subtitle,
            "title": profile.web_title,
            "console_subtitle": profile.web_console_subtitle,
        },
    }
    return canonical(data, root=root)


def report() -> dict[str, Any]:
    """Return the canonical facade/direct-adapter comparison report."""
    with TemporaryDirectory(prefix="stygnox-profile-") as temporary:
        root = Path(temporary)
        _synthetic_repository(root)
        facade = observe(ralph_profile.ZEN_PROFILE, root)
        adapter = observe(stygnox_zen.ZEN_PROFILE, root)
    aliases = {
        "class": ralph_profile.ProjectProfile is stygnox_zen.ZenControlProfile,
        "zen_singleton": ralph_profile.ZEN_PROFILE is stygnox_zen.ZEN_PROFILE,
        "project_singleton": ralph_profile.PROJECT_PROFILE is stygnox_zen.PROJECT_PROFILE,
    }
    return canonical({
        "schema": SCHEMA,
        "baseline_metadata": BASELINE_METADATA,
        "aliases": aliases,
        "facade": facade,
        "adapter": adapter,
        "differences": differences(facade, adapter),
    })


def main() -> int:
    print(json.dumps(report(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
