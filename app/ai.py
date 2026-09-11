from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from .config import SETTINGS
from .models import AIDraft, InstitutionalAnalysis, MarketSnapshot


PROMPT_PATH = Path(__file__).resolve().parents[1] / "docs" / "SMC_FRAMEWORK_V3_FULL.md"


def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_hash() -> str:
    return hashlib.sha256(prompt_text().encode()).hexdigest()[:16]


def _compact_bars(snapshot: MarketSnapshot) -> dict[str, Any]:
    """Transmit the complete bounded historical context in a token-efficient shape.

    The bridge/cloud merge caps the bars per timeframe first; this serializer then
    sends all retained bars to the AI rather than truncating every timeframe to 80.
    Format per bar: [unix_utc, open, high, low, close, tick_volume].
    """
    def pack(group):
        result = {}
        for tf, series in group.items():
            result[tf] = {
                "symbol": series.symbol,
                "atr": series.atr,
                "bar_count": len(series.bars),
                "bar_format": ["unix_utc", "open", "high", "low", "close", "tick_volume"],
                "bars": [
                    [int(b.ts.timestamp()), b.open, b.high, b.low, b.close, b.volume]
                    for b in series.bars
                ],
            }
        return result
    return {"xau": pack(snapshot.xau), "dxy": pack(snapshot.dxy)}


def _candidate_payload(base: InstitutionalAnalysis) -> list[dict[str, Any]]:
    return [
        {
            "instrument": z.instrument,
            "zone_id": z.zone_id,
            "direction": z.direction.value,
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "grade": z.grade.value,
            "source_tf": z.source_tf,
            "setup_type": z.setup_type,
            "authority_stack": z.authority_stack,
            "touch_count": z.touch_count,
            "freshness": z.freshness,
            "requires_sweep": z.requires_sweep,
            "min_displacement_atr": z.min_displacement_atr,
            "min_rr": z.min_rr,
            "targets": [z.target1, z.target2, z.target3, z.runner],
            "confluences": z.confluences,
            "provenance": z.provenance,
        }
        for z in base.zones
    ]


def _user_payload(snapshot: MarketSnapshot, base: InstitutionalAnalysis) -> dict[str, Any]:
    return {
        "instruction": (
            "Analyze the complete supplied historical context across XAU D1/H4/H1/M15 and DXY D1/H4/H1, plus deterministic candidate zones. "
            "TRADING ARCHITECTURE IS XAU D1/H4/H1 TOP-DOWN ZONE MAP -> M15 ONE-TIME ZONE QUALIFICATION -> M1 EXECUTION. "
            "XAU D1, H4 and H1 jointly create the institutional supply/demand map. D1 is the macro parent-zone and external dealing-range authority; H4/H1 refine the intraday executable POI. Prefer D1>H4>H1 nesting first, then other observed two-timeframe combinations, then a clean H1 POI. Reject remote or excessively broad swing-style locations. "
            "Build a TWO-SIDED DAY MAP when the supplied evidence allows it: one best XAU BUY zone and one best XAU SELL zone. On a directional day, the zone in the resolved D1/H4/H1 direction is the CONTINUATION zone and the opposite-side institutional zone is the REVERSAL zone. If the HTF stack is neutral, classify them as transition buy/sell. Never invent a missing side just to complete the pair. "
            "M15 may strengthen, weaken, or help qualify an H4/H1 candidate using already-observed structure, displacement, liquidity, mitigation, and premium/discount evidence. M15 MUST NOT create a standalone execution zone. "
            "CRITICAL: M15 usage ENDS when the cloud publishes the zone for qualification/entry purposes. Once a zone is published, do NOT require a later M15 candle close, M15 displacement, M15 engulf, or M15 confirmation before M1 execution. "
            "A separate deterministic M15 ZONE-HEALTH guard may only BLOCK new M1 entries if CLOSED M15 price shows accepted body-close penetration through the distal boundary; this is invalidation monitoring, not an execution confirmation. Wick-only penetration is not invalidation. "
            "Use XAU D1/H4/H1 together to distinguish continuation from reversal/transition while assessing freshness, mitigation, liquidity, and dealing-range location. Use DXY D1/H4/H1 only as intermarket context. DXY IS ANALYSIS-ONLY: never create, recommend, publish, describe, or output a DXY supply/demand zone, DXY entry POI, DXY target, or DXY execution level. All candidate/execution zones in this system are XAUUSD/GOLD zones only. "
            "You may select, reject, downgrade, or describe deterministic candidate zones, but you MUST NOT invent or modify numeric price levels. "
            "M1 is execution-only and is not supplied here; never claim that an entry trigger has already occurred. As soon as price reaches an authorized published zone, M1 alone may validate execution. "
            "The EA execution order after zone publication is STRICT: liquidity sweep -> MSS with genuine displacement -> Fibonacci retracement location -> "
            "fresh OB/Breaker Block/FVG confluence -> M1 confirmation -> entry -> structural SL/cloud liquidity TP -> break-even/dynamic trailing. "
            "B+ is watchlist/off by default. Return NO TRADE whenever evidence is insufficient. "
            "Use supplied high-impact USD news, broker spread and ATR as part of the institutional decision. "
            "Psychological levels are confluence only, never a zone source. Treat volume as BROKER TICK VOLUME only. "
            "In trader_brief use this strict short order: 1 Daily summary; 2 H4 summary; 3 H1 summary; 4 most important XAU institutional zones with supplied prices; 5 best BUY and SELL alert levels, explicitly labelling CONTINUATION versus REVERSAL/TRANSITION when supplied/qualified; 6 M1 entry model, SL/TP logic and explicit zone invalidation. Never force a missing side if no observed candidate qualifies."
        ),
        "snapshot_meta": {
            "generated_at": snapshot.generated_at.isoformat(),
            "session": snapshot.session,
            "snapshot_kind": snapshot.snapshot_kind,
            "snapshot_reason": snapshot.snapshot_reason,
            "bid": snapshot.bid,
            "ask": snapshot.ask,
            "spread_points": snapshot.spread_points,
            "spread_price": snapshot.spread_price,
            "point_size": snapshot.point_size,
            "atr_period": snapshot.atr_period,
            "history_profile": snapshot.history_profile,
            "timezone": snapshot.timezone,
        },
        "market_data": _compact_bars(snapshot),
        "news_context": [
            {
                "event_id": n.event_id, "ts": n.ts.isoformat(), "currency": n.currency,
                "impact": n.impact, "title": n.title, "released": n.released,
                "actual": n.actual, "forecast": n.forecast, "previous": n.previous, "source": n.source,
            }
            for n in snapshot.news
        ],
        "institutional_features": base.analysis_evidence,
        "deterministic_context": {
            "dxy_d1_bias": base.dxy_d1_bias.value,
            "dxy_h4_bias": base.dxy_h4_bias.value,
            "dxy_h1_bias": base.dxy_h1_bias.value,
            "xau_d1_bias": base.xau_d1_bias.value,
            "xau_h4_bias": base.xau_h4_bias.value,
            "xau_h1_bias": base.xau_h1_bias.value,
            "xau_m15_context": base.xau_m15_context.value,
            "overall_bias": base.overall_bias.value,
            "dxy_implication": base.dxy_implication.value,
        },
        "candidate_zones": _candidate_payload(base),
    }


