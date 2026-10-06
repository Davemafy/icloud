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
    "fresh_zone:(z.zone_id?(z.zone_id+' mitigation telemetry (no grade/risk authority)'):"
    "'Selected-zone mitigation telemetry (no grade/risk authority)')"
)
_JOURNAL_ANCHOR = '<h2>Live trading journal'
_VALIDATION_LEDGER_CARD = (
    '<h2>Master Sniper validation ledger <span class="pill paper">OBSERVATION ONLY</span></h2>'
    '<div class="grid">'
    '<div class="card"><h3>Published samples</h3><div class="kpi" id="vLedgerPublished">0</div>'
    '<div class="muted">Canonical source/core samples. Reanalysis of the same institutional source/core remains one research sample.</div></div>'
    '<div class="card"><h3>Live contacts</h3><div class="kpi" id="vLedgerContacts">0</div>'
    '<div class="muted">Post-publication tactical-core contacts only.</div></div>'
    '<div class="card"><h3>Confirmed reactions</h3><div class="kpi" id="vLedgerReactions">0</div>'
    '<div class="muted" id="vLedgerReactionRate">No contacted sample yet.</div></div>'
    '<div class="card"><h3>Executed samples</h3><div class="kpi" id="vLedgerExecuted">0</div>'
    '<div class="muted">MT5 ENTRY_OPENED evidence linked to a publication.</div></div>'
    '</div>'
    '<div class="card scroll" style="margin-top:12px"><table><thead><tr>'
    '<th>Published</th><th>Zone</th><th>Side</th><th>Grade</th><th>Core</th>'
    '<th>Contact</th><th>Mitigations</th><th>M1 handoff</th><th>Lifecycle</th>'
    '<th>Execution</th><th>Outcome</th>'
    '</tr></thead><tbody id="sniperValidationLedger">'
    '<tr><td colspan="11" class="muted">Waiting for validation evidence...</td></tr>'
    '</tbody></table>'
    '<div style="margin-top:10px"><a class="btn" href="/validation/sniper-ledger.csv?limit=250">Export validation CSV</a></div>'
    '<p class="note"><b>Research boundary:</b> this ledger is read-only. It is built from already-persisted '
    'publication, mitigation, lifecycle and MT5 journal truth. It cannot create a zone, alter a grade, '
    'acquire execution authority, change risk, or send an order.</p></div>'
)

_VALIDATION_LEDGER_SCRIPT = r"""
<script id="sniper-validation-ledger-script">
(function(){
  function le(v){
    return String(v===undefined||v===null?'':v)
      .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
      .replaceAll('"','&quot;').replaceAll("'","&#039;");
  }
  function lt(ts){
    const n=Number(ts||0);
    if(!n)return '—';
    try{return new Date(n*1000).toLocaleString();}catch(e){return String(n);}
  }
  function ln(v,d=3){
    const n=Number(v);
    if(!Number.isFinite(n))return '—';
    return n.toLocaleString(undefined,{maximumFractionDigits:d});
  }
  function setText(id,value){
    const el=document.getElementById(id);
    if(el)el.textContent=String(value===undefined||value===null?'—':value);
  }
  async function refreshSniperValidationLedger(){
    const body=document.getElementById('sniperValidationLedger');
    if(!body)return;
    try{
      const response=await fetch('/validation/sniper-ledger?limit=30',{cache:'no-store'});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const data=await response.json();
      const summary=data?.summary||{};
      setText('vLedgerPublished',summary.publications??0);
      setText('vLedgerContacts',summary.live_contacts??0);
      setText('vLedgerReactions',summary.reaction_confirmed??0);
      setText('vLedgerExecuted',summary.executed_publications??0);
      const rate=document.getElementById('vLedgerReactionRate');
      if(rate){
        const other=Number(summary.reaction_confirmed_without_live_core_contact||0);
        rate.textContent=summary.reaction_rate_after_contact_pct===null||summary.reaction_rate_after_contact_pct===undefined
          ? (other>0 ? (other+' confirmed reaction'+(other===1?'':'s')+' used other qualified handoff paths; no live-core-contact rate yet.') : 'No contacted sample yet.')
          : ('Reaction after live core contact '+summary.reaction_rate_after_contact_pct+'% • descriptive only'+(other>0?' • '+other+' other qualified-handoff reaction'+(other===1?'':'s')+' excluded from this percentage':''));
      }
      const rows=Array.isArray(data?.rows)?data.rows:[];
      body.innerHTML=rows.length?rows.map(r=>{
        const contact=r.live_core_touched_at?lt(r.live_core_touched_at):'NO';
        const obs=Number(r.publication_observation_count||1);
        const handoff=r.handoff_at?(lt(r.handoff_at)+'<br><span class="muted">'+le(r.handoff_authority||'')+'</span>'):'—';
        const grade=le(r.structural_grade||'—')+(r.current_grade&&r.current_grade!==r.structural_grade
          ? (' → <b>'+le(r.current_grade)+'</b>'):'');
        return '<tr>'+
          '<td>'+lt(r.published_at)+(obs>1?('<br><span class="muted">'+obs+' exact-geometry observations collapsed</span>'):'')+'</td>'+
          '<td><b>'+le(r.zone_id||'—')+'</b><br><span class="muted">'+le(r.source_tf||'')+'</span></td>'+
          '<td>'+le(r.direction||'—')+'</td>'+
          '<td>'+grade+'</td>'+
          '<td>'+ln(r.core_low)+'–'+ln(r.core_high)+'</td>'+
          '<td>'+contact+'</td>'+
          '<td>'+le(r.qualified_mitigations??0)+' qualified<br><span class="muted">'+le(r.raw_core_contacts??0)+' raw</span></td>'+
          '<td>'+handoff+'</td>'+
          '<td>'+le(String(r.lifecycle_status||'—').replaceAll('_',' '))+'</td>'+
          '<td>'+le(String(r.execution_state||'—').replaceAll('_',' '))+'</td>'+
          '<td><b>'+le(String(r.outcome||'—').replaceAll('_',' '))+'</b></td>'+
          '</tr>';
      }).join(''):'<tr><td colspan="11" class="muted">No exact zone publication has been recorded yet.</td></tr>';
    }catch(error){
      body.innerHTML='<tr><td colspan="11" class="muted">Validation ledger temporarily unavailable: '+le(error?.message||error)+'</td></tr>';
    }
  }
  refreshSniperValidationLedger();
  window.setInterval(refreshSniperValidationLedger,10000);
})();
</script>
""".strip()
_MITIGATION_AUDIT_CARD = (
    '<h2>Mitigation audit <span class="pill paper">OBSERVATION ONLY</span></h2>'
    '<div class="card scroll"><table><thead><tr>'
    '<th>Zone</th><th>Expected cycle</th><th>Event</th><th>Approach</th>'
    '<th>Armed</th><th>Core touch</th><th>Qualified / exit</th>'
    '<th>Counted</th><th>Grade effect / reason</th>'
    '</tr></thead><tbody id="mitigationAudit">'
    '<tr><td colspan="9" class="muted">Waiting for mitigation audit…</td></tr>'
    '</tbody></table>'
    '<p class="note"><b>Telemetry rule:</b> SELL = below envelope → core → below envelope; '
    'BUY = above envelope → core → above envelope. Touch/mitigation count never changes zone grade, risk, ranking or execution eligibility. '
    'Accepted distal M15 invalidation still ends the original zone lifecycle.</p></div>'
)

