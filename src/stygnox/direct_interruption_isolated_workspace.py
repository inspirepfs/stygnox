"""R3D.2: data-only, inode-independent successor workspace PREPARATION.

Prepares a quarantined snapshot from verified root-protected evidence. It does
not consume the user-owned live workspace, retire any predecessor, start a
service, establish predecessor exclusion, or admit provider execution.

Never use this data-only copy as an executable installed Stygnox product.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Mapping, Any

from . import direct_interruption_custody_intake as intake
from . import direct_interruption_custody_cutover as custody
from . import direct_interruption_blocked_commissioning as commissioning
from . import direct_interruption_host_readiness as readiness

SLOT = 'recovery-r3d2-isolated-workspace-denied-v1'
SCHEMA = 'stygnox_r3d2_isolated_workspace_denied_v1'
MAX_FILES = 2000
MAX_BYTES = 256 * 1024 * 1024
# Production may NOT arbitrarily select another workspace or project.
ORIGINAL = Path('/home/pfsykes/stygnox-r3d2-astra')


class IsolatedWorkspaceRefused(RuntimeError):
    """Safe, nonexecuting successor workspace preparation is not proven."""


def _fail(why: str) -> None:
    raise IsolatedWorkspaceRefused(why)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(record: Mapping[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False) + '\n').encode('utf-8')


def _safe_member(name: str) -> None:
    if (not isinstance(name, str) or not name or name.startswith('/') or
            '\\' in name or '\x00' in name or any(
                part in ('', '.', '..') for part in name.split('/'))):
        _fail('noncanonical preserved member name')
    if name == '.stygnox/' + commissioning.MARKER:
        _fail('candidate already contains cutover quarantine marker')


def _prepare(source: Mapping[str, bytes], projection: Mapping[str, Mapping[str, Any]],
             *, custody_sha256: str, candidate_manifest_sha256: str) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Pure input binding: source history is replaced only by deny-state records.

    The source mapping must be from independently verified, protected immutable
    evidence (the live entry re-reads EVERY candidate member by no-follow FD).
    """
    if not isinstance(source, Mapping) or not 1 <= len(source) <= MAX_FILES:
        _fail('invalid source inventory')
    if not all(isinstance(b, bytes) for b in source.values()):
        _fail('source members must be exact bytes')
    if sum(len(b) for b in source.values()) > MAX_BYTES:
        _fail('candidate exceeds fixed size ceiling')
    if set(projection) != custody._FILES or any(
            not intake._record_hash(p) for p in projection.values()):
        _fail('custody projection is not canonical and sealed')
    if not all(isinstance(x, str) and len(x) == 64 and
               all(c in '0123456789abcdef' for c in x)
               for x in (custody_sha256, candidate_manifest_sha256)):
        _fail('invalid manifest or custody binding')
    if (projection['plan.json'].get('status') != 'RECOVERY_QUARANTINED' or
            projection['plan.json'].get('execution_authority_granted') is not False or
            projection['controller.json'].get('enabled') is not False or
            projection['transaction.json'].get('state') != 'RECOVERY_QUARANTINED' or
            projection[commissioning.MARKER].get('successor_execution_authorised') is not False):
        _fail('authority-enabled projection rejected')
    for name in source:
        _safe_member(name)
    required = {'.stygnox/plan.json', '.stygnox/controller.json',
                '.stygnox/transaction.json'}
    if not required <= set(source):
        _fail('incomplete predecessor runtime lineage')
    # Critical: new files/inodes, not hardlinks to historic source or live tree.
    staged = dict(source)
    for name, record in projection.items():
        staged['.stygnox/' + name] = _canonical(record)
    manifest = {
        'schema': SCHEMA,
        'phase': 'ISOLATED_WORKSPACE_STAGED_EXECUTION_DENIED',
        'transaction_id': intake.TX,
        'approved_plan_hash': intake.PLAN,
        'base_git_head': intake.BASE,
        'current_step': 2,
        'recorded_continuations': 8,
        'historical_step_result_count': 1,
        'protected_candidate_manifest_sha256': candidate_manifest_sha256,
        'blocked_root_custody_record_sha256': custody_sha256,
        'original_workspace_path': str(ORIGINAL),
        'original_workspace_modified': False,
        'historical_provider_work_replayed': False,
        'root_only_isolated_worktree': True,
        'independent_regular_file_inodes_required': True,
        'old_workspace_execution_excluded': False,
        'legacy_controller_excluded': False,
        'successor_execution_authorised': False,
        'successor_identity_commissioned': False,
        'provider_executed': False,
        'operator_release_approved': False,
        'workspace_files': {name: _sha(data) for name, data in sorted(staged.items())},
    }
    manifest['record_sha256'] = _sha(intake._canonical(manifest))
    return staged, manifest


