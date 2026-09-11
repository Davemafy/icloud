from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .ai import AIUnavailable, analyze_with_providers
from .config import SETTINGS
from .db import DB
from .engine import build_candidate_analysis, snapshot_fingerprint, snapshot_id
from .events import EVENTS
from .models import Candle, Direction, Grade, InstitutionalAnalysis, MarketSnapshot, ReplayResult, TimeframeBars, ValidationIssue
from .news import blackout_state, stored_news
from .institutional_features import closed_bars
from .validator import merge_and_validate


def _kind(snapshot: MarketSnapshot) -> str:
    return (snapshot.snapshot_kind or "FULL_HISTORY").upper()


def _merge_cap(tf: str) -> int:
    return {
        "D1": SETTINGS.history_merge_cap_d1,
        "H4": SETTINGS.history_merge_cap_h4,
        "H1": SETTINGS.history_merge_cap_h1,
        "M15": SETTINGS.history_merge_cap_m15,
    }.get(tf.upper(), 700)


def _merge_series(full: TimeframeBars, live: TimeframeBars | None) -> TimeframeBars:
    by_ts = {b.ts: b for b in full.bars}
    if live is not None:
        for bar in live.bars:
            by_ts[bar.ts] = bar
    bars = sorted(by_ts.values(), key=lambda b: b.ts)
    bars = bars[-_merge_cap(full.timeframe):]
    return TimeframeBars(
        symbol=(live.symbol if live is not None else full.symbol),
        timeframe=full.timeframe,
        bars=bars,
        atr=(live.atr if live is not None and live.atr is not None else full.atr),
    )


def _merge_group(full: dict[str, TimeframeBars], live: dict[str, TimeframeBars]) -> dict[str, TimeframeBars]:
    out: dict[str, TimeframeBars] = {}
    for tf, series in full.items():
        out[tf] = _merge_series(series, live.get(tf))
    # Preserve any extra timeframe supplied live, although the institutional
    # engine itself remains restricted to the configured D1/H4/H1/M15 + DXY D1/H4/H1 set.
    for tf, series in live.items():
        if tf not in out:
            out[tf] = series
    return out


def history_requirements() -> dict[str, int]:
    return {
        "XAU:D1": SETTINGS.history_min_xau_d1,
        "XAU:H4": SETTINGS.history_min_xau_h4,
        "XAU:H1": SETTINGS.history_min_xau_h1,
        "XAU:M15": SETTINGS.history_min_xau_m15,
        "DXY:D1": SETTINGS.history_min_dxy_d1,
        "DXY:H4": SETTINGS.history_min_dxy_h4,
        "DXY:H1": SETTINGS.history_min_dxy_h1,
    }


def history_status(snapshot: MarketSnapshot | None) -> dict:
    if snapshot is None:
        return {"ready": False, "reason": "NO_CONTEXT", "counts": {}, "requirements": history_requirements()}
    counts: dict[str, int] = {}
    for tf, s in snapshot.xau.items():
        counts[f"XAU:{tf}"] = len(s.bars)
    for tf, s in snapshot.dxy.items():
        counts[f"DXY:{tf}"] = len(s.bars)

    # Old v2/manual test snapshots did not advertise a history profile. They are
    # kept compatible; protocol-v3 bridge snapshots must satisfy the historical profile.
    enforce = snapshot.schema_version >= 3 and bool(snapshot.history_profile)
    missing = {
        k: {"have": counts.get(k, 0), "need": need}
        for k, need in history_requirements().items()
        if counts.get(k, 0) < need
    }
    return {
        "ready": (not enforce) or not missing,
        "reason": None if ((not enforce) or not missing) else "INSUFFICIENT_HISTORY",
        "counts": counts,
        "requirements": history_requirements(),
        "missing": missing,
        "snapshot_kind": snapshot.snapshot_kind,
        "snapshot_reason": snapshot.snapshot_reason,
    }


