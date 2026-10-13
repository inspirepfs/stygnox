"""R3D.2 hostile cutover gate: canonical evidence and OS exclusion attestations.

A read-only observer of the *real* live host. Unlike a process-name grep, it
inspects every visible Linux task's cwd/root/fds/maps/mountinfo for references
into the original transaction workspace, refuses unreadable process state, and
checks root-private custody and installed artifact bytes. A clean result is a
snapshot, never a right to release; existing/copyable legacy binaries and the
user-owned original namespace are still independent execution pathways.

No method here mutates the original, the custody record, a provider credential,
or an installed source tree. In particular, there is NO release/commit method.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
from typing import Any

from . import direct_interruption_blocked_commissioning as commissioning
from . import direct_interruption_custody_intake as intake
from . import direct_interruption_host_readiness as readiness
from . import direct_interruption_isolated_workspace as isolation

SCHEMA = 'stygnox_r3d2_host_cutover_gate_v1'
SOURCE_SHA256 = 'd1a97f8e6263339c6a360c5097cb471469bbe78cd5eee3372c212a1e446ed991'
ARCHIVE = Path('/usr/local/libexec/stygnox-recovery-a04f001-source.tar')
SOURCE = Path('/usr/local/libexec/stygnox-recovery-successor-a04f001')
ORIGINAL = Path('/home/pfsykes/stygnox-r3d2-astra')
PREDECESSOR_UID = 1000
_HASH_RE = re.compile(r'^[0-9a-f]{64}$')


class CutoverGateRefused(RuntimeError):
    """Evidence unavailable or inconsistent; execution remains denied."""


def _refuse(reason: str) -> None:
    raise CutoverGateRefused(reason)


def _directory(path: Path, *, uid: int) -> os.stat_result:
    st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or
            (st.st_mode & 0o022)):
        _refuse('untrusted source directory or ancestor')
    return st


def _file(path: Path, *, uid: int, maximum: int = 100 * 1024 * 1024) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError as exc:
        raise CutoverGateRefused('protected source member cannot be opened without following links') from exc
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_nlink != 1 or
                st.st_mode & 0o222 or st.st_size > maximum):
            _refuse('untrusted installed source file')
        raw = os.read(fd, maximum + 1)
        if len(raw) != st.st_size:
            _refuse('short or changing installed source file')
        return raw
    finally:
        os.close(fd)


def installed_artifact_audit(*, archive: Path = ARCHIVE, source: Path = SOURCE,
                             expected_sha: str = SOURCE_SHA256) -> dict[str, Any]:
    """Compare exact trusted deployment against byte-identical committed tar.

    File names, types, permissions, hardlinks, unexpected files and tar member
    duplications all matter. The root-controlled archive and source must be in
    trusted ancestors; this is a READ-ONLY check, not a publisher.
    """
    if not _HASH_RE.fullmatch(expected_sha):
        _refuse('invalid operator-pinned source digest')
    if not archive.is_absolute() or not source.is_absolute() or '..' in archive.parts or '..' in source.parts:
        _refuse('noncanonical installed source location')
    for chain in (archive.parent, source):
        for parent in (*reversed(chain.parents), chain):
            _directory(parent, uid=0)
    if stat.S_IMODE(source.lstat().st_mode) & 0o222:
        _refuse('installed source root remains writable')
    archived = _file(archive, uid=0)
    digest = hashlib.sha256(archived).hexdigest()
    if digest != expected_sha:
        _refuse('protected source archive does not match pinned commit')
    expected: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archived), mode='r:') as tar:
            for member in tar:
                name = member.name
                if (name.startswith('/') or '\\' in name or '\x00' in name or
                        any(p in ('', '.', '..') for p in name.split('/'))):
                    _refuse('unsafe source archive path')
                if member.isdir():
                    continue
                if not member.isfile() or name in expected or member.size > 16 * 1024 * 1024:
                    _refuse('unsupported, duplicate or oversized source member')
                stream = tar.extractfile(member)
                if stream is None:
                    _refuse('tar member without content')
                expected[name] = stream.read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise CutoverGateRefused('unable to audit protected source archive') from exc
    if not expected or len(expected) > 10000:
        _refuse('unexpected protected source member count')
    found: set[str] = set()
    found_dirs: set[str] = set()
    expected_dirs = {name.rsplit('/', i)[0] for name in expected
                     for i in range(1, name.count('/') + 1)}
    for folder, folders, files in os.walk(source, followlinks=False):
        base = Path(folder)
        _directory(base, uid=0)
        if stat.S_IMODE(base.lstat().st_mode) & 0o222:
            _refuse('writable directory inside installed source')
        if base != source:
            found_dirs.add(base.relative_to(source).as_posix())
        for name in folders:
            if not stat.S_ISDIR((base / name).lstat().st_mode):
                _refuse('symlink or substituted installed directory')
        for name in files:
            full = base / name
            relative = full.relative_to(source).as_posix()
            if relative not in expected:
                _refuse('untracked installed source file')
            if _file(full, uid=0, maximum=16 * 1024 * 1024) != expected[relative]:
                _refuse('installed artifact differs from protected committed archive')
            found.add(relative)
    if found != set(expected) or found_dirs != expected_dirs:
        _refuse('installed artifact inventory incomplete or contains undeclared directory')
    return {'source_archive_sha256': digest, 'installed_source_file_count': len(found),
            'installed_artifact_bytes_verified': True}


def _inside(value: str, original: Path) -> bool:
    """Conservative comparison: treat deleted paths as references too."""
    if not value.startswith('/'):
        return False
    target = str(original)
    return value == target or value.startswith(target + '/') or value.startswith(target + ' (deleted)')


def _readlink(path: Path) -> str:
    return os.readlink(path)


def _proc_text(path: Path, *, ceiling: int = 8 * 1024 * 1024) -> str:
    # procfs can expose arbitrarily large process maps. Never consume an
    # unbounded amount of live process data from a privileged helper.
    with path.open('rb') as stream:
        raw = stream.read(ceiling + 1)
    if len(raw) > ceiling:
        _refuse('process inventory exceeded conservative read ceiling')
    return raw.decode('utf-8')


def scan_live_holders(*, proc: Path = Path('/proc'), original: Path = ORIGINAL,
                      uid: int = PREDECESSOR_UID) -> dict[str, Any]:
    """Fail-closed snapshot of every task, including holders outside legacy UID.

    Process names cannot define coverage. Running UID is not sufficient: a
    different account could hold a directory fd. Any unreadable task or
    ambiguous record invalidates a quiescence claim. Mount namespace reads
    are *observations*; processes can re-open later and copies can execute.
    """
    if uid < 0 or not original.is_absolute() or '..' in original.parts:
        _refuse('invalid process coverage target')
    hits: list[dict[str, Any]] = []
    uncertain: list[int] = []
    inspected = 0
    try:
        tasks = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError as exc:
        raise CutoverGateRefused('cannot enumerate all visible processes') from exc
    for task in tasks:
        pid = int(task.name)
        try:
            status = _proc_text(task / 'status')
            line = next(x for x in status.splitlines() if x.startswith('Uid:'))
            uids = [int(n) for n in line.split()[1:5]]
            if len(uids) != 4:
                raise ValueError('malformed process UIDs')
            # Kernel threads have no userspace fds/cwd/exe. Skip only when
            # /proc explicitly identifies the task as a kernel thread.
            if any(line.strip() == 'Kthread:\t1' for line in status.splitlines()):
                continue
            # Deliberately inspect *every* userspace process, including root,
            # for inherited FDs and accessible aliases.
            references: list[str] = []
            for link_name in ('cwd', 'root', 'exe'):
                try:
                    link = _readlink(task / link_name)
                    if _inside(link, original):
                        references.append(link_name)
                except (FileNotFoundError, ProcessLookupError):
                    if not task.exists():
                        raise ProcessLookupError
                    raise
            for fd in (task / 'fd').iterdir():
                try:
                    link = _readlink(fd)
                except FileNotFoundError:
                    # A descriptor that closed during enumeration is harmless
                    # only as a *snapshot*; no future-exclusion inference.
                    continue
                if _inside(link, original):
                    references.append('fd:' + fd.name)
            for file_name in ('maps', 'mountinfo'):
                body = _proc_text(task / file_name)
                if any(_inside(field, original) for line in body.splitlines()
                       for field in line.split() if field.startswith('/')):
                    references.append(file_name)
            inspected += 1
            if references:
                hits.append({'pid': pid, 'uid': uids[0], 'references': sorted(set(references))})
        except ProcessLookupError:
            continue
        except (OSError, ValueError, StopIteration, UnicodeError, CutoverGateRefused):
            uncertain.append(pid)
    return {'inspected_processes': inspected, 'workspace_holders': hits,
            'uncertain_processes': sorted(set(uncertain)),
            'all_visible_processes_observed': not uncertain,
            'snapshot_only': True,
            'preopened_fds_revoked': False,
            'future_predecessor_relaunch_excluded': False}


def original_workspace_audit(path: Path = ORIGINAL) -> dict[str, Any]:
    """Report immutable namespace identity without traversing runtime state."""
    if path != ORIGINAL:
        _refuse('live original path cannot be changed')
    if path.is_symlink() or not path.is_dir():
        _refuse('missing or substituted live workspace')
    st = path.lstat()
    if st.st_uid != PREDECESSOR_UID or not stat.S_ISDIR(st.st_mode):
        _refuse('unexpected original checkout owner')
    # This is the known structural problem: user ownership and an executable
    # historical checkout are still available; do not call this exclusion.
    return {'original_workspace_device': st.st_dev, 'original_workspace_inode': st.st_ino,
            'original_workspace_uid': st.st_uid,
            'original_workspace_retired': False,
            'legacy_relaunch_excluded': False}


def audit_live_host() -> dict[str, Any]:
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/proc/self/status').is_file():
        _refuse('root Linux host required')
    commissioning._trusted_root(intake.ROOT)
    root = readiness.verify_published_slot(intake.ROOT, uid=0)
    staged = isolation.verify_isolated_workspace(intake.ROOT, uid=0,
             old_candidate=intake.ROOT / intake.CANDIDATE)
    artifact = installed_artifact_audit()
    original = original_workspace_audit()
    holders = scan_live_holders()
    # No success path can promote the snapshot to authority. In particular
    # clean holders + protected bytes DO NOT prove old source cannot restart.
    return {'schema': SCHEMA, 'phase': 'HOST_CUTOVER_REQUIRES_ENFORCEMENT',
            'transaction_id': root['transaction_id'],
            'approved_plan_hash': root['approved_plan_hash'],
            'current_step': root['current_step'],
            'recorded_continuations': root['recorded_continuations'],
            'historical_step_result_count': root['historical_step_result_count'],
            'root_custody_record_sha256': root['root_custody_record_sha256'],
            'isolated_manifest_record_sha256': staged['manifest_record_sha256'],
            'isolated_workspace_file_count': staged['file_count'],
            **artifact, **original, **holders,
            'legacy_controller_excluded': False,
            'successor_identity_commissioned': False,
            'execution_authority': 'NONE',
            'successor_execution_authorised': False,
            'operator_release_approved': False,
            'provider_credentials_read': False,
            'provider_executed': False,
            'original_workspace_modified': False,
            'root_custody_modified': False,
            'missing_enforcement': [
                'UNTRUSTED_ORIGINAL_HOME_NAMESPACE',
                'PREDECESSOR_RELAUNCH_PATH',
                'PREOPENED_FILE_DESCRIPTOR_REVOCATION',
                'INDEPENDENT_SUCCESSOR_SERVICE_IDENTITY',
                'CONTROLLER_EPOCH_AND_ATOMIC_ADMISSION',
                'PERSISTENT_REBOOT_AND_CRASH_DENIAL',
                'OPERATOR_RELEASE',
            ]}


def denied_report() -> dict[str, Any]:
    return {'schema': SCHEMA, 'phase': 'HOST_CUTOVER_REFUSED',
            'execution_authority': 'NONE', 'successor_execution_authorised': False,
            'provider_executed': False}
