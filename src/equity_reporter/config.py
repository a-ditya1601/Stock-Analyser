from __future__ import annotations

from pathlib import Path

from equity_reporter.models import SignalLabel, ThresholdBand, VerdictTier

DEFAULT_HISTORY_PERIOD = "1y"
DEFAULT_INTERVAL = "1d"
CHART_CONTEXT_HISTORY_PERIOD = "2y"
DEFAULT_CHART_LOOKBACK_DAYS = 126
CHART_CONTEXT_HISTORY_PERIOD_CANDIDATES: tuple[str, ...] = (
    CHART_CONTEXT_HISTORY_PERIOD,
    "3y",
    "5y",
    "max",
)
CHART_CONTEXT_FETCH_RETRIES = 2
MARKET_HISTORY_FETCH_RETRIES = 2
INFO_FETCH_RETRIES = 2
FETCH_RETRY_BACKOFF_SECONDS = 0.4
CHART_MIN_ROWS_FOR_FULL_SMA200 = 200 + DEFAULT_CHART_LOOKBACK_DAYS - 1
DEFAULT_OUTPUT_DIR = Path.cwd() / "reports"
FIB_SUPPORT_TOLERANCE_PCT = 0.01
FIB_BREAKOUT_BUFFER_PCT = 0.005
ATR_PERIOD = 14
TRADING_DAYS_PER_MONTH = 21
PROJECTION_HORIZON_MONTHS: dict[str, int] = {
    "1-2 months": 2,
    "3-4 months": 4,
    "5-6 months": 6,
}
ANALYST_BLEND_MAX_WEIGHT = 0.50

RISK_PROFILES = ("defensive", "balanced", "aggressive")

CATEGORY_WEIGHTS: dict[str, float] = {
    "fundamental": 32.0,
    "technical": 28.0,
    "volume_risk": 25.0,
    "peer_relativity": 15.0,
}

SIGNAL_LABEL_DISPLAY: dict[SignalLabel, str] = {
    SignalLabel.BULLISH: "Bullish",
    SignalLabel.BEARISH: "Bearish",
    SignalLabel.NEUTRAL: "Neutral",
    SignalLabel.WARNING: "Warning",
    SignalLabel.MISSING: "Missing",
}

SIGNAL_LABEL_SCORE: dict[SignalLabel, float] = {
    SignalLabel.BULLISH: 1.0,
    SignalLabel.NEUTRAL: 0.5,
    SignalLabel.WARNING: 0.3,
    SignalLabel.BEARISH: 0.0,
    SignalLabel.MISSING: 0.0,
}

VERDICT_TIERS: tuple[VerdictTier, ...] = (
    VerdictTier(min_score=75.0, verdict="STRONG BUY"),
    VerdictTier(min_score=60.0, verdict="ACCUMULATE / BUY"),
    VerdictTier(min_score=45.0, verdict="HOLD / NEUTRAL"),
    VerdictTier(min_score=30.0, verdict="TRIM / SELL"),
    VerdictTier(min_score=0.0, verdict="STRONG SELL"),
)

RSI_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=30.0, label=SignalLabel.BULLISH, score=1.0),
    ThresholdBand(min_inclusive=30.0, max_exclusive=70.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=70.0, label=SignalLabel.BEARISH, score=0.1),
)

ADX_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=20.0, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=20.0, max_exclusive=25.0, label=SignalLabel.NEUTRAL, score=0.5),
    ThresholdBand(min_inclusive=25.0, label=SignalLabel.BULLISH, score=0.8),
)

RELATIVE_VOLUME_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.85, label=SignalLabel.BEARISH, score=0.2),
    ThresholdBand(min_inclusive=0.85, max_exclusive=1.15, label=SignalLabel.NEUTRAL, score=0.5),
    ThresholdBand(min_inclusive=1.15, label=SignalLabel.BULLISH, score=0.8),
)

SHORT_PERCENT_FLOAT_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=5.0, label=SignalLabel.NEUTRAL, score=0.5),
    ThresholdBand(min_inclusive=5.0, max_exclusive=10.0, label=SignalLabel.WARNING, score=0.4),
    ThresholdBand(min_inclusive=10.0, label=SignalLabel.WARNING, score=0.2),
)

