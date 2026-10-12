"""Release 02M: non-authorising pre-execution barrier for the recovery successor.

This gate consumes *historical, user-readable* 02I/J/K/L evidence for an
operator-facing denial report. Neither report contents nor their digests
confer authority: the original predecessor still may own live Codex sessions.

There is deliberately no code path that invokes, imports or selects a provider,
returns an approval, or grants the interrupted transaction execution authority.
This is a pre-launch barrier candidate, NOT a replacement for server-side
revocation or enforcement by a protected supervisor.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

SCHEMA = 'stygnox_release02m_provider_preexecution_barrier_v1'
DENIED_EXIT = 75
_MAX_REPORT = 16 * 1024

# Exact local host qualification evidence from the prior bounded releases.
# These files are not signed authority attestations and remain user writable.
REPORTS = {
    '02i': (
        'recovery-release-02i-startup-interlock.json',
        'b87df80fee1a5d43e5c56f4119e2a7479432014ce105288f780f351fa84a1139',
        'stygnox_release02i_boot_startup_interlock_v1',
    ),
    '02j': (
        'recovery-release-02j-credential-boundary.json',
        'd90d593e1c0ad313cab90693b690313bd1090f033f04a8cfbd1fc295970af9e5',
        'stygnox_release02j_disposable_credential_boundary_v1',
    ),
    '02k': (
        'recovery-release-02k-provider-authority.json',
        '3ee693a326e4a00e271a852aa07265a779960258fc52ac7a5c6d27d1459d3082',
        'stygnox_release02k_provider_authority_inventory_v1',
    ),
    '02l': (
        'recovery-release-02l-provider-identity.json',
        'ec5d1ea10855c4da7a2644c850e7997413f50e240ced5bff245eb33e9d8da59f',
        'stygnox_release02l_disposable_provider_identity_v1',
    ),
}

_REQUIRED = {
    '02i': {
        'startup_admissible': False,
        'execution_authority': 'NONE',
        'host_wide_real_predecessor_excluded': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
    },
    '02j': {
        'root_can_open_disposable_credential': True,
        'predecessor_direct_open_denied': True,
        'predecessor_alias_open_denied': True,
        'disposable_fixture_removed': True,
        'all_legacy_provider_authority_excluded': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
    },
    '02k': {
        'scope': 'CURRENT_UID_ONLY_NOT_HISTORICAL_PREDECESSOR',
        'adapter_subprocess_environment_inherited_by_default': True,
        'credential_material_read': False,
        'all_legacy_provider_authority_excluded': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
    },
    '02l': {
        'scope': 'DISPOSABLE_TRANSIENT_SYSTEMD_IDENTITY_ONLY',
        'identity_uid_distinct_from_legacy': True,
        'legacy_home_direct_access_denied': True,
        'legacy_home_alias_access_denied': True,
        'ipv4_socket_creation_denied': True,
        'existing_legacy_authentication_revoked': False,
        'real_successor_identity_commissioned': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
    },
}


class ProviderPreflightRefused(RuntimeError):
    """The prior reports are unavailable, untrusted or semantically invalid."""


def _read_report(directory: Path, filename: str, digest: str) -> dict[str, Any]:
    """Read only fixed report names with no symlinks; never read credential files."""
    if os.name != 'posix' or not directory.is_absolute() or '..' in directory.parts:
        raise ProviderPreflightRefused('report directory not qualified')
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ProviderPreflightRefused('report directory is not a directory')
    # Qualifying a user-writable directory does NOT establish trusted authority.
    base = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=base)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > _MAX_REPORT:
                raise ProviderPreflightRefused('unqualified report member')
            raw = os.read(fd, _MAX_REPORT + 1)
            if len(raw) > _MAX_REPORT or hashlib.sha256(raw).hexdigest() != digest:
                raise ProviderPreflightRefused('historical evidence digest mismatch')
        finally:
            os.close(fd)
    finally:
        os.close(base)
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ProviderPreflightRefused('report JSON invalid') from exc
    if not isinstance(result, dict):
        raise ProviderPreflightRefused('report must be an object')
    return result


def check_evidence(directory: Path) -> tuple[bool, list[str]]:
    """Validate the historical report tuple; never determine release authority."""
    if os.name != 'posix' or os.getuid() == 0 or os.geteuid() != os.getuid():
        return False, ['NONROOT_READONLY_INSPECTION_REQUIRED']
    try:
        for release, (filename, digest, schema) in REPORTS.items():
            report = _read_report(directory, filename, digest)
            if report.get('schema') != schema:
                raise ProviderPreflightRefused('report schema mismatch')
            for name, value in _REQUIRED[release].items():
                actual = report.get(name)
                if type(actual) is not type(value) or actual != value:
                    raise ProviderPreflightRefused('report proof scope mismatch')
            for name in ('provider_executed', 'authority_changed'):
                if report.get(name) is not False:
                    raise ProviderPreflightRefused('report includes provider execution or authority change')
        return True, []
    except (OSError, ValueError, ProviderPreflightRefused):
        return False, ['HISTORICAL_REPORTS_INCOMPLETE_OR_UNTRUSTED']


def blocked_preflight(directory: Path) -> dict[str, Any]:
    """An explicitly non-authorising pre-execution decision; cannot become PASS."""
    complete, problems = check_evidence(directory)
    return {
        'schema': SCHEMA,
        'historical_reports_match_expected_sha256': complete,
        'historical_reports_are_release_credentials': False,
        'blocked_reasons': sorted(set(problems + [
            'LEGACY_PROVIDER_SESSION_NOT_REVOKED',
            'HOST_WIDE_PREDECESSOR_EXCLUSION_UNPROVED',
            'REBOOT_PERSISTENCE_UNPROVED',
            'REAL_SUCCESSOR_IDENTITY_NOT_COMMISSIONED',
            'TRANSACTION_BOUND_AUTHORITY_NOT_ISSUED',
            'NO_AUTHORISING_PROVIDER_DISPATCH_IMPLEMENTED',
        ])),
        'provider_executable_invoked': False,
        'provider_executed': False,
        'external_provider_contacted': False,
        'credential_material_read': False,
        'live_runtime_modified': False,
        'authority_changed': False,
        'execution_authority': 'NONE',
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'preexecution_admissible': False,
    }
