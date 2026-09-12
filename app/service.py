from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
from .engine import build_analysis
from .models import Analysis


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())
    a = build_analysis(s, now)
    try:
        ok, summary, risks, provider = await validate_with_ai(a, s)
        a.ai_provider = provider
        a.ai_approved = ok
        if summary:
            a.trader_brief += " AI validation: " + summary
        if risks:
            a.guards.extend([f"AI:{x}" for x in risks])
        if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and not ok:
            a.approved = False
        audit(now, "analysis.ai", f"reason={reason} provider={provider} approved={ok} risks={risks}")
    except Exception as exc:
        audit(now, "analysis.ai.error", f"reason={reason} error={type(exc).__name__}:{exc}")
        a.ai_provider = "ERROR"
        a.ai_approved = False
        if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled:
            a.approved = False
            a.guards.append("AI_PROVIDER_UNAVAILABLE")
    save_analysis(a)
    audit(now, "analysis.completed", f"reason={reason} id={a.analysis_id} approved={a.approved} zones={len(a.zones)}")
    return a


def active_analysis() -> Analysis | None:
    # Carry-forward rule: if AI is required, keep the latest AI-approved plan rather
    # than allowing a newer provider outage to evict it. Live safety guards are still
    # applied at plan delivery time.
    if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled:
        return latest_analysis(ai_required=True) or latest_analysis(ai_required=False)
    return latest_analysis(ai_required=False)
