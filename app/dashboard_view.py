from __future__ import annotations

import re


_EXECUTION_CONTRACT_CARD = re.compile(
    r'<div class="card"><h3>Execution contract</h3><pre id="policy">.*?</pre></div>',
    flags=re.DOTALL,
)
_EXECUTION_CONTRACT_BINDING = "$('policy').textContent=JSON.stringify(a.execution_policy||{},null,2);"
_EXECUTION_POLICY_BINDING = "window.tradeZoneExecutionPolicy=a.execution_policy||{};"
_FRESHNESS_LABEL_BINDING = "fresh_zone:'Fresh zone (0–1 touch)'"
_FRESHNESS_LABEL_REPLACEMENT = (
    "fresh_zone:(z.zone_id?(z.zone_id+' freshness (0–1 touch)'):"
    "'Selected-zone freshness (0–1 touch)')"
)
_JOURNAL_ANCHOR = '<h2>Live trading journal'
_JOURNAL_CONTEXT_CARD = (
    '<div class="card" style="margin-top:12px">'
    '<h3>Map / execution ownership <span class="pill paper">READ ONLY</span></h3>'
    '<div class="kpi" id="ownershipState">WAITING</div>'
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
    '<div class="card"><h3>Sequence execution gate <span class="pill paper">LIVE DEBUG</span></h3>'
    '<div class="kpi" id="sequenceGate">WAITING</div>'
    '<div class="muted" id="sequenceGateMeta">Waiting for Sequence heartbeat telemetry.</div></div>'
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

  function policyState(){
    try{
      return window.tradeZoneExecutionPolicy || {};
    }catch(e){
      return {};
    }
  }

  function activeThesis(){
    const p=policyState();
    const t=p && typeof p.active_thesis==='object' ? p.active_thesis : {};
    return t || {};
  }

  function nextObjective(t){
    const dir=String(t?.direction||'').toUpperCase();
    const best=Number(t?.best_price);
    const haveBest=Number.isFinite(best) && best>0;
    for(const key of ['target1','target2','target3']){
      const target=Number(t?.[key]);
      if(!Number.isFinite(target) || target<=0)continue;
      const reached=haveBest && (
        (dir==='SELL' && best<=target) ||
        (dir==='BUY' && best>=target)
      );
      if(!reached)return target;
    }
    return null;
  }

  function selectedZone(){
    const j=journalState();
    return j?.zone||{};
  }

  function mapRows(){
    return Array.from(document.querySelectorAll('#zones tr')).filter(r=>{
      const text=(r.textContent||'').trim();
      return text && !text.includes('Waiting for analysis') && !text.includes('No prompt-qualified primary zones');
    });
  }

  function refreshZoneOwnershipTags(){
    const thesis=activeThesis();
    const locked=thesis.locked===true;
    const ownerId=String(thesis.owner_zone_id||'');
    const selectedId=String(selectedZone().zone_id||'');

    mapRows().forEach(row=>{
      const cells=row.querySelectorAll('td');
      if(!cells.length)return;
      const cell=cells[0];
      let zid=cell.dataset.zoneId||'';
      if(!zid){
        const first=cell.childNodes && cell.childNodes.length ? cell.childNodes[0] : null;
        zid=String(first?.nodeValue||first?.textContent||cell.textContent||'').trim();
        cell.dataset.zoneId=zid;
      }

      let tag=cell.querySelector('.ownership-tag');
      if(!tag){
        tag=document.createElement('div');
        tag.className='ownership-tag note';
        cell.appendChild(tag);
      }

      tag.className='ownership-tag note';
      if(locked && ownerId && zid===ownerId){
        tag.textContent='EXECUTION OWNER';
        tag.classList.add('ok');
      }else if(locked){
        tag.textContent='WATCH ONLY • NO M1 AUTHORITY';
        tag.classList.add('warn');
      }else if(selectedId && zid===selectedId){
        tag.textContent='SELECTED • UNLOCKED';
        tag.classList.add('blue');
      }else{
        tag.textContent='MAP CONTEXT';
      }
    });
  }

  function refreshJournalContext(){
    const out=document.getElementById('journalContext');
    const stateOut=document.getElementById('ownershipState');
    if(!out || !stateOut)return;

    const j=journalState();
    const z=j?.zone||{};
    const status=document.getElementById('jStatus')?.textContent||'WAITING';
    const rows=mapRows().length;
    const thesis=activeThesis();
    const locked=thesis.locked===true;
    const ownerId=String(thesis.owner_zone_id||'');
    const ownerDir=String(thesis.direction||'').toUpperCase();
    const ownerStatus=String(thesis.status||'ACTIVE').replaceAll('_',' ');
    const selectedId=String(z.zone_id||'');
    const selectedDir=String(z.direction||'').toUpperCase();
    const selectedTouches=(z.touch_count===0 || z.touch_count) ? String(z.touch_count) : '—';
    const parts=[];

    parts.push('Journal status '+status+'.');
    parts.push(rows ? ('Current HTF map: '+rows+' published primary zone'+(rows===1?'':'s')+'.') : 'Current HTF map: no published primary zone.');

    let ownership='NO OWNER';
    let cls='warn';
    if(locked){
      if(ownerId && selectedId===ownerId){
        ownership='OWNER MATCH';
        cls='ok';
      }else if(ownerId){
        ownership='WATCH / BLOCKED';
        cls='warn';
      }else{
        ownership='OWNER OFF MAP';
        cls='bad';
      }

      parts.push(
        'Execution owner '+(ownerDir||'—')+' • '+(ownerId||'owner zone not republished')+
        ' • '+ownerStatus+'.'
      );
      if(selectedId){
        parts.push(
          'Journal-selected zone '+selectedId+' ('+(selectedDir||'—')+', '+selectedTouches+' touches) '+
          (selectedId===ownerId ? 'owns current M1 authority.' : 'does not own current M1 authority.')
        );
      }
      if(thesis.opposite_execution_blocked===true){
        parts.push('All non-owner/opposite zones are WATCH ONLY until the acquired thesis is released.');
      }
      const objective=nextObjective(thesis);
      if(objective!==null){
        parts.push('Next open thesis objective '+Number(objective).toLocaleString(undefined,{maximumFractionDigits:3})+'.');
      }
      if(thesis.no_chase===true || thesis.fresh_m1_confirmation_required===true){
        parts.push('No chase: a fresh same-direction M1 confirmation is still required for any new entry.');
      }
    }else if(selectedId){
      ownership='SELECTED / UNLOCKED';
      cls='blue';
      parts.push('No acquired thesis lock is active. Journal-selected zone '+selectedId+' is the current execution selection, subject to all normal M1 and safety gates.');
    }else{
      parts.push('No acquired thesis lock and no M1-authorized zone are currently selected.');
    }

    stateOut.textContent=ownership;
    stateOut.className='kpi '+cls;
    out.textContent=parts.join(' ');
    refreshZoneOwnershipTags();
  }

  function refreshReadinessSplit(){
    const htf=document.getElementById('htfScore');
    const htfMeta=document.getElementById('htfMeta');
    const exec=document.getElementById('jScore');
    const execMeta=document.getElementById('executionMeta');
    const seqGate=document.getElementById('sequenceGate');
    const seqMeta=document.getElementById('sequenceGateMeta');
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
    const thesis=activeThesis();
    const ownerMatch=thesis.locked===true && Boolean(z.zone_id) && String(thesis.owner_zone_id||'')===String(z.zone_id);
    let state='WAITING FOR LOCATION';
    let cls='warn';
    let meta='No M1 handoff yet.';

    if(!hasZone){
      state='NO M1 SELECTION';
      cls='warn';
      meta='No execution zone is selected. Sequence EA execution remains unavailable.';
    }else if(!live){
      state='SAFETY BLOCKED';
      cls='bad';
      meta=checklist+(
        ownerMatch
          ? 'The active thesis is preserved, but live spread/snapshot safety is blocking execution. This is not a location failure.'
          : 'Live spread/snapshot safety is blocking execution before any M1 entry can be used.'
      );
    }else if(!m1){
      state='WAITING FOR M1 CONFIRMATION';
      cls='warn';
      meta=checklist+(
        ownerMatch
          ? 'The active thesis owns execution. Waiting only for a fresh same-direction M1 confirmation; do not chase.'
          : 'M1 handoff is NO. The HTF zone can be A/A+ and still be far from executable location.'
      );
    }else{
      state='M1 HANDOFF READY';
      cls='ok';
      meta=checklist+'Location has reached M1 handoff. Sequence EA still applies its normal sweep → MSS/BOS → displacement → value/retrace sequence plus all unchanged execution gates.';
    }

    const seq=j?.sequence_debug||{};
    const seqAuthority=String(seq.authority||'NONE');
    const seqStage=String(seq.gate_stage||'UNKNOWN');
    const seqReason=String(seq.gate_reason||'');
    const seqModel=String(seq.candidate_model||'NONE');
    const seqOnline=seq.online===true;
    const seqMismatch=seq.authority_mismatch===true;

    if(seqGate && seqMeta){
      if(!seqOnline){
        seqGate.textContent='OFFLINE';
        seqGate.className='kpi bad';
        seqMeta.textContent='No fresh Sequence heartbeat. Execution cannot be trusted until telemetry returns.';
      }else if(seqMismatch && seqStage==='SAFETY' && seqReason.startsWith('CLOUD_LIVE_BLOCK:')){
        seqGate.textContent='SAFETY HOLD';
        seqGate.className='kpi bad';
        seqMeta.textContent='Cloud thesis authority is preserved, but Sequence execution authority is intentionally suspended by '+seqReason.replace('CLOUD_LIVE_BLOCK:','')+'.';
      }else if(seqMismatch){
        seqGate.textContent='AUTHORITY MISMATCH';
        seqGate.className='kpi bad';
        seqMeta.textContent='Cloud authority='+String(seq.cloud_authority||'NONE')+' but Sequence authority=NONE. Gate '+seqStage+' • '+seqReason;
      }else if(seqStage==='ORDER_SENT'){
        seqGate.textContent='ORDER SENT';
        seqGate.className='kpi ok';
        seqMeta.textContent='Sequence '+String(seq.version||'')+' sent the paper order. Model '+String(seq.last_execution_model||seqModel)+'.';
      }else if(seqAuthority!=='NONE'){
        seqGate.textContent=seqStage.replaceAll('_',' ');
        seqGate.className='kpi '+(seqStage==='VALUE_PD_ARRAY'||seqStage==='VALUE'?'blue':'warn');
        seqMeta.textContent='Authority '+seqAuthority+' • model '+seqModel+' • '+(seqReason||'waiting for next micro gate')+'.';
      }else{
        seqGate.textContent=seqStage.replaceAll('_',' ');
        seqGate.className='kpi warn';
        seqMeta.textContent='No Sequence execution authority. '+(seqReason||'Waiting for a cloud handoff.') ;
      }
    }

    if(seqOnline && seqAuthority!=='NONE' && !seqMismatch && !m1){
      state='M1 SEARCH ACTIVE';
      cls='blue';
      meta=checklist+'Macro execution authority is live. Sequence is currently at '+seqStage.replaceAll('_',' ')+'; this is not the same as waiting for HTF location.';
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
  const zones=document.getElementById('zones');
  if(zones){
    new MutationObserver(function(){
      refreshJournalContext();
    }).observe(zones,{childList:true,subtree:true});
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
    cleaned = cleaned.replace(_EXECUTION_CONTRACT_BINDING, _EXECUTION_POLICY_BINDING)
    cleaned = cleaned.replace(_FRESHNESS_LABEL_BINDING, _FRESHNESS_LABEL_REPLACEMENT)

    if 'id="journalContext"' not in cleaned and _JOURNAL_ANCHOR in cleaned:
        cleaned = cleaned.replace(_JOURNAL_ANCHOR, _JOURNAL_CONTEXT_CARD + "\n" + _JOURNAL_ANCHOR, 1)

    if 'id="htfScore"' not in cleaned and _READINESS_CARD in cleaned:
        cleaned = cleaned.replace(_READINESS_CARD, _READINESS_SPLIT, 1)

    if 'id="journal-context-readonly-script"' not in cleaned and "</body>" in cleaned:
        cleaned = cleaned.replace("</body>", _JOURNAL_CONTEXT_SCRIPT + "\n</body>", 1)

    return cleaned
