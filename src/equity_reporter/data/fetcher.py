from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any

import pandas as pd
import yfinance as yf

from equity_reporter.analysis.fno_data import (
    get_angel_token,
    initialize_angel_session,
    normalize_indian_symbol,
)
from equity_reporter.config import (
    CHART_CONTEXT_FETCH_RETRIES,
    CHART_CONTEXT_HISTORY_PERIOD_CANDIDATES,
    CHART_MIN_ROWS_FOR_FULL_SMA200,
    DEFAULT_HISTORY_PERIOD,
    DEFAULT_INTERVAL,
    FETCH_RETRY_BACKOFF_SECONDS,
    INFO_FETCH_RETRIES,
    MARKET_HISTORY_FETCH_RETRIES,
)
from equity_reporter.models import MarketSnapshot
from equity_reporter.utils.errors import DataUnavailableError
from equity_reporter.utils.logging_utils import get_logger


OHLCV_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
FAST_INFO_KEYS = (
    "lastPrice",
    "previousClose",
    "open",
    "dayHigh",
    "dayLow",
    "marketCap",
    "currency",
    "exchange",
    "quoteType",
    "timezone",
    "shares",
    "tenDayAverageVolume",
    "threeMonthAverageVolume",
    "yearHigh",
    "yearLow",
)
logger = get_logger(__name__)


def fetch_market_snapshot(ticker: str) -> MarketSnapshot:
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise DataUnavailableError("Ticker symbol cannot be empty.")

    yf_ticker = yf.Ticker(normalized_ticker)
    history, history_source, history_note = _fetch_history_for_ticker(
        yf_ticker=yf_ticker,
        ticker=normalized_ticker,
        period=DEFAULT_HISTORY_PERIOD,
        retries=MARKET_HISTORY_FETCH_RETRIES,
        required=True,
    )
    history = _normalize_history(history, normalized_ticker)

    fast_info = _fetch_fast_info(yf_ticker)
    info = _fetch_info(yf_ticker)

    company_metadata = _resolve_company_metadata(normalized_ticker, info, fast_info)
    current_price = _resolve_current_price(history, info, fast_info, history_source=history_source)

    return MarketSnapshot(
        ticker=normalized_ticker,
        history=history,
        info=info,
        current_price=current_price,
        company_metadata=company_metadata,
        fast_info=fast_info,
        fetched_at=datetime.now(tz=timezone.utc),
        history_source=history_source,
        history_note=history_note,
    )


def fetch_chart_context_history(ticker: str) -> pd.DataFrame | None:
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        return None

    best_normalized = pd.DataFrame()
    yf_ticker = yf.Ticker(normalized_ticker)

    for period in CHART_CONTEXT_HISTORY_PERIOD_CANDIDATES:
        history, _, _ = _fetch_history_for_ticker(
            yf_ticker=yf_ticker,
            ticker=normalized_ticker,
            period=period,
            retries=CHART_CONTEXT_FETCH_RETRIES,
            required=False,
        )
        if not _is_usable_history(history):
            continue

        normalized = _normalize_history(history, normalized_ticker)
        if normalized.empty:
            continue

        if len(normalized) > len(best_normalized):
            best_normalized = normalized

        if len(normalized) >= CHART_MIN_ROWS_FOR_FULL_SMA200:
            return normalized

    if not best_normalized.empty:
        return best_normalized

    # Last resort only: use the analysis-window fetch period if all context periods fail.
    history, _, _ = _fetch_history_for_ticker(
        yf_ticker=yf_ticker,
        ticker=normalized_ticker,
        period=DEFAULT_HISTORY_PERIOD,
        retries=CHART_CONTEXT_FETCH_RETRIES,
        required=False,
    )
    if not _is_usable_history(history):
        return None
    normalized = _normalize_history(history, normalized_ticker)
    return normalized if not normalized.empty else None


