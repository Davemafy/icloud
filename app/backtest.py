from __future__ import annotations

import argparse
import asyncio
import bisect
import csv
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPLAY_CONTRACT = "MASTER_SNIPER_V659_NO_LOOKAHEAD_REPLAY_V1"
PLAN_FIELDS = [
    "epoch","analysis_id","zone_id","ea_mode","grade",
    "original_direction","flip_direction",
    "core_low","core_high","zone_low","zone_high",
    "original_target1","original_target2","original_target3","original_runner",
    "flip_target1","flip_target2","flip_target3","flip_runner",
    "min_displacement_atr","min_rr",
]
CONTRACT_FIELDS = [
    "epoch","analysis_id","zone_id","thesis_key","ea_mode","execution_authority",
    "current_grade","qualified_mitigations","risk_context","base_risk_pct",
    "original_risk_pct","flip_risk_pct","validation_initial_capital",
    "liquidity_reversal_direction","liquidity_reversal_label",
    "liquidity_reversal_price","liquidity_reversal_risk_multiplier",
    "zone_state","setup_type","core_method","contract_fingerprint",
    "execution_handoff_ts","sniper_parity_version","replay_reason",
]
TF_SECONDS = {"D1": 86400, "H4": 14400, "H1": 3600, "M15": 900, "M1": 60}
HISTORY_LIMITS = {
    "XAU_D1": 420,
    "XAU_H4": 1000,
    "XAU_H1": 1400,
    "XAU_M15": 1600,
    "DXY_D1": 420,
    "DXY_H4": 1000,
    "DXY_H1": 1400,
}


def _parse_ts(value: str) -> int:
    value = str(value or "").strip()
    if value.isdigit():
        return int(value)
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        dt = None
        for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _norm_header(value: str) -> str:
    return str(value or "").strip().lower().strip("<>").replace(" ", "_")


def _reader(handle):
    sample = handle.read(4096)
    handle.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return csv.DictReader(handle, dialect=dialect)


def _normalized_row(row: dict) -> dict[str, str]:
    return {_norm_header(k): v for k, v in row.items()}


def _row_ts(row: dict[str, str]) -> int:
    direct = row.get("ts") or row.get("time_epoch") or row.get("datetime")
    if direct:
        return _parse_ts(direct)
    date = str(row.get("date") or "").strip()
    clock = str(row.get("time") or "").strip()
    if date and clock:
        return _parse_ts(f"{date} {clock}")
    if clock and ("." in clock or "-" in clock):
        return _parse_ts(clock)
    raise ValueError("missing ts/datetime or DATE+TIME columns")


@dataclass(frozen=True)
class ReplayBar:
    ts: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0.0


def closed_before(bars, epoch: int, tf: str, maxn: int):
    """Compatibility helper retained for existing no-lookahead tests/callers."""
    sec = TF_SECONDS[tf]
    values = [b for b in bars if int(b.ts) + sec <= int(epoch)]
    return values[-maxn:]


class BarSeries:
    def __init__(self, rows: Iterable[ReplayBar]):
        self.rows = sorted(list(rows), key=lambda b: b.ts)
        self.times = [b.ts for b in self.rows]
        self._model_rows = None

    def _models(self):
        if self._model_rows is None:
            self._model_rows = _to_model_bars(self.rows)
        return self._model_rows

    def _closed_bounds(self, epoch: int, tf: str, maxn: int) -> tuple[int, int]:
        sec = TF_SECONDS[tf]
        idx = bisect.bisect_right(self.times, int(epoch) - sec)
        start = max(0, idx - maxn)
        return start, idx

    def closed_before(self, epoch: int, tf: str, maxn: int):
        start, idx = self._closed_bounds(epoch, tf, maxn)
        return self.rows[start:idx]

    def closed_model_before(self, epoch: int, tf: str, maxn: int):
        start, idx = self._closed_bounds(epoch, tf, maxn)
        return self._models()[start:idx]

    def minute_closes(self, start_epoch: int, end_epoch: int):
        for bar in self.rows:
            close_ts = int(bar.ts) + 60
            if close_ts < start_epoch:
                continue
            if close_ts > end_epoch:
                break
            yield close_ts, bar

    def count_minute_closes(self, start_epoch: int, end_epoch: int) -> int:
        lo = bisect.bisect_left(self.times, int(start_epoch) - 60)
        hi = bisect.bisect_right(self.times, int(end_epoch) - 60)
        return max(0, hi - lo)


