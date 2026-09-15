from __future__ import annotations

from typing import Any


def _value(v: Any) -> str:
    raw = getattr(v, "value", v)
    if raw is None:
        return ""
    return str(raw).replace("\r", " ").replace("\n", " ").strip()


def _num(v: Any) -> str:
    try:
        return f"{float(v):.5f}"
    except (TypeError, ValueError):
        return "0.00000"


def _int(v: Any) -> str:
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return "0"


def _readiness(core_method: Any, fallback: Any = "") -> str:
    text = _value(core_method)
    if text:
        return text.split("|", 1)[0]
    return _value(fallback)


def _secondary_records(policy: dict[str, Any]) -> list[dict[str, Any]]:
    public_map = policy.get("public_zone_map", {}) if isinstance(policy, dict) else {}
    secondary = public_map.get("secondary", {}) if isinstance(public_map, dict) else {}
    if not isinstance(secondary, dict):
        return []

    out: list[dict[str, Any]] = []
    for side in ("sell", "buy"):
        raw = secondary.get(side)
        if not isinstance(raw, dict):
            continue
        direction = side.upper()
        source_tf = _value(raw.get("source_tf")) or "HTF"
        source_ts = int(raw.get("source_ts") or 0)
        out.append(
            {
                "id": f"RESERVE_{direction}_{source_tf}_{source_ts}",
                "role": "RESERVE",
                "direction": direction,
                "state": _value(raw.get("state")) or "RESERVE",
                "grade": _value(raw.get("grade")),
                "source_tf": source_tf,
                "source_ts": source_ts,
                "touches": int(raw.get("touches") or 0),
                "zone_low": raw.get("low", 0.0),
                "zone_high": raw.get("high", 0.0),
                "core_low": raw.get("core_low", 0.0),
                "core_high": raw.get("core_high", 0.0),
                "execution_authority": bool(raw.get("execution_authority", False)),
                "active_thesis": False,
            }
        )
    return out


def _primary_records(a: Any, owner_zone_id: str, thesis_locked: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    selected_zone_id = _value(getattr(a, "selected_zone_id", ""))
    for z in list(getattr(a, "zones", []) or []):
        zid = _value(getattr(z, "zone_id", ""))
        active_thesis = bool(thesis_locked and owner_zone_id and zid == owner_zone_id)
        authority = active_thesis or (not thesis_locked and bool(selected_zone_id) and zid == selected_zone_id)
        out.append(
            {
                "id": zid,
                "role": "PRIMARY",
                "direction": _value(getattr(z, "original_direction", "")),
                "state": _readiness(getattr(z, "core_method", ""), getattr(z, "state", "")),
                "grade": _value(getattr(z, "grade", "")),
                "source_tf": _value(getattr(z, "source_tf", "")),
                "source_ts": int(getattr(z, "source_ts", 0) or 0),
                "touches": int(getattr(z, "touch_count", 0) or 0),
                "zone_low": getattr(z, "zone_low", 0.0),
                "zone_high": getattr(z, "zone_high", 0.0),
                "core_low": getattr(z, "core_low", 0.0),
                "core_high": getattr(z, "core_high", 0.0),
                "execution_authority": authority,
                "active_thesis": active_thesis,
            }
        )
    return out


def mt5_zone_render_text(a: Any) -> str:
    """Flat render contract for MT5 chart shading.

    Visual-only feed: it exposes the already-qualified primary and reserve geometry.
    It does not create, rank, promote, invalidate, or authorize any zone/trade.
    """
    if a is None:
        return "protocol=1\nanalysis_id=\nzone_count=0\nactive_thesis_locked=0\n"

    policy = getattr(a, "execution_policy", {}) or {}
    if not isinstance(policy, dict):
        policy = {}
    thesis = policy.get("active_thesis", {})
    if not isinstance(thesis, dict):
        thesis = {}

    thesis_locked = bool(thesis.get("locked", False))
    owner_zone_id = _value(thesis.get("owner_zone_id"))
    owner_direction = _value(thesis.get("direction"))

    records = _primary_records(a, owner_zone_id, thesis_locked)
    primary_ids = {r["id"] for r in records}
    for reserve in _secondary_records(policy):
        # Reserve ids are synthetic, but guard against accidental duplicate geometry labels.
        if reserve["id"] not in primary_ids:
            records.append(reserve)

    # Maximum intended public map is 2 primaries + 2 reserves.
    records = records[:4]

    lines = [
        "protocol=1",
        f"analysis_id={_value(getattr(a, 'analysis_id', ''))}",
        f"generated_at={_int(getattr(a, 'generated_at', 0))}",
        f"zone_count={len(records)}",
        f"active_thesis_locked={1 if thesis_locked else 0}",
        f"active_thesis_direction={owner_direction}",
        f"active_thesis_owner_zone_id={owner_zone_id}",
    ]

    for idx, rec in enumerate(records, start=1):
        p = f"zone{idx}_"
        lines.extend(
            [
                f"{p}id={_value(rec.get('id'))}",
                f"{p}role={_value(rec.get('role'))}",
                f"{p}direction={_value(rec.get('direction'))}",
                f"{p}state={_value(rec.get('state'))}",
                f"{p}grade={_value(rec.get('grade'))}",
                f"{p}source_tf={_value(rec.get('source_tf'))}",
                f"{p}source_ts={_int(rec.get('source_ts'))}",
                f"{p}touches={_int(rec.get('touches'))}",
                f"{p}zone_low={_num(rec.get('zone_low'))}",
                f"{p}zone_high={_num(rec.get('zone_high'))}",
                f"{p}core_low={_num(rec.get('core_low'))}",
                f"{p}core_high={_num(rec.get('core_high'))}",
                f"{p}execution_authority={1 if rec.get('execution_authority') else 0}",
                f"{p}active_thesis={1 if rec.get('active_thesis') else 0}",
            ]
        )

    return "\n".join(lines) + "\n"