def _fetch_history_for_ticker(
    *,
    yf_ticker: Any,
    ticker: str,
    period: str,
    retries: int,
    required: bool,
) -> tuple[pd.DataFrame, str, str]:
    indian_symbol = normalize_indian_symbol(ticker)
    if indian_symbol:
        angel_history, angel_error = _try_fetch_angel_history(ticker=ticker, symbol=indian_symbol, period=period)
        if _is_usable_history(angel_history):
            return (
                angel_history,
                "angel_one",
                "Historical OHLCV sourced from Angel One SmartAPI.",
            )

        yahoo_history = _fetch_history_best_effort(
            yf_ticker=yf_ticker,
            ticker=ticker,
            period=period,
            retries=retries,
        )
        if _is_usable_history(yahoo_history):
            note = (
                "Angel One historical OHLCV was unavailable for this run; "
                "fell back to Yahoo Finance history."
            )
            if angel_error:
                note = f"{note} Angel reason: {angel_error}"
            return yahoo_history, "yfinance_fallback", note

        if required:
            detail = angel_error or "Angel One returned no usable rows"
            raise DataUnavailableError(
                f"Unable to fetch {period} daily OHLCV for {ticker}: Angel One failed ({detail}) "
                "and Yahoo Finance fallback returned no usable rows."
            )
        return pd.DataFrame(), "unavailable", angel_error or "No usable history returned."

    if required:
        yahoo_history = _fetch_history_with_fallback(yf_ticker, ticker)
    else:
        yahoo_history = _fetch_history_best_effort(
            yf_ticker=yf_ticker,
            ticker=ticker,
            period=period,
            retries=retries,
        )
    return yahoo_history, "yfinance", "Historical OHLCV sourced from Yahoo Finance."


def _try_fetch_angel_history(ticker: str, symbol: str, period: str) -> tuple[pd.DataFrame, str | None]:
    exchange = "BSE" if ticker.endswith(".BO") else "NSE"
    try:
        token_basket = get_angel_token(symbol)
    except Exception as exc:
        return pd.DataFrame(), f"ScripMaster token lookup failed: {exc}"

    equity_row = token_basket.equity
    if not equity_row:
        return pd.DataFrame(), "No Angel One equity token found."

    row_exchange = str(equity_row.get("exch_seg") or "").upper()
    if row_exchange in {"NSE", "BSE"}:
        exchange = row_exchange

    token = str(equity_row.get("token") or "").strip()
    if not token:
        return pd.DataFrame(), "Angel One equity token was blank."

    client = initialize_angel_session()
    if client is None:
        return pd.DataFrame(), "Angel One credentials/session unavailable."

    from_date = _period_start_datetime(period)
    to_date = datetime.now()
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "ONE_DAY",
        "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
        "todate": to_date.strftime("%Y-%m-%d %H:%M"),
    }
    try:
        response = client.getCandleData(params)
    except Exception as exc:
        return pd.DataFrame(), f"Historical candle fetch failed: {exc}"

    frame = _normalize_angel_candle_response(response)
    if frame.empty:
        return pd.DataFrame(), "Angel One returned no candle rows."
    return frame, None


def _period_start_datetime(period: str) -> datetime:
    normalized = (period or "").strip().lower()
    now = datetime.now()
    if normalized.endswith("mo"):
        months = _safe_int(normalized.removesuffix("mo"), default=12)
        return now - timedelta(days=max(1, months) * 31)
    if normalized.endswith("y"):
        years = _safe_int(normalized.removesuffix("y"), default=1)
        return now - timedelta(days=max(1, years) * 366)
    if normalized == "max":
        return now - timedelta(days=10 * 366)
    return now - timedelta(days=366)


def _normalize_angel_candle_response(response: Any) -> pd.DataFrame:
    if not isinstance(response, dict):
        return pd.DataFrame()
    rows = response.get("data")
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        normalized_rows.append(
            {
                "Date": row[0],
                "Open": row[1],
                "High": row[2],
                "Low": row[3],
                "Close": row[4],
                "Volume": row[5],
            }
        )
    if not normalized_rows:
        return pd.DataFrame()

    frame = pd.DataFrame(normalized_rows)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).set_index("Date")
    for column in OHLCV_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if isinstance(frame.index, pd.DatetimeIndex) and frame.index.tz is not None:
        frame.index = frame.index.tz_convert(None)
    return frame.sort_index()


