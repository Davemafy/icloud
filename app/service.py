from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .ai import AIUnavailable, analyze_with_providers
from .config import SETTINGS
from .db import DB
from .engine import build_candidate_analysis, snapshot_fingerprint, snapshot_id
from .events import EVENTS
from .models import InstitutionalAnalysis, MarketSnapshot, ReplayResult
from .news import blackout_state
from .validator import merge_and_validate


async def persist_snapshot(snapshot: MarketSnapshot) -> str:
    sid = snapshot_id(snapshot)
    DB.save_snapshot(
        sid, snapshot.generated_at.isoformat(), snapshot.session, snapshot_fingerprint(snapshot),
        snapshot.model_dump(mode="json"),
    )
    # MT5 can act as the primary economic-calendar provider. Persist every
    # calendar event included in the bridge snapshot so the cloud scheduler,
    # blackout engine and post-news reanalysis all use the same authoritative
    # event store as external providers.
    news_count = 0
    for event in snapshot.news:
        DB.upsert_news(event.model_dump(mode="json"))
        news_count += 1
    DB.audit(
        "snapshot.ingest", snapshot.source,
        f"snapshot_id={sid} session={snapshot.session} news={news_count}"
    )
    await EVENTS.publish("snapshot")
    return sid


def load_latest_snapshot() -> MarketSnapshot | None:
    row = DB.latest_snapshot()
    if not row:
        return None
    return MarketSnapshot.model_validate(json.loads(row["payload"]))


def load_latest_analysis(approved_only: bool = False) -> InstitutionalAnalysis | None:
    row = DB.latest_analysis(approved_only=approved_only)
    if not row:
        return None
    return InstitutionalAnalysis.model_validate(json.loads(row["payload"]))


async def run_production_analysis(snapshot: MarketSnapshot | None = None, reason: str = "manual") -> InstitutionalAnalysis:
    snapshot = snapshot or load_latest_snapshot()
    if snapshot is None:
        raise ValueError("No market snapshot available")

    # Use stored news as the authoritative cloud calendar layer, while retaining MT5-supplied events as evidence.
    blackout, blackout_reason, active_events = blackout_state()
    base = build_candidate_analysis(snapshot)
    base.news_blackout = blackout
    if blackout:
        base.no_trade_reason = f"High-impact USD news blackout: {blackout_reason}"

    draft = None
    meta = None
    ai_error = None
    try:
        draft, meta = await analyze_with_providers(snapshot, base)
    except AIUnavailable as exc:
        ai_error = str(exc)
        DB.audit("analysis.ai_unavailable", "cloud", ai_error)
    except Exception as exc:
        ai_error = f"AI failure: {type(exc).__name__}: {exc}"
        DB.audit("analysis.ai_failure", "cloud", ai_error)

    result = merge_and_validate(snapshot, base, draft, meta)
    if ai_error:
        # Deterministic fallback remains visible for audit/watchlist use, but it cannot execute when AI is required.
        result.ai_used = False
        result.trader_brief = (result.trader_brief + " AI unavailable; deterministic safety fallback used.").strip()
        if SETTINGS.require_ai_for_execution:
            from .models import Direction, ValidationIssue
            result.ea_mode = Direction.NO_TRADE
            result.no_trade_reason = "AI analysis unavailable; execution locked by REQUIRE_AI_FOR_EXECUTION."
            result.validator_issues.append(ValidationIssue(severity="ERROR", code="AI_REQUIRED", message=result.no_trade_reason))
            result.approved = True  # approved NO_TRADE plan is safe to deliver to MT5

    DB.save_analysis(result.model_dump(mode="json"))
    DB.audit("analysis.run", "cloud", f"analysis_id={result.analysis_id} reason={reason} approved={result.approved} mode={result.ea_mode.value} ai={result.ai_used} provider={result.ai_provider or 'none'}")
    await EVENTS.publish("analysis")
    return result


async def replay(snapshot: MarketSnapshot, label: str = "") -> ReplayResult:
    # Replays use deterministic candidate generation + AI when configured, but they never replace the live latest plan.
    base = build_candidate_analysis(snapshot)
    draft = None
    meta = None
    try:
        draft, meta = await analyze_with_providers(snapshot, base)
    except Exception:
        pass
    result = merge_and_validate(snapshot, base, draft, meta)
    replay_id = str(uuid.uuid4())
    rr = ReplayResult(replay_id=replay_id, analysis=result, label=label)
    DB.add_replay(replay_id, label, rr.model_dump(mode="json"))
    return rr
