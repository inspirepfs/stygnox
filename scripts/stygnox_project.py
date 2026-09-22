"""Configuration-driven contract for a project hosting Stygnox tooling."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


Guidance = tuple[tuple[str, tuple[str, ...]], ...]
NamedPaths = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class StygnoxProject:
    """Immutable project configuration and layout/policy helper collection.

    Hosts configure values rather than inheriting a product-specific profile.
    The contract intentionally describes repository concerns only; it neither
    selects a global project nor owns an execution environment.
    """

    identity: str = "Project"
    completion_commit_prefix: str = "chore(project):"
    runtime_dir_name: str = ".stygnox"
    controller_cli_relative_path: str = "scripts/controller.py"
    git_executable: str = "git"
    source_roots: tuple[str, ...] = ("src",)
    test_root: str = "tests"
    artifacts: NamedPaths = ()
    excluded_dirs: frozenset[str] = frozenset()
    protected_prefixes: tuple[str, ...] = ()
    protected_exact: frozenset[str] = frozenset()
    protected_dir_prefixes: tuple[str, ...] = ()
    protected_suffixes: tuple[str, ...] = ()
    tooling_paths: frozenset[str] = frozenset()
    optional_final_validators: NamedPaths = ()
    optional_step_validators: NamedPaths = ()
    execution_prompt_guardrails: tuple[str, ...] = ()
    nonrecoverable_validation_markers: tuple[str, ...] = ()
    production_action_keywords: tuple[str, ...] = ()
    policy_review_guidance: Guidance = ()
    gate_rule_definitions: Guidance = (
        ("validation_evidence", ("validation", "test", "evidence", "snapshot")),
        ("runtime_evidence", ("runtime", "diagnostic", "worker", "active durable")),
        ("credentials_or_access", ("credential", "login", "permission", "access token", "authentication")),
        ("security_approval", ("security approval", "security sign-off", "authority approval")),
        ("production_action", ("production", "live action")),
        ("scope_conflict", ("scope conflict", "overlap", "claimed work", "out of scope")),
        ("external_dependency", ("external dependency", "third-party", "upstream", "service unavailable")),
    )
    gate_guidance: tuple[tuple[str, Guidance], ...] = ()
    policy_storage_requires_runtime_argument: bool = False

    def repository_root(self, script_file: str | Path) -> Path:
        return Path(script_file).resolve().parents[1]

    def runtime_directory(self, root: Path) -> Path:
        return root / self.runtime_dir_name

    def runtime_relative_path(self, relative: str | Path | None = None) -> str:
        base = Path(self.runtime_dir_name).as_posix().strip("/")
        if not relative:
            return base
        suffix = Path(relative).as_posix().lstrip("/")
        return f"{base}/{suffix}" if suffix else base

    def is_runtime_path(self, path: str | Path) -> bool:
        value = Path(str(path)).as_posix()
        while value.startswith("./"):
            value = value[2:]
        base = self.runtime_relative_path()
        return value == base or value.startswith(base + "/")

    def artifact(self, root: Path, name: str) -> Path:
        return self.runtime_directory(root) / dict(self.artifacts)[name]

    def artifact_relative_path(self, name: str) -> str:
        return self.runtime_relative_path(dict(self.artifacts)[name])

    def runtime_config_path(self, root: Path, filename: str) -> Path:
        return self.runtime_directory(root) / filename

    def policy_storage_directory(self, root: Path) -> Path:
        return self.runtime_directory(root)

    def policy_storage_kwargs(self, root: Path) -> dict[str, Path]:
        if not self.policy_storage_requires_runtime_argument:
            return {}
        return {"runtime_directory": self.policy_storage_directory(root)}

    def recovery_manifest(self, root: Path, checkpoint_id: str) -> Path:
        return self.artifact(root, "recovery") / checkpoint_id / "manifest.json"

    def policy_reference(self) -> str:
        return self.artifact_relative_path("policy")

    def controller_cli(self, root: Path) -> Path:
        return root / self.controller_cli_relative_path

    def controller_display_command(self, root: Path) -> str:
        return f"python3 {self.relative_path(root, self.controller_cli(root))}"

    def git_worktree(self, root: Path) -> Path:
        return root

    def git_command(self, *args: str) -> list[str]:
        return [self.git_executable, *args]

    def relative_path(self, root: Path, path: Path) -> str:
        return str(path.relative_to(root))

    def source_directories(self, root: Path) -> tuple[Path, ...]:
        return tuple(root / relative_path for relative_path in self.source_roots if (root / relative_path).is_dir())

    def test_directory(self, root: Path) -> Path:
        return root / self.test_root

    def python_sources(self, root: Path) -> tuple[str, ...]:
        return tuple(
            sorted(
                str(path.relative_to(root))
                for base in self.source_directories(root)
                for path in base.glob("*.py")
            )
        )

    def project_metadata(self, root: Path) -> dict[str, str]:
        return {
            "identity": self.identity,
            "repository": root.name,
            "runtime_directory": self.relative_path(root, self.runtime_directory(root)),
        }

    def qualification_gates(self, root: Path, python_executable: str) -> list[tuple[str, list[str]]]:
        gates = [
            ("python-compile", [python_executable, "-m", "py_compile", *self.python_sources(root)]),
            ("unit-tests", [python_executable, "-m", "unittest", "discover", "-s", self.test_root, "-v"]),
        ]
        gates.extend(
            (name, [python_executable, relative_path])
            for name, relative_path in self.optional_step_validators
            if (root / relative_path).exists()
        )
        return gates

    def final_validator_gates(self, root: Path, python_executable: str) -> list[tuple[str, list[str]]]:
        return [
            (name, [python_executable, relative_path])
            for name, relative_path in self.optional_final_validators
            if (root / relative_path).exists()
        ]

    def prompt_guardrails(self) -> str:
        return " ".join(item.strip() for item in self.execution_prompt_guardrails if item.strip())

    def validation_block_is_nonrecoverable(self, text: str) -> bool:
        lower = str(text or "").lower()
        return any(marker.lower() in lower for marker in self.nonrecoverable_validation_markers)

    def gate_rules(self) -> Guidance:
        rules = list(self.gate_rule_definitions)
        for index, (name, _) in enumerate(rules):
            if name == "production_action":
                rules[index] = (name, tuple(self.production_action_keywords))
                break
        return tuple(rules)

    @staticmethod
    def guidance(values: Guidance) -> dict[str, list[str]]:
        return {key: list(items) for key, items in values}

    def guidance_for(self, gate_class: str) -> dict[str, list[str]]:
        return self.guidance(dict(self.gate_guidance).get(gate_class, ()))
