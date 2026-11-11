from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from equity_reporter.ai.input_packer import DATA_UNAVAILABLE
from equity_reporter.ai.prompt_composer import build_structured_prompt_input
from equity_reporter.models import MarketSnapshot, MetricSignal, ProjectionRange, ProjectionScenarios, ScoreCard, SignalLabel


def _snapshot() -> MarketSnapshot:
    history = pd.DataFrame(
        {
            "Close": [100.0, 102.0, 101.5],
            "High": [101.0, 103.0, 102.0],
            "Low": [99.5, 100.5, 100.0],
            "Volume": [1000, 1200, 1100],
        },
        index=pd.to_datetime(["2026-04-20", "2026-04-21", "2026-04-22"]),
    )
    return MarketSnapshot(
        ticker="TEST.BO",
        history=history,
        info={},
        current_price=101.5,
        company_metadata={"company_name": "Test Corp", "exchange": "BSE", "currency": "INR"},
        fetched_at=datetime(2026, 4, 24, 12, 30),
    )


def _baseline_signals() -> dict[str, object]:
    return {
        "risk_profile": "balanced",
        "beta_benchmark": "^BSESN",
        "fundamental_signals": {},
        "technical_signals": {},
        "volume_signals": {},
        "fibonacci_signal": None,
    }


def _baseline_projections() -> ProjectionScenarios:
    return ProjectionScenarios(
        horizons={
            "1-2 months": ProjectionRange(bear=95.0, base=102.0, bull=110.0),
            "3-4 months": ProjectionRange(bear=92.0, base=104.0, bull=116.0),
            "5-6 months": ProjectionRange(bear=90.0, base=106.0, bull=120.0),
        },
        atr_14=2.4,
        monthly_swing=10.2,
        analyst_blend_applied=False,
    )


def _baseline_scorecard() -> ScoreCard:
    return ScoreCard(
        final_score=58.2,
        verdict="HOLD / NEUTRAL",
        data_coverage_pct=75.0,
        category_scores={"fundamental": 60.0, "technical": 55.0, "volume_risk": 58.0, "peer_relativity": 50.0},
        category_weights={"fundamental": 34.0, "technical": 30.0, "volume_risk": 21.0, "peer_relativity": 15.0},
        metric_signals={},
    )


def test_prompt_composer_replaces_missing_values_with_data_unavailable() -> None:
    snapshot = _snapshot()
    signals = _baseline_signals()
    signals["beta_2y"] = None
    signals["short_ratio"] = None

    result = build_structured_prompt_input(snapshot, signals, _baseline_projections(), _baseline_scorecard())

    assert result.payload["fundamentals"]["beta_2y_daily"] == DATA_UNAVAILABLE
    assert result.payload["fundamentals"]["short_ratio"]["value"] == DATA_UNAVAILABLE
    assert '"Data Unavailable"' in result.payload_json


def test_prompt_composer_contains_required_sections_and_guardrails() -> None:
    result = build_structured_prompt_input(
        _snapshot(),
        _baseline_signals(),
        _baseline_projections(),
        _baseline_scorecard(),
    )
    assert "final_confidence_pct" not in result.payload["scoring"]
    assert "final_verdict" not in result.payload["scoring"]

    for heading in (
        "## 1. Fundamental Deep-Dive & Valuation",
        "## 2. Technical Posture & Institutional Liquidity",
        "## 3. Volatility, F&O, & Risk Matrix",
        "## 4. Tactical Execution Plan",
        "## 5. Manual Trade Management & Invalidation Rules",
        "## 6. Scenario Modeling & Probability Matrix",
        "## 7. Macro Stress Test",
        "## 8. Sector Relativity & Peer Valuations",
        "## 9. Executive Summary & Verdict",
    ):
        assert heading in result.user_prompt

    for phrase in (
        "Volume Profile",
        "Point of Control",
        "High Volume Nodes",
        "Options IV Expected Move",
        "Empirical Historical Return Quantiles",
        "S/R Gravity Wells",
        "deterministic peer basket",
        "Operating Margin",
        "Return on Capital Employed",
        "PE-to-sector-PE ratio",
    ):
        assert phrase in result.user_prompt

    for forbidden_phrase in (
        "Binary Catalysts",
        "Earnings",
        "Board Meetings",
        "Gap Risk",
        "IV Crush",
    ):
        assert forbidden_phrase not in result.user_prompt

    assert "Use ONLY the provided payload" in result.user_prompt
    assert "Do not use external data, news, events, or web knowledge." in result.user_prompt
    assert "Do not hallucinate missing metrics." in result.user_prompt


