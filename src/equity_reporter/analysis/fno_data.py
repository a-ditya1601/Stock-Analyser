from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from math import isfinite
import os
from typing import Any, Callable
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

from equity_reporter.models import FnoMetrics, MarketSnapshot, MetricSignal, SignalLabel

try:  # Keep import optional so reports degrade safely when Angel deps are not installed.
    from SmartApi import SmartConnect  # type: ignore
except Exception:  # pragma: no cover - import path depends on installed SDK version.
    try:
        from SmartApi.smartConnect import SmartConnect  # type: ignore
    except Exception:  # pragma: no cover
        try:
            from smartapi import SmartConnect  # type: ignore
        except Exception:  # pragma: no cover
            SmartConnect = None  # type: ignore

try:
    import pyotp  # type: ignore
except Exception:  # pragma: no cover
    pyotp = None  # type: ignore

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
DATA_UNAVAILABLE = "Data Unavailable"
_SCRIP_MASTER_CACHE: list[dict[str, Any]] | None = None

ScripMasterLoader = Callable[[], list[dict[str, Any]]]
YfTickerFactory = Callable[[str], Any]


@dataclass(slots=True)
class AngelTokenBasket:
    equity: dict[str, Any] | None
    near_future: dict[str, Any] | None
    next_future: dict[str, Any] | None
    option_rows: list[dict[str, Any]]
    expiry: str | None


def compute_fno_signals(snapshot: MarketSnapshot) -> dict[str, Any]:
    metrics = get_fno_metrics(snapshot.ticker)
    fno_signals = build_fno_signals(metrics)

    return {
        "fno": metrics,
        "fno_metrics": metrics,
        "fno_signals": fno_signals,
        "fno_pcr": metrics.pcr,
        "fno_futures_oi_buildup": metrics.futures_oi_buildup,
        "fno_rollover_pct": metrics.rollover_pct,
        "fno_iv_percentile": metrics.iv_percentile,
        "fno_atm_iv": metrics.atm_iv,
        "fno_max_pain": metrics.max_pain,
        "fno_expiry": metrics.expiry,
        "fno_source_available": metrics.source_available,
        "fno_availability_status": metrics.availability_status,
        "fno_note": metrics.note,
        "fno_text_block": build_fno_text_block(metrics),
    }


def get_fno_metrics(
    target_ticker: str,
    *,
    angel_client: Any | None = None,
    scrip_master_loader: ScripMasterLoader | None = None,
    yf_ticker_factory: YfTickerFactory | None = None,
) -> FnoMetrics:
    ticker = (target_ticker or "").strip().upper()
    clean_indian_symbol = normalize_indian_symbol(ticker)
    if clean_indian_symbol:
        return _get_indian_fno_metrics(
            clean_indian_symbol,
            angel_client=angel_client,
            scrip_master_loader=scrip_master_loader,
        )
    return _get_global_fno_metrics(ticker, yf_ticker_factory=yf_ticker_factory)


def build_fno_signals(metrics: FnoMetrics) -> dict[str, MetricSignal]:
    return {
        "futures_oi_buildup": _score_futures_oi_buildup(metrics.futures_oi_buildup),
        "rollover_percentage": _score_rollover(metrics.rollover_pct),
        "pcr_sentiment": _score_pcr(metrics.pcr),
        "iv_percentile": _score_iv_percentile(metrics.iv_percentile),
    }


def build_fno_text_block(metrics: FnoMetrics) -> str:
    oi_buildup = _text_value(metrics.futures_oi_buildup)
    rollover_pct = _number_text(metrics.rollover_pct)
    pcr = _number_text(metrics.pcr)
    iv_pct = _number_text(metrics.iv_percentile)
    max_pain = _number_text(metrics.max_pain)
    return (
        f"Derivatives & Smart Money Flow: Availability status is {metrics.availability_status}. "
        f"Futures positioning shows a {oi_buildup} "
        f"with a rollover rate of {rollover_pct}%. The Put-Call Ratio (PCR) stands at {pcr}, "
        f"and the IV Percentile is {iv_pct}%. The Options Max Pain level for the nearest expiry "
        f"is currently {max_pain}."
    )


