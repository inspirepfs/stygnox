#!/usr/bin/env python3
"""Nonexecuting R3D.2 service identity; holds exact broker-attested PID alive.

No repository or provider imports, no execution entrypoint. Installing or
starting this service requires separate operator approval after disposable-host
qualification. It cannot authorise or resume the recovered transaction.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--denied-only', action='store_true', required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--transaction', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--epoch', required=True)
    parser.add_argument('--source-sha256', required=True)
    opts = parser.parse_args()
    if (os.name != 'posix' or os.geteuid() in (0, 1000) or
            not opts.socket.is_absolute() or '..' in opts.socket.parts or
            len(opts.plan_sha256) != 64 or len(opts.source_sha256) != 64 or
            len(opts.epoch) != 32):
        parser.error('denied worker needs dedicated unprivileged Linux identity')
    request = {'schema': 'stygnox_r3d2_denied_broker_v1',
               'operation': 'attest-denial',
               'transaction_id': opts.transaction,
               'approved_plan_hash': opts.plan_sha256,
               'runtime_epoch': opts.epoch,
               'installed_source_archive_sha256': opts.source_sha256}
    raw = (json.dumps(request, sort_keys=True, separators=(',', ':'))+'\n').encode()
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(opts.socket))
        client.sendall(raw)
        reply = client.recv(4097)
    try:
        value = json.loads(reply)
    except (ValueError, UnicodeError) as exc:
        raise SystemExit('broker attestation refused') from exc
    if (value.get('phase') != 'SUCCESSOR_IDENTITY_ATTESTED_EXECUTION_DENIED' or
            value.get('execution_authority') != 'NONE' or
            value.get('provider_executed') is not False or
            value.get('controller_admitted') is not False or
            value.get('successor_execution_authorised') is not False):
        raise SystemExit('broker did not confirm execution-denied identity')
    # Keep the exact attested kernel PID/start bound to one service lifetime.
    # Abrupt exit/crash/reboot does not permit silent readmission.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(75))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(75))
    print('SUCCESSOR_IDENTITY_ATTESTED_EXECUTION_DENIED', flush=True)
    while True:
        signal.pause()


if __name__ == '__main__':
    raise SystemExit(main())
