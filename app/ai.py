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
            "no_future_leakage": True,
            "max_primary_zones": 2,
            "one_primary_zone_per_side": True,
            "d1_context_only": True,
            "h4_parent_location_is_primary": True,
            "h1_refines_h4_or_is_fallback_only": True,
            "zone_is_exact_source_candle_range": True,
            "sell_requires_structural_bsl_inside_marked_zone": True,
            "buy_requires_structural_ssl_inside_marked_zone": True,
            "psy_level_alone_never_qualifies_zone": True,
            "liquidity_sweep_rejection_source_is_valid_htf_source": True,
            "displacement_bos_source_is_valid_htf_source": True,
            "fvg_is_quality_confluence_not_mandatory": True,
            "mitigation_count_affects_strength_and_grade": True,
            "repeated_mitigation_does_not_expand_or_move_zone": True,
            "distance_is_not_a_hard_zone_filter": True,
            "liquidity_must_not_be_used_to_stretch_zone": True,
            "m15_or_h1_closed_body_acceptance_invalidates": True,
            "wick_only_liquidity_raid_does_not_invalidate": True,
            "dxy_is_confirmation_not_zone_authority": True,
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

Validate the prompt-driven zone map with these simple rules:
1. D1 gives the main context/bias. H4 is the main institutional source timeframe. H1 may refine an H4
   source or act as tactical fallback. M15 checks health/invalidation. M1 is entry timing only.
2. Every published zone must come from an exact visible H4/H1 source candle that either:
   a) caused decisive displacement/BOS away, or
   b) swept liquidity, rejected, and was followed by decisive displacement.
3. The marked zone is the source-candle price range. Do not stretch it toward distant liquidity.
4. SELL supply is valid only when structural BSL is physically inside that marked zone.
   BUY demand is valid only when structural SSL is physically inside that marked zone.
   PSY levels are confluence only and never replace BSL/SSL.
5. FVG/imbalance, rejection wick, premium/discount, tick-volume expansion, H4/H1 overlap and DXY may
   strengthen a zone, but none of them can replace the required BSL/SSL.
6. Mitigation count measures strength. Fresh zones rank higher; repeated mitigation should downgrade the
   zone to weaker/WATCH quality rather than move the zone or manufacture a new one.
7. Do not reject a structurally valid source-candle zone only because it is far from current price.
   Distance affects urgency, not whether the institutional zone exists.
8. Closed-body acceptance on M15 or H1 beyond the source-candle boundary invalidates the original zone.
   A wick-only liquidity raid does not.
9. Publish at most one strongest SELL and one strongest BUY. It is acceptable to publish one side or none
   if no source candle contains the correct structural liquidity.
10. M1 cannot redefine the HTF zone. Execution still requires the existing sweep -> MSS/BOS ->
    displacement -> new dealing range -> value/OTE/PD-array sequence.

Reject validation only when a published zone breaks these rules or supplied safety guards. Do not reapply
old compact-envelope, fixed ATR-distance, or mandatory multi-confluence filters that are not in this
prompt-driven contract.

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
