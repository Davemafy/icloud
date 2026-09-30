from __future__ import annotations

import json
import re
from typing import Any
import httpx

from .config import SETTINGS
from .models import Analysis, MarketSnapshot


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise ValueError("AI response did not contain JSON")
        return json.loads(m.group(0))


def _payload(a: Analysis, s: MarketSnapshot) -> dict[str, Any]:
    return {
        "analysis_id": a.analysis_id,
        "current_mid": s.mid,
        "overall_bias": a.overall_bias.value,
        "primary_liquidity": a.primary_liquidity,
        "spread_points": s.spread_points,
        "guards": a.guards,
        "execution_policy": a.execution_policy,
        "zones": [
            {
                "zone_id": z.zone_id,
                "original_direction": z.original_direction.value,
                "flip_direction": z.flip_direction.value,
                "setup_type": z.setup_type,
                "source_tf": z.source_tf,
                "grade": z.grade.value,
                "core": [z.core_low, z.core_high],
                "envelope": [z.zone_low, z.zone_high],
                "core_method": z.core_method,
                "location_score": z.location_score,
                "touch_count": z.touch_count,
                "mitigation_audit": z.mitigation_audit,
                "confluences": z.confluences,
                "clear_run": z.clear_run,
                "dxy_support": z.dxy_support,
                "invalidation_rule": z.invalidation_rule,
                "notes": z.notes,
            }
            for z in a.zones
        ],
        "rules": {
            "prompt_contract_ref": "ZONE_FORMATION_PROMPT_2026_09_14_V659",
            "no_future_leakage": True,
            "max_primary_zones": 2,
            "one_primary_zone_per_side": True,
            "no_forced_second_primary_zone": True,
            "max_secondary_reserve_per_side": 1,
            "secondary_reserve_is_context_only": True,
            "secondary_reserve_has_no_execution_authority": True,
            "secondary_requires_primary_m15_invalidation_then_fresh_requalification": True,
            "sell_secondary_must_be_distinct_higher_supply": True,
            "buy_secondary_must_be_distinct_lower_demand": True,
            "d1_context_only": True,
            "h4_parent_location_is_primary": True,
            "h1_refines_h4_or_is_fallback_only": True,
            "xau_points_per_pip": 10,
            "geometry_authority": "MASTER_SNIPER_TACTICAL_MAP_V6593",
            "source_candles_are_provenance_not_fixed_width_alert_boxes": True,
            "native_h1_refinement_can_extend_h4_parent_edge": True,
            "distal_sweep_room_is_volatility_scaled": True,
            "source_edge_snap_must_preserve_distal_sweep_room": True,
            "sell_requires_structural_bsl_inside_envelope": True,
            "buy_requires_structural_ssl_inside_envelope": True,
            "sell_sweep_room_is_above_bsl": True,
            "buy_sweep_room_is_below_ssl": True,
            "equal_high_low_are_liquidity_objects_only": True,
            "equal_high_low_do_not_create_zone_without_h4_h1_source": True,
            "buy_zone_must_be_below_or_interacting_with_current_price": True,
            "sell_zone_must_be_above_or_interacting_with_current_price": True,
            "wrong_side_zone_is_rejected_not_flipped": True,
            "intraday_reachability_ranks_valid_zones_only": True,
            "remote_htf_zone_can_remain_context": True,
            "psy_level_alone_never_qualifies_zone": True,
            "liquidity_sweep_rejection_source_is_valid_htf_source": True,
            "displacement_bos_source_is_valid_htf_source": True,
            "fvg_is_quality_confluence_not_mandatory": True,
            "mitigation_count_affects_strength_and_grade": False,
            "mitigation_count_is_telemetry_only": True,
            "zone_grade_immutable_for_analysis_cycle": True,
            "touch_count_changes_risk_ranking_or_execution": False,
            "touch_count_semantics": "directional complete mitigation cycles only",
            "sell_mitigation_cycle": "below envelope -> core -> below envelope",
            "buy_mitigation_cycle": "above envelope -> core -> above envelope",
            "wrong_side_contact_consumes_freshness": False,
            "accepted_invalidation_stops_original_zone_counter": True,
            "mitigation_clock_starts_after_source_candle_close": True,
            "incomplete_m15_freshness_history_is_watch_only": False,
            "trend_countertrend_use_separate_grade_models": True,
            "post_reaction_profit_never_upgrades_historical_grade": True,
            "m15_closed_body_acceptance_beyond_outer_envelope_invalidates": True,
            "wick_only_liquidity_raid_does_not_invalidate": True,
            "dxy_d1_h4_h1_is_confirmation_not_zone_authority": True,
            "zone_has_two_branches": True,
            "invalidation_is_not_flip_entry": True,
            "m1_confirmation_cannot_redefine_htf_zone": True,
            "vwap_is_tick_volume_proxy_not_centralized_comex_volume": True,
            "order_flow_disabled_without_centralized_feed": True,
            "risk": "AI never sets lot size",
            "context_grade_risk_contract": "TREND A+=1.00%, TREND A=0.75%, COUNTERTREND A+=0.50%, COUNTERTREND A=0.25% of non-compounding validation capital before entry-share/model multipliers",
            "bplus_execution_authority": True,
            "bplus_role": "reduced-risk execution grade at 0.25% with all normal M15/M1/AI/safety gates",
        },
    }


