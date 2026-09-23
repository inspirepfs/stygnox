from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "stygnox_project_root.py"
spec = importlib.util.spec_from_file_location("stygnox_project_root", MODULE_PATH)
project_root = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = project_root
spec.loader.exec_module(project_root)


class ProjectRootResolverTests(unittest.TestCase):
    def make_repository(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)

    def test_accepts_absolute_relative_home_and_canonical_symlink_paths(self):
        with TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"HOME": temporary}):
            base = Path(temporary)
            repository = base / "repository"
            repository.mkdir()
            self.make_repository(repository)
            symlink = base / "alias"
            try:
                symlink.symlink_to(repository, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks are unavailable: {error}")

            self.assertEqual(repository.resolve(), project_root.resolve_project_root(repository))
            with mock.patch.object(project_root.Path, "cwd", return_value=base):
                self.assertEqual(repository.resolve(), project_root.resolve_project_root("repository"))
            self.assertEqual(repository.resolve(), project_root.resolve_project_root("~/repository"))
            self.assertEqual(repository.resolve(), project_root.resolve_project_root(symlink))

    def test_rejects_empty_malformed_missing_and_file_inputs(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            file_path = base / "file"
            file_path.write_text("not a directory", encoding="utf-8")
            for value, message in (("", "must not be empty"), ("bad\x00path", "invalid NUL"), (base / "missing", "does not exist"), (file_path, "must be a directory")):
                with self.subTest(value=str(value)):
                    with self.assertRaisesRegex(project_root.ProjectRootError, message):
                        project_root.resolve_project_root(value)

    def test_rejects_non_git_and_nested_worktree_subdirectories(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            non_git = base / "non-git"
            non_git.mkdir()
            with self.assertRaisesRegex(project_root.ProjectRootError, "not a usable Git worktree"):
                project_root.resolve_project_root(non_git)

            repository = base / "repository"
            nested = repository / "nested"
            nested.mkdir(parents=True)
            self.make_repository(repository)
            with self.assertRaisesRegex(project_root.ProjectRootError, "not a nested directory"):
                project_root.resolve_project_root(nested)

    def test_reports_git_execution_and_nonzero_failures(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with mock.patch.object(project_root.subprocess, "run", side_effect=OSError("Git unavailable")):
                with self.assertRaisesRegex(project_root.ProjectRootError, "Could not execute Git"):
                    project_root.resolve_project_root(directory)

            failed = subprocess.CompletedProcess([], 7, stdout="", stderr="permission denied")
            with mock.patch.object(project_root.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(project_root.ProjectRootError, "exited 7: permission denied"):
                    project_root.resolve_project_root(directory)


if __name__ == "__main__":
    unittest.main()
