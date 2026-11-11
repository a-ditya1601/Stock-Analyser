from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from equity_reporter.analysis.peers import (
    PEER_DATA_FALLBACK_TEXT,
    build_peer_signals,
    build_peer_valuation_text,
    calculate_relative_valuation,
    get_auto_peers,
    get_nvidia_peers,
    get_peer_group_averages,
)
from equity_reporter.models import SignalLabel
from equity_reporter.utils.errors import NvidiaRateLimitError


def _set_cache_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("equity_reporter.analysis.peers._CACHE_FILE_PATH", tmp_path / "peer_baskets.json")


def _write_cache(path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_get_nvidia_peers_parses_fenced_output_and_filters(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, **kwargs) -> None:
            assert kwargs["model"] == "deepseek-ai/deepseek-v4-pro"
            assert kwargs["timeout_seconds"] == 30

        def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert "top 4 to 6" in system_prompt
            assert "Ticker: RELIANCE.NS" in user_prompt
            return "```python\n['HAL.NS', 'BEL.NS', 'BAD SYMBOL', 'RELIANCE.NS', 'BEL.NS', 'HAL.BO']\n```"

    monkeypatch.setattr("equity_reporter.analysis.peers.NvidiaService", _FakeService)
    monkeypatch.setattr("equity_reporter.analysis.peers.get_nvidia_peer_model", lambda: "deepseek-ai/deepseek-v4-pro")
    monkeypatch.setattr("equity_reporter.analysis.peers.get_nvidia_peer_timeout_seconds", lambda: 30)
    monkeypatch.setattr(
        "equity_reporter.analysis.peers._is_tradable_symbol",
        lambda symbol: symbol in {"HAL.NS", "BEL.NS"},
    )

    peers = get_nvidia_peers("RELIANCE.NS")
    assert peers == ["HAL.NS", "BEL.NS"]


def test_get_nvidia_peers_returns_empty_when_unparseable(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, **kwargs) -> None:
            _ = kwargs

        def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
            _ = (system_prompt, user_prompt)
            return "Top peers are HAL.NS and BEL.NS"

    monkeypatch.setattr("equity_reporter.analysis.peers.NvidiaService", _FakeService)
    monkeypatch.setattr("equity_reporter.analysis.peers.get_nvidia_peer_model", lambda: "deepseek-ai/deepseek-v4-pro")
    monkeypatch.setattr("equity_reporter.analysis.peers.get_nvidia_peer_timeout_seconds", lambda: 30)

    assert get_nvidia_peers("RELIANCE.NS") == []


def test_get_nvidia_peers_returns_empty_on_service_failure(monkeypatch) -> None:
    class _FakeService:
        def __init__(self, **kwargs) -> None:
            _ = kwargs

        def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
            _ = (system_prompt, user_prompt)
            raise NvidiaRateLimitError("rate limit")

    monkeypatch.setattr("equity_reporter.analysis.peers.NvidiaService", _FakeService)
    monkeypatch.setattr("equity_reporter.analysis.peers.get_nvidia_peer_model", lambda: "deepseek-ai/deepseek-v4-pro")
    monkeypatch.setattr("equity_reporter.analysis.peers.get_nvidia_peer_timeout_seconds", lambda: 30)

    assert get_nvidia_peers("AAPL") == []


def test_get_auto_peers_uses_builtin_override_before_cache(monkeypatch, tmp_path) -> None:
    _set_cache_file(monkeypatch, tmp_path)
    monkeypatch.setattr("equity_reporter.analysis.peers._is_tradable_symbol", lambda _: True)
    cache_file = tmp_path / "peer_baskets.json"
    _write_cache(
        cache_file,
        {
            "DATAPATTNS.NS": {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "peers": ["ABB.NS", "ACE.NS"],
            }
        },
    )

    assert get_auto_peers("DATAPATTNS.NS") == ["BEL.NS", "HAL.NS", "BDL.NS", "ASTRAMICRO.NS", "MTARTECH.NS"]


def test_get_auto_peers_uses_cache_before_deterministic_universe_for_uncurated_ticker(monkeypatch, tmp_path) -> None:
    _set_cache_file(monkeypatch, tmp_path)
    monkeypatch.setattr("equity_reporter.analysis.peers._is_tradable_symbol", lambda _: True)
    cache_file = tmp_path / "peer_baskets.json"
    _write_cache(
        cache_file,
        {
            "NEWCO": {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "peers": ["MSFT", "GOOG"],
            }
        },
    )

    monkeypatch.setattr("equity_reporter.analysis.peers.find_deterministic_peers", lambda *args, **kwargs: ["ORCL"])
    first = get_auto_peers("NEWCO")
    assert first == ["MSFT", "GOOG"]

def test_get_auto_peers_uses_deterministic_universe_when_no_cache_or_override(monkeypatch, tmp_path) -> None:
    _set_cache_file(monkeypatch, tmp_path)
    monkeypatch.setattr("equity_reporter.analysis.peers._is_tradable_symbol", lambda _: True)
    monkeypatch.setattr("equity_reporter.analysis.peers.find_deterministic_peers", lambda *args, **kwargs: ["AAA", "BBB"])

    assert get_auto_peers("NEWCO") == ["AAA", "BBB"]


def test_get_auto_peers_returns_cached_when_universe_has_no_match(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "peer_baskets.json"
    _set_cache_file(monkeypatch, tmp_path)
    monkeypatch.setattr("equity_reporter.analysis.peers.find_deterministic_peers", lambda *args, **kwargs: [])
    monkeypatch.setattr("equity_reporter.analysis.peers._is_tradable_symbol", lambda _: True)

    _write_cache(
        cache_file,
        {
            "NEWCO": {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "peers": ["MSFT", "GOOG"],
            }
        },
    )

    assert get_auto_peers("NEWCO") == ["MSFT", "GOOG"]


def test_get_auto_peers_ignores_expired_cache(monkeypatch, tmp_path) -> None:
    cache_file = tmp_path / "peer_baskets.json"
    _set_cache_file(monkeypatch, tmp_path)
    monkeypatch.setattr("equity_reporter.analysis.peers.find_deterministic_peers", lambda *args, **kwargs: [])
    monkeypatch.setattr("equity_reporter.analysis.peers._is_tradable_symbol", lambda _: True)

    _write_cache(
        cache_file,
        {
            "ZZZZ": {
                "updated_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
                "peers": ["MSFT"],
            }
        },
    )

    assert get_auto_peers("ZZZZ") == []


def test_get_auto_peers_uses_builtin_override_for_difficult_ticker(monkeypatch, tmp_path) -> None:
    _set_cache_file(monkeypatch, tmp_path)
    monkeypatch.setattr("equity_reporter.analysis.peers.find_deterministic_peers", lambda *args, **kwargs: [])
    monkeypatch.setattr("equity_reporter.analysis.peers._is_tradable_symbol", lambda _: True)

    assert get_auto_peers("DATAPATTNS.NS") == ["BEL.NS", "HAL.NS", "BDL.NS", "ASTRAMICRO.NS", "MTARTECH.NS"]


def test_get_peer_group_averages_ignores_missing_metrics(monkeypatch) -> None:
    peer_info = {
        "AAA": {
            "forwardPE": 20.0,
            "priceToSalesTrailing12Months": 4.0,
            "profitMargins": 0.15,
            "revenueGrowth": 0.10,
        },
        "BBB": {
            "forwardPE": None,
            "priceToSalesTrailing12Months": 6.0,
            "profitMargins": "N/A",
            "revenueGrowth": 0.20,
        },
    }

    def _fake_ticker(symbol: str) -> SimpleNamespace:
        return SimpleNamespace(info=peer_info.get(symbol, {}))

    monkeypatch.setattr("equity_reporter.analysis.peers.yf.Ticker", _fake_ticker)
    averages = get_peer_group_averages(["AAA", "BBB"])

    assert averages["forwardPE"] == 20.0
    assert averages["priceToSalesTrailing12Months"] == 5.0
    assert averages["profitMargins"] == 0.15
    assert averages["revenueGrowth"] == pytest.approx(0.15)


def test_calculate_relative_valuation_computes_premiums_and_spreads() -> None:
    result = calculate_relative_valuation(
        {
            "forwardPE": 24.0,
            "priceToSalesTrailing12Months": 5.0,
            "profitMargins": 0.20,
            "revenueGrowth": 0.18,
        },
        {
            "forwardPE": 20.0,
            "priceToSalesTrailing12Months": 4.0,
            "profitMargins": 0.15,
            "revenueGrowth": 0.12,
        },
    )

    assert result["forward_pe_premium_pct"] == pytest.approx(20.0)
    assert result["pe_to_sector_pe_ratio"] == pytest.approx(1.2)
    assert result["ps_premium_pct"] == pytest.approx(25.0)
    assert result["margin_spread_pct"] == pytest.approx(5.0)
    assert result["growth_spread_pct"] == pytest.approx(6.0)


def test_build_peer_valuation_text_returns_exact_fallback_when_no_peers() -> None:
    text = build_peer_valuation_text([], {}, {}, {})
    assert text == PEER_DATA_FALLBACK_TEXT


def test_build_peer_signals_marks_missing_when_relative_data_unavailable() -> None:
    signals = build_peer_signals(
        {
            "forward_pe_premium_pct": None,
            "pe_to_sector_pe_ratio": None,
            "ps_premium_pct": None,
            "margin_spread_pct": None,
            "growth_spread_pct": None,
        }
    )

    assert set(signals) == {
        "peer_forward_pe_premium",
        "peer_pe_to_sector_pe_ratio",
        "peer_ps_premium",
        "peer_margin_spread",
        "peer_growth_spread",
    }
    assert all(signal.label == SignalLabel.MISSING for signal in signals.values())
