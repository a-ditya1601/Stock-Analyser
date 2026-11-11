from __future__ import annotations

from datetime import date, datetime, timedelta
from math import isclose, sqrt

import pandas as pd

from equity_reporter.analysis.projections import (
    METHODOLOGY_HYBRID,
    LevelCluster,
    _build_options_expected_move_range,
    _build_volume_profile,
    _gravity_adjust,
    build_projections,
)
from equity_reporter.models import MarketSnapshot


def _snapshot(history: pd.DataFrame, current_price: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        ticker="TEST",
        history=history,
        info={"targetMeanPrice": 112.0, "numberOfAnalystOpinions": 12},
        current_price=current_price,
        company_metadata={"company_name": "Test Co"},
        fast_info={},
        fetched_at=datetime(2026, 5, 15, 12, 0, 0),
    )


def _history(rows: int = 320) -> pd.DataFrame:
    index = pd.bdate_range(end="2026-05-15", periods=rows)
    close = pd.Series([70.0 + (idx * 0.10) for idx in range(rows)], index=index)
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.015,
            "Low": close * 0.985,
            "Close": close,
            "Volume": [1000 + ((idx % 25) * 100) for idx in range(rows)],
        },
        index=index,
    )


def test_options_expected_move_uses_percent_iv_as_decimal() -> None:
    expiry = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")

    rng = _build_options_expected_move_range(
        100.0,
        {"fno_atm_iv": 25.0, "fno_expiry": expiry},
        bias=0.0,
    )

    assert rng is not None
    expected_move = 100.0 * 0.25 * sqrt(30 / 365)
    assert isclose(rng.bear, 100.0 - expected_move, rel_tol=0.05)
    assert isclose(rng.bull, 100.0 + expected_move, rel_tol=0.05)
    assert rng.base == 100.0


def test_volume_profile_identifies_poc_and_hvns() -> None:
    history = _history(120)
    # Concentrate high volume near the middle of the price range.
    high = history["High"]
    low = history["Low"]
    close = history["Close"]
    volume = pd.Series(100.0, index=history.index)
    middle = close.between(78, 82)
    volume.loc[middle] = 10000.0

    profile = _build_volume_profile(high, low, close, volume)

    assert profile["poc"] is not None
    assert 76 <= profile["poc"] <= 84
    assert profile["hvns"]


def test_gravity_adjust_pulls_toward_cluster_without_hard_snapping() -> None:
    raw_target = 105.0
    cluster = LevelCluster(price=104.0, strength=90.0, touches=3)

    adjusted = _gravity_adjust(
        raw_target,
        latest_close=100.0,
        radius=5.0,
        clusters=[cluster],
    )

    assert 104.0 < adjusted < raw_target


def test_build_projections_returns_hybrid_metadata_and_ordered_ranges() -> None:
    history = _history()
    signals = {
        "sma_20": 100.0,
        "sma_50": 96.0,
        "sma_200": 84.0,
        "bb_lower": 92.0,
        "bb_middle": 98.0,
        "bb_upper": 106.0,
        "fib_0_382": 104.0,
        "fib_0_500": 98.0,
        "fib_0_618": 92.0,
        "high_6m": 108.0,
        "low_6m": 82.0,
        "fno_atm_iv": 22.0,
        "fno_expiry": (date.today() + timedelta(days=35)).strftime("%Y-%m-%d"),
    }

    projections = build_projections(_snapshot(history, current_price=102.0), signals)

    assert projections.methodology == METHODOLOGY_HYBRID
    assert projections.projection_confidence in {"High", "Medium", "Low"}
    assert projections.support_levels
    assert projections.resistance_levels
    assert projections.volume_profile_poc is not None
    assert "1-2 months" in projections.scenario_probabilities
    for rng in projections.horizons.values():
        assert rng.bear <= rng.base <= rng.bull

