from __future__ import annotations

from .config import SETTINGS
from .db import connect
from .models import Direction, MarketSnapshot
from .thesis_ownership_policy import active_owner_snapshot

HARD_RELEASE_CONTRACT = "STALE_THESIS_HARD_RELEASE_V6519"
HARD_DISTANCE_M15_ATR = 0.50


def hard_release_stale_thesis(snapshot: MarketSnapshot) -> bool:
    """Release a persisted owner that is unequivocally invalidated while absent from the map.

    This is PAPER/DEMO lifecycle hygiene only. It never creates a new trade and never
    grants opposite-side execution. It removes a stale ownership deadlock after either
    two closed M15 closes beyond the stored outer boundary or one closed M15 close at
    least 0.50 M15 ATR beyond that boundary.
    """
    if not SETTINGS.paper_only:
        return False
    owner = active_owner_snapshot(int(snapshot.sent_at))
    if owner is None or len(snapshot.xau_m15) < 2:
        return False

    direction = str(owner.get("direction") or "")
    sell = direction == Direction.SELL.value
    boundary = float(owner.get("zone_high") if sell else owner.get("zone_low") or 0.0)
    if boundary <= 0:
        return False

    last = snapshot.xau_m15[-1]
    prev = snapshot.xau_m15[-2]
    last_close = float(last.close)
    prev_close = float(prev.close)
    beyond_last = last_close > boundary if sell else last_close < boundary
    beyond_prev = prev_close > boundary if sell else prev_close < boundary
    two_closes = beyond_last and beyond_prev

    m15a = max(float(snapshot.atr_m15 or 0.0), float(snapshot.point or 0.01), 1e-9)
    distance = (last_close - boundary) if sell else (boundary - last_close)
    hard_distance = beyond_last and distance >= HARD_DISTANCE_M15_ATR * m15a
    if not (two_closes or hard_distance):
        return False

    now = int(snapshot.sent_at)
    reason = "STALE_OWNER_TWO_M15_CLOSES_BEYOND_STORED_INVALIDATION" if two_closes else "STALE_OWNER_HARD_M15_DISTANCE_BEYOND_STORED_INVALIDATION"
    with connect() as db:
        db.execute(
            """
            UPDATE zone_reactions
            SET status='INVALIDATED_AFTER_REACTION', invalidated_at=?, last_reason=?, last_seen_at=?
            WHERE reaction_key=? AND invalidated_at=0 AND objective_complete_at=0
            """,
            (now, reason, now, str(owner.get("reaction_key") or "")),
        )
    return True