def test_prompt_composer_uses_dynamic_benchmark_not_hardcoded() -> None:
    result = build_structured_prompt_input(
        _snapshot(),
        _baseline_signals(),
        _baseline_projections(),
        _baseline_scorecard(),
    )
    assert "^BSESN" in result.user_prompt
    assert "^NSEI" not in result.user_prompt


def test_prompt_composer_payload_json_is_valid_and_stable() -> None:
    snapshot = _snapshot()
    signals = _baseline_signals()
    projections = _baseline_projections()
    scorecard = _baseline_scorecard()

    first = build_structured_prompt_input(snapshot, signals, projections, scorecard)
    second = build_structured_prompt_input(snapshot, signals, projections, scorecard)

    parsed = json.loads(first.payload_json)
    assert isinstance(parsed, dict)
    assert first.payload_json == second.payload_json


def test_prompt_composer_marks_sector_data_unavailable_when_missing() -> None:
    result = build_structured_prompt_input(
        _snapshot(),
        _baseline_signals(),
        _baseline_projections(),
        _baseline_scorecard(),
    )
    assert result.payload["sector_relativity_peer_data"] == DATA_UNAVAILABLE
    assert result.payload["sector_relativity_peer_text"] == DATA_UNAVAILABLE
    assert f"Sector peer data state in this run: {DATA_UNAVAILABLE}." in result.user_prompt


def test_prompt_composer_marks_sector_data_provided_when_present() -> None:
    signals = _baseline_signals()
    signals["peer_sector_data"] = {
        "sector_name": "Industrial Manufacturing",
        "peer_forward_pe": 24.1,
        "peer_list": ["ABC", "DEF"],
    }
    signals["peer_sector_text"] = "Automated Peer Basket: ABC, DEF."
    result = build_structured_prompt_input(
        _snapshot(),
        signals,
        _baseline_projections(),
        _baseline_scorecard(),
    )
    assert isinstance(result.payload["sector_relativity_peer_data"], dict)
    assert "Sector peer data state in this run: Provided." in result.user_prompt


def test_prompt_composer_injects_peer_text_into_section8_guidance() -> None:
    signals = _baseline_signals()
    signals["peer_sector_text"] = "Automated Peer Basket: AAA, BBB."
    signals["peer_sector_data"] = {"peer_list": ["AAA", "BBB"]}

    result = build_structured_prompt_input(
        _snapshot(),
        signals,
        _baseline_projections(),
        _baseline_scorecard(),
    )

    assert "Sector peer context (if available): Automated Peer Basket: AAA, BBB." in result.user_prompt


def test_prompt_composer_injects_derivatives_smart_money_text() -> None:
    signals = _baseline_signals()
    signals["fno_text_block"] = (
        "Derivatives & Smart Money Flow: Futures positioning shows a Long Build-up "
        "with a rollover rate of 78%. The Put-Call Ratio (PCR) stands at 1.4, "
        "and the IV Percentile is Data Unavailable%. The Options Max Pain level "
        "for the nearest expiry is currently 100."
    )

    result = build_structured_prompt_input(
        _snapshot(),
        signals,
        _baseline_projections(),
        _baseline_scorecard(),
    )

    assert signals["fno_text_block"] in result.user_prompt
    assert result.payload["derivatives_smart_money"]["text_block"] == signals["fno_text_block"]


def test_prompt_composer_includes_signal_details_in_payload() -> None:
    valuation_signal = MetricSignal(
        key="valuation_pe_trend",
        label=SignalLabel.BULLISH,
        score=0.9,
        available=True,
        value=0.92,
        note="Forward valuation is improving.",
    )
    signals = _baseline_signals()
    signals["forward_pe"] = 19.0
    signals["trailing_pe"] = 20.5
    signals["fundamental_signals"] = {"valuation_pe_trend": valuation_signal}

    result = build_structured_prompt_input(
        _snapshot(),
        signals,
        _baseline_projections(),
        _baseline_scorecard(),
    )
    assert result.payload["fundamentals"]["forward_pe"]["signal"]["label"] == "bullish"
    assert result.payload["fundamentals"]["forward_pe"]["signal"]["note"] == "Forward valuation is improving."
