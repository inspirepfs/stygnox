(() => {
  'use strict';
  const state = { snapshot: null, csrf: document.querySelector('meta[name="stygnox-csrf"]')?.content || '' };
  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { const el=$(id); if(el) el.textContent = value == null || value === '' ? '—' : String(value); };
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
  function render(s){
    state.snapshot=s;
    const tx=s.transaction || {};
    const ctl=s.controller || {};
    const policy=s.execution_policy || {};
    const effective=policy.policy || {};
    text('project-path', s.worktree);
    text('journey', s.current_baseline?.journey);
    text('head', s.current_baseline?.head ? String(s.current_baseline.head).slice(0,12) : '(unborn)');
    text('operator', s.operator || 'not adopted');
    badge('adoption-state', s.adopted ? 'ADOPTED' : 'NOT ADOPTED', s.adopted ? 'success' : 'warn');
    const txState=tx.state || 'NONE'; badge('transaction-state', txState, txState==='ACTIVE'?'success':txState==='STOPPED'?'warn':'');
    const enabled=Boolean(ctl.enabled); badge('controller-state', enabled?'ACTIVE':'INACTIVE', enabled?'success':'');
    text('model', effective.model || 'neutral'); text('effort', effective.effort || 'neutral');
    text('live', enabled ? 'controller active' : 'idle'); text('pid', s.server?.pid || '—');
    text('provider', effective.provider || 'neutral'); text('reserve', effective.reserve_percent ?? '—');
    text('wait-limits', effective.wait_for_limits == null ? '—' : String(Boolean(effective.wait_for_limits)));
    text('runtime-count', s.attribution?.categories?.runtime_only?.count ?? 0);
    attributionRows(s.attribution || {});
    const ev=$('evidence-json'); if(ev) ev.textContent=JSON.stringify(s.evidence_summary || {}, null, 2);
  }
  async function refresh(){
    try{
      const r=await fetch('/api/snapshot',{headers:{'Accept':'application/json'}}); const j=await r.json();
      if(!r.ok) throw new Error(j.error||`HTTP ${r.status}`); render(j);
    }catch(err){ setNotice(String(err),'error'); }
  }
  function setNotice(message,tone=''){ const el=$('notice'); if(!el) return; el.className='notice '+tone; el.textContent=message||''; }
  async function action(name,payload){
    setNotice(`Running ${name}…`);
    const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Stygnox-CSRF':state.csrf},body:JSON.stringify({action:name,payload})});
    const j=await r.json();
    if(!r.ok || !j.ok){ setNotice(j.error||`HTTP ${r.status}`,'error'); return null; }
    setNotice(`${name}: PASS`,'success');
    const out=$('action-result'); if(out) out.textContent=JSON.stringify(j.result,null,2);
    await refresh(); return j.result;
  }
  const val=(id)=>($(id)?.value||'').trim();
  window.stygnoxAction = async (name) => {
    const operator=val('operator-input');
    if(name==='adopt.preview') return action(name,{operator,dirty_evidence:val('dirty-evidence')||null});
    if(name==='adopt.handoff') return action(name,{operator,dirty_evidence:val('dirty-evidence')||null,preview:val('preview-input'),confirm:'HANDOFF'});
    if(name==='transaction.begin') return action(name,{operator,confirm:'BEGIN'});
    if(name==='transaction.stop') return action(name,{operator,reason:val('stop-reason')||'operator-abort',confirm:'STOP'});
    if(name==='recovery.preview') return action(name,{operator,post_handoff_disposition:'discard'});
    if(name==='recovery.restore') return action(name,{operator,preview:val('recovery-preview-input'),confirm:'RESTORE',post_handoff_disposition:'discard'});
    if(name==='controller.activate') return action(name,{operator,confirm:'ACTIVATE'});
    if(name==='controller.deactivate') return action(name,{operator,confirm:'DEACTIVATE'});
    if(name==='controller.run-preview') return action(name,{operator,objective:val('objective'),repository_authority:val('repo-authority')||'read-only'});
    if(name==='controller.run') return action(name,{operator,objective:val('objective'),repository_authority:val('repo-authority')||'read-only',preview:val('run-preview-input'),confirm:'RUN'});
  };
  window.addEventListener('DOMContentLoaded',()=>{ refresh(); setInterval(refresh,5000); });
})();
