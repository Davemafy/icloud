from __future__ import annotations

"""Master Sniper structural geometry correction (PAPER/DEMO only).

The institutional source candle is the anchor and its body/refinement remains the
execution core. Genuine structural BSL/SSL may define the distal envelope when it
is attached to that source within the configured HTF structural reach. There is
no fixed 200-300 point width veto and no arbitrary remote-liquidity padding.
"""

from .config import SETTINGS
from .engine import atr
from .models import Direction

CONTRACT = "MASTER_SNIPER_SOURCE_ANCHORED_STRUCTURAL_ENVELOPE_V6582"


def _candidate_atr_limit(candidate, snapshot) -> float:
    tf = str(candidate.source_tf).upper()
    if tf in {"H4", "H4>H1"}:
        base = max(float(atr(snapshot.xau_h4)), float(snapshot.atr_h1 or 0.0), 1e-9)
        return SETTINGS.zone_liquidity_envelope_max_h4_atr * base
    base = max(float(snapshot.atr_h1 or atr(snapshot.xau_h1)), 1e-9)
    return SETTINGS.zone_liquidity_envelope_max_h1_atr * base


def _sweep_buffer(snapshot) -> float:
    base = max(float(snapshot.atr_m15 or atr(snapshot.xau_m15)), 1e-9)
    return max(0.0, SETTINGS.zone_liquidity_sweep_buffer_m15_atr * base)


def _install_engine_geometry() -> None:
    from . import institutional_two_zone as zoning

    def normalize_core(candidate, snapshot):
        # Master Sniper core = real source body / H1 refinement. Never normalize
        # the core to a fixed point width.
        return tuple(sorted((float(candidate.core_low), float(candidate.core_high))))

    def select_liquidity(candidate, core_low, core_high, liq, snapshot):
        required = zoning._required_liquidity(candidate.direction)
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        reach = _candidate_atr_limit(candidate, snapshot)
        tf_rank = {"D1": 0, "H4": 1, "H1": 2}
        options = []
        for level in liq:
            if required not in str(level.label).upper():
                continue
            tf = str(level.source_tf).upper()
            if tf not in {"D1", "H4", "H1"}:
                continue
            price = float(level.price)
            if candidate.direction == Direction.SELL:
                if price < core_low:
                    continue
                attachment = max(0.0, price - source_high)
                edge = abs(price - core_high)
            else:
                if price > core_high:
                    continue
                attachment = max(0.0, source_low - price)
                edge = abs(core_low - price)
            # Liquidity already inside the source is ideal. External structural
            # liquidity is allowed only when still attached to the source within
            # the existing HTF ATR reach guard. This prevents remote fabrication.
            if attachment > reach + 1e-9:
                continue
            options.append((0 if attachment == 0.0 else 1, tf_rank.get(tf, 9), attachment, edge, float(level.distance), level))
        if not options:
            return None
        options.sort(key=lambda row: row[:-1])
        return options[0][-1]

    def build_geometry(candidate, core_low, core_high, level, snapshot):
        source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
        price = float(level.price)
        if core_low < source_low - 1e-9 or core_high > source_high + 1e-9:
            return None
        reach = _candidate_atr_limit(candidate, snapshot)
        buffer = _sweep_buffer(snapshot)
        if candidate.direction == Direction.SELL:
            if price < core_low:
                return None
            attachment = max(0.0, price - source_high)
            if attachment > reach + 1e-9:
                return None
            low = source_low
            high = max(source_high, price + buffer)
            room = high - price
        else:
            if price > core_high:
                return None
            attachment = max(0.0, source_low - price)
            if attachment > reach + 1e-9:
                return None
            low = min(source_low, price - buffer)
            high = source_high
            room = price - low
        return low, high, max(0.0, room)

    zoning._normalize_core = normalize_core
    zoning._select_liquidity = select_liquidity
    zoning._build_geometry = build_geometry

    current = zoning._candidate_zone
    if not getattr(current, "_master_sniper_adaptive_diag", False):
        def candidate_with_truth(candidate, snapshot, liq, context, index):
            zone, diag = current(candidate, snapshot, liq, context, index)
            if zone is not None or not isinstance(diag, dict):
                return zone, diag
            out = dict(diag)
            code = str(out.get("rejection_code") or "")
            if code.startswith("MISSING_") and code.endswith("_IN_MARKED_ZONE"):
                required = "BSL" if candidate.direction == Direction.SELL else "SSL"
                out["rejection_code"] = f"NO_ATTACHED_STRUCTURAL_{required}"
                out["rejection_reason"] = (
                    f"No genuine {required} is attached to this institutional source within the configured HTF structural reach. "
                    "The zone was not widened to remote liquidity."
                )
            elif code == "ZONE_GEOMETRY_CANNOT_FIT_SWEEP":
                out["rejection_code"] = "STRUCTURAL_ENVELOPE_INVALID"
                out["rejection_reason"] = (
                    "The source core and attached structural liquidity cannot form a valid directional envelope. "
                    "No fixed 200-300 point width rule is used."
                )
            return zone, out
        candidate_with_truth._master_sniper_adaptive_diag = True
        zoning._candidate_zone = candidate_with_truth


