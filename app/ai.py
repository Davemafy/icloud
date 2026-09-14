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
            "sell_requires_structural_bsl_inside_marked_zone": True,
            "buy_requires_structural_ssl_inside_marked_zone": True,
            "psy_level_alone_never_qualifies_zone": True,
            "max_primary_core_mitigations": 1,
            "liquidity_sweep_rejection_source_is_valid_htf_source": True,
            "displacement_source_is_valid_htf_source": True,
            "distant_liquidity_is_target_not_zone_expansion": True,
            "m15_or_h1_body_acceptance_invalidates": True,
            "wick_only_liquidity_raid_does_not_invalidate": True,
            "dxy_is_confirmation_not_zone_authority": True,
            "zone_has_two_branches": True,
            "invalidation_is_not_flip_entry": True,
            "htf_location_remains_authority": True,
            "m1_confirmation_cannot_redefine_htf_zone": True,
            "vwap_is_tick_volume_proxy_not_centralized_comex_volume": True,
            "order_flow_disabled_without_centralized_feed": True,
            "risk": "AI never sets lot size",
        },
    }


SYSTEM = """You are a conservative validation layer for an XAUUSD institutional chart-analysis engine.
The deterministic engine owns the observed prices, candidate zones, liquidity map and safety guards. You
MUST NOT invent unseen market data, move a zone to a price that is not in the supplied analysis, or create
an entry merely because price is close to a level.

Validate the published primary map using this hierarchy:
1. D1 gives directional/context bias only; D1 must not create the intraday zone geometry.
2. H4 supplies the parent institutional location. H1 may refine an H4 parent. An H1-only area is fallback
   only when no valid H4/H4>H1 parent exists on that side.
3. SELL supply MUST have structural buy-side liquidity (BSL) physically inside/attached to the compact
   marked area. BUY demand MUST have structural sell-side liquidity (SSL) physically inside/attached.
   A psychological level or generic nearby liquidity by itself is not enough.
4. Accept two HTF source styles: a displacement origin, or a closed-candle liquidity sweep/rejection that
   is followed by decisive displacement away. Strong rejection wicks and stop raids matter when confirmed
   by that follow-through.
5. Freshness is strict. More than one core mitigation rejects a primary zone. Do not approve a repeatedly
   traded internal H1 area as an A/A+ primary zone.
6. Liquidity is a qualification/sweep reference, not permission to stretch a narrow source into a huge
   envelope. Distant liquidity belongs to targets/context.
7. M15/H1 body acceptance beyond the compact zone invalidates the original thesis. A wick-only raid does
   not. DXY is intermarket confirmation only and cannot create or rescue a weak XAU zone.
8. Publish at most one primary SELL and one primary BUY. It is acceptable to publish only one side, or no
   primary zone, when the supplied evidence does not satisfy the rules.
9. M1 is timing only. The HTF zone exists before M1; M1 confirmation cannot redefine the parent location.

Reject validation when any published zone contradicts these rules. Be especially strict about: wrong
liquidity type, liquidity outside the marked area, repeated mitigation, H1 internal noise being promoted
over a valid H4 parent, or a remote context level being presented as today's primary intraday alert.

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
