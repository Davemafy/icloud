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


def _bool01(v: Any) -> str:
    return "1" if bool(v) else "0"


def _readiness(core_method: Any, fallback: Any = "") -> str:
    text = _value(core_method)
    if text:
        return text.split("|", 1)[0]
    return _value(fallback)


def _zone_note_int(zone: Any, prefix: str, default: int = 0) -> int:
    for note in list(getattr(zone, "notes", []) or []):
        text = str(note)
        if not text.startswith(prefix):
            continue
        try:
            return int(float(text.split(":", 1)[1]))
        except (TypeError, ValueError, IndexError):
            return default
    return default


def _effective_thesis_targets(thesis: dict[str, Any]) -> list[float]:
    direction = _value(thesis.get("direction")).upper()
    try:
        cap = float(thesis.get("ownership_objective_cap") or 0.0)
    except (TypeError, ValueError):
        cap = 0.0
    values: list[float] = []
    for key in ("target1", "target2", "target3"):
        try:
            target = float(thesis.get(key) or 0.0)
        except (TypeError, ValueError):
            target = 0.0
        if target <= 0:
            continue
        if cap > 0 and direction == "BUY" and target > cap + 1e-9:
            continue
        if cap > 0 and direction == "SELL" and target < cap - 1e-9:
            continue
        values.append(target)
    if cap > 0 and not any(abs(x - cap) <= 1e-9 for x in values):
        values.append(cap)
    try:
        anchor_price = float(thesis.get("ownership_anchor_price") or 0.0)
    except (TypeError, ValueError):
        anchor_price = 0.0
    values.sort(key=lambda price: abs(price - anchor_price) if anchor_price > 0 else price)
    return (values + [0.0, 0.0, 0.0])[:3]


def _next_objective(thesis: dict[str, Any]) -> float:
    """Return the next still-open frozen owner objective.

    Target-hit timestamps are lifecycle truth and outrank a stale/partial best-price
    snapshot. best_price remains a compatibility fallback for historical owners that
    predate explicit hit timestamps.
    """
    direction = _value(thesis.get("direction")).upper()
    try:
        best = float(thesis.get("best_price") or 0.0)
    except (TypeError, ValueError):
        best = 0.0

    next_frozen = 0.0
    for idx, key in enumerate(("target1", "target2", "target3"), start=1):
        try:
            target = float(thesis.get(key) or 0.0)
        except (TypeError, ValueError):
            target = 0.0
        if target <= 0:
            continue

        try:
            hit_at = int(thesis.get(f"target{idx}_hit_at") or 0)
        except (TypeError, ValueError):
            hit_at = 0

        reached_by_price = bool(
            best > 0
            and (
                (direction == "SELL" and best <= target)
                or (direction == "BUY" and best >= target)
            )
        )
        if hit_at > 0 or reached_by_price:
            continue

        next_frozen = target
        break

    try:
        cap = float(thesis.get("ownership_objective_cap") or 0.0)
    except (TypeError, ValueError):
        cap = 0.0
    cap_reached = bool(int(thesis.get("ownership_objective_cap_reached_at") or 0))

    if cap > 0 and not cap_reached:
        if next_frozen <= 0:
            return cap
        if direction == "BUY" and cap < next_frozen:
            return cap
        if direction == "SELL" and cap > next_frozen:
            return cap
    return next_frozen


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
                "published_at": int(raw.get("geometry_published_at") or 0),
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


def _wrong_side_for_live_price(rec: dict[str, Any], current_mid: float | None) -> bool:
    """Visual truth only: do not paint an alert zone on the wrong side of live price.

    BUY demand belongs below/at current price; SELL supply belongs above/at current
    price. Active thesis ownership is lifecycle truth and is never hidden here.
    """
    if current_mid is None or bool(rec.get("active_thesis")):
        return False
    try:
        mid = float(current_mid)
        low = min(float(rec.get("zone_low") or 0.0), float(rec.get("zone_high") or 0.0))
        high = max(float(rec.get("zone_low") or 0.0), float(rec.get("zone_high") or 0.0))
    except (TypeError, ValueError):
        return False
    direction = _value(rec.get("direction")).upper()
    if direction == "BUY":
        return low > mid
    if direction == "SELL":
        return high < mid
    return False