SHORT_RATIO_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=3.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=3.0, max_exclusive=7.0, label=SignalLabel.WARNING, score=0.4),
    ThresholdBand(min_inclusive=7.0, label=SignalLabel.WARNING, score=0.2),
)

ROE_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.08, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=0.08, max_exclusive=0.15, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=0.15, label=SignalLabel.BULLISH, score=0.9),
)

ROCE_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.0, label=SignalLabel.BEARISH, score=0.1),
    ThresholdBand(min_inclusive=0.0, max_exclusive=0.08, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=0.08, max_exclusive=0.15, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=0.15, label=SignalLabel.BULLISH, score=0.9),
)

PROFIT_MARGIN_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.0, label=SignalLabel.BEARISH, score=0.1),
    ThresholdBand(min_inclusive=0.0, max_exclusive=0.05, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=0.05, max_exclusive=0.15, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=0.15, label=SignalLabel.BULLISH, score=0.9),
)

DEBT_TO_EQUITY_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.5, label=SignalLabel.BULLISH, score=0.9),
    ThresholdBand(min_inclusive=0.5, max_exclusive=1.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=1.0, max_exclusive=2.0, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=2.0, label=SignalLabel.BEARISH, score=0.1),
)

CURRENT_RATIO_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=1.0, label=SignalLabel.BEARISH, score=0.2),
    ThresholdBand(min_inclusive=1.0, max_exclusive=1.2, label=SignalLabel.WARNING, score=0.4),
    ThresholdBand(min_inclusive=1.2, max_exclusive=3.0, label=SignalLabel.BULLISH, score=0.8),
    ThresholdBand(min_inclusive=3.0, max_exclusive=4.0, label=SignalLabel.NEUTRAL, score=0.5),
    ThresholdBand(min_inclusive=4.0, label=SignalLabel.WARNING, score=0.4),
)

REVENUE_GROWTH_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=-0.10, label=SignalLabel.BEARISH, score=0.1),
    ThresholdBand(min_inclusive=-0.10, max_exclusive=0.0, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=0.0, max_exclusive=0.10, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=0.10, label=SignalLabel.BULLISH, score=0.9),
)

FCF_TO_DEBT_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.0, label=SignalLabel.BEARISH, score=0.1),
    ThresholdBand(min_inclusive=0.0, max_exclusive=0.10, label=SignalLabel.WARNING, score=0.3),
    ThresholdBand(min_inclusive=0.10, max_exclusive=0.50, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=0.50, label=SignalLabel.BULLISH, score=0.9),
)

PEER_FORWARD_PE_PREMIUM_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=-10.0, label=SignalLabel.BULLISH, score=0.9),
    ThresholdBand(min_inclusive=-10.0, max_exclusive=10.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=10.0, max_exclusive=25.0, label=SignalLabel.WARNING, score=0.35),
    ThresholdBand(min_inclusive=25.0, label=SignalLabel.BEARISH, score=0.1),
)

PEER_PE_TO_SECTOR_PE_RATIO_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=0.90, label=SignalLabel.BULLISH, score=0.9),
    ThresholdBand(min_inclusive=0.90, max_exclusive=1.10, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=1.10, max_exclusive=1.30, label=SignalLabel.WARNING, score=0.35),
    ThresholdBand(min_inclusive=1.30, label=SignalLabel.BEARISH, score=0.1),
)

PEER_PS_PREMIUM_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(max_exclusive=-10.0, label=SignalLabel.BULLISH, score=0.9),
    ThresholdBand(min_inclusive=-10.0, max_exclusive=10.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=10.0, max_exclusive=30.0, label=SignalLabel.WARNING, score=0.35),
    ThresholdBand(min_inclusive=30.0, label=SignalLabel.BEARISH, score=0.1),
)

PEER_MARGIN_SPREAD_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(min_inclusive=3.0, label=SignalLabel.BULLISH, score=0.9),
    ThresholdBand(min_inclusive=-2.0, max_exclusive=3.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=-6.0, max_exclusive=-2.0, label=SignalLabel.WARNING, score=0.35),
    ThresholdBand(max_exclusive=-6.0, label=SignalLabel.BEARISH, score=0.1),
)

