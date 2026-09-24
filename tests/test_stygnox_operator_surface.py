"""D8.6A presentation-neutral operator/reconciliation characterization tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import adoption, operator  # noqa: E402


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "D8.6A Operator Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "baseline")


class StygnoxOperatorSurfaceTests(TestCase):
    def test_write_turn_attribution_never_reattributes_preexisting_dirty_paths(self) -> None:
        before = {
            "status": " M operator.txt\n?? baseline-note.txt\n",
            "untracked": [{"path": "baseline-note.txt"}],
        }
        after = {
            "status": " M operator.txt\n?? baseline-note.txt\n?? native.txt\n",
            "untracked": [{"path": "baseline-note.txt"}, {"path": "native.txt"}],
        }
        value = operator.status_attribution(before, after)
        self.assertEqual(["native.txt"], value["controller_native_paths"])
        self.assertIn("operator.txt", value["overlap_unresolved_paths"])
        self.assertIn("baseline-note.txt", value["overlap_unresolved_paths"])
        self.assertNotIn("operator.txt", value["controller_native_paths"])

    def test_snapshot_separates_operator_native_runtime_external_and_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            init_repo(repo)
            (repo / "operator.txt").write_text("operator\n", encoding="utf-8")
            baseline = adoption.capture_baseline(repo).public()
            (repo / "stygnox.toml").write_text("tracked authority\n", encoding="utf-8")
            runtime = repo / adoption.RUNTIME_NAME
            runtime.mkdir()
            handoff = {
                "schema": adoption.HANDOFF_SCHEMA,
                "operator": "Operator One",
                "baseline": baseline,
                "tracked_review": [{"path": "stygnox.toml", "action": "create"}],
            }
            (runtime / "adoption.json").write_text(json.dumps(handoff), encoding="utf-8")
            receipt = {
                "schema": "stygnox_controller_run_result_v1",
                "record_sha256": "a" * 64,
                "preview_sha256": "b" * 64,
                "repository_authority": "write",
                "change_attribution": {
                    "controller_native_paths": ["native.txt"],
                    "operator_baseline_paths": ["operator.txt"],
                    "overlap_unresolved_paths": ["operator.txt"],
                    "removed_preexisting_paths": [],
                },
            }
            (runtime / "controller-run-bbbbbbbbbbbbbbbb.json").write_text(json.dumps(receipt), encoding="utf-8")
            (repo / "native.txt").write_text("native\n", encoding="utf-8")
            (repo / "foreign.txt").write_text("foreign\n", encoding="utf-8")

            value = operator.classify_changes(repo)
            cats = value["categories"]
            self.assertIn("native.txt", cats["controller_native"]["paths"])
            self.assertIn("foreign.txt", cats["external"]["paths"])
            self.assertIn("operator.txt", cats["unresolved"]["paths"])
            self.assertTrue(any(path.startswith(".stygnox/") for path in cats["runtime_only"]["paths"]))
            self.assertFalse(value["auto_adopt"])
            self.assertFalse(value["auto_reattribute"])
            self.assertTrue(value["requires_human_decision"])

    def test_dispatch_refuses_unknown_action_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            before = adoption.capture_baseline(repo).public()["sha256"]
            with self.assertRaisesRegex(operator.OperatorSurfaceError, "unsupported installed operator action"):
                operator.dispatch_action(repo, "legacy.ralph.run", {})
            after = adoption.capture_baseline(repo).public()["sha256"]
            self.assertEqual(before, after)
            self.assertFalse((repo / adoption.RUNTIME_NAME).exists())

    def test_operator_snapshot_is_neutral_before_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            value = operator.operator_snapshot(repo, server_pid=1234)
            self.assertEqual("stygnox_operator_surface_v1", value["schema"])
            self.assertEqual("Stygnox", value["identity"])
            self.assertFalse(value["adopted"])
            self.assertIsNone(value["operator"])
            self.assertEqual(1234, value["server"]["pid"])
            self.assertFalse(value["evidence_summary"]["source_tree_dependency"])
            self.assertFalse(value["evidence_summary"]["legacy_ralph_delegate"])


if __name__ == "__main__":
    import unittest
    unittest.main()
