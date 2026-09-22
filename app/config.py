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
    # Release truth is code-authoritative so a stale Railway APP_VERSION variable
    # cannot make a new deployment report an old cloud version.
    app_version: str = "6.5.52"
    timezone_name: str = os.getenv("TIMEZONE_NAME", "Africa/Lagos")
    api_key: str = os.getenv("CLOUD_EA_API_KEY", "change-me")
    db_path: str = os.getenv("DB_PATH", "/data/smc_cloud.db")
    paper_only: bool = _b("PAPER_ONLY", True)

    # Existing intraday checkpoints remain unchanged. Opening checkpoints below
    # are aligned to Deriv XAUUSD hours (GMT) but expressed in Africa/Lagos WAT.
    # Deriv XAUUSD: week open Sun 22:10 GMT; Mon-Thu daily reopen 22:05 GMT.
    # We schedule one minute after each open so the bridge can publish a fresh tick.
    session_analysis_times: str = os.getenv("SESSION_ANALYSIS_TIMES", "07:50,12:50,15:20")
    trading_day_open_time: str = os.getenv("TRADING_DAY_OPEN_TIME", "23:06")
    trading_day_weekdays: str = os.getenv("TRADING_DAY_WEEKDAYS", "0,1,2,3")
    week_open_weekday: int = _i("WEEK_OPEN_WEEKDAY", 6)
    week_open_time: str = os.getenv("WEEK_OPEN_TIME", "23:11")
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

    # V6.4 ML data foundation. Data collection/shadow labels only: no model can
    # authorize trades, alter lot size, move stops, or bypass deterministic guards.
    ml_data_enabled: bool = _b("ML_DATA_ENABLED", True)
    ml_max_cloud_zones_per_analysis: int = _i("ML_MAX_CLOUD_ZONES_PER_ANALYSIS", 24)
    ml_max_open_candidates_per_mark: int = _i("ML_MAX_OPEN_CANDIDATES_PER_MARK", 2500)
    ml_max_label_hours: int = _i("ML_MAX_LABEL_HOURS", 24)
    ml_dataset_export_limit: int = _i("ML_DATASET_EXPORT_LIMIT", 100000)
    ml_min_resolved_for_training: int = _i("ML_MIN_RESOLVED_FOR_TRAINING", 1000)

    # Legacy/research-zone settings retained only for non-production compatibility.
    # The live v6.5 prompt zoning engine does not use these as hard zone gates.
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

    # DEMO/PAPER context x grade risk validation. Structural grade and D1
    # alignment are separate axes. The research capital does not compound upward;
    # live balance below the anchor reduces the sizing base.
    research_validation_initial_capital: float = _f("RESEARCH_VALIDATION_INITIAL_CAPITAL", 10000.0)
    research_risk_pct_trend_a_plus: float = _f("RESEARCH_RISK_PCT_TREND_A_PLUS", 1.00)
    research_risk_pct_trend_a: float = _f("RESEARCH_RISK_PCT_TREND_A", 0.75)
    research_risk_pct_countertrend_a_plus: float = _f("RESEARCH_RISK_PCT_COUNTERTREND_A_PLUS", 0.50)
    research_risk_pct_countertrend_a: float = _f("RESEARCH_RISK_PCT_COUNTERTREND_A", 0.25)
    research_risk_epoch: str = os.getenv("RESEARCH_RISK_EPOCH", "CONTEXT_GRADE_10000_V2")

    # M15 outer-envelope acceptance -> flip candidate.
    m15_single_accept_body_fraction: float = _f("M15_SINGLE_ACCEPT_BODY_FRACTION", 0.60)
    m15_single_accept_body_atr: float = _f("M15_SINGLE_ACCEPT_BODY_ATR", 0.40)
    m15_double_accept_body_atr: float = _f("M15_DOUBLE_ACCEPT_BODY_ATR", 0.20)

    # Plan protocol / tester.
    protocol_version: int = _i("PROTOCOL_VERSION", 6)
    tester_plan_filename: str = os.getenv("TESTER_PLAN_FILENAME", "SMC_v6_tester_plans.csv")


SETTINGS = Settings()
