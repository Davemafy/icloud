from __future__ import annotations

from .engine import structure_bias
from .models import Analysis, Direction, MarketSnapshot


def prompt_snapshot_complete(snapshot: MarketSnapshot) -> bool:
    """History required by the 2026-09-14 prompt contract only.

    XAU: D1/H4/H1/M15. DXY: D1/H1. DXY H4 is deliberately not required.
    """
    return all(
        [
            len(snapshot.xau_d1) >= 80,
            len(snapshot.xau_h4) >= 120,
            len(snapshot.xau_h1) >= 160,
            len(snapshot.xau_m15) >= 160,
            len(snapshot.dxy_d1) >= 60,
            len(snapshot.dxy_h1) >= 100,
        ]
    )


def prompt_dxy_direction(snapshot: MarketSnapshot) -> Direction:
    """DXY confirmation from D1 + H1 only, as required by today's prompt."""
    d1 = structure_bias(snapshot.dxy_d1)
    h1 = structure_bias(snapshot.dxy_h1)
    if d1 == h1:
        return d1
    if d1 == Direction.NEUTRAL:
        return h1
    if h1 == Direction.NEUTRAL:
        return d1
    return Direction.NEUTRAL


def apply_prompt_confirmation_contract(analysis: Analysis, snapshot: MarketSnapshot) -> Analysis:
    """Align non-zone confirmation/health metadata with the prompt contract.

    This function cannot create, move, rank, or delete XAU zones.
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
    structure["dxy_h1"] = structure_bias(snapshot.dxy_h1).value
    structure.pop("dxy_h4", None)
    policy["market_structure"] = structure

    inputs = dict(policy.get("market_inputs") or {})
    inputs["prompt_snapshot_complete"] = complete
    inputs["dxy_confirmation_timeframes"] = ["D1", "H1"]
    policy["market_inputs"] = inputs
    analysis.execution_policy = policy
    return analysis