SYSTEM = """You are a conservative validation layer for an XAUUSD institutional chart-analysis engine.
Use ONLY the market data supplied by the deterministic engine. Do not invent prices, unseen candles,
volume, news, liquidity, FVGs, or zones. Do not move a published zone to make it fit a theory.

Validate the prompt-driven PAPER/DEMO zone map with these rules:
1. D1 gives the main context/bias. H4 is the main institutional source timeframe. H1 may refine an H4
   source or act as tactical fallback. M15 checks health/invalidation. M1 is entry timing only.
2. Every published primary zone must be anchored to a visible H4/H1 source that either:
   a) caused decisive displacement/BOS away, or
   b) swept liquidity, rejected, and was followed by decisive displacement.
3. Trade Zone uses 1 XAU pip = 10 broker points. H4/H1 source candles are provenance and the H1 child
   may refine the H4 parent near an edge. The published alert zone is the native tactical reaction band
   built from the exact institutional core, attached structural liquidity and volatility-scaled M15 sweep
   room. Do not impose old fixed-width 60/100/180/260-pip padding or reject a valid H1 refinement merely
   because it extends slightly beyond the parent wick.
4. SELL supply requires genuine structural BSL attached to the institutional source; BUY demand requires
   genuine structural SSL. Preserve volatility-scaled distal sweep room beyond that liquidity. If a source
   edge is used for display precision, snapping must NEVER collapse the distal sweep room to zero. Remote
   liquidity must not be dragged into a source merely to make it qualify.
5. Equal highs/equal lows are liquidity objects only. They may identify resting BSL/SSL, sweep objectives,
   or inducement, but they do NOT create a trading zone by themselves. A zone still requires the valid
   H4/H1 institutional source in rule 2.
6. Alert-side placement is mandatory. A BUY alert zone cannot sit completely above current price; it must
   be below current price, or current price may already be inside/interacting with it. A SELL alert zone
   cannot sit completely below current price; it must be above current price, or current price may already
   be inside/interacting with it. A wrong-side zone is rejected from today's alert map and is NOT flipped.
7. PSY levels are confluence only and never replace BSL/SSL. FVG/imbalance, rejection wick,
   premium/discount, tick-volume expansion, H4/H1 overlap and DXY may strengthen a zone, but none can
   replace the required structural liquidity.
8. Mitigation count is directional JOURNAL TELEMETRY only.
   SELL mitigation = CLOSED M15 below envelope -> later tactical-core overlap -> CLOSED M15 back below envelope.
   BUY mitigation = CLOSED M15 above envelope -> later tactical-core overlap -> CLOSED M15 back above envelope.
   Record qualified mitigations and raw contacts for research, but NEVER use touch/mitigation count to downgrade,
   block, resize, re-rank, promote or demote a zone. The analysis-time structural grade is immutable for that
   analysis cycle. Only accepted structural invalidation or a new analysis cycle may retire or replace the zone.
9. TREND and COUNTERTREND use different A+/A qualification models. TREND grades continuation-source
   strength and HTF authority. COUNTERTREND grades HTF extremity, structural liquidity raid/rejection,
   reversal-source strength and displacement/FVG/volume/PSY evidence. Mitigation/touch history is telemetry
   only and never changes the analysis-time grade, risk, ranking or execution eligibility. A countertrend
   zone is not downgraded merely because D1 points the other way. Never upgrade a historical zone because
   price later moved strongly away from it. A+, A and B+ are execution grades; B+ uses 0.25% reduced-risk
   authority and still requires every normal M15/M1/AI/safety gate. Base thesis risk is TREND A+=1.00%,
   TREND A=0.75%, COUNTERTREND A+=0.50%, COUNTERTREND A=0.25%, B+=0.25% of non-compounding validation capital
   before entry-share/model multipliers. Intraday reachability ranks structurally valid alert candidates;
   touch/freshness telemetry never participates in ranking. Distance never manufactures a zone and never
   excuses missing structural source/liquidity evidence.
10. Closed M15 body acceptance beyond the OUTER envelope invalidates the original zone and permanently
    stops its mitigation/freshness counter. A wick-only liquidity raid does not invalidate it.
11. Publish at most one PRIMARY SELL and one PRIMARY BUY, but DO NOT force both sides. If no valid BUY
    exists below/interacting with price, PRIMARY BUY=NONE. If no valid SELL exists above/interacting with
    price, PRIMARY SELL=NONE.
12. A SECONDARY level is a reserve only. At most one reserve per side may be exposed in execution_policy.
    It must pass the same structural/liquidity/geometry/M15 rules, be A/A+, come from a distinct non-overlapping
    institutional source, and sit beyond the primary invalidation side: higher supply for SELL, lower demand
    for BUY. Mitigation count is telemetry only and cannot remove the reserve. While Level 1 is valid, Level 2
    remains plotted context; a fresh analysis requalifies it before any promotion. Do not manufacture a reserve
    if no second independent institutional source qualifies.
13. M1 cannot redefine the HTF zone. The PRIMARY FIRST-ENTRY model is deliberately simple and M1-only:
    price contacts the published institutional envelope -> M1 liquidity sweep -> M1 MICRO MSS (internal
    1-minute structure, not M5/M15/HTF structure) -> pullback -> CLOSED M1 candle in the trade direction ->
    entry. M15 validates zone health/accepted invalidation only. Tactical-core touch, M15 sweep/reclaim,
    displacement-ATR thresholds, dealing-range construction, OTE, FVG and PD-array overlap are NOT mandatory
    first-entry gates. Initial SL belongs beyond the full institutional zone with the configured buffer.
14. When there is NO acquired thesis owner, a valid PRIMARY BUY and PRIMARY SELL are independent execution
    candidates. The zone currently at a qualifying M1 handoff location may receive execution authority even
    when it is counter to D1. D1 remains context and a tie-breaker; it must not monopolize authority merely
    because the D1-aligned zone was pre-selected. After one side earns a valid handoff and ownership, normal
    thesis ownership blocks the opposite side until release. Countertrend authority never bypasses spread/news/
    snapshot safety, target-direction checks, actual-entry minimum-RR, risk sizing, or the simple M1 sequence.

This contract comes from the user's institutional XAU framework: identify the MOST IMPORTANT levels where
price is most likely to react, reverse or continue TODAY, while following visible D1/H4/H1/M15 structure,
liquidity, source candles, displacement, FVG, mitigation, ATR/spread/news and DXY confirmation.

Reject validation only when a published primary breaks these rules or supplied safety guards. A reserve
zone in execution_policy is context-only and must not be treated as an active execution zone. Do not reapply
old broad fixed-width geometry, tiny exact-candle envelopes, mandatory two-sided primary output, or mandatory
multi-confluence filters that are not in this prompt-driven contract.

Return JSON only: {"approved": true|false, "summary": "...", "risks": ["..."]}.
"""


