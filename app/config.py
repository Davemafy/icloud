from __future__ import annotations

from dataclasses import dataclass
import os


def _b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Institutional SMC AI Cloud")
    app_version: str = os.getenv("APP_VERSION", "6.3.0")
    timezone_name: str = os.getenv("TIMEZONE_NAME", "Africa/Lagos")
    api_key: str = os.getenv("CLOUD_EA_API_KEY", "change-me")
    db_path: str = os.getenv("DB_PATH", "/data/smc_cloud.db")
    paper_only: bool = _b("PAPER_ONLY", True)

    # Analysis schedule. Existing session checkpoints are preserved. The weekly
    # opening checkpoint replaces the Monday daily-open duplicate at the same time.
    session_analysis_times: str = os.getenv("SESSION_ANALYSIS_TIMES", "07:50,12:50,15:20")
    trading_day_open_time: str = os.getenv("TRADING_DAY_OPEN_TIME", "00:05")
    trading_day_weekdays: str = os.getenv("TRADING_DAY_WEEKDAYS", "0,1,2,3,4")
    week_open_weekday: int = _i("WEEK_OPEN_WEEKDAY", 0)
    week_open_time: str = os.getenv("WEEK_OPEN_TIME", "00:05")
    scheduler_poll_seconds: int = _i("SCHEDULER_POLL_SECONDS", 20)
    plan_refresh_minutes: int = _i("PLAN_REFRESH_MINUTES", 180)

    # AI validation. Deterministic engine remains authoritative.
    ai_enabled: bool = _b("AI_ENABLED", True)
    require_ai_for_execution: bool = _b("REQUIRE_AI_FOR_EXECUTION", True)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    ai_timeout_seconds: int = _i("AI_TIMEOUT_SECONDS", 18)
    ai_compat_url: str = os.getenv("AI_COMPAT_URL", "")
    ai_compat_key: str = os.getenv("AI_COMPAT_KEY", "")
    ai_compat_model: str = os.getenv("AI_COMPAT_MODEL", "")

    # Core/zone quality.
    zone_retire_touch_count: int = _i("ZONE_RETIRE_TOUCH_COUNT", 2)
    zone_min_independent_confluences: int = _i("ZONE_MIN_INDEPENDENT_CONFLUENCES", 2)
    zone_liquidity_envelope_max_h1_atr: float = _f("ZONE_LIQUIDITY_ENVELOPE_MAX_H1_ATR", 1.50)
    zone_liquidity_envelope_max_h4_atr: float = _f("ZONE_LIQUIDITY_ENVELOPE_MAX_H4_ATR", 0.75)
    zone_liquidity_envelope_max_d1_atr: float = _f("ZONE_LIQUIDITY_ENVELOPE_MAX_D1_ATR", 0.30)
    zone_liquidity_sweep_buffer_m15_atr: float = _f("ZONE_LIQUIDITY_SWEEP_BUFFER_M15_ATR", 0.15)
    clear_run_with_trend: float = _f("CLEAR_RUN_WITH_TREND_PRICE", 5.0)
    clear_run_countertrend: float = _f("CLEAR_RUN_COUNTERTREND_PRICE", 10.0)

    # Dynamic safety gates.
    max_snapshot_age_seconds: int = _i("MAX_SNAPSHOT_AGE_SECONDS", 120)
    max_spread_points: float = _f("MAX_SPREAD_POINTS", 35.0)
    news_entry_lock_minutes: int = _i("NEWS_ENTRY_LOCK_MINUTES", 15)
    news_post_revalidate_minutes: int = _i("NEWS_POST_REVALIDATE_MINUTES", 10)

    # M15 outer-envelope acceptance -> flip candidate.
    m15_single_accept_body_fraction: float = _f("M15_SINGLE_ACCEPT_BODY_FRACTION", 0.60)
    m15_single_accept_body_atr: float = _f("M15_SINGLE_ACCEPT_BODY_ATR", 0.40)
    m15_double_accept_body_atr: float = _f("M15_DOUBLE_ACCEPT_BODY_ATR", 0.20)

    # Plan protocol / tester.
    protocol_version: int = _i("PROTOCOL_VERSION", 6)
    tester_plan_filename: str = os.getenv("TESTER_PLAN_FILENAME", "SMC_v6_tester_plans.csv")


SETTINGS = Settings()
