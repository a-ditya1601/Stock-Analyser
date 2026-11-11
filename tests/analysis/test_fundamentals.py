from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from equity_reporter.analysis.fundamentals import compute_fundamental_signals
from equity_reporter.models import MarketSnapshot, SignalLabel


def _snapshot(info: dict) -> MarketSnapshot:
    return MarketSnapshot(
        ticker="TEST.NS",
        history=pd.DataFrame(),
        info=info,
        current_price=100.0,
        company_metadata={"exchange": "NSE"},
        fetched_at=datetime(2026, 5, 16, 12, 0),
    )


def _stub_beta(monkeypatch) -> None:
    monkeypatch.setattr(
        "equity_reporter.analysis.fundamentals._compute_beta_suite",
        lambda snapshot: {
            "benchmark": "^NSEI",
            "beta_1m": None,
            "beta_1y": None,
            "beta_2y": None,
            "beta_5y": None,
            "beta_weekly": None,
        },
    )


def test_fundamentals_extracts_direct_roce_and_operating_margin(monkeypatch) -> None:
    _stub_beta(monkeypatch)
    monkeypatch.setattr(
        "equity_reporter.analysis.fundamentals._compute_statement_quality_metrics",
        lambda snapshot: {"return_on_capital_employed": None, "operating_margin": None},
    )
    snapshot = _snapshot({"returnOnCapitalEmployed": 0.18, "operatingMargins": 0.24})

    result = compute_fundamental_signals(snapshot, "balanced")

    assert result["return_on_capital_employed"] == pytest.approx(0.18)
    assert result["operating_margin"] == pytest.approx(0.24)
    assert result["fundamental_signals"]["return_on_capital_employed"].label == SignalLabel.BULLISH
    assert result["fundamental_signals"]["operating_margin"].label == SignalLabel.BULLISH


def test_fundamentals_prefers_statement_metrics_over_info_fallback(monkeypatch) -> None:
    _stub_beta(monkeypatch)
    monkeypatch.setattr(
        "equity_reporter.analysis.fundamentals._compute_statement_quality_metrics",
        lambda snapshot: {
            "return_on_capital_employed": 0.16,
            "operating_margin": 0.21,
            "debt_to_equity": 0.48,
            "current_ratio": 1.9,
            "quarterly_revenue_growth": 0.12,
            "free_cash_flow": 1000.0,
            "total_debt": 2000.0,
            "sources": {"debt_to_equity": "statement-derived"},
        },
    )
    snapshot = _snapshot(
        {
            "returnOnCapitalEmployed": 0.01,
            "operatingMargins": 0.02,
            "debtToEquity": 250.0,
            "currentRatio": 0.5,
            "quarterlyRevenueGrowth": -0.5,
            "freeCashflow": -100.0,
            "totalDebt": 9999.0,
        }
    )

    result = compute_fundamental_signals(snapshot, "balanced")

    assert result["return_on_capital_employed"] == pytest.approx(0.16)
    assert result["operating_margin"] == pytest.approx(0.21)
    assert result["debt_to_equity"] == pytest.approx(0.48)
    assert result["current_ratio"] == pytest.approx(1.9)
    assert result["quarterly_revenue_growth"] == pytest.approx(0.12)
    assert result["free_cash_flow"] == pytest.approx(1000.0)
    assert result["total_debt"] == pytest.approx(2000.0)


def test_fundamentals_normalizes_info_debt_to_equity_percent_style(monkeypatch) -> None:
    _stub_beta(monkeypatch)
    monkeypatch.setattr(
        "equity_reporter.analysis.fundamentals._compute_statement_quality_metrics",
        lambda snapshot: {},
    )

    result = compute_fundamental_signals(_snapshot({"debtToEquity": 48.04}), "balanced")

    assert result["debt_to_equity"] == pytest.approx(0.4804)
    assert result["fundamental_signals"]["debt_to_equity"].label == SignalLabel.BULLISH


def test_fundamentals_estimates_roce_and_opm_from_statements(monkeypatch) -> None:
    _stub_beta(monkeypatch)
    income_stmt = pd.DataFrame(
        {"2026": [120.0, 100.0, 500.0]},
        index=["EBIT", "Operating Income", "Total Revenue"],
    )
    balance_sheet = pd.DataFrame(
        {"2026": [1000.0, 250.0]},
        index=["Total Assets", "Current Liabilities"],
    )
    monkeypatch.setattr(
        "equity_reporter.analysis.fundamentals.yf.Ticker",
        lambda symbol: SimpleNamespace(income_stmt=income_stmt, financials=pd.DataFrame(), balance_sheet=balance_sheet),
    )

    result = compute_fundamental_signals(_snapshot({}), "balanced")

    assert result["return_on_capital_employed"] == pytest.approx(120.0 / 750.0)
    assert result["operating_margin"] == pytest.approx(100.0 / 500.0)


def test_fundamentals_marks_roce_and_opm_missing_when_unavailable(monkeypatch) -> None:
    _stub_beta(monkeypatch)
    monkeypatch.setattr(
        "equity_reporter.analysis.fundamentals.yf.Ticker",
        lambda symbol: SimpleNamespace(income_stmt=pd.DataFrame(), financials=pd.DataFrame(), balance_sheet=pd.DataFrame()),
    )

    result = compute_fundamental_signals(_snapshot({}), "balanced")

    assert result["return_on_capital_employed"] is None
    assert result["operating_margin"] is None
    assert result["fundamental_signals"]["return_on_capital_employed"].available is False
    assert result["fundamental_signals"]["operating_margin"].available is False
