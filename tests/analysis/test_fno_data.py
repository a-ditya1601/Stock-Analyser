from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import equity_reporter.analysis.fno_data as fno_data
from equity_reporter.analysis.fno_data import (
    _calculate_max_pain,
    _classify_futures_oi_buildup,
    build_fno_signals,
    get_fno_metrics,
    normalize_indian_symbol,
)
from equity_reporter.models import FnoMetrics, SignalLabel


class FakeAngelClient:
    def __init__(self, quotes_by_token: dict[str, dict]) -> None:
        self.quotes_by_token = quotes_by_token

    def getMarketData(self, mode: str, exchange_tokens: dict[str, list[str]]) -> dict:
        assert mode == "FULL"
        tokens = next(iter(exchange_tokens.values()))
        return {
            "status": True,
            "data": {
                "fetched": [
                    {"symbolToken": token, **self.quotes_by_token[token]}
                    for token in tokens
                    if token in self.quotes_by_token
                ]
            },
        }


def _angel_scrip_master() -> list[dict]:
    return [
        {
            "token": "2885",
            "symbol": "RELIANCE-EQ",
            "name": "RELIANCE",
            "expiry": "",
            "strike": "-1.000000",
            "instrumenttype": "",
            "exch_seg": "NSE",
        },
        {
            "token": "FUT1",
            "symbol": "RELIANCE30JUL26FUT",
            "name": "RELIANCE",
            "expiry": "30JUL2026",
            "strike": "-1.000000",
            "instrumenttype": "FUTSTK",
            "exch_seg": "NFO",
        },
        {
            "token": "FUT2",
            "symbol": "RELIANCE30AUG26FUT",
            "name": "RELIANCE",
            "expiry": "30AUG2026",
            "strike": "-1.000000",
            "instrumenttype": "FUTSTK",
            "exch_seg": "NFO",
        },
        *_option_master_rows(),
    ]


def _option_master_rows() -> list[dict]:
    rows: list[dict] = []
    token = 100
    for strike in (90, 100, 110):
        for side in ("CE", "PE"):
            rows.append(
                {
                    "token": str(token),
                    "symbol": f"RELIANCE30JUL26{strike}{side}",
                    "name": "RELIANCE",
                    "expiry": "30JUL2026",
                    "strike": f"{strike * 100:.6f}",
                    "instrumenttype": "OPTSTK",
                    "exch_seg": "NFO",
                }
            )
            token += 1
    return rows


def _angel_quotes() -> dict[str, dict]:
    return {
        "100": {"opnInterest": 10, "impliedVolatility": 24},
        "101": {"opnInterest": 30, "impliedVolatility": 26},
        "102": {"opnInterest": 20, "impliedVolatility": 20},
        "103": {"opnInterest": 20, "impliedVolatility": 22},
        "104": {"opnInterest": 30, "impliedVolatility": 28},
        "105": {"opnInterest": 10, "impliedVolatility": 30},
        "FUT1": {"ltp": 105, "netChange": 5, "opnInterest": 1000, "oiChange": 100},
        "FUT2": {"ltp": 106, "netChange": 1, "opnInterest": 500, "oiChange": 50},
    }


def test_normalize_indian_symbol_accepts_ns_and_bo_tickers() -> None:
    assert normalize_indian_symbol("RELIANCE.NS") == "RELIANCE"
    assert normalize_indian_symbol("RELIANCE.BO") == "RELIANCE"
    assert normalize_indian_symbol("AAPL") is None


def test_indian_ticker_without_angel_credentials_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(fno_data, "SmartConnect", None)

    metrics = get_fno_metrics("RELIANCE.NS", scrip_master_loader=_angel_scrip_master)

    assert metrics.source_available is False
    assert metrics.availability_status == "fetch_failed"
    assert "tokens exist" in metrics.note
    assert metrics.pcr is None
    assert metrics.futures_oi_buildup is None


def test_indian_ticker_without_derivative_tokens_reports_no_derivatives() -> None:
    metrics = get_fno_metrics(
        "MAPMYINDIA.NS",
        angel_client=FakeAngelClient({}),
        scrip_master_loader=lambda: [
            {
                "token": "123",
                "symbol": "MAPMYINDIA-EQ",
                "name": "MAPMYINDIA",
                "expiry": "",
                "strike": "-1.000000",
                "instrumenttype": "",
                "exch_seg": "NSE",
            }
        ],
    )

    assert metrics.source_available is False
    assert metrics.availability_status == "no_derivatives"
    assert "does not appear to be in the F&O segment" in metrics.note


