from __future__ import annotations

from typing import Any

import pandas as pd

from equity_reporter.config import RELATIVE_VOLUME_BANDS
from equity_reporter.models import MarketSnapshot, MetricSignal, SignalLabel, ThresholdBand, VolumeMetrics


def compute_volume_signals(snapshot: MarketSnapshot) -> dict[str, Any]:
    history = snapshot.history.copy()
    close = _to_numeric_series(history, "Close")
    volume = _to_numeric_series(history, "Volume")

    latest_volume = _latest_numeric(volume)

    obv_series = _compute_obv(close, volume)
    obv_value = _latest_numeric(obv_series)
    obv_30d_trend_pct = _compute_obv_30d_trend_pct(obv_series, volume)

    avg_volume_10d = _rolling_mean_last(volume, window=10)
    avg_volume_3m = _rolling_mean_last(volume, window=63)
    relative_volume = _compute_relative_volume(avg_volume_10d, avg_volume_3m)

    metrics = VolumeMetrics(
        obv=obv_value,
        obv_30d_slope=obv_30d_trend_pct,
        avg_volume_10d=avg_volume_10d,
        avg_volume_3m=avg_volume_3m,
    )

    signals = {
        "obv_30d_trend": _score_obv_trend(obv_30d_trend_pct),
        "relative_volume_10d_3m": _score_from_bands(
            "relative_volume_10d_3m",
            relative_volume,
            RELATIVE_VOLUME_BANDS,
            "Relative volume compares 10-day activity against the 3-month average.",
        ),
    }

    return {
        "volumes": metrics,
        "volume_signals": signals,
        "latest_volume": latest_volume,
        "obv": obv_value,
        "obv_30d_slope": obv_30d_trend_pct,
        "avg_volume_10d": avg_volume_10d,
        "avg_volume_3m": avg_volume_3m,
        "relative_volume_10d_3m": relative_volume,
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


def _latest_numeric(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    non_null = series.dropna()
    if non_null.empty:
        return None
    return float(non_null.iloc[-1])


def _rolling_mean_last(series: pd.Series, window: int) -> float | None:
    if series.empty:
        return None
    rolling = series.rolling(window=window, min_periods=window).mean()
    return _latest_numeric(rolling)


def _compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    if close.empty or volume.empty:
        return pd.Series(dtype="float64")

    joined = pd.DataFrame({"close": close, "volume": volume}).dropna()
    if joined.empty:
        return pd.Series(dtype="float64")

    direction = joined["close"].diff().fillna(0.0).apply(lambda change: 1.0 if change > 0 else (-1.0 if change < 0 else 0.0))
    obv = (direction * joined["volume"]).cumsum()
    return obv


def _compute_obv_30d_trend_pct(obv: pd.Series, volume: pd.Series) -> float | None:
    if obv.empty:
        return None
    non_null = obv.dropna()
    if len(non_null) < 30:
        return None

    delta = float(non_null.iloc[-1]) - float(non_null.iloc[-30])
    aligned_volume = pd.to_numeric(volume.reindex(non_null.index), errors="coerce").dropna()
    if len(aligned_volume) < 30:
        return None
    denominator = float(aligned_volume.iloc[-30:].sum())
    if denominator <= 0:
        return None
    return delta / denominator


def _compute_relative_volume(avg_volume_10d: float | None, avg_volume_3m: float | None) -> float | None:
    if avg_volume_10d is None or avg_volume_3m is None:
        return None
    if avg_volume_3m <= 0:
        return None
    return avg_volume_10d / avg_volume_3m


def _score_obv_trend(obv_30d_trend_pct: float | None) -> MetricSignal:
    if obv_30d_trend_pct is None:
        return _missing_signal(
            "obv_30d_trend",
            "OBV 30-day trend is unavailable due to insufficient history.",
        )

    if obv_30d_trend_pct >= 0.02:
        return MetricSignal(
            key="obv_30d_trend",
            value=obv_30d_trend_pct,
            label=SignalLabel.BULLISH,
            score=0.85,
            available=True,
            note="OBV is trending up over the last 30 sessions, indicating accumulation.",
        )
    if obv_30d_trend_pct <= -0.02:
        return MetricSignal(
            key="obv_30d_trend",
            value=obv_30d_trend_pct,
            label=SignalLabel.BEARISH,
            score=0.15,
            available=True,
            note="OBV is trending down over the last 30 sessions, indicating distribution.",
        )
    return MetricSignal(
        key="obv_30d_trend",
        value=obv_30d_trend_pct,
        label=SignalLabel.NEUTRAL,
        score=0.55,
        available=True,
        note="OBV has moved sideways over the last 30 sessions.",
    )


def _score_from_bands(
    key: str,
    value: float | None,
    bands: tuple[ThresholdBand, ...],
    note: str,
) -> MetricSignal:
    if value is None:
        return _missing_signal(key, f"{note} Metric is unavailable.")

    for band in bands:
        if band.matches(value):
            return MetricSignal(
                key=key,
                value=value,
                label=band.label,
                score=band.score,
                available=True,
                note=note,
            )

    return MetricSignal(
        key=key,
        value=value,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note=note,
    )


def _missing_signal(key: str, note: str) -> MetricSignal:
    return MetricSignal(
        key=key,
        value=None,
        label=SignalLabel.MISSING,
        score=0.0,
        available=False,
        note=note,
    )
