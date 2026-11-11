from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


class SignalLabel(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    WARNING = "warning"
    MISSING = "missing"


@dataclass(slots=True, frozen=True)
class ThresholdBand:
    min_inclusive: float | None = None
    max_exclusive: float | None = None
    label: SignalLabel = SignalLabel.NEUTRAL
    score: float = 0.0

    def matches(self, value: float) -> bool:
        min_ok = self.min_inclusive is None or value >= self.min_inclusive
        max_ok = self.max_exclusive is None or value < self.max_exclusive
        return min_ok and max_ok


@dataclass(slots=True, frozen=True)
class VerdictTier:
    min_score: float
    verdict: str


@dataclass(slots=True)
class MetricSignal:
    key: str
    value: float | int | str | None = None
    label: SignalLabel = SignalLabel.MISSING
    score: float = 0.0
    weight: float = 0.0
    note: str = ""
    available: bool = False


@dataclass(slots=True)
class FundamentalMetrics:
    forward_pe: float | None = None
    trailing_pe: float | None = None
    return_on_equity: float | None = None
    return_on_capital_employed: float | None = None
    profit_margin: float | None = None
    operating_margin: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quarterly_revenue_growth: float | None = None
    beta: float | None = None
    beta_1y: float | None = None
    beta_2y: float | None = None
    beta_5y: float | None = None
    beta_1m: float | None = None
    beta_weekly: float | None = None
    beta_benchmark: str | None = None
    short_ratio: float | None = None
    short_percent_of_float: float | None = None
    free_cash_flow: float | None = None
    total_debt: float | None = None


@dataclass(slots=True)
class TechnicalMetrics:
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    bb_lower: float | None = None
    bb_middle: float | None = None
    bb_upper: float | None = None
    adx_14: float | None = None
    ichimoku_span_a: float | None = None
    ichimoku_span_b: float | None = None


@dataclass(slots=True)
class VolumeMetrics:
    obv: float | None = None
    obv_30d_slope: float | None = None
    avg_volume_10d: float | None = None
    avg_volume_3m: float | None = None


@dataclass(slots=True)
class FnoMetrics:
    pcr: float | None = None
    futures_oi_buildup: str | None = None
    rollover_pct: float | None = None
    iv_percentile: float | None = None
    atm_iv: float | None = None
    max_pain: float | None = None
    expiry: str | None = None
    source_available: bool = False
    availability_status: str = "unavailable"
    note: str = ""


@dataclass(slots=True)
class FibonacciLevels:
    high_6m: float | None = None
    low_6m: float | None = None
    level_0_382: float | None = None
    level_0_500: float | None = None
    level_0_618: float | None = None


@dataclass(slots=True)
class MarketSnapshot:
    ticker: str
    history: pd.DataFrame
    info: dict[str, Any]
    current_price: float | None = None
    company_metadata: dict[str, Any] = field(default_factory=dict)
    fast_info: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None
    history_source: str = "yfinance"
    history_note: str = ""


@dataclass(slots=True)
class ScoreCard:
    final_score: float = 0.0
    verdict: str = "PENDING"
    category_scores: dict[str, float] = field(default_factory=dict)
    category_weights: dict[str, float] = field(default_factory=dict)
    metric_signals: dict[str, MetricSignal] = field(default_factory=dict)
    max_score: float = 100.0
    data_coverage_pct: float = 0.0


@dataclass(slots=True)
class ProjectionRange:
    bear: float
    base: float
    bull: float


@dataclass(slots=True)
class ProjectionScenarios:
    horizons: dict[str, ProjectionRange] = field(default_factory=dict)
    atr_14: float | None = None
    monthly_swing: float | None = None
    methodology: str = ""
    projection_confidence: str = ""
    support_levels: list[dict[str, Any]] = field(default_factory=list)
    resistance_levels: list[dict[str, Any]] = field(default_factory=list)
    volume_profile_poc: float | None = None
    volume_profile_hvns: list[float] = field(default_factory=list)
    scenario_probabilities: dict[str, dict[str, float]] = field(default_factory=dict)
    fallback_reason: str = ""
    analyst_target_mean: float | None = None
    analyst_target_low: float | None = None
    analyst_target_high: float | None = None
    analyst_opinions: int | None = None
    analyst_blend_applied: bool = False
    blend_weights: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ReportContext:
    snapshot: MarketSnapshot
    signals: dict[str, MetricSignal] = field(default_factory=dict)
    fundamentals: FundamentalMetrics = field(default_factory=FundamentalMetrics)
    technicals: TechnicalMetrics = field(default_factory=TechnicalMetrics)
    volumes: VolumeMetrics = field(default_factory=VolumeMetrics)
    fno: FnoMetrics = field(default_factory=FnoMetrics)
    fibonacci: FibonacciLevels = field(default_factory=FibonacciLevels)
    scorecard: ScoreCard = field(default_factory=ScoreCard)
    projections: ProjectionScenarios = field(default_factory=ProjectionScenarios)
    chart_path: Path | None = None
