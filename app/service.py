from __future__ import annotations

from datetime import datetime, timezone

from .ai import validate_with_ai
from .config import SETTINGS
from .db import audit, latest_analysis, latest_snapshot, save_analysis
from .execution_models import build_execution_overlay, regime_brief
from .institutional_two_zone import build_prompt_analysis
from .ml_foundation import capture_cloud_candidates
from .models import Analysis
from .watch_ready import promote_watch_to_m1_ready


async def run_analysis(reason: str = "MANUAL") -> Analysis:
    s = latest_snapshot()
    if s is None:
        raise RuntimeError("No market snapshot available")
    now = int(datetime.now(timezone.utc).timestamp())

    # Single authoritative zoning path: today's prompt-driven source-candle engine.
    # No legacy H4 policy, compact-envelope expansion, distance gate, or old candidate patching.
    a = build_prompt_analysis(s, now)
    primary_zones = list(a.zones)

    # PAPER_ONLY handoff: M1 only times entry after price reaches a qualified HTF core.
    ready_zone = promote_watch_to_m1_ready(a, s)

    overlay = build_execution_overlay(s, a, reason)
    a.execution_policy = {**a.execution_policy, "multi_model": overlay}
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
            a.trader_brief += " AI validation: primary prompt zone ARMED; execution waits for core interaction/M1_READY."
        else:
            a.trader_brief += " AI validation: no A+/A prompt zone is selected for execution; weaker zones may remain visible as WATCH."
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
            f"paper_m1_ready={bool(ready_zone)} primary_zones={len(primary_zones)} "
            f"prompt_zone_engine=2026_09_14 risks={risks}",
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
            a.trader_brief += " AI validation unavailable; prompt zones remain analysis-only locations."

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
        f"prompt_zone_engine=2026_09_14 "
        f"regime={overlay['regime']['name']} ml_data={SETTINGS.ml_data_enabled}",
    )
    return a


def active_analysis() -> Analysis | None:
    # Newest market analysis is always the current truth. AI approval gates the
    # paper plan; it must never cause an older analysis to replace a newer map.
    return latest_analysis(ai_required=False)
