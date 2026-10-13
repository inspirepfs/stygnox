#!/usr/bin/env python3
"""Unprivileged successor service smoke test ONLY; never a provider/controller.

This must not become the normal Stygnox execution entrypoint. A successful
systemd invocation witnesses process isolation only, not transaction admission.
"""
from __future__ import annotations

import json
import os
import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    uid = os.geteuid() if os.name == 'posix' else -1
    independent = uid > 0 and uid != 1000 and os.getuid() == uid
    # No privileged operation; no provider imports, sockets, home access or
    # provider environment reads. Purposefully no positive execution branch.
    phase = ('ISOLATED_IDENTITY_PROBE_EXECUTION_DENIED' if
             argv == ['--probe-denied-only'] and independent else
             'ISOLATED_IDENTITY_PROBE_REFUSED')
    print(json.dumps({'schema': 'stygnox_r3d2_denied_service_probe_v1',
                      'phase': phase, 'effective_uid': uid,
                      'independent_nonlegacy_uid_observed': independent,
                      'root_custody_access_attempted': False,
                      'legacy_provider_credentials_read': False,
                      'controller_admitted': False,
                      'successor_execution_authorised': False,
                      'provider_executed': False}, sort_keys=True))
    return 75


if __name__ == '__main__':
    raise SystemExit(main())
