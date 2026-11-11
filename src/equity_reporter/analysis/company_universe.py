from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import io
import json
from math import isfinite, log
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

DATA_UNAVAILABLE = "Data Unavailable"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UNIVERSE_CACHE_FILE_PATH = _REPO_ROOT / ".cache" / "company_universe.json"
_REFRESH_STATE_FILE_PATH = _REPO_ROOT / ".cache" / "company_universe_refresh_state.json"
_LOCAL_NIFTY500_CSV_PATH = _REPO_ROOT / "ind_nifty500list.csv"
_NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
_DEFAULT_USER_AGENT = "Mozilla/5.0 equity-reporter-company-universe/1.0"
_DEFAULT_TIMEOUT_SECONDS = 20

_MAX_PEERS = 6
_MIN_PEERS_BEFORE_SECTOR_FALLBACK = 3
_DEFAULT_BATCH_SIZE = 50
_DEFAULT_STALE_AFTER = timedelta(days=30)
_EQUITY_QUOTE_TYPES = {"EQUITY", "COMMONSTOCK", "STOCK"}
_ETF_QUOTE_TYPES = {"ETF", "MUTUALFUND", "FUND"}
_EXCLUDED_NON_EQUITY_TYPES = {"INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE", "OPTION"}


@dataclass(slots=True)
class CompanyUniverseEntry:
    ticker: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    exchange: str | None = None
    currency: str | None = None
    quote_type: str | None = None
    country: str | None = None
    source_market: str | None = None
    refreshed_at: str | None = None
    enrichment_status: str | None = None


def find_deterministic_peers(
    target_ticker: str,
    target_metadata: dict[str, Any] | None = None,
    target_info: dict[str, Any] | None = None,
    *,
    max_peers: int = _MAX_PEERS,
) -> list[str]:
    """Find peers from the local company universe using industry/sector similarity."""
    normalized_target = _normalize_symbol(target_ticker)
    if normalized_target is None:
        return []

    universe = load_company_universe()
    if not universe:
        return []

    local_target_entry = next((entry for entry in universe if entry.ticker == normalized_target), None)
    target = _build_target_entry(normalized_target, target_metadata=target_metadata, target_info=target_info)
    target = _merge_local_target_taxonomy(target, local_target_entry)
    if not target.industry and not target.sector:
        return []

    target_is_etf = _is_etf_quote_type(target.quote_type)
    candidates = [
        entry
        for entry in universe
        if _is_valid_candidate(entry, normalized_target, target_is_etf=target_is_etf)
        and (entry.industry or entry.sector)
    ]

    industry_matches: list[CompanyUniverseEntry] = []
    if target.industry:
        industry_matches = [
            entry for entry in candidates if _same_text(entry.industry, target.industry)
        ]

    selected = _rank_candidates(industry_matches, target)[:max_peers]

    if len(selected) < _MIN_PEERS_BEFORE_SECTOR_FALLBACK and target.sector:
        selected_symbols = {entry.ticker for entry in selected}
        sector_matches = [
            entry
            for entry in candidates
            if entry.ticker not in selected_symbols and _same_text(entry.sector, target.sector)
        ]
        selected.extend(_rank_candidates(sector_matches, target)[: max_peers - len(selected)])

    return [entry.ticker for entry in selected[:max_peers]]


