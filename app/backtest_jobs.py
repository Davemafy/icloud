from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path


BACKTEST_API_CONTRACT = "MASTER_SNIPER_V659_BACKTEST_JOB_V1"
MAX_UPLOAD_BYTES = 96 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_TEST_DAYS = 120
REQUIRED_HISTORY_FILES = {
    "XAU_D1.csv",
    "XAU_H4.csv",
    "XAU_H1.csv",
    "XAU_M15.csv",
    "XAU_M1.csv",
    "DXY_D1.csv",
    "DXY_H4.csv",
    "DXY_H1.csv",
}
_OPTIONAL_HISTORY_FILES = {"news.csv", "export_manifest.txt"}
_JOB_LOCK = threading.Lock()
_ASYNC_JOBS_LOCK = threading.Lock()
_ASYNC_JOBS: dict[str, dict] = {}
_ASYNC_JOB_DIR = Path(tempfile.gettempdir()) / "tradezone_v659_async_jobs"
ROOT = Path(__file__).resolve().parents[1]


class BacktestJobError(RuntimeError):
    pass


def _parse_iso(value: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise BacktestJobError(f"invalid ISO datetime: {value}") from exc
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return out.astimezone(timezone.utc)


def _validate_window(start: str, end: str) -> tuple[datetime, datetime]:
    a = _parse_iso(start)
    b = _parse_iso(end)
    if b <= a:
        raise BacktestJobError("end must be after start")
    days = (b - a).total_seconds() / 86400.0
    if days > MAX_TEST_DAYS:
        raise BacktestJobError(f"test window exceeds {MAX_TEST_DAYS} days")
    return a, b


def _safe_extract_history(blob: bytes, destination: Path) -> list[str]:
    if not blob:
        raise BacktestJobError("empty upload")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise BacktestJobError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")

    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise BacktestJobError("upload is not a valid ZIP archive") from exc

    names: list[str] = []
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        total += int(info.file_size)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise BacktestJobError("uncompressed history payload is too large")
        raw = info.filename.replace("\\", "/")
        name = Path(raw).name
        if name not in REQUIRED_HISTORY_FILES | _OPTIONAL_HISTORY_FILES:
            continue
        target = destination / name
        target.write_bytes(archive.read(info))
        names.append(name)

    missing = sorted(REQUIRED_HISTORY_FILES - set(names))
    if missing:
        raise BacktestJobError("missing required history files: " + ", ".join(missing))
    return sorted(set(names))


def _next_readme(start: datetime, end: datetime) -> str:
    return (
        "Trade Zone Master Sniper backtest package is ready.\n\n"
        "MT5 Strategy Tester settings:\n"
        "EA: InstitutionalSMC_SequenceEA_v3_42_MasterSniper_Backtest_Demo\n"
        "Symbol: XAUUSD\n"
        "Timeframe: M1\n"
        "Model: Every tick based on real ticks\n"
        f"From: {start.strftime('%Y.%m.%d')}\n"
        f"To: {end.strftime('%Y.%m.%d')}\n"
        "Optimization: Off\n"
        "Initial deposit: 10000 USD\n\n"
        "The legacy geometry file is named SMC_v6_tester_plans.csv so the "
        "backtest EA can use its default TesterPlanFile.\n"
        "The Sequence 3.42 sidecar is SMC_v659_tester_plans_contract.csv.\n"
    )


def run_replay_job(
    payload: bytes,
    *,
    start: str,
    end: str,
    timezone_name: str = "Africa/Lagos",
    spread_points: float = 16.0,
    point: float = 0.01,
) -> bytes:
    start_dt, end_dt = _validate_window(start, end)
    if spread_points <= 0 or spread_points > 1000:
        raise BacktestJobError("spread_points is outside the validation range")
    if point <= 0 or point > 10:
        raise BacktestJobError("point is outside the validation range")

    if not _JOB_LOCK.acquire(blocking=False):
        raise BacktestJobError("another Master Sniper backtest job is already running")

    try:
        with tempfile.TemporaryDirectory(prefix="tradezone_v659_job_") as tmp:
            root = Path(tmp)
            history = root / "history"
            history.mkdir()
            extracted = _safe_extract_history(payload, history)

            out_plan = root / "SMC_v6_tester_plans.csv"
            out_contract = root / "SMC_v659_tester_plans_contract.csv"
            out_meta = root / "SMC_v659_tester_plans_metadata.json"

            command = [
                sys.executable,
                "-m",
                "app.backtest",
                "--input-dir",
                str(history),
                "--start",
                start_dt.isoformat(),
                "--end",
                end_dt.isoformat(),
                "--out",
                str(out_plan),
                "--contract-out",
                str(out_contract),
                "--metadata-out",
                str(out_meta),
                "--timezone",
                timezone_name,
                "--spread-points",
                str(float(spread_points)),
                "--point",
                str(float(point)),
            ]
            env = dict(os.environ)
            proc = subprocess.run(
                command,
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=1200,
            )
            if proc.returncode != 0:
                tail = (proc.stdout + "\n" + proc.stderr)[-12000:]
                raise BacktestJobError("historical replay failed:\n" + tail)

            for required in (out_plan, out_contract, out_meta):
                if not required.exists() or required.stat().st_size <= 0:
                    raise BacktestJobError(f"replay output missing: {required.name}")

            metadata = json.loads(out_meta.read_text(encoding="utf-8"))
            if metadata.get("contract") != "MASTER_SNIPER_V659_NO_LOOKAHEAD_REPLAY_V1":
                raise BacktestJobError("unexpected replay metadata contract")
            if not metadata.get("no_lookahead"):
                raise BacktestJobError("replay did not certify no-lookahead")

            job_manifest = {
                "contract": BACKTEST_API_CONTRACT,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "timezone": timezone_name,
                "spread_points": float(spread_points),
                "point": float(point),
                "input_files": extracted,
                "plan_rows": metadata.get("plan_rows"),
                "contract_rows": metadata.get("contract_rows"),
                "authority_counts": metadata.get("authority_counts", {}),
                "replay_reason_counts": metadata.get("replay_reason_counts", {}),
                "required_mt5_model": "Every tick based on real ticks",
                "required_backtest_ea": metadata.get("required_backtest_ea"),
            }

            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(out_plan, out_plan.name)
                zf.write(out_contract, out_contract.name)
                zf.write(out_meta, out_meta.name)
                zf.writestr(
                    "MasterSniper_Backtest_Job.json",
                    json.dumps(job_manifest, indent=2, sort_keys=True) + "\n",
                )
                zf.writestr("README_NEXT.txt", _next_readme(start_dt, end_dt))
                zf.writestr(
                    "replay_stdout.txt",
                    (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""),
                )
            return output.getvalue()
    except subprocess.TimeoutExpired as exc:
        raise BacktestJobError("historical replay exceeded the 20-minute job limit") from exc
    finally:
        _JOB_LOCK.release()


def _prune_async_jobs(max_age_seconds: int = 21600) -> None:
    now = time.time()
    with _ASYNC_JOBS_LOCK:
        stale = [
            job_id for job_id, item in _ASYNC_JOBS.items()
            if now - float(item.get("created_at") or now) > max_age_seconds
        ]
        for job_id in stale:
            item = _ASYNC_JOBS.pop(job_id, {})
            path = Path(str(item.get("result_path") or ""))
            if path.exists():
                path.unlink(missing_ok=True)


def _run_async_job(job_id: str, payload: bytes, kwargs: dict) -> None:
    with _ASYNC_JOBS_LOCK:
        if job_id not in _ASYNC_JOBS:
            return
        _ASYNC_JOBS[job_id]["status"] = "RUNNING"
        _ASYNC_JOBS[job_id]["started_at"] = time.time()
    try:
        result = run_replay_job(payload, **kwargs)
        _ASYNC_JOB_DIR.mkdir(parents=True, exist_ok=True)
        path = _ASYNC_JOB_DIR / f"{job_id}.zip"
        path.write_bytes(result)
        with _ASYNC_JOBS_LOCK:
            _ASYNC_JOBS[job_id].update(
                status="COMPLETED",
                completed_at=time.time(),
                result_path=str(path),
                result_bytes=len(result),
                error="",
            )
    except Exception as exc:
        with _ASYNC_JOBS_LOCK:
            _ASYNC_JOBS[job_id].update(
                status="FAILED",
                completed_at=time.time(),
                error=str(exc)[-16000:],
            )


def start_replay_job(
    payload: bytes,
    *,
    start: str,
    end: str,
    timezone_name: str = "Africa/Lagos",
    spread_points: float = 16.0,
    point: float = 0.01,
) -> dict:
    _validate_window(start, end)
    _prune_async_jobs()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise BacktestJobError(f"upload exceeds {MAX_UPLOAD_BYTES} bytes")
    with _ASYNC_JOBS_LOCK:
        if any(item.get("status") in {"QUEUED", "RUNNING"} for item in _ASYNC_JOBS.values()):
            raise BacktestJobError("another Master Sniper backtest job is already running")
        job_id = uuid.uuid4().hex
        _ASYNC_JOBS[job_id] = {
            "job_id": job_id,
            "status": "QUEUED",
            "created_at": time.time(),
            "started_at": 0,
            "completed_at": 0,
            "result_path": "",
            "result_bytes": 0,
            "error": "",
        }
    kwargs = {
        "start": start,
        "end": end,
        "timezone_name": timezone_name,
        "spread_points": float(spread_points),
        "point": float(point),
    }
    thread = threading.Thread(
        target=_run_async_job,
        args=(job_id, bytes(payload), kwargs),
        name=f"master-sniper-backtest-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "status": "QUEUED", "contract": BACKTEST_API_CONTRACT}


def replay_job_status(job_id: str) -> dict:
    _prune_async_jobs()
    with _ASYNC_JOBS_LOCK:
        item = dict(_ASYNC_JOBS.get(str(job_id)) or {})
    if not item:
        raise BacktestJobError("backtest job not found")
    item.pop("result_path", None)
    return item


def replay_job_result(job_id: str) -> bytes:
    with _ASYNC_JOBS_LOCK:
        item = dict(_ASYNC_JOBS.get(str(job_id)) or {})
    if not item:
        raise BacktestJobError("backtest job not found")
    if item.get("status") == "FAILED":
        raise BacktestJobError(str(item.get("error") or "backtest job failed"))
    if item.get("status") != "COMPLETED":
        raise BacktestJobError("backtest job is not complete")
    path = Path(str(item.get("result_path") or ""))
    if not path.exists():
        raise BacktestJobError("backtest result package is no longer available")
    return path.read_bytes()
