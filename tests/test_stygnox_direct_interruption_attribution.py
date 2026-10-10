"""Stage B2: hostile read-only recovered-source attribution and qualification replay."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from stygnox import direct_interruption_attribution as a
from stygnox import direct_interruption_replay as replay
from tests import test_stygnox_direct_interruption_replay as fixturemod
from tests.test_stygnox_direct_interruption_replay import record, delta, fp


class B2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / '.stygnox'
        self.runtime.mkdir()
        fixture = fixturemod.Tests()
        fixture.setUp()
        self.state = copy.deepcopy(fixture.state)
        self.state['operator'] = 'alice'
        self.state['direct_interruption_pending'] = None
        self.original = record(self.state)
        self.preview = copy.deepcopy(fixture.preview)
        self.preview['candidate_baseline_sha256'] = 'e'*64
        self.preview['current_step'] = 2
        self.preview['operator'] = 'alice'
        self.preview['worktree'] = str(self.root)
        self.preview['reviewed_file_sha256'] = {
            'stygnox.toml':fp('operator-config'),
            # Accepted source that is still Git-dirty, but unchanged by interruption.
            'src/stygnox/planning.py':fp('old-plan'),
            'src/stygnox/transactions.py':fp('failed-turn'),
            'tests/test_stygnox_transaction_renewal.py':fp('failed-test')}
        self.preview = record({k:v for k,v in self.preview.items() if k!='preview_sha256'}, 'preview_sha256')
        self.approval = fixture.approval
        self.candidate = fixture.candidate
        for accepted in fixture.receipts.values():
            self.write(f"controller-run-{accepted['preview_sha256'][:16]}.json",accepted)
        self.proof = a.prove_review(self.root, self.original, self.preview)
        self.preview['manifest_proof'] = self.proof
        self.preview = record({k:v for k,v in self.preview.items() if k!='preview_sha256'}, 'preview_sha256')
        self.intent = record({'schema':'stygnox_direct_interruption_intent_v1',
            'review_preview':self.preview,'manifest_proof':self.proof,
            'human_reason':'Reviewed exact source and tests for transaction renewal',
            'operator_review_is_new_authority_not_retroactive_grant':True})
        from stygnox.direct_interruption import QUALIFICATION_FILES
        self.qual = record({'schema':'stygnox_direct_interruption_test_evidence_v1',
            'test_files':list(QUALIFICATION_FILES),
            'test_output_sha256':'a'*64,
            'test_python':'/opt/stygnox-external-qualification/python3',
            'intent_record_sha256':self.intent['record_sha256'],
            'candidate_baseline_sha256':self.preview['candidate_baseline_sha256'],
            'origin_preview_sha256':self.preview['origin_preview_sha256'],
            'exit_code':0, 'plan_record_sha256': 'd'*64})
        self.release = record({'schema':'stygnox_direct_interruption_release_v1',
            'reviewed_origin':self.preview['origin_preview_sha256'],
            'provider_pass_fabricated':False,'retrospective_grant_fabricated':False,
            'classification':'HUMAN_REVIEWED_UNATTRIBUTED_INTERRUPTED_WORK',
            'manifest_proof_sha256':self.proof['proof_sha256'],
            'intent_record_sha256':self.intent['record_sha256'],
            'qualification_record_sha256':self.qual['record_sha256'],
            'predecessor_plan_record_sha256':self.original['record_sha256'],
            'quarantined_plan_record_sha256': 'd'*64,
            'original_baseline_sha256':self.preview['predecessor_baseline_sha256'],
            'reviewed_baseline_sha256':self.preview['candidate_baseline_sha256']})
        prefix=f"direct-interruption-{self.preview['origin_preview_sha256'][:16]}"
        self.prefix = prefix
        for suffix,obj in [('intent',self.intent),('predecessor-plan',record({'schema':'stygnox_direct_interruption_predecessor_plan_v1','original_plan':self.original})),('qualification',self.qual),('release',self.release)]:
            self.write(f'{prefix}-{suffix}.json',obj)
        self.state['direct_interruption_recoveries']=[self.release]
    def write(self,name,obj):
        (self.runtime/name).write_text(json.dumps(obj),encoding='utf-8')
    def verify(self):
        return a.replay_attribution(self.root,self.state,self.original['plan'],self.candidate,pending_receipt=None)
    def test_distinct_attribution_replays_original_receipts_and_recovery(self):
        result=self.verify()
        self.assertEqual(len(result['accepted_controller_receipts']),2)
        self.assertEqual(result['accepted_controller_paths'], ['src/stygnox/transactions.py','tests/test_stygnox_transaction_renewal.py'])
        self.assertEqual(result['reviewed_recovery_paths'],['src/stygnox/transactions.py','tests/test_stygnox_transaction_renewal.py'])
        self.assertEqual(len(result['reviewed_recovery_evidence']),1)
    def test_authoritative_qualification_integration_keeps_distinct_review(self):
        from stygnox import qualification
        result = qualification._accepted_controller_attribution(
            self.state, self.root, self.original['plan'], self.candidate, pending_receipt=None)
        self.assertEqual(len(result['accepted_controller_receipts']),2)
        self.assertEqual(len(result['reviewed_recovery_evidence']),1)
        self.assertEqual(result['attributed_paths'],result['accepted_controller_paths'])
        self.assertEqual(result['reviewed_recovery_paths'],['src/stygnox/transactions.py','tests/test_stygnox_transaction_renewal.py'])
        self.assertTrue(result['attribution_sha256'])
    def test_qualification_must_prove_exact_test_suite(self):
        bad={**self.qual,'test_files':[]}
        bad=record({k:v for k,v in bad.items() if k!='record_sha256'})
        self.write(f'{self.prefix}-qualification.json',bad)
        with self.assertRaisesRegex(a.AttributionRefused,'review/release'):
            self.verify()
    def test_historical_ralph_approval_evidence_is_not_a_writable_scope(self):
        old=copy.deepcopy(self.original)
        old['approval_repository_manifest']['.ralph/policy.md']=fp('historical')
        with self.assertRaisesRegex(a.AttributionRefused,'discontinuity'):
            a.prove_review(self.root,old,self.preview)

    def test_original_controller_receipt_missing(self):
        (self.runtime/'controller-run-1111111111111111.json').unlink()
        with self.assertRaisesRegex(a.AttributionRefused,'missing or duplicate'):
            self.verify()
    def test_no_fabricated_success_receipt_for_failed_origin(self):
        origin = self.preview['origin_preview_sha256']
        self.write(f'controller-run-{origin[:16]}.json',{'schema':'not-a-controller-result'})
        with self.assertRaisesRegex(a.AttributionRefused,'failed provider origin'):
            self.verify()
    def test_continuation_baseline_substitution(self):
        row = dict(self.state['continuation_history'][0])
        row['after_baseline_sha256'] = 'e'*64
        self.state['continuation_history'][0] = record({k:v for k,v in row.items() if k!='record_sha256'})
        with self.assertRaisesRegex(a.AttributionRefused,'continuation does not match'):
            self.verify()

    def test_original_controller_receipt_tampered(self):
        name='controller-run-1111111111111111.json'
        obj=json.loads((self.runtime/name).read_text());obj['next_action']='turn-complete';self.write(name,obj)
        with self.assertRaisesRegex(a.AttributionRefused,'malformed accepted'):
            self.verify()
    def test_missing_review_evidence(self):
        (self.runtime/f'{self.prefix}-intent.json').unlink()
        with self.assertRaisesRegex(a.AttributionRefused,'missing or unsafe'):
            self.verify()
    def test_release_substitution(self):
        self.state['direct_interruption_recoveries'][0]['classification']='CONTROLLER_SUCCESS'
        with self.assertRaisesRegex(a.AttributionRefused,'tampered'):
            self.verify()
    def test_duplicate_recovery(self):
        self.state['direct_interruption_recoveries'].append(self.release)
        with self.assertRaisesRegex(a.AttributionRefused,'unsupported'):
            self.verify()
    def test_unresolved_quarantine(self):
        self.state['direct_interruption_pending']={'origin_preview_sha256':self.preview['origin_preview_sha256']}
        with self.assertRaisesRegex(a.AttributionRefused,'unresolved'):
            self.verify()
    def test_qualification_failure(self):
        bad={**self.qual,'exit_code':1};bad=record({k:v for k,v in bad.items() if k!='record_sha256'})
        self.write(f'{self.prefix}-qualification.json',bad)
        with self.assertRaisesRegex(a.AttributionRefused,'review/release'):
            self.verify()
    def test_missing_candidate_changes_refused(self):
        with self.assertRaisesRegex(a.AttributionRefused,'reproduce qualified manifest'):
            a.replay_attribution(self.root,self.state,self.original['plan'],self.approval,pending_receipt=None)
    def test_approval_time_test_mutation_refused(self):
        old=self.preview
        self.preview=copy.deepcopy(self.preview)
        self.preview['candidate_manifest']['tests/test_stygnox_old.py']=fp('illicit')
        self.preview['candidate_manifest_sha256']=replay.digest(self.preview['candidate_manifest'])
        self.preview=record({k:v for k,v in self.preview.items() if k!='preview_sha256'}, 'preview_sha256')
        with self.assertRaisesRegex(a.AttributionRefused,'approval-existing'):
            a.prove_review(self.root,self.original,self.preview)
    def test_unapproved_post_release_drift(self):
        modified={**self.candidate,'src/stygnox/scheduler.py':fp('foreign')}
        with self.assertRaisesRegex(a.AttributionRefused,'reproduce qualified manifest'):
            a.replay_attribution(self.root,self.state,self.original['plan'],modified,pending_receipt=None)
    def test_unreferenced_competing_receipt_is_preserved_not_replayed(self):
        origin='7'*64
        rogue_manifest=dict(self.approval)
        rogue_manifest['src/stygnox/transactions.py']=fp('unaccepted-fork')
        rogue=record({'schema':'stygnox_controller_run_result_v1',
            'repository_authority':'write','transaction_id':self.state['transaction_id'],
            'human_gate':None,'provider_result':{'status':'PASS'},
            'next_action':'continue-same-step','preview_sha256':origin,
            'before_baseline_sha256':'b'*64,'after_baseline_sha256':'b'*64,
            'plan_binding':{'plan_hash':self.state['plan_hash'],'current_step':2,
                'repository_mutation_scope':self.state['repository_mutation_scope'],
                'repository_mutation_scope_sha256':replay.digest(self.state['repository_mutation_scope'])},
            'actual_delta':delta(self.approval,rogue_manifest)})
        self.write(f'controller-run-{origin[:16]}.json',rogue)
        outcome=self.verify()
        self.assertEqual(len(outcome['accepted_controller_receipts']),2)
        self.assertNotIn(rogue['record_sha256'],outcome['accepted_controller_receipts'])

    def test_additional_controller_receipt_after_release(self):
        next_candidate=dict(self.candidate)
        next_candidate['src/stygnox/planning.py']=fp('new-controller-after-release')
        origin='3'*64
        body={'schema':'stygnox_controller_run_result_v1','repository_authority':'write',
            'transaction_id':self.state['transaction_id'],'human_gate':None,
            'provider_result':{'status':'PASS'},'next_action':'continue-same-step',
            'preview_sha256':origin,
            'plan_binding':{'plan_hash':self.state['plan_hash'],'current_step':2,
                'repository_mutation_scope':self.state['repository_mutation_scope'],
                'repository_mutation_scope_sha256':replay.digest(self.state['repository_mutation_scope'])},
            'actual_delta':delta(self.candidate,next_candidate),'before_baseline_sha256':'e'*64,'after_baseline_sha256':'a'*64}
        future=record(body)
        self.write(f'controller-run-{origin[:16]}.json',future)
        self.state['continuation_history'].append(record({'plan_hash':self.state['plan_hash'],'step':2,
            'origin_preview_sha256':origin,'before_baseline_sha256':'e'*64,'after_baseline_sha256':'a'*64}))
        result=a.replay_attribution(self.root,self.state,self.original['plan'],next_candidate,pending_receipt=None)
        self.assertEqual(len(result['accepted_controller_receipts']),3)

if __name__=='__main__':unittest.main()
