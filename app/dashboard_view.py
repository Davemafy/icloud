from __future__ import annotations

import re


_EXECUTION_CONTRACT_CARD = re.compile(
    r'<div class="card"><h3>Execution contract</h3><pre id="policy">.*?</pre></div>',
    flags=re.DOTALL,
)
_EXECUTION_CONTRACT_BINDING = "$('policy').textContent=JSON.stringify(a.execution_policy||{},null,2);"
_JOURNAL_ANCHOR = '<h2>Live trading journal'
_JOURNAL_CONTEXT_CARD = (
    '<div class="card" style="margin-top:12px">'
    '<h3>Map / execution ownership <span class="pill paper">READ ONLY</span></h3>'
    '<div id="journalContext" class="note">'
    'Waiting for map and execution-ownership context…'
    '</div>'
    '<p class="note"><b>Display only:</b> this panel does not change zone selection, '
    'AI approval, M1 handoff, risk, orders, or Sequence EA execution.</p>'
    '</div>'
)
_READINESS_CARD = (
    '<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div>'
    '<div class="muted">Process checklist — not a prediction.</div></div>'
)
_READINESS_SPLIT = (
    '<div class="card"><h3>HTF setup quality</h3><div class="kpi" id="htfScore">0/6</div>'
    '<div class="muted" id="htfMeta">Location quality only — not entry readiness.</div></div>'
    '<div class="card"><h3>Execution readiness</h3><div class="kpi" id="jScore">WAITING</div>'
    '<div class="muted" id="executionMeta">M1 handoff controls entry timing.</div></div>'
)
_JOURNAL_CONTEXT_SCRIPT = r'''
<script id="journal-context-readonly-script">
(function(){
  function journalState(){
    try{
      return (typeof currentJournal!=='undefined' && currentJournal) ? currentJournal : null;
    }catch(e){
      return null;
    }
  }

  function refreshJournalContext(){
    const out=document.getElementById('journalContext');
    if(!out)return;
    const brief=(document.getElementById('brief')?.textContent||'');
    const ids=(document.getElementById('jIds')?.textContent||'');
    const status=(document.getElementById('jStatus')?.textContent||'WAITING');
    const selected=ids.includes(' • Zone ');
    const rows=Array.from(document.querySelectorAll('#zones tr')).filter(r=>{
      const text=(r.textContent||'').trim();
      return text && !text.includes('Waiting for analysis') && !text.includes('No prompt-qualified primary zones');
    }).length;
    const thesis=brief.match(/Active thesis lock=([A-Z]+) \(([^)]+)\)/i);
    const aiUnavailable=/AI validation unavailable/i.test(brief);
    const parts=[];
    parts.push('Journal status '+status+'.');
    parts.push(rows ? ('Current HTF map: '+rows+' published primary zone'+(rows===1?'':'s')+'.') : 'Current HTF map: no published primary zone.');
    if(thesis){
      parts.push('Execution ownership remains '+thesis[1].toUpperCase()+' ('+thesis[2]+').');
    }
    if(selected){
      parts.push('The beginner journal is showing the currently selected execution zone.');
    }else{
      parts.push('No M1-authorized zone is selected, so the execution-specific journal fields may be blank even though the HTF map above remains valid and visible.');
    }
    if(aiUnavailable){
      parts.push('AI validation is unavailable; this dashboard-only update leaves that execution gate unchanged.');
    }
    out.textContent=parts.join(' ');
  }

  function refreshReadinessSplit(){
    const htf=document.getElementById('htfScore');
    const htfMeta=document.getElementById('htfMeta');
    const exec=document.getElementById('jScore');
    const execMeta=document.getElementById('executionMeta');
    if(!htf || !htfMeta || !exec || !execMeta)return;

    const j=journalState();
    const z=j?.zone||{};
    const checks=j?.checks||{};
    const htfKeys=[
      'fresh_zone',
      'liquidity_in_marked_zone',
      'two_plus_confluences',
      'clear_run',
      'm15_zone_healthy',
      'grade_executable'
    ];
    const htfPassed=htfKeys.reduce((n,k)=>n+(checks[k]===true?1:0),0);
    const hasZone=Boolean(z.zone_id);
    htf.textContent=hasZone ? (htfPassed+'/'+htfKeys.length) : '0/'+htfKeys.length;
    htf.className='kpi '+(hasZone && htfPassed===htfKeys.length?'ok':(hasZone && htfPassed>=4?'warn':''));
    htfMeta.textContent=hasZone
      ? 'HTF location/source quality only. It does not authorize an entry.'
      : 'No execution zone is currently selected. Published HTF map zones may still remain visible above.';

    const allKeys=Object.keys(checks);
    const allPassed=allKeys.reduce((n,k)=>n+(checks[k]===true?1:0),0);
    const checklist=allKeys.length ? ('Checklist '+allPassed+'/'+allKeys.length+'. ') : '';
    const m1=checks.m1_handoff_ready===true;
    const live=checks.live_data_safe===true;
    let state='WAITING FOR LOCATION';
    let cls='warn';
    let meta='No M1 handoff yet.';

    if(!hasZone){
      state='NO M1 SELECTION';
      cls='warn';
      meta='No execution zone is selected. Sequence EA execution remains unavailable.';
    }else if(!m1){
      state='WAITING FOR LOCATION';
      cls='warn';
      meta=checklist+'M1 handoff is NO. The HTF zone can be A/A+ and still be far from executable location.';
    }else if(!live){
      state='SAFETY BLOCKED';
      cls='bad';
      meta=checklist+'M1 handoff is ready, but live spread/snapshot safety is blocking execution.';
    }else{
      state='M1 HANDOFF READY';
      cls='ok';
      meta=checklist+'Location has reached M1 handoff. Sequence EA still applies its normal sweep → MSS/BOS → displacement → value/retrace sequence plus all unchanged execution gates.';
    }

    if(exec.textContent!==state)exec.textContent=state;
    exec.className='kpi '+cls;
    execMeta.textContent=meta;
  }

  refreshJournalContext();
  refreshReadinessSplit();

  const checks=document.getElementById('checks');
  if(checks){
    new MutationObserver(function(){
      refreshReadinessSplit();
      refreshJournalContext();
    }).observe(checks,{childList:true,subtree:true});
  }
  window.setInterval(function(){
    refreshJournalContext();
    refreshReadinessSplit();
  },3000);
})();
</script>
'''.strip()


def compact_dashboard_html(html: str) -> str:
    """Presentation-only cleanup for the human dashboard.

    The raw execution-policy panel is removed, map visibility versus current M1
    execution ownership is explained, and HTF setup quality is separated from
    M1 execution readiness. This function does not alter /mt5/plan,
    deterministic analysis, AI approval, risk controls, or any MT5/Sequence EA
    code path.
    """
    cleaned = _EXECUTION_CONTRACT_CARD.sub("", html, count=1)
    cleaned = cleaned.replace(_EXECUTION_CONTRACT_BINDING, "")

    if 'id="journalContext"' not in cleaned and _JOURNAL_ANCHOR in cleaned:
        cleaned = cleaned.replace(_JOURNAL_ANCHOR, _JOURNAL_CONTEXT_CARD + "\n" + _JOURNAL_ANCHOR, 1)

    if 'id="htfScore"' not in cleaned and _READINESS_CARD in cleaned:
        cleaned = cleaned.replace(_READINESS_CARD, _READINESS_SPLIT, 1)

    if 'id="journal-context-readonly-script"' not in cleaned and "</body>" in cleaned:
        cleaned = cleaned.replace("</body>", _JOURNAL_CONTEXT_SCRIPT + "\n</body>", 1)

    return cleaned