def test_indian_angel_route_calculates_pcr_rollover_buildup_max_pain_and_atm_iv() -> None:
    metrics = get_fno_metrics(
        "RELIANCE.NS",
        angel_client=FakeAngelClient(_angel_quotes()),
        scrip_master_loader=_angel_scrip_master,
    )

    assert metrics.source_available is True
    assert metrics.availability_status == "available"
    assert metrics.expiry == "30JUL2026"
    assert metrics.pcr == pytest.approx(1.0)
    assert metrics.futures_oi_buildup == "Long Build-up"
    assert metrics.rollover_pct == pytest.approx(33.33)
    assert metrics.atm_iv == pytest.approx(21.0)
    assert metrics.iv_percentile is None
    assert metrics.max_pain == 100


def test_global_yfinance_route_calculates_options_metrics_and_nulls_futures() -> None:
    calls = pd.DataFrame(
        {
            "strike": [90, 100, 110],
            "openInterest": [10, 20, 30],
            "impliedVolatility": [0.24, 0.20, 0.28],
        }
    )
    puts = pd.DataFrame(
        {
            "strike": [90, 100, 110],
            "openInterest": [30, 20, 10],
            "impliedVolatility": [0.26, 0.22, 0.30],
        }
    )
    fake_ticker = SimpleNamespace(
        options=["2026-05-30"],
        fast_info={"last_price": 100},
        option_chain=lambda expiry: SimpleNamespace(calls=calls, puts=puts),
    )

    metrics = get_fno_metrics("AAPL", yf_ticker_factory=lambda _: fake_ticker)

    assert metrics.source_available is True
    assert metrics.expiry == "2026-05-30"
    assert metrics.pcr == pytest.approx(1.0)
    assert metrics.max_pain == 100
    assert metrics.atm_iv == pytest.approx(21.0)
    assert metrics.futures_oi_buildup is None
    assert metrics.rollover_pct is None
    assert metrics.iv_percentile is None


def test_global_ticker_without_options_reports_no_derivatives() -> None:
    fake_ticker = SimpleNamespace(options=[])

    metrics = get_fno_metrics("NOOPT", yf_ticker_factory=lambda _: fake_ticker)

    assert metrics.source_available is False
    assert metrics.availability_status == "no_derivatives"
    assert "No listed options expiries" in metrics.note


def test_calculate_max_pain_uses_minimum_total_intrinsic_loss() -> None:
    rows = [
        {"strikePrice": 90, "CE": {"openInterest": 10}, "PE": {"openInterest": 30}},
        {"strikePrice": 100, "CE": {"openInterest": 20}, "PE": {"openInterest": 20}},
        {"strikePrice": 110, "CE": {"openInterest": 30}, "PE": {"openInterest": 10}},
    ]

    assert _calculate_max_pain(rows) == 100


@pytest.mark.parametrize(
    ("current_price", "previous_price", "current_oi", "previous_oi", "expected"),
    [
        (105, 100, 1100, 1000, "Long Build-up"),
        (95, 100, 1100, 1000, "Short Build-up"),
        (105, 100, 900, 1000, "Short Covering"),
        (95, 100, 900, 1000, "Long Unwinding"),
    ],
)
def test_futures_oi_buildup_classification(
    current_price: float,
    previous_price: float,
    current_oi: float,
    previous_oi: float,
    expected: str,
) -> None:
    assert _classify_futures_oi_buildup(current_price, previous_price, current_oi, previous_oi) == expected


def test_fno_signal_rules_and_iv_percentile_display_only() -> None:
    signals = build_fno_signals(
        FnoMetrics(
            pcr=1.35,
            futures_oi_buildup="Long Build-up",
            rollover_pct=80,
            iv_percentile=None,
            source_available=True,
        )
    )

    assert signals["pcr_sentiment"].label == SignalLabel.BULLISH
    assert signals["futures_oi_buildup"].label == SignalLabel.BULLISH
    assert signals["rollover_percentage"].label == SignalLabel.BULLISH
    assert signals["iv_percentile"].available is False
