from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
from .intraday_engine import build_analysis
from .execution_models import build_execution_overlay, regime_brief
from .h4_liquidity_policy import apply_latest_h4_liquidity_policy
from .institutional_two_zone import apply_two_zone_institutional_map
from .ml_foundation import capture_cloud_candidates
from .models import Analysis
from .watch_ready import promote_watch_to_m1_ready


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())
    a = build_analysis(s, now)

    # Legacy H4 discovery still runs first, but the final public map below is
    # authoritative and now requires the correct BSL/SSL inside the marked zone.
    h4_ready = apply_latest_h4_liquidity_policy(a, s)

    # Public map: one best institutional SELL and one best institutional BUY.
    # SELL must contain BSL; BUY must contain SSL; repeated mitigation is rejected.
    primary_zones = apply_two_zone_institutional_map(a, s)

    # PAPER_ONLY handoff: only the primary core price is actually interacting with
    # may become M1_READY. Existing M1 confirmation remains unchanged downstream.
    ready_zone = promote_watch_to_m1_ready(a, s)

    overlay = build_execution_overlay(s, a, reason)
    a.execution_policy = {**a.execution_policy, "multi_model": overlay}
    a.prompt_version = "SMC_V6_4_9_PROMPT_GUIDED_LIQUIDITY_ZONE"
    a.trader_brief += " " + regime_brief(overlay)
    try:
        ok, summary, risks, provider = await validate_with_ai(a, s)
        a.ai_provider = provider
        selected = bool(a.selected_zone_id)
        execution_selected = bool(
            ready_zone is not None
            and a.selected_zone_id
            and ready_zone.zone_id == a.selected_zone_id
        )
        a.ai_approved = bool(ok and execution_selected)
        if execution_selected:
            if summary:
                a.trader_brief += " AI execution validation: " + summary
        elif selected:
            a.trader_brief += " AI validation: primary plan ARMED; execution validation waits for core interaction/M1_READY."
        else:
            a.trader_brief += " AI validation: no prompt-qualified primary zone is currently selected; execution waits."
        if risks:
            a.guards.extend([f"AI:{x}" for x in risks])

        if selected and not execution_selected:
            a.approved = False
        elif SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and execution_selected and not ok:
            a.approved = False

        audit(
            now,
            "analysis.ai",
            f"reason={reason} provider={provider} approved={a.ai_approved} "
            f"selected={selected} execution_selected={execution_selected} "
            f"paper_m1_ready={bool(ready_zone)} h4_liquidity_ready={len(h4_ready)} "
            f"primary_zones={len(primary_zones)} risks={risks}",
        )
    except Exception as exc:
        audit(now, "analysis.ai.error", f"reason={reason} error={type(exc).__name__}:{exc}")
        a.ai_provider = "ERROR"
        a.ai_approved = False
        if a.selected_zone_id:
            a.approved = False
            if ready_zone is not None:
                a.guards.append("AI_PROVIDER_UNAVAILABLE")
        else:
            a.trader_brief += " AI validation unavailable; prompt-qualified zones remain analysis-only locations."
    save_analysis(a)
    if SETTINGS.ml_data_enabled:
        try:
            capture_cloud_candidates(a, s, reason)
        except Exception as exc:
            audit(now, "ml.cloud.error", f"reason={reason} analysis_id={a.analysis_id} error={type(exc).__name__}:{exc}")
    audit(
        now,
        "analysis.completed",
        f"reason={reason} id={a.analysis_id} approved={a.approved} zones={len(a.zones)} "
        f"selected={a.selected_zone_id or 'NONE'} paper_m1_ready={bool(ready_zone)} "
        f"h4_liquidity_ready={len(h4_ready)} "
        f"regime={overlay['regime']['name']} ml_data={SETTINGS.ml_data_enabled}",
    )
    return a


def active_analysis() -> Analysis | None:
    # Newest market analysis is always the current truth. AI approval gates the
    # paper plan; it must never cause an older analysis to replace a newer map.
    return latest_analysis(ai_required=False)