async def persist_snapshot(snapshot: MarketSnapshot) -> str:
    sid = snapshot_id(snapshot)
    DB.save_snapshot(
        sid, snapshot.generated_at.isoformat(), snapshot.session, snapshot_fingerprint(snapshot),
        snapshot.model_dump(mode="json"),
    )
    # MT5 is the primary economic-calendar provider. Persist every supplied event
    # so the cloud blackout and post-news scheduler share exactly the same evidence.
    news_count = 0
    for event in snapshot.news:
        DB.upsert_news(event.model_dump(mode="json"))
        news_count += 1
    DB.audit(
        "snapshot.ingest", snapshot.source,
        f"snapshot_id={sid} kind={_kind(snapshot)} reason={snapshot.snapshot_reason} "
        f"session={snapshot.session} news={news_count} spread={snapshot.spread_points:.1f}"
    )
    if _kind(snapshot) == "FULL_HISTORY":
        status = history_status(snapshot)
        DB.audit(
            "history.sync", snapshot.source,
            f"snapshot_id={sid} ready={status['ready']} reason={snapshot.snapshot_reason} counts={status['counts']}"
        )
    await EVENTS.publish("snapshot")
    return sid


def _row_snapshot(row) -> MarketSnapshot | None:
    if not row:
        return None
    return MarketSnapshot.model_validate(json.loads(row["payload"]))


def load_latest_snapshot() -> MarketSnapshot | None:
    return _row_snapshot(DB.latest_snapshot())


def load_latest_full_snapshot() -> MarketSnapshot | None:
    return _row_snapshot(DB.latest_full_snapshot())


def load_analysis_snapshot() -> MarketSnapshot | None:
    """Build the analysis context from the latest heavy history sync + latest live quote/bars.

    The historical snapshot supplies structural depth. The latest snapshot supplies
    current bid/ask/spread, ATR and the newest closed candles. This prevents the
    frequent live bridge heartbeat from replacing the long institutional context.
    """
    latest = load_latest_snapshot()
    full = load_latest_full_snapshot()
    if latest is None:
        return None
    if full is None:
        # Legacy/manual snapshots are still usable. A protocol-v3 LIVE_UPDATE with
        # no full bootstrap is deliberately not analyzed.
        return latest if _kind(latest) != "LIVE_UPDATE" else None

    now = latest.generated_at.astimezone(timezone.utc)
    full_time = full.generated_at.astimezone(timezone.utc)
    full_age_hours = max(0.0, (now - full_time).total_seconds() / 3600.0)
    if full_age_hours > SETTINGS.history_full_max_age_hours and _kind(latest) == "LIVE_UPDATE":
        return None

    if latest.generated_at < full.generated_at:
        latest = full

    xau = _merge_group(full.xau, latest.xau)
    dxy = _merge_group(full.dxy, latest.dxy)
    counts = {f"XAU:{tf}": len(s.bars) for tf, s in xau.items()}
    counts.update({f"DXY:{tf}": len(s.bars) for tf, s in dxy.items()})

    profile_advertised = bool(full.history_profile) or bool(latest.history_profile)
    return MarketSnapshot(
        schema_version=max(full.schema_version, latest.schema_version, 3),
        generated_at=latest.generated_at,
        broker_time=latest.broker_time or full.broker_time,
        session=latest.session,
        timezone=latest.timezone or full.timezone,
        snapshot_kind="ANALYSIS_CONTEXT",
        snapshot_reason=f"{full.snapshot_reason}+{latest.snapshot_reason}",
        xau=xau,
        dxy=dxy,
        bid=latest.bid if latest.bid is not None else full.bid,
        ask=latest.ask if latest.ask is not None else full.ask,
        spread_points=latest.spread_points,
        spread_price=latest.spread_price if latest.spread_price is not None else full.spread_price,
        point_size=latest.point_size,
        atr_period=latest.atr_period,
        history_profile=counts if profile_advertised else {},
        news=latest.news if latest.news else full.news,
        source="MT5_BRIDGE_CONTEXT",
        account_mode=latest.account_mode,
    )


def load_latest_analysis(approved_only: bool = False) -> InstitutionalAnalysis | None:
    row = DB.latest_analysis(approved_only=approved_only)
    if not row:
        return None
    return InstitutionalAnalysis.model_validate(json.loads(row["payload"]))


