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
    app_version: str = "6.5.79"
    timezone_name: str = os.getenv("TIMEZONE_NAME", "Africa/Lagos")
    api_key: str = os.getenv("CLOUD_EA_API_KEY", "change-me")
    db_path: str = os.getenv("DB_PATH", "/data/smc_cloud.db")
    paper_only: bool = _b("PAPER_ONLY", True)

    session_analysis_times: str = os.getenv("SESSION_ANALYSIS_TIMES", "07:50,12:50,15:20")
    trading_day_open_time: str = os.getenv("TRADING_DAY_OPEN_TIME", "23:06")
    trading_day_weekdays: str = os.getenv("TRADING_DAY_WEEKDAYS", "0,1,2,3")
    week_open_weekday: int = _i("WEEK_OPEN_WEEKDAY", 6)
    week_open_time: str = os.getenv("WEEK_OPEN_TIME", "23:11")
    scheduler_poll_seconds: int = _i("SCHEDULER_POLL_SECONDS", 20)
    plan_refresh_minutes: int = _i("PLAN_REFRESH_MINUTES", 180)
    stale_snapshot_seconds: int = _i("STALE_SNAPSHOT_SECONDS", 75)
    max_spread_points: int = _i("MAX_SPREAD_POINTS", 80)
    min_rr: float = _f("MIN_RR", 1.5)
    protocol_version: int = _i("PROTOCOL_VERSION", 1)
    ai_enabled: bool = _b("AI_ENABLED", True)
    require_ai_for_execution: bool = _b("REQUIRE_AI_FOR_EXECUTION", True)
    ai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    research_validation_initial_capital: float = _f("RESEARCH_VALIDATION_INITIAL_CAPITAL", 10000.0)
    research_risk_pct_trend_a_plus: float = _f("RESEARCH_RISK_PCT_TREND_A_PLUS", 1.00)
    research_risk_pct_trend_a: float = _f("RESEARCH_RISK_PCT_TREND_A", 0.75)
    research_risk_pct_countertrend_a_plus: float = _f("RESEARCH_RISK_PCT_COUNTERTREND_A_PLUS", 0.50)
    research_risk_pct_countertrend_a: float = _f("RESEARCH_RISK_PCT_COUNTERTREND_A", 0.25)
    # Retained only for backward-compatible config parsing. Master Sniper V4
    # hard-blocks B+ new execution authority and assigns it 0% risk.
    research_risk_pct_b_plus: float = _f("RESEARCH_RISK_PCT_B_PLUS", 0.25)
    m15_single_accept_body_fraction: float = _f("M15_SINGLE_ACCEPT_BODY_FRACTION", 0.60)
    m15_single_accept_body_atr: float = _f("M15_SINGLE_ACCEPT_BODY_ATR", 0.50)
    m15_double_accept_body_atr: float = _f("M15_DOUBLE_ACCEPT_BODY_ATR", 0.20)


SETTINGS = Settings()
