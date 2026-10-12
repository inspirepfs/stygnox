"""Behavioral C3n tests: real /proc FDs and actual source path boundaries."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'probe_c3n_live_predecessor_inventory.py'
spec = importlib.util.spec_from_file_location('c3n_inventory', SCRIPT)
c3n = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(c3n)


def test_detects_real_open_fd_even_after_unlink_of_name(tmp_path):
    old = tmp_path / 'predecessor'
    old.mkdir()
    state = old / 'open-authority-record.txt'
    state.write_text('fake only, no real controller authority')
    child = subprocess.Popen([sys.executable, '-c',
        'import os,sys,time; f=open(sys.argv[1], "rb"); print("READY",flush=True); time.sleep(15)',
        str(state)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'READY'
        state.unlink()
        report = c3n.inventory(old, tmp_path / 'not-a-real-installed-command', max(os.getuid(), 1000),
                               enforce_root=False)
        assert report['process_scan']['related_process_count'] >= 1
        found = [p for p in report['process_scan']['related_processes'] if p['pid'] == child.pid]
        assert len(found) == 1
        assert 'fd-path' in found[0]['references'] or 'fd-inode' in found[0]['references']
        assert report['unknown_predecessor_holders_excluded'] is False
        assert report['handoff_admissible'] is False
        assert report['authority_changed'] is False
    finally:
        child.terminate()
        child.communicate(timeout=5)


def test_inventory_never_grants_release_authority(tmp_path):
    old = tmp_path / 'original'
    old.mkdir()
    report = c3n.inventory(old, tmp_path / 'old-stygnox', os.getuid() or 1, enforce_root=False)
    assert report['handoff_admissible'] is False
    assert report['original_binding_retired'] is False
    assert report['successor_execution_authorised'] is False


def test_relative_path_rejected():
    with pytest.raises(ValueError):
        c3n._canonical_absolute('relative/path')
    with pytest.raises(ValueError):
        c3n._canonical_absolute('/tmp/../etc')


def test_nonroot_cannot_claim_complete_scan(tmp_path, monkeypatch):
    old = tmp_path / 'original'
    old.mkdir()
    monkeypatch.setattr(c3n.os, 'geteuid', lambda: 1000)
    with pytest.raises(PermissionError):
        c3n.inventory(old, tmp_path / 'old-stygnox', 1000, enforce_root=True)


def test_inode_catalog_never_traverses_symlinks(tmp_path):
    old = tmp_path / 'original'
    old.mkdir()
    (old / 'link').symlink_to(tmp_path)
    keys, evidence = c3n._inode_catalog(old)
    assert evidence['symlinks_skipped'] == 1
    assert evidence['entries_seen'] == 1
    assert len(keys) == 1


def test_installed_executable_hash_pinned_without_exec(tmp_path):
    installed = tmp_path / 'old-bin'
    installed.write_bytes(b'#!/bin/sh\nexit 1\n')
    import hashlib
    expected = hashlib.sha256(installed.read_bytes()).hexdigest()
    evidence = c3n._read_executable_hash(installed)
    assert evidence['sha256'] == expected
    assert evidence['available'] is True
    installed.unlink()
    installed.symlink_to('/bin/sh')
    assert c3n._read_executable_hash(installed)['available'] is False