class AIUnavailable(RuntimeError):
    pass


class ProviderUnavailable(RuntimeError):
    pass


def _provider_order() -> list[str]:
    allowed = {"gemini", "groq", "openrouter", "tensormux", "openai"}
    values = [x.strip().lower() for x in SETTINGS.ai_provider_order.split(",") if x.strip()]
    return [x for x in values if x in allowed]


def _extract_chat_text(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderUnavailable("OpenAI-compatible response contained no message content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(item["text"])
        return "".join(parts)
    raise ProviderUnavailable("OpenAI-compatible response content was not text")


async def _openai_responses(snapshot: MarketSnapshot, base: InstitutionalAnalysis) -> tuple[AIDraft, dict[str, str]]:
    if not SETTINGS.openai_api_key:
        raise ProviderUnavailable("OPENAI_API_KEY not configured")
    schema = AIDraft.model_json_schema()
    body = {
        "model": SETTINGS.openai_model,
        "store": False,
        "reasoning": {"effort": SETTINGS.ai_reasoning_effort},
        "instructions": prompt_text(),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps(_user_payload(snapshot, base), separators=(",", ":"))}]}],
        "text": {"format": {"type": "json_schema", "name": "institutional_smc_analysis", "schema": schema, "strict": True}},
    }
    headers = {"Authorization": f"Bearer {SETTINGS.openai_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=SETTINGS.ai_timeout_seconds) as client:
        response = await client.post(SETTINGS.openai_base_url.rstrip("/") + "/responses", headers=headers, json=body)
    if response.status_code >= 400:
        raise ProviderUnavailable(f"OpenAI HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    output_text = data.get("output_text")
    if not output_text:
        chunks = []
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") in {"output_text", "text"} and c.get("text"):
                    chunks.append(c["text"])
        output_text = "".join(chunks)
    if not output_text:
        raise ProviderUnavailable("OpenAI response contained no structured output text")
    return AIDraft.model_validate_json(output_text), {
        "provider": "openai", "response_id": data.get("id", ""), "model": data.get("model", SETTINGS.openai_model), "prompt_hash": prompt_hash()
    }


async def _gemini(snapshot: MarketSnapshot, base: InstitutionalAnalysis) -> tuple[AIDraft, dict[str, str]]:
    if not SETTINGS.gemini_api_key:
        raise ProviderUnavailable("GEMINI_API_KEY not configured")
    schema = AIDraft.model_json_schema()
    combined = prompt_text() + "\n\nMACHINE INPUT:\n" + json.dumps(_user_payload(snapshot, base), separators=(",", ":"))
    body = {
        "contents": [{"role": "user", "parts": [{"text": combined}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "temperature": 0.1,
        },
    }
    url = f"{SETTINGS.gemini_base_url.rstrip('/')}/models/{SETTINGS.gemini_model}:generateContent"
    headers = {"x-goog-api-key": SETTINGS.gemini_api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=SETTINGS.ai_timeout_seconds) as client:
        response = await client.post(url, headers=headers, json=body)
    if response.status_code >= 400:
        raise ProviderUnavailable(f"Gemini HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        output_text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderUnavailable("Gemini response contained no output text") from exc
    return AIDraft.model_validate_json(output_text), {
        "provider": "gemini", "response_id": data.get("responseId", ""), "model": SETTINGS.gemini_model, "prompt_hash": prompt_hash()
    }


async def _openai_compatible(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    snapshot: MarketSnapshot,
    base: InstitutionalAnalysis,
) -> tuple[AIDraft, dict[str, str]]:
    if not base_url or not model:
        raise ProviderUnavailable(f"{provider} base URL/model not configured")
    if provider != "tensormux" and not api_key:
        raise ProviderUnavailable(f"{provider} API key not configured")

    schema = AIDraft.model_json_schema()
    messages = [
        {"role": "system", "content": prompt_text()},
        {"role": "user", "content": json.dumps(_user_payload(snapshot, base), separators=(",", ":"))},
    ]
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # First attempt strict/best-effort JSON-schema output. If a compatible gateway/model
    # rejects json_schema, retry once with JSON-object mode and validate locally with Pydantic.
    formats = [
        {"type": "json_schema", "json_schema": {"name": "institutional_smc_analysis", "strict": True, "schema": schema}},
        {"type": "json_object"},
    ]
    last_error = ""
    for response_format in formats:
        body = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": response_format,
        }
        async with httpx.AsyncClient(timeout=SETTINGS.ai_timeout_seconds) as client:
            response = await client.post(base_url.rstrip("/") + "/chat/completions", headers=headers, json=body)
        if response.status_code >= 400:
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            continue
        data = response.json()
        try:
            draft = AIDraft.model_validate_json(_extract_chat_text(data))
        except Exception as exc:
            last_error = f"schema validation failed: {type(exc).__name__}: {exc}"
            continue
        return draft, {
            "provider": provider,
            "response_id": data.get("id", ""),
            "model": data.get("model", model),
            "prompt_hash": prompt_hash(),
        }
    raise ProviderUnavailable(f"{provider} failed: {last_error}")


async def _groq(snapshot: MarketSnapshot, base: InstitutionalAnalysis):
    return await _openai_compatible("groq", SETTINGS.groq_base_url, SETTINGS.groq_api_key, SETTINGS.groq_model, snapshot, base)


async def _openrouter(snapshot: MarketSnapshot, base: InstitutionalAnalysis):
    return await _openai_compatible("openrouter", SETTINGS.openrouter_base_url, SETTINGS.openrouter_api_key, SETTINGS.openrouter_model, snapshot, base)


async def _tensormux(snapshot: MarketSnapshot, base: InstitutionalAnalysis):
    return await _openai_compatible("tensormux", SETTINGS.tensormux_base_url, SETTINGS.tensormux_api_key, SETTINGS.tensormux_model, snapshot, base)


async def analyze_with_providers(snapshot: MarketSnapshot, base: InstitutionalAnalysis) -> tuple[AIDraft, dict[str, str]]:
    if not SETTINGS.ai_enabled:
        raise AIUnavailable("AI is disabled")

    providers: dict[str, Callable[[MarketSnapshot, InstitutionalAnalysis], Awaitable[tuple[AIDraft, dict[str, str]]]]] = {
        "gemini": _gemini,
        "groq": _groq,
        "openrouter": _openrouter,
        "tensormux": _tensormux,
        "openai": _openai_responses,
    }
    errors: list[str] = []
    for name in _provider_order():
        try:
            draft, meta = await providers[name](snapshot, base)
            meta["attempted_order"] = ",".join(_provider_order())
            return draft, meta
        except ProviderUnavailable as exc:
            errors.append(f"{name}: {exc}")
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    raise AIUnavailable("No AI provider returned a valid schema response. " + " | ".join(errors))


# Backwards-compatible alias for older imports/tests.
analyze_with_openai = analyze_with_providers
