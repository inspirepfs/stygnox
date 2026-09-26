(() => {
  'use strict';
  const state = {
    snapshot: null,
    csrf: document.querySelector('meta[name="stygnox-csrf"]')?.content || '',
    policySeeded: false,
    lifecyclePreview: null
  };
  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { const el=$(id); if(el) el.textContent = value == null || value === '' ? '—' : String(value); };
  const setValue = (id, value) => { const el=$(id); if(el) el.value = value == null ? '' : String(value); };
  const badge = (id, value, tone='') => { const el=$(id); if(!el) return; el.className='state-badge '+tone; el.textContent=String(value ?? '—'); };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const val=(id)=>($(id)?.value||'').trim();
  const numeric=(id)=>{ const raw=val(id); return raw==='' ? undefined : Number(raw); };
  const lines=(id)=>val(id).split(/\r?\n/).map((row)=>row.trim()).filter(Boolean);

  function attributionRows(model){
    const host=$('attribution'); if(!host) return;
    const labels = [
      ['operator_baseline','Operator baseline'],['controller_native','Stygnox native'],['runtime_only','Runtime only'],['external','External / foreign'],['unresolved','Unresolved overlap']
    ];
    host.innerHTML = labels.map(([key,label]) => {
      const row=model?.categories?.[key] || {count:0,paths:[]};
      const paths=(row.paths||[]).slice(0,12).join('\n') || 'none';
      return `<div class="attribution-row"><b>${esc(label)}</b><span class="count">${Number(row.count||0)}</span><code>${esc(paths)}</code></div>`;
    }).join('');
  }

  function authorityEvidence(model){
    const host=$('authority-evidence'); if(!host) return;
    const rows=Array.isArray(model?.human_decisions) ? model.human_decisions.slice(-5).reverse() : [];
    if(!rows.length){ host.textContent='No recent authority evidence.'; return; }
    host.innerHTML=rows.map((item) => {
      const kind=esc(item?.kind || 'decision');
      const authority=esc(item?.repository_authority || '—');
      const digest=esc(item?.record_sha256 || '—');
      return `<div class="attribution-row"><b>${kind}</b><span class="count">•</span><code>${authority}\n${digest}</code></div>`;
    }).join('');
  }

  function lifecycleProgress(lifecycle){
    const p=lifecycle?.progress || {};
    if(!p.total_steps) return '—';
    return `${p.completed_steps||0}/${p.total_steps} · ${p.percent_complete||0}%`;
  }

  function lifecycleBlockers(lifecycle){
    const host=$('lifecycle-blockers'); if(!host) return;
    const rows=Array.isArray(lifecycle?.blockers) ? lifecycle.blockers : [];
    if(!rows.length){ host.innerHTML='<div class="lifecycle-empty success">No lifecycle blockers.</div>'; return; }
    host.innerHTML=rows.map((row)=>{
      const detail=row?.detail == null ? '' : (typeof row.detail==='string' ? row.detail : JSON.stringify(row.detail));
      return `<div class="lifecycle-row blocker"><b>${esc(row?.code||'BLOCKED')}</b><span>${esc(detail)}</span></div>`;
    }).join('');
  }

  function nextActionIdentity(lifecycle){
    return JSON.stringify((Array.isArray(lifecycle?.next_actions)?lifecycle.next_actions:[]).map((row)=>row?.action||''));
  }

  function lifecycleActions(lifecycle){
    const host=$('lifecycle-actions'); if(!host) return;
    const rows=Array.isArray(lifecycle?.next_actions) ? lifecycle.next_actions : [];
    if(!rows.length){ host.innerHTML='<div class="lifecycle-empty">No authority-valid next action.</div>'; return; }
    host.innerHTML=rows.map((row)=>{
      const action=String(row?.action||'');
      return `<div class="lifecycle-row action"><div><b>${esc(action)}</b><span>${esc(row?.reason||'')}</span></div><button class="sn-btn sn-btn--secondary lifecycle-action" data-lifecycle-action="${esc(action)}" onclick="stygnoxLifecycleAction('${esc(action)}')">Run</button></div>`;
    }).join('');
  }

  function seedLifecycleContext(lifecycle){
    const gate=lifecycle?.human_gate?.gate || {};
    const selfCandidates=Array.isArray(gate?.self_development_candidates) ? gate.self_development_candidates.map((row)=>row?.path).filter(Boolean) : [];
    if(!val('lifecycle-paths') && selfCandidates.length) setValue('lifecycle-paths', selfCandidates.join('\n'));
    const pending=lifecycle?.reconciliation?.pending_paths || [];
    if(!val('lifecycle-pending-paths') && pending.length) setValue('lifecycle-pending-paths', pending.join('\n'));
    const progress=lifecycle?.progress || {};
    if(progress.repository_authority && !val('lifecycle-repo-authority')) setValue('lifecycle-repo-authority', progress.repository_authority);
  }

  function renderLifecycle(lifecycle){
    lifecycle=lifecycle || {};
    const p=lifecycle.progress || {};
    const current=p.current || {};
    const gate=lifecycle.human_gate?.gate || {};
    const recovery=lifecycle.recovery || {};
    const recon=lifecycle.reconciliation || {};
    const selfdev=lifecycle.self_development || {};
    const qual=lifecycle.qualification || {};
    const fin=lifecycle.finalization || {};
    const usage=lifecycle.usage || {};
    const usageSummary=usage.summary || {};
    const eff=lifecycle.efficiency || {};
    const latest=lifecycle.latest_controller_turn || {};
    const phase=lifecycle.phase || 'UNKNOWN';
    const attention=Boolean(lifecycle.attention_required);
    badge('lifecycle-phase', phase, phase==='PUSHED'||phase==='READ_ONLY_COMPLETE'?'success':attention?'warn':'info');
    text('lifecycle-progress', lifecycleProgress(lifecycle));
    badge('lifecycle-attention', attention?'YES':'NO', attention?'warn':'success');
    text('lifecycle-step', current.title ? `${p.current_step||'-'}/${p.total_steps||'-'} · ${current.title}` : (p.current_step ? `${p.current_step}/${p.total_steps||'-'}` : '—'));
    text('lifecycle-plan', p.plan_hash ? `${String(p.plan_hash).slice(0,16)}… · ${p.repository_authority||'—'}` : '—');
    text('lifecycle-latest-turn', latest.next_action ? `${latest.next_action} · ${latest.efficiency_status||'—'}` : '—');
    lifecycleBlockers(lifecycle);
    lifecycleActions(lifecycle);
    text('lifecycle-gate', gate.gate_id ? `${gate.gate_id} · ${gate.kind||'—'}` : 'none');
    text('lifecycle-recovery', `${recovery.required?'REQUIRED':'clear'} · transaction ${recovery.transaction_state||'—'} · scheduler ${recovery.scheduler_state||'—'}`);
    text('lifecycle-reconciliation', `pending ${(recon.pending_paths||[]).length} · stale ${(recon.stale_paths||[]).length}`);
    text('lifecycle-self-development', `${selfdev.active_grant?'ACTIVE':'none'} · history ${selfdev.grant_history_count||0}`);
    text('lifecycle-qualification', `${qual.plan_status||'—'} · current ${qual.qualified_current_repository?'YES':'NO'}`);
    text('lifecycle-finalization', `${fin.plan_status||'—'} · commit ${fin.commit_sha ? String(fin.commit_sha).slice(0,12) : '—'}`);
    text('lifecycle-efficiency', `${eff.mode||'—'} · latest ${eff.latest?.status||latest.efficiency_status||'—'}`);
    text('lifecycle-usage', `turns ${usageSummary.turn_count ?? usageSummary.records ?? 0} · input ${usageSummary.input_tokens||0} · output ${usageSummary.output_tokens||0}`);
    seedLifecycleContext(lifecycle);
    if(state.lifecyclePreview && state.lifecyclePreview.actionsIdentity!==nextActionIdentity(lifecycle)) clearLifecyclePreview();
  }

  function seedPolicyInputs(effective, policy){
    if(state.policySeeded) return;
    setValue('policy-provider', effective.provider || '');
    setValue('policy-model-input', effective.model || '');
    setValue('policy-effort-input', effective.effort || '');
    setValue('policy-reviewer', policy?.review?.reviewer || effective.reviewer || '');
    setValue('policy-efficiency', effective.efficiency_mode || '');
    setValue('policy-reserve', effective.reserve_percent ?? '');
    setValue('policy-wait', effective.wait_for_limits == null ? '' : String(Boolean(effective.wait_for_limits)));
    setValue('policy-poll', effective.usage_poll_seconds ?? '');
    setValue('policy-loops', effective.max_loops ?? '');
    state.policySeeded=true;
  }

  function render(s){
    state.snapshot=s;
    const tx=s.transaction || {};
    const ctl=s.controller || {};
    const policy=s.execution_policy || {};
    const effective=policy.policy || {};
    const enabled=Boolean(ctl.controller_execution_enabled ?? ctl.enabled);
    const txState=tx.state || 'NONE';

    text('product-name', s.identity);
    text('product-version', s.product_version);
    text('profile-name', s.profile?.name || 'stygnox-default');
    text('project-path', s.worktree);
    text('journey', s.current_baseline?.journey);
    text('head', s.current_baseline?.head ? String(s.current_baseline.head).slice(0,12) : '(unborn)');
    text('operator', s.operator || 'not adopted');
    text('authority-summary', `${s.adopted ? 'ADOPTED' : 'NOT ADOPTED'} · controller ${enabled ? 'ENABLED' : 'DISABLED'}`);
    text('transaction-summary', txState);

    text('model', effective.model || 'neutral');
    text('effort', effective.effort || 'neutral');
    text('live', enabled ? 'controller active' : 'idle');
    text('pid', s.server?.pid || '—');

    text('provider', effective.provider || 'neutral');
    text('policy-model', effective.model || 'neutral');
    text('policy-effort', effective.effort || 'neutral');
    text('efficiency', effective.efficiency_mode || '—');
    text('reserve', effective.reserve_percent == null ? '—' : `${effective.reserve_percent}%`);
    text('wait-limits', effective.wait_for_limits == null ? '—' : String(Boolean(effective.wait_for_limits)));
    text('usage-poll', effective.usage_poll_seconds == null ? '—' : `${effective.usage_poll_seconds}s`);
    text('max-loops', effective.max_loops ?? '—');
    text('policy-reviewer', policy?.review?.reviewer || effective.reviewer || '—');
    text('policy-approved', policy?.error ? `ERROR: ${policy.error}` : (policy?.approved == null ? '—' : String(Boolean(policy.approved))));
    seedPolicyInputs(effective, policy);

    const evidence=s.evidence_summary || {};
    text('runtime-directory', evidence.runtime_directory || '.stygnox');
    text('runtime-count', evidence.runtime_files ?? s.attribution?.categories?.runtime_only?.count ?? 0);
    text('controller-receipts', evidence.latest_controller_receipts ?? 0);
    text('source-tree-fallback', evidence.source_tree_dependency === false ? 'NO' : 'UNKNOWN');
    text('legacy-delegate', evidence.legacy_ralph_delegate === false ? 'NO' : 'UNKNOWN');

    renderLifecycle(s.lifecycle || {});
    attributionRows(s.attribution || {});
    authorityEvidence(s.attribution || {});
    const ev=$('evidence-json'); if(ev) ev.textContent=JSON.stringify(evidence, null, 2);
    if(!val('operator-input') && s.operator) setValue('operator-input', s.operator);
  }

  async function refresh(){
    try{
      const r=await fetch('/api/snapshot',{headers:{'Accept':'application/json'}}); const j=await r.json();
      if(!r.ok) throw new Error(j.error||`HTTP ${r.status}`); render(j);
    }catch(err){ setNotice(String(err),'error'); }
  }

  function setNotice(message,tone=''){ const el=$('notice'); if(!el) return; el.className='notice '+tone; el.textContent=message||''; }

  function capturePreview(name, result){
    const digest=result?.preview_sha256;
    if(!digest) return;
    if(name==='adopt.preview') setValue('preview-input', digest);
    if(name==='recovery.preview') setValue('recovery-preview-input', digest);
    if(name==='policy.preview' || name==='policy.preview-reset') setValue('policy-preview-input', digest);
    if(name==='controller.run-preview') setValue('run-preview-input', digest);
  }

  async function action(name,payload,backendName=name){
    setNotice(`Running ${name}…`);
    const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Stygnox-CSRF':state.csrf},body:JSON.stringify({action:backendName,payload})});
    const j=await r.json();
    if(!r.ok || !j.ok){ setNotice(j.error||`HTTP ${r.status}`,'error'); return null; }
    setNotice(`${name}: PASS`,'success');
    const out=$('action-result'); if(out) out.textContent=JSON.stringify(j.result,null,2);
    capturePreview(name, j.result);
    await refresh(); return j.result;
  }

  function policyPayload(operator){
    const payload={operator};
    const strings=[['provider','policy-provider'],['model','policy-model-input'],['effort','policy-effort-input'],['reviewer','policy-reviewer'],['efficiency_mode','policy-efficiency']];
    strings.forEach(([key,id])=>{ const raw=val(id); if(raw!=='') payload[key]=raw; });
    const reserve=numeric('policy-reserve'); if(reserve!==undefined) payload.reserve_percent=reserve;
    const poll=numeric('policy-poll'); if(poll!==undefined) payload.usage_poll_seconds=poll;
    const loops=numeric('policy-loops'); if(loops!==undefined) payload.max_loops=loops;
    const wait=val('policy-wait'); if(wait!=='') payload.wait_for_limits=wait==='true';
    return payload;
  }

  function lifecycleIdentity(){
    const lifecycle=state.snapshot?.lifecycle || {};
    const progress=lifecycle.progress || {};
    const gate=lifecycle.human_gate?.gate || {};
    return {lifecycle,progress,gate,operator:val('operator-input') || state.snapshot?.operator || ''};
  }

  function lifecyclePayload(name){
    const {lifecycle,progress,gate,operator}=lifecycleIdentity();
    const canonicalRow=(lifecycle?.next_actions||[]).find((row)=>row?.action===name) || {};
    const payload={operator};
    if(progress.plan_hash) payload.plan_hash=progress.plan_hash;
    if(gate.gate_id) payload.gate_id=gate.gate_id;
    if(name.startsWith('plan.propose')){
      payload.goal=val('lifecycle-goal'); payload.repository_authority=val('lifecycle-repo-authority')||'write';
      const min=numeric('lifecycle-min-steps'), max=numeric('lifecycle-max-steps');
      if(min!==undefined) payload.min_steps=min; if(max!==undefined) payload.max_steps=max;
      if(name.startsWith('plan.propose-replacement')) payload.retirement_record_id=canonicalRow.retirement_record_id || lifecycle?.plan?.plan?.retirement_record_id || '';
    }
    if(name.startsWith('plan.retire')){ payload.reason=val('lifecycle-reason'); payload.disposition=val('lifecycle-retirement-disposition')||'carry-forward'; }
    if(name.startsWith('gate.steer')){ payload.direction=val('lifecycle-direction'); payload.allow_new_tests=lines('lifecycle-allow-tests'); }
    if(name.startsWith('gate.resume') || name.startsWith('gate.resolve') || name==='plan.reject') payload.reason=val('lifecycle-reason');
    if(name.startsWith('self-development.')){ payload.paths=lines('lifecycle-paths'); payload.reason=val('lifecycle-reason'); }
    if(name.startsWith('scheduler.recover')) payload.pending_paths=lines('lifecycle-pending-paths');
    if(name==='controller.run-preview' || name==='controller.run'){
      payload.objective=progress.current?.objective || val('objective');
      payload.repository_authority=progress.repository_authority || val('repo-authority') || 'read-only';
    }
    if(name.startsWith('finalization.commit')) payload.message=val('lifecycle-message');
    if(name.startsWith('finalization.reconcile-commit')){ payload.commit_sha=val('lifecycle-commit-sha'); payload.reason=val('lifecycle-reason'); }
    if(name==='adopt.preview') payload.dirty_evidence=val('dirty-evidence')||null;
    if(name==='recovery.preview' || name==='recovery.restore') payload.post_handoff_disposition='discard';
    return payload;
  }

  const previewPairs={
    'adopt.preview':['adopt.handoff','HANDOFF'],
    'recovery.preview':['recovery.restore','RESTORE'],
    'plan.propose-preview':['plan.propose','PROPOSE'],
    'plan.propose-replacement-preview':['plan.propose-replacement','PROPOSE'],
    'plan.retire-preview':['plan.retire','CARRY_FORWARD'],
    'gate.steer-preview':['gate.steer','STEER'],
    'gate.resume-preview':['gate.resume','RESUME'],
    'gate.resolve-preview':['gate.resolve','RESOLVE'],
    'scheduler.run-preview':['scheduler.run','SCHEDULE'],
    'scheduler.recover-preview':['scheduler.recover','RECOVER'],
    'self-development.authorize-preview':['self-development.authorize','AUTHORIZE'],
    'qualification.preview':['qualification.run','QUALIFY'],
    'qualification.requalify-preview':['qualification.requalify','REQUALIFY'],
    'finalization.commit-preview':['finalization.commit','COMMIT'],
    'finalization.push-preview':['finalization.push','PUSH'],
    'finalization.reconcile-commit-preview':['finalization.reconcile-commit','RECONCILE_COMMIT'],
    'finalization.reconcile-push-preview':['finalization.reconcile-push','RECONCILE_PUSH']
  };
  const directConfirm={
    'transaction.begin':'BEGIN','controller.activate':'ACTIVATE','plan.approve':'APPROVE','plan.reject':'REJECT'
  };

  function clearLifecyclePreview(){ state.lifecyclePreview=null; setValue('lifecycle-preview',''); const host=$('lifecycle-confirm'); if(host) host.innerHTML=''; }

  function renderLifecycleConfirmation(){
    const host=$('lifecycle-confirm'); if(!host) return;
    const row=state.lifecyclePreview;
    if(!row){ host.innerHTML=''; return; }
    host.innerHTML=`<button class="sn-btn sn-btn--primary" onclick="stygnoxConfirmLifecycleAction()">Confirm ${esc(row.action)}</button><span class="confirmation-note">Exact preview ${esc(row.preview.slice(0,16))}… · confirmation ${esc(row.confirm)}</span>`;
  }

  window.stygnoxLifecycleAction = async (name) => {
    const canonical=(state.snapshot?.lifecycle?.next_actions||[]).map((row)=>row?.action);
    if(!canonical.includes(name)){ setNotice(`Lifecycle action ${name} is not canonical for the current snapshot`,'error'); return null; }
    const payload=lifecyclePayload(name);
    if(directConfirm[name]) payload.confirm=directConfirm[name];
    const result=await action(name,payload);
    if(!result) return null;
    const pair=previewPairs[name];
    if(pair && result.preview_sha256){
      state.lifecyclePreview={source:name,action:pair[0],confirm:result.confirmation||pair[1],preview:result.preview_sha256,payload:lifecyclePayload(pair[0]),actionsIdentity:nextActionIdentity(state.snapshot?.lifecycle||{})};
      setValue('lifecycle-preview',result.preview_sha256); renderLifecycleConfirmation();
    } else if(!pair) clearLifecyclePreview();
    return result;
  };

  window.stygnoxConfirmLifecycleAction = async () => {
    const row=state.lifecyclePreview; if(!row) return null;
    const payload={...row.payload,preview:row.preview,confirm:row.confirm};
    const result=await action(row.action,payload);
    if(result) clearLifecyclePreview();
    return result;
  };

  window.stygnoxAction = async (name) => {
    const operator=val('operator-input');
    if(name==='adopt.preview') return action(name,{operator,dirty_evidence:val('dirty-evidence')||null});
    if(name==='adopt.abort') return action(name,{operator,dirty_evidence:val('dirty-evidence')||null,preview:val('preview-input')});
    if(name==='adopt.handoff') return action(name,{operator,dirty_evidence:val('dirty-evidence')||null,preview:val('preview-input'),confirm:'HANDOFF'});
    if(name==='transaction.begin') return action(name,{operator,confirm:'BEGIN'});
    if(name==='transaction.stop') return action(name,{operator,reason:val('stop-reason')||'operator-abort',confirm:'STOP'});
    if(name==='recovery.preview') return action(name,{operator,post_handoff_disposition:'discard'});
    if(name==='recovery.restore') return action(name,{operator,preview:val('recovery-preview-input'),confirm:'RESTORE',post_handoff_disposition:'discard'});
    if(name==='policy.preview') return action(name,policyPayload(operator));
    if(name==='policy.set') return action(name,{...policyPayload(operator),preview:val('policy-preview-input'),confirm:'SET'});
    if(name==='policy.preview-reset') return action(name,{operator,reset:true},'policy.preview');
    if(name==='policy.reset') return action(name,{operator,preview:val('policy-preview-input'),confirm:'RESET'});
    if(name==='controller.activate') return action(name,{operator,confirm:'ACTIVATE'});
    if(name==='controller.deactivate') return action(name,{operator,confirm:'DEACTIVATE'});
    if(name==='controller.run-preview') return action(name,{operator,objective:val('objective'),repository_authority:val('repo-authority')||'read-only'});
    if(name==='controller.run') return action(name,{operator,objective:val('objective'),repository_authority:val('repo-authority')||'read-only',preview:val('run-preview-input'),confirm:'RUN'});
  };

  window.addEventListener('DOMContentLoaded',()=>{ refresh(); setInterval(refresh,5000); });
})();
