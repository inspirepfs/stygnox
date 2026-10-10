import copy
import hashlib
import json
import sys
from pathlib import Path
import unittest

from stygnox import direct_interruption_replay as m

def fp(x):return hashlib.sha256(x.encode()).hexdigest()
def record(body,key='record_sha256'):
    out=dict(body);out[key]=m.digest(out);return out

def delta(before,after):
    changes=[]
    for p in sorted(set(before)|set(after)):
        a,b=before.get(p),after.get(p)
        if a==b:continue
        changes.append({'path':p,'kind':'created' if a is None else 'deleted' if b is None else 'modified',
                        'before_fingerprint':a,'after_fingerprint':b})
    return record({'before_manifest_sha256':m.digest(before),'after_manifest_sha256':m.digest(after),'paths':changes},'delta_sha256')

class Tests(unittest.TestCase):
    def setUp(self):
        self.approval={'stygnox.toml':fp('operator-config'), 'src/stygnox/transactions.py':fp('old-tx'),
                       'src/stygnox/planning.py':fp('old-plan'),'tests/test_stygnox_old.py':fp('existing')}
        self.scope=sorted(['src/stygnox/transactions.py','src/stygnox/planning.py','tests/test_stygnox_transaction_renewal.py','tests/test_stygnox_old.py'])
        self.first=dict(self.approval);self.first['src/stygnox/transactions.py']=fp('accepted-first')
        self.second=dict(self.first);self.second['tests/test_stygnox_transaction_renewal.py']=fp('accepted-test')
        self.candidate=dict(self.second);self.candidate['src/stygnox/transactions.py']=fp('failed-turn')
        self.candidate['tests/test_stygnox_transaction_renewal.py']=fp('failed-test')
        self.tx='TX-test';self.planhash='a'*64
        self.steps=[{'test_change_policy':'add-only'},{'test_change_policy':'add-only'}]
        self.state={'status':'APPROVED','active_gate':None,'self_development_grant':None,
                    'approval_repository_manifest':self.approval,'plan_hash':self.planhash,'transaction_id':self.tx,
                    'current_step':2,'approval_baseline_sha256':'b'*64,'step_authority_baseline_sha256':'b'*64,
                    'repository_mutation_scope':self.scope,
                    'plan':{'steps':self.steps,'repository_mutation_scope':self.scope,
                            'repository_mutation_scope_sha256':m.digest(self.scope)},
                    'step_results':[],'continuation_history':[]}
        self.receipts={}
        for idx,(before,after) in enumerate([(self.approval,self.first),(self.first,self.second)]):
            preview=f'{idx+1}'*64
            body={'schema':'stygnox_controller_run_result_v1',
                  'repository_authority':'write','transaction_id':self.tx,
                  'human_gate':None,'provider_result':{'status':'PASS'},'next_action':'continue-same-step',
                  'preview_sha256':preview,
                  'plan_binding':{'plan_hash':self.planhash,'current_step':2,
                                  'repository_mutation_scope':self.scope,
                                  'repository_mutation_scope_sha256':m.digest(self.scope)},
                  'actual_delta':delta(before,after),'before_baseline_sha256':'b'*64,'after_baseline_sha256':'b'*64}
            rec=record(body);self.receipts[preview]=rec
            self.state['continuation_history'].append(record({'plan_hash':self.planhash,'step':2,
                'origin_preview_sha256':preview,'before_baseline_sha256':'b'*64,'after_baseline_sha256':'b'*64}))
        body={'origin_preview_sha256':'c'*64,'plan_hash':self.planhash,'transaction_id':self.tx,
              'predecessor_baseline_sha256':'b'*64,
              'candidate_manifest':self.candidate,'candidate_manifest_sha256':m.digest(self.candidate),
              'last_accepted_manifest_sha256':m.digest(self.second),
              'last_accepted_controller_receipt_sha256':self.receipts['2'*64]['record_sha256'],
              'approval_manifest_sha256':m.digest(self.approval)}
        self.preview=record(body,'preview_sha256')

    def proof(self):return m.verify_reviewed_transition(self.state,self.preview,receipt_loader=self.receipts.__getitem__)
    def test_replay_proves_exact_preturn_and_config(self):
        p=self.proof();self.assertEqual(p['predecessor_manifest'],self.second)
        self.assertTrue(p['operator_config_unchanged'])
        self.assertEqual([a['path'] for a in p['changed_paths']],
            ['src/stygnox/transactions.py','tests/test_stygnox_transaction_renewal.py'])
        self.assertFalse(p['past_provider_success'])
    def test_config_change_refused(self):
        self.preview['candidate_manifest']['stygnox.toml']=fp('interrupted-config')
        self.preview['candidate_manifest_sha256']=m.digest(self.preview['candidate_manifest'])
        self.preview=record({k:v for k,v in self.preview.items() if k!='preview_sha256'},'preview_sha256')
        with self.assertRaisesRegex(m.EvidenceRefused,'operator-owned or out-of-scope'):
            self.proof()
    def test_receipt_tamper_refused(self):
        self.receipts['1'*64]['actual_delta']['paths'][0]['after_fingerprint']=fp('tamper')
        with self.assertRaisesRegex(m.EvidenceRefused,'record_sha256'):
            self.proof()
    def test_missing_middle_receipt_refused(self):
        del self.receipts['1'*64]
        with self.assertRaisesRegex(m.EvidenceRefused,'missing accepted controller receipt'):self.proof()
    def test_receipt_origin_substitution_refused(self):
        self.receipts['1'*64]['preview_sha256']='f'*64
        self.receipts['1'*64]=record({k:v for k,v in self.receipts['1'*64].items() if k!='record_sha256'})
        with self.assertRaisesRegex(m.EvidenceRefused,'identity or step mismatch'):
            self.proof()
    def test_discontinuous_chain_refused(self):
        r=self.receipts['2'*64];r['actual_delta']['before_manifest_sha256']='e'*64
        r['actual_delta']=record({k:v for k,v in r['actual_delta'].items() if k!='delta_sha256'},'delta_sha256')
        self.receipts['2'*64]=record({k:v for k,v in r.items() if k!='record_sha256'})
        with self.assertRaisesRegex(m.EvidenceRefused,'discontinuity'):
            self.proof()
    def test_scope_violation_refused(self):
        self.preview['candidate_manifest']['outside.py']=fp('unreviewed')
        self.preview['candidate_manifest_sha256']=m.digest(self.preview['candidate_manifest'])
        self.preview=record({k:v for k,v in self.preview.items() if k!='preview_sha256'},'preview_sha256')
        with self.assertRaisesRegex(m.EvidenceRefused,'out-of-scope'):
            self.proof()
    def test_approval_time_existing_test_refused(self):
        self.preview['candidate_manifest']['tests/test_stygnox_old.py']=fp('tampered')
        self.preview['candidate_manifest_sha256']=m.digest(self.preview['candidate_manifest'])
        self.preview=record({k:v for k,v in self.preview.items() if k!='preview_sha256'},'preview_sha256')
        with self.assertRaisesRegex(m.EvidenceRefused,'approval-existing'):
            self.proof()
    def test_last_accepted_hash_substitution_refused(self):
        self.preview['last_accepted_manifest_sha256']='d'*64
        self.preview=record({k:v for k,v in self.preview.items() if k!='preview_sha256'},'preview_sha256')
        with self.assertRaisesRegex(m.EvidenceRefused,'last-accepted manifest mismatch'):
            self.proof()
    def test_extra_accepted_receipt_fork_refused(self):
        third=copy.deepcopy(self.receipts['1'*64]);third['preview_sha256']='e'*64
        third=record({k:v for k,v in third.items() if k!='record_sha256'})
        self.receipts['e'*64]=third
        self.state['continuation_history'].append(record({'plan_hash':self.planhash,'step':2,
            'origin_preview_sha256':'e'*64,'before_baseline_sha256':'b'*64,'after_baseline_sha256':'b'*64}))
        with self.assertRaisesRegex(m.EvidenceRefused,'discontinuity'):
            self.proof()
    def test_no_implicit_approval_and_grants_refused(self):
        self.state['self_development_grant']={'grant_sha256':'b'*64}
        with self.assertRaisesRegex(m.EvidenceRefused,'not cleanly approved'):
            self.proof()
    def test_wrong_policy_refused(self):
        self.state['plan']['steps'][1]['test_change_policy']='unknown'
        with self.assertRaisesRegex(m.EvidenceRefused,'test policy'):
            self.proof()
    def test_unbound_manifest_refused(self):
        self.state['approval_repository_manifest']=None
        with self.assertRaisesRegex(m.EvidenceRefused,'manifest missing'):
            self.proof()

    def test_noop_step_continuation_and_qualified_step_replay_in_plan_order(self):
        """Real R3D.2 shape: no-op Step 1 continuation then Step 1 PASS, then Step 2 changes."""
        no_delta=delta(self.approval,self.approval)
        def make(origin, step, action):
            return record({'schema':'stygnox_controller_run_result_v1',
                'repository_authority':'write','transaction_id':self.tx,'human_gate':None,
                'provider_result':{'status':'PASS'},'next_action':action,
                'preview_sha256':origin,'plan_binding':{'plan_hash':self.planhash,
                    'current_step':step,'repository_mutation_scope':self.scope,
                    'repository_mutation_scope_sha256':m.digest(self.scope)},
                'actual_delta':no_delta,'before_baseline_sha256':'b'*64,
                'after_baseline_sha256':'b'*64})
        continuation=make('8'*64,1,'continue-same-step')
        completed=make('9'*64,1,'turn-complete')
        self.receipts['8'*64]=continuation
        self.receipts[completed['record_sha256']]=completed
        self.state['continuation_history'].insert(0,record({
            'plan_hash':self.planhash,'step':1,'origin_preview_sha256':'8'*64,
            'before_baseline_sha256':'b'*64,'after_baseline_sha256':'b'*64}))
        self.state['step_results']=[record({
            'step':1,'result':'PASS','controller_receipt_sha256':completed['record_sha256'],
            'qualified_baseline_sha256':'b'*64})]
        rogue=make('7'*64,2,'continue-same-step')
        rogue['actual_delta']=delta(self.approval,{**self.approval,'src/stygnox/transactions.py':fp('unaccepted-fork')})
        rogue=record({k:v for k,v in rogue.items() if k!='record_sha256'})
        # The rogue is on disk but NOT in accepted history and must not be replayed.
        self.receipts['7'*64]=rogue
        proof=self.proof()
        self.assertEqual(proof['accepted_controller_receipt_sha256s'],[
            continuation['record_sha256'], completed['record_sha256'],
            self.receipts['1'*64]['record_sha256'],self.receipts['2'*64]['record_sha256']])
        self.assertEqual(proof['predecessor_manifest'],self.second)

    def test_noop_manifest_cannot_hide_reordered_accepted_continuations(self):
        self.state['continuation_history'].reverse()
        with self.assertRaisesRegex(m.EvidenceRefused,'reordered|discontinuity'):
            self.proof()

    def test_accepted_continuation_before_baseline_tamper_refused(self):
        item=dict(self.state['continuation_history'][1])
        item['before_baseline_sha256']='c'*64
        self.state['continuation_history'][1]=record({k:v for k,v in item.items() if k!='record_sha256'})
        with self.assertRaisesRegex(m.EvidenceRefused,'continuation does not match'):
            self.proof()

if __name__=='__main__':unittest.main()
