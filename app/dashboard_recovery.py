from __future__ import annotations

"""Read-only dashboard transport recovery.

The live dashboard historically depended on one SSE payload containing every
section. If any read-only aggregation raised, the EventSource could still be
open while the page remained stuck on CHECKING/Waiting. This layer adds an
independent 3-second REST polling fallback and removes a self-triggering zone
MutationObserver. It does not alter /mt5/plan, analysis selection, M1 handoff,
risk, orders, or Sequence EA execution.
"""

from typing import Callable

_INSTALLED = False

_ZONES_OBSERVERS = (
    r'''  const zones=document.getElementById('zones');
  if(zones){
    new MutationObserver(function(){
      refreshJournalContext();
    }).observe(zones,{childList:true,subtree:true});
  }
''',
    r'''  const zones=document.getElementById('zones');
  if(zones){
    new MutationObserver(function(){
      refreshJournalContext();
      refreshMitigationAudit();
    }).observe(zones,{childList:true,subtree:true});
  }
''',
)

_RECOVERY_SCRIPT = r'''
<script id="dashboard-recovery-polling-script">
(function(){
  let inFlight=false;
  let lastSuccess=0;

  function safeEsc(v){
    return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  }
  function safeNum(v,d=3){
    if(v===null||v===undefined||v===''||Number.isNaN(Number(v)))return '—';
    return Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
  }
  function setConnection(ok){
    const el=document.getElementById('conn');
    if(!el)return;
    el.textContent=ok?'LIVE':'RECONNECTING';
    el.className='badge '+(ok?'ok':'warn');
  }
  async function getJson(url,timeoutMs=1800){
    const ctl=new AbortController();
    const timer=setTimeout(()=>ctl.abort(),timeoutMs);
    try{
      const r=await fetch(url,{cache:'no-store',headers:{'Accept':'application/json'},signal:ctl.signal});
      if(!r.ok)throw new Error(url+' HTTP '+r.status);
      return await r.json();
    }finally{
      clearTimeout(timer);
    }
  }
  function renderAnalysisRecovery(a){
    if(!a || typeof a!=='object')return;
    window.tradeZoneExecutionPolicy=a.execution_policy||{};
    window.tradeZoneAnalysisZones=Array.isArray(a.zones)?a.zones:[];
    window.tradeZoneAuditIdentity='audit_zone_id';

    const brief=document.getElementById('brief');
    if(brief)brief.textContent=a.trader_brief||'—';

    const zones=document.getElementById('zones');
    if(zones){
      const rows=Array.isArray(a.zones)?a.zones:[];
      zones.innerHTML=rows.length?rows.map(z=>{
        const pm=a?.execution_policy?.public_zone_map?.[String(z.original_direction||'').toLowerCase()]||{};
        const audit=z.mitigation_audit||{};
        const sg=pm.structural_grade||z.grade||'—';
        const cg=pm.grade||z.grade||'—';
        const reason=pm.grade_degrade_reason&&pm.grade_degrade_reason!=='NONE'?String(pm.grade_degrade_reason).replaceAll('_',' '):'NONE';
        const gap=pm.structural_aplus_missing&&pm.structural_aplus_missing!=='NONE'?String(pm.structural_aplus_missing).replaceAll('_',' '):'NONE';
        const qm=pm.qualified_mitigations??audit.qualified_mitigations??z.touch_count??'—';
        const raw=pm.raw_core_touch_episodes??audit.raw_core_contact_episodes_before_invalidation;
        const pub=pm.publication_execution_status||'UNKNOWN';
        const pubAt=pm.geometry_published_at?new Date(Number(pm.geometry_published_at)*1000).toLocaleString():'—';
        const liveAt=pm.live_core_touched_at?new Date(Number(pm.live_core_touched_at)*1000).toLocaleString():'—';
        const baseQ=pm.publication_qualified_mitigations??'—';
        const baseR=pm.publication_raw_core_contacts??'—';
        return `<tr><td>${safeEsc(z.zone_id)}</td><td>${safeEsc(z.original_direction)}</td><td>${safeEsc(z.flip_direction)}</td><td>${safeEsc(z.state)}</td><td>${safeNum(z.core_low)}–${safeNum(z.core_high)}<br><span class="muted">${safeEsc(z.core_method||'')}</span></td><td>${safeNum(z.zone_low)}–${safeNum(z.zone_high)}</td><td><b>${safeEsc(sg)}</b></td><td><b>${safeEsc(cg)}</b></td><td>${safeEsc(reason)}<br><span class="muted">A+ gap: ${safeEsc(gap)}</span></td><td><b>${safeEsc(String(pub).replaceAll('_',' '))}</b><br><span class="muted">published ${safeEsc(pubAt)} • baseline ${safeEsc(baseQ)} qualified / ${safeEsc(baseR)} raw • live touch ${safeEsc(liveAt)}</span></td><td>${safeEsc(z.setup_type)}</td><td>${safeEsc(qm)} qualified${raw===undefined?'':(' / '+safeEsc(raw)+' raw')}</td></tr>`;
      }).join(''):'<tr><td colspan="12" class="muted">No prompt-qualified primary zones.</td></tr>';
    }

    try{
      if(typeof renderRejected==='function')renderRejected(a);
    }catch(e){}
  }

  async function refreshDashboardFallback(){
    if(inFlight)return;
    inFlight=true;
    let success=0;

    // Primary observability path: one short-timeout, query-only endpoint that
    // bypasses the normal process-wide database lock and heavy aggregators.
    try{
      const ro=await getJson('/dashboard/read-only-state',1500);
      if(ro?.system && typeof renderSystem==='function')renderSystem(ro.system);
      if(ro?.analysis)renderAnalysisRecovery(ro.analysis);
      if(ro?.system || ro?.analysis)success++;
    }catch(e){}

    // Journal is useful but optional. It must never be able to freeze version
    // truth or mitigation-audit visibility.
    try{
      const j=await getJson('/journal/current',1200);
      if(typeof renderJournal==='function')renderJournal(j);
      success++;
    }catch(e){}

    // Compatibility fallbacks for older/degraded deployments. Every request is
    // bounded so one blocked endpoint cannot leave inFlight stuck forever.
    if(success===0){
      try{
        const sys=await getJson('/system/status',1200);
        if(typeof renderSystem==='function')renderSystem(sys);
        success++;
      }catch(e){}
      try{
        const a=await getJson('/analysis',1200);
        renderAnalysisRecovery(a);
        success++;
      }catch(e){}
    }

    if(success>0){
      lastSuccess=Date.now();
      setConnection(true);
    }else if(!lastSuccess || Date.now()-lastSuccess>10000){
      setConnection(false);
      const kpi=document.getElementById('healthKpi');
      const meta=document.getElementById('healthMeta');
      if(kpi && kpi.textContent==='CHECKING'){
        kpi.textContent='CONNECTION ISSUE';
        kpi.className='kpi warn';
      }
      if(meta && (meta.textContent==='Waiting…' || meta.textContent==='Waiting...')){
        meta.textContent='Live dashboard data is reconnecting…';
      }
    }

    inFlight=false;
  }

  window.tradeZoneDashboardRefresh=refreshDashboardFallback;
  window.setTimeout(refreshDashboardFallback,150);
  window.setInterval(refreshDashboardFallback,3000);
})();
</script>
'''.strip()


def _dashboard_factory(original: Callable[[str], str]) -> Callable[[str], str]:
    def compact_dashboard_html(html: str) -> str:
        cleaned = original(html)

        # The ownership view already refreshes on a 3-second timer. Observing the
        # same zone subtree while also writing ownership tags into that subtree can
        # create a self-triggering MutationObserver loop on some browsers.
        for observer in _ZONES_OBSERVERS:
            cleaned = cleaned.replace(observer, "")

        if 'id="dashboard-recovery-polling-script"' not in cleaned and "</body>" in cleaned:
            cleaned = cleaned.replace("</body>", _RECOVERY_SCRIPT + "\n</body>", 1)
        return cleaned

    return compact_dashboard_html


def install_dashboard_recovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import dashboard_view

    dashboard_view.compact_dashboard_html = _dashboard_factory(dashboard_view.compact_dashboard_html)
    _INSTALLED = True
