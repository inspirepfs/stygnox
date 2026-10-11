"""C3i read-only installed successor inspection of a *blocked* C3h namespace.

This is NOT an authority handoff. It cannot authenticate operator approval,
retire a predecessor binding or enable scheduler, provider or recovery release.
It ties real installed package/RECORD/wheel proof to the exact C3h publication.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from . import direct_interruption as recovery
from . import direct_interruption_binding as binding
from . import direct_interruption_exclusion as exclusion
from . import direct_interruption_publication as publication
from . import direct_interruption_transfer as transfer
from . import lifecycle
from .direct_interruption_supervisor import BINDING, JOURNAL, _open_runtime, _regular_json
from .direct_interruption_fence import SUCCESSOR_STATUS

SCHEMA = 'stygnox_c3i_installed_blocked_successor_inspection_v1'


class SuccessorInspectionRefused(RuntimeError):
    """Actual installed successor or exact blocked lineage is unproved."""


def _rebuild_original_plan(fenced: Mapping[str, Any]) -> dict[str, Any]:
    """Invert ONLY the C3a fence fields, never assert authority from this copy."""
    if (fenced.get('status') != SUCCESSOR_STATUS or
            fenced.get('execution_authority_granted') is not False or
            not isinstance(fenced.get('direct_interruption_transfer_pending'), Mapping)):
        raise SuccessorInspectionRefused('successor-only blocked plan required')
    original = deepcopy(dict(fenced))
    original.pop('record_sha256', None)
    original.pop('direct_interruption_transfer_pending', None)
    original['status'] = 'APPROVED'
    original['execution_authority_granted'] = True
    original['record_sha256'] = recovery._digest(original)
    return original


def validate_blocked_snapshot(*, original: Path, published: Path,
                              admission: Mapping[str, Any], proposal: Mapping[str, Any],
                              current_plan: Mapping[str, Any], journal: Mapping[str, Any],
                              witness: Mapping[str, Any], controller_record: Mapping[str, Any],
                              transaction_record: Mapping[str, Any],
                              installed_identity: Mapping[str, Any], wheel_identity: Mapping[str, Any],
                              invocation: Path) -> dict[str, Any]:
    """Pure, exact identity check; always returns BLOCKED, never authority."""
    try:
        preflight = transfer._sealed(admission, 'preview_sha256')
        projection = publication._transfer(proposal)
        plan = publication._sealed(current_plan, 'record_sha256')
        observed_journal = publication._sealed(journal, 'preview_sha256')
        observed_witness = publication._sealed(witness, 'record_sha256')
        old_controller = binding._record(controller_record, 'stygnox_controller_state_v1')
        old_transaction = binding._record(transaction_record, 'stygnox_transaction_v1')
        expected_original = _rebuild_original_plan(plan)
        rebuilt = transfer.build_fence_publication_preview(preflight, expected_original)
        expected_journal = publication.build_journal_preview(rebuilt)
        expected_witness = binding.build_blocked_binding_witness(
            transfer_preview=rebuilt, journal_preview=expected_journal,
            predecessor_controller=old_controller, predecessor_transaction=old_transaction,
            original=original, published=published,
        )
    except (transfer.TransferRefused, publication.PublicationRefused,
            binding.BindingRefused, KeyError, TypeError, ValueError) as exc:
        raise SuccessorInspectionRefused(f'invalid installed binding lineage: {exc}') from exc

    if (preflight.get('schema') != 'stygnox_direct_interruption_successor_admission_preflight_v1'
            or preflight.get('admissible') is not False
            or preflight.get('authority_changed') is not False
            or preflight.get('successor_execution_admission') != 'DISABLED'
            or preflight.get('exclusive_transfer_publication') != 'NOT_IMPLEMENTED'
            or projection != rebuilt or plan != rebuilt['fenced_plan']
            or observed_journal != expected_journal or observed_witness != expected_witness
            or projection['admission_preview_sha256'] != preflight['preview_sha256']
            or observed_witness['published_successor_worktree'] != str(published)
            or observed_witness['original_worktree'] != str(original)):
        raise SuccessorInspectionRefused('published records are stale, substituted or authority claiming')
    pending = plan['direct_interruption_transfer_pending']
    claimed_installed = preflight.get('successor_installed_identity')
    claimed_wheel = preflight.get('successor_wheel_identity')
    old = preflight.get('predecessor_installed_executable')
    if (not isinstance(claimed_installed, Mapping) or not isinstance(claimed_wheel, Mapping)
            or not isinstance(old, Mapping)
            or dict(installed_identity) != dict(claimed_installed)
            or dict(wheel_identity) != dict(claimed_wheel)
            or installed_identity.get('executable') != pending.get('successor_executable')
            or installed_identity.get('executable') != observed_witness.get('candidate_installed_command_unverified')
            or wheel_identity.get('sha256') != pending.get('successor_wheel_sha256')
            or old.get('path') != observed_witness.get('predecessor_installed_command')
            or str(invocation) != installed_identity.get('executable')
            or str(invocation) == old.get('path')
            or not isinstance(old.get('sha256'), str)
            or not transfer._hash_ok(old.get('sha256'))):
        raise SuccessorInspectionRefused('installed successor executable/wheel/invocation identity mismatch')
    return {
        'schema': SCHEMA,
        'original_worktree': str(original),
        'blocked_successor_worktree': str(published),
        'transaction_id': plan['transaction_id'],
        'plan_hash': plan['plan_hash'],
        'fenced_plan_record_sha256': plan['record_sha256'],
        'blocked_binding_record_sha256': observed_witness['record_sha256'],
        'successor_executable': installed_identity['executable'],
        'successor_installed_record_sha256': installed_identity['record_sha256'],
        'successor_wheel_sha256': wheel_identity['sha256'],
        'exact_blocked_lineage': True,
        'installed_successor_identity_verified': True,
        'predecessor_executable_rechecked': False,
        'original_binding_retired': False,
        'legacy_inflight_process_exclusion_proved': False,
        'successor_execution_authorised': False,
        'handoff_admissible': False,
        'authority_changed': False,
    }


def _original_absence_visible(original: Path) -> bool:
    """An inaccessible legacy parent is not proof that the old path is gone."""
    try:
        os.lstat(original)
    except FileNotFoundError:
        return True
    except PermissionError:
        return False
    raise SuccessorInspectionRefused('predecessor original path was not retired')


def _read_external(path: Path) -> dict[str, Any]:
    """Read bounded operator-supplied preview; contents remain untrusted."""
    if not Path(path).is_absolute() or '..' in Path(path).parts:
        raise SuccessorInspectionRefused('evidence path must be absolute')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > 16_000_000:
            raise SuccessorInspectionRefused('unsafe evidence file')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            value = json.loads(stream.read(16_000_001))
        if not isinstance(value, dict):
            raise SuccessorInspectionRefused('evidence must be a JSON object')
        return value
    finally:
        os.close(fd)


def inspect_installed_blocked_successor(*, project: Path, predecessor_uid: int,
                                        admission_file: Path, transfer_file: Path,
                                        candidate_wheel: Path) -> dict[str, Any]:
    """Read-only inspection from exact installed Stygnox; never used for release."""
    project = Path(project)
    uid = os.geteuid()
    if uid == 0 or predecessor_uid == uid:
        raise SuccessorInspectionRefused('inspection requires a distinct non-root successor UID')
    try:
        exclusion.verify_dac_boundary(project, predecessor_uid=predecessor_uid, successor_uid=uid)
        admission = _read_external(admission_file)
        proposal = _read_external(transfer_file)
        fd = _open_runtime(project, owner=uid)
        try:
            plan = _regular_json(fd, 'plan.json', uid)
            journal = _regular_json(fd, JOURNAL, uid)
            witness = _regular_json(fd, BINDING, uid)
            old_controller = _regular_json(fd, 'controller.json', uid)
            old_tx = _regular_json(fd, 'transaction.json', uid)
        finally:
            os.close(fd)
        original = Path(str(witness['original_worktree']))
        # A private legacy home often hides the original path from the new UID.
        # Do not mistake EACCES for proof of retirement or reject read-only
        # installed-identity inspection solely because that proof is missing.
        original_absence_visible = _original_absence_visible(original)
        # The lifecycle implementation validates the actual imported package,
        # installed distribution/RECORD and wheel, not caller-provided hashes.
        installed = lifecycle._installed_identity(project)
        wheel = lifecycle._wheel_identity(candidate_wheel, installed)
        invocation = Path(sys.argv[0]).resolve()
        result = validate_blocked_snapshot(
            original=original, published=project,
            admission=admission, proposal=proposal, current_plan=plan,
            journal=journal, witness=witness, controller_record=old_controller,
            transaction_record=old_tx, installed_identity=installed,
            wheel_identity=wheel, invocation=invocation,
        )
        result['original_path_absence_visible_to_successor'] = original_absence_visible
        old_executable = Path(str(admission['predecessor_installed_executable']['path']))
        try:
            info = old_executable.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SuccessorInspectionRefused('installed predecessor executable inode changed')
            actual_old_sha = hashlib.sha256(old_executable.read_bytes()).hexdigest()
        except PermissionError:
            # Legacy installation may be private beneath UID 1000's home.
            # Never claim it was rechecked, and never use this as authority.
            result['predecessor_executable_rechecked'] = False
        else:
            if actual_old_sha != admission['predecessor_installed_executable']['sha256']:
                raise SuccessorInspectionRefused('installed predecessor executable changed')
            result['predecessor_executable_rechecked'] = True
        return result
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            exclusion.ExclusionRefused, lifecycle.LifecycleError) as exc:
        raise SuccessorInspectionRefused(f'installed successor inspection refused: {exc}') from exc
