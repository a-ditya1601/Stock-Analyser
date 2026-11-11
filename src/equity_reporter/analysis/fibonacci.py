from __future__ import annotations

from typing import Any

import pandas as pd

from equity_reporter.config import (
    DEFAULT_CHART_LOOKBACK_DAYS,
    FIB_BREAKOUT_BUFFER_PCT,
    FIB_SUPPORT_TOLERANCE_PCT,
)
from equity_reporter.models import FibonacciLevels, MarketSnapshot, MetricSignal, SignalLabel


def compute_fibonacci_signals(snapshot: MarketSnapshot) -> dict[str, Any]:
    history = snapshot.history.copy()
    range_window = _aligned_high_low_window(history, DEFAULT_CHART_LOOKBACK_DAYS)
    if range_window.empty:
        missing_signal = _missing_signal(
            "fibonacci_support_breakout",
            "Not enough valid high/low data to compute 6-month Fibonacci levels.",
        )
        return {
            "fibonacci": FibonacciLevels(),
            "fibonacci_signal": missing_signal,
            "high_6m": None,
            "low_6m": None,
            "fib_0_382": None,
            "fib_0_500": None,
            "fib_0_618": None,
        }

    high_6m = float(range_window["High"].max())
    low_6m = float(range_window["Low"].min())

    if high_6m <= low_6m:
        missing_signal = _missing_signal(
            "fibonacci_support_breakout",
            "6-month high/low range is invalid, so Fibonacci levels are unavailable.",
        )
        return {
            "fibonacci": FibonacciLevels(high_6m=high_6m, low_6m=low_6m),
            "fibonacci_signal": missing_signal,
            "high_6m": high_6m,
            "low_6m": low_6m,
            "fib_0_382": None,
            "fib_0_500": None,
            "fib_0_618": None,
        }

    span = high_6m - low_6m
    level_0_382 = high_6m - (0.382 * span)
    level_0_500 = high_6m - (0.500 * span)
    level_0_618 = high_6m - (0.618 * span)

    latest_close = _latest_close(snapshot)
    fib_signal = _score_fibonacci_signal(
        latest_close=latest_close,
        level_0_382=level_0_382,
        level_0_500=level_0_500,
        level_0_618=level_0_618,
    )

    fib_levels = FibonacciLevels(
        high_6m=high_6m,
        low_6m=low_6m,
        level_0_382=level_0_382,
        level_0_500=level_0_500,
        level_0_618=level_0_618,
    )

    return {
        "fibonacci": fib_levels,
        "fibonacci_signal": fib_signal,
        "high_6m": high_6m,
        "low_6m": low_6m,
        "fib_0_382": level_0_382,
        "fib_0_500": level_0_500,
        "fib_0_618": level_0_618,
    }


def _to_numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype="float64")
    series = frame[column]
    if isinstance(series, pd.DataFrame):
        if series.empty:
            return pd.Series(dtype="float64")
        series = series.iloc[:, 0]
    return pd.to_numeric(series, errors="coerce")


def _aligned_high_low_window(history: pd.DataFrame, lookback: int) -> pd.DataFrame:
    high = _to_numeric_series(history, "High")
    low = _to_numeric_series(history, "Low")
    frame = pd.DataFrame({"High": high, "Low": low}).dropna()
    if frame.empty:
        return frame
    return frame.tail(lookback)


def _latest_close(snapshot: MarketSnapshot) -> float | None:
    if snapshot.current_price is not None:
        return float(snapshot.current_price)

    close = _to_numeric_series(snapshot.history, "Close")
    if close.empty:
        return None
    non_null = close.dropna()
    if non_null.empty:
        return None
    return float(non_null.iloc[-1])


def _score_fibonacci_signal(
    latest_close: float | None,
    level_0_382: float,
    level_0_500: float,
    level_0_618: float,
) -> MetricSignal:
    if latest_close is None:
        return _missing_signal(
            "fibonacci_support_breakout",
            "Latest close is unavailable, so Fibonacci support/breakout cannot be classified.",
        )

    if latest_close >= level_0_382 * (1.0 + FIB_BREAKOUT_BUFFER_PCT):
        return MetricSignal(
            key="fibonacci_support_breakout",
            value=latest_close,
            label=SignalLabel.BULLISH,
            score=0.9,
            available=True,
            note="Price is holding above the 38.2% retracement, signaling bullish breakout continuation.",
        )

    if _is_near_level(latest_close, level_0_382) or _is_near_level(latest_close, level_0_500):
        return MetricSignal(
            key="fibonacci_support_breakout",
            value=latest_close,
            label=SignalLabel.BULLISH,
            score=0.8,
            available=True,
            note="Price is finding support near a key Fibonacci retracement level.",
        )

    if latest_close > level_0_500 and latest_close < level_0_382:
        return MetricSignal(
            key="fibonacci_support_breakout",
            value=latest_close,
            label=SignalLabel.NEUTRAL,
            score=0.6,
            available=True,
            note="Price is between 50% and 38.2% retracement levels in a constructive zone.",
        )

    if _is_near_level(latest_close, level_0_618):
        return MetricSignal(
            key="fibonacci_support_breakout",
            value=latest_close,
            label=SignalLabel.WARNING,
            score=0.4,
            available=True,
            note="Price is testing the 61.8% retracement, a critical support area.",
        )

    if latest_close < level_0_618:
        return MetricSignal(
            key="fibonacci_support_breakout",
            value=latest_close,
            label=SignalLabel.BEARISH,
            score=0.1,
            available=True,
            note="Price is below 61.8% retracement, indicating potential breakdown risk.",
        )

    return MetricSignal(
        key="fibonacci_support_breakout",
        value=latest_close,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note="Price is between key Fibonacci levels without a clear breakout/breakdown signal.",
    )


def _is_near_level(price: float, level: float) -> bool:
    if level == 0:
        return False
    return abs(price - level) / abs(level) <= FIB_SUPPORT_TOLERANCE_PCT


def _missing_signal(key: str, note: str) -> MetricSignal:
    return MetricSignal(
        key=key,
        value=None,
        label=SignalLabel.MISSING,
        score=0.0,
        available=False,
        note=note,
    )
