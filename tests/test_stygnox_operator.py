import ast
import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stygnox_operator.py"
spec = importlib.util.spec_from_file_location("stygnox_operator", MODULE_PATH)
operator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(operator)


class StygnoxOperatorSnapshotTests(unittest.TestCase):
    def test_versioned_schema_and_all_operator_sections_are_present(self):
        snapshot = operator.stygnox_operator_snapshot_v1(
            controller={"status": "APPROVED"},
            progress={"current": 1}, gate={"state": "OPEN"},
            pending_paths=["scripts/new.py"], recovery={"checkpoint": "RP-1"},
            reconciliation={"replacement": True}, retirement={"record_id": "RT-1"},
            efficiency_model={"mode": "NORMAL", "model": "standard"},
            report={"status": "PASS"}, events=[{"kind": "PASS"}], live_output="ready",
        )
        self.assertEqual(operator.OPERATOR_SNAPSHOT_SCHEMA, snapshot["schema"])
        self.assertEqual(1, snapshot["version"])
        self.assertEqual("APPROVED", snapshot["controller"]["status"])
        self.assertEqual(1, snapshot["progress"]["current"])
        self.assertEqual("OPEN", snapshot["gate"]["state"])
        self.assertEqual(["scripts/new.py"], snapshot["pending_paths"])
        self.assertEqual("RP-1", snapshot["recovery"]["checkpoint"])
        self.assertTrue(snapshot["reconciliation"]["replacement"])
        self.assertEqual("RT-1", snapshot["retirement"]["record_id"])
        self.assertEqual("NORMAL", snapshot["efficiency_model"]["mode"])
        self.assertEqual("PASS", snapshot["report"]["status"])
        self.assertEqual([{"kind": "PASS"}], snapshot["events"])
        self.assertEqual("ready", snapshot["live_output"])

    def test_shaping_is_bounded_and_does_not_retain_caller_mutable_data(self):
        source = {f"key-{number}": "x" * 20 for number in range(5)}
        pending = [f"path-{number}" for number in range(5)]
        snapshot = operator.stygnox_operator_snapshot_v1(
            controller=source, pending_paths=pending, events=pending,
            live_output="y" * 20, max_items=2, max_text=7,
        )
        self.assertEqual(["key-0", "key-1"], list(snapshot["controller"]))
        self.assertEqual("xxxxxxx", snapshot["controller"]["key-0"])
        self.assertEqual(["path-0", "path-1"], snapshot["pending_paths"])
        self.assertEqual(["path-0", "path-1"], snapshot["events"])
        self.assertEqual("yyyyyyy", snapshot["live_output"])
        source["key-0"] = "changed"
        pending[0] = "changed"
        self.assertEqual("xxxxxxx", snapshot["controller"]["key-0"])
        self.assertEqual("path-0", snapshot["pending_paths"][0])

    def test_invalid_values_are_rejected_at_the_contract_boundary(self):
        with self.assertRaises(TypeError):
            operator.stygnox_operator_snapshot_v1(controller=["not", "a", "mapping"])
        with self.assertRaises(TypeError):
            operator.stygnox_operator_snapshot_v1(pending_paths="not a path list")
        with self.assertRaises(ValueError):
            operator.stygnox_operator_snapshot_v1(max_items=0)
        with self.assertRaises(ValueError):
            operator.stygnox_operator_snapshot_v1(events=[float("nan")])

    def test_source_is_standard_library_only_and_has_no_runtime_lifecycle_dependencies(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, {"math", "typing"})
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in ("open", "Path", "subprocess", "socket", "urllib", "http", "session", "html"):
            self.assertNotIn(forbidden, names)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(node.func, ast.Name) and node.func.id == "open" for node in calls))


if __name__ == "__main__":
    unittest.main()
