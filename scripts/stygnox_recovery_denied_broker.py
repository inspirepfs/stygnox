#!/usr/bin/env python3
"""Never from a mutable checkout; protected, disabled-only internal broker."""
import argparse
import os
from pathlib import Path
import pwd
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description='Denied-only internal successor broker')
    parser.add_argument('--serve-denied-only', action='store_true', required=True)
    parser.add_argument('--installed-source', type=Path, required=True)
    parser.add_argument('--installed-archive', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--socket-path', type=Path, required=True)
    arguments = parser.parse_args()

    base = arguments.installed_source
    if (os.name != 'posix' or os.geteuid() != 0 or
            base.is_symlink() or
            Path(__file__).resolve() != base / 'scripts/stygnox_recovery_denied_broker.py' or
            not str(base).startswith('/usr/local/libexec/stygnox-recovery-successor-')):
        parser.error('requires a separately protected installed source; checkout refused')

    sys.path.insert(0, str(base / 'src'))
    from stygnox import direct_interruption_cutover_gate as gate
    from stygnox import direct_interruption_epoch_reservation as epoch
    from stygnox import direct_interruption_successor_broker as broker
    from stygnox import direct_interruption_custody_intake as intake
    from stygnox import direct_interruption_blocked_commissioning as commissioning
    from stygnox import direct_interruption_host_readiness as readiness
    from stygnox import direct_interruption_isolated_workspace as isolated
    from stygnox import direct_interruption_authority_cutover as authority

    verified = gate.installed_artifact_audit(archive=arguments.installed_archive,
                                             source=base,
                                             expected_sha=arguments.source_sha256)
    commissioning._trusted_root(intake.ROOT)
    report = readiness.verify_published_slot(intake.ROOT, uid=0)
    staged = isolated.verify_isolated_workspace(intake.ROOT, uid=0)
    rec = epoch.read_reservation(intake.ROOT, owner=0)
    if (rec['root_custody_record_sha256'] != report['root_custody_record_sha256'] or
            rec['isolated_workspace_manifest_sha256'] != staged['manifest_record_sha256'] or
            rec['installed_source_archive_sha256'] != verified['source_archive_sha256'] or
            rec['installed_source_file_count'] != verified['installed_source_file_count']):
        parser.error('reserved epoch does not match verified installed source or custody')
    # No socket is published until the root authority registry has explicitly
    # withdrawn trust from historical files. Service restarts cannot invent it.
    chain = authority.read_chain(intake.ROOT, owner=0)
    if len(chain) not in (2, 3):
        parser.error('root-controlled legacy-untrusted transition not published')
    head = chain[-1]
    if (head['reservation_record_sha256'] != rec['record_sha256'] or
            head['root_custody_record_sha256'] != report['root_custody_record_sha256'] or
            head['isolated_workspace_manifest_sha256'] != staged['manifest_record_sha256'] or
            head['installed_source_archive_sha256'] != verified['source_archive_sha256']):
        parser.error('authority chain differs from immutable protected evidence')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    context = broker.DeniedContext.from_reservation(rec,
        pinned_source_sha256=verified['source_archive_sha256'], boot_id=boot)
    from dataclasses import replace
    context = replace(context, authority_root=intake.ROOT, authority_owner=0,
                      worker_script=base / 'scripts/stygnox_recovery_denied_worker.py',
                      worker_unit='stygnox-recovery-denied-worker.service')
    try:
        worker = pwd.getpwuid(context.successor_uid)
    except KeyError:
        parser.error('reserved successor UID is not a provisioned local user')
    if worker.pw_gid in (0, 1000):
        parser.error('successor must have a dedicated non-root group')
    server = broker.bind_private_socket(arguments.socket_path,
                                         successor_gid=worker.pw_gid)
    try:
        broker.serve_denied_forever(server, context)
    finally:
        # Do NOT unlink the socket: a restart must refuse until reconciled.
        server.close()
    return 75


if __name__ == '__main__':
    raise SystemExit(main())
