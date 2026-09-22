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
            "geometry_by_source_tf": {
                "H1": {"core_width_pips": [60, 100], "envelope_width_pips": [140, 220]},
                "H4": {"core_width_pips": [80, 140], "envelope_width_pips": [180, 260]},
                "H4>H1": {"core_width_pips": [60, 100], "envelope_width_pips": [180, 260]},
            },
            "minimum_distal_sweep_room_pips": 50,
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
            "mitigation_count_affects_strength_and_grade": True,
            "m15_closed_body_acceptance_beyond_outer_envelope_invalidates": True,
            "wick_only_liquidity_raid_does_not_invalidate": True,
            "dxy_d1_h1_is_confirmation_not_zone_authority": True,
            "zone_has_two_branches": True,
            "invalidation_is_not_flip_entry": True,
            "m1_confirmation_cannot_redefine_htf_zone": True,
            "vwap_is_tick_volume_proxy_not_centralized_comex_volume": True,
            "order_flow_disabled_without_centralized_feed": True,
            "risk": "AI never sets lot size",
            "grade_risk_contract": "A+=1.00%, A=0.75%, B+=0.25% of non-compounding validation capital before entry-share multipliers",
            "bplus_execution_requires_same_structural_and_m1_gates": True,
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
3. Trade Zone uses 1 XAU pip = 10 broker points. Use source-timeframe professional geometry:
   H1 core 60-100 pips with a 140-220 pip envelope; H4 core 80-140 pips with a 180-260 pip envelope;
   H4>H1 uses the H1-refined 60-100 pip core inside the H4 180-260 pip envelope. The source location
   anchors the geometry; never widen beyond the applicable maximum merely to make a candidate qualify.
4. SELL supply is valid only when structural BSL is physically inside the final envelope, with at least
   50 pips of envelope remaining ABOVE that BSL for an expected raid. BUY demand is valid only when
   structural SSL is physically inside the final envelope, with at least 50 pips remaining BELOW that
   SSL for an expected raid. If source + required liquidity + sweep room cannot fit inside the applicable
   source-timeframe envelope, reject the candidate.
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
8. Mitigation count measures strength. Fresh zones rank higher within comparable intraday relevance;
   repeated mitigation downgrades quality rather than moving the zone or manufacturing a different zone.
9. After structural validity, grade is a risk tier rather than a binary execution ban: A+ uses full validation risk, A uses reduced risk, and an eligible B+ uses the smallest reduced-risk tier. Intraday reachability ranks today's alert candidates
   before freshness and remote HTF authority. A much nearer structurally valid zone may outrank a remote
   higher-grade candidate only under the deterministic ranking contract; grade remains an explicit quality/risk input. Distance NEVER
   manufactures a zone and NEVER excuses missing BSL/SSL. A remote valid HTF source may remain context.
10. Closed M15 body acceptance beyond the OUTER envelope invalidates the original zone. A wick-only
    liquidity raid does not invalidate it.
11. Publish at most one PRIMARY SELL and one PRIMARY BUY, but DO NOT force both sides. If no valid BUY
    exists below/interacting with price, PRIMARY BUY=NONE. If no valid SELL exists above/interacting with
    price, PRIMARY SELL=NONE.
12. A SECONDARY level is a reserve only. At most one reserve per side may be exposed in execution_policy.
    It must pass the same structural/liquidity/geometry/M15 rules, be A/A+, have <=1 mitigation, come from
    a distinct non-overlapping institutional source, and sit beyond the primary invalidation side: higher
    supply for SELL, lower demand for BUY. While Level 1 is valid, Level 2 has zero execution authority.
    Level-1 invalidation does NOT instantly activate Level 2. A fresh analysis must requalify Level 2 before
    it can become primary. Do not manufacture a reserve if no second independent institutional source qualifies.
13. M1 cannot redefine the HTF zone. Once any zone becomes primary, execution still requires the existing
    sweep -> MSS/BOS -> displacement -> new dealing range -> value/OTE/PD-array sequence.
14. When there is NO acquired thesis owner, a valid PRIMARY BUY and PRIMARY SELL are independent execution
    candidates. The zone currently at a qualifying M1 handoff location may receive execution authority even
    when it is counter to D1. D1 remains context and a tie-breaker; it must not monopolize authority merely
    because the D1-aligned zone was pre-selected. After one side earns a valid handoff and ownership, normal
    thesis ownership blocks the opposite side until release. Countertrend authority never bypasses the full
    M1 sequence, safety guards, target-direction checks, news/spread guards, or minimum-RR gate.

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