def _write_new(parentfd: int, name: str, raw: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o400, dir_fd=parentfd)
    try:
        with os.fdopen(os.dup(fd), 'wb') as stream:
            stream.write(raw)
            stream.flush()
        os.fsync(fd)
    finally:
        os.close(fd)


def _mkdir_file_tree(worktreefd: int, records: Mapping[str, bytes]) -> None:
    """All descendants root-only, new inodes, no symlinks or inherited links."""
    dirs = sorted({parent for name in records
                   for parent in _parents(name)}, key=lambda p: (p.count('/'), p))
    for path in dirs:
        parent, leaf = path.rsplit('/', 1) if '/' in path else ('', path)
        dirfd = os.open(parent or '.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                        os.O_CLOEXEC, dir_fd=worktreefd)
        try:
            os.mkdir(leaf, 0o700, dir_fd=dirfd)
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    for name, raw in sorted(records.items()):
        parent, leaf = name.rsplit('/', 1) if '/' in name else ('', name)
        dirfd = os.open(parent or '.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                        os.O_CLOEXEC, dir_fd=worktreefd)
        try:
            _write_new(dirfd, leaf, raw)
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    os.fsync(worktreefd)


def _parents(name: str) -> tuple[str, ...]:
    parts = name.split('/')[:-1]
    return tuple('/'.join(parts[:i]) for i in range(1, len(parts) + 1))


def _publish(root: Path, records: Mapping[str, bytes], manifest: Mapping[str, Any],
             *, uid: int) -> dict[str, Any]:
    """One-shot atomic blocked publication; fixture tests run as their own UID.

    LIVE callers must independently verify root ancestry and original archive
    first. Never retry an interrupted .pending and never automatically clean it.
    """
    if not intake._record_hash(manifest) or manifest.get('schema') != SCHEMA:
        _fail('noncanonical workspace manifest')
    if (manifest.get('phase') != 'ISOLATED_WORKSPACE_STAGED_EXECUTION_DENIED' or
            manifest.get('successor_execution_authorised') is not False or
            manifest.get('legacy_controller_excluded') is not False or
            manifest.get('successor_identity_commissioned') is not False or
            manifest.get('operator_release_approved') is not False or
            manifest.get('provider_executed') is not False or
            manifest.get('workspace_files') != {name: _sha(raw) for name, raw in sorted(records.items())}):
        _fail('cannot publish unbound or authority-claiming workspace')
    if not 1 <= len(records) <= MAX_FILES + 1:
        _fail('invalid workspace member count')
    for name in records:
        _safe_member(name) if name != '.stygnox/' + commissioning.MARKER else None
    rootfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(rootfd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or
                stat.S_IMODE(info.st_mode) != 0o700):
            _fail('private custody root is not exclusive')
        if sum(len(raw) for raw in records.values()) > MAX_BYTES:
            _fail('staged records exceed total bytes ceiling')
        if os.path.lexists(root / SLOT) or os.path.lexists(root / (SLOT + '.pending')):
            _fail('commissioned workspace exists or publication interrupted')
        try:
            os.mkdir(SLOT + '.pending', 0o700, dir_fd=rootfd)
        except FileExistsError as exc:
            raise IsolatedWorkspaceRefused('concurrent claimant or stale pending') from exc
        pendingfd = os.open(SLOT + '.pending', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                            os.O_CLOEXEC, dir_fd=rootfd)
        try:
            os.mkdir('workspace', 0o700, dir_fd=pendingfd)
            wfd = os.open('workspace', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                          os.O_CLOEXEC, dir_fd=pendingfd)
            try:
                _mkdir_file_tree(wfd, records)
            finally:
                os.close(wfd)
            _write_new(pendingfd, 'isolated-workspace.json', _canonical(manifest))
            os.fsync(pendingfd)
        finally:
            os.close(pendingfd)
        os.rename(SLOT + '.pending', SLOT, src_dir_fd=rootfd, dst_dir_fd=rootfd)
        os.fsync(rootfd)
    except OSError as exc:
        raise IsolatedWorkspaceRefused('isolated publication interrupted; manual reconciliation required') from exc
    finally:
        os.close(rootfd)
    return {
        'schema': SCHEMA,
        'phase': 'ISOLATED_WORKSPACE_STAGED_EXECUTION_DENIED',
        'published_path': str(root / SLOT),
        'legacy_controller_excluded': False,
        'successor_identity_commissioned': False,
        'successor_execution_authorised': False,
        'provider_executed': False,
    }


def prepare_live_denied_workspace() -> dict[str, Any]:
    """Host-side ONE SHOT DATA-ONLY operation; NEVER permits provider launch.

    Explicit operator approval is required before root deployment/operation.
    Never call this through the ordinary controller or a mutable checkout.
    """
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/status').is_file():
        _fail('root Linux supervisor required')
    commissioning._trusted_root(intake.ROOT)
    existing = readiness.verify_published_slot(intake.ROOT, uid=0)
    # Validate every preserved record and all 609 candidate files against the
    # original separately protected source of truth. No access to /home.
    intake.audit_protected_intake()
    manifest_path = intake.ROOT / intake.CANDIDATE / 'offline-reconstruction-manifest.json'
    source_manifest = intake._json(intake._read_root_file(manifest_path))
    spec = source_manifest.get('files')
    if not isinstance(spec, dict) or len(spec) != 609:
        _fail('candidate file inventory changed')
    records: dict[str, bytes] = {}
    for name, entry in spec.items():
        _safe_member(name)
        raw = intake._read_root_file(intake.ROOT / intake.CANDIDATE / name)
        if _sha(raw) != entry.get('sha256'):
            _fail('protected candidate changed during staging')
        records[name] = raw
    slot = intake.ROOT / custody.SLOT / '.stygnox'
    projection = {
        name: readiness._record(slot, name, uid=0)
        for name in sorted(custody._FILES)
    }
    staged, manifest = _prepare(
        records, projection,
        custody_sha256=existing['root_custody_record_sha256'],
        candidate_manifest_sha256=intake.EXPECTED['candidate'],
    )
    return _publish(intake.ROOT, staged, manifest, uid=0)


def verify_isolated_workspace(root: Path, *, uid: int,
                              old_candidate: Path | None = None) -> dict[str, Any]:
    """Reopen and verify the complete new inode graph and deny-only state.

    Host operation requires root owner and trusted ancestry before this call.
    The optional candidate path is protected evidence, NEVER the live workspace.
    """
    slot = root / SLOT
    if os.path.lexists(root / (SLOT + '.pending')):
        _fail('stale pending workspace requires manual reconciliation')
    for directory in (slot, slot / 'workspace', slot / 'workspace/.stygnox'):
        st = directory.lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or
                stat.S_IMODE(st.st_mode) != 0o700):
            _fail('workspace directory substituted or accessible to predecessor')
    if set(os.listdir(slot)) != {'workspace', 'isolated-workspace.json'}:
        _fail('unexpected staged workspace root members')
    manifest_file = slot / 'isolated-workspace.json'
    fd = os.open(manifest_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o400 or
                info.st_size > MAX_BYTES):
            _fail('untrusted workspace manifest')
        raw = os.read(fd, MAX_BYTES + 1)
        if len(raw) != info.st_size:
            _fail('workspace manifest length changed')
    finally:
        os.close(fd)
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise IsolatedWorkspaceRefused('corrupt workspace manifest') from exc
    if (not isinstance(manifest, dict) or not intake._record_hash(manifest) or
            raw != _canonical(manifest) or manifest.get('schema') != SCHEMA or
            manifest.get('phase') != 'ISOLATED_WORKSPACE_STAGED_EXECUTION_DENIED' or
            manifest.get('transaction_id') != intake.TX or
            manifest.get('approved_plan_hash') != intake.PLAN or
            manifest.get('base_git_head') != intake.BASE or
            manifest.get('current_step') != 2 or
            manifest.get('recorded_continuations') != 8 or
            manifest.get('historical_step_result_count') != 1 or
            manifest.get('protected_candidate_manifest_sha256') != intake.EXPECTED['candidate'] or
            manifest.get('original_workspace_path') != str(ORIGINAL) or
            any(manifest.get(flag) is not False for flag in (
                'original_workspace_modified', 'historical_provider_work_replayed',
                'old_workspace_execution_excluded', 'legacy_controller_excluded',
                'successor_execution_authorised', 'successor_identity_commissioned',
                'provider_executed', 'operator_release_approved')) or
            manifest.get('root_only_isolated_worktree') is not True or
            manifest.get('independent_regular_file_inodes_required') is not True):
        _fail('stage is corrupt or asserts unproved execution authority')
    expected = manifest.get('workspace_files')
    if (not isinstance(expected, dict) or not 1 <= len(expected) <= MAX_FILES + 1):
        _fail('workspace inventory absent')
    paths_seen: set[str] = set()
    actual_dirs: set[str] = set()
    def walk_error(exc: OSError) -> None:
        raise IsolatedWorkspaceRefused('cannot traverse staged member graph') from exc

    for folder, folders, filenames in os.walk(slot / 'workspace', followlinks=False, onerror=walk_error):
        relative = Path(folder).relative_to(slot / 'workspace').as_posix()
        if relative != '.':
            actual_dirs.add(relative)
        for dirname in folders:
            entry = Path(folder) / dirname
            st = entry.lstat()
            if (not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or
                    stat.S_IMODE(st.st_mode) != 0o700):
                _fail('candidate directory alias or unsafe mode')
        for filename in filenames:
            candidate = Path(folder) / filename
            name = candidate.relative_to(slot / 'workspace').as_posix()
            paths_seen.add(name)
            if name not in expected:
                _fail('unexpected staged member')
            try:
                fd = os.open(candidate, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError as exc:
                raise IsolatedWorkspaceRefused("unsafe or substituted staged member") from exc
            try:
                st = os.fstat(fd)
                if (not stat.S_ISREG(st.st_mode) or st.st_uid != uid or
                        stat.S_IMODE(st.st_mode) != 0o400 or st.st_nlink != 1 or
                        st.st_size > intake._MAX):
                    _fail('staged member has unsafe permissions or hardlink')
                data = os.read(fd, intake._MAX + 1)
                if len(data) != st.st_size or _sha(data) != expected[name]:
                    _fail('staged member digest or size changed')
                if old_candidate is not None and (old_candidate / name).exists():
                    other = (old_candidate / name).lstat()
                    if (st.st_dev, st.st_ino) == (other.st_dev, other.st_ino):
                        _fail('candidate reused original inode instead of copying')
            finally:
                os.close(fd)
    if paths_seen != set(expected):
        _fail('missing staged candidate members')
    declared_dirs = {d for name in expected for d in _parents(name)}
    if actual_dirs != declared_dirs:
        _fail('undeclared candidate directory')
    for name, field, value in (
        ('plan.json', 'status', 'RECOVERY_QUARANTINED'),
        ('controller.json', 'enabled', False),
        ('transaction.json', 'state', 'RECOVERY_QUARANTINED'),
        (commissioning.MARKER, 'successor_execution_authorised', False),
    ):
        staged = json.loads((slot / 'workspace/.stygnox' / name).read_bytes())
        if not intake._record_hash(staged) or staged.get(field) != value:
            _fail('candidate has executable or corrupted runtime')
    return {
        'phase': 'ISOLATED_WORKSPACE_VERIFIED_EXECUTION_DENIED',
        'file_count': len(expected),
        'manifest_record_sha256': manifest['record_sha256'],
        'original_workspace_modified': False,
        'legacy_controller_excluded': False,
        'successor_execution_authorised': False,
        'provider_executed': False,
    }