def load_company_universe(path: Path | None = None) -> list[CompanyUniverseEntry]:
    cache_path = path or _UNIVERSE_CACHE_FILE_PATH
    try:
        parsed = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []

    raw_entries: Any
    if isinstance(parsed, dict):
        raw_entries = parsed.get("entries")
    else:
        raw_entries = parsed

    if not isinstance(raw_entries, list):
        return []

    entries: list[CompanyUniverseEntry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        entry = _entry_from_mapping(raw)
        if entry is None or entry.ticker in seen:
            continue
        seen.add(entry.ticker)
        entries.append(entry)
    return entries


def write_company_universe(entries: Iterable[CompanyUniverseEntry], path: Path | None = None) -> Path:
    cache_path = path or _UNIVERSE_CACHE_FILE_PATH
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": [asdict(entry) for entry in entries if entry.ticker],
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(cache_path)
    return cache_path


def read_refresh_state(path: Path | None = None) -> dict[str, Any]:
    state_path = path or _REFRESH_STATE_FILE_PATH
    try:
        parsed = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def write_refresh_state(state: dict[str, Any], path: Path | None = None) -> Path:
    state_path = path or _REFRESH_STATE_FILE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(state_path)
    return state_path


def _default_state_path_for_cache(cache_path: Path) -> Path:
    if cache_path == _UNIVERSE_CACHE_FILE_PATH:
        return _REFRESH_STATE_FILE_PATH
    return cache_path.with_name(f"{cache_path.stem}_refresh_state.json")


def refresh_company_universe(
    *,
    markets: Iterable[str] = ("IN", "US"),
    limit_per_market: int | None = None,
    pause_seconds: float = 0.05,
    path: Path | None = None,
    seed_only: bool = False,
    resume: bool = True,
    fresh: bool = False,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    state_path: Path | None = None,
    stale_after_days: int = 30,
    progress_callback: Callable[[int, int, int, int], None] | None = None,
) -> list[CompanyUniverseEntry]:
    if seed_only:
        entries = build_seed_only_company_universe(markets=markets, limit_per_market=limit_per_market)
        write_company_universe(entries, path=path)
        return entries

    symbols = collect_universe_symbols(markets=markets, limit_per_market=limit_per_market)
    seed_metadata = _load_local_nifty500_seed_metadata()
    cache_path = path or _UNIVERSE_CACHE_FILE_PATH
    refresh_state_path = state_path or _default_state_path_for_cache(cache_path)
    batch_size = max(1, int(batch_size or _DEFAULT_BATCH_SIZE))
    stale_after = timedelta(days=max(0, stale_after_days))

    if fresh:
        entries_by_ticker: dict[str, CompanyUniverseEntry] = {}
        state: dict[str, Any] = {}
    else:
        entries_by_ticker = {entry.ticker: entry for entry in load_company_universe(cache_path)}
        state = read_refresh_state(refresh_state_path) if resume else {}

    failed_symbols = set(_as_string_list(state.get("failed_symbols")))
    processed_symbols = set(_as_string_list(state.get("processed_symbols")))
    pending_entries: list[CompanyUniverseEntry] = []
    normalized_total_symbols = {
        normalized for symbol, _ in symbols if (normalized := _normalize_symbol(symbol)) is not None
    }
    total_symbol_count = len(normalized_total_symbols)

    for symbol, source_market in symbols:
        normalized = _normalize_symbol(symbol)
        if normalized is None:
            continue
        existing = entries_by_ticker.get(normalized)
        if resume and existing is not None and _entry_is_fresh(existing, stale_after):
            processed_symbols.add(normalized)
            continue

        entry = enrich_company_entry(
            normalized,
            source_market=source_market,
            seed_metadata=seed_metadata.get(normalized),
        )
        if entry is None:
            entry = _build_failed_entry(
                normalized,
                source_market=source_market,
                seed_metadata=seed_metadata.get(normalized),
            )
            failed_symbols.add(normalized)
        else:
            failed_symbols.discard(normalized)

        entries_by_ticker[normalized] = entry
        pending_entries.append(entry)
        processed_symbols.add(normalized)

        if len(pending_entries) >= batch_size:
            _persist_refresh_progress(
                entries_by_ticker=entries_by_ticker,
                processed_symbols=processed_symbols,
                failed_symbols=failed_symbols,
                symbols=symbols,
                markets=markets,
                cache_path=cache_path,
                state_path=refresh_state_path,
            )
            if progress_callback is not None:
                progress_callback(
                    len(processed_symbols),
                    total_symbol_count,
                    len(failed_symbols),
                    total_symbol_count - len(processed_symbols),
                )
            pending_entries.clear()

        if pause_seconds > 0:
            time.sleep(pause_seconds)

    _persist_refresh_progress(
        entries_by_ticker=entries_by_ticker,
        processed_symbols=processed_symbols,
        failed_symbols=failed_symbols,
        symbols=symbols,
        markets=markets,
        cache_path=cache_path,
        state_path=refresh_state_path,
        completed=True,
    )
    if progress_callback is not None:
        progress_callback(
            len(processed_symbols),
            total_symbol_count,
            len(failed_symbols),
            total_symbol_count - len(processed_symbols),
        )
    return list(entries_by_ticker.values())


def build_seed_only_company_universe(
    *,
    markets: Iterable[str] = ("IN",),
    limit_per_market: int | None = None,
) -> list[CompanyUniverseEntry]:
    normalized_markets = {str(market or "").strip().upper() for market in markets}
    entries: list[CompanyUniverseEntry] = []

    if "IN" in normalized_markets or "INDIA" in normalized_markets:
        metadata = _load_local_nifty500_seed_metadata()
        for ticker in _collect_local_nifty500_symbols(limit=limit_per_market):
            seed = metadata.get(ticker, {})
            industry = _clean_text(seed.get("industry"))
            entries.append(
                CompanyUniverseEntry(
                    ticker=ticker,
                    company_name=_clean_text(seed.get("company_name")),
                    sector=industry,
                    industry=industry,
                    exchange="NSI",
                    currency="INR",
                    quote_type="EQUITY",
                    country="India",
                    source_market="IN",
                    refreshed_at=datetime.now(timezone.utc).isoformat(),
                    enrichment_status="partial",
                )
            )

    return entries


def collect_universe_symbols(
    *,
    markets: Iterable[str] = ("IN", "US"),
    limit_per_market: int | None = None,
) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    normalized_markets = {str(market or "").strip().upper() for market in markets}

    if "IN" in normalized_markets or "INDIA" in normalized_markets:
        output.extend((symbol, "IN") for symbol in _collect_nse_symbols(limit=limit_per_market, prefer_local=False))
    if "US" in normalized_markets:
        output.extend((symbol, "US") for symbol in _collect_us_symbols(limit=limit_per_market))

    return output


def enrich_company_entry(
    symbol: str,
    *,
    source_market: str | None = None,
    seed_metadata: dict[str, Any] | None = None,
) -> CompanyUniverseEntry | None:
    normalized = _normalize_symbol(symbol)
    if normalized is None:
        return None

    seed = seed_metadata or {}

    try:
        ticker = yf.Ticker(normalized)
        info = ticker.info or {}
    except Exception:
        info = {}

    quote_type = _clean_text(info.get("quoteType"))
    if quote_type and quote_type.upper() in _EXCLUDED_NON_EQUITY_TYPES:
        return None

    sector = _clean_text(info.get("sector"))
    industry = _clean_text(info.get("industry"), seed.get("industry"))
    if not sector and not industry:
        return None

    return CompanyUniverseEntry(
        ticker=normalized,
        company_name=_clean_text(info.get("longName"), info.get("shortName"), info.get("displayName"), seed.get("company_name")),
        sector=sector,
        industry=industry,
        market_cap=_to_float(info.get("marketCap")),
        exchange=_clean_text(info.get("exchange")),
        currency=_clean_text(info.get("currency")),
        quote_type=quote_type,
        country=_clean_text(info.get("country")),
        source_market=source_market,
        refreshed_at=datetime.now(timezone.utc).isoformat(),
        enrichment_status=_entry_status(sector=sector, industry=industry, info=info),
    )


def _build_target_entry(
    normalized_target: str,
    *,
    target_metadata: dict[str, Any] | None = None,
    target_info: dict[str, Any] | None = None,
) -> CompanyUniverseEntry:
    metadata = target_metadata or {}
    info = target_info or {}

    sector = _clean_text(metadata.get("sector"), info.get("sector"))
    industry = _clean_text(metadata.get("industry"), info.get("industry"))
    market_cap = _to_float(info.get("marketCap"))
    exchange = _clean_text(metadata.get("exchange"), info.get("exchange"))
    currency = _clean_text(metadata.get("currency"), info.get("currency"))
    quote_type = _clean_text(metadata.get("quote_type"), metadata.get("quoteType"), info.get("quoteType"))
    country = _clean_text(metadata.get("country"), info.get("country"))

    if sector or industry:
        return CompanyUniverseEntry(
            ticker=normalized_target,
            sector=sector,
            industry=industry,
            market_cap=market_cap,
            exchange=exchange,
            currency=currency,
            quote_type=quote_type,
            country=country,
        )

    try:
        fetched_info = yf.Ticker(normalized_target).info or {}
    except Exception:
        fetched_info = {}

    return CompanyUniverseEntry(
        ticker=normalized_target,
        sector=_clean_text(fetched_info.get("sector")),
        industry=_clean_text(fetched_info.get("industry")),
        market_cap=_to_float(fetched_info.get("marketCap")),
        exchange=_clean_text(fetched_info.get("exchange")),
        currency=_clean_text(fetched_info.get("currency")),
        quote_type=_clean_text(fetched_info.get("quoteType")),
        country=_clean_text(fetched_info.get("country")),
    )


def _merge_local_target_taxonomy(
    target: CompanyUniverseEntry,
    local_target_entry: CompanyUniverseEntry | None,
) -> CompanyUniverseEntry:
    if local_target_entry is None:
        return target

    # Peer matching should use one consistent taxonomy. When the local universe
    # provides the target row (for example, Nifty 500 CSV sectors), prefer that
    # classification over Yahoo's more granular wording.
    return CompanyUniverseEntry(
        ticker=target.ticker,
        company_name=target.company_name or local_target_entry.company_name,
        sector=local_target_entry.sector or target.sector,
        industry=local_target_entry.industry or target.industry,
        market_cap=target.market_cap or local_target_entry.market_cap,
        exchange=target.exchange or local_target_entry.exchange,
        currency=target.currency or local_target_entry.currency,
        quote_type=target.quote_type or local_target_entry.quote_type,
        country=target.country or local_target_entry.country,
        source_market=local_target_entry.source_market,
        refreshed_at=local_target_entry.refreshed_at,
        enrichment_status=local_target_entry.enrichment_status,
    )


def _persist_refresh_progress(
    *,
    entries_by_ticker: dict[str, CompanyUniverseEntry],
    processed_symbols: set[str],
    failed_symbols: set[str],
    symbols: list[tuple[str, str]],
    markets: Iterable[str],
    cache_path: Path,
    state_path: Path,
    completed: bool = False,
) -> None:
    ordered_entries = [entries_by_ticker[ticker] for ticker in sorted(entries_by_ticker)]
    write_company_universe(ordered_entries, path=cache_path)
    all_symbols = {_normalize_symbol(symbol) for symbol, _ in symbols}
    normalized_all_symbols = {symbol for symbol in all_symbols if symbol is not None}
    pending_symbols = sorted(normalized_all_symbols - processed_symbols)
    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed": bool(completed),
        "markets": [str(market).strip().upper() for market in markets],
        "total_symbols": len(normalized_all_symbols),
        "processed_count": len(processed_symbols),
        "failed_count": len(failed_symbols),
        "pending_count": len(pending_symbols),
        "processed_symbols": sorted(processed_symbols),
        "failed_symbols": sorted(failed_symbols),
        "pending_symbols": pending_symbols,
    }
    write_refresh_state(state, path=state_path)


