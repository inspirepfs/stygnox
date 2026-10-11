#!/usr/bin/env python3
"""C3l: independently installed wheel quarantine refusal (disposable only).

No authority publication, installed rebind, operator release or production process drain.
Build the candidate wheel from the exact committed source separately; this tool
checks the wheel's actual installed command and package in a fresh environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


CHECK_INSTALLED = r'''
import base64, csv, hashlib, importlib.metadata, json, pathlib, sys
import stygnox
root = pathlib.Path(sys.prefix).resolve()
package = pathlib.Path(stygnox.__file__).resolve()
if not package.is_relative_to(root):
    raise SystemExit('installed package escaped candidate virtualenv')
dist = importlib.metadata.distribution('stygnox')
record = dist.read_text('RECORD')
if not record:
    raise SystemExit('installed RECORD is absent')
verified = 0
package_verified = 0
for name, digest, size in csv.reader(record.splitlines()):
    if not name or not digest:
        continue
    kind, token = digest.split('=', 1)
    if kind != 'sha256':
        raise SystemExit('unsupported RECORD digest: ' + kind)
    path = pathlib.Path(dist.locate_file(name)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise SystemExit('RECORD path is outside the install or missing: ' + name)
    expected = base64.urlsafe_b64decode(token + '=' * (-len(token) % 4))
    if hashlib.sha256(path.read_bytes()).digest() != expected:
        raise SystemExit('installed RECORD hash mismatch: ' + name)
    verified += 1
    if 'stygnox/' in str(name).replace('\\', '/'):
        package_verified += 1
if package_verified < 20:
    raise SystemExit('insufficient hashed package files')
print(json.dumps({'package': str(package), 'installed_record_hashes_verified': verified,
                  'package_hashes_verified': package_verified, 'venv_prefix': str(root)}, sort_keys=True))
'''


def run(args: list[str], *, cwd: Path, env: dict[str, str], check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(f'{args[0]} exited {result.returncode}: {result.stderr[-2000:]}')
    return result


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    return {str(file.relative_to(root)): sha(file) for file in sorted(root.rglob('*')) if file.is_file()}


def qualify(wheel: Path) -> dict[str, object]:
    wheel = wheel.absolute()
    if wheel.is_symlink() or not wheel.is_file() or not wheel.name.endswith('.whl'):
        raise RuntimeError('wheel must be one existing regular non-symlink wheel')
    wheel_hash_before = sha(wheel)
    with tempfile.TemporaryDirectory(prefix='stygnox-c3l-installed-') as work:
        root = Path(work)
        venv_dir = root / 'candidate-venv'
        venv.EnvBuilder(with_pip=True, symlinks=True).create(venv_dir)
        python = venv_dir / 'bin' / 'python'
        cli = venv_dir / 'bin' / 'stygnox'
        env = {**os.environ, 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'PIP_NO_INDEX': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
               'HOME': str(root), 'PATH': f'{venv_dir / "bin"}:/usr/bin:/bin'}
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], cwd=root, env=env, check=True)
        if cli.is_symlink() or not cli.is_file():
            raise RuntimeError('installed command must be a regular executable')
        cmd_sha = sha(cli)
        identity = run([str(python), '-I', '-c', CHECK_INSTALLED], cwd=root, env=env, check=True)
        installed = json.loads(identity.stdout)
        version = run([str(cli), '--version'], cwd=root, env=env, check=True).stdout.strip()
        project = root / 'fixture'
        project.mkdir()
        run(['git', 'init', '-q', str(project)], cwd=root, env=env, check=True)
        runtime = project / '.stygnox'
        runtime.mkdir()
        marker = runtime / 'direct-interruption-quarantined-binding.json'
        marker.write_text('{"quarantine":"intentionally malformed; must still block"}\n', encoding='utf-8')
        before = snapshot(project)
        cases = {
            'controller-activate': ['controller', 'activate', '--project', str(project), '--operator', 'Probe', '--confirm', 'ACTIVATE'],
            'controller-run-preview': ['controller', 'run-preview', '--project', str(project), '--operator', 'Probe', '--objective', 'must refuse', '--repository-authority', 'write'],
            'controller-run': ['controller', 'run', '--project', str(project), '--operator', 'Probe', '--objective', 'must refuse', '--repository-authority', 'write', '--preview', 'a'*64, '--confirm', 'RUN'],
            'scheduler-run-preview': ['scheduler', 'run-preview', '--project', str(project), '--operator', 'Probe'],
            'scheduler-run': ['scheduler', 'run', '--project', str(project), '--operator', 'Probe', '--preview', 'b'*64, '--confirm', 'SCHEDULE'],
            'scheduler-recover-preview': ['scheduler', 'recover-preview', '--project', str(project), '--operator', 'Probe'],
            'scheduler-recover': ['scheduler', 'recover', '--project', str(project), '--operator', 'Probe', '--preview', 'c'*64, '--confirm', 'RECOVER'],
        }
        refusals: dict[str, bool] = {}
        for name, args in cases.items():
            outcome = run([str(cli), *args], cwd=root, env=env)
            refused = outcome.returncode != 0 and 'RECOVERY_QUARANTINED' in outcome.stderr
            refusals[name] = refused
            if not refused:
                raise RuntimeError(f'{name}: missing explicit quarantine refusal; rc={outcome.returncode}, stderr={outcome.stderr[-1000:]}')
            if snapshot(project) != before:
                raise RuntimeError(f'{name}: quarantined fixture mutated')
        if sha(wheel) != wheel_hash_before or sha(cli) != cmd_sha:
            raise RuntimeError('wheel or installed command changed during qualification')
        return {
            'schema': 'stygnox_c3l_fresh_installed_quarantine_v1',
            'fixture_type': 'isolated_venv_and_disposable_git_worktree',
            'wheel_sha256': wheel_hash_before,
            'installed_cli_sha256': cmd_sha,
            'installed_package': installed,
            'installed_version': version,
            'installed_entry_refusals': refusals,
            'all_installed_entry_refusals': all(refusals.values()),
            'fixture_unchanged': snapshot(project) == before,
            'provider_executed': False,
            'authority_changed': False,
            'live_runtime_modified': False,
            'predecessor_exclusion_proved': False,
            'successor_executable_binding_verified': False,
            'handoff_admissible': False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = qualify(args.wheel)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'C3l installed quarantine probe REFUSED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
