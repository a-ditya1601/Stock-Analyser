from __future__ import annotations

from typing import Any

import pandas as pd

from equity_reporter.config import ADX_BANDS, RSI_BANDS
from equity_reporter.models import MarketSnapshot, MetricSignal, SignalLabel, TechnicalMetrics, ThresholdBand


def compute_technical_signals(snapshot: MarketSnapshot) -> dict[str, Any]:
    history = snapshot.history.copy()
    close = _to_numeric_series(history, "Close")
    high = _to_numeric_series(history, "High")
    low = _to_numeric_series(history, "Low")

    latest_close = _latest_price(snapshot, close)

    ta = _load_ta()
    if ta is None:
        missing_signal = _missing_signal(
            "technical_engine",
            "pandas-ta is unavailable, so technical indicators could not be computed.",
        )
        return {
            "latest_close": latest_close,
            "technicals": TechnicalMetrics(),
            "technical_signals": {"technical_engine": missing_signal},
            "sma_20": None,
            "sma_50": None,
            "sma_200": None,
            "rsi_14": None,
            "macd": None,
            "macd_signal": None,
            "bb_lower": None,
            "bb_middle": None,
            "bb_upper": None,
            "adx_14": None,
            "ichimoku_span_a": None,
            "ichimoku_span_b": None,
        }

    sma_20 = _latest_numeric(ta.sma(close, length=20))
    sma_50 = _latest_numeric(ta.sma(close, length=50))
    sma_200 = _latest_numeric(ta.sma(close, length=200))

    rsi_14 = _latest_numeric(ta.rsi(close, length=14))

    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_value = _latest_numeric(_select_column_by_prefix(macd_df, "MACD_"))
    macd_signal = _latest_numeric(_select_column_by_prefix(macd_df, "MACDs_"))

    bb_df = ta.bbands(close, length=20, std=2.0)
    bb_lower = _latest_numeric(_select_column_by_prefix(bb_df, "BBL_"))
    bb_middle = _latest_numeric(_select_column_by_prefix(bb_df, "BBM_"))
    bb_upper = _latest_numeric(_select_column_by_prefix(bb_df, "BBU_"))

    adx_df = ta.adx(high, low, close, length=14)
    adx_14 = _latest_numeric(_select_column_by_prefix(adx_df, "ADX_"))
    dmp_14 = _latest_numeric(_select_column_by_prefix(adx_df, "DMP_"))
    dmn_14 = _latest_numeric(_select_column_by_prefix(adx_df, "DMN_"))

    ichimoku_raw = ta.ichimoku(high, low, close)
    ichimoku_span_a, ichimoku_span_b = _extract_ichimoku_spans(ichimoku_raw)
    if ichimoku_span_a is None or ichimoku_span_b is None:
        fallback_span_a, fallback_span_b = _compute_ichimoku_spans_fallback(high, low)
        if ichimoku_span_a is None:
            ichimoku_span_a = fallback_span_a
        if ichimoku_span_b is None:
            ichimoku_span_b = fallback_span_b

    metrics = TechnicalMetrics(
        sma_20=sma_20,
        sma_50=sma_50,
        sma_200=sma_200,
        rsi_14=rsi_14,
        macd=macd_value,
        macd_signal=macd_signal,
        bb_lower=bb_lower,
        bb_middle=bb_middle,
        bb_upper=bb_upper,
        adx_14=adx_14,
        ichimoku_span_a=ichimoku_span_a,
        ichimoku_span_b=ichimoku_span_b,
    )

    signals = {
        "sma_crossover": _score_sma_crossover(sma_50, sma_200),
        "rsi_14": _score_from_bands(
            "rsi_14",
            rsi_14,
            RSI_BANDS,
            "RSI(14) measures momentum pressure and overbought/oversold conditions.",
        ),
        "macd_crossover": _score_macd_crossover(macd_value, macd_signal),
        "bollinger_position": _score_bollinger_position(
            latest_close,
            bb_lower,
            bb_middle,
            bb_upper,
        ),
        "adx_trend_strength": _score_adx(adx_14, dmp_14, dmn_14),
        "ichimoku_cloud": _score_ichimoku(latest_close, ichimoku_span_a, ichimoku_span_b),
    }

    return {
        "latest_close": latest_close,
        "technicals": metrics,
        "technical_signals": signals,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi_14": rsi_14,
        "macd": macd_value,
        "macd_signal": macd_signal,
        "bb_lower": bb_lower,
        "bb_middle": bb_middle,
        "bb_upper": bb_upper,
        "adx_14": adx_14,
        "ichimoku_span_a": ichimoku_span_a,
        "ichimoku_span_b": ichimoku_span_b,
    }