def _safe_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fetch_history_with_fallback(yf_ticker: Any, ticker: str) -> pd.DataFrame:
    attempts = max(1, MARKET_HISTORY_FETCH_RETRIES)
    details: list[str] = []

    for attempt in range(attempts):
        history, primary_error = _try_fetch_history_primary(yf_ticker, DEFAULT_HISTORY_PERIOD)
        if _is_usable_history(history):
            return history

        history, fallback_error = _try_fetch_history_fallback_download(ticker, DEFAULT_HISTORY_PERIOD)
        if _is_usable_history(history):
            return history

        if primary_error is not None:
            details.append(f"primary error: {primary_error}")
        if fallback_error is not None:
            details.append(f"fallback error: {fallback_error}")

        if attempt < attempts - 1:
            wait_seconds = FETCH_RETRY_BACKOFF_SECONDS * float(attempt + 1)
            logger.warning(
                "History fetch retry %s/%s for %s (waiting %.2fs)",
                attempt + 2,
                attempts,
                ticker,
                wait_seconds,
            )
            time.sleep(wait_seconds)

    reason = "; ".join(_dedupe_preserve_order(details)) if details else (
        f"no rows returned from either source across {attempts} attempt(s)"
    )
    invalid_hint = ""
    if _looks_like_invalid_or_delisted(reason) or "no rows returned from either source" in reason:
        invalid_hint = " The ticker may be invalid, delisted, or not yet supported by the free Yahoo feed."
    raise DataUnavailableError(f"Unable to fetch 1y daily OHLCV for {ticker}: {reason}.{invalid_hint}")


def _fetch_history_best_effort(
    yf_ticker: Any,
    ticker: str,
    period: str,
    retries: int = 1,
) -> pd.DataFrame:
    attempts = max(1, retries)
    for attempt in range(attempts):
        history = _fetch_history_primary(yf_ticker, period)
        if _is_usable_history(history):
            return history

        history = _fetch_history_fallback_download(ticker, period)
        if _is_usable_history(history):
            return history

        if attempt < attempts - 1:
            time.sleep(FETCH_RETRY_BACKOFF_SECONDS * float(attempt + 1))

    return pd.DataFrame()


def _fetch_history_primary(yf_ticker: Any, period: str) -> pd.DataFrame:
    history, _ = _try_fetch_history_primary(yf_ticker, period)
    return history


def _try_fetch_history_primary(yf_ticker: Any, period: str) -> tuple[pd.DataFrame, Exception | None]:
    try:
        return (
            yf_ticker.history(
                period=period,
                interval=DEFAULT_INTERVAL,
                auto_adjust=False,
                actions=False,
            ),
            None,
        )
    except Exception as exc:  # pragma: no cover - network/API dependent.
        return pd.DataFrame(), exc


def _fetch_history_fallback_download(ticker: str, period: str) -> pd.DataFrame:
    history, _ = _try_fetch_history_fallback_download(ticker, period)
    return history


def _try_fetch_history_fallback_download(ticker: str, period: str) -> tuple[pd.DataFrame, Exception | None]:
    try:
        return (
            yf.download(
                tickers=ticker,
                period=period,
                interval=DEFAULT_INTERVAL,
                auto_adjust=False,
                actions=False,
                progress=False,
                group_by="column",
                threads=False,
            ),
            None,
        )
    except Exception as exc:  # pragma: no cover - network/API dependent.
        return pd.DataFrame(), exc


def _is_usable_history(history: pd.DataFrame | None) -> bool:
    return bool(history is not None and not history.empty)


