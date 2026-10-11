"""Hostile C2c verification of fresh-process predecessor entrypoint refusal.

A disposable private installation exercises actual controller/scheduler code;
this does not assert that the user's historical installed binary was tested.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe_c2c_legacy_execution_fence.py"
SRC = ROOT / "src" / "stygnox"


def _load_probe():
    spec = importlib.util.spec_from_file_location("c2c_execution_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class C2cExecutionFenceProbe(unittest.TestCase):
    def test_refuses_uninstalled_or_symlinked_cli(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cli = root / "bin" / "stygnox"
            cli.parent.mkdir()
            cli.write_text("stub", encoding="utf-8")
            with self.assertRaisesRegex(probe.ProbeRefused, "interpreter is missing"):
                probe.probe(cli)
            alias = root / "alias"
            alias.symlink_to(cli)
            with self.assertRaisesRegex(probe.ProbeRefused, "non-symlink"):
                probe.probe(alias)

    def test_disposable_installed_controller_scheduler_refuse_without_provider(self):
        probe = _load_probe()
        with tempfile.TemporaryDirectory(prefix="stygnox-c2c-test-") as td:
            root = Path(td)
            virtual = root / "venv"
            venv.EnvBuilder(with_pip=False, symlinks=True, system_site_packages=True).create(virtual)
            interpreter = virtual / "bin" / "python3"
            loc = subprocess.run([str(interpreter), "-I", "-c",
                                  "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                                 text=True, capture_output=True, check=True)
            package = Path(loc.stdout.strip()) / "stygnox"
            shutil.copytree(SRC, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            cli = virtual / "bin" / "stygnox"
            cli.write_text("#!" + str(interpreter) + "\n"
                           "from stygnox.cli import main\n"
                           "raise SystemExit(main())\n", encoding="utf-8")
            cli.chmod(0o755)
            evidence = probe.probe(cli)
            self.assertEqual(set(evidence["installed_entry_refusals"]), {
                "controller_preview", "controller_run", "scheduler_preview", "scheduler_run"})
            self.assertTrue(all(evidence["installed_entry_refusals"].values()))
            self.assertFalse(evidence["provider_executed"])
            self.assertTrue(evidence["plan_fixture_unchanged"])
            self.assertFalse(evidence["old_full_controller_scheduler_fenced"])
            self.assertFalse(evidence["exclusive_handoff_proved"])
            self.assertFalse(evidence["authority_changed"])
            self.assertFalse(evidence["handoff_admissible"])


if __name__ == "__main__":
    unittest.main()
