from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from .config import SETTINGS
from .models import AIDraft, InstitutionalAnalysis, MarketSnapshot


PROMPT_PATH = Path(__file__).resolve().parents[2] / "docs" / "SMC_FRAMEWORK_V3_FULL.md"


def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_hash() -> str:
    return hashlib.sha256(prompt_text().encode()).hexdigest()[:16]


def _compact_bars(snapshot: MarketSnapshot, n: int = 80) -> dict[str, Any]:
    def pack(group):
        result = {}
        for tf, series in group.items():
            result[tf] = {
                "symbol": series.symbol,
                "atr": series.atr,
                "bars": [
                    {"ts": b.ts.isoformat(), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
                    for b in series.bars[-n:]
                ],
            }
        return result
    return {"xau": pack(snapshot.xau), "dxy": pack(snapshot.dxy)}


def _candidate_payload(base: InstitutionalAnalysis) -> list[dict[str, Any]]:
    return [
        {
            "zone_id": z.zone_id,
            "direction": z.direction.value,
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "grade": z.grade.value,
            "source_tf": z.source_tf,
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
            "Analyze only the supplied numeric market data and deterministic candidate zones. "
            "You may select, reject, downgrade, or describe candidate zones, but you MUST NOT invent or modify numeric price levels. "
            "M1 is execution-only and is not supplied here; never claim that an entry trigger has already occurred. "
            "The EA execution order is STRICT: liquidity sweep -> MSS with genuine displacement -> Fibonacci retracement location -> "
            "fresh OB/Breaker Block/FVG confluence -> M1 confirmation -> entry -> structural SL/cloud liquidity TP -> break-even/dynamic trailing. "
            "B+ is watchlist/off by default. Return NO TRADE whenever evidence is insufficient."
        ),
        "snapshot_meta": {
            "generated_at": snapshot.generated_at.isoformat(),
            "session": snapshot.session,
            "spread_points": snapshot.spread_points,
            "timezone": snapshot.timezone,
        },
        "market_data": _compact_bars(snapshot),
        "deterministic_context": {
            "dxy_d1_bias": base.dxy_d1_bias.value,
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
