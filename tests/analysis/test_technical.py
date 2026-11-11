from __future__ import annotations

from datetime import datetime

import pandas as pd

from equity_reporter.analysis.technical import compute_technical_signals
from equity_reporter.models import MarketSnapshot, SignalLabel


def _snapshot_with_history(rows: int = 260) -> MarketSnapshot:
    index = pd.date_range("2025-01-01", periods=rows, freq="D")
    close = pd.Series([100 + (i * 0.2) for i in range(rows)], index=index)
    high = close + 1.0
    low = close - 1.0
    volume = pd.Series([100000 + (i * 100) for i in range(rows)], index=index)

    history = pd.DataFrame(
        {
            "Close": close,
            "High": high,
            "Low": low,
            "Volume": volume,
        }
    )
    return MarketSnapshot(
        ticker="TEST",
        history=history,
        info={},
        current_price=float(close.iloc[-1]),
        fetched_at=datetime(2026, 4, 25, 10, 0, 0),
    )


def test_compute_technical_signals_includes_sma20(monkeypatch) -> None:
    snapshot = _snapshot_with_history()

    class _FakeTA:
        @staticmethod
        def sma(series: pd.Series, length: int) -> pd.Series:
            return series.rolling(length, min_periods=length).mean()

        @staticmethod
        def rsi(series: pd.Series, length: int) -> pd.Series:
            out = pd.Series(55.0, index=series.index)
            return out

        @staticmethod
        def macd(series: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:  # noqa: ARG004
            idx = series.index
            return pd.DataFrame(
                {
                    "MACD_12_26_9": pd.Series(1.2, index=idx),
                    "MACDs_12_26_9": pd.Series(0.8, index=idx),
                }
            )

        @staticmethod
        def bbands(series: pd.Series, length: int, std: float) -> pd.DataFrame:  # noqa: ARG004
            idx = series.index
            return pd.DataFrame(
                {
                    "BBL_20_2.0": series - 2.0,
                    "BBM_20_2.0": series,
                    "BBU_20_2.0": series + 2.0,
                },
                index=idx,
            )

        @staticmethod
        def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.DataFrame:  # noqa: ARG004
            idx = close.index
            return pd.DataFrame(
                {
                    "ADX_14": pd.Series(28.0, index=idx),
                    "DMP_14": pd.Series(30.0, index=idx),
                    "DMN_14": pd.Series(16.0, index=idx),
                }
            )

        @staticmethod
        def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series):  # noqa: ANN205, ARG004
            idx = close.index
            frame = pd.DataFrame(
                {
                    "ISA_9": pd.Series(close.iloc[-1] - 1.0, index=idx),
                    "ISB_26": pd.Series(close.iloc[-1] - 3.0, index=idx),
                }
            )
            return frame

    monkeypatch.setattr("equity_reporter.analysis.technical._load_ta", lambda: _FakeTA())

    result = compute_technical_signals(snapshot)

    assert result["sma_20"] is not None
    assert result["sma_50"] is not None
    assert result["sma_200"] is not None
    assert result["technicals"].sma_20 == result["sma_20"]
    assert result["technical_signals"]["sma_crossover"].label in {
        SignalLabel.BULLISH,
        SignalLabel.NEUTRAL,
        SignalLabel.BEARISH,
    }


def test_compute_technical_signals_sets_sma20_none_when_ta_missing(monkeypatch) -> None:
    snapshot = _snapshot_with_history(rows=40)
    monkeypatch.setattr("equity_reporter.analysis.technical._load_ta", lambda: None)

    result = compute_technical_signals(snapshot)

    assert result["sma_20"] is None
    assert result["sma_50"] is None
    assert result["sma_200"] is None
    assert result["technical_signals"]["technical_engine"].available is False