def _flip_context_records(policy: dict[str, Any], generated_at: int) -> list[dict[str, Any]]:
    """Render accepted-invalidated geometry as opposite-side context only.

    The original zone has no execution authority after accepted M15 invalidation.
    Its exact geometry is still useful as breaker/flip context, so expose it to
    MT5 as an outline-only RESERVE record in the *flip* direction. This is visual
    lifecycle truth only and can never restore original-zone authority.
    """
    public = policy.get("public_zone_map", {}) if isinstance(policy, dict) else {}
    rejected = public.get("rejected_diagnostics", {}) if isinstance(public, dict) else {}
    if not isinstance(rejected, dict):
        return []

    out: list[dict[str, Any]] = []
    accepted_codes = {"M15_ACCEPTED_INVALIDATION", "HISTORICAL_M15_ACCEPTED_INVALIDATION"}
    for side in ("sell", "buy"):
        block = rejected.get(side, {})
        if not isinstance(block, dict):
            continue
        diag = block.get("strongest_rejected")
        if not isinstance(diag, dict):
            continue
        code = _value(diag.get("rejection_code")).upper()
        if code not in accepted_codes:
            continue

        original = _value(diag.get("direction") or side).upper()
        if original not in {"BUY", "SELL"}:
            continue
        flip = "SELL" if original == "BUY" else "BUY"

        try:
            zone_low = float(diag.get("zone_low") or 0.0)
            zone_high = float(diag.get("zone_high") or 0.0)
            core_low = float(diag.get("core_low") or 0.0)
            core_high = float(diag.get("core_high") or 0.0)
        except (TypeError, ValueError):
            continue
        if zone_low <= 0 or zone_high <= zone_low or core_low <= 0 or core_high <= core_low:
            continue

        source_tf = _value(diag.get("source_tf"))
        source_ts = _int(diag.get("source_ts"))
        invalidated_at = _int(diag.get("mitigation_invalidated_at"))
        grade = _value(diag.get("current_execution_grade") or diag.get("structural_grade") or diag.get("grade"))
        touches = _int(diag.get("touches"))
        safe_tf = source_tf.replace(">", "")
        zid = f"FLIPCTX_{safe_tf}_{original}_{source_ts or generated_at}"
        out.append(
            {
                "id": zid,
                "role": "RESERVE",
                "direction": flip,
                "state": "FLIP_CONTEXT",
                "grade": grade,
                "source_tf": source_tf,
                "source_ts": source_ts,
                "published_at": invalidated_at or generated_at,
                "touches": touches,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "core_low": core_low,
                "core_high": core_high,
                "execution_authority": False,
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
        readiness = _readiness(getattr(z, "core_method", ""), getattr(z, "state", ""))
        # Keep three independent presentation truths separate:
        # map selection, current M1 handoff, and acquired thesis ownership.
        # Once a sticky thesis owns this source, the chart must not keep calling
        # the old macro handoff "M1 HANDOFF ACTIVE" after price has travelled
        # away. Ownership remains valid, but every new entry still requires a
        # fresh same-direction M1 confirmation.
        display_state = (
            "THESIS OWNER / FRESH M1 REQUIRED"
            if active_thesis
            else readiness
        )
        m1_handoff = bool(
            not thesis_locked
            and bool(selected_zone_id)
            and zid == selected_zone_id
            and readiness == "M1_READY"
        )
        authority = active_thesis
        out.append(
            {
                "id": zid,
                "role": "PRIMARY",
                "direction": _value(getattr(z, "original_direction", "")),
                "state": display_state,
                "grade": _value(getattr(z, "grade", "")),
                "source_tf": _value(getattr(z, "source_tf", "")),
                "source_ts": int(getattr(z, "source_ts", 0) or 0),
                "published_at": _zone_note_int(
                    z,
                    "geometry_published_at:",
                    int(getattr(a, "generated_at", 0) or 0),
                ),
                "touches": int(getattr(z, "touch_count", 0) or 0),
                "zone_low": getattr(z, "zone_low", 0.0),
                "zone_high": getattr(z, "zone_high", 0.0),
                "core_low": getattr(z, "core_low", 0.0),
                "core_high": getattr(z, "core_high", 0.0),
                "execution_authority": authority,
                "m1_handoff": m1_handoff,
                "active_thesis": active_thesis,
            }
        )
    return out


def mt5_zone_render_text(a: Any, current_mid: float | None = None) -> str:
    """Flat render contract for MT5 chart shading and execution-ownership labels.

    Visual-only feed: it exposes the already-qualified primary/reserve geometry
    plus read-only ownership state. It does not create, rank, promote,
    invalidate, or authorize any zone/trade.
    """
    if a is None:
        return (
            "protocol=2\n"
            "analysis_id=\n"
            "selected_zone_id=\n"
            "zone_count=0\n"
            "active_thesis_locked=0\n"
            "active_thesis_direction=\n"
            "active_thesis_status=\n"
            "active_thesis_owner_zone_id=\n"
            "active_thesis_owner_zone_present=0\n"
            "active_thesis_opposite_execution_blocked=0\n"
            "active_thesis_no_chase=0\n"
            "active_thesis_next_objective=0.00000\n"
        )

    policy = getattr(a, "execution_policy", {}) or {}
    if not isinstance(policy, dict):
        policy = {}
    thesis = policy.get("active_thesis", {})
    if not isinstance(thesis, dict):
        thesis = {}

    thesis_locked = bool(thesis.get("locked", False))
    owner_zone_id = _value(thesis.get("owner_zone_id"))
    owner_direction = _value(thesis.get("direction"))
    owner_status = _value(thesis.get("status"))
    selected_zone_id = _value(getattr(a, "selected_zone_id", ""))

    records = _primary_records(a, owner_zone_id, thesis_locked)
    generated_at = int(getattr(a, "generated_at", 0) or 0)

    # Preserve accepted-invalidated geometry as breaker/flip context. It is
    # deliberately inserted before normal reserves so a useful flip reference
    # is not clipped by the four-zone visual cap.
    records.extend(_flip_context_records(policy, generated_at))

    primary_ids = {r["id"] for r in records}
    for reserve in _secondary_records(policy):
        if int(reserve.get("published_at") or 0) <= 0:
            reserve["published_at"] = generated_at
        # Reserve ids are synthetic, but guard against accidental duplicate geometry labels.
        if reserve["id"] not in primary_ids:
            records.append(reserve)

    # The cloud analysis is a snapshot, but chart rendering is live. A stale
    # context BUY must not remain painted above current price, and a stale context
    # SELL must not remain painted below it. This is presentation-only; the
    # execution plan keeps failed geometry long enough for accepted-invalidation
    # / flip monitoring.
    hidden_wrong_side = [r["id"] for r in records if _wrong_side_for_live_price(r, current_mid)]
    records = [r for r in records if not _wrong_side_for_live_price(r, current_mid)]

    # Maximum intended public map is 2 primaries + 2 reserves.
    records = records[:4]

    effective_targets = _effective_thesis_targets(thesis)

    lines = [
        "protocol=2",
        f"analysis_id={_value(getattr(a, 'analysis_id', ''))}",
        f"generated_at={_int(getattr(a, 'generated_at', 0))}",
        f"selected_zone_id={selected_zone_id}",
        f"live_mid={_num(current_mid) if current_mid is not None else '0.00000'}",
        f"wrong_side_hidden_count={len(hidden_wrong_side)}",
        f"wrong_side_hidden_ids={','.join(hidden_wrong_side)}",
        f"zone_count={len(records)}",
        f"active_thesis_locked={_bool01(thesis_locked)}",
        f"active_thesis_direction={owner_direction}",
        f"active_thesis_status={owner_status}",
        f"active_thesis_owner_zone_id={owner_zone_id}",
        f"active_thesis_owner_zone_present={_bool01(thesis.get('owner_zone_present', bool(owner_zone_id)))}",
        f"active_thesis_opposite_execution_blocked={_bool01(thesis.get('opposite_execution_blocked', False))}",
        f"active_thesis_no_chase={_bool01(thesis.get('no_chase', False))}",
        f"active_thesis_fresh_m1_confirmation_required={_bool01(thesis.get('fresh_m1_confirmation_required', False))}",
        f"active_thesis_best_price={_num(thesis.get('best_price', 0.0))}",
        f"active_thesis_target1={_num(effective_targets[0])}",
        f"active_thesis_target2={_num(effective_targets[1])}",
        f"active_thesis_target3={_num(effective_targets[2])}",
        f"active_thesis_next_objective={_num(_next_objective(thesis))}",
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
                f"{p}published_at={_int(rec.get('published_at'))}",
                f"{p}touches={_int(rec.get('touches'))}",
                f"{p}zone_low={_num(rec.get('zone_low'))}",
                f"{p}zone_high={_num(rec.get('zone_high'))}",
                f"{p}core_low={_num(rec.get('core_low'))}",
                f"{p}core_high={_num(rec.get('core_high'))}",
                f"{p}execution_authority={_bool01(rec.get('execution_authority'))}",
                f"{p}m1_handoff={_bool01(rec.get('m1_handoff'))}",
                f"{p}active_thesis={_bool01(rec.get('active_thesis'))}",
            ]
        )

    return "\n".join(lines) + "\n"
