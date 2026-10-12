"""Release 02L: credentialless, non-authorising provider-identity qualification.

Checks the *current* Linux service sandbox; never launches a provider or
accesses any provider credential. A green report cannot revoke the legacy
controller's existing OAuth session or approve a recovery handoff.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import pwd
import socket
import tempfile
from typing import Any, Mapping

SCHEMA = 'stygnox_release02l_disposable_provider_identity_v1'
_CREDENTIAL_NAMES = frozenset({
    'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_HOME', 'OPENAI_BASE_URL',
    'OPENAI_ORG_ID', 'OPENAI_ORGANIZATION', 'OPENAI_PROJECT',
    'AZURE_OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY',
    'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS', 'XDG_CONFIG_HOME',
})
_DENIED = frozenset({errno.EACCES, errno.EPERM})


class ProviderIdentityRefused(RuntimeError):
    """Sandbox or identity cannot be proven; never implies authority."""


def assert_no_provider_environment(env: Mapping[str, str]) -> None:
    """Inspect keys only. Never record, inspect or log environment values."""
    if any(name in env for name in _CREDENTIAL_NAMES):
        raise ProviderIdentityRefused('provider credential environment was inherited')


def _status_flags() -> tuple[int, int]:
    """Read current process metadata only, not another process environment."""
    try:
        lines = Path('/proc/self/status').read_text(encoding='ascii').splitlines()
        flags = {key: value.strip() for line in lines if ':' in line
                 for key, value in (line.split(':', 1),)}
        return int(flags['NoNewPrivs']), int(flags['CapEff'], 16)
    except (OSError, ValueError, KeyError) as exc:
        raise ProviderIdentityRefused('process privilege metadata unavailable') from exc


def _in_system_service() -> bool:
    try:
        lines = Path('/proc/self/cgroup').read_text(encoding='ascii').splitlines()
    except OSError as exc:
        raise ProviderIdentityRefused('service cgroup unavailable') from exc
    import re
    return any(re.fullmatch(
        r'\d+:[^:]*:/system\.slice/stygnox-recovery-release02l-[A-Za-z0-9_.-]+\.service',
        line,
    ) for line in lines)


def _must_deny_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno in _DENIED:
            return
        raise ProviderIdentityRefused('legacy home access was not conclusively denied') from exc
    else:
        os.close(fd)
        raise ProviderIdentityRefused('legacy home is accessible to provider identity')


def _must_deny_network_socket() -> None:
    """Only creates a local socket object; never connects to an endpoint."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EAFNOSUPPORT):
            return
        raise ProviderIdentityRefused('network socket denial not proved') from exc
    else:
        sock.close()
        raise ProviderIdentityRefused('network socket could be created')


def qualify_credentialless_identity(predecessor_uid: int) -> dict[str, Any]:
    """Prove the *disposable test process* is isolated, never release a provider.

    The actual provider remains disabled even when every property holds.
    Host-wide exclusion and external token revocation are not inferred.
    """
    uid, euid, gid = os.getuid(), os.geteuid(), os.getgid()
    if (os.name != 'posix' or type(predecessor_uid) is not int or
            predecessor_uid <= 0 or uid <= 0 or uid == predecessor_uid or
            euid != uid or not _in_system_service()):
        raise ProviderIdentityRefused('separate unprivileged system-service identity required')
    try:
        legacy = pwd.getpwuid(predecessor_uid)
    except KeyError as exc:
        raise ProviderIdentityRefused('predecessor account unavailable') from exc
    if legacy.pw_gid == gid or legacy.pw_gid in os.getgroups():
        raise ProviderIdentityRefused('shared predecessor group identity')
    assert_no_provider_environment(os.environ)
    # HOME is never returned, but must not point to the actual predecessor home.
    if os.environ.get('HOME') == legacy.pw_dir:
        raise ProviderIdentityRefused('legacy HOME inherited')
    no_new_privileges, capabilities = _status_flags()
    if no_new_privileges != 1 or capabilities != 0:
        raise ProviderIdentityRefused('nonprivileged service protections missing')
    if not Path(legacy.pw_dir).is_absolute() or legacy.pw_dir in ('/', '/run', '/tmp'):
        raise ProviderIdentityRefused('legacy home location not qualified')
    _must_deny_directory(Path(legacy.pw_dir))
    # Alias is created under the PRIVATE /tmp from systemd's PrivateTmp=yes.
    # A symlink must never bypass the inaccessible-home mount protection.
    with tempfile.TemporaryDirectory(prefix='stygnox-rr02l-', dir='/tmp') as name:
        alias = Path(name) / 'legacy-home-alias'
        alias.symlink_to(legacy.pw_dir, target_is_directory=True)
        _must_deny_directory(alias)
    _must_deny_network_socket()
    return {
        'schema': SCHEMA,
        'scope': 'DISPOSABLE_TRANSIENT_SYSTEMD_IDENTITY_ONLY',
        'identity_uid_distinct_from_legacy': True,
        'identity_group_distinct_from_legacy': True,
        'provider_credential_environment_absent': True,
        'no_new_privileges': True,
        'effective_capabilities_zero': True,
        'legacy_home_direct_access_denied': True,
        'legacy_home_alias_access_denied': True,
        'ipv4_socket_creation_denied': True,
        'actual_provider_executable_invoked': False,
        'external_provider_contacted': False,
        'actual_provider_credentials_read': False,
        'existing_legacy_authentication_revoked': False,
        'host_wide_predecessor_excluded': False,
        'real_successor_identity_commissioned': False,
        'live_runtime_modified': False,
        'authority_changed': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'provider_executed': False,
    }
