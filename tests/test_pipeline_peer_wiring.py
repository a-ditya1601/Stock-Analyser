from __future__ import annotations

from datetime import datetime

import pandas as pd

from equity_reporter.models import MarketSnapshot
from equity_reporter.pipeline import _build_peer_context


def test_build_peer_context_uses_auto_peer_list_and_existing_math_chain(monkeypatch) -> None:
    snapshot = MarketSnapshot(
        ticker="AAPL",
        history=pd.DataFrame(),
        info={"priceToSalesTrailing12Months": 7.5},
        current_price=190.0,
        company_metadata={"sector": "Technology", "industry": "Consumer Electronics"},
        fetched_at=datetime(2026, 4, 24, 12, 0),
    )
    signals = {
        "forward_pe": 24.0,
        "profit_margin": 0.22,
        "quarterly_revenue_growth": 0.11,
    }

    seen: dict[str, object] = {}

    def _fake_get_auto_peers(ticker: str, **kwargs) -> list[str]:
        seen["ticker"] = ticker
        seen["peer_kwargs"] = kwargs
        return ["MSFT", "GOOGL", "AMZN"]

    def _fake_get_peer_group_averages(peer_list: list[str]) -> dict[str, float | None]:
        seen["peer_list"] = list(peer_list)
        return {
            "forwardPE": 20.0,
            "priceToSalesTrailing12Months": 6.0,
            "profitMargins": 0.18,
            "revenueGrowth": 0.09,
        }

    def _fake_relative_math(target: dict, peer_avg: dict) -> dict[str, float | None]:
        seen["target_metrics"] = dict(target)
        seen["peer_avg"] = dict(peer_avg)
        return {
            "target_forward_pe": 24.0,
            "peer_avg_forward_pe": 20.0,
            "pe_to_sector_pe_ratio": 1.2,
            "forward_pe_premium_pct": 20.0,
            "target_ps": 7.5,
            "peer_avg_ps": 6.0,
            "ps_premium_pct": 25.0,
            "target_margin": 0.22,
            "peer_avg_margin": 0.18,
            "margin_spread_pct": 4.0,
            "target_growth": 0.11,
            "peer_avg_growth": 0.09,
            "growth_spread_pct": 2.0,
        }

    def _fake_text_builder(peer_list: list[str], target: dict, avg: dict, relative: dict) -> str:
        seen["text_chain_inputs"] = {
            "peer_list": list(peer_list),
            "target": dict(target),
            "avg": dict(avg),
            "relative": dict(relative),
        }
        return "Automated Peer Basket: MSFT, GOOGL, AMZN."

    monkeypatch.setattr("equity_reporter.pipeline.get_auto_peers", _fake_get_auto_peers)
    monkeypatch.setattr("equity_reporter.pipeline.get_peer_group_averages", _fake_get_peer_group_averages)
    monkeypatch.setattr("equity_reporter.pipeline.calculate_relative_valuation", _fake_relative_math)
    monkeypatch.setattr("equity_reporter.pipeline.build_peer_valuation_text", _fake_text_builder)
    monkeypatch.setattr("equity_reporter.pipeline.build_peer_signals", lambda relative: {})

    context = _build_peer_context(snapshot, signals)

    assert seen["ticker"] == "AAPL"
    assert seen["peer_kwargs"]["target_metadata"] == {"sector": "Technology", "industry": "Consumer Electronics"}
    assert seen["peer_list"] == ["MSFT", "GOOGL", "AMZN"]
    assert context["peer_list"] == ["MSFT", "GOOGL", "AMZN"]
    assert context["peer_sector_text"] == "Automated Peer Basket: MSFT, GOOGL, AMZN."
    assert context["peer_target_ps"] == 7.5
    assert context["peer_pe_to_sector_pe_ratio"] == 1.2