def load_active_execution_analysis() -> InstitutionalAnalysis | None:
    """Newest plan that may remain active until a successful replacement arrives.

    If REQUIRE_AI_FOR_EXECUTION is enabled, a newer AI-unavailable deterministic
    fallback remains visible in the audit trail but does not evict the previous
    AI-validated plan.
    """
    row = DB.latest_execution_analysis(require_ai=SETTINGS.require_ai_for_execution)
    if not row:
        return None
    return InstitutionalAnalysis.model_validate(json.loads(row["payload"]))


def apply_live_execution_guards(analysis: InstitutionalAnalysis, snapshot: MarketSnapshot | None = None) -> InstitutionalAnalysis:
    """Apply only restrictive live guards to a carried institutional plan.

    Plan age alone never removes zones. The plan remains visible/eligible until a
    newer successful institutional analysis replaces it. Execution may still be
    blocked immediately by M15 zone-health invalidation, stale bridge data, spread,
    current high-impact-news blackout, or a released major-news event that occurred
    after the active plan and therefore still needs post-news revalidation.
    """
    snap = snapshot or load_latest_snapshot()
    out = apply_live_zone_guard(analysis, snap)
    issues = list(out.validator_issues)
    now = datetime.now(timezone.utc)

    if snap is None:
        out.ea_mode = Direction.NO_TRADE
        out.no_trade_reason = "Live MT5 snapshot unavailable; carried zones remain visible but new entries are blocked."
        issues.append(ValidationIssue(severity="ERROR", code="LIVE_SNAPSHOT_MISSING", message=out.no_trade_reason))
    else:
        age = (now - snap.generated_at.astimezone(timezone.utc)).total_seconds()
        if age > SETTINGS.max_snapshot_age_seconds:
            out.ea_mode = Direction.NO_TRADE
            out.no_trade_reason = f"Live MT5 snapshot stale ({age:.0f}s); carried zones remain visible but new entries are blocked."
            issues.append(ValidationIssue(severity="ERROR", code="LIVE_SNAPSHOT_STALE", message=out.no_trade_reason))
        if snap.spread_points > SETTINGS.max_spread_points:
            out.ea_mode = Direction.NO_TRADE
            out.no_trade_reason = f"Live spread too high: {snap.spread_points:.1f} points"
            issues.append(ValidationIssue(severity="ERROR", code="LIVE_SPREAD_GUARD", message=out.no_trade_reason))

    blackout, reason, _ = blackout_state(now)
    out.news_blackout = blackout
    if blackout:
        out.ea_mode = Direction.NO_TRADE
        out.no_trade_reason = f"High-impact USD news blackout/cooldown is active: {reason}"
        issues.append(ValidationIssue(severity="ERROR", code="LIVE_NEWS_BLACKOUT", message=out.no_trade_reason))

    # Never resume a pre-news plan after the release merely because the fixed
    # blackout clock ended. If a released high-impact USD event is newer than the
    # active plan, a successful post-news analysis must replace that plan first.
    pending = [
        e for e in stored_news()
        if e.currency.upper() == "USD" and e.impact.upper() == "HIGH" and e.released
        and e.ts.astimezone(timezone.utc) > analysis.generated_at.astimezone(timezone.utc)
        and e.ts.astimezone(timezone.utc) <= now
    ]
    if pending:
        latest = max(pending, key=lambda e: e.ts)
        out.ea_mode = Direction.NO_TRADE
        out.no_trade_reason = (
            f"Post-news institutional revalidation pending after {latest.title} @ {latest.ts.isoformat()}; "
            "carried zones remain visible but new entries are blocked."
        )
        issues.append(ValidationIssue(severity="ERROR", code="POST_NEWS_REVALIDATION_PENDING", message=out.no_trade_reason))

    out.validator_issues = issues
    return out


