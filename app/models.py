from __future__ import annotations

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"

    def opposite(self) -> "Direction":
        if self == Direction.BUY:
            return Direction.SELL
        if self == Direction.SELL:
            return Direction.BUY
        return Direction.NEUTRAL


class Grade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B_PLUS = "B+"
    REJECT = "REJECT"


class ZoneState(str, Enum):
    ACTIVE = "ACTIVE"
    FAILED_FLIP_CANDIDATE = "FAILED_FLIP_CANDIDATE"
    FLIP_ACTIVE = "FLIP_ACTIVE"
    RETIRED = "RETIRED"


class Bar(BaseModel):
    ts: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0.0


class NewsEvent(BaseModel):
    ts: int
    currency: str = "USD"
    title: str = ""
    impact: str = "HIGH"
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None


class MarketSnapshot(BaseModel):
    protocol: int = 6
    kind: str = "LIVE"
    reason: str = "TICK"
    sent_at: int
    xau_symbol: str = "XAUUSD"
    dxy_symbol: str = "DXYUSD"
    bid: float
    ask: float
    spread_points: float
    point: float = 0.01
    atr_h1: float = 0.0
    atr_m15: float = 0.0
    xau_d1: List[Bar] = Field(default_factory=list)
    xau_h4: List[Bar] = Field(default_factory=list)
    xau_h1: List[Bar] = Field(default_factory=list)
    xau_m15: List[Bar] = Field(default_factory=list)
    dxy_d1: List[Bar] = Field(default_factory=list)
    dxy_h4: List[Bar] = Field(default_factory=list)
    dxy_h1: List[Bar] = Field(default_factory=list)
    news: List[NewsEvent] = Field(default_factory=list)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    def complete(self) -> bool:
        return all([
            len(self.xau_d1) >= 80,
            len(self.xau_h4) >= 120,
            len(self.xau_h1) >= 160,
            len(self.xau_m15) >= 160,
            len(self.dxy_d1) >= 60,
            len(self.dxy_h4) >= 80,
            len(self.dxy_h1) >= 100,
        ])


class LiquidityLevel(BaseModel):
    label: str
    price: float
    side: str
    source_tf: str
    distance: float


class Zone(BaseModel):
    zone_id: str
    original_direction: Direction
    flip_direction: Direction
    setup_type: str
    source_tf: str
    grade: Grade
    state: ZoneState = ZoneState.ACTIVE
    core_low: float
    core_high: float
    core_method: str
    location_score: float
    zone_low: float
    zone_high: float
    touch_count: int = 0
    confluences: List[str] = Field(default_factory=list)
    independent_confluence_count: int = 0
    requires_sweep: bool = True
    source_ts: int = 0
    invalidation_level: float
    invalidation_rule: str
    original_target1: float = 0.0
    original_target2: float = 0.0
    original_target3: float = 0.0
    original_runner: float = 0.0
    flip_target1: float = 0.0
    flip_target2: float = 0.0
    flip_target3: float = 0.0
    flip_runner: float = 0.0
    clear_run: float = 0.0
    countertrend: bool = False
    dxy_support: str = "NEUTRAL"
    notes: List[str] = Field(default_factory=list)


class Analysis(BaseModel):
    analysis_id: str
    generated_at: int
    snapshot_at: int
    overall_bias: Direction = Direction.NEUTRAL
    primary_liquidity: str = ""
    liquidity_map: List[LiquidityLevel] = Field(default_factory=list)
    zones: List[Zone] = Field(default_factory=list)
    selected_zone_id: str = ""
    trader_brief: str = ""
    ai_provider: str = "DETERMINISTIC"
    ai_approved: bool = False
    approved: bool = False
    prompt_version: str = "SMC_V6_DUAL_BRANCH"
    execution_policy: Dict[str, Any] = Field(default_factory=dict)
    guards: List[str] = Field(default_factory=list)


class Heartbeat(BaseModel):
    ts: int
    ea: str
    version: str
    symbol: str
    account_login: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class Feedback(BaseModel):
    ts: int
    event: str
    analysis_id: str = ""
    zone_id: str = ""
    price: float = 0.0
    details: Any = Field(default_factory=dict)


class MLCandidateTelemetry(BaseModel):
    """Frozen candidate-time feature packet from MT5 execution engines.

    This is observation/shadow telemetry only. It never authorizes a trade, changes
    risk, or replaces the deterministic SMC/ICT execution and safety gates.
    """
    candidate_id: str = ""
    ts: int
    source: str = "MT5_EXECUTION"
    source_version: str = ""
    analysis_id: str = ""
    zone_id: str = ""
    model: str
    direction: Direction
    eligible: bool = True
    rejection_reasons: List[str] = Field(default_factory=list)
    entry_price: float = 0.0
    stop_price: float = 0.0
    target1: float = 0.0
    target2: float = 0.0
    target3: float = 0.0
    atr: float = 0.0
    regime: str = "UNKNOWN"
    features: Dict[str, Any] = Field(default_factory=dict)
