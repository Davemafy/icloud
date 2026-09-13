from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
from datetime import datetime, timezone
from typing import Any

from .config import SETTINGS
from .db import audit, connect
from .engine import (
    _bias,
    _dxy,
    _zone,
    atr,
    build_candidates,
    evaluate_zone_state,
    liquidity_map,
    structure_bias,
)
from .execution_models import classify_regime
from .models import Analysis, Direction, MLCandidateTelemetry, MarketSnapshot, Zone, ZoneState
from .timezones import safe_zoneinfo

FEATURE_VERSION = "V6_4_MLF1"
DATA_CONTRACT = "V6_4_ML_DATA_FOUNDATION_SHADOW_ONLY"
_ml_lock = threading.Lock()


def init_ml_schema() -> None:
    with _ml_lock, connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS ml_candidates(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT UNIQUE NOT NULL,
                feature_cutoff_ts INTEGER NOT NULL,
                source TEXT NOT NULL,
                analysis_id TEXT,
                zone_id TEXT,
                model TEXT NOT NULL,
                direction TEXT NOT NULL,
                eligible INTEGER NOT NULL DEFAULT 0,
                rejection_reasons TEXT NOT NULL DEFAULT '[]',
                entry_price REAL NOT NULL DEFAULT 0,
                stop_price REAL NOT NULL DEFAULT 0,
                target1 REAL NOT NULL DEFAULT 0,
                target2 REAL NOT NULL DEFAULT 0,
                target3 REAL NOT NULL DEFAULT 0,
                atr_ref REAL NOT NULL DEFAULT 0,
                feature_version TEXT NOT NULL,
                features TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ml_outcomes(
                candidate_id TEXT PRIMARY KEY,
                last_mark_ts INTEGER NOT NULL DEFAULT 0,
                last_bar_ts INTEGER NOT NULL DEFAULT 0,
                max_favorable REAL NOT NULL DEFAULT 0,
                max_adverse REAL NOT NULL DEFAULT 0,
                max_favorable_r REAL NOT NULL DEFAULT 0,
                max_adverse_r REAL NOT NULL DEFAULT 0,
                tp1_ts INTEGER,
                tp2_ts INTEGER,
                tp3_ts INTEGER,
                sl_ts INTEGER,
                first_barrier TEXT NOT NULL DEFAULT '',
                horizon_15m REAL,
                horizon_15m_atr REAL,
                horizon_60m REAL,
                horizon_60m_atr REAL,
                horizon_240m REAL,
                horizon_240m_atr REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                result TEXT NOT NULL DEFAULT '',
                resolved_at INTEGER,
                labels TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_ml_candidates_ts ON ml_candidates(feature_cutoff_ts);
            CREATE INDEX IF NOT EXISTS idx_ml_candidates_model ON ml_candidates(model, eligible);
            CREATE INDEX IF NOT EXISTS idx_ml_candidates_analysis ON ml_candidates(analysis_id, zone_id);
            CREATE INDEX IF NOT EXISTS idx_ml_outcomes_status ON ml_outcomes(status, last_mark_ts);
            """
        )


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def _candidate_key(*parts: Any) -> str:
    raw = "|".join(str(x) for x in parts)
    return "ML_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]


_FORBIDDEN_FEATURE_TOKENS = (
    "outcome",
    "future_",
    "label",
    "realized",
    "final_",
    "closed_profit",
    "mfe",
    "mae",
    "tp_hit",
    "sl_hit",
)


def _sanitize_features(value: Any) -> Any:
    """Remove obvious post-event fields from feature payloads.

    Features are frozen at candidate time. Labels and realized results belong only
    in ml_outcomes. This is a guardrail against accidental future leakage from MT5.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            low = key.lower()
            if any(token in low for token in _FORBIDDEN_FEATURE_TOKENS):
                continue
            out[key] = _sanitize_features(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_sanitize_features(x) for x in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _save_candidate(record: dict[str, Any]) -> bool:
    now = int(datetime.now(timezone.utc).timestamp())
    features = _sanitize_features(record.get("features", {}))
    metadata = record.get("metadata", {})
    with _ml_lock, connect() as db:
        cur = db.execute(
            """
            INSERT OR IGNORE INTO ml_candidates(
                candidate_id, feature_cutoff_ts, source, analysis_id, zone_id,
                model, direction, eligible, rejection_reasons,
                entry_price, stop_price, target1, target2, target3, atr_ref,
                feature_version, features, metadata, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["candidate_id"],
                int(record["feature_cutoff_ts"]),
                str(record.get("source", "UNKNOWN")),
                str(record.get("analysis_id", "")),
                str(record.get("zone_id", "")),
                str(record.get("model", "UNKNOWN")),
                str(record.get("direction", "NEUTRAL")),
                int(bool(record.get("eligible", False))),
                _json(record.get("rejection_reasons", [])),
                float(record.get("entry_price", 0.0) or 0.0),
                float(record.get("stop_price", 0.0) or 0.0),
                float(record.get("target1", 0.0) or 0.0),
                float(record.get("target2", 0.0) or 0.0),
                float(record.get("target3", 0.0) or 0.0),
                float(record.get("atr_ref", 0.0) or 0.0),
                str(record.get("feature_version", FEATURE_VERSION)),
                _json(features),
                _json(metadata),
                now,
            ),
        )
        inserted = cur.rowcount > 0
        if inserted:
            db.execute(
                "INSERT OR IGNORE INTO ml_outcomes(candidate_id,last_mark_ts,last_bar_ts) VALUES(?,?,?)",
                (record["candidate_id"], int(record["feature_cutoff_ts"]), int(record["feature_cutoff_ts"])),
            )
    return inserted


def _time_features(ts: int) -> dict[str, Any]:
    utc = datetime.fromtimestamp(ts, timezone.utc)
    local = utc.astimezone(safe_zoneinfo(SETTINGS.timezone_name))
    return {
        "utc_hour": utc.hour,
        "utc_minute": utc.minute,
        "utc_weekday": utc.weekday(),
        "local_hour": local.hour,
        "local_minute": local.minute,
        "local_weekday": local.weekday(),
        "is_london_window": 1 if 6 <= utc.hour < 11 else 0,
        "is_new_york_window": 1 if 12 <= utc.hour < 18 else 0,
    }


def _news_features(s: MarketSnapshot) -> dict[str, Any]:
    high = [n for n in s.news if n.currency.upper() == "USD" and n.impact.upper() == "HIGH"]
    if not high:
        return {"nearest_usd_high_minutes": 9999.0, "usd_high_within_30m": 0, "usd_high_within_60m": 0}
    signed = [(n.ts - s.sent_at) / 60.0 for n in high]
    nearest = min(signed, key=lambda x: abs(x))
    return {
        "nearest_usd_high_minutes": round(nearest, 2),
        "usd_high_within_30m": int(abs(nearest) <= 30),
        "usd_high_within_60m": int(abs(nearest) <= 60),
    }


def _base_features(s: MarketSnapshot, a: Analysis, reason: str) -> dict[str, Any]:
    regime = classify_regime(s)
    policy = a.execution_policy if isinstance(a.execution_policy, dict) else {}
    multi = policy.get("multi_model", {}) if isinstance(policy, dict) else {}
    models = multi.get("models", {}) if isinstance(multi, dict) else {}
    h4_atr = atr(s.xau_h4)
    d1_atr = atr(s.xau_d1)
    m15_atr = s.atr_m15 or atr(s.xau_m15)
    h1_atr = s.atr_h1 or atr(s.xau_h1)
    out: dict[str, Any] = {
        "feature_cutoff_ts": s.sent_at,
        "analysis_reason": reason,
        "snapshot_kind": s.kind,
        "snapshot_complete": int(s.complete()),
        "mid": round(s.mid, 6),
        "spread_points": round(s.spread_points, 3),
        "point": s.point,
        "atr_m15": round(m15_atr, 6),
        "atr_h1": round(h1_atr, 6),
        "atr_h4": round(h4_atr, 6),
        "atr_d1": round(d1_atr, 6),
        "atr_m15_h1_ratio": round(m15_atr / h1_atr, 5) if h1_atr > 0 else 0.0,
        "xau_d1_bias": structure_bias(s.xau_d1).value,
        "xau_h4_bias": structure_bias(s.xau_h4).value,
        "xau_h1_bias": structure_bias(s.xau_h1).value,
        "dxy_d1_bias": structure_bias(s.dxy_d1).value,
        "dxy_h4_bias": structure_bias(s.dxy_h4).value,
        "dxy_h1_bias": structure_bias(s.dxy_h1).value,
        "overall_bias": a.overall_bias.value,
        "dxy_consensus": _dxy(s).value,
        "analysis_approved": int(a.approved),
        "ai_approved": int(a.ai_approved),
        "ai_provider": a.ai_provider,
        "regime": regime.get("name", "UNKNOWN"),
        "regime_direction": regime.get("direction", "NEUTRAL"),
        "regime_confidence": regime.get("confidence", 0.0),
        "regime_volatility_ratio": regime.get("volatility_ratio", 0.0),
        "regime_efficiency": regime.get("efficiency", 0.0),
        "regime_range_expansion": regime.get("range_expansion", 0.0),
        "regime_vwap_proxy": regime.get("vwap_proxy", 0.0),
        "regime_vwap_distance_atr": regime.get("vwap_distance_atr", 0.0),
        "model_ict_sniper_allowed": int(bool(models.get("ict_sniper", False))),
        "model_ict_reentry_allowed": int(bool(models.get("ict_deep_reentry", False))),
        "model_momentum_allowed": int(bool(models.get("momentum_pullback", False))),
        "model_vwap_allowed": int(bool(models.get("vwap_proxy_reclaim", False))),
        "model_orb_allowed": int(bool(models.get("opening_range_retest", False))),
        "model_flip_allowed": int(bool(models.get("accepted_zone_flip", False))),
    }
    out.update(_time_features(s.sent_at))
    out.update(_news_features(s))
    return out


def _zone_features(base: dict[str, Any], z: Zone, s: MarketSnapshot, selected: bool) -> dict[str, Any]:
    m15_atr = max(float(base.get("atr_m15", 0.0) or 0.0), 1e-9)
    mid = s.mid
    zone_mid = (z.zone_low + z.zone_high) / 2.0
    near = min(abs(mid - z.zone_low), abs(mid - z.zone_high))
    conf = set(z.confluences)
    return {
        **base,
        "selected_zone": int(selected),
        "zone_original_direction": z.original_direction.value,
        "zone_flip_direction": z.flip_direction.value,
        "zone_setup_type": z.setup_type,
        "zone_source_tf": z.source_tf,
        "zone_grade": z.grade.value,
        "zone_state": z.state.value,
        "zone_core_method": z.core_method,
        "zone_location_score": z.location_score,
        "zone_touch_count": z.touch_count,
        "zone_confluence_count": z.independent_confluence_count,
        "zone_clear_run": z.clear_run,
        "zone_countertrend": int(z.countertrend),
        "zone_dxy_support": z.dxy_support,
        "zone_width_atr": round((z.zone_high - z.zone_low) / m15_atr, 5),
        "zone_mid_distance_atr": round(abs(mid - zone_mid) / m15_atr, 5),
        "zone_near_distance_atr": round(near / m15_atr, 5),
        "conf_htf_overlap": int("HTF_OVERLAP" in conf),
        "conf_historical_fvg": int("HISTORICAL_DISPLACEMENT_FVG" in conf),
        "conf_displacement": int("INSTITUTIONAL_DISPLACEMENT" in conf),
        "conf_premium_discount": int("PREMIUM_DISCOUNT_EXTREMITY" in conf),
        "conf_external_liquidity": int("EXTERNAL_LIQUIDITY_ADJACENCY" in conf),
    }


def _original_rejections(a: Analysis, z: Zone) -> list[str]:
    out: list[str] = []
    if z.grade.value not in {"A+", "A"}:
        out.append("GRADE_NOT_EXECUTABLE")
    if z.state == ZoneState.RETIRED:
        out.append("ZONE_RETIRED")
    if not a.approved:
        out.append("ANALYSIS_NOT_APPROVED")
    if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and not a.ai_approved:
        out.append("AI_NOT_APPROVED")
    return out


def capture_cloud_candidates(a: Analysis, s: MarketSnapshot, reason: str) -> int:
    """Freeze pre-trade cloud features for both original and flip hypotheses.

    Rejected candidates are intentionally stored. That prevents the future ML model
    from learning only from trades that the existing rules already chose.
    """
    if not SETTINGS.ml_data_enabled:
        return 0
    init_ml_schema()
    liq = liquidity_map(s)
    bias = _bias(s)
    zones = [_zone(c, s, liq, bias, i + 1) for i, c in enumerate(build_candidates(s))]
    for z in zones:
        z.state = evaluate_zone_state(z, s.xau_m15, s.atr_m15)
    zones.sort(key=lambda z: (abs(((z.zone_low + z.zone_high) / 2.0) - s.mid), -z.location_score))
    zones = zones[: max(1, SETTINGS.ml_max_cloud_zones_per_analysis)]
    base = _base_features(s, a, reason)
    atr_ref = float(base.get("atr_m15", 0.0) or 0.0)
    inserted = 0

    for z in zones:
        selected = z.zone_id == a.selected_zone_id
        zf = _zone_features(base, z, s, selected)
        original_reject = _original_rejections(a, z)
        original_id = _candidate_key(
            "CLOUD", s.sent_at, z.source_ts, z.source_tf, z.original_direction.value,
            z.core_low, z.core_high, "ORIGINAL"
        )
        inserted += int(_save_candidate({
            "candidate_id": original_id,
            "feature_cutoff_ts": s.sent_at,
            "source": "CLOUD_ZONE",
            "analysis_id": a.analysis_id,
            "zone_id": z.zone_id,
            "model": "ZONE_ORIGINAL_THESIS",
            "direction": z.original_direction.value,
            "eligible": not original_reject,
            "rejection_reasons": original_reject,
            "entry_price": s.mid,
            "stop_price": z.invalidation_level,
            "target1": z.original_target1,
            "target2": z.original_target2,
            "target3": z.original_target3,
            "atr_ref": atr_ref,
            "features": {**zf, "hypothesis_branch": "ORIGINAL"},
            "metadata": {"analysis_reason": reason, "feature_freeze": "CANDIDATE_TIME_ONLY"},
        }))

        flip_reject = ["FLIP_ACCEPTANCE_NOT_CONFIRMED"] if z.state != ZoneState.FAILED_FLIP_CANDIDATE else []
        if not a.approved:
            flip_reject.append("ANALYSIS_NOT_APPROVED")
        if SETTINGS.require_ai_for_execution and SETTINGS.ai_enabled and not a.ai_approved:
            flip_reject.append("AI_NOT_APPROVED")
        flip_id = _candidate_key(
            "CLOUD", s.sent_at, z.source_ts, z.source_tf, z.flip_direction.value,
            z.core_low, z.core_high, "FLIP"
        )
        inserted += int(_save_candidate({
            "candidate_id": flip_id,
            "feature_cutoff_ts": s.sent_at,
            "source": "CLOUD_ZONE",
            "analysis_id": a.analysis_id,
            "zone_id": z.zone_id,
            "model": "ZONE_FLIP_HYPOTHESIS",
            "direction": z.flip_direction.value,
            "eligible": not flip_reject,
            "rejection_reasons": flip_reject,
            "entry_price": s.mid,
            "stop_price": 0.0,
            "target1": z.flip_target1,
            "target2": z.flip_target2,
            "target3": z.flip_target3,
            "atr_ref": atr_ref,
            "features": {**zf, "hypothesis_branch": "FLIP"},
            "metadata": {"analysis_reason": reason, "feature_freeze": "CANDIDATE_TIME_ONLY"},
        }))

    audit(
        int(datetime.now(timezone.utc).timestamp()),
        "ml.cloud.capture",
        f"analysis_id={a.analysis_id} reason={reason} inserted={inserted} zones={len(zones)} feature_version={FEATURE_VERSION}",
    )
    return inserted


def ingest_execution_candidate(t: MLCandidateTelemetry) -> str:
    if not SETTINGS.ml_data_enabled:
        return "DISABLED"
    init_ml_schema()
    cid = t.candidate_id.strip() if t.candidate_id else ""
    if not cid:
        cid = _candidate_key(
            "MT5", t.ts, t.analysis_id, t.zone_id, t.model, t.direction.value,
            round(t.entry_price, 5), round(t.stop_price, 5)
        )
    features = {
        **_time_features(t.ts),
        "feature_cutoff_ts": t.ts,
        "regime": t.regime,
        "mt5_model": t.model,
        "mt5_direction": t.direction.value,
        **_sanitize_features(t.features),
    }
    inserted = _save_candidate({
        "candidate_id": cid,
        "feature_cutoff_ts": t.ts,
        "source": t.source or "MT5_EXECUTION",
        "analysis_id": t.analysis_id,
        "zone_id": t.zone_id,
        "model": t.model,
        "direction": t.direction.value,
        "eligible": t.eligible,
        "rejection_reasons": t.rejection_reasons,
        "entry_price": t.entry_price,
        "stop_price": t.stop_price,
        "target1": t.target1,
        "target2": t.target2,
        "target3": t.target3,
        "atr_ref": t.atr,
        "features": features,
        "metadata": {"feature_freeze": "CANDIDATE_TIME_ONLY", "source_version": t.source_version},
    })
    audit(t.ts, "ml.execution.capture", f"candidate_id={cid} model={t.model} eligible={t.eligible} inserted={inserted}")
    return cid


def _directional_move(direction: str, entry: float, price: float) -> float:
    return (price - entry) if direction == Direction.BUY.value else (entry - price)


def _bar_excursions(direction: str, entry: float, high: float, low: float) -> tuple[float, float]:
    if direction == Direction.BUY.value:
        return max(0.0, high - entry), max(0.0, entry - low)
    return max(0.0, entry - low), max(0.0, high - entry)


def _barrier_hits(direction: str, high: float, low: float, stop: float, targets: list[float]) -> tuple[bool, list[bool]]:
    if direction == Direction.BUY.value:
        sl = stop > 0 and low <= stop
        t = [x > 0 and high >= x for x in targets]
    else:
        sl = stop > 0 and high >= stop
        t = [x > 0 and low <= x for x in targets]
    return sl, t


def mark_ml_outcomes(s: MarketSnapshot) -> int:
    """Update labels using only market data that arrived after each feature cutoff."""
    if not SETTINGS.ml_data_enabled:
        return 0
    init_ml_schema()
    now = s.sent_at
    with _ml_lock, connect() as db:
        rows = db.execute(
            """
            SELECT c.*, o.last_mark_ts,o.last_bar_ts,o.max_favorable,o.max_adverse,
                   o.max_favorable_r,o.max_adverse_r,o.tp1_ts,o.tp2_ts,o.tp3_ts,o.sl_ts,
                   o.first_barrier,o.horizon_15m,o.horizon_15m_atr,o.horizon_60m,o.horizon_60m_atr,
                   o.horizon_240m,o.horizon_240m_atr,o.status,o.result,o.resolved_at,o.labels
            FROM ml_candidates c JOIN ml_outcomes o ON o.candidate_id=c.candidate_id
            WHERE o.status='OPEN' AND c.feature_cutoff_ts < ?
            ORDER BY c.id ASC LIMIT ?
            """,
            (now, max(100, SETTINGS.ml_max_open_candidates_per_mark)),
        ).fetchall()

        if not rows:
            return 0

        bars = sorted((b for b in s.xau_m15 if b.ts <= now), key=lambda b: b.ts)
        changed = 0
        for r in rows:
            entry = float(r["entry_price"] or 0.0)
            if entry <= 0:
                continue
            direction = str(r["direction"])
            atr_ref = float(r["atr_ref"] or 0.0)
            risk_dist = abs(entry - float(r["stop_price"] or 0.0)) if float(r["stop_price"] or 0.0) > 0 else 0.0
            max_fav = float(r["max_favorable"] or 0.0)
            max_adv = float(r["max_adverse"] or 0.0)
            max_fav_r = float(r["max_favorable_r"] or 0.0)
            max_adv_r = float(r["max_adverse_r"] or 0.0)
            tp_ts = [r["tp1_ts"], r["tp2_ts"], r["tp3_ts"]]
            sl_ts = r["sl_ts"]
            first_barrier = str(r["first_barrier"] or "")
            last_bar_ts = int(r["last_bar_ts"] or r["feature_cutoff_ts"])
            targets = [float(r["target1"] or 0.0), float(r["target2"] or 0.0), float(r["target3"] or 0.0)]

            for b in bars:
                if b.ts <= max(int(r["feature_cutoff_ts"]), last_bar_ts):
                    continue
                fav, adv = _bar_excursions(direction, entry, b.high, b.low)
                max_fav, max_adv = max(max_fav, fav), max(max_adv, adv)
                if risk_dist > 0:
                    max_fav_r, max_adv_r = max(max_fav_r, fav / risk_dist), max(max_adv_r, adv / risk_dist)
                sl_hit, hits = _barrier_hits(direction, b.high, b.low, float(r["stop_price"] or 0.0), targets)
                if sl_hit and sl_ts is None:
                    sl_ts = b.ts
                for i, hit in enumerate(hits):
                    if hit and tp_ts[i] is None:
                        tp_ts[i] = b.ts
                if not first_barrier:
                    if sl_hit and hits[0]:
                        first_barrier = "AMBIGUOUS_SAME_M15_BAR"
                    elif hits[0]:
                        first_barrier = "TP1"
                    elif sl_hit:
                        first_barrier = "SL"
                last_bar_ts = max(last_bar_ts, b.ts)

            current_move = _directional_move(direction, entry, s.mid)
            max_fav = max(max_fav, max(0.0, current_move))
            max_adv = max(max_adv, max(0.0, -current_move))
            if risk_dist > 0:
                max_fav_r = max(max_fav_r, max(0.0, current_move) / risk_dist)
                max_adv_r = max(max_adv_r, max(0.0, -current_move) / risk_dist)

            elapsed = now - int(r["feature_cutoff_ts"])
            horizons: dict[int, tuple[Any, Any]] = {
                15: (r["horizon_15m"], r["horizon_15m_atr"]),
                60: (r["horizon_60m"], r["horizon_60m_atr"]),
                240: (r["horizon_240m"], r["horizon_240m_atr"]),
            }
            for minutes, pair in list(horizons.items()):
                raw, norm = pair
                if raw is None and elapsed >= minutes * 60:
                    raw = current_move
                    norm = current_move / atr_ref if atr_ref > 0 else None
                horizons[minutes] = (raw, norm)

            expired = elapsed >= max(1, SETTINGS.ml_max_label_hours) * 3600
            status = "RESOLVED" if expired else "OPEN"
            result = str(r["result"] or "")
            resolved_at = r["resolved_at"]
            if expired:
                if first_barrier == "TP1":
                    result = "TP1_BEFORE_SL"
                elif first_barrier == "SL":
                    result = "SL_BEFORE_TP1"
                elif first_barrier.startswith("AMBIGUOUS"):
                    result = "AMBIGUOUS_FIRST_BARRIER"
                else:
                    result = "EXPIRED_NO_FIRST_BARRIER"
                resolved_at = now

            labels = {
                "tp1_before_sl": 1 if first_barrier == "TP1" else 0 if first_barrier == "SL" else None,
                "first_barrier": first_barrier or None,
                "eligible_at_cutoff": int(r["eligible"]),
                "feature_cutoff_ts": int(r["feature_cutoff_ts"]),
                "label_updated_at": now,
            }
            db.execute(
                """
                UPDATE ml_outcomes SET
                    last_mark_ts=?,last_bar_ts=?,max_favorable=?,max_adverse=?,
                    max_favorable_r=?,max_adverse_r=?,tp1_ts=?,tp2_ts=?,tp3_ts=?,sl_ts=?,
                    first_barrier=?,horizon_15m=?,horizon_15m_atr=?,horizon_60m=?,horizon_60m_atr=?,
                    horizon_240m=?,horizon_240m_atr=?,status=?,result=?,resolved_at=?,labels=?
                WHERE candidate_id=?
                """,
                (
                    now,last_bar_ts,max_fav,max_adv,max_fav_r,max_adv_r,
                    tp_ts[0],tp_ts[1],tp_ts[2],sl_ts,first_barrier,
                    horizons[15][0],horizons[15][1],horizons[60][0],horizons[60][1],
                    horizons[240][0],horizons[240][1],status,result,resolved_at,_json(labels),r["candidate_id"],
                ),
            )
            changed += 1
    return changed


def ml_status() -> dict[str, Any]:
    if not SETTINGS.ml_data_enabled:
        return {"enabled": False, "contract": DATA_CONTRACT, "feature_version": FEATURE_VERSION}
    init_ml_schema()
    with _ml_lock, connect() as db:
        total = db.execute("SELECT COUNT(*) FROM ml_candidates").fetchone()[0]
        eligible = db.execute("SELECT COUNT(*) FROM ml_candidates WHERE eligible=1").fetchone()[0]
        open_n = db.execute("SELECT COUNT(*) FROM ml_outcomes WHERE status='OPEN'").fetchone()[0]
        resolved = db.execute("SELECT COUNT(*) FROM ml_outcomes WHERE status='RESOLVED'").fetchone()[0]
        mt5 = db.execute("SELECT COUNT(*) FROM ml_candidates WHERE source LIKE 'MT5%'").fetchone()[0]
        cloud = db.execute("SELECT COUNT(*) FROM ml_candidates WHERE source='CLOUD_ZONE'").fetchone()[0]
        last = db.execute("SELECT MAX(feature_cutoff_ts) FROM ml_candidates").fetchone()[0]
    readiness = "READY_FOR_BASELINE_EXPERIMENTS" if resolved >= SETTINGS.ml_min_resolved_for_training else "COLLECTING"
    return {
        "enabled": True,
        "mode": "SHADOW_DATA_ONLY",
        "contract": DATA_CONTRACT,
        "feature_version": FEATURE_VERSION,
        "total_candidates": total,
        "eligible_candidates": eligible,
        "cloud_zone_candidates": cloud,
        "mt5_execution_candidates": mt5,
        "open_labels": open_n,
        "resolved_labels": resolved,
        "last_candidate_ts": last,
        "training_readiness": readiness,
        "min_resolved_for_training": SETTINGS.ml_min_resolved_for_training,
        "future_leakage_guard": "FEATURES_FROZEN_AT_CANDIDATE_TIME",
    }


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}{k}__", v, out)
    elif isinstance(value, list):
        out[prefix[:-2]] = "|".join(str(x) for x in value)
    else:
        out[prefix[:-2]] = value


def export_ml_dataset_csv(limit: int | None = None) -> str:
    init_ml_schema()
    max_rows = min(max(1, int(limit or SETTINGS.ml_dataset_export_limit)), SETTINGS.ml_dataset_export_limit)
    with _ml_lock, connect() as db:
        rows = db.execute(
            """
            SELECT c.*,o.last_mark_ts,o.last_bar_ts,o.max_favorable,o.max_adverse,
                   o.max_favorable_r,o.max_adverse_r,o.tp1_ts,o.tp2_ts,o.tp3_ts,o.sl_ts,
                   o.first_barrier,o.horizon_15m,o.horizon_15m_atr,o.horizon_60m,o.horizon_60m_atr,
                   o.horizon_240m,o.horizon_240m_atr,o.status,o.result,o.resolved_at,o.labels
            FROM ml_candidates c JOIN ml_outcomes o ON o.candidate_id=c.candidate_id
            ORDER BY c.id ASC LIMIT ?
            """,
            (max_rows,),
        ).fetchall()
    items: list[dict[str, Any]] = []
    all_keys: set[str] = set()
    for row in rows:
        d = dict(row)
        features = json.loads(d.pop("features") or "{}")
        metadata = json.loads(d.pop("metadata") or "{}")
        labels = json.loads(d.pop("labels") or "{}")
        d["rejection_reasons"] = "|".join(json.loads(d.get("rejection_reasons") or "[]"))
        flat: dict[str, Any] = dict(d)
        _flatten("f__", features, flat)
        _flatten("meta__", metadata, flat)
        _flatten("label__", labels, flat)
        items.append(flat)
        all_keys.update(flat.keys())
    if not items:
        return "candidate_id,feature_cutoff_ts,source,model,direction,eligible,status,result\n"
    preferred = [
        "candidate_id","feature_cutoff_ts","source","analysis_id","zone_id","model","direction","eligible",
        "rejection_reasons","entry_price","stop_price","target1","target2","target3","atr_ref","feature_version",
        "status","result","first_barrier","max_favorable","max_adverse","max_favorable_r","max_adverse_r",
        "horizon_15m","horizon_15m_atr","horizon_60m","horizon_60m_atr","horizon_240m","horizon_240m_atr",
        "tp1_ts","tp2_ts","tp3_ts","sl_ts","resolved_at"
    ]
    fields = [x for x in preferred if x in all_keys] + sorted(all_keys - set(preferred) - {"id","created_at","last_mark_ts","last_bar_ts"})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for item in items:
        w.writerow(item)
    return out.getvalue()
