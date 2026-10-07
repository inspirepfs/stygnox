"""Black-box coverage for the R3D.1 exact installed-successor qualifier."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build_d8_7_release.py"
QUALIFIER = ROOT / "scripts" / "qualify_r3d_1_installed_successor.py"


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    return environment


class InstalledSuccessorQualificationTests(unittest.TestCase):
    def build_wheel(self, directory: Path) -> Path:
        result = subprocess.run(
            [sys.executable, str(BUILD), "--output-dir", str(directory)],
            cwd=ROOT,
            env=clean_environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        wheels = list(directory.glob("stygnox-*.whl"))
        self.assertEqual(1, len(wheels))
        return wheels[0]

    def test_exact_wheel_report_proves_successor_and_hostile_refusals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-r3d1-test-") as temporary:
            wheel = self.build_wheel(Path(temporary) / "release")
            wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
            result = subprocess.run(
                [sys.executable, str(QUALIFIER), "--wheel", str(wheel)],
                cwd=ROOT,
                env=clean_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)
            report = json.loads(result.stdout)

        self.assertEqual("stygnox_r3d_1_installed_successor_qualification_v1", report["schema"])
        self.assertEqual(wheel_sha256, report["wheel_sha256"])
        successor = report["installed_successor"]
        self.assertEqual("PASS", successor["result"])
        self.assertTrue(Path(successor["canonical_worktree"]).is_absolute())
        self.assertEqual(wheel_sha256, successor["wheel"]["sha256"])
        installed = successor["installed_identity"]
        for field in ("distribution_name", "package_file", "package_sha256", "record", "record_sha256", "executable"):
            self.assertTrue(installed[field])
        for field in (
            "plan_scope_provenance_checkpoint_lineage",
            "transaction",
            "controller",
            "runtime_epoch",
            "bootstrap_disposition",
            "successor_receipt_sha256",
        ):
            self.assertTrue(successor[field])
        self.assertFalse(successor["source_tree_fallback"])
        self.assertFalse(successor["ralph_fallback"])
        self.assertEqual("OPERATOR_ADOPTION_MATERIAL", successor["bootstrap_disposition"]["disposition"])
        self.assertEqual("EXCLUDED", successor["bootstrap_disposition"]["provider_attribution"])
        expected_hostile = {
            "pythonpath_ralph_decoy",
            "copied_launcher",
            "source_tree_substitution",
            "stale_or_substituted_artifact",
            "failing_handoff",
        }
        self.assertEqual(expected_hostile, set(report["hostile_cases"]))
        for refusal in report["hostile_cases"].values():
            self.assertEqual("REFUSED_PREDECESSOR_RETAINED", refusal["result"])
            self.assertNotEqual(0, refusal["returncode"])
        self.assertEqual({"provider_owned": False, "executable_authority": False}, report["cap_011"])

    def test_non_wheel_input_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-r3d1-test-") as temporary:
            not_a_wheel = Path(temporary) / "substituted.txt"
            not_a_wheel.write_text("not a wheel\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(QUALIFIER), "--wheel", str(not_a_wheel)],
                cwd=ROOT,
                env=clean_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("qualification requires one regular Stygnox wheel", result.stderr)


if __name__ == "__main__":
    unittest.main()