PEER_GROWTH_SPREAD_BANDS: tuple[ThresholdBand, ...] = (
    ThresholdBand(min_inclusive=5.0, label=SignalLabel.BULLISH, score=0.9),
    ThresholdBand(min_inclusive=-3.0, max_exclusive=5.0, label=SignalLabel.NEUTRAL, score=0.6),
    ThresholdBand(min_inclusive=-8.0, max_exclusive=-3.0, label=SignalLabel.WARNING, score=0.35),
    ThresholdBand(max_exclusive=-8.0, label=SignalLabel.BEARISH, score=0.1),
)

BETA_BANDS_BY_RISK_PROFILE: dict[str, tuple[ThresholdBand, ...]] = {
    "defensive": (
        ThresholdBand(max_exclusive=0.8, label=SignalLabel.BULLISH, score=1.0),
        ThresholdBand(min_inclusive=0.8, max_exclusive=1.2, label=SignalLabel.NEUTRAL, score=0.6),
        ThresholdBand(min_inclusive=1.2, label=SignalLabel.BEARISH, score=0.2),
    ),
    "balanced": (
        ThresholdBand(max_exclusive=0.8, label=SignalLabel.NEUTRAL, score=0.5),
        ThresholdBand(min_inclusive=0.8, max_exclusive=1.3, label=SignalLabel.BULLISH, score=0.8),
        ThresholdBand(min_inclusive=1.3, label=SignalLabel.WARNING, score=0.4),
    ),
    "aggressive": (
        ThresholdBand(max_exclusive=1.0, label=SignalLabel.NEUTRAL, score=0.4),
        ThresholdBand(min_inclusive=1.0, max_exclusive=1.8, label=SignalLabel.BULLISH, score=0.8),
        ThresholdBand(min_inclusive=1.8, label=SignalLabel.WARNING, score=0.5),
    ),
}

METRIC_THRESHOLD_MAP: dict[str, tuple[ThresholdBand, ...]] = {
    "rsi_14": RSI_BANDS,
    "adx_14": ADX_BANDS,
    "relative_volume_10d_3m": RELATIVE_VOLUME_BANDS,
    "return_on_equity": ROE_BANDS,
    "return_on_capital_employed": ROCE_BANDS,
    "profit_margin": PROFIT_MARGIN_BANDS,
    "operating_margin": PROFIT_MARGIN_BANDS,
    "debt_to_equity": DEBT_TO_EQUITY_BANDS,
    "current_ratio": CURRENT_RATIO_BANDS,
    "quarterly_revenue_growth": REVENUE_GROWTH_BANDS,
    "short_ratio": SHORT_RATIO_BANDS,
    "short_percent_of_float": SHORT_PERCENT_FLOAT_BANDS,
    "fcf_to_debt": FCF_TO_DEBT_BANDS,
    "peer_forward_pe_premium": PEER_FORWARD_PE_PREMIUM_BANDS,
    "peer_pe_to_sector_pe_ratio": PEER_PE_TO_SECTOR_PE_RATIO_BANDS,
    "peer_ps_premium": PEER_PS_PREMIUM_BANDS,
    "peer_margin_spread": PEER_MARGIN_SPREAD_BANDS,
    "peer_growth_spread": PEER_GROWTH_SPREAD_BANDS,
}

CATEGORY_METRIC_WEIGHTS: dict[str, dict[str, float]] = {
    "fundamental": {
        "fcf_vs_debt": 7.0,
        "return_on_equity": 6.0,
        "return_on_capital_employed": 6.0,
        "quarterly_revenue_growth": 5.0,
        "profit_margin": 4.0,
        "operating_margin": 4.0,
        "valuation_pe_trend": 4.0,
        "debt_to_equity": 4.0,
        "current_ratio": 3.0,
    },
    "technical": {
        "sma_crossover": 7.0,
        "ichimoku_cloud": 6.0,
        "macd_crossover": 5.0,
        "rsi_14": 5.0,
        "adx_trend_strength": 4.0,
        "bollinger_position": 4.0,
        "fibonacci_support_breakout": 4.0,
    },
    "volume_risk": {
        "obv_30d_trend": 7.0,
        "relative_volume_10d_3m": 6.0,
        "futures_oi_buildup": 5.0,
        "rollover_percentage": 4.0,
        "pcr_sentiment": 3.0,
        "iv_percentile": 3.0,
    },
    "peer_relativity": {
        "peer_pe_to_sector_pe_ratio": 5.0,
        "peer_ps_premium": 4.0,
        "peer_margin_spread": 3.0,
        "peer_growth_spread": 3.0,
    },
}