def _build_failed_entry(
    ticker: str,
    *,
    source_market: str | None,
    seed_metadata: dict[str, Any] | None = None,
) -> CompanyUniverseEntry:
    seed = seed_metadata or {}
    return CompanyUniverseEntry(
        ticker=ticker,
        company_name=_clean_text(seed.get("company_name")),
        sector=None,
        industry=_clean_text(seed.get("industry")),
        exchange="NSI" if source_market == "IN" else None,
        currency="INR" if source_market == "IN" else None,
        quote_type="EQUITY",
        country="India" if source_market == "IN" else None,
        source_market=source_market,
        refreshed_at=datetime.now(timezone.utc).isoformat(),
        enrichment_status="partial" if seed.get("industry") else "failed",
    )


def _entry_status(*, sector: str | None, industry: str | None, info: dict[str, Any]) -> str:
    if sector and industry and info:
        return "enriched"
    if sector or industry:
        return "partial"
    return "failed"


def _entry_is_fresh(entry: CompanyUniverseEntry, stale_after: timedelta) -> bool:
    if stale_after.total_seconds() <= 0:
        return False
    parsed = _parse_timestamp(entry.refreshed_at)
    if parsed is None:
        return False
    return datetime.now(timezone.utc) - parsed <= stale_after


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _normalize_symbol(item)
        if text is not None:
            output.append(text)
    return output


