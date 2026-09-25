from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app import backtest_jobs


def _zip(names: list[str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, "ts,open,high,low,close,tick_volume\n1,1,1,1,1,1\n")
    return out.getvalue()


def test_safe_extract_accepts_exact_required_history_set(tmp_path):
    blob = _zip(sorted(backtest_jobs.REQUIRED_HISTORY_FILES))
    names = backtest_jobs._safe_extract_history(blob, tmp_path)
    assert set(names) == backtest_jobs.REQUIRED_HISTORY_FILES
    for name in backtest_jobs.REQUIRED_HISTORY_FILES:
        assert (tmp_path / name).exists()


def test_safe_extract_flattens_nested_zip_and_ignores_unrelated_files(tmp_path):
    required = [f"nested/export/{name}" for name in sorted(backtest_jobs.REQUIRED_HISTORY_FILES)]
    blob = _zip(required + ["nested/secret.txt"])
    names = backtest_jobs._safe_extract_history(blob, tmp_path)
    assert set(names) == backtest_jobs.REQUIRED_HISTORY_FILES
    assert not (tmp_path / "secret.txt").exists()


def test_missing_history_file_fails_closed(tmp_path):
    names = sorted(backtest_jobs.REQUIRED_HISTORY_FILES - {"DXY_H1.csv"})
    with pytest.raises(backtest_jobs.BacktestJobError, match="DXY_H1.csv"):
        backtest_jobs._safe_extract_history(_zip(names), tmp_path)


def test_backtest_window_is_bounded_to_research_limit():
    start, end = backtest_jobs._validate_window(
        "2026-06-01T00:00:00+00:00",
        "2026-08-31T23:59:00+00:00",
    )
    assert end > start
    with pytest.raises(backtest_jobs.BacktestJobError, match="exceeds"):
        backtest_jobs._validate_window(
            "2026-01-01T00:00:00+00:00",
            "2026-08-31T00:00:00+00:00",
        )


def test_backtest_api_contract_and_endpoint_are_research_only():
    assert backtest_jobs.BACKTEST_API_CONTRACT == "MASTER_SNIPER_V659_BACKTEST_JOB_V1"
    text = Path("app/main.py").read_text(encoding="utf-8")
    assert '@app.post("/validation/backtest/v659/replay", dependencies=[Depends(require_api_key)])' in text
    assert "await asyncio.to_thread(" in text
    assert "run_replay_job" in text


def test_backtest_job_module_never_writes_live_db():
    text = Path("app/backtest_jobs.py").read_text(encoding="utf-8")
    for forbidden in (
        "save_snapshot(",
        "save_analysis(",
        "save_feedback(",
        "latest_snapshot(",
        "active_analysis(",
    ):
        assert forbidden not in text
    assert "TemporaryDirectory" in text
    assert "another Master Sniper backtest job is already running" in text


def test_async_backtest_job_endpoints_are_authenticated_and_pollable():
    text = Path("app/main.py").read_text(encoding="utf-8")
    assert '@app.post("/validation/backtest/v659/jobs", dependencies=[Depends(require_api_key)])' in text
    assert '@app.get("/validation/backtest/v659/jobs/{job_id}", dependencies=[Depends(require_api_key)])' in text
    assert '@app.get("/validation/backtest/v659/jobs/{job_id}/download", dependencies=[Depends(require_api_key)])' in text
    assert "start_replay_job" in text
    assert "replay_job_status" in text
    assert "replay_job_result" in text


def test_async_job_manager_is_single_flight_and_persists_result_outside_request_scope():
    text = Path("app/backtest_jobs.py").read_text(encoding="utf-8")
    assert "_ASYNC_JOBS" in text
    assert "threading.Thread(" in text
    assert "daemon=True" in text
    assert '"COMPLETED"' in text
    assert '"FAILED"' in text
    assert "another Master Sniper backtest job is already running" in text


def test_async_job_status_carries_live_replay_progress_fields():
    text = Path("app/backtest_jobs.py").read_text(encoding="utf-8")
    for required in (
        '"processed_m1_closes": 0',
        '"total_m1_closes": 0',
        '"progress_pct": 0.0',
        '"analysis_states": 0',
        'progress_hook(progress: dict)',
        'historical replay exceeded the 30-minute job limit',
        '"--progress-out"',
    ):
        assert required in text



def test_next_readme_uses_exclusive_mt5_end_date():
    from datetime import datetime, timezone
    from app.backtest_jobs import _next_readme

    start = datetime(2026, 8, 24, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)
    text = _next_readme(start, end)
    assert "Requested through: 2026.08.31 inclusive" in text
    assert "MT5 ToDate: 2026.09.01 (exclusive)" in text
    assert "MasterSniper_v659_tester_gate_audit.csv" in text
