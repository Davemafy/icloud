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
_JOURNAL_CONTEXT_SCRIPT = r'''
<script id="journal-context-readonly-script">
(function(){
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
  refreshJournalContext();
  window.setInterval(refreshJournalContext,3000);
})();
</script>
'''.strip()


def compact_dashboard_html(html: str) -> str:
    """Presentation-only cleanup for the human dashboard.

    The raw execution-policy panel is removed and a read-only explanation of
    map visibility versus current M1 execution ownership is added. This function
    does not alter /mt5/plan, deterministic analysis, AI approval, risk controls,
    or any MT5/Sequence EA code path.
    """
    cleaned = _EXECUTION_CONTRACT_CARD.sub("", html, count=1)
    cleaned = cleaned.replace(_EXECUTION_CONTRACT_BINDING, "")

    if 'id="journalContext"' not in cleaned and _JOURNAL_ANCHOR in cleaned:
        cleaned = cleaned.replace(_JOURNAL_ANCHOR, _JOURNAL_CONTEXT_CARD + "\n" + _JOURNAL_ANCHOR, 1)

    if 'id="journal-context-readonly-script"' not in cleaned and "</body>" in cleaned:
        cleaned = cleaned.replace("</body>", _JOURNAL_CONTEXT_SCRIPT + "\n</body>", 1)

    return cleaned
