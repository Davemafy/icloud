import asyncio

import app.ai as ai
from app.engine import build_candidate_analysis
from app.models import AIDraft, AIZoneDecision, Grade
from tests.helpers import make_snapshot


def make_draft(base):
    return AIDraft(
        dxy_d1_bias=base.dxy_d1_bias,
        dxy_h4_bias=base.dxy_h4_bias,
        dxy_h1_bias=base.dxy_h1_bias,
        xau_d1_bias=base.xau_d1_bias,
        xau_h4_bias=base.xau_h4_bias,
        xau_h1_bias=base.xau_h1_bias,
        xau_m15_context=base.xau_m15_context,
        overall_bias=base.overall_bias,
        dxy_implication=base.dxy_implication,
        primary_liquidity=base.primary_liquidity,
        no_trade=True,
        no_trade_reason="test-safe",
        zone_decisions=[],
        expected_sequence="sweep -> MSS/displacement -> Fibonacci -> OB/BB/FVG -> M1 confirmation -> entry",
        retail_trap="none",
        overall_invalidation="test",
        trader_brief="test",
    )


def test_provider_failover_uses_next_valid(monkeypatch):
    snap = make_snapshot()
    base = build_candidate_analysis(snap)

    async def fail(*args, **kwargs):
        raise ai.ProviderUnavailable("simulated failure")

    async def success(*args, **kwargs):
        return make_draft(base), {"provider": "groq", "model": "test-model", "response_id": "r1"}

    monkeypatch.setattr(ai, "_gemini", fail)
    monkeypatch.setattr(ai, "_groq", success)
    draft, meta = asyncio.run(ai.analyze_with_providers(snap, base))
    assert draft.no_trade is True
    assert meta["provider"] == "groq"
