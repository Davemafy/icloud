from __future__ import annotations

import hashlib
from math import isclose


SNIPER_PARITY_VERSION = "SNIPER_PARITY_V1"
_PLAN_FINALIZER_INSTALLED = False
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


def _canonical_value(field: str, value) -> str:
    if field == "base_risk_pct":
        try:
            return f"{float(value or 0.0):.8f}"
        except (TypeError, ValueError):
            return "INVALID"
    if field == "qualified_mitigations":
        try:
            return str(int(value or 0))
        except (TypeError, ValueError):
            return "INVALID"
    return str(value or "").strip()


def contract_fingerprint(contract: dict) -> str:
    """Stable, language-neutral fingerprint for the eight-field Sniper contract.

    The wire representation is intentionally simple so MQL5 can reproduce it:
    field=value pairs in _REQUIRED_SEQUENCE_FIELDS order, joined by ``|``.
    """
    raw = "|".join(f"{field}={_canonical_value(field, contract.get(field))}" for field in _REQUIRED_SEQUENCE_FIELDS)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cloud_contract(analysis, zone, *, risk_context: str, base_risk_pct: float, execution_eligible: bool) -> dict:
    """Build the authoritative Cloud-side contract for the selected Sniper zone."""
    if analysis is None or zone is None:
        out = {
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
        out["contract_fingerprint"] = contract_fingerprint(out)
        return out
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
    out = {
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
    out["contract_fingerprint"] = contract_fingerprint(out)
    return out


def evaluate_sequence_parity(cloud: dict, sequence: dict, *, online: bool, open_positions: int = 0) -> dict:
    """Compare Sequence's loaded contract echo to current Cloud truth.

    Legacy Sequence builds are explicitly UNVERIFIED rather than falsely MATCHED.
    A mismatch blocks *new-entry* trust only; open-position management remains
    allowed and is reported separately.
    """
    seq = dict(sequence or {})
    cloud_fp = contract_fingerprint(cloud or {})
    result = {
        "version": SNIPER_PARITY_VERSION,
        "status": "OFFLINE" if not online else "UNVERIFIED",
        "verified": False,
        "new_entry_safe": False,
        "position_management_safe": bool(int(open_positions or 0) > 0),
        "reason": "SEQUENCE_OFFLINE" if not online else "LEGACY_TELEMETRY",
        "mismatches": [],
        "cloud": dict(cloud or {}),
        "cloud_fingerprint": cloud_fp,
        "sequence_fingerprint": str(seq.get("contract_fingerprint") or ""),
    }
    if not online:
        return result
    missing = [name for name in _REQUIRED_SEQUENCE_FIELDS if name not in seq]
    if missing:
        result["missing_fields"] = missing
        return result
    if not str(seq.get("contract_fingerprint") or ""):
        result["missing_fields"] = ["contract_fingerprint"]
        result["reason"] = "INCOMPLETE_PARITY_TELEMETRY"
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

    computed_sequence_fp = contract_fingerprint(seq)
    sequence_wire_fp = str(seq.get("contract_fingerprint") or "")
    if sequence_wire_fp != computed_sequence_fp or sequence_wire_fp != cloud_fp:
        mismatches.append("contract_fingerprint")

    result["mismatches"] = mismatches
    result["verified"] = not mismatches
    result["computed_sequence_fingerprint"] = computed_sequence_fp
    if mismatches:
        result["status"] = "MISMATCH"
        result["reason"] = "SNIPER_CONTRACT_MISMATCH"
        return result
    result["status"] = "MATCH"
    result["reason"] = "SNIPER_CONTRACT_MATCH"
    result["new_entry_safe"] = True
    return result


def plan_contract_from_kv(kv: dict) -> dict:
    """Build the eight-field authoritative contract from the final MT5 plan KV."""
    data = dict(kv or {})
    return {
        "analysis_id": str(data.get("analysis_id") or ""),
        "zone_id": str(data.get("zone_id") or ""),
        "direction": str(data.get("original_direction") or data.get("direction") or ""),
        "current_grade": str(data.get("current_grade") or data.get("grade") or ""),
        "qualified_mitigations": data.get("qualified_mitigations", data.get("touch_count", 0)),
        "risk_context": str(data.get("risk_context") or ""),
        "base_risk_pct": data.get("base_risk_pct", data.get("original_risk_pct", data.get("grade_risk_pct", 0.0))),
        "execution_authority": str(data.get("execution_authority") or "NONE"),
    }


def plan_contract_from_text(text: str) -> dict:
    kv: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key:
            kv[key] = value.strip()
    return plan_contract_from_kv(kv)


def sequence_contract_from_details(details: dict) -> dict:
    """Extract the contract echo without confusing runtime gate authority with plan authority."""
    data = dict(details or {})
    return {
        "analysis_id": data.get("analysis_id", ""),
        "zone_id": data.get("zone_id", ""),
        "direction": data.get("direction", ""),
        "current_grade": data.get("current_grade", ""),
        "qualified_mitigations": data.get("qualified_mitigations", 0),
        "risk_context": data.get("risk_context", ""),
        "base_risk_pct": data.get("base_risk_pct", 0.0),
        "execution_authority": data.get("contract_execution_authority", data.get("execution_authority", "NONE")),
        "contract_fingerprint": data.get("contract_fingerprint", ""),
    }


def finalize_plan_contract_text(text: str) -> str:
    """Stamp the fingerprint only after every plan safety/separation layer has run."""
    rows = [line for line in str(text or "").splitlines() if line]
    kv: dict[str, str] = {}
    order: list[str] = []
    for row in rows:
        if "=" not in row:
            continue
        key, value = row.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if key not in kv:
            order.append(key)
        kv[key] = value.strip()

    kv["current_grade"] = str(kv.get("current_grade") or kv.get("grade") or "")
    kv["qualified_mitigations"] = str(kv.get("qualified_mitigations", kv.get("touch_count", "0")))
    try:
        base_risk = float(kv.get("base_risk_pct", kv.get("original_risk_pct", kv.get("grade_risk_pct", 0.0))) or 0.0)
    except (TypeError, ValueError):
        base_risk = 0.0
    kv["base_risk_pct"] = f"{base_risk:.8f}"
    kv["sniper_parity_version"] = SNIPER_PARITY_VERSION
    kv["contract_fingerprint"] = contract_fingerprint(plan_contract_from_kv(kv))

    for key in (
        "current_grade",
        "qualified_mitigations",
        "base_risk_pct",
        "sniper_parity_version",
        "contract_fingerprint",
    ):
        if key not in order:
            order.append(key)
    return "".join(f"{key}={kv[key]}\n" for key in order)


def install_plan_contract_finalizer() -> None:
    """Make fingerprinting the outermost plan-export step.

    Several runtime wrappers are allowed to fail the plan closed after the main
    execution guard runs (for example live thesis ownership synchronization).
    Any such wrapper can legitimately change ea_mode/execution_authority. The
    fingerprint must therefore be stamped after *all* wrappers, otherwise the
    Cloud publishes a stale fingerprint for a plan whose final authority is NONE.
    """
    global _PLAN_FINALIZER_INSTALLED
    if _PLAN_FINALIZER_INSTALLED:
        return

    from . import engine

    original = engine.active_plan_text
    if getattr(original, "_tradezone_sniper_contract_finalizer_v1", False):
        _PLAN_FINALIZER_INSTALLED = True
        return

    def finalized_active_plan_text(analysis, snapshot=None):
        return finalize_plan_contract_text(original(analysis, snapshot))

    finalized_active_plan_text._tradezone_sniper_contract_finalizer_v1 = True
    engine.active_plan_text = finalized_active_plan_text
    _PLAN_FINALIZER_INSTALLED = True
