from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .config import SETTINGS
from .models import Direction, Grade, MarketSnapshot, Zone
from .risk_matrix import execution_grade_eligible, zone_risk_context

# User-approved Master Sniper analysis windows. These are minimum evidence windows;
# retaining additional history for lifecycle/mitigation accounting is harmless and
# must never change the source-exact zone used by the analysis layer.
D1_MIN_CALENDAR_DAYS = 350
H4_MIN_CALENDAR_DAYS = 120
H1_MIN_CALENDAR_DAYS = 28
M15_MIN_TRADING_DAYS = 3

# Minimum bar counts are the live prompt-completeness contract. Extended XAU
# windows below are execution-authority evidence. DXY is confirmation/confluence:
# it must meet these minimum counts, but extended DXY depth cannot manufacture or
# veto an XAU institutional zone by itself.
MIN_BAR_COUNTS = {
    "XAU_D1": 80,
    "XAU_H4": 120,
    "XAU_H1": 160,
    "XAU_M15": 160,
    "DXY_D1": 60,
    "DXY_H4": 80,
    "DXY_H1": 100,
}


def _span_days(bars: Iterable) -> float:
    timestamps = [int(getattr(b, "ts", 0) or 0) for b in (bars or [])]
    timestamps = [ts for ts in timestamps if ts > 0]
    if len(timestamps) < 2:
        return 0.0
    return max(0.0, (max(timestamps) - min(timestamps)) / 86400.0)


def _trading_days(bars: Iterable) -> int:
    days = set()
    for b in bars or []:
        d = datetime.fromtimestamp(int(b.ts), tz=timezone.utc).date()
        if d.weekday() < 5:
            days.add(d)
    return len(days)


def _series(snapshot: MarketSnapshot, key: str):
    return getattr(snapshot, key.lower(), []) or []


def history_metrics(snapshot: MarketSnapshot | None) -> dict[str, float | int]:
    if snapshot is None:
        return {}
    out: dict[str, float | int] = {}
    for label in MIN_BAR_COUNTS:
        bars = _series(snapshot, label)
        out[f"{label}_bars"] = len(bars)
        if label.endswith("M15"):
            out[f"{label}_trading_days"] = _trading_days(bars)
        else:
            out[f"{label}_span_days"] = round(_span_days(bars), 2)
    return out


