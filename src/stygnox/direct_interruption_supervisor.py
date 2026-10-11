"""C3g root-supervised *blocked* recovery namespace transition.

The first authority-relevant publication primitive in the C3 recovery branch.
It retires an old root-anchored checkout and publishes only a *fenced* successor
replica from a root-private staging parent. Neither an installed-controller
handoff nor permission to execute follows from this operation. A legacy process
with an old open FD is not revoked; this operation is not a process drain.

Not wired to CLI: requires explicit independent operator authorization and a
hostile-qualified installed successor protocol before any live invocation.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping

from . import direct_interruption as recovery
from . import direct_interruption_publication as publication
from . import direct_interruption_transfer as transfer
from . import direct_interruption_binding as binding
from . import direct_interruption_quarantine as quarantine
from .direct_interruption_retirement import (
    RetirementRefused, _open_trusted_parent, retire_predecessor_path,
)
from .direct_interruption_workspace import inspect_protected_tree, WorkspaceRefused

SCHEMA = 'stygnox_c3g_blocked_namespace_publication_v1'
JOURNAL = 'direct-interruption-transfer-journal.json'
BINDING = binding.FILENAME


class SupervisorRefused(RuntimeError):
    """A root-supervised blocked transition cannot be admitted."""


def _regular_json(dirfd: int, name: str, uid: int) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=dirfd)
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_nlink != 1
                    or stat.S_IMODE(st.st_mode) != 0o600):
                raise SupervisorRefused('untrusted runtime record inode or permissions')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                body = stream.read(16_000_001)
            if len(body) > 16_000_000:
                raise SupervisorRefused('oversized authority record')
            result = json.loads(body)
            if not isinstance(result, dict):
                raise SupervisorRefused('authority record is not a JSON object')
            return result
        finally:
            os.close(fd)
    except (OSError, ValueError, UnicodeError) as exc:
        raise SupervisorRefused(f'cannot verify runtime record {name}: {exc}') from exc


def _open_runtime(worktree: Path, *, owner: int) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(worktree / '.stygnox', flags)
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != owner or stat.S_IMODE(st.st_mode) != 0o700:
        os.close(fd)
        raise SupervisorRefused('runtime directory owner or mode is unsafe')
    return fd


def _write_exact(fd: int, name: str, record: Mapping[str, Any], uid: int) -> None:
    """Single-directory durable replace, never an in-place legacy-compatible write."""
    if not name.endswith('.json') or '/' in name or '\\' in name:
        raise SupervisorRefused('non-canonical runtime filename')
    blob = (json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
    tmp = '.' + name + '.staging'
    if len(blob) > 16_000_000:
        raise SupervisorRefused('oversized publication record')
    try:
        writefd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                          0o600, dir_fd=fd)
    except OSError as exc:
        raise SupervisorRefused(f'staging name collision or inaccessible: {name}: {exc}') from exc
    try:
        os.fchown(writefd, uid, uid)
        with os.fdopen(os.dup(writefd), 'wb') as stream:
            stream.write(blob)
            stream.flush()
        os.fsync(writefd)
    finally:
        os.close(writefd)
    os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _read_old_plan(old: Path, uid: int) -> dict[str, Any]:
    fd = _open_runtime(old, owner=uid)
    try:
        return _regular_json(fd, 'plan.json', uid)
    finally:
        os.close(fd)


def _open_pinned_parents(original: Path, vault: Path, staging: Path,
                         published: Path) -> list[int]:
    parents = (original.parent, vault.parent, staging.parent, published.parent)
    if len({str(p) for p in parents}) != 4:
        raise SupervisorRefused('distinct trusted namespace parents required')
    fds = []
    try:
        for idx, path in enumerate(parents):
            fds.append(_open_trusted_parent(path, vault=idx in (1, 2)))
        if len({os.fstat(fd).st_dev for fd in fds}) != 1:
            raise SupervisorRefused('single-filesystem namespace transfer required')
        return fds
    except Exception:
        for fd in fds:
            os.close(fd)
        raise


def _entry_identity(fd: int, name: str, owner: int, expected: tuple[int, int]) -> None:
    st = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != owner
            or (st.st_dev, st.st_ino) != expected or stat.S_IMODE(st.st_mode) != 0o700):
        raise SupervisorRefused('namespace entry identity/ownership changed')


def _absent(fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise SupervisorRefused(f'namespace collision: {name}')


def _lock(vault_fd: int) -> int:
    """Supervisor-only serialization, NOT a cooperative old-controller lock."""
    try:
        fd = os.open('.stygnox-c3g.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=vault_fd)
        info = os.fstat(fd)
        if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode)):
            raise SupervisorRefused('supervisor lock is not root-private')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (OSError, BlockingIOError, SupervisorRefused) as exc:
        if 'fd' in locals():
            os.close(fd)
        raise SupervisorRefused(f'supervisor already active or lock unsafe: {exc}') from exc


def publish_blocked_namespace(*, original: Path, retired: Path,
                              staged: Path, published: Path,
                              predecessor_uid: int, successor_uid: int,
                              predecessor_identity: tuple[int, int],
                              staged_identity: tuple[int, int],
                              transfer_preview: Mapping[str, Any],
                              journal_preview: Mapping[str, Any]) -> dict[str, Any]:
    """Physically retire a root-anchored predecessor, then expose ONLY a blocked replica.

    The staged replica lives inside an inaccessible root-private directory;
    even the successor UID cannot reach an APPROVED copied plan beforehand.
    Publication order is: validate -> retire old -> journal -> fence ->
    expose blocked replica. Every interrupted boundary requires operator
    reconciliation; no automatic restart, release, or roll-back is attempted.

    This function CANNOT prove exclusion of unknown legacy holders, process
    descendants, controller binding, reviewed source, or final release.
    Caller must not infer those properties from its output.
    """
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/status').is_file():
        raise SupervisorRefused('Linux root supervisor required')
    if (predecessor_uid <= 0 or successor_uid <= 0 or predecessor_uid == successor_uid
        or any(not isinstance(x, int) or x <= 0 for x in (*predecessor_identity, *staged_identity))):
        raise SupervisorRefused('distinct non-root UIDs and pinned inode identities required')
    paths = tuple(Path(p) for p in (original, retired, staged, published))
    if any(not p.is_absolute() or '..' in p.parts or p.name in ('', '.', '..') for p in paths):
        raise SupervisorRefused('absolute canonical paths required')
    if len(set(paths)) != 4:
        raise SupervisorRefused('all namespace paths must be distinct')
    if any(paths[i].is_relative_to(paths[j]) for i in range(4) for j in range(4) if i != j):
        raise SupervisorRefused('nested namespace paths prohibited')
    # Validate complete immutable proposal BEFORE opening any writable handles.
    proposed = publication._transfer(transfer_preview)
    expected_journal = publication.build_journal_preview(proposed)
    if dict(journal_preview) != expected_journal:
        raise SupervisorRefused('journal proposal mismatch')
    fenced = proposed['fenced_plan']
    fds = _open_pinned_parents(*paths)
    try:
        lockfd = _lock(fds[1])
        try:
            _entry_identity(fds[0], original.name, predecessor_uid, predecessor_identity)
            _entry_identity(fds[2], staged.name, successor_uid, staged_identity)
            _absent(fds[1], retired.name)
            _absent(fds[3], published.name)
            inspect_protected_tree(staged, predecessor_uid=predecessor_uid, successor_uid=successor_uid)
            old_plan = _read_old_plan(original, predecessor_uid)
            stagefd = _open_runtime(staged, owner=successor_uid)
            try:
                staged_plan = _regular_json(stagefd, 'plan.json', successor_uid)
                # C3h: require byte-equivalent digest-bound installed authority
                # records in both namespaces before the irreversible retirement.
                oldfd = _open_runtime(original, owner=predecessor_uid)
                try:
                    original_controller = _regular_json(oldfd, 'controller.json', predecessor_uid)
                    original_tx = _regular_json(oldfd, 'transaction.json', predecessor_uid)
                finally:
                    os.close(oldfd)
                staged_controller = _regular_json(stagefd, 'controller.json', successor_uid)
                staged_tx = _regular_json(stagefd, 'transaction.json', successor_uid)
                if staged_controller != original_controller or staged_tx != original_tx:
                    raise SupervisorRefused('staged installed authority records differ from predecessor')
                try:
                    blocked_binding = binding.build_blocked_binding_witness(
                        transfer_preview=proposed, journal_preview=expected_journal,
                        predecessor_controller=original_controller,
                        predecessor_transaction=original_tx,
                        original=original, published=published,
                    )
                except binding.BindingRefused as exc:
                    raise SupervisorRefused(f'installed predecessor binding refused: {exc}') from exc
                if old_plan != staged_plan or old_plan.get('record_sha256') != proposed['predecessor_plan_record_sha256']:
                    raise SupervisorRefused('predecessor and staged authority lineage mismatch')
                transfer.classify_publication(proposed, staged_plan)
                try:
                    os.stat(JOURNAL, dir_fd=stagefd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise SupervisorRefused('journal already exists; manual reconciliation required')
                try:
                    os.stat(BINDING, dir_fd=stagefd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise SupervisorRefused('blocked binding record already exists; manual reconciliation required')
                # Build disabled controller/transaction records while the replica
                # is still private. No partial state is ever exposed as authority.
                disabled = quarantine.build_quarantine_binding(
                    fenced_plan=fenced, journal=expected_journal, witness=blocked_binding,
                    predecessor_controller=original_controller,
                    predecessor_transaction=original_tx)
                try:
                    os.stat(quarantine.FILENAME, dir_fd=stagefd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise SupervisorRefused('quarantine receipt already exists; manual review required')
                # The original rename is an irreversible fail-closed boundary.
                retire_predecessor_path(original, retired,
                                        predecessor_uid=predecessor_uid,
                                        expected_dev=predecessor_identity[0],
                                        expected_inode=predecessor_identity[1])
                _write_exact(stagefd, JOURNAL, expected_journal, successor_uid)
                _write_exact(stagefd, BINDING, blocked_binding, successor_uid)
                _write_exact(stagefd, 'plan.json', fenced, successor_uid)
                # Disable the controller FIRST; a crash before the transaction
                # update cannot create a new executable plan.
                _write_exact(stagefd, 'controller.json', disabled['controller'], successor_uid)
                _write_exact(stagefd, 'transaction.json', disabled['transaction'], successor_uid)
                _write_exact(stagefd, quarantine.FILENAME, disabled['receipt'], successor_uid)
                quarantine.validate_quarantine_binding(
                    fenced_plan=_regular_json(stagefd, 'plan.json', successor_uid),
                    journal=_regular_json(stagefd, JOURNAL, successor_uid),
                    witness=_regular_json(stagefd, BINDING, successor_uid),
                    controller_record=_regular_json(stagefd, 'controller.json', successor_uid),
                    transaction_record=_regular_json(stagefd, 'transaction.json', successor_uid),
                    quarantine_record=_regular_json(stagefd, quarantine.FILENAME, successor_uid))
                actual_binding = _regular_json(stagefd, BINDING, successor_uid)
                if actual_binding != blocked_binding:
                    raise SupervisorRefused('blocked installed authority witness does not match')
                actual_journal = _regular_json(stagefd, JOURNAL, successor_uid)
                actual_plan = _regular_json(stagefd, 'plan.json', successor_uid)
                phase = publication.reconcile_crash_boundary(proposed, actual_journal, actual_plan)
                if phase['phase'] != publication.FENCED:
                    raise SupervisorRefused('blocked publication not verified')
            finally:
                os.close(stagefd)
            # No successor can reach the staged path until the exact fenced
            # plan and journal have been synced. Exposure is an atomic rename.
            _entry_identity(fds[2], staged.name, successor_uid, staged_identity)
            _absent(fds[3], published.name)
            os.rename(staged.name, published.name, src_dir_fd=fds[2], dst_dir_fd=fds[3])
            os.fsync(fds[3])
            os.fsync(fds[2])
            _entry_identity(fds[3], published.name, successor_uid, staged_identity)
            return {
                'schema': SCHEMA,
                'predecessor_retired': True,
                'blocked_replica_exposed': True,
                'fenced_plan_record_sha256': fenced['record_sha256'],
                'journal_preview_sha256': expected_journal['preview_sha256'],
                'blocked_binding_record_sha256': blocked_binding['record_sha256'],
                'quarantine_record_sha256': disabled['receipt']['record_sha256'],
                'installed_successor_bound_non_executing': True,
                'publication_phase': phase['phase'],
                'legacy_original_path_reentry_blocked': True,
                'old_controller_execution_authority_revoked': False,
                'successor_execution_authorised': False,
                'preopened_fd_revocation_proved': False,
                'unknown_legacy_holders_excluded': False,
                'binding_transferred': False,
                'handoff_admissible': False,
            }
        finally:
            os.close(lockfd)
    except (RetirementRefused, WorkspaceRefused, OSError, ValueError, transfer.TransferRefused,
            publication.PublicationRefused, quarantine.QuarantineRefused) as exc:
        raise SupervisorRefused(f'blocked namespace publication refused or interrupted; manual review required: {exc}') from exc
    finally:
        for fd in fds:
            os.close(fd)