@dataclass(frozen=True)
class ReplayNews:
    ts: int
    currency: str
    title: str
    impact: str


class NewsSeries:
    def __init__(self, rows: Iterable[ReplayNews]):
        self.rows = sorted(list(rows), key=lambda item: item.ts)
        self.times = [item.ts for item in self.rows]

    def around(self, epoch: int, seconds: int = 3600):
        lo = bisect.bisect_left(self.times, int(epoch) - int(seconds))
        hi = bisect.bisect_right(self.times, int(epoch) + int(seconds))
        return self.rows[lo:hi]


def read_bars(path: Path) -> BarSeries:
    if not path.exists():
        raise FileNotFoundError(path)
    out: list[ReplayBar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = _reader(handle)
        headers = {_norm_header(x) for x in (reader.fieldnames or [])}
        required = {"open", "high", "low", "close"}
        if not required.issubset(headers):
            raise ValueError(f"{path.name}: expected OHLC columns plus ts/datetime or DATE+TIME")
        for row in reader:
            normalized = _normalized_row(row)
            ts = _row_ts(normalized)
            out.append(
                ReplayBar(
                    ts=ts,
                    open=float(normalized["open"]),
                    high=float(normalized["high"]),
                    low=float(normalized["low"]),
                    close=float(normalized["close"]),
                    tick_volume=float(
                        normalized.get("tick_volume")
                        or normalized.get("tickvol")
                        or normalized.get("tick_volume_")
                        or normalized.get("volume")
                        or 0.0
                    ),
                )
            )
    return BarSeries(out)


def read_news(path: Path) -> NewsSeries:
    if not path.exists():
        return NewsSeries([])
    out: list[ReplayNews] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = _reader(handle)
        for row in reader:
            normalized = _normalized_row(row)
            out.append(
                ReplayNews(
                    ts=_row_ts(normalized),
                    currency=str(normalized.get("currency") or "USD"),
                    title=str(normalized.get("title") or ""),
                    impact=str(normalized.get("impact") or "HIGH"),
                )
            )
    return NewsSeries(out)


def _simple_atr(bars, n: int = 14) -> float:
    if not bars:
        return 0.0
    start = max(0, len(bars) - int(n))
    total = 0.0
    count = 0
    for idx in range(start, len(bars)):
        bar = bars[idx]
        pc = bars[idx - 1].close if idx > 0 else bar.close
        total += max(bar.high - bar.low, abs(bar.high - pc), abs(bar.low - pc))
        count += 1
    return total / count if count else 0.0


def _to_model_bars(rows):
    from .models import Bar
    return [
        Bar(
            ts=int(b.ts),
            open=float(b.open),
            high=float(b.high),
            low=float(b.low),
            close=float(b.close),
            tick_volume=float(b.tick_volume),
        )
        for b in rows
    ]


def make_snapshot(
    epoch: int,
    minute_bar: ReplayBar,
    data: dict[str, BarSeries],
    news: NewsSeries,
    *,
    spread_points: float,
    point: float,
):
    from .models import MarketSnapshot, NewsEvent

    slices = {}
    model_slices = {}
    for key, tf in (
        ("XAU_D1", "D1"), ("XAU_H4", "H4"), ("XAU_H1", "H1"), ("XAU_M15", "M15"),
        ("DXY_D1", "D1"), ("DXY_H4", "H4"), ("DXY_H1", "H1"),
    ):
        slices[key] = data[key].closed_before(epoch, tf, HISTORY_LIMITS[key])
        if not slices[key]:
            return None
        model_slices[key] = data[key].closed_model_before(epoch, tf, HISTORY_LIMITS[key])

    half_spread = float(spread_points) * float(point) * 0.5
    mid = float(minute_bar.close)
    relevant_news = [
        NewsEvent(ts=n.ts, currency=n.currency, title=n.title, impact=n.impact)
        for n in news.around(epoch, 3600)
    ]
    snapshot = MarketSnapshot(
        kind="HISTORICAL_REPLAY",
        reason=REPLAY_CONTRACT,
        sent_at=int(epoch),
        bid=mid - half_spread,
        ask=mid + half_spread,
        spread_points=float(spread_points),
        point=float(point),
        atr_h1=_simple_atr(slices["XAU_H1"]),
        atr_m15=_simple_atr(slices["XAU_M15"]),
        xau_d1=model_slices["XAU_D1"],
        xau_h4=model_slices["XAU_H4"],
        xau_h1=model_slices["XAU_H1"],
        xau_m15=model_slices["XAU_M15"],
        dxy_d1=model_slices["DXY_D1"],
        dxy_h4=model_slices["DXY_H4"],
        dxy_h1=model_slices["DXY_H1"],
        news=relevant_news,
    )

    # Hard no-lookahead assertion: every analysis bar must have closed at or
    # before the replay instant. M1 itself is consumed only as the just-closed
    # price clock; Strategy Tester still executes on broker real ticks.
    for key, tf in (
        ("XAU_D1", "D1"), ("XAU_H4", "H4"), ("XAU_H1", "H1"), ("XAU_M15", "M15"),
        ("DXY_D1", "D1"), ("DXY_H4", "H4"), ("DXY_H1", "H1"),
    ):
        sec = TF_SECONDS[tf]
        last = slices[key][-1]
        if int(last.ts) + sec > int(epoch):
            raise RuntimeError(f"NO_LOOKAHEAD_BREACH:{key}:{epoch}")
    if int(minute_bar.ts) + 60 > int(epoch):
        raise RuntimeError(f"NO_LOOKAHEAD_BREACH:XAU_M1:{epoch}")
    return snapshot


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key:
            out[key] = value.strip()
    return out


def _f(kv: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(kv.get(key) or default)
    except (TypeError, ValueError):
        return float(default)


def _i(kv: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(kv.get(key) or default))
    except (TypeError, ValueError):
        return int(default)


def _thesis_key(analysis, kv: dict[str, str]) -> str:
    thesis = dict((analysis.execution_policy or {}).get("active_thesis") or {})
    owner_id = str(thesis.get("owner_zone_id") or "")
    acquired = int(thesis.get("ownership_acquired_at") or 0)
    if bool(thesis.get("locked")) and owner_id and acquired > 0:
        return f"OWNER|{owner_id}|{acquired}"
    zone_id = str(kv.get("zone_id") or "")
    return f"ZONE|{zone_id}" if zone_id else f"NONE|{analysis.analysis_id}"


def _plan_rows(epoch: int, reason: str, analysis, snapshot, plan_text: str):
    kv = _parse_kv(plan_text)
    current_grade = str(kv.get("current_grade") or kv.get("grade") or "")
    plan = {
        "epoch": int(epoch),
        "analysis_id": str(kv.get("analysis_id") or analysis.analysis_id),
        "zone_id": str(kv.get("zone_id") or ""),
        "ea_mode": str(kv.get("ea_mode") or "NO_TRADE"),
        # Sequence live mode replaces Plan.grade with current_grade after loading.
        # Put current_grade directly into the legacy tester geometry file too.
        "grade": current_grade,
        "original_direction": str(kv.get("original_direction") or ""),
        "flip_direction": str(kv.get("flip_direction") or ""),
        "core_low": _f(kv, "core_low"),
        "core_high": _f(kv, "core_high"),
        "zone_low": _f(kv, "zone_low"),
        "zone_high": _f(kv, "zone_high"),
        "original_target1": _f(kv, "original_target1"),
        "original_target2": _f(kv, "original_target2"),
        "original_target3": _f(kv, "original_target3"),
        "original_runner": _f(kv, "original_runner"),
        "flip_target1": _f(kv, "flip_target1"),
        "flip_target2": _f(kv, "flip_target2"),
        "flip_target3": _f(kv, "flip_target3"),
        "flip_runner": _f(kv, "flip_runner"),
        "min_displacement_atr": _f(kv, "min_displacement_atr", 0.80),
        "min_rr": _f(kv, "min_rr", 1.50),
    }
    contract = {
        "epoch": int(epoch),
        "analysis_id": plan["analysis_id"],
        "zone_id": plan["zone_id"],
        "thesis_key": _thesis_key(analysis, kv),
        "ea_mode": plan["ea_mode"],
        "execution_authority": str(kv.get("execution_authority") or "NONE"),
        "current_grade": current_grade,
        "qualified_mitigations": _i(kv, "qualified_mitigations", _i(kv, "touch_count", 0)),
        "risk_context": str(kv.get("risk_context") or ""),
        "base_risk_pct": _f(kv, "base_risk_pct", _f(kv, "original_risk_pct", _f(kv, "grade_risk_pct", 0.0))),
        "original_risk_pct": _f(kv, "original_risk_pct", _f(kv, "base_risk_pct", 0.0)),
        "flip_risk_pct": _f(kv, "flip_risk_pct"),
        "validation_initial_capital": _f(kv, "validation_initial_capital", 10000.0),
        "liquidity_reversal_direction": str(kv.get("liquidity_reversal_direction") or ""),
        "liquidity_reversal_label": str(kv.get("liquidity_reversal_label") or ""),
        "liquidity_reversal_price": _f(kv, "liquidity_reversal_price"),
        "liquidity_reversal_risk_multiplier": _f(kv, "liquidity_reversal_risk_multiplier", 0.50),
        "zone_state": str(kv.get("zone_state") or ""),
        "setup_type": str(kv.get("setup_type") or ""),
        "core_method": str(kv.get("core_method") or ""),
        "contract_fingerprint": str(kv.get("contract_fingerprint") or ""),
        "execution_handoff_ts": _i(kv, "execution_handoff_ts", int((analysis.execution_policy or {}).get("execution_authority", {}).get("ownership_acquired_at") or 0)),
        "sniper_parity_version": str(kv.get("sniper_parity_version") or ""),
        "replay_reason": str(reason),
    }
    return plan, contract


async def _deterministic_replay_ai(_analysis, _snapshot):
    # Historical replay must not call a present-day model using future-trained
    # weights. Production already has a PAPER-only deterministic outage fallback;
    # replay deliberately exercises that same documented path.
    return False, "", ["AI_PROVIDER_UNAVAILABLE"], "NONE"


def _write_progress(path: Path | None, **payload) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


async def generate_v659(
    *,
    input_dir: Path,
    start: datetime,
    end: datetime,
    out_csv: Path,
    contract_csv: Path,
    metadata_json: Path,
    timezone_name: str,
    spread_points: float,
    point: float,
    progress_json: Path | None = None,
) -> dict:
    from .config import SETTINGS
    from .db import init_db, latest_analysis, save_snapshot_record
    from .engine import active_plan_text
    from .service import run_analysis
    from . import scheduler
    from .thesis_hard_release import hard_release_stale_thesis
    from .timezones import safe_zoneinfo
    from .zone_reaction_lifecycle import update_zone_publication_contacts, update_zone_reactions

    if SETTINGS.app_version != "6.5.90":
        raise RuntimeError(f"BACKTEST_VERSION_DRIFT: expected Cloud 6.5.90, found {SETTINGS.app_version}")
    if not SETTINGS.paper_only:
        raise RuntimeError("BACKTEST_REQUIRES_PAPER_ONLY")

    names = ["XAU_D1","XAU_H4","XAU_H1","XAU_M15","XAU_M1","DXY_D1","DXY_H4","DXY_H1"]
    data = {name: read_bars(input_dir / f"{name}.csv") for name in names}
    news = read_news(input_dir / "news.csv")
    init_db()

    tz = safe_zoneinfo(timezone_name)
    start_epoch = int(start.astimezone(timezone.utc).timestamp())
    end_epoch = int(end.astimezone(timezone.utc).timestamp())

    plans: list[dict] = []
    contracts: list[dict] = []
    reasons_count: dict[str, int] = {}
    processed_minutes = 0
    skipped_incomplete = 0
    startup_pending = True
    due_keys: set[str] = set()
    zone_latch: set[str] = set()
    m1_latch: set[str] = set()
    wrong_latch: set[str] = set()
    thesis_latch = ""
    liquidity_latch = ""
    saved_snapshot_epoch = 0
    total_minutes = data["XAU_M1"].count_minute_closes(start_epoch, end_epoch)
    _write_progress(
        progress_json,
        phase="REPLAYING",
        processed_m1_closes=0,
        total_m1_closes=total_minutes,
        progress_pct=0.0,
        analysis_states=0,
        last_epoch=0,
    )

    async def run_and_capture(reason: str, snapshot, epoch: int):
        nonlocal saved_snapshot_epoch
        if saved_snapshot_epoch != int(epoch):
            save_snapshot_record(snapshot)
            saved_snapshot_epoch = int(epoch)
        analysis = await run_analysis(
            reason,
            snapshot=snapshot,
            as_of_ts=epoch,
            ai_validator=_deterministic_replay_ai,
        )
        plan_text = active_plan_text(analysis, snapshot)
        plan_row, contract_row = _plan_rows(epoch, reason, analysis, snapshot, plan_text)
        plans.append(plan_row)
        contracts.append(contract_row)
        reasons_count[reason] = reasons_count.get(reason, 0) + 1
        return analysis

    for epoch, minute_bar in data["XAU_M1"].minute_closes(start_epoch, end_epoch):
        snapshot = make_snapshot(
            epoch,
            minute_bar,
            data,
            news,
            spread_points=spread_points,
            point=point,
        )
        if snapshot is None:
            skipped_incomplete += 1
            continue
        processed_minutes += 1
        # Mirror live snapshot lifecycle exactly once for each historical M1 close,
        # without serializing the full multi-timeframe snapshot into SQLite each minute.
        update_zone_publication_contacts(snapshot)
        update_zone_reactions(snapshot)
        if processed_minutes == 1 or processed_minutes % 250 == 0 or processed_minutes == total_minutes:
            pct = round(100.0 * processed_minutes / total_minutes, 1) if total_minutes else 100.0
            _write_progress(
                progress_json,
                phase="REPLAYING",
                processed_m1_closes=processed_minutes,
                total_m1_closes=total_minutes,
                progress_pct=pct,
                analysis_states=len(plans),
                last_epoch=int(epoch),
            )
        now_local = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(tz)
        ran_analysis = False
        for reason in scheduler._due_reasons(now_local):
            key = f"{now_local.date()}:{reason}"
            if key in due_keys:
                continue
            due_keys.add(key)
            await run_and_capture(reason, snapshot, epoch)
            ran_analysis = True

        if startup_pending:
            if ran_analysis:
                startup_pending = False
            elif scheduler._fresh_complete_snapshot(snapshot, epoch):
                await run_and_capture("HISTORICAL_REPLAY_STARTUP", snapshot, epoch)
                startup_pending = False
                ran_analysis = True

        if not scheduler._fresh_complete_snapshot(snapshot, epoch):
            continue

        hard_released = hard_release_stale_thesis(snapshot)

        thesis_sig = scheduler._thesis_signature(epoch)
        thesis_changed = thesis_sig != thesis_latch
        previous_thesis = thesis_latch
        thesis_latch = thesis_sig

        current_ids = scheduler._interaction_ids(snapshot)
        new_ids = current_ids - zone_latch
        zone_latch.clear()
        zone_latch.update(current_ids)

        current_m1 = scheduler._m1_handoff_ids(snapshot)
        new_m1 = current_m1 - m1_latch
        m1_latch.clear()
        m1_latch.update(current_m1)

        liquidity_sig = scheduler._liquidity_reversal_signature(snapshot)
        liquidity_changed = bool(liquidity_sig and liquidity_sig != liquidity_latch)
        liquidity_latch = liquidity_sig

        wrong_ids = scheduler._wrong_side_context_ids(snapshot)
        new_wrong = wrong_ids - wrong_latch
        wrong_latch.clear()
        wrong_latch.update(wrong_ids)

        refresh_reason = ""
        if hard_released:
            refresh_reason = "STALE_THESIS_HARD_RELEASE"
        elif thesis_changed and (thesis_sig or previous_thesis):
            refresh_reason = f"ACTIVE_THESIS_STATE:{thesis_sig or 'RELEASED'}"
        elif liquidity_changed:
            refresh_reason = f"LIQUIDITY_REVERSAL_HANDOFF:{liquidity_sig}"
        elif new_wrong:
            refresh_reason = f"WRONG_SIDE_CONTEXT_REQUALIFY:{','.join(sorted(new_wrong)[:2])}"
        elif new_m1:
            refresh_reason = f"ACTIVE_THESIS_M1_HANDOFF:{','.join(sorted(new_m1)[:2])}"
        elif new_ids:
            refresh_reason = f"PRIMARY_ZONE_REFRESH:{','.join(sorted(new_ids)[:2])}"

        if refresh_reason and not ran_analysis:
            await run_and_capture(refresh_reason, snapshot, epoch)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    contract_csv.parent.mkdir(parents=True, exist_ok=True)
    metadata_json.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAN_FIELDS)
        writer.writeheader()
        writer.writerows(plans)
    with contract_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS)
        writer.writeheader()
        writer.writerows(contracts)

    authority_counts: dict[str, int] = {}
    no_zone_rows = 0
    for row in contracts:
        authority = str(row.get("execution_authority") or "NONE")
        authority_counts[authority] = authority_counts.get(authority, 0) + 1
        if not row.get("zone_id"):
            no_zone_rows += 1

    metadata = {
        "contract": REPLAY_CONTRACT,
        "cloud_version": SETTINGS.app_version,
        "sequence_contract": "3.42",
        "paper_only": True,
        "no_lookahead": True,
        "analysis_pipeline": "app.service.run_analysis production path",
        "scheduler_replay": "session/day/week/news + primary-zone/thesis/M1/liquidity/wrong-side refresh triggers",
        "ai_mode": "PAPER_DETERMINISTIC_AI_PROVIDER_UNAVAILABLE_FALLBACK",
        "m1_clock": "XAU_M1 closed bars; MT5 execution remains Every tick based on real ticks",
        "start": start.astimezone(timezone.utc).isoformat(),
        "end": end.astimezone(timezone.utc).isoformat(),
        "timezone": timezone_name,
        "spread_points_for_cloud_snapshot": spread_points,
        "point": point,
        "processed_m1_closes": processed_minutes,
        "skipped_incomplete_minutes": skipped_incomplete,
        "plan_rows": len(plans),
        "contract_rows": len(contracts),
        "no_zone_rows": no_zone_rows,
        "authority_counts": authority_counts,
        "replay_reason_counts": reasons_count,
        "plan_csv": str(out_csv),
        "contract_csv": str(contract_csv),
        "required_mt5_model": "Every tick based on real ticks",
        "required_backtest_ea": "InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo.mq5",
    }
    metadata_json.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_progress(
        progress_json,
        phase="COMPLETED",
        processed_m1_closes=processed_minutes,
        total_m1_closes=total_minutes,
        progress_pct=100.0,
        analysis_states=len(plans),
        last_epoch=end_epoch,
    )
    return metadata


