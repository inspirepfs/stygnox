import unittest
from unittest.mock import patch

from stygnox import self_development as sd


class ApprovalEpochTests(unittest.TestCase):
    def check_candidates(self, manifest, candidates):
        state = {
            "current_step": 1,
            "approval_repository_manifest": manifest,
        }
        plan = {"steps": [{"test_change_policy": "add-only"}]}
        with patch.object(sd.planning, "_validate_plan", return_value=plan):
            sd._test_policy_allows_candidates(state, candidates)

    def test_new_at_approval_can_be_modified_on_later_turn(self):
        self.check_candidates(
            {"tests/existing.py": "fingerprint"},
            [{
                "path": "tests/test_stygnox_transaction_renewal.py",
                "approval_presence": "present",
            }],
        )

    def test_existing_at_approval_remains_protected(self):
        with self.assertRaisesRegex(
            sd.SelfDevelopmentError, "cannot authorize existing"
        ):
            self.check_candidates(
                {"tests/existing.py": "fingerprint"},
                [{"path": "tests/existing.py",
                  "approval_presence": "absent"}],
            )

    def test_missing_approval_manifest_fails_closed(self):
        with self.assertRaisesRegex(
            sd.SelfDevelopmentError, "plan-approval repository manifest"
        ):
            self.check_candidates(
                None,
                [{"path": "tests/new.py",
                  "approval_presence": "absent"}],
            )


if __name__ == "__main__":
    unittest.main()
