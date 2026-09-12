from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .engine import build_analysis
from .models import Bar, MarketSnapshot, NewsEvent
from .timezones import safe_zoneinfo

TF_SECONDS = {"D1": 86400, "H4": 14400, "H1": 3600, "M15": 900}


def _parse_ts(v: str) -> int:
    v = v.strip()
    if v.isdigit():
        return int(v)
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def read_bars(path: Path) -> list[Bar]:
    out: list[Bar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = _parse_ts(row.get("ts") or row.get("time") or row.get("datetime") or "")
            out.append(Bar(
                ts=ts,
                open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]),
                tick_volume=float(row.get("tick_volume") or row.get("volume") or 0),
            ))
    return sorted(out, key=lambda b: b.ts)


def read_news(path: Path) -> list[NewsEvent]:
    if not path.exists():
        return []
    out: list[NewsEvent] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            out.append(NewsEvent(
                ts=_parse_ts(row.get("ts") or row.get("time") or row.get("datetime") or ""),
                currency=row.get("currency", "USD"), title=row.get("title", ""), impact=row.get("impact", "HIGH"),
            ))
    return sorted(out, key=lambda x: x.ts)


def closed_before(bars: list[Bar], epoch: int, tf: str, maxn: int) -> list[Bar]:
    sec = TF_SECONDS[tf]
    vals = [b for b in bars if b.ts + sec <= epoch]
    return vals[-maxn:]


def _simple_atr(bars: list[Bar], n: int = 14) -> float:
    if not bars:
        return 0.0
    tr = []
    for i,b in enumerate(bars):
        pc = bars[i-1].close if i else b.close
        tr.append(max(b.high-b.low, abs(b.high-pc), abs(b.low-pc)))
    x = tr[-n:]
    return sum(x)/len(x)


def analysis_epochs(start: datetime, end: datetime, tz_name: str, times: list[str], news: list[NewsEvent]) -> list[int]:
    tz = safe_zoneinfo(tz_name)
    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)
    d = start_local.date()
    out = set()
    while d <= end_local.date():
        for t in times:
            hh,mm = [int(x) for x in t.split(":")]
            dt = datetime(d.year,d.month,d.day,hh,mm,tzinfo=tz)
            if start_local <= dt <= end_local:
                out.add(int(dt.astimezone(timezone.utc).timestamp()))
        d += timedelta(days=1)
    for n in news:
        if n.currency.upper() == "USD" and n.impact.upper() == "HIGH":
            for off in (-10,10):
                e = n.ts + off*60
                if int(start.timestamp()) <= e <= int(end.timestamp()):
                    out.add(e)
    return sorted(out)


def make_snapshot(epoch: int, data: dict[str,list[Bar]], news: list[NewsEvent]) -> MarketSnapshot | None:
    x1 = closed_before(data["XAU_D1"],epoch,"D1",280)
    x4 = closed_before(data["XAU_H4"],epoch,"H4",600)
    xh = closed_before(data["XAU_H1"],epoch,"H1",600)
    xm = closed_before(data["XAU_M15"],epoch,"M15",520)
    d1 = closed_before(data["DXY_D1"],epoch,"D1",280)
    d4 = closed_before(data["DXY_H4"],epoch,"H4",600)
    dh = closed_before(data["DXY_H1"],epoch,"H1",600)
    if not all([x1,x4,xh,xm,d1,d4,dh]):
        return None
    mid = xm[-1].close
    relevant_news = [n for n in news if epoch-3600 <= n.ts <= epoch+3600]
    return MarketSnapshot(
        kind="HISTORICAL_REPLAY", reason="NO_LOOKAHEAD", sent_at=epoch,
        bid=mid-0.13, ask=mid+0.13, spread_points=26, point=0.01,
        atr_h1=_simple_atr(xh), atr_m15=_simple_atr(xm),
        xau_d1=x1,xau_h4=x4,xau_h1=xh,xau_m15=xm,dxy_d1=d1,dxy_h4=d4,dxy_h1=dh,news=relevant_news,
    )


def generate(input_dir: Path, start: datetime, end: datetime, out_csv: Path, tz_name: str, times: list[str]) -> int:
    names = ["XAU_D1","XAU_H4","XAU_H1","XAU_M15","DXY_D1","DXY_H4","DXY_H1"]
    data = {n: read_bars(input_dir/f"{n}.csv") for n in names}
    news = read_news(input_dir/"news.csv")
    epochs = analysis_epochs(start,end,tz_name,times,news)
    rows=[]
    for e in epochs:
        s = make_snapshot(e,data,news)
        if not s or not s.complete():
            continue
        a = build_analysis(s,e)
        z = next((x for x in a.zones if x.zone_id==a.selected_zone_id),None)
        if not z:
            continue
        rows.append({
            "epoch":e,"analysis_id":a.analysis_id,"zone_id":z.zone_id,"ea_mode":"DUAL_BRANCH",
            "grade":z.grade.value,"original_direction":z.original_direction.value,"flip_direction":z.flip_direction.value,
            "core_low":z.core_low,"core_high":z.core_high,"zone_low":z.zone_low,"zone_high":z.zone_high,
            "original_target1":z.original_target1,"original_target2":z.original_target2,"original_target3":z.original_target3,"original_runner":z.original_runner,
            "flip_target1":z.flip_target1,"flip_target2":z.flip_target2,"flip_target3":z.flip_target3,"flip_runner":z.flip_runner,
            "min_displacement_atr":0.80,"min_rr":1.50,
        })
    out_csv.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0].keys()) if rows else ["epoch","analysis_id","zone_id","ea_mode","grade","original_direction","flip_direction","core_low","core_high","zone_low","zone_high","original_target1","original_target2","original_target3","original_runner","flip_target1","flip_target2","flip_target3","flip_runner","min_displacement_atr","min_rr"]
    with out_csv.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    return len(rows)


def main():
    p=argparse.ArgumentParser(description="Generate no-lookahead MT5 tester plans for SMC v6")
    p.add_argument("--input-dir",required=True)
    p.add_argument("--start",required=True,help="ISO timestamp, e.g. 2026-01-01T00:00:00+00:00")
    p.add_argument("--end",required=True)
    p.add_argument("--out",default="SMC_v6_tester_plans.csv")
    p.add_argument("--timezone",default="Africa/Lagos")
    p.add_argument("--times",default="07:50,12:50,15:20")
    a=p.parse_args()
    start=datetime.fromisoformat(a.start); end=datetime.fromisoformat(a.end)
    if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
    n=generate(Path(a.input_dir),start,end,Path(a.out),a.timezone,[x.strip() for x in a.times.split(",") if x.strip()])
    print(f"generated {n} plans -> {a.out}")

if __name__ == "__main__":
    main()