def _is_valid_candidate(entry: CompanyUniverseEntry, target_ticker: str, *, target_is_etf: bool) -> bool:
    if not entry.ticker or entry.ticker == target_ticker:
        return False
    if _base_symbol(entry.ticker) == _base_symbol(target_ticker):
        return False

    quote_type = (entry.quote_type or "").strip().upper()
    if quote_type in _EXCLUDED_NON_EQUITY_TYPES:
        return False
    if target_is_etf:
        return _is_etf_quote_type(entry.quote_type)
    if _is_etf_quote_type(entry.quote_type):
        return False
    return True


def _rank_candidates(candidates: list[CompanyUniverseEntry], target: CompanyUniverseEntry) -> list[CompanyUniverseEntry]:
    return sorted(candidates, key=lambda entry: _candidate_sort_key(entry, target))


def _candidate_sort_key(entry: CompanyUniverseEntry, target: CompanyUniverseEntry) -> tuple[float, str]:
    # Python sorts ascending, so negate positive quality score.
    score = 0.0
    if _same_text(entry.industry, target.industry):
        score += 100.0
    if _same_text(entry.sector, target.sector):
        score += 50.0
    if _same_text(entry.currency, target.currency):
        score += 15.0
    if _same_text(entry.exchange, target.exchange):
        score += 10.0
    if _same_text(entry.country, target.country):
        score += 8.0
    if entry.market_cap is not None and target.market_cap is not None and entry.market_cap > 0 and target.market_cap > 0:
        distance = abs(log(entry.market_cap / target.market_cap))
        score += max(0.0, 40.0 - (distance * 10.0))
    elif entry.market_cap is not None:
        score += 2.0
    return (-score, entry.ticker)


