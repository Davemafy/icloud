from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .execution_ownership_migration import ensure_execution_ownership_schema
from .models import Analysis, Direction, MarketSnapshot, Zone, ZoneState
from .db import connect

REACTION_LIFECYCLE_CONTRACT = "INSTITUTIONAL_ZONE_REACTION_LIFECYCLE_V6555"
TERMINAL = {"OBJECTIVE_COMPLETE", "INVALIDATED", "INVALIDATED_AFTER_REACTION"}


def _reaction_key(zone: Zone) -> str:
    source_ts = int(zone.source_ts or 0)
    if source_ts:
        return f"{zone.original_direction.value}|{zone.source_tf}|{source_ts}"
    return (
        f"{zone.original_direction.value}|{zone.source_tf}|0|"
        f"{float(zone.core_low):.2f}|{float(zone.core_high):.2f}"
    )


def register_analysis_zones(analysis: Analysis) -> None:
    """Persist the institutional identity of every published primary zone.

    Before first core interaction, a repeated analysis may refresh geometry/targets.
    Once the core has interacted, the historical geometry and objective ladder are
    frozen so later re-analysis cannot rewrite what the market actually reacted to.
    Execution ownership is separate and is never acquired merely by registration or
    interaction.
    """
    if not SETTINGS.paper_only:
        return
    ensure_execution_ownership_schema()
    with connect() as db:
        for zone in analysis.zones:
            if zone.state != ZoneState.ACTIVE:
                continue
            key = _reaction_key(zone)
            db.execute(
                """
                INSERT OR IGNORE INTO zone_reactions(
                    reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                    direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                    first_seen_at,last_seen_at,target1,target2,target3,runner,best_price,mfe_price,last_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    key,analysis.analysis_id,analysis.analysis_id,zone.zone_id,zone.zone_id,
                    zone.original_direction.value,zone.source_tf,int(zone.source_ts or 0),
                    float(zone.core_low),float(zone.core_high),float(zone.zone_low),float(zone.zone_high),
                    zone.grade.value,"ARMED",int(analysis.generated_at),int(analysis.generated_at),
                    float(zone.original_target1 or 0),float(zone.original_target2 or 0),
                    float(zone.original_target3 or 0),float(zone.original_runner or 0),
                    float(zone.core_low if zone.original_direction == Direction.SELL else zone.core_high),
                    0.0,"ZONE_PUBLISHED",
                ),
            )
            db.execute(
                """
                UPDATE zone_reactions SET
                    latest_analysis_id=?,
                    latest_zone_id=CASE WHEN ownership_acquired_at=0 THEN ? ELSE latest_zone_id END,
                    last_seen_at=?,
                    grade=CASE WHEN ownership_acquired_at=0 THEN ? ELSE grade END,
                    core_low=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE core_low END,
                    core_high=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE core_high END,
                    zone_low=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE zone_low END,
                    zone_high=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE zone_high END,
                    target1=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE target1 END,
                    target2=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE target2 END,
                    target3=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE target3 END,
                    runner=CASE WHEN core_touched_at=0 AND ownership_acquired_at=0 THEN ? ELSE runner END
                WHERE reaction_key=?
                """,
                (
                    analysis.analysis_id,zone.zone_id,int(analysis.generated_at),zone.grade.value,
                    float(zone.core_low),float(zone.core_high),float(zone.zone_low),float(zone.zone_high),
                    float(zone.original_target1 or 0),float(zone.original_target2 or 0),
                    float(zone.original_target3 or 0),float(zone.original_runner or 0),key,
                ),
            )


def _body(bar) -> float:
    return abs(float(bar.close) - float(bar.open))


def _accepted_invalidation(row: Any, snapshot: MarketSnapshot) -> bool:
    bars = snapshot.xau_m15
    if len(bars) < 2:
        return False
    a = float(snapshot.atr_m15 or 0.0)
    if a <= 0:
        return False
    sell = str(row["direction"]) == Direction.SELL.value
    boundary = float(row["zone_high"] if sell else row["zone_low"])

    def frac(bar) -> float:
        body = max(_body(bar), 1e-9)
        top = max(float(bar.open), float(bar.close))
        bottom = min(float(bar.open), float(bar.close))
        beyond = max(0.0, top - max(bottom, boundary)) if sell else max(0.0, min(top, boundary) - bottom)
        return beyond / body

    last = bars[-1]
    beyond = float(last.close) > boundary if sell else float(last.close) < boundary
    single = (
        beyond
        and frac(last) >= SETTINGS.m15_single_accept_body_fraction
        and _body(last) >= SETTINGS.m15_single_accept_body_atr * a
    )
    x, y = bars[-2], bars[-1]
    two_closes = (
        (float(x.close) > boundary and float(y.close) > boundary)
        if sell else
        (float(x.close) < boundary and float(y.close) < boundary)
    )
    two = (
        two_closes
        and _body(x) >= SETTINGS.m15_double_accept_body_atr * a
        and _body(y) >= SETTINGS.m15_double_accept_body_atr * a
    )
    return bool(single or two)


def _intersects_core(row: Any, snapshot: MarketSnapshot) -> bool:
    low = float(row["core_low"])
    high = float(row["core_high"])
    mid = float(snapshot.mid)
    if low <= mid <= high:
        return True
    if not snapshot.xau_m15:
        return False
    bar = snapshot.xau_m15[-1]
    return float(bar.high) >= low and float(bar.low) <= high


def _favourable_extreme(row: Any, snapshot: MarketSnapshot) -> float:
    sell = str(row["direction"]) == Direction.SELL.value
    values = [float(snapshot.mid)]
    if snapshot.xau_m15:
        last = snapshot.xau_m15[-1]
        values.append(float(last.low if sell else last.high))
    old = float(row["best_price"] or 0.0)
    if old:
        values.append(old)
    return min(values) if sell else max(values)


def _mfe(row: Any, best: float) -> float:
    authority = str(row["ownership_authority"] or "") if "ownership_authority" in row.keys() else ""
    anchor = float(row["ownership_anchor_price"] or 0.0) if "ownership_anchor_price" in row.keys() else 0.0
    if authority not in {"LIQUIDITY_REVERSAL_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF"} or anchor <= 0:
        anchor = float(row["core_low"] if str(row["direction"]) == Direction.SELL.value else row["core_high"])
    if str(row["direction"]) == Direction.SELL.value:
        return max(0.0, anchor - best)
    return max(0.0, best - anchor)


def _crossed(direction: str, best: float, target: float) -> bool:
    if target <= 0:
        return False
    return best <= target if direction == Direction.SELL.value else best >= target


def _objective_anchor(row: Any) -> float:
    """Return the price from which objective progress is allowed to begin."""
    acquired_at = int(row["ownership_acquired_at"] or 0) if "ownership_acquired_at" in row.keys() else 0
    ownership_anchor = float(row["ownership_anchor_price"] or 0.0) if "ownership_anchor_price" in row.keys() else 0.0
    if acquired_at > 0 and ownership_anchor > 0:
        return ownership_anchor
    return float(row["core_low"] if str(row["direction"]) == Direction.SELL.value else row["core_high"])


def _target_live_from_anchor(direction: str, target: float, anchor: float) -> bool:
    """A target already behind the activation anchor was never completed by this thesis."""
    if target <= 0 or anchor <= 0:
        return False
    return target < anchor if direction == Direction.SELL.value else target > anchor


def update_zone_reactions(snapshot: MarketSnapshot) -> None:
    """Advance persisted zone lifecycle from live/closed market evidence.

    Historical interaction remains independent from execution ownership. A normal
    WATCH interaction may be recorded and even confirm a reaction without ever
    gaining the right to block another direction. Liquidity-reversal and proven
    outer-zone sweep handoffs can own execution without touching the tactical core,
    so their explicitly acquired/reaction-confirmed lifecycle is still advanced
    toward objectives from the actual ownership anchor.
    """
    if not SETTINGS.paper_only:
        return
    ensure_execution_ownership_schema()
    now = int(snapshot.sent_at)
    cutoff = now - 7 * 24 * 3600
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM zone_reactions WHERE first_seen_at>=? ORDER BY first_seen_at DESC",
            (cutoff,),
        ).fetchall()
        for row in rows:
            status = str(row["status"] or "ARMED")
            if status in TERMINAL:
                continue

            if _accepted_invalidation(row, snapshot):
                after_reaction = bool(row["reaction_confirmed_at"])
                db.execute(
                    "UPDATE zone_reactions SET status=?,invalidated_at=?,last_reason=?,last_seen_at=? WHERE reaction_key=?",
                    (
                        "INVALIDATED_AFTER_REACTION" if after_reaction else "INVALIDATED",
                        now,
                        "M15_ACCEPTED_INVALIDATION_AFTER_REACTION" if after_reaction else "M15_ACCEPTED_INVALIDATION",
                        now,row["reaction_key"],
                    ),
                )
                continue

            touched_at = int(row["core_touched_at"] or 0)
            reaction_confirmed_at = int(row["reaction_confirmed_at"] or 0)
            ownership_acquired_at = int(row["ownership_acquired_at"] or 0)
            if not touched_at and _intersects_core(row, snapshot):
                touched_at = now
                status = "INTERACTING" if not reaction_confirmed_at else status
                db.execute(
                    "UPDATE zone_reactions SET status=?,core_touched_at=?,last_reason=?,last_seen_at=? WHERE reaction_key=?",
                    (status,now,"TACTICAL_CORE_INTERACTION",now,row["reaction_key"]),
                )

            # Normal zone-reaction research starts after core touch. Explicit
            # liquidity-reversal or zone-sweep handoffs are already M15-confirmed
            # and may advance from their ownership anchor without touching the core.
            if not touched_at and not (ownership_acquired_at and reaction_confirmed_at):
                continue

            best = _favourable_extreme(row, snapshot)
            mfe = _mfe(row, best)
            m15_atr = max(float(snapshot.atr_m15 or 0.0), float(snapshot.point or 0.01))
            confirmation_distance = max(0.50 * m15_atr, float(snapshot.point or 0.01) * 100.0)
            if not reaction_confirmed_at and touched_at and mfe >= confirmation_distance:
                reaction_confirmed_at = now
                status = "REACTION_CONFIRMED"

            direction = str(row["direction"])
            target1 = float(row["target1"] or 0.0)
            target2 = float(row["target2"] or 0.0)
            target3 = float(row["target3"] or 0.0)
            t1_hit = int(row["target1_hit_at"] or 0)
            t2_hit = int(row["target2_hit_at"] or 0)
            t3_hit = int(row["target3_hit_at"] or 0)
            objective_anchor = _objective_anchor(row)
            t1_live = _target_live_from_anchor(direction, target1, objective_anchor)
            t2_live = _target_live_from_anchor(direction, target2, objective_anchor)
            t3_live = _target_live_from_anchor(direction, target3, objective_anchor)
            if not t1_hit and t1_live and _crossed(direction, best, target1):
                t1_hit = now
            if not t2_hit and t2_live and _crossed(direction, best, target2):
                t2_hit = now
            if not t3_hit and t3_live and _crossed(direction, best, target3):
                t3_hit = now

            valid_targets = [
                target for target, live in ((target1,t1_live),(target2,t2_live),(target3,t3_live))
                if target > 0 and live
            ]
            deepest_hit = False
            if valid_targets:
                deepest = valid_targets[-1]
                deepest_hit = _crossed(direction, best, deepest)

            if deepest_hit and reaction_confirmed_at:
                status = "OBJECTIVE_COMPLETE"
                reason = "DEEPEST_PLANNED_LIQUIDITY_OBJECTIVE_REACHED"
                completed_at = now
            elif (t1_hit or t2_hit or t3_hit) and reaction_confirmed_at:
                status = "OBJECTIVE_IN_PROGRESS"
                reason = "LIQUIDITY_OBJECTIVE_PROGRESS"
                completed_at = int(row["objective_complete_at"] or 0)
            elif reaction_confirmed_at:
                status = "REACTION_CONFIRMED"
                if str(row["ownership_authority"] or "") == "LIQUIDITY_REVERSAL_HANDOFF" and not touched_at:
                    reason = "LIQUIDITY_REVERSAL_HANDOFF_REACTION_CONFIRMED"
                else:
                    reason = "INSTITUTIONAL_REACTION_CONFIRMED"
                completed_at = int(row["objective_complete_at"] or 0)
            else:
                reason = "TACTICAL_CORE_INTERACTION"
                completed_at = int(row["objective_complete_at"] or 0)

            db.execute(
                """
                UPDATE zone_reactions SET
                    status=?,reaction_confirmed_at=?,target1_hit_at=?,target2_hit_at=?,target3_hit_at=?,
                    objective_complete_at=?,best_price=?,mfe_price=?,last_reason=?,last_seen_at=?
                WHERE reaction_key=?
                """,
                (
                    status,reaction_confirmed_at,t1_hit,t2_hit,t3_hit,completed_at,
                    best,mfe,reason,now,row["reaction_key"],
                ),
            )


def lifecycle_summary(limit: int = 20) -> list[dict[str, Any]]:
    ensure_execution_ownership_schema()
    limit = max(1, min(int(limit), 100))
    with connect() as db:
        rows = db.execute(
            """
            SELECT reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                   direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                   first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                   target1,target2,target3,target1_hit_at,target2_hit_at,target3_hit_at,
                   objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
                   ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price
            FROM zone_reactions ORDER BY COALESCE(ownership_acquired_at,reaction_confirmed_at,core_touched_at,first_seen_at) DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def attach_lifecycle(analysis: Analysis) -> Analysis:
    policy = dict(analysis.execution_policy or {})
    records = lifecycle_summary(20)
    policy["zone_reaction_lifecycle"] = {
        "contract": REACTION_LIFECYCLE_CONTRACT,
        "persistence": "SURVIVES_PRIMARY_RESELECTION_AND_ZONE_MAP_REMOVAL",
        "historical_geometry_and_targets_freeze_after_core_interaction": True,
        "zone_validity_independent_of_target_map": True,
        "interaction_is_not_execution_ownership": True,
        "execution_ownership_requires_explicit_handoff": True,
        "reaction_confirmation": "CORE_INTERACTION_THEN_FAVOURABLE_MOVE_AT_LEAST_MAX_0_5_M15_ATR_OR_10_PIPS_OR_EXPLICIT_LIQUIDITY_REVERSAL_HANDOFF",
        "terminal_states": sorted(TERMINAL),
        "records": records,
    }
    analysis.execution_policy = policy
    return analysis
