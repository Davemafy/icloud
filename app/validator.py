from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Iterable

from .config import SETTINGS
from .models import AIDraft, Direction, DxyImplication, Grade, InstitutionalAnalysis, MarketSnapshot, ValidationIssue


def _issue(severity: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, message=message)


def _price_bounds(snapshot: MarketSnapshot) -> tuple[float, float]:
    vals = []
    for group in (snapshot.xau, snapshot.dxy):
        for tf in group.values():
            for b in tf.bars:
                vals.extend([b.low, b.high])
    return min(vals), max(vals)


def _xau_bounds(snapshot: MarketSnapshot) -> tuple[float, float]:
    vals = []
    for tf in snapshot.xau.values():
        for b in tf.bars:
            vals.extend([b.low, b.high])
    return min(vals), max(vals)


def _clear_run_pips(zone, counter_trend: bool) -> float:
    target = zone.target1
    if target is None:
        return 0.0
    entry_ref = (zone.zone_low + zone.zone_high) / 2
    run = abs(target - entry_ref)
    return run / SETTINGS.xau_pip_size


def merge_and_validate(snapshot: MarketSnapshot, base: InstitutionalAnalysis, draft: AIDraft | None, ai_meta: dict | None = None) -> InstitutionalAnalysis:
    out = deepcopy(base)
    issues: list[ValidationIssue] = []
    baseline_implication = base.dxy_implication
    baseline_grade = {z.zone_id: z.grade for z in base.zones}

    if draft is not None:
        out.ai_used = True
        out.ai_provider = (ai_meta or {}).get("provider")
        out.ai_model = (ai_meta or {}).get("model")
        out.ai_response_id = (ai_meta or {}).get("response_id")
        out.dxy_d1_bias = draft.dxy_d1_bias
        out.dxy_h4_bias = draft.dxy_h4_bias
        out.dxy_h1_bias = draft.dxy_h1_bias
        out.xau_d1_bias = draft.xau_d1_bias
        out.xau_h4_bias = draft.xau_h4_bias
        out.xau_h1_bias = draft.xau_h1_bias
        out.xau_m15_context = draft.xau_m15_context
        out.overall_bias = draft.overall_bias
        if draft.dxy_implication != baseline_implication:
            issues.append(_issue("WARN", "AI_DXY_IMPLICATION_OVERRIDDEN", f"AI DXY implication {draft.dxy_implication.value} differed from deterministic {baseline_implication.value}; deterministic value retained."))
        out.dxy_implication = baseline_implication
        out.primary_liquidity = draft.primary_liquidity
        out.expected_sequence = draft.expected_sequence
        out.retail_trap = draft.retail_trap
        out.overall_invalidation = draft.overall_invalidation
        out.trader_brief = draft.trader_brief
        if draft.no_trade:
            out.ea_mode = Direction.NO_TRADE
            out.no_trade_reason = draft.no_trade_reason or "AI classified NO TRADE"

        by_id = {z.zone_id: z for z in out.zones}
        used = []
        for d in draft.zone_decisions:
            z = by_id.get(d.candidate_zone_id)
            if not z:
                issues.append(_issue("ERROR", "AI_UNKNOWN_ZONE", f"AI referenced unknown candidate zone {d.candidate_zone_id}"))
                continue
            if not d.use_zone:
                continue
            if d.direction != z.direction:
                issues.append(_issue("ERROR", "AI_DIRECTION_MUTATION", f"AI changed deterministic direction for {z.zone_id}"))
                continue
            rank = {Grade.REJECT: 0, Grade.B_PLUS: 1, Grade.A: 2, Grade.A_PLUS: 3}
            base_grade = baseline_grade.get(z.zone_id, z.grade)
            if rank[d.grade] > rank[base_grade]:
                issues.append(_issue("WARN", "AI_UPGRADE_BLOCKED", f"AI attempted to upgrade {z.zone_id} from {base_grade.value} to {d.grade.value}; deterministic ceiling retained."))
                z.grade = base_grade
            else:
                z.grade = d.grade
            z.min_displacement_atr = max(z.min_displacement_atr, d.min_displacement_atr)
            z.notes.append("AI: " + d.institutional_interpretation[:500])
            z.notes.append("Execution: " + d.execution_condition[:500])
            if d.downgrade_reason:
                z.notes.append("Downgrade: " + d.downgrade_reason[:300])
            used.append(z)
        out.zones = used

    # Anti-hallucination: AI can only select deterministic zones, then all numeric levels must stay within XAU observed range.
    xlo, xhi = _xau_bounds(snapshot)
    validated_zones = []
    for z in out.zones:
        instrument = (z.instrument or "").upper()
        if "XAU" not in instrument and "GOLD" not in instrument:
            issues.append(_issue("ERROR", "NON_XAU_ZONE_REJECTED", f"Zone {z.zone_id} instrument={z.instrument!r} rejected; DXY is analysis-only and execution zones must be XAU/GOLD."))
            continue
        levels = [z.zone_low, z.zone_high] + [x for x in [z.target1, z.target2, z.target3, z.runner] if x is not None]
        if any(p < xlo or p > xhi for p in levels):
            issues.append(_issue("ERROR", "LEVEL_OUTSIDE_OBSERVED_XAU", f"Zone {z.zone_id} contains a level outside supplied XAU price history."))
            continue
        if z.touch_count >= 3 or z.freshness == "RETIRED":
            issues.append(_issue("WARN", "ZONE_RETIRED", f"Zone {z.zone_id} has >=3 touches and is retired."))
            continue
        if z.grade == Grade.A_PLUS and len(z.confluences) < 3:
            z.grade = Grade.A
            issues.append(_issue("WARN", "A_PLUS_DOWNGRADED", f"Zone {z.zone_id} lacked enough independent confluences for A+."))
        if out.dxy_implication == DxyImplication.CONFLICTS:
            if z.grade in {Grade.A_PLUS, Grade.A}:
                z.grade = Grade.B_PLUS
                issues.append(_issue("WARN", "DXY_CONFLICT_DOWNGRADE", f"Zone {z.zone_id} downgraded to B+ because DXY conflicts."))
            z.min_displacement_atr = max(1.2, z.min_displacement_atr)

        counter = (out.overall_bias.value == "BEARISH" and z.direction == Direction.BUY_ONLY) or (out.overall_bias.value == "BULLISH" and z.direction == Direction.SELL_ONLY)
        required_pips = SETTINGS.min_clear_run_counter_trend_pips if counter else SETTINGS.min_clear_run_with_trend_pips
        if _clear_run_pips(z, counter) < required_pips:
            issues.append(_issue("WARN", "INSUFFICIENT_CLEAR_RUN", f"Zone {z.zone_id} does not meet configured clear-run minimum."))
            z.grade = Grade.B_PLUS
        validated_zones.append(z)
    out.zones = validated_zones

    now = datetime.now(timezone.utc)
    snapshot_time = snapshot.generated_at.astimezone(timezone.utc)
    if (now - snapshot_time).total_seconds() > SETTINGS.max_snapshot_age_seconds:
        out.ea_mode = Direction.NO_TRADE
        out.no_trade_reason = "Snapshot is stale."
        issues.append(_issue("ERROR", "STALE_SNAPSHOT", "Latest market snapshot is older than configured freshness limit."))

    if snapshot.spread_points > SETTINGS.max_spread_points:
        out.ea_mode = Direction.NO_TRADE
        out.no_trade_reason = f"Spread too high: {snapshot.spread_points:.1f} points"
        issues.append(_issue("ERROR", "SPREAD_GUARD", out.no_trade_reason))

    if out.news_blackout:
        out.ea_mode = Direction.NO_TRADE
        out.no_trade_reason = "High-impact USD news blackout/cooldown is active."
        issues.append(_issue("ERROR", "NEWS_BLACKOUT", out.no_trade_reason))

    executable = [z for z in out.zones if z.grade in {Grade.A_PLUS, Grade.A} or (SETTINGS.bplus_executable and z.grade == Grade.B_PLUS)]
    if out.ea_mode != Direction.NO_TRADE:
        dirs = {z.direction for z in executable}
        if dirs == {Direction.BUY_ONLY}:
            out.ea_mode = Direction.BUY_ONLY
        elif dirs == {Direction.SELL_ONLY}:
            out.ea_mode = Direction.SELL_ONLY
        elif Direction.BUY_ONLY in dirs and Direction.SELL_ONLY in dirs:
            out.ea_mode = Direction.BUY_SELL
        else:
            out.ea_mode = Direction.NO_TRADE
            out.no_trade_reason = "No executable A/A+ zones after deterministic validation."

    out.validator_issues = issues
    out.approved = not any(x.severity == "ERROR" for x in issues)
    if out.ea_mode == Direction.NO_TRADE:
        # NO_TRADE plans can still be approved for delivery to the EA.
        out.approved = True
    return out
