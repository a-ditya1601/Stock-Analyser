from __future__ import annotations

import pytest

from equity_reporter.analysis.scoring import compute_scorecard
from equity_reporter.config import CATEGORY_METRIC_WEIGHTS
from equity_reporter.models import MetricSignal, SignalLabel


def _signal(key: str, score: float) -> MetricSignal:
    return MetricSignal(
        key=key,
        value=1.0,
        label=SignalLabel.BULLISH,
        score=score,
        available=True,
        note="test metric",
    )


def _total_configured_metric_count() -> int:
    return len({metric for category in CATEGORY_METRIC_WEIGHTS.values() for metric in category})


def test_scorecard_uses_available_metric_denominator_for_confidence() -> None:
    signals = {
        "fundamental_signals": {
            "valuation_pe_trend": _signal("valuation_pe_trend", 0.5),
        },
        "technical_signals": {
            "sma_crossover": _signal("sma_crossover", 1.0),
        },
        "volume_signals": {},
    }

    scorecard = compute_scorecard(signals)

    assert scorecard.final_score == 82.65
    assert scorecard.verdict == "STRONG BUY"
    assert scorecard.category_scores["fundamental"] == 50.0
    assert scorecard.category_scores["technical"] == 100.0
    assert scorecard.category_scores["volume_risk"] == 0.0
    assert scorecard.category_scores["peer_relativity"] == 0.0
    assert scorecard.data_coverage_pct == round((2 / _total_configured_metric_count()) * 100.0, 2)


@pytest.mark.parametrize(
    ("metric_score", "expected_verdict"),
    [
        (0.75, "STRONG BUY"),
        (0.60, "ACCUMULATE / BUY"),
        (0.45, "HOLD / NEUTRAL"),
        (0.30, "TRIM / SELL"),
        (0.29, "STRONG SELL"),
    ],
)
def test_scorecard_uses_updated_verdict_tiers(metric_score: float, expected_verdict: str) -> None:
    signals = {
        "fundamental_signals": {
            "valuation_pe_trend": _signal("valuation_pe_trend", metric_score),
        },
        "technical_signals": {},
        "volume_signals": {},
    }

    scorecard = compute_scorecard(signals)

    assert scorecard.final_score == round(metric_score * 100.0, 2)
    assert scorecard.verdict == expected_verdict


def test_data_coverage_uses_metric_count_not_metric_weight() -> None:
    heavy_metric_signals = {
        "fundamental_signals": {
            "fcf_vs_debt": _signal("fcf_vs_debt", 0.8),
        },
        "technical_signals": {},
        "volume_signals": {},
    }
    light_metric_signals = {
        "fundamental_signals": {
            "current_ratio": _signal("current_ratio", 0.8),
        },
        "technical_signals": {},
        "volume_signals": {},
    }

    heavy_scorecard = compute_scorecard(heavy_metric_signals)
    light_scorecard = compute_scorecard(light_metric_signals)
    expected_coverage = round((1 / _total_configured_metric_count()) * 100.0, 2)

    assert heavy_scorecard.data_coverage_pct == expected_coverage
    assert light_scorecard.data_coverage_pct == expected_coverage


def test_scorecard_includes_peer_signal_category_in_final_confidence() -> None:
    signals = {
        "fundamental_signals": {},
        "technical_signals": {},
        "volume_signals": {},
        "peer_signals": {
            "peer_pe_to_sector_pe_ratio": _signal("peer_pe_to_sector_pe_ratio", 1.0),
        },
    }

    scorecard = compute_scorecard(signals)

    assert scorecard.category_scores["peer_relativity"] == 100.0
    assert scorecard.final_score == 100.0


def test_scorecard_includes_new_fundamental_quality_metrics() -> None:
    assert "return_on_capital_employed" in CATEGORY_METRIC_WEIGHTS["fundamental"]
    assert "operating_margin" in CATEGORY_METRIC_WEIGHTS["fundamental"]
    assert "peer_pe_to_sector_pe_ratio" in CATEGORY_METRIC_WEIGHTS["peer_relativity"]
    assert "peer_forward_pe_premium" not in CATEGORY_METRIC_WEIGHTS["peer_relativity"]


def test_scorecard_includes_fno_metrics_and_excludes_legacy_short_interest_from_configured_scoring() -> None:
    assert "short_ratio" not in CATEGORY_METRIC_WEIGHTS["volume_risk"]
    assert "short_percent_of_float" not in CATEGORY_METRIC_WEIGHTS["volume_risk"]
    assert "beta_profile_fit" not in CATEGORY_METRIC_WEIGHTS["volume_risk"]
    assert "futures_oi_buildup" in CATEGORY_METRIC_WEIGHTS["volume_risk"]
    assert "rollover_percentage" in CATEGORY_METRIC_WEIGHTS["volume_risk"]
    assert "pcr_sentiment" in CATEGORY_METRIC_WEIGHTS["volume_risk"]
    assert "iv_percentile" in CATEGORY_METRIC_WEIGHTS["volume_risk"]
