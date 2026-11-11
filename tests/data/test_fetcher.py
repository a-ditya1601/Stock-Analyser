from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from equity_reporter.data.fetcher import _fetch_history_for_ticker


class FakeAngelHistoryClient:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.params = None

    def getCandleData(self, params: dict) -> dict:
        self.params = dict(params)
        return {"status": True, "data": self.rows}


class FakeYfTicker:
    def __init__(self, history: pd.DataFrame) -> None:
        self._history = history

    def history(self, **kwargs):  # noqa: ANN001
        return self._history


def test_indian_history_router_uses_angel_first(monkeypatch) -> None:
    client = FakeAngelHistoryClient(
        [["2026-06-01T00:00:00+05:30", 100, 105, 99, 104, 1000]]
    )
    monkeypatch.setattr(
        "equity_reporter.data.fetcher.get_angel_token",
        lambda symbol: SimpleNamespace(equity={"token": "2885", "exch_seg": "NSE"}),
    )
    monkeypatch.setattr("equity_reporter.data.fetcher.initialize_angel_session", lambda: client)

    history, source, note = _fetch_history_for_ticker(
        yf_ticker=FakeYfTicker(pd.DataFrame()),
        ticker="RELIANCE.NS",
        period="1y",
        retries=1,
        required=True,
    )

    assert source == "angel_one"
    assert "Angel One" in note
    assert list(history.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert float(history["Close"].iloc[-1]) == 104.0
    assert client.params["symboltoken"] == "2885"
    assert client.params["exchange"] == "NSE"


def test_indian_history_router_falls_back_to_yfinance_when_angel_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "equity_reporter.data.fetcher.get_angel_token",
        lambda symbol: SimpleNamespace(equity={"token": "2885", "exch_seg": "NSE"}),
    )
    monkeypatch.setattr("equity_reporter.data.fetcher.initialize_angel_session", lambda: None)
    yf_history = pd.DataFrame(
        {"Open": [10], "High": [11], "Low": [9], "Close": [10.5], "Volume": [100]},
        index=pd.to_datetime(["2026-06-01"]),
    )

    history, source, note = _fetch_history_for_ticker(
        yf_ticker=FakeYfTicker(yf_history),
        ticker="RELIANCE.NS",
        period="1y",
        retries=1,
        required=True,
    )

    assert source == "yfinance_fallback"
    assert "fell back" in note
    assert float(history["Close"].iloc[-1]) == 10.5
