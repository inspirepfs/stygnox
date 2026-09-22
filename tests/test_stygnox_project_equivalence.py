from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts import stygnox_project_equivalence as equivalence


class StygnoxProjectEquivalenceTests(unittest.TestCase):
    def test_profile_facade_and_adapter_are_equivalent(self):
        report = equivalence.report()
        self.assertEqual("4f5fb11", report["baseline_metadata"])
        self.assertEqual([], report["differences"])
        self.assertEqual({"class": True, "project_singleton": True, "zen_singleton": True}, report["aliases"])
        frozen = report["facade"]["frozen_dataclass"]
        self.assertTrue(frozen["frozen"])
        self.assertTrue(frozen["replace"]["preserves_class"])
        self.assertEqual(".ralph", frozen["replace"]["original_runtime"])
        self.assertEqual(".replacement", frozen["replace"]["replacement_runtime"])
        self.assertEqual(".ralph/recovery/checkpoint-1/manifest.json", report["facade"]["runtime_artifacts_recovery_policy"]["recovery"])
        self.assertEqual("scripts/ralph.py", report["facade"]["git_controller_metadata"]["controller"])

    def test_canonical_encoding_is_json_safe_sorted_and_root_relative(self):
        root = Path("/synthetic/root")
        encoded = equivalence.canonical({"set": frozenset({"z", "a"}), "path": root / "app" / "main.py", "tuple": (1, 2)}, root=root)
        self.assertEqual({"path": "app/main.py", "set": ["a", "z"], "tuple": [1, 2]}, encoded)
        self.assertEqual(encoded, json.loads(json.dumps(encoded, sort_keys=True)))

    def test_differences_are_deterministic_bounded_and_path_limited(self):
        left = {f"key-{number:02d}": number for number in range(equivalence.MAX_DIFFERENCES + 4)}
        right = {f"key-{number:02d}": number + 1 for number in range(equivalence.MAX_DIFFERENCES + 4)}
        left["!" * 200] = {"nested": 1}
        right["!" * 200] = {"nested": 2}
        observed = equivalence.differences(left, right)
        self.assertEqual(equivalence.MAX_DIFFERENCES, len(observed))
        self.assertEqual(sorted(item["path"] for item in observed), [item["path"] for item in observed])
        self.assertTrue(all(len(item["path"]) <= equivalence.MAX_PATH_LENGTH for item in observed))
        self.assertTrue(observed[0]["path"].endswith("..."))

    def test_harness_has_no_legacy_or_process_dependency(self):
        source = Path(equivalence.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ralph_equivalence", source)
        self.assertNotIn("subprocess", source)


if __name__ == "__main__":
    unittest.main()