_JOURNAL_CONTEXT_CARD = (
    '<div class="card" style="margin-top:12px">'
    '<h3>Map / thesis ownership &amp; M1 authority <span class="pill paper">READ ONLY</span></h3>'
    '<div class="kpi" id="ownershipState">WAITING</div>'
    '<div id="journalContext" class="note">'
    'Waiting for thesis ownership and M1-authority context…'
    '</div>'
    '<p class="note"><b>Display only:</b> this panel does not change zone selection, '
    'AI approval, thesis ownership, M1 handoff, risk, orders, or Sequence EA execution.</p>'
    '</div>'
)
_READINESS_CARD = (
    '<div class="card"><h3>Readiness</h3><div class="kpi" id="jScore">0/6</div>'
    '<div class="muted">Process checklist — not a prediction.</div></div>'
)
_READINESS_SPLIT = (
    '<div class="card"><h3>HTF setup quality</h3><div class="kpi" id="htfScore">0/6</div>'
    '<div class="muted" id="htfMeta">Location quality only — not entry readiness.</div></div>'
    '<div class="card"><h3>Selected map state</h3><div class="kpi" id="mapState">NO ACTIVE MAP</div>'
    '<div class="muted" id="mapStateMeta">Structural map lifecycle only. It never authorizes an entry.</div></div>'
    '<div class="card"><h3>Execution readiness</h3><div class="kpi" id="jScore">WAITING</div>'
    '<div class="muted" id="executionMeta">Thesis ownership is a directional lock; current M1 handoff plus the live Sequence micro-gate control new-entry timing.</div></div>'
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

  function auditTime(ts){
    const n=Number(ts||0);
    if(!n)return '—';
    try{return new Date(n*1000).toLocaleString();}catch(e){return String(n);}
  }

  function auditText(v){
    return String(v===undefined||v===null?'':v)
      .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
      .replaceAll('"','&quot;').replaceAll("'","&#039;");
  }

  function refreshMitigationAudit(){
    const body=document.getElementById('mitigationAudit');
    if(!body)return;
    const p=policyState();
    const map=p && typeof p.public_zone_map==='object' ? p.public_zone_map : {};
    const analysisZones=Array.isArray(window.tradeZoneAnalysisZones)?window.tradeZoneAnalysisZones:[];
    const rows=[];
    for(const side of ['sell','buy']){
      const mapped=map?.[side]||{};
      const raw=analysisZones.find(x=>String(x?.original_direction||'').toLowerCase()===side)||{};
      // public_zone_map deliberately removes the literal zone_id key so DataBridge
      // does not double-count zones. audit_zone_id restores human audit identity.
      const mappedId=String(mapped.audit_zone_id||mapped.zone_id||'');
      const rawId=String(raw.zone_id||'');
      const z=(mappedId||Object.keys(mapped).length)?mapped:raw;
      const zoneId=mappedId||rawId;
      if(!zoneId)continue;
      const audit=z.mitigation_audit||raw.mitigation_audit||{};
      const events=Array.isArray(audit.events)?audit.events:[];
      const rawContacts=Array.isArray(audit.raw_contacts)?audit.raw_contacts:[];
      const expected=String(audit.expected_approach_side||z.mitigation_expected_approach_side||'—');
      const historyComplete=audit.history_complete===true || z.mitigation_history_complete===true;
      const cycle=(String(side).toUpperCase()==='SELL')
        ? 'BELOW → CORE → BELOW'
        : 'ABOVE → CORE → ABOVE';
      if(!historyComplete){
        rows.push(
          '<tr><td>'+auditText(zoneId)+'</td><td>'+cycle+'</td><td><b class="warn">MITIGATION HISTORY INCOMPLETE</b></td>'+
          '<td>'+auditText(expected)+'</td><td>'+auditTime(audit.history_start_ts||z.mitigation_history_start_ts)+'</td>'+
          '<td>—</td><td>Required from '+auditTime(audit.history_required_from_ts||z.mitigation_history_required_from_ts)+'</td>'+
          '<td><b>NO</b></td><td>'+auditText(audit.history_gap_reason||z.mitigation_history_gap_reason||'M15 history cannot prove full mitigation telemetry')+
          ' • Observation only; zone grade and execution authority are unchanged.</td></tr>'
        );
      }
      rawContacts.forEach((r)=>{
        rows.push(
          '<tr><td>'+auditText(zoneId)+'</td>'+
          '<td>'+cycle+'</td>'+
          '<td>RAW CORE CONTACT #'+auditText(r.raw_contact_index||'—')+'</td>'+
          '<td>Campaign '+auditText(r.campaign_approach_side||r.approach_side||'—')+
          '<br><span class="muted">Immediate '+auditText(r.immediate_approach_side||'—')+
          (r.immediate_approach_ts?(' @ '+auditTime(r.immediate_approach_ts)):'')+'</span></td>'+
          '<td>'+auditTime(r.armed_at)+'</td>'+
          '<td>'+auditTime(r.core_touched_at)+'</td>'+
          '<td>—</td>'+
          '<td><b>NO</b></td>'+
          '<td>OBSERVATION ONLY • '+auditText(r.contact_role||'RAW_CONTACT_ONLY')+'</td></tr>'
        );
      });
      if(!events.length){
        rows.push(
          '<tr><td>'+auditText(zoneId)+'</td><td>'+cycle+'</td><td>NO QUALIFIED EVENT</td>'+
          '<td>'+auditText(expected)+'</td><td>—</td><td>—</td><td>—</td><td><b>NO</b></td>'+
          '<td>Qualified mitigations '+auditText(audit.qualified_mitigations??z.qualified_mitigations??z.touch_count??0)+'</td></tr>'
        );
        continue;
      }
      events.forEach((e)=>{
        const qualified=e.qualified===true;
        const type=String(e.event_type||'INTERACTION')+(qualified&&e.qualified_index?' #'+e.qualified_index:'');
        const before=String(e.grade_before||'');
        const after=String(e.grade_after||'');
        const effect=(before||after)?((before||'—')+' → '+(after||'—')):'';
        const reason=String(e.reason||'');
        rows.push(
          '<tr><td>'+auditText(zoneId)+'</td>'+
          '<td>'+cycle+'</td>'+
          '<td>'+auditText(type)+'</td>'+
          '<td>'+auditText(e.approach_side||'—')+'</td>'+
          '<td>'+auditTime(e.armed_at)+'</td>'+
          '<td>'+auditTime(e.core_touched_at)+'</td>'+
          '<td>'+auditTime(e.qualified_at||e.bar_ts)+'</td>'+
          '<td><b class="'+(qualified?'ok':'warn')+'">'+(qualified?'YES':'NO')+'</b></td>'+
          '<td>'+auditText(effect+(effect&&reason?' • ':'')+reason)+'</td></tr>'
        );
      });
      if(audit.counting_stopped===true){
        rows.push(
          '<tr><td>'+auditText(zoneId)+'</td><td>'+cycle+'</td><td><b class="bad">COUNTER STOPPED</b></td>'+
          '<td>—</td><td>—</td><td>—</td><td>'+auditTime(audit.invalidated_at)+'</td><td><b>NO</b></td>'+
          '<td>'+auditText(audit.invalidation_reason||'ACCEPTED INVALIDATION')+'</td></tr>'
        );
      }
    }
    body.innerHTML=rows.length?rows.join(''):'<tr><td colspan="9" class="muted">No current map zone has mitigation audit data.</td></tr>';
  }

  function activeThesis(){
    const p=policyState();
    const t=p && typeof p.active_thesis==='object' ? p.active_thesis : {};
    return t || {};
  }

  function nextObjective(t,j){
    // The journal backend already reconciles target-hit timestamps, owner best
    // price and any active opposing-zone lifecycle cap. Prefer that canonical
    // value so this read-only context panel cannot disagree with the beginner
    // target-ladder truth below it.
    const journalNext=Number(j?.next_open_thesis_objective);
    if(Number.isFinite(journalNext) && journalNext>0)return journalNext;

    const dir=String(t?.direction||'').toUpperCase();
    const best=Number(t?.best_price);
    const haveBest=Number.isFinite(best) && best>0;
    for(const key of ['target1','target2','target3']){
      const target=Number(t?.[key]);
      if(!Number.isFinite(target) || target<=0)continue;
      const hitAt=Number(t?.[key+'_hit_at']||0);
      if(Number.isFinite(hitAt) && hitAt>0)continue;
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
        tag.textContent='THESIS OWNER • DIRECTION LOCK';
        tag.classList.add('ok');
      }else if(locked){
        tag.textContent='WATCH ONLY • BLOCKED BY ACTIVE THESIS';
        tag.classList.add('warn');
      }else if(selectedId && zid===selectedId){
        tag.textContent='PLAN SELECTED • NO THESIS LOCK';
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
    const seqContext=j?.sequence_debug||{};
    const executionContextType=String(seqContext.execution_context_type||'MAP_PLAN').toUpperCase();
    const acceptedFlipContext=executionContextType==='ACCEPTED_ZONE_FLIP';
    const executionContextZone=String(seqContext.execution_context_zone_id||'');
    const executionContextDir=String(seqContext.execution_context_direction||'').toUpperCase();
    const executionContextSlot=String(seqContext.execution_context_slot||'');
    const executionContextAcceptedAt=Number(seqContext.execution_context_accepted_at||0);
    const parts=[];

    parts.push('Journal status '+status+'.');
    parts.push(rows ? ('Current HTF map: '+rows+' published primary zone'+(rows===1?'':'s')+'.') : 'Current HTF map: no published primary zone.');

    let ownership='NO THESIS OWNER';
    let cls='warn';
    if(acceptedFlipContext){
      ownership='ACCEPTED-ZONE '+(executionContextDir||'')+' FLIP';
      cls='blue';
      parts.push(
        'Active execution context is the persisted accepted-zone '+(executionContextDir||'opposite-side')+
        ' flip from failed zone '+(executionContextZone||'—')+
        (executionContextSlot?' • slot '+executionContextSlot:'')+
        (executionContextAcceptedAt?' • accepted '+new Date(executionContextAcceptedAt*1000).toLocaleString():'')+
        '. Its micro gate is independent of the newly ranked current HTF map.'
      );
      if(selectedId){
        parts.push('Current journal/map selection '+selectedId+' ('+(selectedDir||'—')+') is map context only while this accepted-flip execution object is active.');
      }
    }else if(locked){
      if(ownerId && selectedId===ownerId){
        ownership='THESIS OWNER MATCH';
        cls='ok';
      }else if(ownerId){
        ownership='THESIS OWNER / DIFFERENT SELECTION';
        cls='warn';
      }else{
        ownership='THESIS OWNER OFF MAP';
        cls='bad';
      }

      parts.push(
        'Thesis owner '+(ownerDir||'—')+' • '+(ownerId||'owner zone not republished')+
        ' • '+ownerStatus+'. Direction lock is active; this does not by itself authorize a new M1 entry.'
      );
      if(selectedId){
        parts.push(
          'Journal-selected zone '+selectedId+' ('+(selectedDir||'—')+', '+selectedTouches+' touches) '+
          (selectedId===ownerId ? 'matches the active thesis owner.' : 'does not match the active thesis owner.')
        );
      }
      if(selectedId && selectedId===ownerId){
        parts.push('This selected zone is the thesis origin/ownership anchor; it does not mean current price is still inside the original core or envelope.');
      }
      const checks=j?.checks||{};
      const seq=j?.sequence_debug||{};
      const macroHandoff=checks.m1_handoff_ready===true;
      const freshLocation=checks.fresh_m1_location_ready===true;
      const cloudAuthority=String(seq.cloud_authority||'NONE');
      const sequenceAuthority=String(seq.authority||'NONE');
      parts.push(
        'Macro thesis / handoff authority '+(macroHandoff?'YES':'NO')+
        '. Fresh M1 entry location '+(freshLocation?'YES':'NO')+
        '. Cloud execution authority '+cloudAuthority+
        '. Sequence authority '+sequenceAuthority+'.'
      );
      if(thesis.late_stage_reacquisition_required===true){
        const reacquired=thesis.late_stage_reacquisition_satisfied===true;
        parts.push(
          'Late-stage HTF location reacquisition '+(reacquired?'SATISFIED':'REQUIRED / NOT SATISFIED')+
          (thesis.late_stage_reacquisition_zone_id ? ' • current zone '+thesis.late_stage_reacquisition_zone_id : '')+
          (thesis.late_stage_reacquisition_basis ? ' • '+String(thesis.late_stage_reacquisition_basis).replaceAll('_',' ') : '')+
          '. Historical ownership remains lifecycle truth but cannot by itself authorize a fresh entry.'
        );
      }
      if(thesis.opposite_execution_blocked===true){
        parts.push('All non-owner/opposite zones are WATCH ONLY until the acquired thesis is released.');
      }
      const objective=nextObjective(thesis,j);
      if(objective!==null){
        parts.push('Next open thesis objective '+Number(objective).toLocaleString(undefined,{maximumFractionDigits:3})+'.');
      }
      if(thesis.no_chase===true || thesis.fresh_m1_confirmation_required===true){
        parts.push('No chase: a fresh same-direction M1 confirmation is still required for any new entry.');
      }
    }else if(selectedId){
      ownership='PLAN SELECTED / NO THESIS LOCK';
      cls='blue';
      parts.push('No acquired thesis lock is active. Journal-selected zone '+selectedId+' is the current plan selection only; new-entry authority still requires current M1 handoff and Sequence confirmation.');
    }else{
      parts.push('No acquired thesis lock and no current M1-authorized zone are selected.');
    }

    stateOut.textContent=ownership;
    stateOut.className='kpi '+cls;
    out.textContent=parts.join(' ');
    refreshZoneOwnershipTags();
  }

  function refreshReadinessSplit(){
    const htf=document.getElementById('htfScore');
    const htfMeta=document.getElementById('htfMeta');
    const mapState=document.getElementById('mapState');
    const mapStateMeta=document.getElementById('mapStateMeta');
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

    if(mapState && mapStateMeta){
      const rawReadiness=String(z.readiness||'');
      const mapThesis=activeThesis();
      const mapOwnerMatch=mapThesis.locked===true && Boolean(z.zone_id) && String(mapThesis.owner_zone_id||'')===String(z.zone_id);
      const fallback=!hasZone
        ? 'NO ACTIVE MAP'
        : (mapOwnerMatch
            ? String(z.direction||'')+' THESIS OWNER ACTIVE • FRESH M1 REQUIRED'
            : (rawReadiness==='ARMED'
                ? String(z.direction||'')+' MAP VALID • RETEST PENDING'
                : (rawReadiness==='INTERACTING'
                    ? String(z.direction||'')+' MAP CONTACTED • M1 CONFIRMATION PENDING'
                    : (rawReadiness==='M1_READY'
                        ? String(z.direction||'')+' MAP CONTACTED • M1 HANDOFF ACTIVE'
                        : String(z.direction||'')+' MAP '+(rawReadiness||'PLANNED')))));
      mapState.textContent=String(j?.map_display_state||fallback).trim();
      mapState.className='kpi '+(!hasZone?'warn':(mapOwnerMatch?'ok':(rawReadiness==='M1_READY'||rawReadiness==='INTERACTING'?'blue':'')));
      mapStateMeta.textContent=hasZone
        ? 'Structural map lifecycle only. A valid SELL/BUY map is not execution readiness; M1 handoff and the Sequence order gate remain separate.'
        : 'No selected active map. Invalidated geometry may still remain visible as FLIP CONTEXT with zero original-direction authority.';
    }

    const allKeys=Object.keys(checks);
    const allPassed=allKeys.reduce((n,k)=>n+(checks[k]===true?1:0),0);
    const checklist=allKeys.length ? ('Pre-entry conditions '+allPassed+'/'+allKeys.length+'. This is not an M1 trigger or order permission. ') : '';
    const m1=checks.m1_handoff_ready===true;
    const freshM1=checks.fresh_m1_location_ready===true;
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
      state=String(z.readiness||'')==='ARMED' ? 'MAP VALID • NO ENTRY AUTHORITY' : 'WAITING FOR M1 CONFIRMATION';
      cls='warn';
      meta=checklist+(
        ownerMatch
          ? 'The active thesis direction lock remains, but there is no current M1 location handoff or new-entry authority. Do not chase the existing move.'
          : 'M1 handoff is NO. The HTF zone can be A/A+ and still be far from executable location.'
      );
    }else{
      state=ownerMatch ? 'THESIS OWNER ACTIVE • FRESH M1 REQUIRED' : 'M1 HANDOFF ACTIVE';
      cls=ownerMatch ? 'ok' : 'blue';
      meta=ownerMatch
        ? checklist+'The acquired thesis still owns direction, but that ownership anchor is not itself a fresh entry signal. A new same-direction M1 location/confirmation and the live Sequence micro-gate are required before any new order.'
        : checklist+'Macro location handoff is active. Model 1: M1 liquidity sweep → M1 micro structure shift → causal OB/FVG → bounded retest → CLOSED M1 directional confirmation. Model 2: recent-zone CLOSED directional engulfing → entry; if the direct entry is missed, a bounded engulfed-body retest plus fresh CLOSED directional rejection may recover the same opportunity. No separate M1 micro-structure shift. Model 3: institutional boundary breakout → displacement → acceptance → retest → CLOSED directional M1 confirmation; no separate M1 micro-structure shift. M15 validates zone health; each sniper family uses its own confirmation contract.';
    }

    const seq=j?.sequence_debug||{};
    const seqAuthority=String(seq.authority||'NONE');
    const seqStage=String(seq.gate_stage||'UNKNOWN');
    const seqReason=String(seq.gate_reason||'');
    const seqModel=String(seq.candidate_model||'NONE');
    const seqVersion=String(seq.version||'');
    const executionContextType2=String(seq.execution_context_type||'MAP_PLAN').toUpperCase();
    const acceptedFlipContext2=executionContextType2==='ACCEPTED_ZONE_FLIP';
    const executionContextZone2=String(seq.execution_context_zone_id||'');
    const executionContextDirection2=String(seq.execution_context_direction||'').toUpperCase();
    const executionContextSlot2=String(seq.execution_context_slot||'');
    const executionContextAcceptedAt2=Number(seq.execution_context_accepted_at||0);
    const executionContextContractVerified=seq.execution_context_contract_verified===true;
    const executionContextCoreLow=Number(seq.execution_context_core_low||0);
    const executionContextCoreHigh=Number(seq.execution_context_core_high||0);
    const executionContextZoneLow=Number(seq.execution_context_zone_low||0);
    const executionContextZoneHigh=Number(seq.execution_context_zone_high||0);
    const executionContextTarget1=Number(seq.execution_context_target1||0);
    const executionContextTarget2=Number(seq.execution_context_target2||0);
    const executionContextTarget3=Number(seq.execution_context_target3||0);
    const opportunitySlot=String(seq.opportunity_slot||'');
    const primaryEntries=Number(seq.primary_entries||0);
    const reentries=Number(seq.reentries||0);
    const reacquisitionSlot=(opportunitySlot.startsWith('R')&&opportunitySlot!=='REENTRY_CAP_REACHED') ? opportunitySlot : (primaryEntries>0 ? ('R'+String(reentries+1)) : '');
    const lastCandidateEntry=Number(seq.last_candidate_entry||0);
    const lastCandidateStop=Number(seq.last_candidate_stop||0);
    const lastCandidateTarget=Number(seq.last_candidate_target||0);
    const lastCandidateRR=Number(seq.last_candidate_rr||0);
    const lastCandidateRRRequired=Number(seq.last_candidate_rr_required||0);
    const lastCandidateStopBasis=String(seq.last_candidate_stop_basis||'');
    const lastCandidateSwingLevel=Number(seq.last_candidate_swing_level||0);
    const lastCandidateSwingTime=Number(seq.last_candidate_swing_time||0);
    const cloudMode=String(seq.cloud_ea_mode||'UNKNOWN');
    const cloudGuard=String(seq.cloud_execution_guard_reason||'');
    const cloudSeparation=String(seq.cloud_separation_guard||'');
    const cloudRunway=String(seq.cloud_usable_runway||'');
    const cloudRequiredRunway=String(seq.cloud_required_runway||'');
    const cloudRunwayTarget=String(seq.cloud_runway_target||'');
    const cloudRunwayMode=String(seq.cloud_runway_gate_mode||'');
    const cloudRunwayEntryLimit=String(seq.cloud_runway_entry_limit||'');
    const cloudRunwayCandidateLow=String(seq.cloud_runway_candidate_low||'');
    const cloudRunwayCandidateHigh=String(seq.cloud_runway_candidate_high||'');
    const cloudConservativeEdgeRunway=String(seq.cloud_conservative_edge_runway||'');
    const cloudHistoryFailures=String(seq.cloud_history_failures||'');
    const cloudHistoryWarnings=String(seq.cloud_history_warnings||'');
    const cloudHistoryMetrics=String(seq.cloud_history_metrics||'');
    const seqOnline=seq.online===true;
    const seqMismatch=seq.authority_mismatch===true;
    const seqOpen=Number(seq.open_positions||0);
    const traceLiquidity=Number(seq.trace_liquidity_level||0);
    const traceContactTs=Number(seq.trace_contact_ts||0);
    const traceReconstructed=seq.trace_reconstructed_pre_handoff===true;
    const campaignKey=String(seq.campaign_key||'');
    const traceSweep=Number(seq.trace_sweep_price||0);
    const traceSweepTs=Number(seq.trace_sweep_ts||0);
    const traceSweepScanBars=Number(seq.trace_sweep_scan_bars||0);
    const traceSweepRejectReason=String(seq.trace_sweep_reject_reason||'');
    const traceSweepCandidateTs=Number(seq.trace_sweep_candidate_ts||0);
    const traceSweepCandidateLiquidity=Number(seq.trace_sweep_candidate_liquidity||0);
    const traceSweepCandidatePrice=Number(seq.trace_sweep_candidate_price||0);
    const traceSweepCandidateClearance=Number(seq.trace_sweep_candidate_clearance_points||0);
    const traceMss=Number(seq.trace_mss_level||0);
    const traceMssTs=Number(seq.trace_mss_break_ts||0);
    const tracePdType=String(seq.trace_pd_type||'');
    const tracePdLow=Number(seq.trace_pd_low||0);
    const tracePdHigh=Number(seq.trace_pd_high||0);
    const tracePdTs=Number(seq.trace_pd_ts||0);
    const tracePullbackTs=Number(seq.trace_pullback_ts||0);
    const traceConfirmTs=Number(seq.trace_confirm_ts||0);
    const orderFlowMode=Number(seq.orderflow_proxy_mode||0);
    const orderFlowFeed=String(seq.orderflow_proxy_feed||'');
    const orderFlowState=String(seq.orderflow_proxy_state||'UNAVAILABLE');
    const orderFlowScore=Number(seq.orderflow_proxy_score||0);
    const orderFlowDeltaNorm=Number(seq.orderflow_proxy_delta_norm||0);
    const orderFlowAbsorption=seq.orderflow_proxy_absorption===true;
    const orderFlowDivergence=seq.orderflow_proxy_divergence===true;
    const orderFlowExpansion=seq.orderflow_proxy_expansion===true;
    const tracePrice=(v)=>v?Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:5}):'—';
    const traceTime=(v)=>v?new Date(Number(v)*1000).toLocaleString():'—';
    const traceParts=[];
    if(campaignKey)traceParts.push('Campaign '+campaignKey);
    if(opportunitySlot)traceParts.push('Slot '+opportunitySlot);
    if(traceContactTs)traceParts.push('Zone contact @ '+traceTime(traceContactTs)+(traceReconstructed?' (reconstructed pre-handoff)':''));
    if(traceSweep||traceLiquidity)traceParts.push('Sweep '+tracePrice(traceSweep)+(traceLiquidity?' over liquidity '+tracePrice(traceLiquidity):'')+(traceSweepTs?' @ '+traceTime(traceSweepTs):''));
    if(traceSweepRejectReason){
      let rejected='Sweep candidate rejected: '+traceSweepRejectReason.replaceAll('_',' ');
      if(traceSweepCandidatePrice||traceSweepCandidateLiquidity){
        rejected+=' • price '+tracePrice(traceSweepCandidatePrice)+' vs liquidity '+tracePrice(traceSweepCandidateLiquidity);
      }
      if(traceSweepCandidateTs)rejected+=' @ '+traceTime(traceSweepCandidateTs);
      if(Number.isFinite(traceSweepCandidateClearance))rejected+=' • clearance '+traceSweepCandidateClearance.toFixed(1)+'pt';
      if(traceSweepScanBars)rejected+=' • scan '+traceSweepScanBars+' M1 bars';
      traceParts.push(rejected);
    }
    if(traceMss)traceParts.push('Micro MSS '+tracePrice(traceMss)+(traceMssTs?' broken @ '+traceTime(traceMssTs):''));
    if(tracePdLow||tracePdHigh)traceParts.push((tracePdType||'PD')+' '+tracePrice(tracePdLow)+'–'+tracePrice(tracePdHigh)+(tracePdTs?' formed @ '+traceTime(tracePdTs):''));
    if(tracePullbackTs)traceParts.push('PD pullback touched @ '+traceTime(tracePullbackTs));
    if(traceConfirmTs)traceParts.push('Directional close @ '+traceTime(traceConfirmTs));
    const orderFlowFlags=[];
    if(orderFlowAbsorption)orderFlowFlags.push('absorption');
    if(orderFlowDivergence)orderFlowFlags.push('divergence');
    if(orderFlowExpansion)orderFlowFlags.push('delta expansion');
    const orderFlowText=orderFlowMode>0
      ? ' Order-flow proxy: '+orderFlowState+' • score '+orderFlowScore.toFixed(2)+' • Δ-proxy '+orderFlowDeltaNorm.toFixed(2)+(orderFlowFlags.length?' • '+orderFlowFlags.join(', '):'')+' • '+(orderFlowFeed||'CFD_TICK_VOLUME_PROXY')+' (broker CFD tick-volume proxy; NOT centralized COMEX bid/ask delta).'
      : '';
    const rrAuditText=(lastCandidateEntry&&lastCandidateStop&&lastCandidateTarget)
      ? ' Candidate audit: entry '+tracePrice(lastCandidateEntry)+
        ' • SL '+tracePrice(lastCandidateStop)+
        ' • target '+tracePrice(lastCandidateTarget)+
        (lastCandidateRRRequired?' • RR '+lastCandidateRR.toFixed(2)+' / required '+lastCandidateRRRequired.toFixed(2):'')+
        (lastCandidateStopBasis?' • stop '+lastCandidateStopBasis.replaceAll('_',' '):'')+
        (lastCandidateSwingLevel?' • swing '+tracePrice(lastCandidateSwingLevel):'')+
        (lastCandidateSwingTime?' @ '+new Date(lastCandidateSwingTime*1000).toLocaleString():'')+'.'
      : '';
    const flipTargets=[executionContextTarget1,executionContextTarget2,executionContextTarget3].filter(v=>v>0).map(v=>tracePrice(v));
    const executionContextText=acceptedFlipContext2
      ? ' Accepted-flip context: '+(executionContextDirection2||'—')+
        ' from failed zone '+(executionContextZone2||'—')+
        (executionContextSlot2?' • '+executionContextSlot2:'')+
        (executionContextAcceptedAt2?' • accepted '+traceTime(executionContextAcceptedAt2):'')+
        ((executionContextZoneLow||executionContextZoneHigh)?' • failed envelope '+tracePrice(executionContextZoneLow)+'–'+tracePrice(executionContextZoneHigh):'')+
        ((executionContextCoreLow||executionContextCoreHigh)?' • core '+tracePrice(executionContextCoreLow)+'–'+tracePrice(executionContextCoreHigh):'')+
        (flipTargets.length?' • flip targets '+flipTargets.join(' / '):'')+'.'
      : '';
    const parity=seq.sniper_contract_parity||{};
    const parityMismatches=Array.isArray(parity.mismatches)?parity.mismatches:[];
    const parityCloud=parity.cloud||{};
    const paritySequence=parity.sequence||{};
    const parityText=parityMismatches.length
      ? ' Mismatch detail: '+parityMismatches.map(k=>k+' [Cloud='+String(parityCloud[k]??'—')+' / Sequence='+String(paritySequence[k]??'—')+']').join(' • ')+'.'
      : '';
    const traceText=(traceParts.length?' M1 trace: '+traceParts.join(' • ')+'.':'')+executionContextText+orderFlowText+rrAuditText;

    if(seqOnline && seqOpen>0){
      state='IN TRADE • MANAGING';
      cls='ok';
      meta='Sequence is managing '+seqOpen+' open position'+(seqOpen===1?'':'s')+'. Existing stops/targets remain active; any further entry still requires the normal re-entry gates.';
    }

    if(seqGate && seqMeta){
      if(!seqOnline){
        seqGate.textContent='OFFLINE';
        seqGate.className='kpi bad';
        seqMeta.textContent='No fresh Sequence heartbeat. Execution cannot be trusted until telemetry returns.';
      }else if(seqOpen>0){
        seqGate.textContent='MANAGING '+seqOpen+' POSITION'+(seqOpen===1?'':'S');
        seqGate.className='kpi ok';
        seqMeta.textContent='Authority '+seqAuthority+' • current micro gate '+seqStage.replaceAll('_',' ')+' • '+(seqReason||'position management active')+'. This is management telemetry, not a new-entry signal.';
      }else if(seqStage==='SAFETY' && seqReason.startsWith('CLOUD_LIVE_BLOCK:')){
        seqGate.textContent='SAFETY HOLD';
        seqGate.className='kpi bad';
        seqMeta.textContent=(seqAuthority!=='NONE'
          ? 'Macro authority '+seqAuthority+' is preserved; order permission is suspended by '
          : (ownerMatch
              ? 'Cloud thesis owner is preserved; order permission is suspended by '
              : 'Cloud handoff context is preserved; order permission is suspended by ')
        )+seqReason.replace('CLOUD_LIVE_BLOCK:','')+'.';
      }else if(seqStage==='AUTHORITY' && seqReason==='PLAN_WATCH_ONLY' && cloudMode==='WATCH_ONLY'){
        seqGate.textContent='CLOUD PLAN WATCH ONLY';
        seqGate.className='kpi warn';
        let why=(cloudSeparation&&cloudSeparation!=='PASS')?cloudSeparation:(cloudGuard||'NO_EXECUTION_HANDOFF');
        let runwayText='';
        if(cloudRunway||cloudRequiredRunway||cloudRunwayTarget){
          runwayText=' Runway '+(cloudRunway||'—')+' / required '+(cloudRequiredRunway||'—')+
            (cloudRunwayTarget?' to target '+cloudRunwayTarget:'')+'.';
          if(cloudRunwayMode==='ENTRY_SPECIFIC_M1_ORDER'){
            runwayText+=' M1 entry-specific runway is active'+
              ((cloudRunwayCandidateLow||cloudRunwayCandidateHigh)
                ? ' inside core '+(cloudRunwayCandidateLow||'—')+'–'+(cloudRunwayCandidateHigh||'—')
                : '')+
              (cloudRunwayEntryLimit?' (limit '+cloudRunwayEntryLimit+')':'')+
              '; the actual quote is checked again immediately before order.';
          }else if(cloudRunwayMode==='RR_ONLY_M1_ORDER'){
            runwayText=' Absolute runway is observation only. Sequence '+(seqVersion||'current')+' checks minimum RR from the actual M1 entry and its confirmed execution SL to still-open objectives. Sequence 3.69+ uses the nearest confirmed still-protected M1 swing plus buffer for the order SL, while the wider HTF zone remains thesis invalidation.';
          }else if(cloudRunwayMode==='CONSERVATIVE_CORE_EDGE_COMPAT'){
            runwayText+=' Conservative core-edge compatibility guard remains active until the matching Sequence runtime is loaded.'+
              (cloudConservativeEdgeRunway?' Edge runway '+cloudConservativeEdgeRunway+'.':'');
          }
        }
        let historyText='';
        if(why.includes('ANALYSIS_HISTORY_WINDOW_INCOMPLETE')){
          historyText=' Failed history: '+(cloudHistoryFailures||'UNSPECIFIED')+'.'+
            (cloudHistoryMetrics?' Snapshot depth: '+cloudHistoryMetrics+'.':'');
        }
        seqMeta.textContent='Sequence matches the finalized Cloud plan. Hold reason: '+why+'.'+runwayText+historyText+' Entry permission: NO.';
      }else if(seqMismatch){
        seqGate.textContent='AUTHORITY MISMATCH';
        seqGate.className='kpi bad';
        seqMeta.textContent='Final Cloud authority='+String(seq.cloud_authority||'NONE')+' but Sequence authority='+seqAuthority+'. Gate '+seqStage+' • '+seqReason;
      }else if(seqStage==='ORDER_SENT'){
        seqGate.textContent='ORDER SENT';
        seqGate.className='kpi ok';
        seqMeta.textContent='Sequence '+String(seq.version||'')+' sent the paper order. Model '+String(seq.last_execution_model||seqModel)+'.'+traceText;
      }else if(seqAuthority!=='NONE'){
        const valueWait=seqStage==='VALUE'||seqStage==='VALUE_PD_ARRAY'||seqStage==='FLIP_VALUE_PD_ARRAY'||seqReason.includes('WAITING_FOR_VALID_VALUE')||seqReason.includes('WAITING_FOR_PULLBACK');
        const reactionWait=seqStage==='ENTRY_CONFIRMATION'||seqStage==='REENTRY_CONFIRMATION'||seqStage==='HANDOFF_CONFIRMATION'||seqStage==='FLIP_CONFIRMATION';
        const minRRBlock=seqStage==='TARGET'&&seqReason.includes('MIN_RR_NOT_MET');
        const runwayBlock=cloudRunwayMode!=='RR_ONLY_M1_ORDER'&&seqStage==='TARGET'&&seqReason.includes('ENTRY_SPECIFIC_RUNWAY_NOT_MET');
        const targetExpired=seqStage==='TARGET'&&seqReason.includes('POST_HANDOFF_OBJECTIVE_ALREADY_TRADED');
        const limitReached=seqStage==='THESIS'&&seqReason.includes('REENTRY_LIMIT_REACHED');
        const sniperWait=['M1_SWEEP','M1_MICRO_MSS','M1_MICRO_SHIFT','M1_OB_FVG','M1_PD_PULLBACK','M1_DIRECTIONAL_CLOSE'].includes(seqStage);
        const breakoutWait=['BREAKOUT_BOUNDARY','BREAKOUT_DISPLACEMENT','BREAKOUT_ACCEPTANCE','BREAKOUT_RETEST','BREAKOUT_DIRECTIONAL_CLOSE'].includes(seqStage);
        const continuationWait=['CONTINUATION_M1_SHIFT','CONTINUATION_OB_FVG','CONTINUATION_PD_PULLBACK','CONTINUATION_POST_RETEST_M1_SHIFT'].includes(seqStage);
        const sniperGateLabel=(sniperWait&&reacquisitionSlot)?(reacquisitionSlot+' • '+seqStage.replaceAll('_',' ')):seqStage.replaceAll('_',' ');
        seqGate.textContent=limitReached?'THESIS ENTRY LIMIT REACHED':(runwayBlock?'ENTRY BLOCKED: RUNWAY':(minRRBlock?'ENTRY BLOCKED: MIN RR':(targetExpired?'ENTRY BLOCKED: OBJECTIVE ALREADY TRADED':(reactionWait?'WAITING FOR CLOSED M1 CONFIRMATION':(valueWait?'WAITING FOR VALUE / RETRACE':((sniperWait||breakoutWait||continuationWait)?sniperGateLabel:seqStage.replaceAll('_',' ')))))));
        seqGate.className='kpi '+(limitReached||runwayBlock||minRRBlock||targetExpired?'warn':((valueWait||reactionWait)?'blue':'warn'));
        seqMeta.textContent='Authority '+seqAuthority+' • model '+seqModel+' • '+(seqReason||'waiting for next micro gate')+' • Entry permission: NO.'+traceText;
      }else{
        seqGate.textContent=seqStage.replaceAll('_',' ');
        seqGate.className='kpi warn';
        seqMeta.textContent='No Sequence execution authority. '+(seqReason||'Waiting for a cloud handoff.') ;
      }
    }

    const liveSafetyHold=seqStage==='SAFETY' && seqReason.startsWith('CLOUD_LIVE_BLOCK:');
    if(m1 && !seqOnline){
      state='SEQUENCE OFFLINE';
      cls='bad';
      meta=checklist+'Macro handoff exists, but fresh Sequence telemetry is unavailable. Entry permission: NO.';
    }else if(seqOnline && liveSafetyHold){
      state='EXECUTION HOLD';
      cls='bad';
      meta=checklist+(seqAuthority!=='NONE'
        ? 'Macro authority '+seqAuthority+' remains synchronized. '
        : 'Macro owner/context remains preserved. ')
        +'Order permission is blocked by '+seqReason.replace('CLOUD_LIVE_BLOCK:','')+'. Entry permission: NO.';
    }else if(seqOnline && seqStage==='AUTHORITY' && seqReason==='PLAN_WATCH_ONLY' && cloudMode==='WATCH_ONLY'){
      state='CLOUD PLAN WATCH ONLY';
      cls='warn';
      const why=(cloudSeparation&&cloudSeparation!=='PASS')?cloudSeparation:(cloudGuard||'NO_EXECUTION_HANDOFF');
      const historyText=why.includes('ANALYSIS_HISTORY_WINDOW_INCOMPLETE')
        ? ' Failed history: '+(cloudHistoryFailures||'UNSPECIFIED')+'.'+(cloudHistoryMetrics?' Snapshot depth: '+cloudHistoryMetrics+'.':'')
        : '';
      meta=checklist+'Finalized Cloud execution plan is intentionally non-executable: '+why+'.'+historyText+' Entry permission: NO.';
    }else if(seqOnline && seqMismatch){
      state='EXECUTION HOLD';
      cls='bad';
      meta=checklist+'Final Cloud/Sequence authority is not reconciled. Entry permission: NO. '+(seqReason||'');
    }else if(seqOnline && seqOpen===0 && seqAuthority!=='NONE'){
      const valueWait=seqStage==='VALUE'||seqStage==='VALUE_PD_ARRAY'||seqStage==='FLIP_VALUE_PD_ARRAY'||seqReason.includes('WAITING_FOR_VALID_VALUE')||seqReason.includes('WAITING_FOR_PULLBACK');
      const reactionWait=seqStage==='ENTRY_CONFIRMATION'||seqStage==='REENTRY_CONFIRMATION'||seqStage==='HANDOFF_CONFIRMATION'||seqStage==='FLIP_CONFIRMATION';
      const minRRBlock=seqStage==='TARGET'&&seqReason.includes('MIN_RR_NOT_MET');
      const targetExpired=seqStage==='TARGET'&&seqReason.includes('POST_HANDOFF_OBJECTIVE_ALREADY_TRADED');
      const limitReached=seqStage==='THESIS'&&seqReason.includes('REENTRY_LIMIT_REACHED');
      const simplePrimaryWait=['M1_SWEEP','M1_MICRO_MSS','M1_MICRO_SHIFT','M1_OB_FVG','M1_PD_PULLBACK','M1_DIRECTIONAL_CLOSE'].includes(seqStage);
      const breakoutWait=['BREAKOUT_BOUNDARY','BREAKOUT_DISPLACEMENT','BREAKOUT_ACCEPTANCE','BREAKOUT_RETEST','BREAKOUT_DIRECTIONAL_CLOSE'].includes(seqStage);
      const continuationWait=['CONTINUATION_M1_SHIFT','CONTINUATION_OB_FVG','CONTINUATION_PD_PULLBACK','CONTINUATION_POST_RETEST_M1_SHIFT'].includes(seqStage);
      const forming=simplePrimaryWait||breakoutWait||continuationWait||['SWEEP','FLIP_SWEEP','MSS_BOS','FLIP_MSS_BOS','DISPLACEMENT','FLIP_DISPLACEMENT'].includes(seqStage);
      const hold=['SAFETY','RISK','TARGET','DUPLICATE','AUTHORITY','DATA','MARKET','BAR','BREAKOUT_NO_CHASE','BREAKOUT_REGIME'].includes(seqStage);
      if(seqStage==='ORDER_SENT'){
        state='ORDER SENT';
        cls='ok';
        meta=checklist+'Sequence has completed its entry gates and sent the paper order.';
      }else if(seqStage==='LOCATION' || !freshM1){
        state=ownerMatch ? 'THESIS OWNER • WAITING FOR FRESH M1 LOCATION' : 'WAITING FOR M1 LOCATION';
        cls='warn';
        meta=checklist+(ownerMatch
          ? 'The BUY/SELL thesis owner and macro authority are preserved, but Sequence has no fresh entry location yet. '
          : 'Macro authority exists, but Sequence has no fresh entry location yet. ')+
          (seqReason?('Sequence: '+seqReason.replaceAll('_',' ')+'. '):'')+'Entry permission: NO.';
      }else if(limitReached){
        state='THESIS ENTRY LIMIT REACHED';
        cls='warn';
        meta=checklist+'The configured re-entry allowance for this acquired thesis is exhausted. No further same-thesis entry is permitted unless a new thesis is legitimately acquired.';
      }else if(minRRBlock){
        state='ENTRY BLOCKED: MIN RR';
        cls='warn';
        meta=checklist+'A structural entry candidate exists, but reward to the nearest still-open objective is below the plan minimum RR. Entry permission: NO.';
      }else if(targetExpired){
        state='ENTRY BLOCKED: OBJECTIVE ALREADY TRADED';
        cls='warn';
        meta=checklist+'The nearest post-handoff objective already traded after the handoff, so the late entry is expired rather than chased. Entry permission: NO.';
      }else if(simplePrimaryWait){
        const isReacquisition=Boolean(reacquisitionSlot);
        state=isReacquisition ? (reacquisitionSlot+' ZONE RE-ACQUISITION FORMING') : 'M1 PRIMARY SEQUENCE FORMING';
        cls='blue';
        meta=checklist+(isReacquisition
          ? reacquisitionSlot+' belongs to the same acquired thesis. Sequence 3.71+ is reconstructing the original-zone M1 event chain from its bounded R1/R2 history window: zone contact → micro-liquidity sweep → CLOSED M1 micro structure shift → causal OB/FVG → bounded retest → directional close. This does not reset the campaign or loosen the re-entry cap. '
          : 'Model 1 P0: zone interaction → micro-liquidity sweep → CLOSED M1 micro structure shift → causal OB/FVG → bounded retest → directional close. ')+
          'Model 2 engulfing remains a parallel independent trigger; a missed engulfing may use its bounded value-retest recovery without requiring the Model-1 shift. Current gate: '+seqStage.replaceAll('_',' ')+'. Entry permission: NO.'+traceText;
      }else if(breakoutWait){
        state='BREAKOUT SEQUENCE FORMING';
        cls='blue';
        meta=checklist+'Model 3 is progressing through institutional boundary break → displacement → acceptance → retest → CLOSED directional M1 confirmation. No separate Model-1 micro-structure shift is required. Current gate: '+seqStage.replaceAll('_',' ')+'. Entry permission: NO.'+traceText;
      }else if(continuationWait){
        state='CONTINUATION RE-ENTRY FORMING';
        cls='blue';
        meta=checklist+'R1/R2 continuation is evaluating the causal displacement OB/FVG and still requires a CLOSED M1 micro structure shift before entry. Current gate: '+seqStage.replaceAll('_',' ')+'. Entry permission: NO.'+traceText;
      }else if(reactionWait){
        state='WAITING FOR M1 CONFIRMATION';
        cls='blue';
        meta=checklist+((seqModel==='MASTER_SNIPER_PD_RETEST'||seqModel==='ZONE_ENGULFING'||seqModel==='ZONE_ENGULFING_RETEST')
          ? 'Sniper model is waiting for its final closed M1 directional confirmation. Entry permission: NO.'
          : 'This non-primary/re-entry model is waiting for its configured closed-M1 confirmation. Entry permission: NO.');
      }else if(valueWait){
        state='WAITING FOR RETRACE';
        cls='blue';
        meta=checklist+((seqModel==='MASTER_SNIPER_PD_RETEST'||seqModel==='ZONE_ENGULFING'||seqModel==='ZONE_ENGULFING_RETEST')
          ? 'Model 1 is waiting for the OB/FVG pullback after the M1 micro MSS. Entry permission: NO.'
          : 'This non-primary/re-entry model is waiting for its configured value retrace. Entry permission: NO.');
      }else if(forming){
        state='M1 SEQUENCE FORMING';
        cls='blue';
        meta=checklist+'Macro handoff is active. Current micro gate: '+seqStage.replaceAll('_',' ')+'. Entry permission: NO.';
      }else if(hold){
        state='EXECUTION HOLD';
        cls=seqStage==='SAFETY'?'bad':'warn';
        meta=checklist+'Sequence gate '+seqStage.replaceAll('_',' ')+' is holding execution. '+(seqReason||'')+' Entry permission: NO.';
      }else{
        state='M1 SEQUENCE ACTIVE';
        cls='blue';
        meta=checklist+'Macro execution authority is live. Sequence is currently at '+seqStage.replaceAll('_',' ')+'. Entry permission: NO until the order gate completes.';
      }
    }

    if(cloudHistoryWarnings && cloudHistoryWarnings!=='NONE' && cloudMode!=='WATCH_ONLY'){
      meta+=' DXY extended-depth warning (non-blocking): '+cloudHistoryWarnings+'.';
    }
    if(exec.textContent!==state)exec.textContent=state;
    exec.className='kpi '+cls;
    execMeta.textContent=meta;
  }

  refreshJournalContext();
  refreshReadinessSplit();
  refreshMitigationAudit();

  const checks=document.getElementById('checks');
  if(checks){
    new MutationObserver(function(){
      refreshReadinessSplit();
      refreshJournalContext();
    }).observe(checks,{childList:true,subtree:true});
  }
  // Deliberately no MutationObserver on #zones. refreshJournalContext() writes
  // ownership tags back into that same subtree; observing it creates a
  // self-triggering mutation loop on mobile browsers. The bounded 3-second timer
  // below is the sole refresh mechanism for ownership and mitigation audit.
  window.setInterval(function(){
    refreshJournalContext();
    refreshReadinessSplit();
    refreshMitigationAudit();
  },3000);
})();
</script>
'''.strip()


def compact_dashboard_html(html: str) -> str:
    """Presentation-only cleanup for the human dashboard.

    The raw execution-policy panel is removed, map visibility, thesis-direction ownership, and current M1 entry authority are
    explained separately, and HTF setup quality is separated from
    M1 execution readiness. This function does not alter /mt5/plan,
    deterministic analysis, AI approval, risk controls, or any MT5/Sequence EA
    code path.
    """
    cleaned = _EXECUTION_CONTRACT_CARD.sub("", html, count=1)
    cleaned = cleaned.replace(_EXECUTION_CONTRACT_BINDING, _EXECUTION_POLICY_BINDING)
    cleaned = cleaned.replace(_FRESHNESS_LABEL_BINDING, _FRESHNESS_LABEL_REPLACEMENT)

    if 'id="mitigationAudit"' not in cleaned and _JOURNAL_ANCHOR in cleaned:
        cleaned = cleaned.replace(_JOURNAL_ANCHOR, _MITIGATION_AUDIT_CARD + "\n" + _JOURNAL_ANCHOR, 1)

    if 'id="sniperValidationLedger"' not in cleaned and _JOURNAL_ANCHOR in cleaned:
        cleaned = cleaned.replace(_JOURNAL_ANCHOR, _VALIDATION_LEDGER_CARD + "\n" + _JOURNAL_ANCHOR, 1)

    if 'id="journalContext"' not in cleaned and _JOURNAL_ANCHOR in cleaned:
        cleaned = cleaned.replace(_JOURNAL_ANCHOR, _JOURNAL_CONTEXT_CARD + "\n" + _JOURNAL_ANCHOR, 1)

    if 'id="htfScore"' not in cleaned and _READINESS_CARD in cleaned:
        cleaned = cleaned.replace(_READINESS_CARD, _READINESS_SPLIT, 1)

    if 'id="sniper-validation-ledger-script"' not in cleaned and "</body>" in cleaned:
        cleaned = cleaned.replace("</body>", _VALIDATION_LEDGER_SCRIPT + "\n</body>", 1)

    if 'id="journal-context-readonly-script"' not in cleaned and "</body>" in cleaned:
        cleaned = cleaned.replace("</body>", _JOURNAL_CONTEXT_SCRIPT + "\n</body>", 1)

    return cleaned
