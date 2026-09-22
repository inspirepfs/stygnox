"""ZEN Control's configured adapter for the neutral Stygnox project contract.

This module preserves the current RALPH-Lite host configuration without making
the neutral contract aware of ZEN-specific operational or presentation policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.stygnox_project import Guidance, NamedPaths, StygnoxProject


@dataclass(frozen=True)
class ZenControlProfile(StygnoxProject):
    """Immutable ZEN Control configuration, retaining legacy profile members."""

    identity: str = "ZEN Control"
    completion_commit_prefix: str = "chore(zen):"
    runtime_dir_name: str = ".ralph"
    controller_cli_relative_path: str = "scripts/ralph.py"
    source_roots: tuple[str, ...] = ("app", "scripts")
    artifacts: NamedPaths = (
        ("state", "state.json"), ("plan", "plan.md"), ("ideas", "ideas.md"),
        ("journal", "journal.md"), ("policy", "policy.md"), ("live", "live.log"),
        ("context", "context.json"), ("events", "events.jsonl"),
        ("recovery", "recovery"), ("reports", "reports"),
        ("retirements", "retirements"),
        ("usage_ledger", "usage-ledger.jsonl"), ("usage_stats_reset", "usage-stats-reset.json"),
        ("web_job", "web-job.json"), ("web_log", "web-run.log"),
    )
    excluded_dirs: frozenset[str] = frozenset({
        ".git", ".ralph", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        ".venv", "venv", "node_modules", "data", "logs", "diagnostics", "backup", "backups",
    })
    protected_prefixes: tuple[str, ...] = ("secrets/", "certs/")
    protected_exact: frozenset[str] = frozenset({".npmrc", ".pypirc", ".netrc", ".envrc"})
    protected_dir_prefixes: tuple[str, ...] = (".codex/", ".direnv/")
    protected_suffixes: tuple[str, ...] = (".token", ".secret", ".secrets", ".credentials")
    tooling_paths: frozenset[str] = frozenset({
        ".gitignore", ".ralph/policy.md", "scripts/ralph.py", "scripts/ralph_efficiency.py",
        "scripts/ralph_model.py", "scripts/ralph_gate.py", "scripts/ralph_tui.py",
        "scripts/ralph_web.py", "scripts/ralph_profile.py", "tests/test_ralph_lite.py",
        "tests/test_ralph_efficiency.py", "tests/test_ralph_model.py", "tests/test_ralph_gate.py",
        "tests/test_ralph_lifecycle.py", "tests/test_ralph_retry_hardening.py",
        "tests/test_ralph_web.py", "tests/test_ralph_self_hosting.py",
        "tests/test_ralph_profile_boundary.py", "tests/test_ralph_web_gate_profile_boundary.py",
        "docs/RALPH-LITE.md",
    })
    optional_final_validators: NamedPaths = (
        ("environment", "scripts/env_validate.py"),
        ("supply-chain", "scripts/supply_chain_validate.py"),
        ("public-audit", "scripts/public_release_audit.py"),
    )
    optional_step_validators: NamedPaths = (("ux-validator", "scripts/ux_validate.py"),)
    execution_prompt_guardrails: tuple[str, ...] = (
        "Do not interact with live RouterOS, secrets, credentials, or external production systems.",
    )
    nonrecoverable_validation_markers: tuple[str, ...] = (
        "policy violation", "secret", "credential", "routeros", "human decision",
    )
    production_action_keywords: tuple[str, ...] = (
        "routeros", "production", "live write", "live action",
    )
    gate_rule_definitions: Guidance = (
        ("validation_evidence", ("performance", "sample", "acceptance evidence", "snapshot", "validation")),
        ("runtime_evidence", ("incident", "runtime", "diagnostic", "worker", "active durable")),
        ("credentials_or_access", ("credential", "login", "permission", "access token", "authentication")),
        ("security_approval", ("security approval", "security sign-off", "authority approval")),
        ("production_action", ("routeros", "production", "live write", "live action")),
        ("scope_conflict", ("scope conflict", "overlap", "claimed work", "out of scope")),
        ("external_dependency", ("external dependency", "third-party", "upstream", "service unavailable")),
    )
    policy_review_guidance: Guidance = (
        ("actions", (
            "Compare the requested path/action with the approved step and its test-change policy.",
            "Use steer for bounded human direction when the objective is still correct; use --allow-new-test only for an exact test path absent at plan approval.",
            "Retire/re-plan if the approved objective genuinely needs broader existing-file authority.",
        )),
        ("success", (
            "The requested change is demonstrably inside the approved step or is explicitly bounded by a human steering record.",
            "Existing protected/tooling paths and pre-existing tests remain unchanged unless the approved plan already permits them.",
        )),
        ("forbidden", (
            "Do not use steering to bypass protected paths, RALPH tooling authority, secrets or existing-test protection.",
            "Do not broaden the whole step merely to clear one blocked path.",
        )),
    )
    incident_reason_keyword: str = "incident"
    performance_reason_keyword: str = "performance"
    incident_runtime_summary: str = (
        "Incident Monitor state is runtime-owned. No verified source/configuration defect "
        "was found; operator action/evidence is required before this approved step can advance."
    )
    web_login_subtitle: str = "Private home-lab operator console"
    web_title: str = "RALPH-Lite"
    web_console_subtitle: str = "Operator console · CLI/TUI remains authoritative"
    incident_gate_guidance: Guidance = (
        ("actions", (
            "Review the currently active ZEN incidents and identify the underlying condition.",
            "Correct the underlying operational condition where appropriate; do not clear evidence merely for release acceptance.",
            "Run a fresh Incident Monitor scan after the underlying condition has cleared.",
            "Capture fresh operational diagnostics and verify the Incident Monitor is healthy with zero active incidents.",
        )),
        ("success", (
            "Incident Monitor diagnostic state is healthy.",
            "Active durable incident count is 0.",
            "Fresh evidence is produced by the normal monitor/diagnostic path.",
        )),
        ("forbidden", (
            "Do not disable Incident Monitor to obtain PASS.",
            "Do not edit/delete the incident database to obtain PASS.",
            "Do not manufacture or manually rewrite release evidence.",
        )),
    )
    performance_gate_guidance: Guidance = (
        ("actions", (
            "Exercise the real workload required by the existing performance contract.",
            "Capture a fresh operator-owned performance snapshot outside the repository.",
            "Validate it with python3 scripts/perf_acceptance.py ../zen-performance.json.",
        )),
        ("success", (
            "All configured request-class sample minima and latency budgets pass.",
            "Prepared-view effectiveness and mutation-lane evidence pass without threshold relaxation.",
        )),
        ("forbidden", (
            "Do not lower sample minima, latency budgets or acceptance thresholds.",
            "Do not inject synthetic PASS evidence.",
        )),
    )

    def policy_storage_kwargs(self, root: Path) -> dict[str, Path]:
        """Preserve ZEN's implicit ``.ralph`` behavior and portable replacements."""
        runtime_directory = self.policy_storage_directory(root)
        if self.runtime_dir_name == ".ralph" and runtime_directory == self.runtime_directory(root):
            return {}
        return {"runtime_directory": runtime_directory}


ZEN_PROFILE = ZenControlProfile()
PROJECT_PROFILE = ZEN_PROFILE
