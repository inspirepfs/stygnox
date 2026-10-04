from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RALPH_PATH = ROOT / "scripts" / "ralph.py"


class Finding08StepAcceptanceTests(unittest.TestCase):
    """Hostile, process-isolated acceptance tests for the FINDING-08 boundary."""

    def run_probe(self, body: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            probe = textwrap.dedent(
                f"""
                import argparse
                import importlib.util
                import json
                import subprocess
                from pathlib import Path

                root = Path.cwd()
                subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
                subprocess.run(['git', 'config', 'user.email', 'ralph@example.invalid'], cwd=root, check=True)
                subprocess.run(['git', 'config', 'user.name', 'RALPH Test'], cwd=root, check=True)
                (root / 'app.py').write_text('value = 1\\n', encoding='utf-8')
                (root / '.ralph').mkdir()
                (root / '.ralph' / 'policy.md').write_text('# policy\\n', encoding='utf-8')
                subprocess.run(['git', 'add', 'app.py', '.ralph/policy.md'], cwd=root, check=True)
                subprocess.run(['git', 'commit', '-qm', 'baseline'], cwd=root, check=True)

                spec = importlib.util.spec_from_file_location('finding_08_fresh_ralph', {str(RALPH_PATH)!r})
                ralph = importlib.util.module_from_spec(spec)
                assert spec.loader is not None
                spec.loader.exec_module(ralph)
                ralph.bind_controller_root(root)
                ralph.init_files()

                {textwrap.indent(textwrap.dedent(body), '                ')}
                """
            )
            result = subprocess.run(
                ["python3", "-c", probe], cwd=directory, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertEqual(0, result.returncode, result.stdout)
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_fresh_process_outcome_matrix_contract_tamper_and_safety_precedence(self):
        evidence = self.run_probe(
            """
            plan = {
                'schema': 'zen_ralph_plan_v3',
                'repository_mutation_scope': ['app.py'],
                'outcome_result_contract': 'OUTCOME_RESULT_SCHEMA',
                'goal': 'Exercise hostile outcome admission.',
                'repository_authority': 'write',
                'planning': {'min_steps': 1, 'max_steps': 1},
                'steps': [{'id': 1, 'title': 'Only completed advances',
                           'objective': 'Reject every other outcome.',
                           'acceptance': ['Completion is explicit.'],
                           'test_change_policy': 'modify'}],
            }
            state = ralph.default_state()
            digest = ralph.plan_hash(plan)
            state.update({'status': 'AWAITING_APPROVAL', 'plan': plan, 'plan_hash': digest})
            ralph.save_state(state)
            ralph.PLAN.write_text(ralph.render_plan(plan), encoding='utf-8')
            ralph.cmd_approve(argparse.Namespace(plan_hash=digest))
            state = ralph.load_state()
            version = ralph.core.APPROVED_PLAN_V3
            base = {'summary': 'explicit no-code work is complete', 'ideas': [], 'blockers': [],
                    'needs_human': False, 'blocker_class': 'none', 'validation_notes': [],
                    'context': {'relevant_files': [], 'accepted_findings': [], 'files_inspected': []}}
            outcomes = ['completed', 'incomplete', 'blocked', 'failed', 'continuation',
                        'unmet_prerequisite', 'skipped', 'impossible', 'fail_closed']
            admitted, refused = [], []
            for outcome in outcomes:
                result = dict(base, outcome=outcome)
                try:
                    ralph.completed_outcome_witness(state, version, result)
                    admitted.append(outcome)
                except RuntimeError:
                    refused.append(outcome)
            for hostile in (
                dict(base),
                dict(base, outcome='completed', blockers=['contradictory blocker']),
                dict(base, outcome='completed', needs_human=True),
            ):
                try:
                    ralph.completed_outcome_witness(state, version, hostile)
                    raise AssertionError('contradictory or missing outcome passed')
                except RuntimeError:
                    pass

            # A malformed ledger must not hide an out-of-scope safety refusal.
            state['operation_attributions'] = [{'schema': 'forged'}]
            (root / 'outside.py').write_text('outside = True\\n', encoding='utf-8')
            safety = ralph.record_post_turn_repository_verification(
                state, plan['steps'][0], 'workspace-write', ['outside.py'], loop=1,
            )

            state = ralph.load_state()
            state['outcome_result_contract_bindings'][0]['binding_sha256'] = '0' * 64
            try:
                ralph.verified_result_contract_for_active_step(state, version)
                raise AssertionError('tampered immutable binding was selected')
            except (RuntimeError, ValueError):
                pass
            print(json.dumps({'admitted': admitted, 'refused': refused, 'safety': safety['error']}))
            """
        )
        self.assertEqual(["completed"], evidence["admitted"])
        self.assertEqual(
            {"incomplete", "blocked", "failed", "continuation", "unmet_prerequisite", "skipped", "impossible", "fail_closed"},
            set(evidence["refused"]),
        )
        self.assertEqual("CHECKPOINT_REPOSITORY_SCOPE_DELTA: ['outside.py']", evidence["safety"])

    def test_fresh_process_preserves_legacy_provider_and_multigeneration_restored_reconciliation(self):
        evidence = self.run_probe(
            """
            plan = {
                'schema': 'zen_ralph_plan_v3', 'repository_mutation_scope': ['app.py'],
                'outcome_result_contract': 'OUTCOME_RESULT_SCHEMA', 'goal': 'Reconcile restored layers.',
                'repository_authority': 'write', 'planning': {'min_steps': 1, 'max_steps': 1},
                'steps': [{'id': 1, 'title': 'Layered provenance', 'objective': 'Keep generations distinct.',
                           'acceptance': ['Restored evidence is fail closed.'], 'test_change_policy': 'modify'}],
            }
            state = ralph.default_state()
            digest = ralph.plan_hash(plan)
            state.update({'status': 'AWAITING_APPROVAL', 'plan': plan, 'plan_hash': digest})
            ralph.save_state(state)
            ralph.PLAN.write_text(ralph.render_plan(plan), encoding='utf-8')
            ralph.cmd_approve(argparse.Namespace(plan_hash=digest))
            state = ralph.load_state()
            step = plan['steps'][0]
            completed = ralph.completed_outcome_witness(
                state, ralph.core.APPROVED_PLAN_V3,
                {'summary': 'done', 'ideas': [], 'blockers': [], 'needs_human': False,
                 'blocker_class': 'none', 'validation_notes': [], 'outcome': 'completed',
                 'context': {'relevant_files': [], 'accepted_findings': [], 'files_inspected': []}},
            )
            (root / 'app.py').write_text('value = 2\\n', encoding='utf-8')
            first, _ = ralph.process_post_turn_safety(state, step, 'workspace-write', ['app.py'], loop=1)
            assert first['state'] == 'PASS'
            ralph._promote_pending_current_step_provenance(state, step, completed)
            ralph._clear_pending_step_paths(state)
            (root / 'app.py').write_text('value = 3\\n', encoding='utf-8')
            second, _ = ralph.process_post_turn_safety(state, step, 'workspace-write', ['app.py'], loop=2)
            assert second['state'] == 'PASS'
            ralph._promote_pending_current_step_provenance(state, step, completed)
            ralph._clear_pending_step_paths(state)
            (root / 'app.py').write_text('value = 1\\n', encoding='utf-8')
            checkpoint = ralph.load_recovery_checkpoint(state['recovery_checkpoint'])
            records = ralph.reconciled_restored_retirement_records(state, checkpoint)

            legacy_plan = {'goal': 'legacy provider', 'repository_authority': 'write',
                           'planning': {'min_steps': 1, 'max_steps': 1},
                           'steps': [{'id': 1, 'title': 'legacy', 'objective': 'retain provider shape',
                                      'acceptance': ['legacy remains compatible.'], 'test_change_policy': 'none'}]}
            legacy = ralph.default_state()
            legacy.update({'plan': legacy_plan, 'plan_hash': ralph.plan_hash(legacy_plan), 'current_step': 1})
            legacy_result = {'summary': 'old provider result', 'ideas': [], 'blockers': [], 'needs_human': False,
                             'blocker_class': 'none', 'validation_notes': [],
                             'context': {'relevant_files': [], 'accepted_findings': [], 'files_inspected': []}}
            print(json.dumps({'records': len(records), 'action': records[0]['restoration']['action'],
                              'legacy_witness': ralph.completed_outcome_witness(legacy, ralph.core.APPROVED_PLAN_V1, legacy_result)}))
            """
        )
        self.assertEqual(1, evidence["records"])
        self.assertEqual("none", evidence["action"])
        self.assertEqual({}, evidence["legacy_witness"])


if __name__ == "__main__":
    unittest.main()
