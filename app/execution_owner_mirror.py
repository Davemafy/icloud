from __future__ import annotations

from typing import Any

from .db import connect, latest_snapshot, audit
from .models import Heartbeat, Zone, Direction, Grade, ZoneState
from .thesis_ownership_policy import (
    ACTIVE_THESIS_STATUSES,
    active_owner_snapshot,
)
from .execution_ownership_migration import ensure_execution_ownership_schema

OWNER_MIRROR_CONTRACT = "MT5_EXECUTION_OWNER_MIRROR_V1"
OWNER_MIRROR_TTL_SECONDS = 24 * 3600


def owner_plan_text(now: int) -> str:
    """Expose the active owner's frozen lifecycle to MT5 so MT5 can mirror it locally."""
    owner = active_owner_snapshot(now)
    if owner is None:
        return (
            "owner_mirror_contract=" + OWNER_MIRROR_CONTRACT + "\n"
            "owner_mirror_active=0\n"
        )

    fields = {
        "owner_mirror_contract": OWNER_MIRROR_CONTRACT,
        "owner_mirror_active": "1",
        "owner_mirror_saved_at": str(now),
        "owner_mirror_analysis_id": str(owner.get("ownership_analysis_id") or owner.get("latest_analysis_id") or ""),
        "owner_mirror_zone_id": str(owner.get("ownership_zone_id") or owner.get("latest_zone_id") or ""),
        "owner_mirror_direction": str(owner.get("direction") or ""),
        "owner_mirror_source_tf": str(owner.get("source_tf") or ""),
        "owner_mirror_source_ts": str(int(owner.get("source_ts") or 0)),
        "owner_mirror_grade": str(owner.get("grade") or "A"),
        "owner_mirror_status": str(owner.get("status") or "INTERACTING"),
        "owner_mirror_authority": str(owner.get("ownership_authority") or ""),
        "owner_mirror_acquired_at": str(int(owner.get("ownership_acquired_at") or 0)),
        "owner_mirror_core_low": str(float(owner.get("core_low") or 0.0)),
        "owner_mirror_core_high": str(float(owner.get("core_high") or 0.0)),
        "owner_mirror_zone_low": str(float(owner.get("zone_low") or 0.0)),
        "owner_mirror_zone_high": str(float(owner.get("zone_high") or 0.0)),
        "owner_mirror_target1": str(float(owner.get("target1") or 0.0)),
        "owner_mirror_target2": str(float(owner.get("target2") or 0.0)),
        "owner_mirror_target3": str(float(owner.get("target3") or 0.0)),
        "owner_mirror_target1_hit_at": str(int(owner.get("target1_hit_at") or 0)),
        "owner_mirror_target2_hit_at": str(int(owner.get("target2_hit_at") or 0)),
        "owner_mirror_target3_hit_at": str(int(owner.get("target3_hit_at") or 0)),
        "owner_mirror_reaction_confirmed_at": str(int(owner.get("reaction_confirmed_at") or 0)),
        "owner_mirror_best_price": str(float(owner.get("best_price") or 0.0)),
    }
    return "".join(f"{k}={v}\n" for k, v in fields.items())