def _iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _child_main(args) -> int:
    out = Path(args.out)
    contract = Path(args.contract_out) if args.contract_out else out.with_name(out.stem + "_contract.csv")
    meta = Path(args.metadata_out) if args.metadata_out else out.with_name(out.stem + "_metadata.json")
    metadata = asyncio.run(
        generate_v659(
            input_dir=Path(args.input_dir),
            start=_iso(args.start),
            end=_iso(args.end),
            out_csv=out,
            contract_csv=contract,
            metadata_json=meta,
            timezone_name=args.timezone,
            spread_points=float(args.spread_points),
            point=float(args.point),
            progress_json=Path(args.progress_out) if args.progress_out else None,
        )
    )
    print(
        f"generated {metadata['plan_rows']} Master Sniper plan states -> {out}\n"
        f"generated {metadata['contract_rows']} Sequence 3.42 contract states -> {contract}\n"
        f"metadata -> {meta}"
    )
    return 0


def _outer_main(args) -> int:
    # The production pipeline is DB-backed. Run historical replay in a disposable
    # child process so every imported module sees one isolated DB_PATH from startup.
    with tempfile.TemporaryDirectory(prefix="tradezone_v659_replay_") as temp:
        env = dict(os.environ)
        env["TRADEZONE_BACKTEST_INTERNAL"] = "1"
        env["DB_PATH"] = str(Path(temp) / "replay.db")
        env["PAPER_ONLY"] = "true"
        env["ML_DATA_ENABLED"] = "false"
        env["AI_ENABLED"] = "true"
        env["REQUIRE_AI_FOR_EXECUTION"] = "true"
        command = [sys.executable, "-m", "app.backtest", *sys.argv[1:]]
        proc = subprocess.run(command, env=env, check=False)
        return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Master Sniper v6.5.89 no-lookahead replay -> Sequence 3.42 MT5 tester files"
    )
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--start", required=True, help="ISO timestamp, e.g. 2026-06-01T00:00:00+00:00")
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", default="SMC_v659_tester_plans.csv")
    parser.add_argument("--contract-out", default="")
    parser.add_argument("--metadata-out", default="")
    parser.add_argument("--timezone", default="Africa/Lagos")
    parser.add_argument("--spread-points", type=float, default=16.0)
    parser.add_argument("--point", type=float, default=0.01)
    parser.add_argument("--progress-out", default="")
    args = parser.parse_args()

    if os.getenv("TRADEZONE_BACKTEST_INTERNAL") == "1":
        return _child_main(args)
    return _outer_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
