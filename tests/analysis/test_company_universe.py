from __future__ import annotations

from equity_reporter.analysis.company_universe import CompanyUniverseEntry, find_deterministic_peers, write_company_universe


def test_find_deterministic_peers_prefers_exact_industry(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "company_universe.json"
    write_company_universe(
        [
            CompanyUniverseEntry(
                ticker="MSFT",
                sector="Technology",
                industry="Software - Infrastructure",
                market_cap=3_000_000_000_000,
                exchange="NMS",
                currency="USD",
                quote_type="EQUITY",
                country="United States",
            ),
            CompanyUniverseEntry(
                ticker="ORCL",
                sector="Technology",
                industry="Software - Infrastructure",
                market_cap=350_000_000_000,
                exchange="NYQ",
                currency="USD",
                quote_type="EQUITY",
                country="United States",
            ),
            CompanyUniverseEntry(
                ticker="NVDA",
                sector="Technology",
                industry="Semiconductors",
                market_cap=2_000_000_000_000,
                exchange="NMS",
                currency="USD",
                quote_type="EQUITY",
                country="United States",
            ),
        ],
        path=cache_path,
    )
    monkeypatch.setattr("equity_reporter.analysis.company_universe._UNIVERSE_CACHE_FILE_PATH", cache_path)

    peers = find_deterministic_peers(
        "AAPL",
        target_metadata={
            "sector": "Technology",
            "industry": "Software - Infrastructure",
            "exchange": "NMS",
            "currency": "USD",
            "quote_type": "EQUITY",
            "country": "United States",
        },
        target_info={"marketCap": 2_800_000_000_000},
    )

    assert peers == ["MSFT", "ORCL", "NVDA"]


def test_find_deterministic_peers_uses_sector_fallback_when_industry_is_sparse(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "company_universe.json"
    write_company_universe(
        [
            CompanyUniverseEntry(ticker="AAA", sector="Industrials", industry="Aerospace & Defense", market_cap=100, quote_type="EQUITY"),
            CompanyUniverseEntry(ticker="BBB", sector="Industrials", industry="Specialty Industrial Machinery", market_cap=110, quote_type="EQUITY"),
            CompanyUniverseEntry(ticker="CCC", sector="Industrials", industry="Engineering & Construction", market_cap=90, quote_type="EQUITY"),
            CompanyUniverseEntry(ticker="DDD", sector="Healthcare", industry="Medical Devices", market_cap=120, quote_type="EQUITY"),
        ],
        path=cache_path,
    )
    monkeypatch.setattr("equity_reporter.analysis.company_universe._UNIVERSE_CACHE_FILE_PATH", cache_path)

    peers = find_deterministic_peers(
        "TARGET",
        target_metadata={"sector": "Industrials", "industry": "Aerospace & Defense", "quote_type": "EQUITY"},
        target_info={"marketCap": 100},
    )

    assert peers == ["AAA", "BBB", "CCC"]


def test_find_deterministic_peers_excludes_etfs_for_equity_targets(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "company_universe.json"
    write_company_universe(
        [
            CompanyUniverseEntry(ticker="VOO", sector="Technology", industry="Software - Infrastructure", quote_type="ETF"),
            CompanyUniverseEntry(ticker="MSFT", sector="Technology", industry="Software - Infrastructure", quote_type="EQUITY"),
        ],
        path=cache_path,
    )
    monkeypatch.setattr("equity_reporter.analysis.company_universe._UNIVERSE_CACHE_FILE_PATH", cache_path)

    peers = find_deterministic_peers(
        "AAPL",
        target_metadata={"sector": "Technology", "industry": "Software - Infrastructure", "quote_type": "EQUITY"},
    )

    assert peers == ["MSFT"]


def test_find_deterministic_peers_prefers_local_target_taxonomy(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "company_universe.json"
    write_company_universe(
        [
            CompanyUniverseEntry(ticker="DATAPATTNS.NS", sector="Capital Goods", industry="Capital Goods", quote_type="EQUITY"),
            CompanyUniverseEntry(ticker="BEL.NS", sector="Capital Goods", industry="Capital Goods", quote_type="EQUITY"),
            CompanyUniverseEntry(ticker="HAL.NS", sector="Capital Goods", industry="Capital Goods", quote_type="EQUITY"),
        ],
        path=cache_path,
    )
    monkeypatch.setattr("equity_reporter.analysis.company_universe._UNIVERSE_CACHE_FILE_PATH", cache_path)

    peers = find_deterministic_peers(
        "DATAPATTNS.NS",
        target_metadata={"sector": "Industrials", "industry": "Aerospace & Defense", "quote_type": "EQUITY"},
    )

    assert peers == ["BEL.NS", "HAL.NS"]


def test_collect_universe_symbols_uses_full_nse_source_not_local_nifty(monkeypatch) -> None:
    monkeypatch.setattr("equity_reporter.analysis.company_universe._collect_local_nifty500_symbols", lambda limit=None: ["NIFTYONLY.NS"])
    monkeypatch.setattr("equity_reporter.analysis.company_universe._read_url_text", lambda url: "SYMBOL,NAME OF COMPANY, SERIES\nAAA,AAA Ltd,EQ\nBBB,BBB Ltd,BE\nCCC,CCC Ltd,EQ\n")

    from equity_reporter.analysis.company_universe import collect_universe_symbols

    assert collect_universe_symbols(markets=["IN"]) == [("AAA.NS", "IN"), ("CCC.NS", "IN")]


def test_collect_us_symbols_excludes_etfs_and_test_issues(monkeypatch) -> None:
    payloads = {
        "nasdaqlisted": "Symbol|Security Name|Test Issue|ETF\nAAA|AAA Inc|N|N\nETF1|ETF One|N|Y\nTEST|Test Co|Y|N\nFile Creation Time: now|||\n",
        "otherlisted": "ACT Symbol|Security Name|Exchange|ETF|Test Issue\nBBB|BBB Inc|N|N|N\nETF2|ETF Two|P|Y|N\nTEST2|Test Two|A|N|Y\nFile Creation Time: now||||\n",
    }

    def _fake_read_url_text(url: str) -> str:
        if "nasdaqlisted" in url:
            return payloads["nasdaqlisted"]
        return payloads["otherlisted"]

    monkeypatch.setattr("equity_reporter.analysis.company_universe._read_url_text", _fake_read_url_text)

    from equity_reporter.analysis.company_universe import collect_universe_symbols

    assert collect_universe_symbols(markets=["US"]) == [("AAA", "US"), ("BBB", "US")]


def test_refresh_company_universe_writes_batches_and_resume_skips_fresh(monkeypatch, tmp_path) -> None:
    from equity_reporter.analysis.company_universe import refresh_company_universe

    cache_path = tmp_path / "company_universe.json"
    state_path = tmp_path / "company_universe_refresh_state.json"
    calls: list[str] = []
    monkeypatch.setattr(
        "equity_reporter.analysis.company_universe.collect_universe_symbols",
        lambda markets, limit_per_market=None: [("AAA", "US"), ("BBB", "US"), ("CCC", "US")],
    )

    def _fake_enrich(symbol: str, **kwargs) -> CompanyUniverseEntry:
        calls.append(symbol)
        return CompanyUniverseEntry(
            ticker=symbol,
            company_name=f"{symbol} Inc",
            sector="Technology",
            industry="Software",
            quote_type="EQUITY",
            source_market=kwargs.get("source_market"),
            refreshed_at="2026-05-14T00:00:00+00:00",
            enrichment_status="enriched",
        )

    monkeypatch.setattr("equity_reporter.analysis.company_universe.enrich_company_entry", _fake_enrich)

    first = refresh_company_universe(
        markets=["US"],
        batch_size=2,
        path=cache_path,
        state_path=state_path,
        fresh=True,
        pause_seconds=0,
    )
    assert len(first) == 3
    assert calls == ["AAA", "BBB", "CCC"]
    assert cache_path.exists()
    assert state_path.exists()

    calls.clear()
    second = refresh_company_universe(
        markets=["US"],
        batch_size=2,
        path=cache_path,
        state_path=state_path,
        resume=True,
        pause_seconds=0,
    )
    assert len(second) == 3
    assert calls == []