def apply_live_zone_guard(analysis: InstitutionalAnalysis, snapshot: MarketSnapshot | None = None) -> InstitutionalAnalysis:
    """Fail closed for NEW entries when CLOSED M15 candles invalidate a published HTF zone.

    D1/H4/H1 remain the institutional zone-creation authority. M15 is consumed once at
    analysis time to qualify the zone, then M1 is the sole execution trigger. This
    live guard does *not* re-confirm entries with M15; it only monitors zone health.

    Intraday invalidation requires acceptance through the distal boundary, not a wick:
      1) one closed M15 candle with the configured share of its REAL BODY beyond the
         boundary and a meaningful body size versus M15 ATR, OR
      2) the configured number of consecutive closed M15 candles beyond the boundary,
         each with a smaller minimum body size versus M15 ATR.

    The guard can only restrict an existing plan. It never creates/replaces a zone,
    never upgrades a grade, and does not alter management of an already-open demo
    position (SL/BE/trailing remain local to the M1 EA). H1/H4 structural retirement
    is handled by the next full institutional/session/news reanalysis.
    """
    snap = snapshot or load_latest_snapshot()
    if snap is None or not analysis.zones:
        return analysis

    out = deepcopy(analysis)
    kept = []
    live_issues = list(out.validator_issues)

    m15_series = snap.xau.get("M15")
    if m15_series is None:
        return analysis
    m15_bars = closed_bars(m15_series, snap.generated_at)
    if not m15_bars:
        return analysis

    # Prefer the bridge ATR because it reflects the exact configured ATR period;
    # fall back to the ATR frozen into the analysis. If neither is available, the
    # body-size floor falls back to broker point-size protection only.
    m15_atr = float(m15_series.atr or analysis.xau_m15_atr or 0.0)
    point_floor = max(float(snap.point_size or 0.0), 1e-9)
    strong_min_body = max(m15_atr * SETTINGS.m15_zone_guard_min_body_atr, point_floor * 5.0)
    two_close_min_body = max(m15_atr * SETTINGS.m15_zone_guard_two_close_min_body_atr, point_floor * 3.0)
    body_beyond_pct = min(1.0, max(0.0, SETTINGS.m15_zone_guard_body_beyond_pct))
    consecutive_needed = max(2, SETTINGS.m15_zone_guard_consecutive_closes)

    # A candle that opened before analysis but CLOSED after publication must count.
    # Using close-time avoids missing the 17:45-18:00 M15 candle when a zone was
    # published at 17:53, for example.
    post = [
        b for b in m15_bars
        if b.ts + timedelta(minutes=15) > analysis.generated_at
    ]

    def distinct_touches(bars, low: float, high: float) -> int:
        count = 0
        in_zone = False
        for b in bars:
            touched = b.low <= high and b.high >= low
            if touched and not in_zone:
                count += 1
            in_zone = touched
        return count

    def body_acceptance(b: Candle, direction: Direction, level: float) -> tuple[bool, float, float, bool]:
        body_low = min(b.open, b.close)
        body_high = max(b.open, b.close)
        body = max(0.0, body_high - body_low)
        if direction == Direction.SELL_ONLY:
            close_beyond = b.close > level
            beyond = max(0.0, body_high - max(level, body_low))
        else:
            close_beyond = b.close < level
            beyond = max(0.0, min(level, body_high) - body_low)
        ratio = (beyond / body) if body > 1e-12 else 0.0
        strong = close_beyond and ratio >= body_beyond_pct and body >= strong_min_body
        return strong, ratio, body, close_beyond

    for z in out.zones:
        level = z.invalidation_level
        if level is None:
            level = z.zone_low if z.direction == Direction.BUY_ONLY else z.zone_high

        invalid = False
        invalid_at = None
        invalid_reason = ""
        consecutive = 0

        for b in post:
            strong, ratio, body, close_beyond = body_acceptance(b, z.direction, level)
            if strong:
                invalid = True
                invalid_at = b.ts + timedelta(minutes=15)
                invalid_reason = (
                    f"one strong M15 acceptance candle: {ratio * 100:.1f}% of real body beyond boundary; "
                    f"body={body:.5f} >= {strong_min_body:.5f} ({SETTINGS.m15_zone_guard_min_body_atr:.2f}x ATR floor)"
                )
                break

            # A wick through the level with a close back inside resets acceptance.
            # For the two-close route, require actual closes beyond the boundary and
            # a non-trivial real body on each candle.
            if close_beyond and body >= two_close_min_body:
                consecutive += 1
                if consecutive >= consecutive_needed:
                    invalid = True
                    invalid_at = b.ts + timedelta(minutes=15)
                    invalid_reason = (
                        f"{consecutive_needed} consecutive M15 closes beyond boundary with "
                        f"body >= {two_close_min_body:.5f} ({SETTINGS.m15_zone_guard_two_close_min_body_atr:.2f}x ATR floor)"
                    )
                    break
            else:
                consecutive = 0

        if invalid:
            live_issues.append(ValidationIssue(
                severity="ERROR", code="LIVE_M15_ZONE_INVALIDATED",
                message=(
                    f"{z.zone_id} intraday-invalidated at {invalid_at.isoformat()} by {invalid_reason}; "
                    f"distal boundary={level:.5f}. Wick-only penetration does not invalidate."
                )
            ))
            continue

        # Intraday freshness is also guarded with distinct M15 engagements after
        # publication. This is a zone-health restriction, never an entry trigger.
        added_touches = distinct_touches(post, z.zone_low, z.zone_high)
        live_touches = z.touch_count + added_touches
        if live_touches >= 3:
            live_issues.append(ValidationIssue(
                severity="WARN", code="LIVE_ZONE_RETIRED",
                message=f"{z.zone_id} reached {live_touches} total mitigations/engagements and is retired for new M1 entries."
            ))
            continue
        if live_touches > z.touch_count:
            z.touch_count = live_touches
            z.freshness = "VALID" if live_touches == 1 else "WEAK"
            if live_touches >= 2 and z.grade in {Grade.A, Grade.A_PLUS}:
                z.grade = Grade.B_PLUS
                live_issues.append(ValidationIssue(
                    severity="WARN", code="LIVE_ZONE_DOWNGRADED",
                    message=f"{z.zone_id} downgraded to B+ after {live_touches} mitigations/engagements since publication."
                ))
        kept.append(z)

    out.zones = kept
    out.validator_issues = live_issues

    # A live guard can only restrict an already-approved plan; it can never turn a
    # previous NO_TRADE decision into permission to trade.
    if analysis.ea_mode != Direction.NO_TRADE:
        executable = [z for z in kept if z.grade in {Grade.A, Grade.A_PLUS} or (SETTINGS.bplus_executable and z.grade == Grade.B_PLUS)]
        dirs = {z.direction for z in executable}
        if dirs == {Direction.BUY_ONLY}:
            out.ea_mode = Direction.BUY_ONLY
        elif dirs == {Direction.SELL_ONLY}:
            out.ea_mode = Direction.SELL_ONLY
        elif Direction.BUY_ONLY in dirs and Direction.SELL_ONLY in dirs:
            out.ea_mode = Direction.BUY_SELL
        else:
            out.ea_mode = Direction.NO_TRADE
            out.no_trade_reason = "Live M15 zone-health guard: no executable zone remains after acceptance/freshness revalidation."
    return out


async def run_production_analysis(snapshot: MarketSnapshot | None = None, reason: str = "manual") -> InstitutionalAnalysis:
    snapshot = snapshot or load_analysis_snapshot()
    if snapshot is None:
        raise ValueError("No complete historical market context available; waiting for FULL_HISTORY sync from MT5")

    hstatus = history_status(snapshot)
    if not hstatus["ready"]:
        raise ValueError(f"Historical context incomplete: {hstatus['missing']}")

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
    DB.audit(
        "analysis.run", "cloud",
        f"analysis_id={result.analysis_id} reason={reason} approved={result.approved} "
        f"mode={result.ea_mode.value} ai={result.ai_used} provider={result.ai_provider or 'none'} "
        f"history={hstatus['counts']} spread={snapshot.spread_points:.1f}"
    )
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
