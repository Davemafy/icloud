from __future__ import annotations

from .engine import Candidate, _cluster, _overlap, atr
from .models import Direction, MarketSnapshot
from .prompt_zone_sources import prompt_origins


def build_prompt_candidates(snapshot: MarketSnapshot) -> list[Candidate]:
    """Build cloud-analysis candidates from displacement and sweep/rejection origins.

    D1 remains context-only. H4 is the parent authority; H1 refines or acts as fallback.
    The existing two-zone filter still enforces structural BSL/SSL, freshness,
    reachability, compact geometry, M15 health, and the paper-only M1 handoff.
    """
    h4 = prompt_origins(snapshot.xau_h4, "H4")
    h1 = prompt_origins(snapshot.xau_h1, "H1")
    pad = max(0.01, 0.25 * (snapshot.atr_h1 or atr(snapshot.xau_h1)))
    out: list[Candidate] = []

    for direction in (Direction.BUY, Direction.SELL):
        parents = [x for x in h4 if x.direction == direction]
        children = [x for x in h1 if x.direction == direction]
        matched_h1: set[int] = set()

        for parent in parents:
            matches = [x for x in children if _overlap(parent.low, parent.high, x.low, x.high, pad)]
            if matches:
                child = max(
                    matches,
                    key=lambda q: (
                        q.source_ts,
                        q.strength,
                        -abs((q.low + q.high - parent.low - parent.high) / 2.0),
                    ),
                )
                matched_h1.add(id(child))
                low, high, method = _cluster([parent, child], child)
                out.append(
                    Candidate(
                        direction,
                        low,
                        high,
                        "H4>H1",
                        child.source_ts,
                        f"PROMPT_H4_PARENT_H1_REFINEMENT|{method}",
                        [parent, child],
                    )
                )
            else:
                out.append(
                    Candidate(
                        direction,
                        parent.low,
                        parent.high,
                        "H4",
                        parent.source_ts,
                        "PROMPT_H4_PARENT_ORIGIN",
                        [parent],
                    )
                )

        for child in children:
            if id(child) in matched_h1:
                continue
            out.append(
                Candidate(
                    direction,
                    child.low,
                    child.high,
                    "H1",
                    child.source_ts,
                    "PROMPT_H1_TACTICAL_FALLBACK",
                    [child],
                )
            )

    return out


def install_prompt_candidate_policy() -> None:
    """Install the prompt-guided candidate builder across cloud analysis modules."""
    from . import institutional_two_zone, intraday_engine

    intraday_engine.build_candidates = build_prompt_candidates
    institutional_two_zone.build_candidates = build_prompt_candidates