def _latest_price(snapshot: MarketSnapshot, close: pd.Series) -> float | None:
    if snapshot.current_price is not None:
        return float(snapshot.current_price)
    return _latest_numeric(close)


def _load_ta() -> Any | None:
    try:
        import pandas_ta as ta  # type: ignore
    except Exception:  # pragma: no cover - environment dependent.
        return None
    return ta


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


def _select_column_by_prefix(frame: pd.DataFrame | None, prefix: str) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    for column in frame.columns:
        if str(column).startswith(prefix):
            return pd.to_numeric(frame[column], errors="coerce")
    return None


def _extract_ichimoku_spans(ichimoku_raw: Any) -> tuple[float | None, float | None]:
    frames: list[pd.DataFrame] = []
    if isinstance(ichimoku_raw, tuple):
        for item in ichimoku_raw:
            if isinstance(item, pd.DataFrame) and not item.empty:
                frames.append(item)
    elif isinstance(ichimoku_raw, pd.DataFrame) and not ichimoku_raw.empty:
        frames.append(ichimoku_raw)

    for frame in frames:
        span_a_series = _select_column_by_prefix(frame, "ISA_")
        span_b_series = _select_column_by_prefix(frame, "ISB_")
        span_a = _latest_numeric(span_a_series)
        span_b = _latest_numeric(span_b_series)
        if span_a is not None or span_b is not None:
            return span_a, span_b

    return None, None


def _compute_ichimoku_spans_fallback(high: pd.Series, low: pd.Series) -> tuple[float | None, float | None]:
    frame = pd.DataFrame({"high": high, "low": low}).dropna()
    if len(frame) < 52:
        return None, None

    high_series = frame["high"]
    low_series = frame["low"]

    conversion = (high_series.rolling(window=9, min_periods=9).max() + low_series.rolling(window=9, min_periods=9).min()) / 2.0
    base = (high_series.rolling(window=26, min_periods=26).max() + low_series.rolling(window=26, min_periods=26).min()) / 2.0
    span_a = (conversion + base) / 2.0
    span_b = (high_series.rolling(window=52, min_periods=52).max() + low_series.rolling(window=52, min_periods=52).min()) / 2.0

    return _latest_numeric(span_a), _latest_numeric(span_b)


def _score_sma_crossover(sma_50: float | None, sma_200: float | None) -> MetricSignal:
    if sma_50 is None or sma_200 is None:
        return _missing_signal(
            "sma_crossover",
            "SMA50/SMA200 crossover unavailable due to insufficient historical length.",
        )
    if sma_50 > sma_200:
        return MetricSignal(
            key="sma_crossover",
            value=sma_50 - sma_200,
            label=SignalLabel.BULLISH,
            score=0.9,
            available=True,
            note="SMA50 is above SMA200 (golden-cross regime).",
        )
    if sma_50 < sma_200:
        return MetricSignal(
            key="sma_crossover",
            value=sma_50 - sma_200,
            label=SignalLabel.BEARISH,
            score=0.1,
            available=True,
            note="SMA50 is below SMA200 (death-cross regime).",
        )
    return MetricSignal(
        key="sma_crossover",
        value=0.0,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note="SMA50 and SMA200 are nearly equal, indicating indecisive long trend.",
    )


def _score_macd_crossover(macd_value: float | None, macd_signal: float | None) -> MetricSignal:
    if macd_value is None or macd_signal is None:
        return _missing_signal(
            "macd_crossover",
            "MACD or signal line unavailable due to insufficient data.",
        )

    spread = macd_value - macd_signal
    if spread > 0:
        return MetricSignal(
            key="macd_crossover",
            value=spread,
            label=SignalLabel.BULLISH,
            score=0.8,
            available=True,
            note="MACD line is above signal line, suggesting positive momentum.",
        )
    if spread < 0:
        return MetricSignal(
            key="macd_crossover",
            value=spread,
            label=SignalLabel.BEARISH,
            score=0.2,
            available=True,
            note="MACD line is below signal line, suggesting weakening momentum.",
        )
    return MetricSignal(
        key="macd_crossover",
        value=0.0,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note="MACD and signal line overlap, indicating neutral momentum.",
    )


