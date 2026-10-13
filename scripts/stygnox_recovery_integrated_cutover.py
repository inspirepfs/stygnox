#!/usr/bin/env python3
"""R3D.2 root-only authority-registry operator gate; NEVER releases providers.

A preview and separately approved transition are bound to exact source, root
custody, isolated reconstruction, reserved epoch, boot and original inode.
This is NOT a provider-release or a physical old-workspace retirement tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def output(value: dict) -> None:
    print(json.dumps(value, sort_keys=True, separators=(',', ':')))


def main() -> int:
    parser = argparse.ArgumentParser(description='Root-only, denied R3D.2 authority-registry transition')
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument('--preview', action='store_true')
    commands.add_argument('--prepare-approved', action='store_true')
    commands.add_argument('--fence-approved', action='store_true')
    commands.add_argument('--status', action='store_true')
    parser.add_argument('--installed-source', type=Path, required=True)
    parser.add_argument('--installed-archive', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--approved-preview-hash', default=None)
    opts = parser.parse_args()
    base = opts.installed_source
    if (os.name != 'posix' or os.geteuid() != 0 or
            base.is_symlink() or
            Path(__file__).resolve() != base / 'scripts/stygnox_recovery_integrated_cutover.py' or
            not str(base).startswith('/usr/local/libexec/stygnox-recovery-successor-')):
        parser.error('privileged operations require exact protected installed source')
    sys.path.insert(0, str(base / 'src'))
    from stygnox import direct_interruption_authority_cutover as cut
    from stygnox import direct_interruption_epoch_reservation as epoch
    from stygnox import direct_interruption_custody_intake as intake
    from stygnox import direct_interruption_blocked_commissioning as commissioning
    from stygnox import direct_interruption_host_readiness as readiness
    from stygnox import direct_interruption_isolated_workspace as isolated
    from stygnox import direct_interruption_cutover_gate as gate
    try:
        verified = gate.installed_artifact_audit(
            archive=opts.installed_archive, source=base,
            expected_sha=opts.source_sha256)
        commissioning._trusted_root(intake.ROOT)
        published = readiness.verify_published_slot(intake.ROOT, uid=0)
        staged = isolated.verify_isolated_workspace(intake.ROOT, uid=0)
        reserved = epoch.read_reservation(intake.ROOT, owner=0)
        original = isolated.ORIGINAL.lstat()
        if not stat.S_ISDIR(original.st_mode) or original.st_uid != 1000:
            raise cut.AuthorityCutoverRefused('original identity missing or substituted')
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        item = cut.build_prepared(
            reservation=reserved,
            custody_sha256=published['root_custody_record_sha256'],
            isolated_manifest_sha256=staged['manifest_record_sha256'],
            installed_source_sha256=verified['source_archive_sha256'],
            project_identity=(original.st_dev, original.st_ino), boot_id=boot_id)
        if opts.preview:
            output({'phase': 'CUTOVER_PREVIEW_EXECUTION_DENIED',
                    'preview_record_sha256': item['record_sha256'],
                    'transaction_id': item['transaction_id'],
                    'runtime_epoch': item['reserved_epoch'],
                    'original_workspace_modified': False,
                    'provider_executed': False,
                    'legacy_controller_excluded': False,
                    'successor_execution_authorised': False})
            return 75
        if opts.status:
            records = cut.read_chain(intake.ROOT, owner=0)
            if records[0] != item:
                raise cut.AuthorityCutoverRefused('root registry no longer matches exact host evidence')
            output({'phase': records[-1]['phase'], 'chain_length': len(records),
                    'provider_executed': False, 'execution_authority': 'NONE',
                    'original_workspace_modified': False})
            return 75
        # Binding the operator's approval to an exact dry-run record prevents
        # unnoticed source, custody, project, boot or epoch changes.
        if opts.approved_preview_hash != item['record_sha256']:
            raise cut.AuthorityCutoverRefused('explicit exact-record operator approval required')
        if opts.prepare_approved:
            cut.publish_prepared(intake.ROOT, item, owner=0)
        elif opts.fence_approved:
            current = cut.read_chain(intake.ROOT, owner=0)
            if len(current) != 1 or current[0] != item:
                raise cut.AuthorityCutoverRefused('expected phase-0 authoritative record missing')
            # A zero-holder scan is a quiescence observation only. It does not
            # grant kernel revocation of old FDs, nor prohibit future launches.
            holders = gate.scan_live_holders()
            if (holders.get('workspace_holders') or holders.get('uncertain_processes') or
                    holders.get('all_visible_processes_observed') is not True):
                raise cut.AuthorityCutoverRefused('active/unknown historical references')
            cut.advance(intake.ROOT, owner=0, next_phase=cut.PHASES[1])
        else:
            raise cut.AuthorityCutoverRefused('unsupported command')
        output({'phase': 'ROOT_AUTHORITY_REGISTRY_UPDATED_EXECUTION_DENIED',
                'execution_authority': 'NONE', 'provider_executed': False,
                'successor_execution_authorised': False})
        return 75
    except (OSError, ValueError, RuntimeError) as exc:
        # No sensitive custody bytes in the refusal output.
        output({'phase': 'ROOT_AUTHORITY_REGISTRY_REFUSED_EXECUTION_DENIED',
                'reason_type': type(exc).__name__, 'provider_executed': False,
                'successor_execution_authorised': False})
        return 75


if __name__ == '__main__':
    raise SystemExit(main())