async def validate_with_ai(a: Analysis, s: MarketSnapshot) -> tuple[bool, str, list[str], str]:
    if not SETTINGS.ai_enabled:
        return True, "AI disabled; deterministic engine only.", [], "DETERMINISTIC"
    prompt = SYSTEM + "\nINPUT:\n" + json.dumps(_payload(a, s), separators=(",", ":"))
    timeout = httpx.Timeout(SETTINGS.ai_timeout_seconds)
    if SETTINGS.gemini_api_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{SETTINGS.gemini_model}:generateContent"
        params = {"key": SETTINGS.gemini_api_key}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, params=params, json=body)
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            obj = _extract_json(text)
            return bool(obj.get("approved")), str(obj.get("summary", "")), list(obj.get("risks", [])), f"GEMINI:{SETTINGS.gemini_model}"
    if SETTINGS.ai_compat_url and SETTINGS.ai_compat_key and SETTINGS.ai_compat_model:
        headers = {"Authorization": f"Bearer {SETTINGS.ai_compat_key}", "Content-Type": "application/json"}
        body = {
            "model": SETTINGS.ai_compat_model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(_payload(a, s))},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(SETTINGS.ai_compat_url, headers=headers, json=body)
            r.raise_for_status()
            obj = _extract_json(r.json()["choices"][0]["message"]["content"])
            return bool(obj.get("approved")), str(obj.get("summary", "")), list(obj.get("risks", [])), f"COMPAT:{SETTINGS.ai_compat_model}"
    if SETTINGS.require_ai_for_execution:
        return False, "AI required but no provider configured.", ["AI_PROVIDER_UNAVAILABLE"], "NONE"
    return True, "No AI provider configured; deterministic analysis allowed by settings.", [], "DETERMINISTIC"
