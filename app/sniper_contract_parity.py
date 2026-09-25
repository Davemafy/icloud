from __future__ import annotations

from math import isclose


SNIPER_PARITY_VERSION = "SNIPER_PARITY_V1"
_REQUIRED_SEQUENCE_FIELDS = (
    "analysis_id",
    "zone_id",
    "direction",
    "current_grade",
    "qualified_mitigations",
    "risk_context",
    "base_risk_pct",
    "execution_authority",
)


def cloud_contract(analysis, zone, *, risk_context: str, base_risk_pct: float, execution_eligible: bool) -> dict:
    """Build the authoritative Cloud-side contract for the selected Sniper zone."""
    if analysis is None or zone is None:
        return {
            "parity_version": SNIPER_PARITY_VERSION,
            "analysis_id": "",
            "zone_id": "",
            "direction": "",
            "current_grade": "",
            "qualified_mitigations": 0,
            "risk_context": "",
            "base_risk_pct": 0.0,
            "execution_authority": "NONE",
        }
    policy = dict(getattr(analysis, "execution_policy", {}) or {})
    authority = str(dict(policy.get("execution_authority") or {}).get("authority") or "NONE")
    notes = list(getattr(zone, "notes", []) or [])
    qualified = int(getattr(zone, "touch_count", 0) or 0)
    current_grade = str(getattr(getattr(zone, "grade", None), "value", getattr(zone, "grade", "")) or "")
    for note in notes:
        text = str(note)
        if text.startswith("qualified_mitigations:"):
            try:
                qualified = int(float(text.split(":", 1)[1]))
            except (TypeError, ValueError):
                pass
        elif text.startswith("current_execution_grade:"):
            current_grade = text.split(":", 1)[1]
    if not execution_eligible:
        authority = "NONE"
    return {
        "parity_version": SNIPER_PARITY_VERSION,
        "analysis_id": str(getattr(analysis, "analysis_id", "") or ""),
        "zone_id": str(getattr(zone, "zone_id", "") or ""),
        "direction": str(getattr(getattr(zone, "original_direction", None), "value", getattr(zone, "original_direction", "")) or ""),
        "current_grade": current_grade,
        "qualified_mitigations": qualified,
        "risk_context": str(risk_context or ""),
        "base_risk_pct": float(base_risk_pct or 0.0),
        "execution_authority": authority,
    }


def evaluate_sequence_parity(cloud: dict, sequence: dict, *, online: bool, open_positions: int = 0) -> dict:
    """Compare Sequence's loaded contract echo to current Cloud truth.

    Legacy Sequence builds are explicitly UNVERIFIED rather than falsely MATCHED.
    A mismatch blocks *new-entry* trust only; open-position management remains
    allowed and is reported separately.
    """
    seq = dict(sequence or {})
    result = {
        "version": SNIPER_PARITY_VERSION,
        "status": "OFFLINE" if not online else "UNVERIFIED",
        "verified": False,
        "new_entry_safe": False,
        "position_management_safe": bool(int(open_positions or 0) > 0),
        "reason": "SEQUENCE_OFFLINE" if not online else "LEGACY_TELEMETRY",
        "mismatches": [],
        "cloud": dict(cloud or {}),
    }
    if not online:
        return result
    missing = [name for name in _REQUIRED_SEQUENCE_FIELDS if name not in seq]
    if missing:
        result["missing_fields"] = missing
        return result

    mismatches: list[str] = []
    for field in _REQUIRED_SEQUENCE_FIELDS:
        cv = cloud.get(field)
        sv = seq.get(field)
        if field == "base_risk_pct":
            try:
                equal = isclose(float(cv or 0.0), float(sv or 0.0), rel_tol=0.0, abs_tol=1e-9)
            except (TypeError, ValueError):
                equal = False
        elif field == "qualified_mitigations":
            try:
                equal = int(cv or 0) == int(sv or 0)
            except (TypeError, ValueError):
                equal = False
        else:
            equal = str(cv or "") == str(sv or "")
        if not equal:
            mismatches.append(field)

    result["mismatches"] = mismatches
    result["verified"] = not mismatches
    if mismatches:
        result["status"] = "MISMATCH"
        result["reason"] = "SNIPER_CONTRACT_MISMATCH"
        return result
    result["status"] = "MATCH"
    result["reason"] = "SNIPER_CONTRACT_MATCH"
    result["new_entry_safe"] = True
    return result
