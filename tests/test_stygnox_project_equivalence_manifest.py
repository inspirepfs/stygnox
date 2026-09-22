"""Freeze the reviewed facade/direct profile comparison manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import stygnox_project_equivalence as equivalence


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stygnox_project_equivalence_4f5fb11.json"
REVIEWED_MANIFEST_SHA256 = "c39ead2612bc62c5ebcea31e81175cca1ec657c12d5085dc1a6cabee54b621f1"
IMMUTABLE_BASELINE_METADATA = "4f5fb11"


class _StableTemporaryDirectory:
    """Keep the synthetic repository basename stable for frozen evidence."""

    def __init__(self, root: Path, **_: object) -> None:
        self.root = root

    def __enter__(self) -> str:
        self.root.mkdir()
        return str(self.root)

    def __exit__(self, *_: object) -> None:
        return None


class StygnoxProjectEquivalenceManifestTests(unittest.TestCase):
    def _fresh_observation(self) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="stygnox-manifest-") as temporary:
            root = Path(temporary) / "stygnox-project-equivalence-4f5fb11"
            with mock.patch.object(
                equivalence,
                "TemporaryDirectory",
                lambda **kwargs: _StableTemporaryDirectory(root, **kwargs),
            ), mock.patch("subprocess.run", side_effect=AssertionError("manifest observation must not run Git")):
                return equivalence.report()

    def test_reviewed_manifest_is_canonical_complete_and_matches_fresh_observation(self):
        fixture_bytes = FIXTURE_PATH.read_bytes()
        manifest = json.loads(fixture_bytes)
        canonical_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

        self.assertEqual(canonical_bytes, fixture_bytes, "reviewed manifest bytes must already be canonical")
        self.assertEqual(REVIEWED_MANIFEST_SHA256, hashlib.sha256(fixture_bytes).hexdigest())
        self.assertEqual(
            {"schema", "baseline_metadata", "aliases", "facade", "adapter", "differences"},
            set(manifest),
        )
        self.assertEqual(equivalence.SCHEMA, manifest["schema"])
        self.assertEqual(IMMUTABLE_BASELINE_METADATA, manifest["baseline_metadata"])
        self.assertEqual({"class": True, "project_singleton": True, "zen_singleton": True}, manifest["aliases"])
        self.assertEqual([], manifest["differences"])
        self.assertEqual(manifest["facade"], manifest["adapter"])
        self.assertEqual(manifest, self._fresh_observation())


if __name__ == "__main__":
    unittest.main()
