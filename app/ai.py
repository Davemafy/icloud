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
            "prompt_contract_ref": "ZONE_FORMATION_PROMPT_2026_09_14_V653",
            "no_future_leakage": True,
            "max_primary_zones": 2,
            "one_primary_zone_per_side": True,
            "no_forced_second_zone": True,
            "d1_context_only": True,
            "h4_parent_location_is_primary": True,
            "h1_refines_h4_or_is_fallback_only": True,
            "xau_points_per_pip": 10,
            "core_width_pips_min": 100,
            "core_width_pips_max": 200,
            "envelope_width_pips_min": 300,
            "envelope_width_pips_max": 400,
            "minimum_distal_sweep_room_pips": 50,
            "sell_requires_structural_bsl_inside_envelope": True,
            "buy_requires_structural_ssl_inside_envelope": True,
            "sell_sweep_room_is_above_bsl": True,
            "buy_sweep_room_is_below_ssl": True,
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
        },
    }


SYSTEM = """You are a conservative validation layer for an XAUUSD institutional chart-analysis engine.
Use ONLY the market data supplied by the deterministic engine. Do not invent prices, unseen candles,
volume, news, liquidity, FVGs, or zones. Do not move a published zone to make it fit a theory.

Validate the prompt-driven PAPER/DEMO zone map with these rules:
1. D1 gives the main context/bias. H4 is the main institutional source timeframe. H1 may refine an H4
   source or act as tactical fallback. M15 checks health/invalidation. M1 is entry timing only.
2. Every published zone must be anchored to a visible H4/H1 source that either:
   a) caused decisive displacement/BOS away, or
   b) swept liquidity, rejected, and was followed by decisive displacement.
3. Trade Zone uses 1 XAU pip = 10 broker points. The institutional CORE must be 100-200 pips wide.
   The OUTER ENVELOPE must be 300-400 pips wide. The source location anchors both; the envelope may
   extend around the source only to satisfy this width contract and reserve realistic liquidity-sweep room.
4. SELL supply is valid only when structural BSL is physically inside the final envelope, with at least
   50 pips of envelope remaining ABOVE that BSL for an expected raid. BUY demand is valid only when
   structural SSL is physically inside the final envelope, with at least 50 pips remaining BELOW that
   SSL for an expected raid. If core + liquidity + sweep room cannot fit inside 400 pips, reject it.
5. Alert-side placement is mandatory. A BUY alert zone cannot sit completely above current price; it must
   be below current price, or current price may already be inside/interacting with it. A SELL alert zone
   cannot sit completely below current price; it must be above current price, or current price may already
   be inside/interacting with it. A wrong-side zone is rejected from today's alert map and is NOT flipped.
6. PSY levels are confluence only and never replace BSL/SSL. FVG/imbalance, rejection wick,
   premium/discount, tick-volume expansion, H4/H1 overlap and DXY may strengthen a zone, but none can
   replace the required structural liquidity.
7. Mitigation count measures strength. Fresh zones rank higher; repeated mitigation downgrades quality
   rather than moving the zone or manufacturing a different zone.
8. After structural validity and freshness, intraday reachability ranks today's alert candidates. A much
   nearer A/A+ valid zone should outrank a remote equally-executable candidate. Distance NEVER manufactures
   a zone and NEVER excuses missing BSL/SSL. A remote valid HTF source may remain context instead of the
   primary intraday alert.
9. Closed M15 body acceptance beyond the OUTER envelope invalidates the original zone. A wick-only
   liquidity raid does not invalidate it.
10. Publish at most one strongest SELL and one strongest BUY, but DO NOT force both sides. If no valid BUY
    exists below/interacting with price, publish BUY=NONE. If no valid SELL exists above/interacting with
    price, publish SELL=NONE.
11. M1 cannot redefine the HTF zone. Execution still requires the existing sweep -> MSS/BOS ->
    displacement -> new dealing range -> value/OTE/PD-array sequence.

This contract comes from the user's 2026-09-14 institutional XAU prompt: identify the MOST IMPORTANT
levels where price is most likely to react, reverse or continue TODAY, while following visible D1/H4/H1/M15
structure, liquidity, source candles, displacement, FVG, mitigation, ATR/spread/news and DXY confirmation.

Reject validation only when a published zone breaks these rules or supplied safety guards. Do not reapply
old fixed ATR-distance, tiny exact-candle envelope, mandatory two-sided output, or mandatory multi-confluence
filters that are not in this prompt-driven contract.

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