def _f(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _i(v: Any) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def recover_owner_from_sequence_heartbeat(h: Heartbeat) -> bool:
    """Self-heal cloud ownership from the MT5-local owner mirror after cloud restarts.

    This is PAPER/DEMO continuity only. Recovery never creates a trade and never
    bypasses M15 invalidation or deepest-objective completion.
    """
    if h.ea != "InstitutionalSMC_SequenceEA":
        return False
    d = dict(h.details or {})
    if d.get("owner_mirror_contract") != OWNER_MIRROR_CONTRACT or not bool(d.get("owner_mirror_active")):
        return False
    if not bool(d.get("paper_only", True)):
        return False

    saved_at = _i(d.get("owner_mirror_saved_at"))
    if saved_at <= 0 or h.ts - saved_at > OWNER_MIRROR_TTL_SECONDS:
        return False
    if active_owner_snapshot(h.ts) is not None:
        return False

    direction = str(d.get("owner_mirror_direction") or "")
    zone_id = str(d.get("owner_mirror_zone_id") or "")
    analysis_id = str(d.get("owner_mirror_analysis_id") or "")
    authority = str(d.get("owner_mirror_authority") or "")
    status = str(d.get("owner_mirror_status") or "INTERACTING")
    if direction not in {"BUY", "SELL"} or not zone_id or not analysis_id:
        return False
    if status not in ACTIVE_THESIS_STATUSES:
        return False
    if authority not in {"HTF_CORE_HANDOFF", "HTF_ZONE_SWEEP_HANDOFF", "LIQUIDITY_REVERSAL_HANDOFF"}:
        return False

    core_low, core_high = _f(d.get("owner_mirror_core_low")), _f(d.get("owner_mirror_core_high"))
    zone_low, zone_high = _f(d.get("owner_mirror_zone_low")), _f(d.get("owner_mirror_zone_high"))
    if not (0 < zone_low < zone_high and zone_low <= core_low <= core_high <= zone_high):
        return False

    target1, target2, target3 = (_f(d.get("owner_mirror_target1")), _f(d.get("owner_mirror_target2")), _f(d.get("owner_mirror_target3")))
    deepest = next((x for x in reversed((target1, target2, target3)) if x > 0), 0.0)
    snap = latest_snapshot()
    best = _f(d.get("owner_mirror_best_price"))
    if snap is not None:
        px = float(snap.mid)
        if deepest > 0:
            completed = min(best or px, px) <= deepest if direction == "SELL" else max(best or px, px) >= deepest
            if completed:
                return False
        # Fail closed if current closed M15 acceptance is already beyond frozen invalidation.
        bars = snap.xau_m15
        if bars:
            last = bars[-1]
            if direction == "SELL" and float(last.close) > zone_high:
                return False
            if direction == "BUY" and float(last.close) < zone_low:
                return False

    zone = Zone(
        zone_id=zone_id,
        original_direction=Direction(direction),
        flip_direction=Direction(direction).opposite(),
        setup_type="CONTINUATION",
        source_tf=str(d.get("owner_mirror_source_tf") or "H4>H1"),
        grade=Grade(str(d.get("owner_mirror_grade") or "A")),
        state=ZoneState.ACTIVE,
        core_low=core_low,
        core_high=core_high,
        core_method="PERSISTED_OWNER_MIRROR",
        location_score=0.0,
        zone_low=zone_low,
        zone_high=zone_high,
        touch_count=1,
        independent_confluence_count=2,
        confluences=["PERSISTED_EXECUTION_OWNER", "MT5_OWNER_MIRROR_RECOVERY"],
        source_ts=_i(d.get("owner_mirror_source_ts")),
        invalidation_level=zone_high if direction == "SELL" else zone_low,
        invalidation_rule="M15_ACCEPTED_INVALIDATION",
        original_target1=target1,
        original_target2=target2,
        original_target3=target3,
        notes=["recovered_from_mt5_owner_mirror"],
    )

    ensure_execution_ownership_schema()
    key = f"{direction}|{zone.source_tf}|{zone.source_ts}|MIRROR|{zone_id}"
    acquired = _i(d.get("owner_mirror_acquired_at")) or saved_at
    with connect() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO zone_reactions(
                reaction_key,first_analysis_id,latest_analysis_id,first_zone_id,latest_zone_id,
                direction,source_tf,source_ts,core_low,core_high,zone_low,zone_high,grade,status,
                first_seen_at,last_seen_at,core_touched_at,reaction_confirmed_at,
                target1,target2,target3,runner,target1_hit_at,target2_hit_at,target3_hit_at,
                objective_complete_at,invalidated_at,best_price,mfe_price,last_reason,
                ownership_acquired_at,ownership_authority,ownership_analysis_id,ownership_anchor_price,
                ownership_zone_id,ownership_zone_payload
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                key, analysis_id, analysis_id, zone_id, zone_id,
                direction, zone.source_tf, int(zone.source_ts or 0),
                core_low, core_high, zone_low, zone_high, zone.grade.value, status,
                saved_at, h.ts, saved_at, _i(d.get("owner_mirror_reaction_confirmed_at")),
                target1, target2, target3, 0.0,
                _i(d.get("owner_mirror_target1_hit_at")), _i(d.get("owner_mirror_target2_hit_at")), _i(d.get("owner_mirror_target3_hit_at")),
                0, 0, best, 0.0, "RESTORED_FROM_MT5_OWNER_MIRROR",
                acquired, authority, analysis_id, best or float(snap.mid if snap else 0.0),
                zone_id, zone.model_dump_json(),
            ),
        )
    audit(h.ts, "execution_owner.mirror_restored", f"zone={zone_id} direction={direction} authority={authority}")
    return True