def _collect_nse_symbols(*, limit: int | None = None, prefer_local: bool = False) -> list[str]:
    local_symbols = _collect_local_nifty500_symbols(limit=limit)
    if prefer_local and local_symbols:
        return local_symbols

    try:
        raw = _read_url_text(_NSE_EQUITY_LIST_URL)
        frame = pd.read_csv(io.StringIO(raw))
    except Exception:
        return []

    symbol_column = _find_column(frame, "SYMBOL")
    series_column = _find_column(frame, "SERIES")
    if symbol_column is None:
        return []

    if series_column is not None:
        frame = frame[frame[series_column].astype(str).str.upper().eq("EQ")]

    symbols: list[str] = []
    for raw_symbol in frame[symbol_column].tolist():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        normalized = _normalize_symbol(f"{symbol}.NS")
        if normalized is not None:
            symbols.append(normalized)
        if limit is not None and len(symbols) >= limit:
            break
    return symbols


def _collect_local_nifty500_symbols(*, limit: int | None = None) -> list[str]:
    if not _LOCAL_NIFTY500_CSV_PATH.exists():
        return []

    try:
        frame = pd.read_csv(_LOCAL_NIFTY500_CSV_PATH)
    except Exception:
        return []

    symbol_column = _find_column(frame, "Symbol")
    series_column = _find_column(frame, "Series")
    if symbol_column is None:
        return []

    if series_column is not None:
        frame = frame[frame[series_column].astype(str).str.upper().eq("EQ")]

    symbols: list[str] = []
    for raw_symbol in frame[symbol_column].tolist():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        normalized = _normalize_symbol(f"{symbol}.NS")
        if normalized is not None:
            symbols.append(normalized)
        if limit is not None and len(symbols) >= limit:
            break
    return symbols


