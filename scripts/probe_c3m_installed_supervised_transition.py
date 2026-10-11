#!/usr/bin/env python3
"""C3m disposable Linux installed-successor + root-supervised blocked transition.

Never accepts a project root, controller state or old binary from the operator.
Keeps protected authority fixtures under /run and installs the inert wheel
into a separately root-owned, executable /tmp fixture. The synthetic
predecessor is NOT the actual legacy StygNox binary: a known child is drained,
not arbitrary pre-existing holders. This evidence cannot admit a live handoff.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import select
import stat
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import venv

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_transfer as transfer
from stygnox import direct_interruption_quarantine as quarantine
from stygnox.direct_interruption_fence import SUCCESSOR_STATUS
from stygnox.direct_interruption_supervisor import publish_blocked_namespace

SCHEMA = 'stygnox_c3m_disposable_installed_supervised_transition_v1'
_WRITER = r'''
import os,sys,time
fd=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC)
print('READY',flush=True)
while True:
    os.write(fd,b'x')
    os.fsync(fd)
    time.sleep(0.02)
'''
_IDENTITY = r'''
import json,sys
from pathlib import Path
from stygnox import lifecycle
installed=lifecycle._installed_identity(Path(sys.argv[1]))
wheel=lifecycle._wheel_identity(Path(sys.argv[2]),installed)
print(json.dumps({'installed':installed,'wheel':wheel},sort_keys=True))
'''
_DENY = r'''
import json,sys
from pathlib import Path
old,vault,published = (Path(x) for x in sys.argv[1:4])
result={}
for name,path in [('original',old),('retired',vault),('published',published)]:
    try:
        (path/'.stygnox'/'legacy-reentry.json').write_text('FORBIDDEN')
    except (OSError,PermissionError):
        result[name]=True
    else:
        result[name]=False
print(json.dumps(result))
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seal(record: dict, key: str) -> dict:
    result = dict(record)
    result[key] = recovery._digest(result)
    return result


def _drop(uid: int):
    def apply():
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
    return apply


def _run(args: list[str], *, cwd: Path, env: dict[str, str], uid: int | None = None,
         timeout: int = 60, success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                            preexec_fn=_drop(uid) if uid is not None else None,
                            timeout=timeout)
    if success and result.returncode:
        raise RuntimeError(f'child failed: {args[0]} (rc={result.returncode}): {result.stderr[-1500:]}')
    return result


def _unused_uid(legacy: int) -> int:
    for uid in range(61001, 62000):
        if uid == legacy:
            continue
        try:
            pwd.getpwuid(uid)
        except KeyError:
            return uid
    raise RuntimeError('no available disposable UID')


def _write_record(worktree: Path, uid: int, name: str, record: dict) -> None:
    path = worktree / '.stygnox' / name
    path.write_text(json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n')
    path.chmod(0o600)
    os.chown(path, uid, uid)


def _runtime(worktree: Path, uid: int, records: dict[str, dict]) -> None:
    worktree.mkdir(mode=0o700)
    runtime = worktree / '.stygnox'
    runtime.mkdir(mode=0o700)
    for name, record in records.items():
        _write_record(worktree, uid, name, record)
    os.chown(runtime, uid, uid)
    os.chown(worktree, uid, uid)


def _evidence(*, predecessor: Path, installed: dict, wheel_id: dict) -> tuple[dict, dict, dict, dict, dict, dict]:
    old_path = str(predecessor)
    tx = _seal({'schema': 'stygnox_transaction_v1', 'transaction_id': 'TX-c3m-disposable',
                'state': 'ACTIVE', 'installed_command': old_path}, 'record_sha256')
    controller = _seal({'schema': 'stygnox_controller_state_v1', 'transaction_id': 'TX-c3m-disposable',
                        'enabled': True, 'installed_command': old_path}, 'record_sha256')
    plan = _seal({
        'schema': 'stygnox_plan_state_v1', 'status': 'APPROVED',
        'execution_authority_granted': True, 'plan_hash': '1'*64,
        'transaction_id': tx['transaction_id'], 'operator': 'c3m-fixture', 'current_step': 2,
        'controller_record_sha256': controller['record_sha256'],
        'transaction_record_sha256': tx['record_sha256'], 'active_gate': None,
        'self_development_grant': None, 'direct_interruption_pending': None,
        'direct_interruption_recoveries': [],
        'repository_mutation_scope': ['src/stygnox/planning.py'],
        'continuation_history': [{'accepted': 'synthetic-fixture'}],
    }, 'record_sha256')
    admission = _seal({
        'schema': 'stygnox_direct_interruption_successor_admission_preflight_v1',
        'admissible': False, 'authority_changed': False,
        'successor_execution_admission': 'DISABLED',
        'exclusive_transfer_publication': 'NOT_IMPLEMENTED',
        'proposed_successor_only_plan_status': SUCCESSOR_STATUS,
        'proposed_legacy_execution_authority_granted': False,
        'predecessor_plan_record_sha256': plan['record_sha256'],
        'predecessor_controller_record_sha256': controller['record_sha256'],
        'predecessor_transaction_record_sha256': tx['record_sha256'],
        'plan_hash': plan['plan_hash'], 'transaction_id': plan['transaction_id'],
        'operator': plan['operator'], 'current_step': plan['current_step'],
        'handoff_preview_sha256': '5'*64, 'fence_design_sha256': '6'*64,
        'review_preview_sha256': '7'*64, 'manifest_proof_sha256': '8'*64,
        'predecessor_installed_executable': {'path': old_path, 'sha256': _sha(predecessor)},
        'successor_installed_identity': installed, 'successor_wheel_identity': wheel_id,
    }, 'preview_sha256')
    proposal = transfer.build_fence_publication_preview(admission, plan)
    journal = publication.build_journal_preview(proposal)
    return plan, controller, tx, admission, proposal, journal


def _drain_known_child(child: subprocess.Popen, *, marker: Path) -> dict:
    """Pidfd-directed drain of a fixture child; not an unknown-holder census."""
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Linux pidfd signal support required')
    pidfd = os.pidfd_open(child.pid, 0)
    try:
        signal.pidfd_send_signal(pidfd, signal.SIGTERM, None, 0)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('known predecessor child did not drain') from exc
        stopped = marker.stat().st_size
        time.sleep(0.08)
        stable = child.poll() is not None and marker.stat().st_size == stopped
        if not stable:
            raise RuntimeError('predecessor open descriptor remained writable after drain')
        return {'known_child_pidfd_drained': True, 'known_child_fd_stable': True}
    finally:
        os.close(pidfd)


def _snapshot(runtime: Path) -> dict[str, str]:
    return {p.name: _sha(p) for p in sorted(runtime.iterdir()) if p.is_file()}


def _verify_candidate_launcher(python: Path, cli: Path, cwd: Path,
                               env: dict[str, str], successor_uid: int) -> None:
    """Require real launcher discovery and execution as the distinct UID."""
    discover = _run([str(python), '-I', '-c',
                     'import shutil; print(shutil.which("stygnox") or "")'],
                    cwd=cwd, env=env, uid=successor_uid)
    if discover.stdout.strip() != str(cli):
        raise RuntimeError('installed Stygnox command unavailable to successor UID '
                           'on disposable executable path')
    _run([str(cli), '--version'], cwd=cwd, env=env, uid=successor_uid)


def qualify(wheel: Path, legacy_uid: int) -> dict:
    if os.name != 'posix' or os.geteuid() != 0 or not Path('/run').is_dir():
        raise RuntimeError('disposable C3m requires root on Linux with /run')
    if legacy_uid <= 0 or legacy_uid == 0:
        raise RuntimeError('distinct non-root legacy UID required')
    pwd.getpwuid(legacy_uid)
    wheel = Path(wheel).absolute()
    if wheel.is_symlink() or not wheel.is_file() or wheel.suffix != '.whl':
        raise RuntimeError('wheel must be an existing non-symlink regular .whl')
    wheel_before = _sha(wheel)
    successor_uid = _unused_uid(legacy_uid)
    # /run is frequently mounted noexec on hardened hosts. Keep all authority
    # fixtures in /run but install ONLY the inert candidate executable under
    # root-owned /tmp, where cross-UID execution can be verified independently.
    # Neither the runtime nor a caller-supplied worktree can be placed there.
    exec_parent = Path('/tmp')
    parent_stat = exec_parent.lstat()
    if (not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != 0 or
            not parent_stat.st_mode & stat.S_ISVTX):
        raise RuntimeError('C3m requires a root-owned sticky /tmp for disposable executable')
    if os.statvfs(exec_parent).f_flag & os.ST_NOEXEC:
        raise RuntimeError('C3m requires an executable /tmp for the isolated wheel; /tmp is noexec')
    with (tempfile.TemporaryDirectory(prefix='stygnox-c3m-', dir='/run') as tmp,
          tempfile.TemporaryDirectory(prefix='stygnox-c3m-exec-', dir='/tmp') as exec_tmp):
        base = Path(tmp)
        base.chmod(0o755)
        exec_root = Path(exec_tmp)
        exec_root.chmod(0o755)  # traversal for distinct successor UID, root still owns writes
        # Only an inert local copy enters the temporary supervisor namespace.
        candidate = base / wheel.name
        candidate.write_bytes(wheel.read_bytes())
        candidate.chmod(0o644)
        if _sha(candidate) != wheel_before:
            raise RuntimeError('candidate wheel copy changed')
        venv_dir = exec_root / 'candidate-venv'
        # sudo may inherit a restrictive umask (e.g. 077).  The successor UID
        # must traverse the root-owned installed venv and execute its launcher,
        # but must never be granted write access to it.  Limit the 022 umask
        # strictly to constructing the inert candidate installation; restore
        # the caller's umask BEFORE preparing private runtime authorities.
        previous_umask = os.umask(0o022)
        try:
            venv.EnvBuilder(with_pip=True, symlinks=True).create(venv_dir)
            python = venv_dir / 'bin' / 'python'
            cli = venv_dir / 'bin' / 'stygnox'
            env = {**os.environ, 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PIP_NO_INDEX': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                   'HOME': str(base), 'PATH': f'{venv_dir / "bin"}:/usr/bin:/bin'}
            env.pop('PYTHONPATH', None)
            env.pop('PYTHONHOME', None)
            _run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(candidate)],
                 cwd=base, env=env)
        finally:
            os.umask(previous_umask)
        if cli.is_symlink() or not cli.is_file():
            raise RuntimeError('installed successor launcher is not a regular file')
        # Fail here with an actionable filesystem diagnosis, rather than later
        # misreporting a PATH-resolution failure as an identity mismatch.
        _verify_candidate_launcher(python, cli, base, env, successor_uid)
        cli_before = _sha(cli)
        active, vault, staging, publish = [base / name for name in ('active','vault','stage','publish')]
        for path, mode in ((active, 0o711), (vault, 0o700), (staging, 0o700), (publish, 0o711)):
            path.mkdir(mode=mode)
            # mkdir(mode=...) is filtered by the root process umask.  These
            # exact modes are the fixture's cross-UID boundary: traverse-only
            # on active/publish, no legacy traversal of vault/stage.
            path.chmod(mode)
        old, retired = active / 'old', vault / 'retired'
        staged, published = staging / 'successor', publish / 'successor'
        legacy_dir = base / 'legacy-bin'
        legacy_dir.mkdir(mode=0o755)
        legacy_dir.chmod(0o755)
        legacy = legacy_dir / 'stygnox'
        legacy.write_text('#!/bin/sh\necho "synthetic predecessor; execution prohibited" >&2\nexit 70\n')
        legacy.chmod(0o755)
        observed = _run([str(python), '-I', '-c', _IDENTITY, str(published), str(candidate)],
                        cwd=base, env=env, uid=successor_uid)
        identity = json.loads(observed.stdout)
        installed, wheel_id = identity['installed'], identity['wheel']
        if installed['executable'] != str(cli) or wheel_id['sha256'] != wheel_before:
            raise RuntimeError('fresh installed successor identity/wheel mismatch')
        plan, ctrl, tx, admission, proposal, journal = _evidence(
            predecessor=legacy, installed=installed, wheel_id=wheel_id)
        for target, owner in ((old, legacy_uid), (staged, successor_uid)):
            _runtime(target, owner, {'plan.json': plan, 'controller.json': ctrl, 'transaction.json': tx})
            # A real controller CLI needs an actual Git worktree; keep it in
            # the same unpublished disposable namespace.
            _run(['git', 'init', '-q', str(target)], cwd=base, env=env)
            # The C3e private-tree verifier prohibits mixed-owner objects,
            # symlinks, group-readable files and non-0700 directories.
            for git_item in sorted((target / '.git').rglob('*'), reverse=True):
                if git_item.is_symlink() or not (git_item.is_dir() or git_item.is_file()):
                    raise RuntimeError('unsupported Git metadata entry in disposable fixture')
                os.chown(git_item, owner, owner)
                git_item.chmod(0o700 if git_item.is_dir() else 0o600)
            (target / '.git').chmod(0o700)
            os.chown(target / '.git', owner, owner)
        # Give the known, non-cooperating predecessor an open writable FD to an
        # untrusted data file. pidfd drain precedes the irreversible rename.
        marker = old / 'legacy-holder.dat'
        marker.write_bytes(b'')
        marker.chmod(0o600)
        os.chown(marker, legacy_uid, legacy_uid)
        holder = subprocess.Popen([sys.executable, '-c', _WRITER, str(marker)], cwd=base,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, preexec_fn=_drop(legacy_uid))
        try:
            ready, _, _ = select.select([holder.stdout], [], [], 5)
            if not ready or holder.stdout.readline().strip() != 'READY':
                raise RuntimeError('fixture predecessor did not open writable descriptor')
            drained = _drain_known_child(holder, marker=marker)
            before = old.stat()
            stage_stat = staged.stat()
            publication_record = publish_blocked_namespace(
                original=old, retired=retired, staged=staged, published=published,
                predecessor_uid=legacy_uid, successor_uid=successor_uid,
                predecessor_identity=(before.st_dev, before.st_ino),
                staged_identity=(stage_stat.st_dev, stage_stat.st_ino),
                transfer_preview=proposal, journal_preview=journal)
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait(timeout=5)
            if holder.stdout:
                holder.stdout.close()
            if holder.stderr:
                holder.stderr.close()
        admission_path, proposal_path = base / 'admission.json', base / 'proposal.json'
        for path, value in ((admission_path, admission), (proposal_path, proposal)):
            path.write_text(json.dumps(value, sort_keys=True))
            path.chmod(0o644)
        inspect_cmd = [str(cli), 'direct-interruption', 'inspect-blocked-successor',
                       '--project', str(published), '--predecessor-uid', str(legacy_uid),
                       '--admission-evidence', str(admission_path),
                       '--transfer-evidence', str(proposal_path),
                       '--candidate-wheel', str(candidate)]
        inspected = _run(inspect_cmd, cwd=base, env=env, uid=successor_uid)
        result = json.loads(inspected.stdout)
        if not (result['installed_successor_identity_verified'] is True
                and result['exact_blocked_lineage'] is True
                and result['quarantined_controller_transaction_records'] is True
                and result['predecessor_executable_rechecked'] is True
                and result['original_path_absence_visible_to_successor'] is True
                and result['successor_execution_authorised'] is False
                and result['handoff_admissible'] is False):
            raise RuntimeError('installed inspector did not attest exact blocked lineage')
        runtime = published / '.stygnox'
        original_state = _snapshot(runtime)
        # Reuse installed CLI entrypoints against the exact C3j record pair.
        cases = {
            'controller-activate': ['controller', 'activate', '--project', str(published), '--operator', 'Probe', '--confirm', 'ACTIVATE'],
            'controller-run': ['controller', 'run', '--project', str(published), '--operator', 'Probe', '--objective', 'refuse', '--repository-authority', 'write', '--preview', 'a'*64, '--confirm', 'RUN'],
            'scheduler-run': ['scheduler', 'run', '--project', str(published), '--operator', 'Probe', '--preview', 'b'*64, '--confirm', 'SCHEDULE'],
            'scheduler-recover': ['scheduler', 'recover', '--project', str(published), '--operator', 'Probe', '--preview', 'c'*64, '--confirm', 'RECOVER'],
        }
        for name, params in cases.items():
            refused = _run([str(cli), *params], cwd=base, env=env, uid=successor_uid, success=False)
            if refused.returncode == 0 or 'RECOVERY_QUARANTINED' not in refused.stderr:
                raise RuntimeError(f'{name} failed to refuse quarantine: {refused.stderr[-1000:]}')
            if _snapshot(runtime) != original_state:
                raise RuntimeError(f'{name} changed quarantined authority files')
        denied = _run([str(python), '-c', _DENY, str(old), str(retired), str(published)],
                      cwd=base, env=env, uid=legacy_uid)
        if set(json.loads(denied.stdout).values()) != {True}:
            raise RuntimeError('legacy UID could write a withdrawn/protected path')
        if _snapshot(runtime) != original_state:
            raise RuntimeError('installed probe changed successor runtime')
        # Hostile installed artifact/entrypoint mismatches must fail without
        # rewriting the fixture or issuing an execution receipt.
        different_wheel = base / ('different-' + candidate.name)
        different_wheel.write_bytes(candidate.read_bytes() + b'\nSUBSTITUTED\n')
        different_wheel.chmod(0o644)
        bad_wheel = inspect_cmd.copy()
        bad_wheel[-1] = str(different_wheel)
        invalid_wheel = _run(bad_wheel, cwd=base, env=env, uid=successor_uid, success=False)
        if invalid_wheel.returncode == 0:
            raise RuntimeError('substituted candidate wheel was accepted')
        other_launcher = venv_dir / 'bin' / 'stygnox-other'
        shutil.copyfile(cli, other_launcher)
        other_launcher.chmod(0o755)
        swapped = [str(other_launcher), *inspect_cmd[1:]]
        invalid_launcher = _run(swapped, cwd=base, env=env, uid=successor_uid, success=False)
        if invalid_launcher.returncode == 0:
            raise RuntimeError('substituted command invocation was accepted')
        if (_snapshot(runtime) != original_state or _sha(candidate) != wheel_before or
                _sha(cli) != cli_before or _sha(wheel) != wheel_before):
            raise RuntimeError('installed artifact or blocked runtime changed during qualification')
        return {
            'schema': SCHEMA,
            'fixture_type': 'root_private_run_namespace_distinct_uid_real_installed_wheel',
            'predecessor_uid': legacy_uid, 'successor_uid': successor_uid,
            'wheel_sha256': wheel_before, 'installed_command_sha256': cli_before,
            'installed_record_sha256': installed['record_sha256'],
            'installed_package_manifest_sha256': installed['record_manifest_sha256'],
            'exact_quarantine_lineage': True,
            'installed_successor_executable_binding_verified': True,
            'known_predecessor_pidfd_drained': drained['known_child_pidfd_drained'],
            'known_predecessor_fd_stable': drained['known_child_fd_stable'],
            'root_retired_predecessor_fixture': publication_record['predecessor_retired'],
            'legacy_uid_write_denied': True,
            'quarantined_controller_and_transaction': True,
            'installed_runtime_entry_refusals': sorted(cases),
            'substituted_wheel_refused': True,
            'substituted_launcher_refused': True,
            'runtime_fixture_unchanged_after_checks': True,
            'provider_executed': False,
            'live_runtime_modified': False,
            'unknown_predecessor_holders_excluded': False,
            'real_predecessor_exclusion_proved': False,
            'live_original_worktree_root_controlled': False,
            'original_binding_retired': False,
            'authority_changed': False,
            'successor_execution_authorised': False,
            'handoff_admissible': False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true', required=True)
    parser.add_argument('--legacy-uid', type=int, required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(qualify(args.wheel, args.legacy_uid), indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired,
            json.JSONDecodeError, PermissionError) as exc:
        print(f'C3m installed supervised probe REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
