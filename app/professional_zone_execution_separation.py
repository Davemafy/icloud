from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .config import SETTINGS
from .models import Direction, Grade, MarketSnapshot, Zone
from .risk_matrix import execution_grade_eligible

# User-approved Master Sniper analysis windows. These are minimum evidence windows;
# retaining additional history is harmless and must never change the source-exact zone.
D1_MIN_CALENDAR_DAYS = 350
H4_MIN_CALENDAR_DAYS = 120
H1_MIN_CALENDAR_DAYS = 28
M15_MIN_TRADING_DAYS = 3


def _span_days(bars: Iterable) -> float:
    rows = list(bars or [])
    if len(rows) < 2:
        return 0.0
    return max(0.0, (int(rows[-1].ts) - int(rows[0].ts)) / 86400.0)


def _trading_days(bars: Iterable) -> int:
    days = set()
    for b in bars or []:
        d = datetime.fromtimestamp(int(b.ts), tz=timezone.utc).date()
        if d.weekday() < 5:
            days.add(d)
    return len(days)


def history_audit(snapshot: MarketSnapshot | None) -> tuple[bool, list[str]]:
    if snapshot is None:
        return False, ["SNAPSHOT_MISSING"]
    checks = {
        "XAU_D1_1Y": _span_days(snapshot.xau_d1) >= D1_MIN_CALENDAR_DAYS,
        "XAU_H4_4M": _span_days(snapshot.xau_h4) >= H4_MIN_CALENDAR_DAYS,
        "XAU_H1_4W": _span_days(snapshot.xau_h1) >= H1_MIN_CALENDAR_DAYS,
        "XAU_M15_3TD": _trading_days(snapshot.xau_m15) >= M15_MIN_TRADING_DAYS,
        "DXY_D1_1Y": _span_days(snapshot.dxy_d1) >= D1_MIN_CALENDAR_DAYS,
        "DXY_H1_4W": _span_days(snapshot.dxy_h1) >= H1_MIN_CALENDAR_DAYS,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return not failed, failed


def conservative_runway(zone: Zone) -> tuple[float, float, bool]:
    """Measure usable target space from the least-favourable edge of the tactical core.

    This is deliberately separate from zone formation. A source-exact institutional
    location remains map truth even when there is no longer enough directional space
    to grant execution authority.
    """
    target = float(zone.original_target1 or 0.0)
    if zone.original_direction == Direction.BUY:
        runway = target - float(zone.core_high) if target > 0 else 0.0
    else:
        runway = float(zone.core_low) - target if target > 0 else 0.0
    need = float(SETTINGS.clear_run_countertrend if zone.countertrend else SETTINGS.clear_run_with_trend)
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
    runway, runway_need, runway_ok = conservative_runway(zone)
    layer = zone_layer(zone, history_ok, runway_ok)

    _replace_or_append(rows, "institutional_layer", layer)
    _replace_or_append(rows, "history_window_ok", "1" if history_ok else "0")
    _replace_or_append(rows, "history_window_failures", ",".join(history_failures) if history_failures else "NONE")
    _replace_or_append(rows, "usable_runway", f"{runway:.5f}")
    _replace_or_append(rows, "required_runway", f"{runway_need:.5f}")
    _replace_or_append(rows, "usable_runway_ok", "1" if runway_ok else "0")
    _replace_or_append(rows, "map_location_authority", "SOURCE_EXACT_PRESERVED")

    if layer != "EXECUTION_CANDIDATE":
        _replace_or_append(rows, "ea_mode", "WATCH_ONLY")
        _replace_or_append(rows, "execution_authority", "NONE")
        reasons = []
        if not execution_grade_eligible(zone):
            reasons.append("GRADE_OR_QUALIFIED_MITIGATION_EXHAUSTED")
        if not history_ok:
            reasons.append("ANALYSIS_HISTORY_WINDOW_INCOMPLETE")
        if not runway_ok:
            reasons.append("INSUFFICIENT_USABLE_RUNWAY")
        _replace_or_append(rows, "separation_guard", ",".join(reasons) or "MAP_CONTEXT_ONLY")
    else:
        _replace_or_append(rows, "separation_guard", "PASS")

    return "\n".join(rows) + "\n"


def install_ai_contract_correction() -> None:
    """Remove the stale B+ watch-only wording without changing deterministic risk sizing."""
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
        rules["bplus_role"] = "reduced-risk execution candidate at 0.25% through <=1 qualified mitigation; all normal gates still required"
        rules["institutional_layers"] = ["MAP_CONTEXT", "EXECUTION_CANDIDATE", "M1_AUTHORIZED"]
        rules["map_location_is_not_execution_authority"] = True
        rules["analysis_history_windows"] = {
            "XAU_D1": "1 year",
            "XAU_H4": "4-6 months",
            "XAU_H1": "4-6 weeks",
            "XAU_M15": "3-5 trading days",
            "DXY_D1": "1 year",
            "DXY_H1": "4-6 weeks",
        }
        rules["clear_run_semantics"] = "usable directional space from conservative tactical-core edge to valid target; never a reason to move the institutional zone"
        return payload

    corrected_payload._tradezone_professional_separation = True
    ai._payload = corrected_payload
