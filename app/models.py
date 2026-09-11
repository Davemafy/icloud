from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Bias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Direction(str, Enum):
    BUY_ONLY = "BUY_ONLY"
    SELL_ONLY = "SELL_ONLY"
    BUY_SELL = "BUY_SELL"
    NO_TRADE = "NO_TRADE"


class Grade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B_PLUS = "B+"
    REJECT = "REJECT"


class DxyImplication(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONFLICTS = "CONFLICTS"
    NEUTRAL = "NEUTRAL"


class Visibility(str, Enum):
    OBSERVED = "OBSERVED_FACT"
    PROBABLE = "PROBABLE_NOT_CONFIRMED"
    NOT_VISIBLE = "NOT_VISIBLE_ON_CHART"


class Candle(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @model_validator(mode="after")
    def validate_ohlc(self):
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("Invalid OHLC candle")
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self


class TimeframeBars(BaseModel):
    symbol: str
    timeframe: str
    bars: List[Candle] = Field(min_length=20)
    atr: Optional[float] = None


class NewsEvent(BaseModel):
    event_id: str = ""
    ts: datetime
    currency: str = "USD"
    impact: str = "HIGH"
    title: str
    released: bool = False
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
    source: str = "manual"


class MarketSnapshot(BaseModel):
    # v3 separates heavy historical-context syncs from lightweight live updates.
    # v2 payloads remain accepted for backwards compatibility.
    schema_version: int = 3
    generated_at: datetime
    broker_time: Optional[datetime] = None
    session: str
    timezone: str = "Africa/Lagos"
    snapshot_kind: str = "FULL_HISTORY"
    snapshot_reason: str = "LEGACY_OR_MANUAL"
    xau: Dict[str, TimeframeBars]
    dxy: Dict[str, TimeframeBars]
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_points: float = Field(ge=0)
    spread_price: Optional[float] = Field(default=None, ge=0)
    point_size: float = Field(default=0.001, gt=0)
    atr_period: int = Field(default=14, ge=2, le=100)
    # Informational counts requested by the MT5 bridge for the full historical profile.
    history_profile: Dict[str, int] = Field(default_factory=dict)
    news: List[NewsEvent] = Field(default_factory=list)
    source: str = "MT5"
    account_mode: str = "DEMO"


    @model_validator(mode="after")
    def validate_symbol_integrity(self):
        # Protocol-v3 MT5 bridge packets must keep XAU and DXY streams distinct.
        # This prevents an EA attached to a DXY chart from overwriting XAU context.
        if self.schema_version >= 3 and self.source.upper().startswith("MT5_BRIDGE"):
            xau_symbols = {s.symbol.upper() for s in self.xau.values() if s.symbol}
            dxy_symbols = {s.symbol.upper() for s in self.dxy.values() if s.symbol}
            if not xau_symbols or not dxy_symbols:
                raise ValueError("MT5 bridge snapshot must contain both XAU and DXY symbol streams")
            if xau_symbols & dxy_symbols:
                raise ValueError(f"XAU/DXY symbol collision detected: {sorted(xau_symbols & dxy_symbols)}")

            # Broker quote must belong to XAU, not DXY. Compare it with the latest
            # XAU M15 close using a deliberately wide tolerance for genuine gaps.
            m15 = self.xau.get("M15")
            if self.bid is not None and self.ask is not None and m15 and m15.bars:
                mid = (self.bid + self.ask) / 2.0
                ref = m15.bars[-1].close
                atr = m15.atr or 0.0
                tolerance = max(abs(ref) * 0.05, atr * 10.0)
                if abs(mid - ref) > tolerance:
                    raise ValueError(
                        f"XAU quote mismatch: broker mid={mid:.8f} latest XAU M15 close={ref:.8f}"
                    )
        return self


class Zone(BaseModel):
    # Execution/visual zones are XAU-only. DXY is intermarket analysis context and
    # must never become an execution-zone instrument.
    instrument: str = "XAUUSD"
    zone_id: str
    direction: Direction
    zone_low: float
    zone_high: float
    grade: Grade
    source_tf: str
    # Top-down role of the zone in the day map. CONTINUATION follows the resolved
    # D1/H4/H1 directional stack; REVERSAL is the opposite-side institutional
    # location; TRANSITION is used only when the higher-timeframe stack is neutral.
    setup_type: str = "UNCLASSIFIED"
    authority_stack: List[str] = Field(default_factory=list)
    touch_count: int = 0
    freshness: str = "UNKNOWN"
    requires_sweep: str
    min_displacement_atr: float = 1.0
    min_rr: float = 2.0
    target1: Optional[float] = None
    target2: Optional[float] = None
    target3: Optional[float] = None
    runner: Optional[float] = None
    invalidation: str
    confluences: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    provenance: List[str] = Field(default_factory=list)
    # Canonical institutional evidence. These fields are informational for the cloud/dashboard
    # and do not change the MT5 plan protocol.
    source_candle_ts: Optional[datetime] = None
    source_candle_low: Optional[float] = None
    source_candle_high: Optional[float] = None
    displacement_ts: Optional[datetime] = None
    structure_break: Optional[str] = None
    structure_break_level: Optional[float] = None
    fvg_low: Optional[float] = None
    fvg_high: Optional[float] = None
    tick_volume_ratio: Optional[float] = None
    psychological_level: Optional[float] = None
    invalidation_level: Optional[float] = None
    invalidation_tf: Optional[str] = None

    @model_validator(mode="after")
    def order_prices(self):
        if self.zone_low > self.zone_high:
            self.zone_low, self.zone_high = self.zone_high, self.zone_low
        return self


class AIZoneDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_zone_id: str
    use_zone: bool
    grade: Grade
    direction: Direction
    required_sweep: str
    min_displacement_atr: float = Field(ge=0.5, le=3.0)
    institutional_interpretation: str
    execution_condition: str
    downgrade_reason: Optional[str]


class AIDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dxy_d1_bias: Bias
    dxy_h4_bias: Bias
    dxy_h1_bias: Bias
    xau_d1_bias: Bias
    xau_h4_bias: Bias
    xau_h1_bias: Bias
    xau_m15_context: Bias
    overall_bias: Bias
    dxy_implication: DxyImplication
    primary_liquidity: str
    no_trade: bool
    no_trade_reason: Optional[str]
    zone_decisions: List[AIZoneDecision]
    expected_sequence: str
    retail_trap: str
    overall_invalidation: str
    trader_brief: str


class ValidationIssue(BaseModel):
    severity: str
    code: str
    message: str


class InstitutionalAnalysis(BaseModel):
    schema_version: int = 2
    analysis_id: str
    generated_at: datetime
    valid_until: datetime
    snapshot_id: str
    session: str
    current_xau_price: float
    current_dxy_price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_points: float
    spread_price: Optional[float] = None
    xau_d1_atr: Optional[float] = None
    xau_h4_atr: Optional[float] = None
    xau_h1_atr: Optional[float] = None
    xau_m15_atr: Optional[float] = None
    dxy_d1_bias: Bias
    dxy_h4_bias: Bias
    dxy_h1_bias: Bias
    xau_d1_bias: Bias
    xau_h4_bias: Bias
    xau_h1_bias: Bias
    xau_m15_context: Bias
    overall_bias: Bias
    dxy_implication: DxyImplication
    primary_liquidity: str
    expected_sequence: str = ""
    retail_trap: str = ""
    overall_invalidation: str = ""
    trader_brief: str = ""
    zones: List[Zone]
    ea_mode: Direction
    no_trade_reason: Optional[str] = None
    post_news: bool = False
    news_blackout: bool = False
    ai_used: bool = False
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_response_id: Optional[str] = None
    validator_issues: List[ValidationIssue] = Field(default_factory=list)
    source_fingerprint: str
    prompt_version: str = "SMC_V3_1_MULTI_PROVIDER_FIB_EXEC"
    # Deterministic feature map supporting the original manual institutional-analysis contract.
    # It contains only values derived from supplied XAU/DXY candles and broker/news inputs.
    analysis_evidence: Dict[str, object] = Field(default_factory=dict)
    approved: bool = False


class TradeFeedback(BaseModel):
    ts: datetime
    signal_id: str
    event: str
    symbol: str = "XAUUSD"
    price: Optional[float] = None
    details: str = ""
    pnl: Optional[float] = None
    rr_realized: Optional[float] = None


class Heartbeat(BaseModel):
    ts: datetime
    terminal: str = "MT5"
    account_mode: str = "DEMO"
    symbol: str = "XAUUSD"
    ea_version: str = ""
    details: str = ""


class PlanAck(BaseModel):
    ts: datetime
    analysis_id: str
    zone_id: str
    terminal: str = "MT5"


class ManualNewsTrigger(BaseModel):
    event_id: str
    ts: datetime
    title: str
    currency: str = "USD"
    impact: str = "HIGH"
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None


class ReplayRequest(BaseModel):
    snapshot: MarketSnapshot
    label: str = ""


class ReplayResult(BaseModel):
    replay_id: str
    analysis: InstitutionalAnalysis
    label: str = ""
