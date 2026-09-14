from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
from .intraday_engine import build_analysis
from .execution_models import build_execution_overlay, regime_brief
from .ml_foundation import capture_cloud_candidates
from .models import Analysis


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())
    a = build_analysis(s, now)
    overlay = build_execution_overlay(s, a, reason)
    a.execution_policy = {**a.execution_policy, "multi_model": overlay}
    a.prompt_version = "SMC_V6_4_3_INTRADAY_ZONE_READINESS"
    a.trader_brief += " " + regime_brief(overlay)
    try:
        ok, summary, risks, provider = await validate_with_ai(a, s)
        a.ai_provider = provider
        actionable_selected = bool(a.selected_zone_id)
        a.ai_approved = bool(ok and actionable_selected)
        if actionable_selected:
            if summary:
                a.trader_brief += " AI validation: " + summary
        else:
            a.trader_brief += " AI validation: analysis-only; no ACTIONABLE zone is selected, so execution validation is not applicable."
        if risks:
            a.guards.extend([f"AI:{x}" for x in risks])
        if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and actionable_selected and not ok:
            a.approved = False
        audit(now, "analysis.ai", f"reason={reason} provider={provider} approved={a.ai_approved} actionable={actionable_selected} risks={risks}")
    except Exception as exc:
        audit(now, "analysis.ai.error", f"reason={reason} error={type(exc).__name__}:{exc}")
        a.ai_provider = "ERROR"
        a.ai_approved = False
        if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and a.selected_zone_id:
            a.approved = False
            a.guards.append("AI_PROVIDER_UNAVAILABLE")
        elif not a.selected_zone_id:
            a.trader_brief += " AI validation unavailable, but there is no ACTIONABLE zone and execution remains disabled."
    save_analysis(a)
    if SETTINGS.ml_data_enabled:
        try:
            capture_cloud_candidates(a, s, reason)
        except Exception as exc:
            audit(now, "ml.cloud.error", f"reason={reason} analysis_id={a.analysis_id} error={type(exc).__name__}:{exc}")
    audit(now, "analysis.completed", f"reason={reason} id={a.analysis_id} approved={a.approved} zones={len(a.zones)} selected={a.selected_zone_id or 'NONE'} regime={overlay['regime']['name']} ml_data={SETTINGS.ml_data_enabled}")
    return a


def active_analysis() -> Analysis | None:
    # Newest market analysis is always the current truth. AI approval gates
    # execution in the plan; it must never cause an older approved analysis to
    # replace a newer WATCH/NO_TRADE market map.
    return latest_analysis(ai_required=False)