def install_master_sniper_adaptive_geometry() -> None:
    """Make the service's legacy geometry installer finish on Master Sniper V6582."""
    from . import zone_runtime_policy as runtime

    if getattr(runtime, "_MASTER_SNIPER_ADAPTIVE_WRAPPED", False):
        return

    original_install = runtime.install_zone_geometry_policy
    original_display = runtime.apply_pip_display_contract

    def install_geometry():
        original_install()
        _install_engine_geometry()

    def display_contract(analysis, snapshot):
        analysis = original_display(analysis, snapshot)
        if analysis is None:
            return analysis
        policy = dict(analysis.execution_policy or {})
        zone_map = dict(policy.get("public_zone_map") or {})
        zone_map.update({
            "prompt_contract_ref": CONTRACT,
            "geometry_authority": "MASTER_SNIPER_SOURCE_ANCHORED_STRUCTURAL_ENVELOPE",
            "core_geometry": "EXACT_INSTITUTIONAL_SOURCE_BODY_OR_H1_REFINEMENT",
            "envelope_geometry": "SOURCE_RANGE_PLUS_ATTACHED_STRUCTURAL_LIQUIDITY_ONLY",
            "fixed_width_padding": False,
            "fixed_200_300_point_veto": False,
            "remote_liquidity_envelope_expansion": False,
            "structural_liquidity_may_define_distal_envelope": True,
        })
        policy["public_zone_map"] = zone_map
        policy["zone_geometry"] = {
            "authority": CONTRACT,
            "core": "EXACT_SOURCE_BODY_OR_NATIVE_H1_REFINEMENT",
            "envelope": "SOURCE_ANCHORED_TO_ATTACHED_STRUCTURAL_LIQUIDITY",
            "fixed_width_padding": False,
            "atr_is_attachment_guard_not_padding": True,
            "remote_liquidity_expansion": False,
        }
        analysis.execution_policy = policy
        brief = str(analysis.trader_brief or "")
        stale = "Structural liquidity must already exist inside the source envelope."
        brief = brief.replace(stale, "Structural liquidity must be genuinely attached to the source; when it sits just beyond the source candle it may define the distal envelope within the HTF structural-reach guard.")
        brief += " MASTER SNIPER V6582: source core is exact; the envelope follows genuine attached structural liquidity and is never rejected by a fixed 200-300 point width cap. Remote liquidity is never pulled in to manufacture a zone."
        analysis.trader_brief = brief
        return analysis

    runtime.install_zone_geometry_policy = install_geometry
    runtime.apply_pip_display_contract = display_contract
    runtime._MASTER_SNIPER_ADAPTIVE_WRAPPED = True
