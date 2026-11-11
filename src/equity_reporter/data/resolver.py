from __future__ import annotations

from typing import Any

import yfinance as yf

from equity_reporter.utils.errors import DataUnavailableError

SUPPORTED_QUOTE_TYPES = {
    "EQUITY",
    "ETF",
    "MUTUALFUND",
    "INDEX",
}


def resolve_ticker_input(query: str, max_results: int = 10) -> str:
    cleaned_query = query.strip()
    if not cleaned_query:
        raise DataUnavailableError("Ticker or company name cannot be empty.")

    try:
        search = yf.Search(cleaned_query, max_results=max_results, news_count=0)
        quotes = getattr(search, "quotes", []) or []
    except Exception as exc:  # pragma: no cover - network/provider dependent.
        raise DataUnavailableError(
            f"Unable to resolve company name '{cleaned_query}' to a ticker: {exc}"
        ) from exc

    ranked: list[tuple[float, str]] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue

        symbol = _clean_symbol(quote.get("symbol"))
        if not symbol:
            continue

        quote_type = str(quote.get("quoteType", "")).upper()
        if quote_type and quote_type not in SUPPORTED_QUOTE_TYPES:
            continue

        score = _score_quote(cleaned_query, quote)
        ranked.append((score, symbol))

    if not ranked:
        raise DataUnavailableError(
            f"Could not resolve '{cleaned_query}' to a supported ticker symbol."
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _score_quote(query: str, quote: dict[str, Any]) -> float:
    query_norm = query.strip().lower()
    query_words = [word for word in query_norm.split() if word]

    symbol = str(quote.get("symbol", "")).strip()
    short_name = str(quote.get("shortname", "")).strip().lower()
    long_name = str(quote.get("longname", "")).strip().lower()
    exchange = str(quote.get("exchange", "")).strip().lower()

    score = 0.0

    symbol_lower = symbol.lower()
    if symbol_lower == query_norm:
        score += 120.0
    elif symbol_lower.startswith(query_norm):
        score += 70.0

    if query_norm and query_norm in short_name:
        score += 55.0
    if query_norm and query_norm in long_name:
        score += 60.0

    if short_name == query_norm or long_name == query_norm:
        score += 90.0

    for word in query_words:
        if word in short_name:
            score += 10.0
        if word in long_name:
            score += 10.0

    if "nasdaq" in exchange or "nyse" in exchange:
        score += 2.0

    return score


def _clean_symbol(value: Any) -> str | None:
    if value is None:
        return None
    symbol = str(value).strip().upper()
    if not symbol:
        return None
    return symbol
