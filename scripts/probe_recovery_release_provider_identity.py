#!/usr/bin/env python3
"""02L systemd DynamicUser sandbox probe; no provider, no credentials, no release."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

SCHEMA = 'stygnox_release02l_disposable_provider_identity_v1'


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Reject malformed input without echoing supplied values to stderr.
        raise ValueError('invalid probe arguments')


_STAGE = Path(__file__).absolute().parent


def _root_owned_program() -> None:
    # The script executes as a DynamicUser; stage MUST be root-owned but world readable.
    if not Path('/proc/self/cgroup').exists() or os.geteuid() == 0:
        raise RuntimeError('isolated system service identity required')
    for directory in (*reversed(_STAGE.parents), _STAGE, _STAGE / 'stygnox'):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('untrusted executable directory')
    for path in (Path(__file__), _STAGE / 'stygnox' / '__init__.py',
                 _STAGE / 'stygnox' / '_version.py',
                 _STAGE / 'stygnox' / 'direct_interruption_provider_identity.py'):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                info.st_nlink != 1 or info.st_mode & 0o022):
            raise RuntimeError('untrusted Python source')


def main() -> int:
    parser = _QuietParser(add_help=False)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--predecessor-uid', type=int, required=True)
    try:
        args = parser.parse_args()
        _root_owned_program()
        sys.path.insert(0, str(_STAGE))
        from stygnox.direct_interruption_provider_identity import qualify_credentialless_identity
        result = qualify_credentialless_identity(args.predecessor_uid)
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException as exc:
        # Never print exception text: may contain caller-supplied values.
        print(json.dumps({
            'schema': SCHEMA, 'qualification_failed': True,
            'failure_class': type(exc).__name__,
            'provider_executed': False, 'authority_changed': False,
            'successor_execution_authorised': False, 'handoff_admissible': False,
        }, sort_keys=True))
        return 1


if __name__ == '__main__':
    sys.exit(main())