def _normalize_history(history: pd.DataFrame, ticker: str) -> pd.DataFrame:
    normalized = history.copy()

    if isinstance(normalized.columns, pd.MultiIndex):
        level0 = [str(item) for item in normalized.columns.get_level_values(0)]
        level1 = [str(item) for item in normalized.columns.get_level_values(1)]
        if ticker in level1:
            normalized = normalized.xs(ticker, axis=1, level=1, drop_level=True)
        elif ticker in level0:
            normalized = normalized.xs(ticker, axis=1, level=0, drop_level=True)
        else:
            normalized.columns = normalized.columns.get_level_values(0)

    renamed_columns = {column: str(column).title() for column in normalized.columns}
    normalized = normalized.rename(columns=renamed_columns)

    for column in OHLCV_COLUMNS:
        if column in normalized.columns:
            column_values = normalized[column]
            if isinstance(column_values, pd.DataFrame):
                column_values = column_values.iloc[:, 0]
            normalized[column] = pd.to_numeric(column_values, errors="coerce")

    if isinstance(normalized.index, pd.DatetimeIndex) and normalized.index.tz is not None:
        normalized.index = normalized.index.tz_convert(None)

    normalized = normalized.sort_index()
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    return normalized


def _fetch_fast_info(yf_ticker: Any) -> dict[str, Any]:
    try:
        source = yf_ticker.fast_info
    except Exception:  # pragma: no cover - network/API dependent.
        return {}

    if source is None:
        return {}

    fast_info: dict[str, Any] = {}
    for key in FAST_INFO_KEYS:
        value = _dict_like_get(source, key)
        if value is not None:
            fast_info[key] = value

    if fast_info:
        return fast_info

    try:
        converted = dict(source)
    except Exception:  # pragma: no cover - network/API dependent.
        return {}
    return converted


def _fetch_info(yf_ticker: Any) -> dict[str, Any]:
    attempts = max(1, INFO_FETCH_RETRIES)
    for attempt in range(attempts):
        try:
            getter = getattr(yf_ticker, "get_info", None)
            if callable(getter):
                loaded = getter()
            else:
                loaded = yf_ticker.info
            if isinstance(loaded, dict) and loaded:
                return loaded
        except Exception:  # pragma: no cover - network/API dependent.
            pass

        if attempt < attempts - 1:
            time.sleep(FETCH_RETRY_BACKOFF_SECONDS * float(attempt + 1))

    return {}


def _resolve_company_metadata(ticker: str, info: dict[str, Any], fast_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "company_name": _first_non_empty(
            info.get("longName"),
            info.get("shortName"),
            info.get("displayName"),
            ticker,
        ),
        "sector": _first_non_empty(info.get("sector")),
        "industry": _first_non_empty(info.get("industry")),
        "country": _first_non_empty(info.get("country")),
        "currency": _first_non_empty(info.get("currency"), fast_info.get("currency")),
        "exchange": _first_non_empty(info.get("exchange"), fast_info.get("exchange")),
        "quote_type": _first_non_empty(info.get("quoteType"), fast_info.get("quoteType")),
    }


def _resolve_current_price(
    history: pd.DataFrame,
    info: dict[str, Any],
    fast_info: dict[str, Any],
    *,
    history_source: str = "yfinance",
) -> float | None:
    if history_source.startswith("angel"):
        latest_close = _latest_history_close(history)
        if latest_close is not None:
            return latest_close

    candidates = (
        fast_info.get("lastPrice"),
        info.get("currentPrice"),
        info.get("regularMarketPrice"),
        info.get("previousClose"),
    )

    for candidate in candidates:
        numeric = _coerce_float(candidate)
        if numeric is not None and numeric > 0:
            return numeric

    return _latest_history_close(history)


def _latest_history_close(history: pd.DataFrame) -> float | None:
    if "Close" not in history.columns or history["Close"].dropna().empty:
        return None
    latest_close = _coerce_float(history["Close"].iloc[-1])
    if latest_close is not None and latest_close > 0:
        return latest_close
    return None


def _dict_like_get(container: Any, key: str) -> Any:
    if isinstance(container, dict):
        return container.get(key)

    getter = getattr(container, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:  # pragma: no cover - container dependent.
            return None

    try:
        return container[key]
    except Exception:  # pragma: no cover - container dependent.
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return value
    return None


def _looks_like_invalid_or_delisted(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "possibly delisted",
        "no timezone found",
        "not found",
        "no data found",
        "failed to decrypt",
        "invalid",
    )
    return any(marker in lowered for marker in markers)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        trimmed = item.strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        ordered.append(trimmed)
    return ordered