def history_audit(snapshot: MarketSnapshot | None) -> tuple[bool, list[str]]:
    """Hard execution-history audit.

    XAU extended windows are authority evidence because zones are built from XAU.
    DXY is confirmation only, so it must satisfy the live prompt minimum bar counts
    but a shorter *extended* DXY window is not allowed to veto an XAU thesis.
    """
    if snapshot is None:
        return False, ["SNAPSHOT_MISSING"]

    checks = {
        "XAU_D1_MIN_BARS": len(snapshot.xau_d1) >= MIN_BAR_COUNTS["XAU_D1"],
        "XAU_H4_MIN_BARS": len(snapshot.xau_h4) >= MIN_BAR_COUNTS["XAU_H4"],
        "XAU_H1_MIN_BARS": len(snapshot.xau_h1) >= MIN_BAR_COUNTS["XAU_H1"],
        "XAU_M15_MIN_BARS": len(snapshot.xau_m15) >= MIN_BAR_COUNTS["XAU_M15"],
        "DXY_D1_MIN_BARS": len(snapshot.dxy_d1) >= MIN_BAR_COUNTS["DXY_D1"],
        "DXY_H4_MIN_BARS": len(snapshot.dxy_h4) >= MIN_BAR_COUNTS["DXY_H4"],
        "DXY_H1_MIN_BARS": len(snapshot.dxy_h1) >= MIN_BAR_COUNTS["DXY_H1"],
        "XAU_D1_1Y": _span_days(snapshot.xau_d1) >= D1_MIN_CALENDAR_DAYS,
        "XAU_H4_4M": _span_days(snapshot.xau_h4) >= H4_MIN_CALENDAR_DAYS,
        "XAU_H1_4W": _span_days(snapshot.xau_h1) >= H1_MIN_CALENDAR_DAYS,
        "XAU_M15_3TD": _trading_days(snapshot.xau_m15) >= M15_MIN_TRADING_DAYS,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return not failed, failed


def confluence_history_audit(snapshot: MarketSnapshot | None) -> list[str]:
    """Extended DXY depth is quality telemetry, never standalone XAU authority."""
    if snapshot is None:
        return ["DXY_HISTORY_UNAVAILABLE"]
    checks = {
        "DXY_D1_EXTENDED_LT_1Y": _span_days(snapshot.dxy_d1) >= D1_MIN_CALENDAR_DAYS,
        "DXY_H4_EXTENDED_LT_4M": _span_days(snapshot.dxy_h4) >= H4_MIN_CALENDAR_DAYS,
        "DXY_H1_EXTENDED_LT_4W": _span_days(snapshot.dxy_h1) >= H1_MIN_CALENDAR_DAYS,
    }
    return [name for name, ok in checks.items() if not ok]


def _history_metrics_text(snapshot: MarketSnapshot | None) -> str:
    m = history_metrics(snapshot)
    if not m:
        return "NONE"
    order = (
        "XAU_D1", "XAU_H4", "XAU_H1", "XAU_M15",
        "DXY_D1", "DXY_H4", "DXY_H1",
    )
    parts = []
    for label in order:
        bars = int(m.get(f"{label}_bars", 0) or 0)
        if label == "XAU_M15":
            depth = f"{int(m.get(f'{label}_trading_days', 0) or 0)}td"
        else:
            depth = f"{float(m.get(f'{label}_span_days', 0.0) or 0.0):.1f}d"
        parts.append(f"{label}:{bars}/{depth}")
    return ";".join(parts)


def conservative_runway(zone: Zone, target_override: float | None = None) -> tuple[float, float, bool]:
    """Measure usable target space from the least-favourable edge of the tactical core.

    When a thesis already owns execution, TP1 can legitimately be behind the
    ownership anchor. The final plan guard therefore passes the next still-open
    objective as target_override; falling back to zone.original_target1 preserves
    pre-activation behavior.
    """
    target = float(target_override if target_override and target_override > 0 else (zone.original_target1 or 0.0))
    if zone.original_direction == Direction.BUY:
        runway = target - float(zone.core_high) if target > 0 else 0.0
    else:
        runway = float(zone.core_low) - target if target > 0 else 0.0
    context = zone_risk_context(zone)
    need = float(
        SETTINGS.clear_run_countertrend
        if context == "COUNTERTREND"
        else SETTINGS.clear_run_with_trend
    )
    runway = max(0.0, runway)
    return runway, need, runway >= need


def zone_layer(zone: Zone, history_ok: bool, runway_ok: bool) -> str:
    if not execution_grade_eligible(zone):
        return "MAP_CONTEXT"
    if not history_ok or not runway_ok:
        return "MAP_CONTEXT"
    return "EXECUTION_CANDIDATE"


def _kv(text: str) -> tuple[list[str], dict[str, str]]:
    rows = [line for line in str(text).splitlines() if line]
    values: dict[str, str] = {}
    for line in rows:
        if "=" in line:
            k, v = line.split("=", 1)
            values[k] = v
    return rows, values


def _replace_or_append(rows: list[str], key: str, value: str) -> None:
    prefix = key + "="
    for i, row in enumerate(rows):
        if row.startswith(prefix):
            rows[i] = prefix + value
            return
    rows.append(prefix + value)


def apply_execution_separation(text: str, analysis, snapshot: MarketSnapshot | None) -> str:
    """Fail closed without moving, resizing, regrading or deleting the published map zone."""
    rows, values = _kv(text)
    zone_id = values.get("zone_id", "")
    zone = next((z for z in getattr(analysis, "zones", []) if z.zone_id == zone_id), None)
    if zone is None:
        return text

    history_ok, history_failures = history_audit(snapshot)
    history_warnings = confluence_history_audit(snapshot)
    history_metrics_text = _history_metrics_text(snapshot)
    runway_target = 0.0
    runway_target_basis = "ZONE_ORIGINAL_TARGET1"
    for key in ("next_open_target", "original_target1"):
        try:
            candidate = float(values.get(key, "0") or 0.0)
        except (TypeError, ValueError):
            candidate = 0.0
        if candidate > 0:
            runway_target = candidate
            runway_target_basis = "FINAL_PLAN_" + key.upper()
            break
    runway, runway_need, runway_ok = conservative_runway(
        zone,
        target_override=runway_target if runway_target > 0 else None,
    )
    spread = float(getattr(snapshot, "spread_points", 0.0) or 0.0) if snapshot is not None else 0.0
    spread_ok = snapshot is not None and spread <= float(SETTINGS.max_spread_points)
    if snapshot is None:
        snapshot_age = 10**9
    elif str(getattr(snapshot, "kind", "") or "").upper() == "HISTORICAL_REPLAY":
        snapshot_age = max(0, int(getattr(analysis, "generated_at", snapshot.sent_at) or snapshot.sent_at) - int(snapshot.sent_at))
    else:
        snapshot_age = max(0, int(datetime.now(tz=timezone.utc).timestamp()) - int(snapshot.sent_at))
    snapshot_ok = snapshot is not None and snapshot_age <= int(SETTINGS.max_snapshot_age_seconds)
    layer = zone_layer(zone, history_ok, runway_ok)

    _replace_or_append(rows, "institutional_layer", layer)
    _replace_or_append(rows, "history_window_ok", "1" if history_ok else "0")
    _replace_or_append(rows, "history_window_failures", ",".join(history_failures) if history_failures else "NONE")
    _replace_or_append(rows, "history_confluence_warnings", ",".join(history_warnings) if history_warnings else "NONE")
    _replace_or_append(rows, "history_window_metrics", history_metrics_text)
    _replace_or_append(rows, "usable_runway", f"{runway:.5f}")
    _replace_or_append(rows, "required_runway", f"{runway_need:.5f}")
    _replace_or_append(rows, "usable_runway_ok", "1" if runway_ok else "0")
    _replace_or_append(rows, "usable_runway_target", f"{float(runway_target or zone.original_target1 or 0.0):.5f}")
    _replace_or_append(rows, "usable_runway_target_basis", runway_target_basis)
    _replace_or_append(rows, "map_location_authority", "SOURCE_EXACT_PRESERVED")
    _replace_or_append(rows, "live_spread_points", f"{spread:.2f}")
    _replace_or_append(rows, "max_spread_points", f"{float(SETTINGS.max_spread_points):.2f}")
    _replace_or_append(rows, "spread_safety_ok", "1" if spread_ok else "0")
    _replace_or_append(rows, "snapshot_age_seconds", str(snapshot_age))
    _replace_or_append(rows, "snapshot_safety_ok", "1" if snapshot_ok else "0")

    # B+ authority is a grade/risk contract, not a statement that a live order is
    # currently authorized. Preserve that truth even while the final execution
    # layer correctly fails closed for missing history/snapshot/spread/runway.
    bplus_grade_authority = bool(zone.grade == Grade.B_PLUS and execution_grade_eligible(zone))
    _replace_or_append(rows, "bplus_execution_authority", "1" if bplus_grade_authority else "0")
    _replace_or_append(rows, "bplus_reduced_risk", "1" if bplus_grade_authority else "0")

    # Location/map truth is independent of execution authority. Incomplete analysis
    # history or runway keeps a zone as context. Live spread/snapshot safety is a
    # separate final execution hold and never destroys an earned thesis/map.
    reasons = []
    if not execution_grade_eligible(zone):
        reasons.append("GRADE_NOT_EXECUTABLE")
    if not history_ok:
        reasons.append("ANALYSIS_HISTORY_WINDOW_INCOMPLETE")
    if not runway_ok:
        reasons.append("INSUFFICIENT_USABLE_RUNWAY")
    if not spread_ok:
        reasons.append("SPREAD_SAFETY_HOLD")
    if not snapshot_ok:
        reasons.append("SNAPSHOT_SAFETY_HOLD")

    structural_block = layer != "EXECUTION_CANDIDATE"
    safety_hold = not spread_ok or not snapshot_ok

    if structural_block:
        # Structural/history/runway failure means execution authority was never
        # legitimately earned for this plan.
        _replace_or_append(rows, "ea_mode", "WATCH_ONLY")
        _replace_or_append(rows, "execution_authority", "NONE")
        _replace_or_append(rows, "safety_hold_preserves_authority", "0")
        _replace_or_append(rows, "separation_guard", ",".join(reasons) or "MAP_CONTEXT_ONLY")
    elif safety_hold:
        # Spread/snapshot safety suspends ORDER permission only. Keep the already-
        # earned macro authority in the plan so MT5 parity/ownership truth remains
        # synchronized. WATCH_ONLY is a second fail-closed barrier; /mt5/plan also
        # exports live_block=1 and Sequence refuses the order before micro execution.
        _replace_or_append(rows, "ea_mode", "WATCH_ONLY")
        _replace_or_append(rows, "safety_hold_preserves_authority", "1")
        _replace_or_append(rows, "separation_guard", ",".join(reasons) or "SAFETY_HOLD")
    else:
        _replace_or_append(rows, "safety_hold_preserves_authority", "0")
        _replace_or_append(rows, "separation_guard", "PASS")

    return "\n".join(rows) + "\n"


def install_ai_contract_correction() -> None:
    """Remove stale B+ wording and publish the exact Master Sniper evidence contract."""
    from . import ai

    ai.SYSTEM = ai.SYSTEM.replace(
        "A+ and A are execution grades; B+ is research context/watch only.",
        "A+, A and B+ are execution grades when their normal gates pass; B+ uses the dedicated reduced 0.25% authority and is limited to <=1 qualified mitigation.",
    )
    original_payload = ai._payload
    if getattr(original_payload, "_tradezone_professional_separation", False):
        return

    def corrected_payload(a, s):
        payload = original_payload(a, s)
        rules = payload.setdefault("rules", {})
        rules["bplus_execution_authority"] = True
        rules["bplus_role"] = "reduced-risk execution candidate at 0.25% when structurally produced; mitigation count is telemetry only and all normal gates still apply"
        rules["institutional_layers"] = ["MAP_CONTEXT", "EXECUTION_CANDIDATE", "M1_AUTHORIZED"]
        rules["map_location_is_not_execution_authority"] = True
        rules["analysis_history_windows"] = {
            "XAU_D1": "1 year HARD execution evidence",
            "XAU_H4": "4-6 months HARD execution evidence",
            "XAU_H1": "4-6 weeks HARD execution evidence",
            "XAU_M15": "3-5 trading days HARD health evidence",
            "DXY": "prompt minimum counts required; extended depth is confluence-quality telemetry only",
        }
        rules["dxy_history_authority"] = "DXY is confirmation/confluence only: minimum prompt counts remain mandatory, but extended DXY depth alone cannot veto or manufacture an XAU zone."
        rules["lifecycle_history_is_separate"] = "Mitigation history may retain older M15 bars than the 3-5 trading-day analysis window; it is lifecycle telemetry only and must not change grade, risk, ranking, authority, width or location."
        rules["spread_safety"] = f"hard execution hold above {float(SETTINGS.max_spread_points):.0f} points; spread never changes zone geometry or thesis map truth"
        rules["clear_run_semantics"] = "usable directional space from conservative tactical-core edge to valid target; never a reason to move the institutional zone"
        return payload

    corrected_payload._tradezone_professional_separation = True
    ai._payload = corrected_payload