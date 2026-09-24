from __future__ import annotations

"""Master Sniper structural geometry correction (PAPER/DEMO only).

Contract V6586: HTF source candles are provenance/guardrails; the published map
is the tactical structural reaction band around genuine attached liquidity and
native refinement. No manual price is hard-coded.
"""

from .config import SETTINGS
from .engine import atr
from .models import Direction

CONTRACT = "MASTER_SNIPER_TACTICAL_MAP_V6586"


def _safe_atr(snapshot, field: str, bars_field: str) -> float:
    direct = float(getattr(snapshot, field, 0.0) or 0.0)
    bars = getattr(snapshot, bars_field, []) or []
    derived = float(atr(bars)) if bars else 0.0
    return max(direct, derived, 1e-9)


def _candidate_atr_limit(candidate, snapshot) -> float:
    tf = str(candidate.source_tf).upper()
    if tf in {"H4", "H4>H1"}:
        h4 = _safe_atr(snapshot, "atr_h4", "xau_h4")
        h1 = _safe_atr(snapshot, "atr_h1", "xau_h1")
        return SETTINGS.zone_liquidity_envelope_max_h4_atr * max(h4, h1)
    return SETTINGS.zone_liquidity_envelope_max_h1_atr * _safe_atr(snapshot, "atr_h1", "xau_h1")


def _m15_atr(snapshot) -> float:
    return _safe_atr(snapshot, "atr_m15", "xau_m15")


def _sweep_buffer(snapshot) -> float:
    return max(0.0, SETTINGS.zone_liquidity_sweep_buffer_m15_atr * _m15_atr(snapshot))


def _tactical_depth(snapshot) -> float:
    return _m15_atr(snapshot)


def _tactical_band(candidate, core_low: float, core_high: float, liquidity_price: float, snapshot):
    source_low, source_high = sorted((float(candidate.zone_low), float(candidate.zone_high)))
    depth = _tactical_depth(snapshot)
    sweep = _sweep_buffer(snapshot)
    price = float(liquidity_price)
    if candidate.direction == Direction.SELL:
        if price < core_low:
            return None
        low = max(source_low, min(core_low, price - depth))
        high = max(core_high, price + sweep, min(source_high, price + depth))
        high = min(high, source_high + _candidate_atr_limit(candidate, snapshot))
    else:
        if price > core_high:
            return None
        low = min(core_low, price - sweep, max(source_low, price - depth))
        low = max(low, source_low - _candidate_atr_limit(candidate, snapshot))
        high = min(source_high, max(core_high, price + depth))
    if high <= low:
        return None
    if not (low - 1e-9 <= core_high and core_low <= high + 1e-9):
        return None
    return float(low), float(high)


def _install_engine_geometry() -> None:
    from . import institutional_two_zone as zoning

    def normalize_core(candidate, snapshot):
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
        attachment = max(0.0, price - source_high) if candidate.direction == Direction.SELL else max(0.0, source_low - price)
        if attachment > reach + 1e-9:
            return None
        band = _tactical_band(candidate, core_low, core_high, price, snapshot)
        if band is None:
            return None
        low, high = band
        room = (high - price) if candidate.direction == Direction.SELL else (price - low)
        if room + 1e-9 < _sweep_buffer(snapshot):
            return None
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
                out["rejection_reason"] = f"No genuine {required} is attached to this institutional source within configured HTF structural reach; remote liquidity was not pulled in."
            elif code == "ZONE_GEOMETRY_CANNOT_FIT_SWEEP":
                out["rejection_code"] = "TACTICAL_MAP_GEOMETRY_INVALID"
                out["rejection_reason"] = "The native refinement and attached structural liquidity cannot form a valid Master Sniper tactical reaction band."
            return zone, out
        candidate_with_truth._master_sniper_adaptive_diag = True
        zoning._candidate_zone = candidate_with_truth


def install_master_sniper_adaptive_geometry() -> None:
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
            "geometry_authority": "MASTER_SNIPER_STRUCTURAL_TACTICAL_MAP",
            "source_geometry_role": "PROVENANCE_AND_ATTACHMENT_GUARD_NOT_PUBLISHED_ZONE",
            "core_geometry": "EXACT_INSTITUTIONAL_SOURCE_BODY_OR_H1_REFINEMENT",
            "published_zone_geometry": "ATTACHED_LIQUIDITY_PLUS_M15_ATR_REACTION_BAND",
            "fixed_width_padding": False,
            "fixed_200_300_point_veto": False,
            "remote_liquidity_envelope_expansion": False,
            "hardcoded_manual_prices": False,
            "m15_atr_is_band_depth_not_location_source": True,
        })
        policy["public_zone_map"] = zone_map
        policy["zone_geometry"] = {
            "authority": CONTRACT,
            "source": "HTF_PROVENANCE_GUARD",
            "core": "EXACT_SOURCE_BODY_OR_NATIVE_H1_REFINEMENT",
            "published_zone": "STRUCTURAL_LIQUIDITY_REACTION_BAND",
            "fixed_width_padding": False,
            "hardcoded_prices": False,
            "remote_liquidity_expansion": False,
        }
        analysis.execution_policy = policy
        analysis.trader_brief = str(analysis.trader_brief or "") + " MASTER SNIPER V6586: H4/H1 source candles are provenance, not published alert zones. Published BUY/SELL zones are volatility-scaled tactical reaction bands around genuine attached SSL/BSL plus native refinement; no manual price is hard-coded."
        return analysis

    runtime.install_zone_geometry_policy = install_geometry
    runtime.apply_pip_display_contract = display_contract
    runtime._MASTER_SNIPER_ADAPTIVE_WRAPPED = True
