from __future__ import annotations

from typing import Any

from .config import SETTINGS
from .db import connect
from .models import Analysis, Direction, MarketSnapshot, Zone, ZoneState

THESIS_OWNERSHIP_CONTRACT = "INSTITUTIONAL_THESIS_OWNERSHIP_V6511"
ACTIVE_THESIS_STATUSES = {"INTERACTING", "REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
CONTINUATION_STATUSES = {"REACTION_CONFIRMED", "OBJECTIVE_IN_PROGRESS"}
OWNER_REFRESH_BUFFER_M15_ATR = 0.30
OWNER_M1_HANDOFF_BUFFER_M15_ATR = 0.10
OWNER_MIN_BUFFER_POINTS = 5.0

_AI_RULE = """
13. ACTIVE THESIS OWNERSHIP (PAPER/DEMO): once a published zone has actually interacted and its
    persisted lifecycle is still non-terminal, that thesis owns execution direction until M15 accepted
    invalidation or the deepest planned liquidity objective completes. A newly ranked opposite zone may
    remain visible as context, but it cannot steal M1 authority from the live thesis. If the live thesis is
    REACTION_CONFIRMED or OBJECTIVE_IN_PROGRESS, later mitigation may downgrade the current map display
    to B+ without automatically cancelling the already-confirmed thesis. This is NOT permission to create
    a new zone or chase price: continuation authority is same-direction only, must use the same surviving
    institutional geometry/liquidity, requires price back at the tactical core, and still requires the full
    M1 sweep -> MSS/BOS -> displacement -> dealing-range -> value/PD-array confirmation. If the owner zone
    is absent from the current map, fail closed and allow no opposite execution until the lifecycle becomes
    terminal or a fresh analysis safely republishes the owner.
"""


def install_thesis_ai_contract() -> None:
    """Extend the AI validator with the deterministic thesis-ownership rule."""
    from . import ai

    marker = "13. ACTIVE THESIS OWNERSHIP"
    if marker not in ai.SYSTEM:
        ai.SYSTEM += _AI_RULE


def _active_owner_row(now: int) -> dict[str, Any] | None:
    """Return the first still-live interacted thesis.

    Ownership is intentionally sticky: a later opposite alert cannot replace an
    earlier non-terminal interacted thesis. Lifecycle invalidation/objective
    completion is the release mechanism.
    """
    cutoff = int(now) - 7 * 24 * 3600
    with connect() as db:
        rows = db.execute(
            """
            SELECT reaction_key,latest_zone_id,direction,source_tf,source_ts,status,
                   core_low,core_high,zone_low,zone_high,grade,core_touched_at,
                   reaction_confirmed_at,target1,target2,target3,target1_hit_at,
                   target2_hit_at,target3_hit_at,objective_complete_at,invalidated_at,
                   best_price,mfe_price,last_reason,first_seen_at,last_seen_at
            FROM zone_reactions
            WHERE first_seen_at>=?
              AND core_touched_at>0
              AND invalidated_at=0
              AND objective_complete_at=0
              AND status IN ('INTERACTING','REACTION_CONFIRMED','OBJECTIVE_IN_PROGRESS')
            ORDER BY core_touched_at ASC, first_seen_at ASC
            """,
            (cutoff,),
        ).fetchall()
    if not rows:
        return None
    return dict(rows[0])


def active_owner_snapshot(now: int) -> dict[str, Any] | None:
    """Public read-only owner snapshot for scheduler refresh decisions."""
    if not SETTINGS.paper_only:
        return None
    return _active_owner_row(int(now))


def _owner_core_interaction(
    snapshot: MarketSnapshot,
    atr_fraction: float,
    allowed_statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    owner = active_owner_snapshot(int(snapshot.sent_at))
    if owner is None:
        return None
    if allowed_statuses is not None and str(owner.get("status") or "") not in allowed_statuses:
        return None
    low, high = sorted((float(owner.get("core_low") or 0.0), float(owner.get("core_high") or 0.0)))
    if high <= low:
        return None
    px = float(snapshot.mid)
    if low <= px <= high:
        distance = 0.0
    else:
        distance = low - px if px < low else px - high
    point = max(float(snapshot.point or 0.01), 1e-9)
    m15a = max(float(snapshot.atr_m15 or 0.0), point)
    buffer_price = max(point * OWNER_MIN_BUFFER_POINTS, float(atr_fraction) * m15a)
    return owner if distance <= buffer_price else None


def owner_core_interacting(snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Broad refresh trigger when a live thesis returns near its tactical core.

    This is analysis scheduling only. It deliberately uses the wider 0.30 M15-ATR
    buffer and grants no execution authority by itself.
    """
    return _owner_core_interaction(snapshot, OWNER_REFRESH_BUFFER_M15_ATR)


def owner_m1_handoff_interacting(snapshot: MarketSnapshot) -> dict[str, Any] | None:
    """Strict refresh trigger for an already-confirmed thesis entering M1 handoff range.

    v6.5.10 could latch the wider 0.30-ATR interaction first and then miss the
    later transition into the execution engine's stricter 0.10-ATR core buffer.
    This separate edge trigger exists only for REACTION_CONFIRMED / OBJECTIVE_IN_PROGRESS
    owners. A fresh analysis must still promote M1_READY and pass AI/risk guards.
    """
    return _owner_core_interaction(
        snapshot,
        OWNER_M1_HANDOFF_BUFFER_M15_ATR,
        CONTINUATION_STATUSES,
    )


def _matches_owner(zone: Zone, owner: dict[str, Any]) -> bool:
    if zone.state != ZoneState.ACTIVE:
        return False
    if zone.original_direction.value != str(owner.get("direction", "")):
        return False
    latest_zone_id = str(owner.get("latest_zone_id") or "")
    if latest_zone_id and zone.zone_id == latest_zone_id:
        return True
    source_ts = int(owner.get("source_ts") or 0)
    source_tf = str(owner.get("source_tf") or "")
    return bool(
        source_ts
        and int(zone.source_ts or 0) == source_ts
        and str(zone.source_tf) == source_tf
    )


def apply_thesis_ownership(analysis: Analysis, snapshot: MarketSnapshot) -> Zone | None:
    """Give a live interacted thesis precedence over newly ranked opposite zones.

    This policy does not change zone formation. Both BUY and SELL maps remain
    visible. It only controls which side may receive PAPER M1 execution authority.
    """
    if not SETTINGS.paper_only:
        return None

    owner = _active_owner_row(int(snapshot.sent_at))
    policy = dict(analysis.execution_policy or {})

    if owner is None:
        policy["active_thesis"] = {
            "contract": THESIS_OWNERSHIP_CONTRACT,
            "locked": False,
            "reason": "NO_NONTERMINAL_INTERACTED_THESIS",
        }
        analysis.execution_policy = policy
        return None

    previous_selected = analysis.selected_zone_id
    owner_zone = next((z for z in analysis.zones if _matches_owner(z, owner)), None)
    status = str(owner.get("status") or "INTERACTING")
    direction = str(owner.get("direction") or Direction.NEUTRAL.value)

    meta = {
        "contract": THESIS_OWNERSHIP_CONTRACT,
        "locked": True,
        "direction": direction,
        "status": status,
        "reaction_key": str(owner.get("reaction_key") or ""),
        "source_tf": str(owner.get("source_tf") or ""),
        "source_ts": int(owner.get("source_ts") or 0),
        "owner_zone_id": owner_zone.zone_id if owner_zone is not None else "",
        "owner_zone_present": owner_zone is not None,
        "same_direction_execution_only": True,
        "opposite_execution_blocked": True,
        "d1_context_cannot_override_live_thesis": True,
        "current_grade_downgrade_does_not_flip_thesis": True,
        "continuation_authority": status in CONTINUATION_STATUSES,
        "release_conditions": [
            "M15_ACCEPTED_INVALIDATION",
            "DEEPEST_PLANNED_LIQUIDITY_OBJECTIVE_REACHED",
        ],
        "fresh_m1_confirmation_required": True,
        "no_chase": True,
        "objective_open": True,
        "target1": float(owner.get("target1") or 0.0),
        "target2": float(owner.get("target2") or 0.0),
        "target3": float(owner.get("target3") or 0.0),
        "best_price": float(owner.get("best_price") or 0.0),
        "mfe_price": float(owner.get("mfe_price") or 0.0),
    }
    policy["active_thesis"] = meta
    analysis.execution_policy = policy

    if owner_zone is None:
        # Fail closed. Do not allow an unrelated opposite map zone to become the
        # execution owner while the persisted thesis is still alive.
        analysis.selected_zone_id = ""
        analysis.approved = False
        if "ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP" not in analysis.guards:
            analysis.guards.append("ACTIVE_THESIS_OWNER_NOT_IN_CURRENT_MAP")
        analysis.trader_brief += (
            f" Active thesis lock={direction} ({status}). Its original institutional zone is not "
            "currently republished, so opposite-side execution is blocked until fresh requalification "
            "or lifecycle invalidation/objective completion."
        )
        return None

    analysis.selected_zone_id = owner_zone.zone_id
    owner_zone.notes = [
        f"thesis_owner:{direction}:{status}",
        *[n for n in owner_zone.notes if not str(n).startswith("thesis_owner:")],
    ]

    if previous_selected and previous_selected != owner_zone.zone_id:
        analysis.trader_brief += (
            f" Active thesis lock={direction} ({status}) on {owner_zone.zone_id}; "
            f"newly ranked {previous_selected} remains map/context only and has no M1 authority until "
            "the active thesis is invalidated or completes its deepest liquidity objective."
        )
    else:
        analysis.trader_brief += (
            f" Active thesis lock={direction} ({status}) on {owner_zone.zone_id}; same-direction M1 "
            "confirmation remains mandatory and opposite-side execution is blocked."
        )
    return owner_zone
