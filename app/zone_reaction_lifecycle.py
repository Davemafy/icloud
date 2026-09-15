from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .models import Analysis, Direction, MarketSnapshot, Zone, ZoneState
from .db import connect

REACTION_LIFECYCLE_CONTRACT = "INSTITUTIONAL_ZONE_REACTION_LIFECYCLE_V658"
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

    Re-selection in a later analysis updates the latest reference but never erases
    an already-recorded reaction lifecycle.
    """
    if not SETTINGS.paper_only:
        return
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
                    latest_analysis_id=?,latest_zone_id=?,last_seen_at=?,grade=?,
                    core_low=?,core_high=?,zone_low=?,zone_high=?,
                    target1=?,target2=?,target3=?,runner=?
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
    if str(row["direction"]) == Direction.SELL.value:
        return max(0.0, float(row["core_low"]) - best)
    return max(0.0, best - float(row["core_high"]))


def _crossed(direction: str, best: float, target: float) -> bool:
    if target <= 0:
        return False
    return best <= target if direction == Direction.SELL.value else best >= target


def update_zone_reactions(snapshot: MarketSnapshot) -> None:
    """Advance persisted zone lifecycle from live/closed market evidence.

    A zone can disappear from the current alert map without losing the historical
    fact that it interacted and produced an institutional reaction.
    """
    if not SETTINGS.paper_only:
        return
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
            if not touched_at and _intersects_core(row, snapshot):
                touched_at = now
                status = "INTERACTING"
                db.execute(
                    "UPDATE zone_reactions SET status=?,core_touched_at=?,last_reason=?,last_seen_at=? WHERE reaction_key=?",
                    (status,now,"TACTICAL_CORE_INTERACTION",now,row["reaction_key"]),
                )

            if not touched_at:
                continue

            best = _favourable_extreme(row, snapshot)
            mfe = _mfe(row, best)
            m15_atr = max(float(snapshot.atr_m15 or 0.0), float(snapshot.point or 0.01))
            confirmation_distance = max(0.50 * m15_atr, float(snapshot.point or 0.01) * 100.0)
            reaction_confirmed_at = int(row["reaction_confirmed_at"] or 0)
            if not reaction_confirmed_at and mfe >= confirmation_distance:
                reaction_confirmed_at = now
                status = "REACTION_CONFIRMED"

            direction = str(row["direction"])
            target1 = float(row["target1"] or 0.0)
            target2 = float(row["target2"] or 0.0)
            target3 = float(row["target3"] or 0.0)
            t1_hit = int(row["target1_hit_at"] or 0)
            t2_hit = int(row["target2_hit_at"] or 0)
            t3_hit = int(row["target3_hit_at"] or 0)
            if not t1_hit and _crossed(direction, best, target1):
                t1_hit = now
            if not t2_hit and _crossed(direction, best, target2):
                t2_hit = now
            if not t3_hit and _crossed(direction, best, target3):
                t3_hit = now

            valid_targets = [x for x in (target1,target2,target3) if x > 0]
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
    limit = max(1, min(int(limit), 100))
    with connect() as db:
        rows = db.execute(
            """
            SELECT reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                   direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                   first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                   target1,target2,target3,target1_hit_at,target2_hit_at,target3_hit_at,
                   objective_complete_at,invalidated_at,best_price,mfe_price,last_reason
            FROM zone_reactions ORDER BY COALESCE(reaction_confirmed_at,core_touched_at,first_seen_at) DESC LIMIT ?
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
        "zone_validity_independent_of_target_map": True,
        "reaction_confirmation": "CORE_INTERACTION_THEN_FAVOURABLE_MOVE_AT_LEAST_MAX_0_5_M15_ATR_OR_10_PIPS",
        "terminal_states": sorted(TERMINAL),
        "records": records,
    }
    analysis.execution_policy = policy
    return analysis