def normalize_indian_symbol(target_ticker: str) -> str | None:
    cleaned = (target_ticker or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if cleaned.endswith(suffix):
            symbol = cleaned.removesuffix(suffix).strip()
            return symbol or None
    return None


def initialize_angel_session() -> Any | None:
    _load_env()
    api_key = os.getenv("ANGEL_API_KEY", "").strip()
    client_id = os.getenv("ANGEL_CLIENT_ID", "").strip()
    pin = os.getenv("ANGEL_PIN", "").strip()
    totp_secret = os.getenv("ANGEL_TOTP_SECRET", "").strip()
    if not all((api_key, client_id, pin, totp_secret)):
        return None
    if SmartConnect is None or pyotp is None:
        return None

    try:
        client = SmartConnect(api_key=api_key)
        totp = pyotp.TOTP(totp_secret).now()
        response = client.generateSession(client_id, pin, totp)
        if not isinstance(response, dict) or response.get("status") is not True:
            return None
        client.getfeedToken()
        return client
    except Exception:
        return None


def get_angel_token(symbol: str, scrip_master_loader: ScripMasterLoader | None = None) -> AngelTokenBasket:
    master = scrip_master_loader() if scrip_master_loader else load_angel_scrip_master()
    return _resolve_angel_token_basket(symbol, master)


def load_angel_scrip_master() -> list[dict[str, Any]]:
    global _SCRIP_MASTER_CACHE
    if _SCRIP_MASTER_CACHE is not None:
        return _SCRIP_MASTER_CACHE

    request = Request(
        SCRIP_MASTER_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=25) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        _SCRIP_MASTER_CACHE = []
    else:
        _SCRIP_MASTER_CACHE = [row for row in payload if isinstance(row, dict)]
    return _SCRIP_MASTER_CACHE


def _get_indian_fno_metrics(
    clean_symbol: str,
    *,
    angel_client: Any | None,
    scrip_master_loader: ScripMasterLoader | None,
) -> FnoMetrics:
    try:
        token_basket = get_angel_token(clean_symbol, scrip_master_loader)
    except Exception:
        return _unavailable_metrics(
            "Angel One ScripMaster token lookup failed, so derivative availability could not be confirmed.",
            status="fetch_failed",
        )

    if not token_basket.option_rows and not token_basket.near_future:
        return _unavailable_metrics(
            "No Angel One derivative tokens were found for this symbol; this equity does not appear to be in the F&O segment.",
            status="no_derivatives",
        )

    client = angel_client or initialize_angel_session()
    if client is None:
        return _unavailable_metrics(
            "F&O derivative tokens exist for this symbol, but Angel One credentials or SDK were unavailable for this run.",
            status="fetch_failed",
        )

    option_quotes = _fetch_angel_market_quotes(
        client,
        [str(row.get("token")) for row in token_basket.option_rows if row.get("token")],
        exchange="NFO",
    )
    option_rows = _merge_angel_option_rows(token_basket.option_rows, option_quotes)
    pcr = _calculate_pcr(option_rows)
    max_pain = _calculate_max_pain(option_rows)
    atm_iv = _extract_atm_iv(option_rows, {})

    future_tokens = [
        str(row.get("token"))
        for row in (token_basket.near_future, token_basket.next_future)
        if row and row.get("token")
    ]
    future_quotes = _fetch_angel_market_quotes(client, future_tokens, exchange="NFO")
    near_future = _merge_angel_future_row(token_basket.near_future, future_quotes)
    next_future = _merge_angel_future_row(token_basket.next_future, future_quotes)
    futures_buildup = _classify_future_row(near_future)
    rollover_pct = _calculate_rollover_pct(near_future, next_future)

    source_available = any(
        value is not None
        for value in (pcr, futures_buildup, rollover_pct, atm_iv, max_pain)
    )
    if not source_available:
        return _unavailable_metrics(
            "F&O derivative tokens exist for this symbol, but Angel One returned no usable market data in this run.",
            status="fetch_failed",
        )

    return FnoMetrics(
        pcr=pcr,
        futures_oi_buildup=futures_buildup,
        rollover_pct=rollover_pct,
        iv_percentile=None,
        atm_iv=atm_iv,
        max_pain=max_pain,
        expiry=token_basket.expiry,
        source_available=True,
        availability_status="available",
        note="F&O metrics sourced through Angel One SmartAPI and official ScripMaster token mapping.",
    )


def _get_global_fno_metrics(
    ticker: str,
    *,
    yf_ticker_factory: YfTickerFactory | None,
) -> FnoMetrics:
    if not ticker:
        return _unavailable_metrics(
            "Ticker was unavailable for global options routing.",
            status="fetch_failed",
        )
    try:
        ticker_obj = yf_ticker_factory(ticker) if yf_ticker_factory else yf.Ticker(ticker)
        expiries = list(getattr(ticker_obj, "options", []) or [])
        if not expiries:
            return _unavailable_metrics(
                "No listed options expiries were returned by Yahoo Finance for this symbol.",
                status="no_derivatives",
            )
        expiry = str(expiries[0])
        chain = ticker_obj.option_chain(expiry)
        calls = _normalize_option_frame(getattr(chain, "calls", None))
        puts = _normalize_option_frame(getattr(chain, "puts", None))
    except Exception:
        return _unavailable_metrics(
            "Yahoo Finance options chain exists or was requested, but the fetch failed in this run.",
            status="fetch_failed",
        )

    pcr = _calculate_global_pcr(calls, puts)
    max_pain = _calculate_global_max_pain(calls, puts)
    atm_iv = _calculate_global_atm_iv(ticker_obj, calls, puts)
    source_available = any(value is not None for value in (pcr, max_pain, atm_iv))
    if not source_available:
        return _unavailable_metrics(
            "Yahoo Finance options chain was fetched, but no usable option-chain metrics were available in this run.",
            status="fetch_failed",
        )

    return FnoMetrics(
        pcr=pcr,
        futures_oi_buildup=None,
        rollover_pct=None,
        iv_percentile=None,
        atm_iv=atm_iv,
        max_pain=max_pain,
        expiry=expiry,
        source_available=True,
        availability_status="available",
        note="Options metrics sourced from Yahoo Finance; single-stock futures metrics are unavailable for this route.",
    )


def _resolve_angel_token_basket(symbol: str, master: list[dict[str, Any]]) -> AngelTokenBasket:
    clean = symbol.strip().upper()
    equity = _first_row(
        master,
        lambda row: _row_name(row) == clean
        and str(row.get("exch_seg") or "").upper() in {"NSE", "BSE"}
        and str(row.get("symbol") or "").upper().endswith("-EQ"),
    )
    futures = [
        row
        for row in master
        if _row_name(row) == clean
        and str(row.get("exch_seg") or "").upper() == "NFO"
        and str(row.get("instrumenttype") or "").upper() == "FUTSTK"
    ]
    options = [
        row
        for row in master
        if _row_name(row) == clean
        and str(row.get("exch_seg") or "").upper() == "NFO"
        and str(row.get("instrumenttype") or "").upper() == "OPTSTK"
    ]

    futures.sort(key=_row_expiry_sort_key)
    option_expiry = _nearest_expiry_from_rows(options)
    option_rows = [row for row in options if _row_expiry_text(row) == option_expiry] if option_expiry else []

    return AngelTokenBasket(
        equity=equity,
        near_future=futures[0] if futures else None,
        next_future=futures[1] if len(futures) > 1 else None,
        option_rows=option_rows,
        expiry=option_expiry,
    )


def _fetch_angel_market_quotes(client: Any, tokens: list[str], *, exchange: str) -> dict[str, dict[str, Any]]:
    cleaned_tokens = [token for token in dict.fromkeys(tokens) if token]
    if not cleaned_tokens:
        return {}

    quotes: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(cleaned_tokens, 50):
        response = _safe_get_market_data(client, "FULL", {exchange: chunk})
        extracted = _extract_angel_fetched_quotes(response)
        quotes.update(extracted)
        missing = [token for token in chunk if token not in extracted]
        if missing and len(chunk) > 1:
            for token in missing:
                single = _safe_get_market_data(client, "FULL", {exchange: [token]})
                quotes.update(_extract_angel_fetched_quotes(single))
    return quotes


def _safe_get_market_data(client: Any, mode: str, exchange_tokens: dict[str, list[str]]) -> dict[str, Any]:
    try:
        response = client.getMarketData(mode, exchange_tokens)
        return response if isinstance(response, dict) else {}
    except Exception:
        return {}


def _extract_angel_fetched_quotes(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, dict):
        rows = data.get("fetched") or data.get("data") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = response.get("fetched") if isinstance(response, dict) else []
    if not isinstance(rows, list):
        return {}

    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        token = _quote_token(row)
        if token:
            output[token] = row
    return output


def _merge_angel_option_rows(master_rows: list[dict[str, Any]], quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_strike: dict[float, dict[str, Any]] = {}
    for row in master_rows:
        token = str(row.get("token") or "")
        quote = quotes.get(token, {})
        strike = _normalize_angel_strike(row.get("strike"))
        side = _option_side_from_symbol(row.get("symbol"))
        if strike is None or side not in {"CE", "PE"}:
            continue
        bucket = by_strike.setdefault(strike, {"strikePrice": strike})
        bucket[side] = {
            "openInterest": _first_numeric(
                quote,
                ("opnInterest", "openInterest", "oi", "openinterest"),
            ),
            "impliedVolatility": _first_numeric(
                quote,
                ("impliedVolatility", "impliedVol", "iv", "IV"),
            ),
        }
    return list(by_strike.values())


def _merge_angel_future_row(master_row: dict[str, Any] | None, quotes: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not master_row:
        return None
    quote = quotes.get(str(master_row.get("token") or ""), {})
    if not quote:
        return dict(master_row)
    merged = dict(master_row)
    merged.update(quote)
    return merged


def _score_futures_oi_buildup(value: str | None) -> MetricSignal:
    if not value:
        return _missing_signal(
            "futures_oi_buildup",
            "Futures OI build-up was unavailable from derivative data.",
        )

    normalized = value.strip().lower()
    if normalized == "long build-up":
        return MetricSignal(
            key="futures_oi_buildup",
            value=value,
            label=SignalLabel.BULLISH,
            score=1.0,
            available=True,
            note="Futures positioning shows long build-up: price and open interest rose together.",
        )
    if normalized == "short build-up":
        return MetricSignal(
            key="futures_oi_buildup",
            value=value,
            label=SignalLabel.BEARISH,
            score=0.0,
            available=True,
            note="Futures positioning shows short build-up: price fell while open interest expanded.",
        )
    return MetricSignal(
        key="futures_oi_buildup",
        value=value,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note="Futures positioning is transitional rather than a clean directional build-up.",
    )


def _score_rollover(value: float | None) -> MetricSignal:
    if value is None:
        return _missing_signal(
            "rollover_percentage",
            "Rollover percentage was unavailable from near/next month futures OI.",
        )
    if value > 75.0:
        label, score, note = (
            SignalLabel.BULLISH,
            1.0,
            "Rollover above 75% indicates strong carry-forward participation into the next series.",
        )
    elif value >= 60.0:
        label, score, note = (
            SignalLabel.NEUTRAL,
            0.5,
            "Rollover is in the neutral 60-75% band.",
        )
    else:
        label, score, note = (
            SignalLabel.BEARISH,
            0.0,
            "Rollover below 60% indicates weak carry-forward participation.",
        )
    return MetricSignal(
        key="rollover_percentage",
        value=value,
        label=label,
        score=score,
        available=True,
        note=note,
    )


def _score_pcr(value: float | None) -> MetricSignal:
    if value is None:
        return _missing_signal(
            "pcr_sentiment",
            "Put-call ratio was unavailable from nearest-expiry option-chain OI.",
        )
    if value > 1.30:
        label, score, note = (
            SignalLabel.BULLISH,
            1.0,
            "PCR above 1.30 is treated as contrarian oversold support.",
        )
    elif value >= 0.70:
        label, score, note = (
            SignalLabel.NEUTRAL,
            0.5,
            "PCR is in the neutral 0.70-1.30 sentiment band.",
        )
    else:
        label, score, note = (
            SignalLabel.BEARISH,
            0.0,
            "PCR below 0.70 indicates call-heavy overbought positioning risk.",
        )
    return MetricSignal(
        key="pcr_sentiment",
        value=value,
        label=label,
        score=score,
        available=True,
        note=note,
    )


def _score_iv_percentile(value: float | None) -> MetricSignal:
    if value is None:
        return _missing_signal(
            "iv_percentile",
            "True 52-week IV percentile is unavailable in F&O v1, so this metric is display-only.",
        )
    if value < 30.0:
        label, score, note = SignalLabel.BULLISH, 1.0, "IV percentile below 30% indicates lower volatility risk."
    elif value <= 80.0:
        label, score, note = SignalLabel.NEUTRAL, 0.5, "IV percentile is in a normal volatility band."
    else:
        label, score, note = SignalLabel.BEARISH, 0.0, "IV percentile above 80% flags extreme volatility risk."
    return MetricSignal(
        key="iv_percentile",
        value=value,
        label=label,
        score=score,
        available=True,
        note=note,
    )


def _calculate_pcr(option_rows: list[dict[str, Any]]) -> float | None:
    put_oi = 0.0
    call_oi = 0.0
    for row in option_rows:
        put_oi += _to_float(_nested_get(row, "PE", "openInterest")) or 0.0
        call_oi += _to_float(_nested_get(row, "CE", "openInterest")) or 0.0
    if call_oi <= 0:
        return None
    return round(put_oi / call_oi, 4)


def _calculate_max_pain(option_rows: list[dict[str, Any]]) -> float | None:
    strikes = sorted(
        {
            strike
            for row in option_rows
            if (strike := _to_float(row.get("strikePrice"))) is not None
        }
    )
    if not strikes:
        return None

    best_strike: float | None = None
    best_loss: float | None = None
    for settlement in strikes:
        total_loss = 0.0
        for row in option_rows:
            strike = _to_float(row.get("strikePrice"))
            if strike is None:
                continue
            call_oi = _to_float(_nested_get(row, "CE", "openInterest")) or 0.0
            put_oi = _to_float(_nested_get(row, "PE", "openInterest")) or 0.0
            total_loss += max(0.0, settlement - strike) * call_oi
            total_loss += max(0.0, strike - settlement) * put_oi
        if best_loss is None or total_loss < best_loss:
            best_loss = total_loss
            best_strike = settlement
    return best_strike


def _extract_atm_iv(option_rows: list[dict[str, Any]], records: dict[str, Any]) -> float | None:
    underlying = _to_float(records.get("underlyingValue"))
    if underlying is None:
        strikes = [_to_float(row.get("strikePrice")) for row in option_rows]
        valid_strikes = [strike for strike in strikes if strike is not None]
        underlying = valid_strikes[len(valid_strikes) // 2] if valid_strikes else None
    strike_rows = [
        (abs(strike - underlying), row)
        for row in option_rows
        if (strike := _to_float(row.get("strikePrice"))) is not None and underlying is not None
    ]
    if not strike_rows:
        return None
    _, atm_row = min(strike_rows, key=lambda item: item[0])
    iv_values = [
        _to_float(_nested_get(atm_row, side, "impliedVolatility"))
        for side in ("CE", "PE")
    ]
    valid = [value for value in iv_values if value is not None and value > 0]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)


def _classify_future_row(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    price = _first_numeric(row, ("ltp", "lastPrice", "close", "closePrice"))
    price_change = _first_numeric(row, ("netChange", "change", "changeInPrice"))
    current_oi = _first_numeric(row, ("opnInterest", "openInterest", "oi", "openinterest"))
    oi_change = _first_numeric(
        row,
        ("changeinOpenInterest", "changeInOpenInterest", "chgInOI", "oiChange", "oi_change"),
    )
    if price is None or price_change is None or current_oi is None or oi_change is None:
        return None
    prev_price = price - price_change
    prev_oi = current_oi - oi_change
    return _classify_futures_oi_buildup(price, prev_price, current_oi, prev_oi)


def _classify_futures_oi_buildup(
    current_price: float | None,
    previous_price: float | None,
    current_oi: float | None,
    previous_oi: float | None,
) -> str | None:
    if None in (current_price, previous_price, current_oi, previous_oi):
        return None
    assert current_price is not None
    assert previous_price is not None
    assert current_oi is not None
    assert previous_oi is not None
    price_up = current_price > previous_price
    oi_up = current_oi > previous_oi
    if price_up and oi_up:
        return "Long Build-up"
    if (not price_up) and oi_up:
        return "Short Build-up"
    if price_up and (not oi_up):
        return "Short Covering"
    return "Long Unwinding"


def _calculate_rollover_pct(near: dict[str, Any] | None, next_row: dict[str, Any] | None) -> float | None:
    near_oi = _first_numeric(near or {}, ("opnInterest", "openInterest", "oi", "openinterest"))
    next_oi = _first_numeric(next_row or {}, ("opnInterest", "openInterest", "oi", "openinterest"))
    if near_oi is None or next_oi is None:
        return None
    denominator = near_oi + next_oi
    if denominator <= 0:
        return None
    return round((next_oi / denominator) * 100.0, 2)


def _calculate_global_pcr(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    call_oi = _sum_frame_column(calls, "openInterest")
    put_oi = _sum_frame_column(puts, "openInterest")
    if call_oi is None or call_oi <= 0 or put_oi is None:
        return None
    return round(put_oi / call_oi, 4)


def _calculate_global_max_pain(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    if calls.empty and puts.empty:
        return None
    call_rows = _frame_option_rows(calls)
    put_rows = _frame_option_rows(puts)
    strikes = sorted({row[0] for row in call_rows + put_rows})
    if not strikes:
        return None

    best_strike: float | None = None
    best_loss: float | None = None
    for settlement in strikes:
        call_loss = sum(oi * max(0.0, settlement - strike) for strike, oi in call_rows)
        put_loss = sum(oi * max(0.0, strike - settlement) for strike, oi in put_rows)
        total_loss = call_loss + put_loss
        if best_loss is None or total_loss < best_loss:
            best_loss = total_loss
            best_strike = settlement
    return best_strike


def _calculate_global_atm_iv(ticker_obj: Any, calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    underlying = _resolve_yfinance_price(ticker_obj)
    frames = [frame for frame in (calls, puts) if not frame.empty and "impliedVolatility" in frame.columns]
    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty or "strike" not in combined.columns:
        return None
    combined["strike"] = pd.to_numeric(combined["strike"], errors="coerce")
    combined["impliedVolatility"] = pd.to_numeric(combined["impliedVolatility"], errors="coerce")
    combined = combined.dropna(subset=["strike", "impliedVolatility"])
    combined = combined[combined["impliedVolatility"] > 0]
    if combined.empty:
        return None
    if underlying is None:
        underlying = float(combined["strike"].median())
    combined["distance"] = (combined["strike"] - underlying).abs()
    nearest_distance = combined["distance"].min()
    atm = combined[combined["distance"] == nearest_distance]
    if atm.empty:
        return None
    return round(float(atm["impliedVolatility"].mean() * 100.0), 2)


def _normalize_option_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame()


def _frame_option_rows(frame: pd.DataFrame) -> list[tuple[float, float]]:
    if frame.empty or "strike" not in frame.columns or "openInterest" not in frame.columns:
        return []
    strikes = pd.to_numeric(frame["strike"], errors="coerce")
    oi = pd.to_numeric(frame["openInterest"], errors="coerce").fillna(0.0)
    rows: list[tuple[float, float]] = []
    for strike, open_interest in zip(strikes, oi, strict=False):
        if pd.isna(strike):
            continue
        rows.append((float(strike), float(open_interest)))
    return rows


def _sum_frame_column(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.sum())


def _resolve_yfinance_price(ticker_obj: Any) -> float | None:
    try:
        fast_info = getattr(ticker_obj, "fast_info", {}) or {}
        for key in ("last_price", "lastPrice", "regularMarketPrice"):
            value = fast_info.get(key) if isinstance(fast_info, dict) else getattr(fast_info, key, None)
            numeric = _to_float(value)
            if numeric is not None:
                return numeric
    except Exception:
        pass
    try:
        history = ticker_obj.history(period="5d")
        if isinstance(history, pd.DataFrame) and not history.empty and "Close" in history.columns:
            close = pd.to_numeric(history["Close"], errors="coerce").dropna()
            if not close.empty:
                return float(close.iloc[-1])
    except Exception:
        pass
    return None


def _first_row(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
    for row in rows:
        if predicate(row):
            return row
    return None


def _row_name(row: dict[str, Any]) -> str:
    return str(row.get("name") or "").strip().upper()


def _row_expiry_text(row: dict[str, Any]) -> str | None:
    expiry = str(row.get("expiry") or "").strip().upper()
    return expiry or None


def _nearest_expiry_from_rows(rows: list[dict[str, Any]]) -> str | None:
    expiries = sorted({_row_expiry_text(row) for row in rows if _row_expiry_text(row)}, key=_parse_expiry_sort_key)
    return expiries[0] if expiries else None


def _row_expiry_sort_key(row: dict[str, Any]) -> datetime:
    return _parse_expiry_sort_key(_row_expiry_text(row))


def _parse_expiry_sort_key(value: Any) -> datetime:
    text = str(value or "").strip().upper()
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d%b%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.date() >= date.today():
                return parsed
            return datetime.max.replace(year=9998)
        except ValueError:
            continue
    return datetime.max


def _normalize_angel_strike(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if abs(numeric) >= 1000:
        numeric = numeric / 100.0
    return numeric


def _option_side_from_symbol(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text.endswith("CE"):
        return "CE"
    if text.endswith("PE"):
        return "PE"
    return None


def _quote_token(row: dict[str, Any]) -> str | None:
    for key in ("symbolToken", "symboltoken", "token"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return None


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _nested_get(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_numeric(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _to_float(row.get(key))
        if value is not None:
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if isfinite(numeric) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "")
        if not text or text in {"-", "--"}:
            return None
        try:
            numeric = float(text)
        except ValueError:
            return None
        return numeric if isfinite(numeric) else None
    return None


def _text_value(value: Any) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    text = str(value).strip()
    return text if text else DATA_UNAVAILABLE


def _number_text(value: float | int | None) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    numeric = float(value)
    if not isfinite(numeric):
        return DATA_UNAVAILABLE
    if abs(numeric) >= 1000:
        return f"{numeric:,.2f}"
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def _missing_signal(key: str, note: str) -> MetricSignal:
    return MetricSignal(
        key=key,
        value=None,
        label=SignalLabel.MISSING,
        score=0.0,
        available=False,
        note=note,
    )


def _unavailable_metrics(note: str, *, status: str = "unavailable") -> FnoMetrics:
    return FnoMetrics(source_available=False, availability_status=status, note=note)


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()
