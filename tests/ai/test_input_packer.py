from __future__ import annotations

from datetime import datetime

import pandas as pd

from equity_reporter.ai.input_packer import DATA_UNAVAILABLE, build_ai_input_payload
from equity_reporter.models import MarketSnapshot, MetricSignal, ProjectionRange, ProjectionScenarios, ScoreCard, SignalLabel


def _snapshot() -> MarketSnapshot:
    history = pd.DataFrame(
        {
            "Close": [100.0, 101.5, 102.0],
            "Volume": [1000, 1100, 1200],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
    )
    return MarketSnapshot(
        ticker="TEST.NS",
        history=history,
        info={},
        current_price=102.0,
        company_metadata={"company_name": "Test Industries", "exchange": "NSE", "currency": "INR"},
        fast_info={},
        fetched_at=datetime(2026, 4, 24, 12, 0, 0),
    )


def test_ai_input_packer_converts_missing_values_to_data_unavailable() -> None:
    snapshot = _snapshot()
    signals = {
        "risk_profile": "balanced",
        "forward_pe": None,
        "trailing_pe": 22.4,
        "beta": None,
        "sma_20": None,
        "short_ratio": None,
        "fib_0_382": float("nan"),
        "fundamental_signals": {},
        "technical_signals": {},
        "volume_signals": {},
        "fibonacci_signal": None,
    }
    projections = ProjectionScenarios(
        horizons={},
        analyst_blend_applied=False,
    )
    scorecard = ScoreCard(
        final_score=51.25,
        verdict="HOLD / NEUTRAL",
        data_coverage_pct=62.0,
        category_scores={"fundamental": 55.0, "technical": 51.0, "volume_risk": 46.0},
        category_weights={"fundamental": 40.0, "technical": 35.0, "volume_risk": 25.0},
        metric_signals={},
    )

    payload = build_ai_input_payload(snapshot, signals, projections, scorecard)

    assert payload["fundamentals"]["forward_pe"]["value"] == DATA_UNAVAILABLE
    assert payload["fundamentals"]["return_on_capital_employed"]["value"] == DATA_UNAVAILABLE
    assert payload["fundamentals"]["operating_margin"]["value"] == DATA_UNAVAILABLE
    assert payload["fundamentals"]["beta_1y_daily"]["value"] == DATA_UNAVAILABLE
    assert payload["technical"]["sma_20"] == DATA_UNAVAILABLE
    assert payload["derivatives_smart_money"]["pcr"]["value"] == DATA_UNAVAILABLE
    assert payload["fibonacci"]["level_0_382"] == DATA_UNAVAILABLE
    assert payload["projections"]["horizons"] == DATA_UNAVAILABLE
    assert payload["scoring"]["metric_breakdown"] == DATA_UNAVAILABLE
    assert payload["projections"]["analyst_blend_applied"] is False
    assert "final_confidence_pct" not in payload["scoring"]
    assert "final_verdict" not in payload["scoring"]


def test_ai_input_packer_builds_normalized_metric_and_score_sections() -> None:
    snapshot = _snapshot()
    valuation_signal = MetricSignal(
        key="valuation_pe_trend",
        value=0.95,
        label=SignalLabel.BULLISH,
        score=0.9,
        available=True,
        note="Forward P/E is below trailing P/E.",
    )
    adx_signal = MetricSignal(
        key="adx_trend_strength",
        value=27.5,
        label=SignalLabel.BULLISH,
        score=0.85,
        available=True,
        note="Trend strength confirmed.",
    )
    fib_signal = MetricSignal(
        key="fibonacci_support_breakout",
        value=101.0,
        label=SignalLabel.NEUTRAL,
        score=0.6,
        available=True,
        note="Price is between key levels.",
    )
    score_signal = MetricSignal(
        key="valuation_pe_trend",
        value=0.95,
        label=SignalLabel.BULLISH,
        score=0.9,
        weight=4.0,
        available=True,
        note="Contribution metric.",
    )
    peer_pe_ratio_signal = MetricSignal(
        key="peer_pe_to_sector_pe_ratio",
        value=0.92,
        label=SignalLabel.BULLISH,
        score=0.9,
        available=True,
        note="Target trades below the peer forward P/E basket.",
    )

    signals = {
        "risk_profile": "balanced",
        "forward_pe": 20.0,
        "trailing_pe": 21.0,
        "return_on_capital_employed": 0.18,
        "operating_margin": 0.22,
        "beta": 1.11,
        "beta_2y": 1.18,
        "beta_5y": 1.05,
        "beta_1m": 1.34,
        "beta_weekly": 1.27,
        "beta_benchmark": "^NSEI",
        "sma_20": 101.2,
        "adx_14": 27.5,
        "fno_pcr": 1.42,
        "fno_futures_oi_buildup": "Long Build-up",
        "fno_rollover_pct": 78.0,
        "fno_atm_iv": 22.4,
        "fno_max_pain": 100.0,
        "fno_expiry": "30-May-2026",
        "fno_text_block": "Derivatives & Smart Money Flow: test.",
        "fib_0_382": 105.2,
        "fib_0_500": 100.0,
        "fib_0_618": 95.8,
        "fundamental_signals": {"valuation_pe_trend": valuation_signal},
        "technical_signals": {"adx_trend_strength": adx_signal},
        "peer_pe_to_sector_pe_ratio": 0.92,
        "peer_signals": {"peer_pe_to_sector_pe_ratio": peer_pe_ratio_signal},
        "volume_signals": {
            "pcr_sentiment": MetricSignal(
                key="pcr_sentiment",
                value=1.42,
                label=SignalLabel.BULLISH,
                score=1.0,
                available=True,
                note="PCR bullish.",
            )
        },
        "fibonacci_signal": fib_signal,
    }
    projections = ProjectionScenarios(
        horizons={
            "1-2 months": ProjectionRange(bear=95.0, base=103.0, bull=112.0),
        },
        atr_14=2.4,
        monthly_swing=11.0,
        analyst_target_mean=109.0,
        analyst_target_low=98.0,
        analyst_target_high=121.0,
        analyst_opinions=22,
        analyst_blend_applied=True,
        blend_weights={"1-2 months": 0.35},
    )
    scorecard = ScoreCard(
        final_score=68.4,
        verdict="ACCUMULATE / BUY",
        data_coverage_pct=88.0,
        category_scores={"fundamental": 70.0, "technical": 66.0, "volume_risk": 64.0},
        category_weights={"fundamental": 40.0, "technical": 35.0, "volume_risk": 25.0},
        metric_signals={"valuation_pe_trend": score_signal},
    )

    payload = build_ai_input_payload(snapshot, signals, projections, scorecard)

    assert payload["meta"]["ticker"] == "TEST.NS"
    assert payload["meta"]["currency"] == "INR"
    assert payload["fundamentals"]["forward_pe"]["signal"]["label"] == "bullish"
    assert payload["fundamentals"]["return_on_capital_employed"]["value"] == 0.18
    assert payload["fundamentals"]["operating_margin"]["value"] == 0.22
    assert payload["technical"]["sma_20"] == 101.2
    assert payload["technical"]["adx_14"]["signal"]["label"] == "bullish"
    assert payload["derivatives_smart_money"]["pcr"]["signal"]["label"] == "bullish"
    assert payload["derivatives_smart_money"]["text_block"] == "Derivatives & Smart Money Flow: test."
    assert payload["peer_relativity"]["pe_to_sector_pe_ratio"]["signal"]["label"] == "bullish"
    assert payload["fibonacci"]["support_breakout_signal"]["label"] == "neutral"
    assert payload["projections"]["horizons"]["1-2 months"]["bull_case"] == 112.0
    assert "final_confidence_pct" not in payload["scoring"]
    assert "final_verdict" not in payload["scoring"]
    assert payload["scoring"]["metric_breakdown"][0]["contribution_points"] == 3.6
