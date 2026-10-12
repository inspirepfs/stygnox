"""Release 02J: disposable kernel credential-isolation qualification.

This module deals ONLY with random disposable material. It cannot rotate,
read, inventory, import, or issue actual provider credentials. It cannot
approve a handoff, and does not protect a legacy token already known to the
predecessor UID. Future provider access must be routed through an independently
protected credential owner after separate external credential revocation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


class CredentialIsolationRefused(RuntimeError):
    """The disposable privilege boundary cannot be trusted or was bypassed."""


def _owner(path: Path, *, mode: int, directory: bool) -> None:
    st = path.lstat()
    if (st.st_uid != 0 or st.st_gid != 0 or stat.S_IMODE(st.st_mode) != mode
            or (directory and not stat.S_ISDIR(st.st_mode))
            or (not directory and (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1))):
        raise CredentialIsolationRefused('fixture ownership or file type mismatch')


def _predecessor(uid: int) -> tuple[int, int]:
    if os.name != 'posix' or os.getuid() != 0 or os.geteuid() != 0:
        raise CredentialIsolationRefused('root required for disposable credential boundary')
    if type(uid) is not int or uid <= 0 or uid == os.getuid():
        raise CredentialIsolationRefused('distinct non-root predecessor UID required')
    try:
        account = pwd.getpwuid(uid)
    except KeyError as exc:
        raise CredentialIsolationRefused('predecessor UID does not resolve') from exc
    return uid, account.pw_gid


def _legacy_access_attempt(paths: tuple[Path, Path], uid: int, gid: int) -> dict[str, Any]:
    """Run an actual unprivileged Python process; no mocks or secrets in argv/env."""
    child = r'''
import json, os, sys
out = {'uid': os.getuid()}
for name, path in zip(('direct', 'alias'), sys.argv[1:]):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except PermissionError:
        out[name] = 'DENIED'
    except OSError as exc:
        out[name] = 'UNVERIFIED_' + type(exc).__name__
    else:
        os.close(fd)
        out[name] = 'EXPOSED'
print(json.dumps(out, sort_keys=True))
'''
    def drop() -> None:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    try:
        run = subprocess.run(
            ['/usr/bin/python3', '-I', '-c', child, *(str(p) for p in paths)],
            capture_output=True, text=True, timeout=8, check=False,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/'},
            preexec_fn=drop,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialIsolationRefused('cannot qualify unprivileged subprocess') from exc
    if run.returncode != 0:
        raise CredentialIsolationRefused('unprivileged subprocess failed')
    try:
        result = json.loads(run.stdout)
    except ValueError as exc:
        raise CredentialIsolationRefused('invalid unprivileged process evidence') from exc
    if (result != {'uid': uid, 'direct': 'DENIED', 'alias': 'DENIED'}):
        raise CredentialIsolationRefused('predecessor UID accessed material or test is inconclusive')
    return result


def qualify_disposable_credential_boundary(predecessor_uid: int) -> dict[str, Any]:
    """Probe real DAC against ONLY a self-created random fixture under /run.

    No actual credential is accepted, read or written. Even a successful test
    is not evidence of revoked legacy OAuth sessions, keys, or API access.
    """
    uid, gid = _predecessor(predecessor_uid)
    run_root = Path('/run')
    run_info = run_root.lstat()
    if (not stat.S_ISDIR(run_info.st_mode) or run_info.st_uid != 0
            or stat.S_IMODE(run_info.st_mode) & 0o022):
        raise CredentialIsolationRefused('untrusted /run fixture parent')
    root = Path(tempfile.mkdtemp(prefix='stygnox-rr02j-', dir='/run'))
    removed = False
    result: dict[str, Any]
    try:
        os.chmod(root, 0o755)  # Public alias readable; secret directory stays private.
        _owner(root, mode=0o755, directory=True)
        vault = root / 'root-only'
        vault.mkdir(mode=0o700)
        _owner(vault, mode=0o700, directory=True)
        credential = vault / 'disposable-sentinel'
        secret = secrets.token_bytes(32)  # Never a real provider key.
        fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if os.write(fd, secret) != len(secret):
                raise CredentialIsolationRefused('disposable credential write incomplete')
            os.fsync(fd)
        finally:
            os.close(fd)
        _owner(credential, mode=0o600, directory=False)
        alias = root / 'public-alias'
        alias.symlink_to(credential)
        with credential.open('rb') as source:
            if source.read() != secret:
                raise CredentialIsolationRefused('root credential fixture not readable')
        actual = _legacy_access_attempt((credential, alias), uid, gid)
        result = {
            'schema': 'stygnox_release02j_disposable_credential_boundary_v1',
            'fixture_type': 'random_inert_root_only_credential',
            'predecessor_uid': uid,
            'root_can_open_disposable_credential': True,
            'predecessor_direct_open_denied': actual['direct'] == 'DENIED',
            'predecessor_alias_open_denied': actual['alias'] == 'DENIED',
            'external_provider_credential_revocation_proved': False,
            'old_oauth_sessions_invalidated': False,
            'actual_provider_secret_migrated': False,
            'all_legacy_provider_authority_excluded': False,
            'live_runtime_modified': False,
            'provider_executed': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
        }
    finally:
        # Only a freshly allocated /run/stygnox-rr02j-* fixture is removed.
        if root.parent == run_root and root.name.startswith('stygnox-rr02j-'):
            shutil.rmtree(root)
            removed = True
        if not removed:
            raise CredentialIsolationRefused('fixture cleanup not proved')
    result['disposable_fixture_removed'] = True
    return result
