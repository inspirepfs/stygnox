"""Release 02K: read-only, redacted inspection of Codex credential *surfaces*.

NEVER opens login files, reads credential values, probes endpoints, executes
Codex, or grants authority. Inspection of the CURRENT user's environment is
not proof of a historical predecessor process's inherited credentials.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Mapping, Any

SCHEMA = 'stygnox_release02k_provider_authority_inventory_v1'
ENV_NAMES = (
    'CODEX_HOME', 'OPENAI_API_KEY', 'CODEX_API_KEY',
    'OPENAI_BASE_URL', 'OPENAI_ORG_ID', 'XDG_CONFIG_HOME',
)


class ProviderInventoryRefused(RuntimeError):
    """The scope, source integrity or inspection result cannot be trusted."""


def _source_call_shape(source: bytes) -> dict[str, Any]:
    """AST-only source inspection: NEVER import/execute the source being reviewed."""
    try:
        parsed = ast.parse(source.decode('utf-8'))
    except (UnicodeError, SyntaxError) as exc:
        raise ProviderInventoryRefused('provider adapter is not parseable') from exc
    functions = {node.name for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    calls = []
    for node in ast.walk(parsed):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        base = node.func.value
        if isinstance(base, ast.Name) and base.id == 'subprocess' and node.func.attr in ('Popen', 'run'):
            calls.append(node)
    if not calls or not {'execute', 'execute_structured', '_run'}.issubset(functions):
        raise ProviderInventoryRefused('unrecognised reviewed provider adapter')
    explicit_environment = any(any(k.arg in ('env', None) for k in call.keywords) for call in calls)
    # Lexical names here identify the REVIEWED adapter only, not how Codex itself authenticates.
    literals = {n.value for n in ast.walk(parsed) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    if not {'codex', 'app-server', 'exec'}.issubset(literals):
        raise ProviderInventoryRefused('reviewed provider launch markers missing')
    return {
        'reviewed_adapter_subprocess_call_count': len(calls),
        'adapter_explicit_subprocess_environment_override': explicit_environment,
        'adapter_subprocess_environment_inherited_by_default': not explicit_environment,
        'reviewed_launch_markers_present': True,
    }


def _metadata(path: Path, *, expected_uid: int) -> dict[str, Any]:
    """lstat only: NEVER follow a final symlink or read file contents."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'status': 'absent'}
    except PermissionError:
        return {'status': 'inaccessible'}
    except OSError:
        return {'status': 'inspection_error'}
    kind = ('symlink' if stat.S_ISLNK(info.st_mode) else
            'regular' if stat.S_ISREG(info.st_mode) else
            'directory' if stat.S_ISDIR(info.st_mode) else 'other')
    return {
        'status': 'present',
        'kind': kind,
        'owned_by_inspection_uid': info.st_uid == expected_uid,
        'group_or_other_permission_bits': bool(info.st_mode & 0o077),
    }


def collect_provider_authority_inventory(
    *, provider_source: Path, expected_provider_sha256: str,
    home: Path, environment: Mapping[str, str], inspection_uid: int,
    cli_on_path: bool,
) -> dict[str, Any]:
    """Produce an intentionally non-authorising inventory of the caller's scope.

    Source is byte-hash pinned; home candidates are inspected by *metadata*
    only; environment is checked by KEY, not value. This function never
    performs IO requiring an external service or writes anything.
    """
    if (type(inspection_uid) is not int or inspection_uid <= 0
            or not home.is_absolute() or not provider_source.is_file()):
        raise ProviderInventoryRefused('invalid non-root inventory scope')
    if (len(expected_provider_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in expected_provider_sha256)):
        raise ProviderInventoryRefused('invalid pinned adapter digest')
    try:
        source = provider_source.read_bytes()  # REVIEWED SOURCE ONLY, not a credential.
    except OSError as exc:
        raise ProviderInventoryRefused('provider adapter unavailable') from exc
    observed = hashlib.sha256(source).hexdigest()
    if observed != expected_provider_sha256:
        raise ProviderInventoryRefused('reviewed provider adapter digest mismatch')
    shape = _source_call_shape(source)
    codex_dir = home / '.codex'
    root_meta = _metadata(codex_dir, expected_uid=inspection_uid)
    if root_meta.get('status') == 'present' and root_meta.get('kind') == 'directory':
        login_meta = _metadata(codex_dir / 'auth.json', expected_uid=inspection_uid)
        config_meta = _metadata(codex_dir / 'config.toml', expected_uid=inspection_uid)
    else:
        # Never traverse a symlinked .codex parent; credential aliases remain unqualified.
        status = 'not_inspected_parent_untrusted' if root_meta.get('status') != 'absent' else 'absent'
        login_meta = {'status': status}
        config_meta = {'status': status}
    result: dict[str, Any] = {
        'schema': SCHEMA,
        'scope': 'CURRENT_UID_ONLY_NOT_HISTORICAL_PREDECESSOR',
        'reviewed_provider_adapter': 'codex',
        'reviewed_adapter_sha256': observed,
        **shape,
        'codex_executable_on_current_path': bool(cli_on_path),
        'candidate_environment_names_present': [name for name in ENV_NAMES if name in environment],
        'default_codex_directory_metadata': root_meta,
        'default_codex_auth_json_metadata': login_meta,
        'default_codex_config_toml_metadata': config_meta,
        'custom_codex_home_present_uninspected': 'CODEX_HOME' in environment,
        'legacy_process_environment_verified': False,
        'actual_provider_login_validity_verified': False,
        'old_oauth_sessions_invalidated': False,
        'external_provider_credential_revocation_proved': False,
        'all_legacy_provider_authority_excluded': False,
        'alternate_launch_paths_excluded': False,
        'provider_executed': False,
        'external_endpoints_contacted': False,
        'credential_material_read': False,
        'environment_values_emitted': False,
        'credential_content_hashes_computed': False,
        'live_runtime_modified': False,
        'authority_changed': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'inventory_complete': False,
        'required_followup': [
            'HISTORICAL_PROCESS_ENVIRONMENT_UNPROVED',
            'EXISTING_PROVIDER_LOGIN_VALIDITY_UNPROVED',
            'LEGACY_TOKEN_AND_OAUTH_REVOCATION_UNPROVED',
            'CODEX_CLI_INTERNAL_AUTH_SOURCES_UNQUALIFIED',
            'ALTERNATIVE_LAUNCH_PATHS_UNPROVED',
        ],
    }
    if shape['adapter_explicit_subprocess_environment_override']:
        result['required_followup'].append('ADAPTER_ENVIRONMENT_OVERRIDE_REVIEW_REQUIRED')
    if result['custom_codex_home_present_uninspected']:
        result['required_followup'].append('CUSTOM_CODEX_HOME_NOT_INSPECTED')
    return result


def current_user_inventory(provider_source: Path, expected_sha256: str) -> dict[str, Any]:
    uid = os.getuid()
    if os.name != 'posix' or uid == 0 or os.geteuid() != uid:
        raise ProviderInventoryRefused('ordinary non-root inspector required')
    # We deliberately neither log nor return HOME, PATH, CODEX_HOME or any other value.
    return collect_provider_authority_inventory(
        provider_source=provider_source,
        expected_provider_sha256=expected_sha256,
        home=Path.home(),
        environment=os.environ,
        inspection_uid=uid,
        cli_on_path=shutil.which('codex') is not None,
    )


def canonical_report(report: Mapping[str, Any]) -> str:
    return json.dumps(dict(report), sort_keys=True, separators=(',', ':'))
