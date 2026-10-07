"""Regression coverage for the installed-only upgrade/rebind boundary."""
from __future__ import annotations

import base64
import hashlib
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stygnox import lifecycle  # noqa: E402


class StygnoxR3dUpgradeRebindTests(unittest.TestCase):
    def _preview(self, root: Path, digest: str) -> dict[str, object]:
        return {
            "preview_sha256": digest,
            "admissible": True,
            "blockers": [],
            "worktree": str(root),
            "operator": "Operator",
            "installed_identity": {
                "executable": "/installed/bin/stygnox",
                "site_packages": "/installed/lib/python/site-packages",
            },
            "candidate_artifact": {"sha256": "c" * 64},
            "bootstrap_disposition": {"disposition": "OPERATOR_ADOPTION_MATERIAL"},
            "authority_lineage": {},
            "successor_binding": {"qualified_source_manifest_sha256": "e" * 64},
            "immutable_runtime_inventory_sha256": "d" * 64,
            "new_runtime_epoch": 1,
        }

    @staticmethod
    def _wheel_record_digest(payload: bytes) -> str:
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode("ascii").rstrip("=")
        return f"sha256={encoded}"

    def _write_wheel(self, wheel: Path, package_payload: bytes, version: str) -> None:
        metadata = f"Name: stygnox\nVersion: {version}\n".encode("utf-8")
        record = "\n".join(
            (
                f"stygnox/adoption.py,{self._wheel_record_digest(package_payload)},{len(package_payload)}",
                f"stygnox-1.dist-info/METADATA,{self._wheel_record_digest(metadata)},{len(metadata)}",
                "stygnox-1.dist-info/RECORD,,",
            )
        ).encode("utf-8")
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("stygnox/adoption.py", package_payload)
            archive.writestr("stygnox-1.dist-info/METADATA", metadata)
            archive.writestr("stygnox-1.dist-info/RECORD", record)

    def test_stale_preview_refuses_before_starting_a_handoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            expected = "a" * 64
            stale = self._preview(root, "b" * 64)
            with mock.patch.object(lifecycle, "build_rebind_preview", return_value=stale), mock.patch.object(
                lifecycle.subprocess, "run"
            ):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "preview is stale"):
                    lifecycle.accept_rebind(root, "Operator", root / "stygnox.whl", expected, "REBIND")
            self.assertFalse((root / ".stygnox" / lifecycle.REBIND_RECORD).exists())

    def test_failed_fresh_handoff_retains_previous_authority(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            expected = "a" * 64
            preview = self._preview(root, expected)
            failed = subprocess.CompletedProcess(["stygnox"], 2, "", "refused")
            with mock.patch.object(lifecycle, "build_rebind_preview", return_value=preview), mock.patch.object(
                lifecycle.subprocess, "run", return_value=failed
            ), mock.patch.object(lifecycle.sys, "argv", ["/installed/bin/stygnox"]):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "failed before transfer"):
                    lifecycle.accept_rebind(root, "Operator", root / "stygnox.whl", expected, "REBIND")
            self.assertFalse((root / ".stygnox" / lifecycle.REBIND_RECORD).exists())

    def test_source_tree_invocation_refuses_before_starting_a_handoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            expected = "a" * 64
            preview = self._preview(root, expected)
            with mock.patch.object(lifecycle, "build_rebind_preview", return_value=preview), mock.patch.object(
                lifecycle.subprocess, "run"
            ):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "must be initiated"):
                    lifecycle.accept_rebind(root, "Operator", root / "stygnox.whl", expected, "REBIND")
            self.assertFalse((root / ".stygnox" / lifecycle.REBIND_RECORD).exists())

    def test_success_requires_receipt_from_a_new_process(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            expected = "a" * 64
            preview = self._preview(root, expected)
            committed = {
                "schema": lifecycle.REBIND_SCHEMA,
                "product_version": lifecycle.PRODUCT.version,
                "operator": "Operator",
                "preview_sha256": expected,
                "parent_process": mock.ANY,
                "fresh_process": {"pid": 99123, "executable": "/installed/bin/stygnox"},
                "new_runtime_epoch": 1,
                "installed_identity": preview["installed_identity"],
                "candidate_artifact": preview["candidate_artifact"],
                "bootstrap_disposition": preview["bootstrap_disposition"],
                "authority_lineage": {},
                "successor_binding": preview["successor_binding"],
                "successor_transaction": {"record_sha256": "f" * 64},
                "successor_controller": {"record_sha256": "0" * 64},
                "immutable_runtime_inventory_sha256": "d" * 64,
                "quiescent_handoff": True,
                "source_tree_fallback": False,
                "ralph_fallback": False,
                "result": "REBIND_COMPLETED_BY_FRESH_INSTALLED_PROCESS",
            }
            committed["parent_process"] = lifecycle.os.getpid()
            committed["record_sha256"] = lifecycle._digest(committed)
            receipt = dict(committed)
            completed = subprocess.CompletedProcess(["stygnox"], 0, lifecycle._render(receipt), "")
            with mock.patch.object(lifecycle, "build_rebind_preview", return_value=preview), mock.patch.object(
                lifecycle.subprocess, "run", return_value=completed
            ), mock.patch.object(lifecycle, "_load_json", return_value=committed), mock.patch.object(
                lifecycle.sys, "argv", ["/installed/bin/stygnox"]
            ):
                result = lifecycle.accept_rebind(root, "Operator", root / "stygnox.whl", expected, "REBIND")
            self.assertEqual(receipt, result)

    def test_wheel_identity_is_deterministic_and_refuses_substitution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            site_packages = root / "site-packages"
            package = site_packages / "stygnox" / "adoption.py"
            package.parent.mkdir(parents=True)
            wheel = root / "stygnox.whl"
            installed = {"package_version": "0.1.0.dev9", "site_packages": str(site_packages)}
            package.write_bytes(b"first installed identity\n")
            self._write_wheel(wheel, package.read_bytes(), "0.1.0.dev9")
            first = lifecycle._wheel_identity(wheel, installed)
            self.assertEqual(first, lifecycle._wheel_identity(wheel, installed))
            package.write_bytes(b"substituted installed identity\n")
            with self.assertRaisesRegex(lifecycle.LifecycleError, "does not match"):
                lifecycle._wheel_identity(wheel, installed)

    def test_wheel_identity_refuses_an_incomplete_package_even_when_listed_files_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            site_packages = root / "site-packages"
            package = site_packages / "stygnox" / "adoption.py"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"installed adoption identity\n")
            (package.parent / "lifecycle.py").write_bytes(b"installed lifecycle identity\n")
            wheel = root / "stygnox.whl"
            installed = {"package_version": "0.1.0.dev9", "site_packages": str(site_packages)}
            self._write_wheel(wheel, package.read_bytes(), "0.1.0.dev9")
            with self.assertRaisesRegex(lifecycle.LifecycleError, "package members do not match"):
                lifecycle._wheel_identity(wheel, installed)

    def _qualified_records(self, baseline: str) -> dict[str, dict[str, object]]:
        final: dict[str, object] = {
            "state": "PASS", "repository_baseline_sha256": baseline,
            "repository_mutation_scope_sha256": lifecycle._digest(["src/stygnox/lifecycle.py"]),
            "accepted_controller_attribution": {"attribution_sha256": "a" * 64},
        }
        final["provenance_sha256"] = lifecycle._digest(final)
        plan: dict[str, object] = {
            "plan_hash": "p" * 64, "current_step": 1,
            "repository_mutation_scope": ["src/stygnox/lifecycle.py"],
            "repository_mutation_scope_sha256": lifecycle._digest(["src/stygnox/lifecycle.py"]),
            "final_qualification": final,
        }
        plan["record_sha256"] = lifecycle._digest(plan)
        transaction: dict[str, object] = {"transaction_id": "TX-old", "state": "STOPPED"}
        transaction["record_sha256"] = lifecycle._digest(transaction)
        predecessor: dict[str, object] = {"enabled": False, "controller_execution_enabled": False}
        predecessor["record_sha256"] = lifecycle._digest(predecessor)
        return {"plan": plan, "transaction": transaction, "controller": predecessor}

    def test_rebind_refuses_wheel_source_mismatch_after_qualification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            source = root / "src" / "stygnox" / "lifecycle.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"qualified source\n")
            artifact = {"package_manifest": [{"path": "stygnox/lifecycle.py", "sha256": "0" * 64, "size": 1}]}
            artifact["package_manifest_sha256"] = lifecycle._digest(artifact["package_manifest"])
            with mock.patch.object(lifecycle.adoption, "capture_baseline", return_value=mock.Mock(public=lambda: {"sha256": "b" * 64})):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "does not match qualified source"):
                    lifecycle._qualified_successor_binding(root, self._qualified_records("b" * 64), artifact)

    def test_rebind_refuses_stale_qualification_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            artifact = {"package_manifest": []}
            artifact["package_manifest_sha256"] = lifecycle._digest([])
            with mock.patch.object(lifecycle.adoption, "capture_baseline", return_value=mock.Mock(public=lambda: {"sha256": "c" * 64})):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "qualification is stale"):
                    lifecycle._qualified_successor_binding(root, self._qualified_records("b" * 64), artifact)

    def test_successor_transaction_refuses_incomplete_installed_identity(self) -> None:
        predecessor = {"transaction_id": "TX-old", "state": "STOPPED"}
        predecessor["record_sha256"] = lifecycle.transactions._digest(predecessor)
        with self.assertRaisesRegex(lifecycle.transactions.TransactionError, "lacks installed artifact identity"):
            lifecycle.transactions.successor_transaction(predecessor, {"candidate_artifact": {}})

    def test_handoff_preserves_the_exact_installed_launcher_on_child_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            expected = "a" * 64
            preview = self._preview(root, expected)
            committed = {
                "schema": lifecycle.REBIND_SCHEMA,
                "product_version": lifecycle.PRODUCT.version,
                "operator": "Operator",
                "preview_sha256": expected,
                "parent_process": lifecycle.os.getpid(),
                "fresh_process": {"pid": 99123, "executable": "/installed/bin/stygnox"},
                "new_runtime_epoch": 1,
                "installed_identity": preview["installed_identity"],
                "candidate_artifact": preview["candidate_artifact"],
                "bootstrap_disposition": preview["bootstrap_disposition"],
                "authority_lineage": {},
                "successor_binding": preview["successor_binding"],
                "successor_transaction": {"record_sha256": "f" * 64},
                "successor_controller": {"record_sha256": "0" * 64},
                "immutable_runtime_inventory_sha256": "d" * 64,
                "quiescent_handoff": True,
                "source_tree_fallback": False,
                "ralph_fallback": False,
                "result": "REBIND_COMPLETED_BY_FRESH_INSTALLED_PROCESS",
            }
            committed["record_sha256"] = lifecycle._digest(committed)
            completed = subprocess.CompletedProcess(["stygnox"], 0, lifecycle._render(committed), "")
            with mock.patch.object(lifecycle, "build_rebind_preview", return_value=preview), mock.patch.object(
                lifecycle.subprocess, "run", return_value=completed
            ) as handoff, mock.patch.object(lifecycle, "_load_json", return_value=committed), mock.patch.object(
                lifecycle.sys, "argv", ["/installed/bin/stygnox"]
            ):
                lifecycle.accept_rebind(root, "Operator", root / "stygnox.whl", expected, "REBIND")
            self.assertEqual("/installed/bin", handoff.call_args.kwargs["env"]["PATH"])

    def test_copied_executable_refuses_before_authority_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            expected = "a" * 64
            preview = self._preview(root, expected)
            with mock.patch.object(lifecycle, "build_rebind_preview", return_value=preview), mock.patch.object(
                lifecycle.sys, "argv", ["/copied/stygnox"]
            ):
                with self.assertRaisesRegex(lifecycle.LifecycleError, "executable differs"):
                    lifecycle._commit_rebind(
                        root, "Operator", root / "stygnox.whl", expected, parent_pid=lifecycle.os.getppid()
                    )
            self.assertFalse((root / ".stygnox" / lifecycle.REBIND_RECORD).exists())

    def test_bootstrap_disposition_never_becomes_provider_attribution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stygnox-rebind-") as temp:
            root = Path(temp)
            (root / "stygnox.toml").write_text("schema = 'stygnox_project_config_v1'\n", encoding="utf-8")
            (root / "stygnox.policy.md").write_text("# operator material\n", encoding="utf-8")
            disposition = lifecycle._bootstrap_disposition(root)
            self.assertEqual("OPERATOR_ADOPTION_MATERIAL", disposition["disposition"])
            self.assertEqual("EXCLUDED", disposition["provider_attribution"])
            self.assertFalse(disposition["accepted_provider_delta"])
            self.assertFalse(disposition["qualified_provider_delta"])
            self.assertFalse(disposition["finalized_provider_delta"])


if __name__ == "__main__":
    unittest.main()
