from __future__ import annotations

import re


_EXECUTION_CONTRACT_CARD = re.compile(
    r'<div class="card"><h3>Execution contract</h3><pre id="policy">.*?</pre></div>',
    flags=re.DOTALL,
)
_EXECUTION_CONTRACT_BINDING = "$('policy').textContent=JSON.stringify(a.execution_policy||{},null,2);"


def compact_dashboard_html(html: str) -> str:
    """Remove the raw execution-policy panel from the human dashboard only.

    The underlying execution policy remains available to the cloud/MT5 APIs. This
    is a presentation cleanup so the institutional brief and actionable trading
    information get the screen space instead of a large unreadable JSON block.
    """
    cleaned = _EXECUTION_CONTRACT_CARD.sub("", html, count=1)
    return cleaned.replace(_EXECUTION_CONTRACT_BINDING, "")
