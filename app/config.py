from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Local development convenience. Railway environment variables take precedence.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_path: str = os.getenv("DATABASE_PATH", "/data/smc_cloud.db")
    cloud_ea_api_key: str = os.getenv("CLOUD_EA_API_KEY", "change-me")
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "change-me-admin")
    signing_secret: str = os.getenv("SIGNING_SECRET", "change-me-signing")

    # Multi-provider AI layer. Providers are attempted in AI_PROVIDER_ORDER and the
    # first schema-valid response is accepted. Unconfigured providers are skipped.
    ai_provider_order: str = os.getenv("AI_PROVIDER_ORDER", "gemini,groq,openrouter,tensormux,openai")
    ai_enabled: bool = _bool("AI_ENABLED", True)
    require_ai_for_execution: bool = _bool("REQUIRE_AI_FOR_EXECUTION", True)
    ai_timeout_seconds: int = _int("AI_TIMEOUT_SECONDS", 90)
    ai_reasoning_effort: str = os.getenv("AI_REASONING_EFFORT", "medium")

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    gemini_base_url: str = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    # TensorMux is treated as an OpenAI-compatible gateway. It is optional and is
    # only attempted when TENSORMUX_BASE_URL and TENSORMUX_MODEL are configured.
    tensormux_api_key: str = os.getenv("TENSORMUX_API_KEY", "")
    tensormux_model: str = os.getenv("TENSORMUX_MODEL", "")
    tensormux_base_url: str = os.getenv("TENSORMUX_BASE_URL", "")

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    paper_only: bool = _bool("PAPER_ONLY", True)
    timezone_name: str = os.getenv("TIMEZONE_NAME", "Africa/Lagos")
    max_snapshot_age_seconds: int = _int("MAX_SNAPSHOT_AGE_SECONDS", 900)
    plan_valid_minutes: int = _int("PLAN_VALID_MINUTES", 120)
    max_spread_points: float = _float("MAX_SPREAD_POINTS", 40.0)
    bplus_executable: bool = _bool("BPLUS_EXECUTABLE", False)
    xau_pip_size: float = _float("XAU_PIP_SIZE", 0.01)
    min_clear_run_with_trend_pips: float = _float("MIN_CLEAR_RUN_WITH_TREND_PIPS", 50.0)
    min_clear_run_counter_trend_pips: float = _float("MIN_CLEAR_RUN_COUNTER_TREND_PIPS", 100.0)

    # Intraday/scalping profile. D1/H4 remain structural context; H1/M15 generate
    # the executable reaction map that is refined by the M1 execution EA.
    trading_profile: str = os.getenv("TRADING_PROFILE", "INTRADAY_SCALP").upper()
    intraday_max_distance_h1_atr: float = _float("INTRADAY_MAX_DISTANCE_H1_ATR", 2.5)
    intraday_max_distance_d1_atr: float = _float("INTRADAY_MAX_DISTANCE_D1_ATR", 0.35)
    intraday_max_zone_width_m15_atr: float = _float("INTRADAY_MAX_ZONE_WIDTH_M15_ATR", 2.5)
    intraday_h1_lookback: int = _int("INTRADAY_H1_LOOKBACK", 180)
    intraday_m15_lookback: int = _int("INTRADAY_M15_LOOKBACK", 320)
    intraday_max_candidates: int = _int("INTRADAY_MAX_CANDIDATES", 8)

    nonce_ttl_seconds: int = _int("NONCE_TTL_SECONDS", 300)
    rate_limit_per_minute: int = _int("RATE_LIMIT_PER_MINUTE", 120)

    session_asia_start: str = os.getenv("SESSION_ASIA_START", "00:00")
    session_london_start: str = os.getenv("SESSION_LONDON_START", "08:00")
    session_newyork_start: str = os.getenv("SESSION_NEWYORK_START", "13:00")
    session_lead_minutes: int = _int("SESSION_LEAD_MINUTES", 10)
    scheduler_poll_seconds: int = _int("SCHEDULER_POLL_SECONDS", 20)
    # A scheduled session analysis may catch up after its nominal pre-session time.
    # Example: Asia 00:00, lead 10, catch-up 20 => eligible from 23:50 through 00:10 WAT.
    session_catchup_minutes: int = _int("SESSION_CATCHUP_MINUTES", 20)
    # If a pre-session run was missed, run once during the active session using the latest fresh snapshot.
    session_active_recovery: bool = _bool("SESSION_ACTIVE_RECOVERY", True)
    # Do not spend an AI call on stale context; wait for the next Data Bridge snapshot.
    session_snapshot_max_age_seconds: int = _int("SESSION_SNAPSHOT_MAX_AGE_SECONDS", 180)

    # Historical-context protocol v3. The bridge sends a full context bootstrap
    # at startup, ~10 minutes before each session, and after high-impact USD news.
    # Lightweight live updates are merged into the latest full context before analysis.
    history_full_max_age_hours: int = _int("HISTORY_FULL_MAX_AGE_HOURS", 12)
    history_min_xau_d1: int = _int("HISTORY_MIN_XAU_D1", 240)
    history_min_xau_h4: int = _int("HISTORY_MIN_XAU_H4", 480)
    history_min_xau_h1: int = _int("HISTORY_MIN_XAU_H1", 400)
    history_min_xau_m15: int = _int("HISTORY_MIN_XAU_M15", 400)
    history_min_dxy_d1: int = _int("HISTORY_MIN_DXY_D1", 200)
    history_min_dxy_h4: int = _int("HISTORY_MIN_DXY_H4", 480)
    history_min_dxy_h1: int = _int("HISTORY_MIN_DXY_H1", 400)
    history_merge_cap_d1: int = _int("HISTORY_MERGE_CAP_D1", 320)
    history_merge_cap_h4: int = _int("HISTORY_MERGE_CAP_H4", 700)
    history_merge_cap_h1: int = _int("HISTORY_MERGE_CAP_H1", 700)
    history_merge_cap_m15: int = _int("HISTORY_MERGE_CAP_M15", 560)
    snapshot_live_retention: int = _int("SNAPSHOT_LIVE_RETENTION", 1500)
    snapshot_full_retention: int = _int("SNAPSHOT_FULL_RETENTION", 180)

    news_provider: str = os.getenv("NEWS_PROVIDER", "mt5_calendar").lower()
    tradingeconomics_api_key: str = os.getenv("TRADINGECONOMICS_API_KEY", "")
    news_poll_minutes: int = _int("NEWS_POLL_MINUTES", 10)
    news_pre_blackout_minutes: int = _int("NEWS_PRE_BLACKOUT_MINUTES", 10)
    news_post_cooldown_minutes: int = _int("NEWS_POST_COOLDOWN_MINUTES", 5)
    # Keep retrying post-news reanalysis for this long after the cooldown, waiting for a fresh post-release snapshot.
    post_news_catchup_minutes: int = _int("POST_NEWS_CATCHUP_MINUTES", 30)

    dashboard_enabled: bool = _bool("DASHBOARD_ENABLED", True)


SETTINGS = Settings()


def validate_runtime_settings() -> None:
    if SETTINGS.app_env.lower() == "production":
        bad = []
        if SETTINGS.cloud_ea_api_key in {"", "change-me"}: bad.append("CLOUD_EA_API_KEY")
        if SETTINGS.admin_api_key in {"", "change-me-admin"}: bad.append("ADMIN_API_KEY")
        if SETTINGS.signing_secret in {"", "change-me-signing"}: bad.append("SIGNING_SECRET")
        if SETTINGS.ai_enabled:
            configured = any([
                SETTINGS.gemini_api_key,
                SETTINGS.groq_api_key,
                SETTINGS.openrouter_api_key and SETTINGS.openrouter_model,
                SETTINGS.tensormux_base_url and SETTINGS.tensormux_model,
                SETTINGS.openai_api_key,
            ])
            if not configured:
                bad.append("At least one AI provider key/model must be configured")
        if not SETTINGS.paper_only: bad.append("PAPER_ONLY must remain true in this build")
        if bad:
            raise RuntimeError("Unsafe/incomplete production configuration: " + ", ".join(bad))
