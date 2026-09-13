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
        "zones": [{"zone_id": z.zone_id, "original_direction": z.original_direction.value, "flip_direction": z.flip_direction.value, "setup_type": z.setup_type, "source_tf": z.source_tf, "grade": z.grade.value, "core": [z.core_low, z.core_high], "envelope": [z.zone_low, z.zone_high], "core_method": z.core_method, "location_score": z.location_score, "touch_count": z.touch_count, "confluences": z.confluences, "clear_run": z.clear_run, "dxy_support": z.dxy_support} for z in a.zones],
        "rules": {
            "no_future_leakage": True,
            "zone_has_two_branches": True,
            "invalidation_is_not_flip_entry": True,
            "htf_location_remains_authority": True,
            "alternative_execution_never_bypasses_zone_or_risk": True,
            "m1_execution_models": ["ICT_SNIPER", "ICT_DEEP_REENTRY", "MOMENTUM_PULLBACK", "VWAP_PROXY_RECLAIM", "OPENING_RANGE_RETEST", "ACCEPTED_ZONE_FLIP"],
            "vwap_is_tick_volume_proxy_not_centralized_comex_volume": True,
            "order_flow_disabled_without_centralized_feed": True,
            "risk": "AI never sets lot size",
        },
    }


SYSTEM = """You are a conservative validation layer for an XAUUSD institutional execution engine.
The deterministic engine owns prices, zones, liquidity, invalidation, execution-model eligibility and risk.
You may approve/reject or point out contradictions, but MUST NOT invent unseen market data, move zone
prices, enable a deterministic model the engine disabled, or prescribe lot size.

The pre-analysis core uses only CLOSED D1/H4/H1 evidence already available at the analysis timestamp.
HTF SMC location remains authoritative. The V6.3 regime layer may independently permit M1 ICT sniper,
deep ICT re-entry, momentum pullback, CFD tick-volume VWAP-proxy reclaim, or session opening-range
breakout/retest. These models complement SMC location; none may bypass the live spread/news/snapshot,
thesis-risk, grade or zone-health gates.

Every verified zone has two possibilities: rejection in the original direction, or accepted invalidation
that creates only a FLIP CANDIDATE. Invalidation is never an immediate opposite entry; the M1 engine must
wait for retest + opposite MSS/BOS + displacement + value confirmation. Order-flow imbalance remains
disabled unless a centralized/appropriate feed is explicitly available.

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
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, params=params, json=body); r.raise_for_status(); data = r.json(); text = data["candidates"][0]["content"]["parts"][0]["text"]; obj = _extract_json(text)
            return bool(obj.get("approved")), str(obj.get("summary", "")), list(obj.get("risks", [])), f"GEMINI:{SETTINGS.gemini_model}"
    if SETTINGS.ai_compat_url and SETTINGS.ai_compat_key and SETTINGS.ai_compat_model:
        headers = {"Authorization": f"Bearer {SETTINGS.ai_compat_key}", "Content-Type": "application/json"}
        body = {"model": SETTINGS.ai_compat_model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(_payload(a, s))}], "temperature": 0.1, "response_format": {"type": "json_object"}}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(SETTINGS.ai_compat_url, headers=headers, json=body); r.raise_for_status(); obj = _extract_json(r.json()["choices"][0]["message"]["content"])
            return bool(obj.get("approved")), str(obj.get("summary", "")), list(obj.get("risks", [])), f"COMPAT:{SETTINGS.ai_compat_model}"
    if SETTINGS.require_ai_for_execution:
        return False, "AI required but no provider configured.", ["AI_PROVIDER_UNAVAILABLE"], "NONE"
    return True, "No AI provider configured; deterministic execution allowed by settings.", [], "DETERMINISTIC"
