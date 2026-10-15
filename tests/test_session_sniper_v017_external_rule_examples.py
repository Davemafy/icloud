"""Specification examples for the v0.17 external-liquidity rule.

The examples independently check the *business rule*. They are NOT MT5 broker
candle replays or proof that the compiled MQL runtime passes these fixtures.
That still requires the MT5 Strategy Tester and demo VPS.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    kind: str
    objective: float
    confirmed: bool = True
    unswept: bool = True
    unfilled: bool = True


def select_side(reference: float, buy: bool, options: list[Candidate]):
    valid = [
        c for c in options
        if c.confirmed and (c.unswept if c.kind == "SWING" else c.unfilled)
        and ((c.objective < reference) if buy else (c.objective > reference))
    ]
    if not valid:
        return None
    # On equal objective price, source code uses swing as the stable tie-break.
    return sorted(
        valid,
        key=lambda c: (
            reference - c.objective if buy else c.objective - reference,
            0 if c.kind == "SWING" else 1,
        ),
    )[0]


def test_screenshot_example_nearest_downside_fvg_bottom_wins_only_when_unfilled():
    low = 4145.195
    candidates = [
        Candidate("SWING", 4144.410, confirmed=False),  # one-bar dip
        Candidate("FVG_BOTTOM", 4139.760),
        Candidate("SWING", 4131.585),
    ]
    selected = select_side(low, True, candidates)
    assert (selected.kind, selected.objective) == ("FVG_BOTTOM", 4139.760)
    filled = [
        Candidate(c.kind, c.objective, c.confirmed, c.unswept,
                  unfilled=False if c.objective == 4139.760 else c.unfilled)
        for c in candidates
    ]
    selected = select_side(low, True, filled)
    assert (selected.kind, selected.objective) == ("SWING", 4131.585)


def test_shallow_level_may_win_if_it_really_is_confirmed_and_unswept():
    result = select_side(
        4145.195, True,
        [Candidate("SWING", 4144.41), Candidate("FVG_BOTTOM", 4139.760)],
    )
    assert result.objective == 4144.41


def test_proximal_edge_must_not_compete_with_distal_fvg_objective():
    # Hypothetical still-unfilled bullish gap: proximal 4144.80,
    # distal bottom 4139.76. The distal is the sweep target.
    result = select_side(
        4145.195, True,
        [Candidate("SWING", 4142.0), Candidate("FVG_BOTTOM", 4139.76)],
    )
    assert result.kind == "SWING"


def test_sell_side_uses_eligible_bearish_fvg_top_not_lower_edge():
    result = select_side(
        4158.8, False,
        [Candidate("SWING", 4171.3), Candidate("FVG_TOP", 4166.0)],
    )
    assert (result.kind, result.objective) == ("FVG_TOP", 4166.0)


def test_exhausted_or_inside_range_cannot_activate_external_target():
    assert select_side(4145.195, True, [
        Candidate("SWING", 4131.585, unswept=False),
        Candidate("FVG_BOTTOM", 4145.5),
        Candidate("FVG_BOTTOM", 4139.760, unfilled=False),
    ]) is None


def test_ties_choose_confirmed_swing():
    result = select_side(
        4150, True,
        [Candidate("FVG_BOTTOM", 4140), Candidate("SWING", 4140)],
    )
    assert result.kind == "SWING"
