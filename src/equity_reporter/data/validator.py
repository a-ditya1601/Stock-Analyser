from __future__ import annotations

import pandas as pd

from equity_reporter.models import MarketSnapshot
from equity_reporter.utils.errors import DataUnavailableError, ValidationError


REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
PRICE_COLUMNS = ("Open", "High", "Low", "Close")


def validate_market_snapshot(snapshot: MarketSnapshot) -> None:
    if snapshot.history is None or snapshot.history.empty:
        raise DataUnavailableError(
            f"No historical market data returned for ticker '{snapshot.ticker}'. "
            "The ticker may be invalid, delisted, or temporarily unavailable."
        )

    missing = set(REQUIRED_COLUMNS) - set(snapshot.history.columns)
    if missing:
        raise ValidationError(f"Missing required market columns: {sorted(missing)}")

    history = snapshot.history.copy()
    if not isinstance(history.index, pd.DatetimeIndex):
        raise ValidationError("Historical index must be a DatetimeIndex.")

    required_frame = history.loc[:, list(REQUIRED_COLUMNS)]
    usable_rows = required_frame.dropna(subset=PRICE_COLUMNS, how="all")
    if usable_rows.empty:
        raise DataUnavailableError(
            f"No usable OHLC rows found for ticker '{snapshot.ticker}'. "
            "The symbol may be invalid or the feed may be empty."
        )

    close_series = pd.to_numeric(required_frame["Close"], errors="coerce")
    if close_series.dropna().empty:
        raise ValidationError("Close price data is present but entirely non-numeric or missing.")

    bad_price_columns: list[str] = []
    for column in PRICE_COLUMNS:
        series = pd.to_numeric(required_frame[column], errors="coerce")
        non_null = series.dropna()
        if not non_null.empty and (non_null <= 0).any():
            bad_price_columns.append(column)

    if bad_price_columns:
        raise ValidationError(
            f"Invalid non-positive price values found in columns: {', '.join(bad_price_columns)}"
        )

    volume_series = pd.to_numeric(required_frame["Volume"], errors="coerce")
    non_null_volume = volume_series.dropna()
    if not non_null_volume.empty and (non_null_volume < 0).any():
        raise ValidationError("Volume contains negative values, which indicates malformed market data.")
