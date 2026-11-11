from __future__ import annotations

from equity_reporter.reporting.pdf_builder import _build_technical_rows


def test_technical_rows_include_sma20_sma50_sma200_label_and_values() -> None:
    signals = {
        "sma_20": 101.2,
        "sma_50": 99.4,
        "sma_200": 92.8,
        "rsi_14": 54.0,
        "macd": 1.1,
        "macd_signal": 0.8,
        "bb_lower": 95.0,
        "bb_middle": 100.0,
        "bb_upper": 105.0,
        "ichimoku_span_a": 99.5,
        "ichimoku_span_b": 97.0,
        "fib_0_382": 103.0,
        "fib_0_500": 100.0,
        "fib_0_618": 97.0,
        "technical_signals": {},
        "fibonacci_signal": None,
    }

    rows = _build_technical_rows(signals, metric_notes={})
    first = rows[0]

    assert first[0] == "SMA20 / SMA50 / SMA200"
    assert "101.20 / 99.40 / 92.80" in first[1]
