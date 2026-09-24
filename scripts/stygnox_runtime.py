"""Standalone process, Git, and atomic JSON runtime helpers."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def run_process(
    args: list[str], *, cwd: Path, input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if env is None:
        return subprocess.run(
            args, cwd=cwd, input=input_text, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    return subprocess.run(
        args, cwd=cwd, input=input_text, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
    )


def _git(
    args: list[str], *, root: Path, check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stdout[-3000:]}")
    return proc


def git_head(*, root: Path) -> str:
    return _git(["rev-parse", "HEAD"], root=root).stdout.strip()


def git_branch(*, root: Path) -> str:
    return _git(["branch", "--show-current"], root=root).stdout.strip()


def git_upstream(*, root: Path) -> str | None:
    proc = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root=root, check=False)
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def status_sets(*, root: Path) -> tuple[list[str], list[str]]:
    proc = _git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], root=root)
    dirty: list[str] = []
    untracked: list[str] = []
    for entry in proc.stdout.split("\0"):
        if not entry:
            continue
        code = entry[:2]
        payload = entry[3:] if len(entry) >= 4 else ""
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        payload = payload.strip()
        if not payload:
            continue
        if payload not in dirty:
            dirty.append(payload)
        if code == "??" and payload not in untracked:
            untracked.append(payload)
    return sorted(dirty), sorted(untracked)


def approval_status_records(*, root: Path, normalize_path: callable) -> dict[str, str]:
    """Return current porcelain status codes keyed by their worktree paths."""
    proc = _git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], root=root)
    records: dict[str, str] = {}
    entries = proc.stdout.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:].strip()
        if path:
            records[normalize_path(path)] = code
        # In -z mode renamed/copied entries have a second, source-path field.
        if len(code) == 2 and (code[0] in {"R", "C"} or code[1] in {"R", "C"}):
            index += 1
    return records


def write_json_atomic(value: dict, *, path: Path, directory: Path | None = None) -> None:
    """Serialize JSON deterministically, then replace the destination atomically."""
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