def _load_local_nifty500_seed_metadata() -> dict[str, dict[str, str]]:
    if not _LOCAL_NIFTY500_CSV_PATH.exists():
        return {}

    try:
        frame = pd.read_csv(_LOCAL_NIFTY500_CSV_PATH)
    except Exception:
        return {}

    symbol_column = _find_column(frame, "Symbol")
    company_column = _find_column(frame, "Company Name")
    industry_column = _find_column(frame, "Industry")
    if symbol_column is None:
        return {}

    output: dict[str, dict[str, str]] = {}
    for _, row in frame.iterrows():
        symbol = _normalize_symbol(f"{row.get(symbol_column)}.NS")
        if symbol is None:
            continue
        output[symbol] = {
            "company_name": _clean_text(row.get(company_column)) or "",
            "industry": _clean_text(row.get(industry_column)) or "",
        }
    return output


def _collect_us_symbols(*, limit: int | None = None) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for url, symbol_column_name in ((_NASDAQ_LISTED_URL, "Symbol"), (_OTHER_LISTED_URL, "ACT Symbol")):
        try:
            raw = _read_url_text(url)
            frame = pd.read_csv(io.StringIO(raw), sep="|")
        except Exception:
            continue

        symbol_column = _find_column(frame, symbol_column_name)
        test_issue_column = _find_column(frame, "Test Issue")
        etf_column = _find_column(frame, "ETF")
        if symbol_column is None:
            continue

        for _, row in frame.iterrows():
            raw_symbol = str(row.get(symbol_column) or "").strip().upper()
            if not raw_symbol or raw_symbol.startswith("FILE CREATION TIME"):
                continue
            if test_issue_column is not None and str(row.get(test_issue_column) or "").strip().upper() == "Y":
                continue
            if etf_column is not None and str(row.get(etf_column) or "").strip().upper() == "Y":
                # Keep ETF peer baskets for existing cache/manual overrides; skip broad ETF universe for equity peer matching.
                continue
            symbol = raw_symbol.replace("/", "-")
            normalized = _normalize_symbol(symbol)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            symbols.append(normalized)
            if limit is not None and len(symbols) >= limit:
                return symbols
    return symbols


def _read_url_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": _DEFAULT_USER_AGENT})
    with urlopen(request, timeout=_DEFAULT_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed public market-data URLs.
        return response.read().decode("utf-8", errors="replace")


def _entry_from_mapping(raw: dict[str, Any]) -> CompanyUniverseEntry | None:
    ticker = _normalize_symbol(raw.get("ticker"))
    if ticker is None:
        return None
    return CompanyUniverseEntry(
        ticker=ticker,
        company_name=_clean_text(raw.get("company_name")),
        sector=_clean_text(raw.get("sector")),
        industry=_clean_text(raw.get("industry")),
        market_cap=_to_float(raw.get("market_cap")),
        exchange=_clean_text(raw.get("exchange")),
        currency=_clean_text(raw.get("currency")),
        quote_type=_clean_text(raw.get("quote_type")),
        country=_clean_text(raw.get("country")),
        source_market=_clean_text(raw.get("source_market")),
        refreshed_at=_clean_text(raw.get("refreshed_at")),
        enrichment_status=_clean_text(raw.get("enrichment_status")),
    )


def _find_column(frame: pd.DataFrame, name: str) -> str | None:
    lowered = name.strip().lower()
    for column in frame.columns:
        if str(column).strip().lower() == lowered:
            return str(column)
    return None


def _clean_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _same_text(left: Any, right: Any) -> bool:
    left_text = _clean_text(left)
    right_text = _clean_text(right)
    if not left_text or not right_text:
        return False
    return left_text.casefold() == right_text.casefold()


def _is_etf_quote_type(value: Any) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    return text.upper() in _ETF_QUOTE_TYPES


def _normalize_symbol(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=")
    if any(char not in allowed for char in text):
        return None
    return text


def _base_symbol(value: str) -> str:
    return value.split(".", 1)[0]


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric):
        return None
    return numeric
