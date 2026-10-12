#!/usr/bin/env python3
"""Root system-service disposable credential isolation qualification (02J).

Never handles actual provider credentials or launches a provider. On failure
always exits nonzero, without an authorization or successor-release mode.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = 'stygnox_release02j_disposable_credential_boundary_v1'
_UNIT = re.compile(r'\d+:[^:]*:/system\.slice/stygnox-recovery-release02j-[A-Za-z0-9_.-]+\.service')
_STAGE = Path(__file__).absolute().parent


class CredentialBoundaryProbeRefused(RuntimeError):
    pass


def _trusted_stage() -> None:
    if os.getuid() != 0 or os.geteuid() != 0 or os.name != 'posix':
        raise CredentialBoundaryProbeRefused('independent root system service required')
    cgroups = Path('/proc/self/cgroup').read_text(encoding='ascii').splitlines()
    if not any(_UNIT.fullmatch(line) for line in cgroups):
        raise CredentialBoundaryProbeRefused('dedicated 02J root service required')
    for ancestor in (*reversed(_STAGE.parents), _STAGE, _STAGE / 'stygnox'):
        st = ancestor.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or
                stat.S_IMODE(st.st_mode) & 0o022):
            raise CredentialBoundaryProbeRefused('untrusted source directory')
    if stat.S_IMODE(_STAGE.stat().st_mode) & 0o077:
        raise CredentialBoundaryProbeRefused('root-private source stage required')
    for member in (
        Path(__file__), _STAGE / 'stygnox' / '__init__.py',
        _STAGE / 'stygnox' / '_version.py',
        _STAGE / 'stygnox' / 'direct_interruption_credential_isolation.py',
    ):
        st = member.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
                or st.st_nlink != 1 or st.st_mode & 0o022):
            raise CredentialBoundaryProbeRefused('untrusted installed code')


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        _trusted_stage()
        sys.path.insert(0, str(_STAGE))
        from stygnox.direct_interruption_credential_isolation import (
            qualify_disposable_credential_boundary,
        )
        result = qualify_disposable_credential_boundary(args.predecessor_uid)
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException as exc:
        print(json.dumps({
            'schema': SCHEMA, 'inspection_failed': True,
            'reason': type(exc).__name__, 'authority_changed': False,
            'provider_executed': False, 'successor_execution_authorised': False,
            'handoff_admissible': False,
        }, sort_keys=True))
        return 1


if __name__ == '__main__':
    sys.exit(main())
