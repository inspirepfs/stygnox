#!/usr/bin/env python3
"""C3g live-kernel BLOCKED transition probe using only disposable /run fixtures.

Never accepts a project root or existing transaction path. Must be executed by
root with a non-root legacy UID. Cannot grant StygNox execution authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_transfer as transfer
from stygnox.direct_interruption_fence import SUCCESSOR_STATUS
from stygnox import direct_interruption_quarantine as quarantine
from stygnox.direct_interruption_supervisor import publish_blocked_namespace


def seal(body: dict, key: str) -> dict:
    result = dict(body)
    result[key] = recovery._digest(result)
    return result


def evidence() -> tuple[dict, dict, dict, dict, dict]:
    tx = seal({
        'schema': 'stygnox_transaction_v1', 'transaction_id': 'TX-disposable-c3g',
        'state': 'ACTIVE', 'installed_command': '/old/bin/stygnox',
    }, 'record_sha256')
    active = seal({
        'schema': 'stygnox_controller_state_v1', 'transaction_id': 'TX-disposable-c3g',
        'enabled': True, 'installed_command': '/old/bin/stygnox',
    }, 'record_sha256')
    plan = seal({
        'schema': 'stygnox_plan_state_v1', 'status': 'APPROVED',
        'execution_authority_granted': True, 'plan_hash': '1'*64,
        'transaction_id': 'TX-disposable-c3g', 'operator': 'fixture-operator',
        'current_step': 2, 'controller_record_sha256': active['record_sha256'],
        'transaction_record_sha256': tx['record_sha256'], 'active_gate': None,
        'self_development_grant': None, 'direct_interruption_pending': None,
        'direct_interruption_recoveries': [],
        'repository_mutation_scope': ['src/stygnox/planning.py'],
        'continuation_history': [{'accepted': 'fixture'}],
    }, 'record_sha256')
    admission = seal({
        'schema': 'stygnox_direct_interruption_successor_admission_preflight_v1',
        'admissible': False, 'authority_changed': False,
        'successor_execution_admission': 'DISABLED',
        'exclusive_transfer_publication': 'NOT_IMPLEMENTED',
        'proposed_successor_only_plan_status': SUCCESSOR_STATUS,
        'proposed_legacy_execution_authority_granted': False,
        'predecessor_plan_record_sha256': plan['record_sha256'],
        'predecessor_controller_record_sha256': active['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'plan_hash': '1'*64, 'transaction_id': 'TX-disposable-c3g',
        'operator': 'fixture-operator', 'current_step': 2,
        'handoff_preview_sha256': '5'*64,
        'fence_design_sha256': '6'*64, 'review_preview_sha256': '7'*64,
        'manifest_proof_sha256': '8'*64,
        'predecessor_installed_executable': {'path': '/old/bin/stygnox', 'sha256': '9'*64},
        'successor_installed_identity': {'executable': '/new/bin/stygnox'},
        'successor_wheel_identity': {'sha256': 'a'*64},
    }, 'preview_sha256')
    proposal = transfer.build_fence_publication_preview(admission, plan)
    journal = publication.build_journal_preview(proposal)
    return plan, proposal, journal, active, tx


def unused_uid(exclude: int) -> int:
    for candidate in range(61001, 62000):
        if candidate == exclude:
            continue
        try:
            pwd.getpwuid(candidate)
        except KeyError:
            return candidate
    raise RuntimeError('no unused successor UID in the disposable range')


def drop(uid: int):
    def child():
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    return child


def run(legacy: int) -> dict:
    if not Path('/run').is_dir() or os.geteuid() != 0 or legacy <= 0:
        raise RuntimeError('Linux root supervisor and non-root legacy UID required')
    pwd.getpwuid(legacy)
    successor = unused_uid(legacy)
    plan, proposal, journal, controller_record, tx_record = evidence()
    with tempfile.TemporaryDirectory(dir='/run', prefix='stygnox-c3g-probe-') as temp:
        base = Path(temp)
        base.chmod(0o755)
        active, vault, stage, publish = (base / name for name in ('active','vault','stage','publish'))
        for path, mode in ((active, 0o711), (vault, 0o700), (stage, 0o700), (publish, 0o711)):
            path.mkdir(mode=mode)
        original, retired = active/'old', vault/'retired'
        staged, published = stage/'successor', publish/'successor'
        for path, uid in ((original, legacy), (staged, successor)):
            path.mkdir(mode=0o700)
            runtime = path/'.stygnox'
            runtime.mkdir(mode=0o700)
            p = runtime/'plan.json'
            p.write_text(json.dumps(plan))
            p.chmod(0o600)
            os.chown(p, uid, uid)
            for name, authority in (('controller.json', controller_record), ('transaction.json', tx_record)):
                f = runtime / name
                f.write_text(json.dumps(authority))
                f.chmod(0o600)
                os.chown(f, uid, uid)
            os.chown(runtime, uid, uid)
            os.chown(path, uid, uid)
        original_st = original.stat()
        staged_st = staged.stat()
        record = publish_blocked_namespace(
            original=original, retired=retired, staged=staged, published=published,
            predecessor_uid=legacy, successor_uid=successor,
            predecessor_identity=(original_st.st_dev, original_st.st_ino),
            staged_identity=(staged_st.st_dev, staged_st.st_ino),
            transfer_preview=proposal, journal_preview=journal,
        )
        actual = json.loads((published/'.stygnox'/'plan.json').read_text())
        observed_journal = json.loads((published/'.stygnox'/'direct-interruption-transfer-journal.json').read_text())
        observed_binding = json.loads((published/'.stygnox'/'direct-interruption-blocked-binding.json').read_text())
        actual_controller = json.loads((published/'.stygnox'/'controller.json').read_text())
        actual_tx = json.loads((published/'.stygnox'/'transaction.json').read_text())
        actual_quarantine = json.loads((published/'.stygnox'/quarantine.FILENAME).read_text())
        checked_quarantine = quarantine.validate_quarantine_binding(
            fenced_plan=actual, journal=observed_journal, witness=observed_binding,
            controller_record=actual_controller, transaction_record=actual_tx,
            quarantine_record=actual_quarantine)
        check = subprocess.run(
            [sys.executable, '-c',
             'from pathlib import Path;import sys;Path(sys.argv[1]).write_text("UNAUTHORISED")',
             str(published/'.stygnox'/'plan.json')],
            capture_output=True, text=True, timeout=5, preexec_fn=drop(legacy),
        )
        result = {
            'schema': 'stygnox_c3g_disposable_blocked_transition_probe_v1',
            'fixture': 'root_owned_private_staging_and_cross_uid_publish',
            'legacy_uid': legacy, 'successor_uid': successor,
            'predecessor_path_missing': not original.exists(),
            'predecessor_retired_root_privately': retired.is_dir(),
            'private_stage_withdrawn': not staged.exists(),
            'fenced_successor_visible': published.is_dir(),
            'predecessor_denied_published_write': check.returncode != 0,
            'exact_fenced_plan': actual == proposal['fenced_plan'],
            'exact_journal': observed_journal == journal,
            'disabled_successor_controller': (actual_controller['enabled'] is False and
                actual_controller['controller_execution_enabled'] is False),
            'quarantined_successor_transaction': actual_tx['state'] == 'RECOVERY_QUARANTINED',
            'exact_quarantine_binding': checked_quarantine['receipt'] == actual_quarantine,
            'exact_blocked_binding': (observed_binding['record_sha256'] == record['blocked_binding_record_sha256']
                                     and observed_binding['successor_execution_authorised'] is False),
            'legacy_execution_authority_granted': actual['execution_authority_granted'],
            'successor_execution_authorised': record['successor_execution_authorised'],
            'original_binding_retired': record['binding_transferred'],
            'unknown_predecessor_holders_excluded': record['unknown_legacy_holders_excluded'],
            'handoff_admissible': record['handoff_admissible'],
            'live_runtime_modified': False,
        }
        required = ('predecessor_path_missing', 'predecessor_retired_root_privately',
                    'private_stage_withdrawn', 'fenced_successor_visible',
                    'predecessor_denied_published_write', 'exact_fenced_plan', 'exact_journal',
                    'exact_blocked_binding', 'disabled_successor_controller',
                    'quarantined_successor_transaction', 'exact_quarantine_binding')
        if not all(result[key] is True for key in required):
            raise RuntimeError(f'kernel blocked-publish probe failure: {result}')
        if any(result[key] is not False for key in ('legacy_execution_authority_granted',
                                                   'successor_execution_authorised',
                                                   'original_binding_retired',
                                                   'unknown_predecessor_holders_excluded',
                                                   'handoff_admissible')):
            raise RuntimeError('probe unexpectedly issued execution authority')
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--legacy-uid', type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.legacy_uid), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'C3g REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
