(() => {
  'use strict';
  const state = {
    snapshot: null,
    csrf: document.querySelector('meta[name="stygnox-csrf"]')?.content || '',
    policySeeded: false
  };
  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { const el=$(id); if(el) el.textContent = value == null || value === '' ? '—' : String(value); };
  const setValue = (id, value) => { const el=$(id); if(el) el.value = value == null ? '' : String(value); };
  const badge = (id, value, tone='') => { const el=$(id); if(!el) return; el.className='state-badge '+tone; el.textContent=String(value ?? '—'); };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

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

    badge('adoption-state', s.adopted ? 'ADOPTED' : 'NOT ADOPTED', s.adopted ? 'success' : 'warn');
    badge('transaction-state', txState, txState==='ACTIVE'?'success':txState==='STOPPED'?'warn':'');
    badge('controller-state', enabled?'ACTIVE':'INACTIVE', enabled?'success':'');
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

  const val=(id)=>($(id)?.value||'').trim();
  const numeric=(id)=>{ const raw=val(id); return raw==='' ? undefined : Number(raw); };
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
