from __future__ import annotations

from .engine import structure_bias
from .models import Analysis, Direction, MarketSnapshot


def prompt_snapshot_complete(snapshot: MarketSnapshot) -> bool:
    """History required by the live institutional prompt contract.

    XAU: D1/H4/H1/M15. DXY: D1/H4/H1.  DXY H4 is part of directional
    confirmation; omitting it can incorrectly report NEUTRAL when H4 and H1 are
    already aligned in the active dollar leg.
    """
    return all(
        [
            len(snapshot.xau_d1) >= 80,
            len(snapshot.xau_h4) >= 120,
            len(snapshot.xau_h1) >= 160,
            len(snapshot.xau_m15) >= 160,
            len(snapshot.dxy_d1) >= 60,
            len(snapshot.dxy_h4) >= 80,
            len(snapshot.dxy_h1) >= 100,
        ]
    )


def prompt_dxy_direction(snapshot: MarketSnapshot) -> Direction:
    """DXY confirmation from D1 + H4 + H1 using institutional majority truth.

    A direction requires at least two non-neutral timeframe votes. This keeps DXY
    as confirmation only (it never manufactures or moves an XAU zone), while
    preventing a stale/opposing D1 print from erasing a clearly aligned H4/H1
    active dollar leg. A single directional timeframe is not enough.
    """
    votes = [
        structure_bias(snapshot.dxy_d1),
        structure_bias(snapshot.dxy_h4),
        structure_bias(snapshot.dxy_h1),
    ]
    buys = votes.count(Direction.BUY)
    sells = votes.count(Direction.SELL)
    if buys >= 2 and buys > sells:
        return Direction.BUY
    if sells >= 2 and sells > buys:
        return Direction.SELL
    return Direction.NEUTRAL


def apply_prompt_confirmation_contract(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Align non-zone confirmation/health metadata with the prompt contract.

    This function cannot create, move, rank, or delete XAU zones. It also applies
    the presentation-only pip contract after zone construction.
    """
    dxy = prompt_dxy_direction(snapshot)
    for zone in analysis.zones:
        if dxy == Direction.NEUTRAL:
            zone.dxy_support = "NEUTRAL"
        elif (
            zone.original_direction == Direction.SELL and dxy == Direction.BUY
        ) or (
            zone.original_direction == Direction.BUY and dxy == Direction.SELL
        ):
            zone.dxy_support = "SUPPORT"
        else:
            zone.dxy_support = "CONFLICT"

    complete = prompt_snapshot_complete(snapshot)
    if complete:
        analysis.guards = [g for g in analysis.guards if g != "NO_COMPLETE_HISTORY_CONTEXT"]

    hard_block = (
        not complete
        or "SNAPSHOT_STALE" in analysis.guards
        or any(str(g).startswith("SPREAD_HIGH:") for g in analysis.guards)
    )
    analysis.approved = not hard_block

    policy = dict(analysis.execution_policy or {})
    structure = dict(policy.get("market_structure") or {})
    structure["dxy_d1"] = structure_bias(snapshot.dxy_d1).value
    structure["dxy_h4"] = structure_bias(snapshot.dxy_h4).value
    structure["dxy_h1"] = structure_bias(snapshot.dxy_h1).value
    structure["dxy_consensus"] = dxy.value
    policy["market_structure"] = structure

    inputs = dict(policy.get("market_inputs") or {})
    inputs["prompt_snapshot_complete"] = complete
    inputs["dxy_confirmation_timeframes"] = ["D1", "H4", "H1"]
    inputs["dxy_confirmation_rule"] = "TWO_OF_THREE_NON_NEUTRAL_MAJORITY"
    policy["market_inputs"] = inputs
    analysis.execution_policy = policy

    # Presentation only: 1 XAU pip = 10 broker points. Geometry is unchanged.
    # This also removes duplicate public-map zone_id fields so DataBridge v1.34
    # counts only the canonical entries in analysis.zones.
    from .zone_runtime_policy import apply_pip_display_contract

    apply_pip_display_contract(analysis, snapshot)
    return analysis
