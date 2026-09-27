from __future__ import annotations

"""Read-only Master Sniper execution-truth overlay for the dashboard.

The overlay consumes fields already serialized by the backend. It never derives
risk, changes zone grades, grants authority, or touches /mt5/plan. Its only job
is to make the dashboard show the same execution eligibility and base-risk truth
that the server and Sequence safety path use.
"""

from typing import Callable

_INSTALLED = False

_SCRIPT = r'''
<script id="master-sniper-execution-truth-script">
(function(){
  const COLS=['Context','Grade authority','Base risk','Authority reason'];

  function text(v){return String(v===undefined||v===null||v===''?'—':v);}
  function esc(v){return text(v).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
  function risk(v){
    const n=Number(v);
    return Number.isFinite(n)?n.toFixed(2)+'%':'—';
  }
  function sideMap(){
    try{return window.tradeZoneExecutionPolicy?.public_zone_map||{};}catch(e){return {};}
  }
  function zones(){
    try{return Array.isArray(window.tradeZoneAnalysisZones)?window.tradeZoneAnalysisZones:[];}catch(e){return [];}
  }
  function eligible(z,pm){
    if(z?.execution_grade_eligible===true || pm?.execution_grade_eligible===true)return true;
    if(z?.execution_grade_eligible===false || pm?.execution_grade_eligible===false)return false;
    return ['A+','A','B+'].includes(String(pm?.grade||z?.grade||'').toUpperCase());
  }
  function reasonFor(z,pm){
    if(!eligible(z,pm))return 'GRADE / AUTHORITY BLOCK';
    const pub=text(pm?.publication_execution_status||'').replaceAll('_',' ');
    if(pub && pub!=='—')return pub+' • AWAITING M1 HANDOFF';
    return 'GRADE ELIGIBLE • AWAITING M1 HANDOFF';
  }
  function refresh(){
    const body=document.getElementById('zones');
    if(!body)return;
    const table=body.closest('table');
    const head=table?.querySelector('thead tr');
    if(!head)return;

    if(!head.querySelector('[data-sniper-truth="1"]')){
      COLS.forEach(label=>{
        const th=document.createElement('th');
        th.dataset.sniperTruth='1';
        th.textContent=label;
        head.appendChild(th);
      });
    }

    const zs=zones();
    const map=sideMap();
    Array.from(body.querySelectorAll('tr')).forEach(row=>{
      const cells=row.querySelectorAll('td');
      if(!cells.length)return;
      if(cells.length===1){cells[0].colSpan=16;return;}
      const zid=String(cells[0]?.dataset?.zoneId||cells[0]?.childNodes?.[0]?.nodeValue||cells[0]?.textContent||'').trim();
      const z=zs.find(x=>String(x?.zone_id||'')===zid);
      if(!z)return;
      const pm=map?.[String(z.original_direction||'').toLowerCase()]||{};
      const ok=eligible(z,pm);
      const values=[
        text(z.risk_context||pm.risk_context).replaceAll('_',' '),
        ok?'ELIGIBLE':'BLOCKED',
        risk(z.base_risk_pct??pm.base_risk_pct),
        reasonFor(z,pm),
      ];
      let truth=Array.from(row.querySelectorAll('td[data-sniper-truth="1"]'));
      while(truth.length<4){
        const td=document.createElement('td');
        td.dataset.sniperTruth='1';
        row.appendChild(td);
        truth.push(td);
      }
      truth.forEach((td,i)=>{
        const v=values[i];
        td.innerHTML=(i===1?'<b class="'+(v==='ELIGIBLE'?'ok':v==='BLOCKED'?'warn':'muted')+'">'+esc(v)+'</b>':esc(v));
      });
    });
  }

  window.tradeZoneRefreshExecutionTruth=refresh;
  window.setTimeout(refresh,250);
  window.setInterval(refresh,3000);
})();
</script>
'''.strip()


def _factory(original: Callable[[str], str]) -> Callable[[str], str]:
    def compact_dashboard_html(html: str) -> str:
        rendered = original(html)
        if 'id="master-sniper-execution-truth-script"' not in rendered and "</body>" in rendered:
            rendered = rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
        return rendered

    return compact_dashboard_html


def install_dashboard_execution_truth() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import dashboard_view

    dashboard_view.compact_dashboard_html = _factory(dashboard_view.compact_dashboard_html)
    _INSTALLED = True