def _score_bollinger_position(
    latest_close: float | None,
    bb_lower: float | None,
    bb_middle: float | None,
    bb_upper: float | None,
) -> MetricSignal:
    if latest_close is None or bb_lower is None or bb_middle is None or bb_upper is None:
        return _missing_signal(
            "bollinger_position",
            "Bollinger Bands unavailable due to insufficient data.",
        )

    if latest_close <= bb_lower:
        return MetricSignal(
            key="bollinger_position",
            value=latest_close,
            label=SignalLabel.BULLISH,
            score=0.8,
            available=True,
            note="Price is near/below the lower band, suggesting potential oversold support.",
        )
    if latest_close < bb_middle:
        return MetricSignal(
            key="bollinger_position",
            value=latest_close,
            label=SignalLabel.NEUTRAL,
            score=0.55,
            available=True,
            note="Price is between lower and middle band, showing soft momentum.",
        )
    if latest_close < bb_upper:
        return MetricSignal(
            key="bollinger_position",
            value=latest_close,
            label=SignalLabel.NEUTRAL,
            score=0.65,
            available=True,
            note="Price is between middle and upper band, indicating constructive trend.",
        )
    return MetricSignal(
        key="bollinger_position",
        value=latest_close,
        label=SignalLabel.WARNING,
        score=0.3,
        available=True,
        note="Price is near/above upper band, indicating stretched short-term conditions.",
    )


def _score_adx(adx_14: float | None, dmp_14: float | None, dmn_14: float | None) -> MetricSignal:
    if adx_14 is None:
        return _missing_signal(
            "adx_trend_strength",
            "ADX trend-strength reading unavailable.",
        )

    # ADX bands establish trend strength; direction is determined by +DI and -DI.
    if adx_14 < 20:
        return MetricSignal(
            key="adx_trend_strength",
            value=adx_14,
            label=SignalLabel.WARNING,
            score=0.3,
            available=True,
            note="ADX below 20 indicates a choppy or sideways market.",
        )
    if adx_14 < 25:
        return MetricSignal(
            key="adx_trend_strength",
            value=adx_14,
            label=SignalLabel.NEUTRAL,
            score=0.5,
            available=True,
            note="ADX between 20 and 25 indicates trend is forming but not fully validated.",
        )

    if dmp_14 is not None and dmn_14 is not None:
        if dmp_14 > dmn_14:
            return MetricSignal(
                key="adx_trend_strength",
                value=adx_14,
                label=SignalLabel.BULLISH,
                score=0.85,
                available=True,
                note="ADX above 25 with +DI above -DI validates a strong bullish trend.",
            )
        if dmn_14 > dmp_14:
            return MetricSignal(
                key="adx_trend_strength",
                value=adx_14,
                label=SignalLabel.BEARISH,
                score=0.15,
                available=True,
                note="ADX above 25 with -DI above +DI validates a strong bearish trend.",
            )

    return _score_from_bands(
        "adx_trend_strength",
        adx_14,
        ADX_BANDS,
        "ADX indicates strong trend conditions, but directional confirmation is inconclusive.",
    )


def _score_ichimoku(
    latest_close: float | None,
    span_a: float | None,
    span_b: float | None,
) -> MetricSignal:
    if latest_close is None or span_a is None or span_b is None:
        return _missing_signal(
            "ichimoku_cloud",
            "Ichimoku cloud spans are unavailable for the latest session.",
        )

    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)

    if latest_close > cloud_top:
        return MetricSignal(
            key="ichimoku_cloud",
            value=latest_close,
            label=SignalLabel.BULLISH,
            score=0.9,
            available=True,
            note="Price is above the cloud, indicating bullish breakout territory.",
        )
    if latest_close < cloud_bottom:
        return MetricSignal(
            key="ichimoku_cloud",
            value=latest_close,
            label=SignalLabel.BEARISH,
            score=0.1,
            available=True,
            note="Price is below the cloud, indicating bearish territory.",
        )
    return MetricSignal(
        key="ichimoku_cloud",
        value=latest_close,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note="Price is inside the cloud, indicating consolidation/transition.",
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
