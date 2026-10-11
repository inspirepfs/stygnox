"""Stage C2a: a successor-only authority encoding must be incompatible with legacy execution."""
from pathlib import Path
from unittest import TestCase, mock

from stygnox import direct_interruption_fence as f
from stygnox import direct_interruption as d
from stygnox import direct_interruption_handoff as h
from stygnox import planning, controller, scheduler


class SuccessorFenceDesign(TestCase):
    def setUp(self):
        self.handoff = {
            "schema": h.SCHEMA,
            "authority_changed": False,
            "admissible": False,
            "old_controller_fencing_proved": False,
            "fresh_process_authority_transfer_proved": False,
            "worktree": "/tmp/reviewed-project",
            "operator": "alice", "plan_hash": "a"*64,
            "transaction_id": "TX-1", "step": 2,
            "predecessor_plan_record_sha256": "b"*64,
            "predecessor_controller_record_sha256": "c"*64,
            "predecessor_transaction_record_sha256": "d"*64,
            "predecessor_installed_executable": {"path": "/opt/old/bin/stygnox", "sha256": "e"*64},
            "candidate_installed_identity": {"executable": "/opt/new/bin/stygnox", "record_sha256": "f"*64},
            "candidate_wheel_identity": {"sha256": "1"*64},
            "review_preview_sha256": "2"*64,
            "manifest_proof_sha256": "3"*64,
        }
        self.reseal()

    def reseal(self):
        self.handoff['preview_sha256'] = d._digest({k:v for k,v in self.handoff.items() if k!='preview_sha256'})

    def test_proposed_fence_is_explicitly_not_legacy_approved(self):
        design = f.build_fence_design(self.handoff)
        self.assertNotEqual(design['proposed_plan_status'], 'APPROVED')
        self.assertIs(design['proposed_legacy_execution_authority_granted'], False)
        self.assertEqual(design['handoff_preview_sha256'], self.handoff['preview_sha256'])
        self.assertEqual(design['review_preview_sha256'], '2'*64)
        self.assertFalse(design['admissible'])
        self.assertFalse(design['authority_changed'])
        self.assertFalse(design['old_binary_refusal_tested_in_fresh_process'])
        self.assertFalse(design['successor_admission_implemented'])
        self.assertEqual(design['preview_sha256'], d._digest({k:v for k,v in design.items() if k!='preview_sha256'}))

    def test_legacy_planning_rejects_proposed_successor_status(self):
        design = f.build_fence_design(self.handoff)
        state = {"status": design['proposed_plan_status'], "execution_authority_granted": False}
        # This uses the legacy-compatible admission logic found in the supplied
        # checkout. A separate fresh-process test against the actual installed
        # predecessor is STILL required before considering a real handoff.
        with mock.patch.object(planning.adoption, 'resolve_worktree', return_value=Path('/tmp/reviewed-project')), \
             mock.patch.object(planning, '_record', return_value=state), \
             mock.patch.object(planning, '_active_context', side_effect=AssertionError('admitted legacy authority')):
            with self.assertRaisesRegex(planning.PlanningError, 'unsupported active plan status'):
                planning.approved_step_context(Path('/tmp/reviewed-project'), 'alice')

    def test_legacy_controller_run_preview_refuses_successor_status_before_provider(self):
        design = f.build_fence_design(self.handoff)
        state = {"status": design['proposed_plan_status'], "execution_authority_granted": False}
        active = {"enabled": True, "operator": "alice", "transaction_id": "TX-1",
                  "installed_command": "/opt/new/bin/stygnox"}
        tx = {"operator": "alice", "transaction_id": "TX-1"}
        # This is a source-level refusal proof, not fresh-process proof of the
        # user's actual installed original executable.
        with mock.patch.object(controller.adoption, 'resolve_worktree', return_value=Path('/tmp/reviewed-project')), \
             mock.patch.object(controller, '_controller', return_value=active), \
             mock.patch.object(controller, '_transaction', return_value=tx), \
             mock.patch.object(controller, '_operator', return_value='alice'), \
             mock.patch.object(scheduler, 'active_scheduler_authority', return_value=None), \
             mock.patch.object(controller, '_policy_status', return_value={
                'policy': {'provider': controller.provider_codex.PROVIDER_NAME, 'model': 'test'},
                'approved': True}), \
             mock.patch.object(controller.adoption, 'capture_baseline', return_value=mock.Mock(public=lambda: {'sha256':'a'*64})), \
             mock.patch.object(planning, '_record', return_value=state), \
             mock.patch.object(controller.provider_codex, 'execute', side_effect=AssertionError('provider invoked')):
            with self.assertRaisesRegex(controller.ControllerError, 'unsupported active plan status'):
                controller.build_run_preview(Path('/tmp/reviewed-project'), 'alice', 'test', 'write')

    def test_legacy_planning_rejects_ordinary_approved_with_false_grant(self):
        with mock.patch.object(planning.adoption, 'resolve_worktree', return_value=Path('/tmp/reviewed-project')), \
             mock.patch.object(planning, '_record', return_value={"status": "APPROVED", "execution_authority_granted": False}), \
             mock.patch.object(planning, 'pending_required_transition', return_value=None):
            with self.assertRaisesRegex(planning.PlanningError, 'does not grant controller execution authority'):
                planning.approved_step_context(Path('/tmp/reviewed-project'), 'alice')

    def test_tampered_preview_refused(self):
        self.handoff['operator'] = 'eve'
        with self.assertRaisesRegex(f.FenceRefused, 'digest invalid'):
            f.build_fence_design(self.handoff)

    def test_self_declared_handoff_admission_refused(self):
        self.handoff['admissible'] = True
        self.reseal()
        with self.assertRaisesRegex(f.FenceRefused, 'unchanged, read-only'):
            f.build_fence_design(self.handoff)

    def test_claimed_old_fence_proof_refused(self):
        self.handoff['old_controller_fencing_proved'] = True
        self.reseal()
        with self.assertRaisesRegex(f.FenceRefused, 'unchanged, read-only'):
            f.build_fence_design(self.handoff)

    def test_same_executable_refused(self):
        self.handoff['candidate_installed_identity']['executable'] = '/opt/old/bin/stygnox'
        self.reseal()
        with self.assertRaisesRegex(f.FenceRefused, 'must differ'):
            f.build_fence_design(self.handoff)

    def test_missing_manifest_proof_refused(self):
        self.handoff['manifest_proof_sha256'] = None
        self.reseal()
        with self.assertRaisesRegex(f.FenceRefused, 'manifest proof'):
            f.build_fence_design(self.handoff)

    def test_distinct_origin_changes_design_digest(self):
        first = f.build_fence_design(self.handoff)
        self.handoff['review_preview_sha256'] = '9'*64
        self.reseal()
        second = f.build_fence_design(self.handoff)
        self.assertNotEqual(first['preview_sha256'], second['preview_sha256'])

    def test_cli_has_read_only_fence_design_but_no_commit(self):
        parser = d.build_parser()
        args = parser.parse_args(['fence-design-preview', '--project', '/tmp/reviewed-project',
            '--origin-file', '/tmp/origin', '--origin-preview-sha256', '4'*64,
            '--candidate-wheel', '/tmp/wheel', '--review-path', 'src/stygnox/planning.py'])
        self.assertEqual(args.action, 'fence-design-preview')
        with self.assertRaises(SystemExit):
            parser.parse_args(['fence-commit', '--project', '/tmp/reviewed-project'])

    def test_cli_does_not_write_in_fence_design_preview(self):
        with mock.patch.object(h, 'build_handoff_preview', return_value=self.handoff), \
             mock.patch.object(d, '_write', side_effect=AssertionError('runtime write')), \
             mock.patch.object(d.planning, '_write', side_effect=AssertionError('plan write')):
            # cli_main serializes the preview only; no runtime mutation is allowed.
            self.assertEqual(d.cli_main(['fence-design-preview', '--project', '/tmp/reviewed-project',
                '--origin-file', '/tmp/origin', '--origin-preview-sha256', '4'*64,
                '--candidate-wheel', '/tmp/wheel', '--review-path', 'src/stygnox/planning.py']), 0)
