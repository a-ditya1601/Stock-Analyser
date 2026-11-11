from __future__ import annotations

from math import isfinite
from typing import Any

import pandas as pd
import yfinance as yf

from equity_reporter.config import (
    BETA_BANDS_BY_RISK_PROFILE,
    CURRENT_RATIO_BANDS,
    DEBT_TO_EQUITY_BANDS,
    FCF_TO_DEBT_BANDS,
    PROFIT_MARGIN_BANDS,
    REVENUE_GROWTH_BANDS,
    ROCE_BANDS,
    ROE_BANDS,
    SHORT_PERCENT_FLOAT_BANDS,
    SHORT_RATIO_BANDS,
)
from equity_reporter.models import FundamentalMetrics, MarketSnapshot, MetricSignal, SignalLabel, ThresholdBand

BETA_LOOKBACK_OFFSETS: dict[str, pd.DateOffset] = {
    "1m": pd.DateOffset(months=1),
    "1y": pd.DateOffset(years=1),
    "2y": pd.DateOffset(years=2),
    "5y": pd.DateOffset(years=5),
}
BETA_MIN_OBSERVATIONS: dict[str, int] = {
    "1m": 10,
    "1y": 60,
    "2y": 120,
    "5y": 250,
}
BETA_WEEKLY_MIN_OBSERVATIONS = 26


def compute_fundamental_signals(snapshot: MarketSnapshot, risk_profile: str) -> dict[str, Any]:
    info = snapshot.info or {}
    normalized_risk_profile = risk_profile if risk_profile in BETA_BANDS_BY_RISK_PROFILE else "balanced"
    provider_beta = _extract_numeric(info, ("beta",))
    statement_metrics = _compute_statement_quality_metrics(snapshot)
    direct_roce = _normalize_fraction(
        _extract_numeric(info, ("returnOnCapitalEmployed", "returnOnCapital", "roce"))
    )
    direct_operating_margin = _normalize_fraction(_extract_numeric(info, ("operatingMargins", "operatingMargin")))
    direct_debt_to_equity = _normalize_debt_to_equity(_extract_numeric(info, ("debtToEquity",)))
    computed_beta = _compute_beta_suite(snapshot)
    scoring_beta = computed_beta.get("beta_1y")
    if scoring_beta is None:
        scoring_beta = provider_beta

    metrics = FundamentalMetrics(
        forward_pe=_extract_numeric(info, ("forwardPE",)),
        trailing_pe=_extract_numeric(info, ("trailingPE",)),
        return_on_equity=_normalize_fraction(_extract_numeric(info, ("returnOnEquity", "roe"))),
        return_on_capital_employed=_first_metric(
            statement_metrics.get("return_on_capital_employed"),
            direct_roce,
        ),
        profit_margin=_normalize_fraction(_extract_numeric(info, ("profitMargins", "netMargins"))),
        operating_margin=_first_metric(statement_metrics.get("operating_margin"), direct_operating_margin),
        debt_to_equity=_first_metric(statement_metrics.get("debt_to_equity"), direct_debt_to_equity),
        current_ratio=_first_metric(
            statement_metrics.get("current_ratio"),
            _extract_numeric(info, ("currentRatio", "quickRatio")),
        ),
        quarterly_revenue_growth=_first_metric(
            statement_metrics.get("quarterly_revenue_growth"),
            _normalize_fraction(_extract_numeric(info, ("quarterlyRevenueGrowth", "revenueGrowth"))),
        ),
        beta=scoring_beta,
        beta_1y=computed_beta.get("beta_1y"),
        beta_2y=computed_beta.get("beta_2y"),
        beta_5y=computed_beta.get("beta_5y"),
        beta_1m=computed_beta.get("beta_1m"),
        beta_weekly=computed_beta.get("beta_weekly"),
        beta_benchmark=computed_beta.get("benchmark"),
        short_ratio=_extract_numeric(info, ("shortRatio", "daysToCover")),
        short_percent_of_float=_normalize_short_percent(
            _extract_numeric(info, ("shortPercentOfFloat", "sharesPercentSharesOut"))
        ),
        free_cash_flow=_first_metric(
            statement_metrics.get("free_cash_flow"),
            _extract_numeric(info, ("freeCashflow", "freeCashFlow")),
        ),
        total_debt=_first_metric(statement_metrics.get("total_debt"), _extract_numeric(info, ("totalDebt",))),
    )
    metrics.debt_to_equity = _reasonable_metric(metrics.debt_to_equity, min_value=0.0, max_value=10.0)
    metrics.current_ratio = _reasonable_metric(metrics.current_ratio, min_value=0.0, max_value=20.0)
    metrics.quarterly_revenue_growth = _reasonable_metric(
        metrics.quarterly_revenue_growth,
        min_value=-1.0,
        max_value=5.0,
    )
    metrics.free_cash_flow = _reasonable_metric(metrics.free_cash_flow)
    metrics.total_debt = _reasonable_metric(metrics.total_debt, min_value=0.0)
    metric_sources = statement_metrics.get("sources") if isinstance(statement_metrics.get("sources"), dict) else {}
    metric_sources = dict(metric_sources)
    _mark_info_fallback(metric_sources, "debt_to_equity", statement_metrics.get("debt_to_equity"), metrics.debt_to_equity)
    _mark_info_fallback(metric_sources, "current_ratio", statement_metrics.get("current_ratio"), metrics.current_ratio)
    _mark_info_fallback(
        metric_sources,
        "quarterly_revenue_growth",
        statement_metrics.get("quarterly_revenue_growth"),
        metrics.quarterly_revenue_growth,
    )
    _mark_info_fallback(metric_sources, "free_cash_flow", statement_metrics.get("free_cash_flow"), metrics.free_cash_flow)
    _mark_info_fallback(metric_sources, "total_debt", statement_metrics.get("total_debt"), metrics.total_debt)

    signals = {
        "valuation_pe_trend": _score_pe_trend(metrics.forward_pe, metrics.trailing_pe),
        "return_on_equity": _score_from_bands(
            "return_on_equity",
            metrics.return_on_equity,
            ROE_BANDS,
            "ROE indicates how efficiently management converts equity into profits.",
        ),
        "return_on_capital_employed": _score_from_bands(
            "return_on_capital_employed",
            metrics.return_on_capital_employed,
            ROCE_BANDS,
            "ROCE measures operating profit generated from capital employed.",
        ),
        "profit_margin": _score_from_bands(
            "profit_margin",
            metrics.profit_margin,
            PROFIT_MARGIN_BANDS,
            "Profit margin reflects net earnings retained from revenue.",
        ),
        "operating_margin": _score_from_bands(
            "operating_margin",
            metrics.operating_margin,
            PROFIT_MARGIN_BANDS,
            "Operating margin reflects core operating profit retained from revenue.",
        ),
        "debt_to_equity": _score_from_bands(
            "debt_to_equity",
            metrics.debt_to_equity,
            DEBT_TO_EQUITY_BANDS,
            _source_note(
                "Debt-to-equity compares leverage against shareholder capital.",
                metric_sources.get("debt_to_equity"),
            ),
        ),
        "current_ratio": _score_from_bands(
            "current_ratio",
            metrics.current_ratio,
            CURRENT_RATIO_BANDS,
            _source_note(
                "Current ratio evaluates short-term liquidity coverage.",
                metric_sources.get("current_ratio"),
            ),
        ),
        "quarterly_revenue_growth": _score_from_bands(
            "quarterly_revenue_growth",
            metrics.quarterly_revenue_growth,
            REVENUE_GROWTH_BANDS,
            _source_note(
                "Revenue growth shows direction and pace of top-line momentum.",
                metric_sources.get("quarterly_revenue_growth"),
            ),
        ),
        "beta_profile_fit": _score_from_bands(
            "beta_profile_fit",
            metrics.beta,
            BETA_BANDS_BY_RISK_PROFILE[normalized_risk_profile],
            f"Beta (1Y daily, self-computed) evaluated for a {normalized_risk_profile} risk profile.",
        ),
        "short_ratio": _score_from_bands(
            "short_ratio",
            metrics.short_ratio,
            SHORT_RATIO_BANDS,
            "Short ratio estimates average days required to cover short positions.",
        ),
        "short_percent_of_float": _score_from_bands(
            "short_percent_of_float",
            metrics.short_percent_of_float,
            SHORT_PERCENT_FLOAT_BANDS,
            "Short interest as a percentage of float can indicate squeeze risk.",
        ),
        "fcf_vs_debt": _score_fcf_vs_debt(
            metrics.free_cash_flow,
            metrics.total_debt,
            source_note=metric_sources.get("free_cash_flow") or metric_sources.get("total_debt"),
        ),
    }

    return {
        "risk_profile": normalized_risk_profile,
        "fundamentals": metrics,
        "fundamental_signals": signals,
        "forward_pe": metrics.forward_pe,
        "trailing_pe": metrics.trailing_pe,
        "return_on_equity": metrics.return_on_equity,
        "return_on_capital_employed": metrics.return_on_capital_employed,
        "profit_margin": metrics.profit_margin,
        "operating_margin": metrics.operating_margin,
        "debt_to_equity": metrics.debt_to_equity,
        "current_ratio": metrics.current_ratio,
        "quarterly_revenue_growth": metrics.quarterly_revenue_growth,
        "beta": metrics.beta,
        "beta_1y": metrics.beta_1y,
        "beta_2y": metrics.beta_2y,
        "beta_5y": metrics.beta_5y,
        "beta_1m": metrics.beta_1m,
        "beta_weekly": metrics.beta_weekly,
        "beta_benchmark": metrics.beta_benchmark,
        "provider_beta": provider_beta,
        "short_ratio": metrics.short_ratio,
        "short_percent_of_float": metrics.short_percent_of_float,
        "free_cash_flow": metrics.free_cash_flow,
        "total_debt": metrics.total_debt,
        "fundamental_sources": metric_sources,
    }


def _score_pe_trend(forward_pe: float | None, trailing_pe: float | None) -> MetricSignal:
    if forward_pe is None or trailing_pe is None:
        return _missing_signal(
            "valuation_pe_trend",
            "Forward P/E or trailing P/E is unavailable, so valuation trend cannot be ranked.",
        )

    if forward_pe <= 0 or trailing_pe <= 0:
        return MetricSignal(
            key="valuation_pe_trend",
            value=forward_pe,
            label=SignalLabel.WARNING,
            score=0.3,
            available=True,
            note="Non-positive earnings multiples detected; valuation comparison is less reliable.",
        )

    relative_gap = forward_pe / trailing_pe
    if relative_gap <= 0.95:
        label = SignalLabel.BULLISH
        score = 0.9
        note = "Forward P/E is below trailing P/E, suggesting expectations of earnings improvement."
    elif relative_gap <= 1.05:
        label = SignalLabel.NEUTRAL
        score = 0.6
        note = "Forward and trailing P/E are close, implying stable earnings expectations."
    elif relative_gap <= 1.25:
        label = SignalLabel.WARNING
        score = 0.4
        note = "Forward P/E is moderately above trailing P/E, implying decelerating earnings expectations."
    else:
        label = SignalLabel.BEARISH
        score = 0.1
        note = "Forward P/E is materially above trailing P/E, signaling weaker forward earnings expectations."

    return MetricSignal(
        key="valuation_pe_trend",
        value=relative_gap,
        label=label,
        score=score,
        available=True,
        note=note,
    )


def _score_fcf_vs_debt(
    free_cash_flow: float | None,
    total_debt: float | None,
    *,
    source_note: Any = None,
) -> MetricSignal:
    if free_cash_flow is None or total_debt is None:
        return _missing_signal(
            "fcf_vs_debt",
            "Free cash flow or total debt is unavailable, so debt coverage quality cannot be ranked.",
        )

    if total_debt <= 0:
        if free_cash_flow > 0:
            return MetricSignal(
                key="fcf_vs_debt",
                value=free_cash_flow,
                label=SignalLabel.BULLISH,
                score=0.95,
                available=True,
                note="Positive free cash flow with no material debt reported.",
            )
        return MetricSignal(
            key="fcf_vs_debt",
            value=free_cash_flow,
            label=SignalLabel.WARNING,
            score=0.3,
            available=True,
            note="No material debt reported, but free cash flow is non-positive.",
        )

    ratio = free_cash_flow / total_debt
    scored = _score_from_bands(
        "fcf_vs_debt",
        ratio,
        FCF_TO_DEBT_BANDS,
        _source_note(
            "FCF-to-debt indicates how quickly cash generation can cover debt obligations.",
            source_note,
        ),
    )
    scored.value = ratio
    return scored


def _score_from_bands(
    key: str,
    value: float | None,
    bands: tuple[ThresholdBand, ...],
    note: str,
) -> MetricSignal:
    if value is None:
        return _missing_signal(key, f"{note} Metric is unavailable.")

    for band in bands:
        if band.matches(value):
            return MetricSignal(
                key=key,
                value=value,
                label=band.label,
                score=band.score,
                available=True,
                note=note,
            )

    return MetricSignal(
        key=key,
        value=value,
        label=SignalLabel.NEUTRAL,
        score=0.5,
        available=True,
        note=note,
    )


def _missing_signal(key: str, note: str) -> MetricSignal:
    return MetricSignal(
        key=key,
        value=None,
        label=SignalLabel.MISSING,
        score=0.0,
        available=False,
        note=note,
    )


def _extract_numeric(info: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        candidate = _to_float(info.get(key))
        if candidate is not None:
            return candidate
    return None


def _normalize_fraction(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 1.0 and value <= 100.0:
        return value / 100.0
    return value


def _normalize_debt_to_equity(value: float | None) -> float | None:
    if value is None:
        return None
    # yfinance commonly reports debtToEquity as percent-like points (48.04 == 0.4804x).
    if value > 10.0:
        return value / 100.0
    return value


def _normalize_short_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 1.0:
        return value * 100.0
    return value


def _first_metric(*values: Any) -> float | None:
    for value in values:
        numeric = _to_float(value)
        if numeric is not None:
            return numeric
    return None


def _source_note(base_note: str, source: Any) -> str:
    if isinstance(source, str) and source.strip():
        return f"{base_note} Source: {source.strip()}."
    return base_note


def _mark_info_fallback(
    sources: dict[str, str],
    key: str,
    statement_value: Any,
    selected_value: Any,
) -> None:
    if key in sources:
        return
    if _to_float(statement_value) is None and _to_float(selected_value) is not None:
        sources[key] = "Yahoo Finance info fallback"


def _reasonable_metric(
    value: float | None,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if min_value is not None and numeric < min_value:
        return None
    if max_value is not None and numeric > max_value:
        return None
    return numeric


def _compute_statement_quality_metrics(snapshot: MarketSnapshot) -> dict[str, Any]:
    sources: dict[str, str] = {}
    try:
        ticker = yf.Ticker(snapshot.ticker)
        income_statement = _first_statement_frame(
            getattr(ticker, "income_stmt", None),
            getattr(ticker, "financials", None),
        )
        quarterly_income_statement = _first_statement_frame(
            getattr(ticker, "quarterly_income_stmt", None),
            getattr(ticker, "quarterly_financials", None),
        )
        balance_sheet = _first_statement_frame(
            getattr(ticker, "balance_sheet", None),
            getattr(ticker, "balancesheet", None),
        )
        cashflow = _first_statement_frame(
            getattr(ticker, "quarterly_cashflow", None),
            getattr(ticker, "cashflow", None),
        )
    except Exception:
        return {
            "return_on_capital_employed": None,
            "operating_margin": None,
            "debt_to_equity": None,
            "current_ratio": None,
            "quarterly_revenue_growth": None,
            "free_cash_flow": None,
            "total_debt": None,
            "sources": sources,
        }

    operating_income = _statement_value(income_statement, ("Operating Income", "OperatingIncome"))
    total_revenue = _statement_value(income_statement, ("Total Revenue", "TotalRevenue"))
    ebit = _statement_value(income_statement, ("EBIT", "Ebit", "Operating Income", "OperatingIncome"))

    total_assets = _statement_value(balance_sheet, ("Total Assets", "TotalAssets"))
    current_assets = _statement_value(balance_sheet, ("Current Assets", "Total Current Assets"))
    current_liabilities = _statement_value(balance_sheet, ("Current Liabilities", "Total Current Liabilities"))
    total_debt = _statement_total_debt(balance_sheet)
    equity = _statement_value(
        balance_sheet,
        ("Stockholders Equity", "Stockholder Equity", "Total Equity Gross Minority Interest", "Total Stockholder Equity"),
    )

    capital_employed = None
    if total_assets is not None and current_liabilities is not None:
        capital_employed = total_assets - current_liabilities
    if (capital_employed is None or capital_employed <= 0) and total_debt is not None and equity is not None:
        capital_employed = total_debt + equity

    roce = _safe_ratio(ebit, capital_employed)
    if roce is not None:
        sources["return_on_capital_employed"] = "statement-derived"

    operating_margin = _safe_ratio(operating_income, total_revenue)
    if operating_margin is not None:
        sources["operating_margin"] = "statement-derived"

    debt_to_equity = _safe_ratio(total_debt, equity)
    if debt_to_equity is not None:
        sources["debt_to_equity"] = "statement-derived"

    current_ratio = _safe_ratio(current_assets, current_liabilities)
    if current_ratio is not None:
        sources["current_ratio"] = "statement-derived"

    quarterly_revenue_growth, quarterly_growth_source = _quarterly_revenue_growth(quarterly_income_statement)
    if quarterly_revenue_growth is not None and quarterly_growth_source is not None:
        sources["quarterly_revenue_growth"] = quarterly_growth_source

    free_cash_flow, fcf_source = _free_cash_flow(cashflow)
    if free_cash_flow is not None and fcf_source is not None:
        sources["free_cash_flow"] = fcf_source
    if total_debt is not None:
        sources["total_debt"] = "statement-derived"

    return {
        "return_on_capital_employed": roce,
        "operating_margin": operating_margin,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "quarterly_revenue_growth": quarterly_revenue_growth,
        "free_cash_flow": free_cash_flow,
        "total_debt": total_debt,
        "sources": sources,
    }


def _first_statement_frame(*candidates: Any) -> pd.DataFrame:
    for candidate in candidates:
        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
            return candidate
    return pd.DataFrame()


def _statement_value(frame: pd.DataFrame, row_names: tuple[str, ...]) -> float | None:
    if frame.empty:
        return None

    normalized_rows = {str(index).strip().lower(): index for index in frame.index}
    for row_name in row_names:
        row_index = normalized_rows.get(row_name.strip().lower())
        if row_index is None:
            continue
        row = frame.loc[row_index]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        for value in row:
            numeric = _to_float(value)
            if numeric is not None:
                return numeric
    return None


def _statement_values(frame: pd.DataFrame, row_names: tuple[str, ...], *, limit: int | None = None) -> list[float]:
    if frame.empty:
        return []

    normalized_rows = {str(index).strip().lower(): index for index in frame.index}
    for row_name in row_names:
        row_index = normalized_rows.get(row_name.strip().lower())
        if row_index is None:
            continue
        row = frame.loc[row_index]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        values: list[float] = []
        for value in row:
            numeric = _to_float(value)
            if numeric is not None:
                values.append(numeric)
                if limit is not None and len(values) >= limit:
                    return values
        return values
    return []


def _statement_total_debt(balance_sheet: pd.DataFrame) -> float | None:
    direct = _statement_value(balance_sheet, ("Total Debt", "TotalDebt"))
    if direct is not None:
        return direct

    long_term_debt = _statement_value(balance_sheet, ("Long Term Debt", "LongTermDebt"))
    current_debt = _statement_value(
        balance_sheet,
        ("Current Debt", "CurrentDebt", "Short Long Term Debt", "ShortLongTermDebt"),
    )
    if long_term_debt is None and current_debt is None:
        return None
    return (long_term_debt or 0.0) + (current_debt or 0.0)


def _quarterly_revenue_growth(quarterly_income_statement: pd.DataFrame) -> tuple[float | None, str | None]:
    revenues = _statement_values(
        quarterly_income_statement,
        ("Total Revenue", "TotalRevenue"),
        limit=5,
    )
    if len(revenues) >= 5 and revenues[4] > 0:
        return (revenues[0] / revenues[4]) - 1.0, "quarterly statement YoY"
    if len(revenues) >= 2 and revenues[1] > 0:
        return (revenues[0] / revenues[1]) - 1.0, "quarterly statement sequential fallback"
    return None, None


def _free_cash_flow(cashflow: pd.DataFrame) -> tuple[float | None, str | None]:
    operating_cash_flow_values = _statement_values(
        cashflow,
        ("Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"),
        limit=4,
    )
    capex_values = _statement_values(
        cashflow,
        ("Capital Expenditure", "CapitalExpenditure", "Capital Expenditures"),
        limit=4,
    )
    if not operating_cash_flow_values or not capex_values:
        return None, None

    count = min(len(operating_cash_flow_values), len(capex_values), 4)
    if count <= 0:
        return None, None
    fcf_values = [
        _fcf_from_operating_cash_flow_and_capex(operating_cash_flow_values[index], capex_values[index])
        for index in range(count)
    ]
    if count >= 4:
        return sum(fcf_values), "quarterly cash-flow TTM"
    return fcf_values[0], "cash-flow statement latest period"


def _fcf_from_operating_cash_flow_and_capex(operating_cash_flow: float, capex: float) -> float:
    if capex < 0:
        return operating_cash_flow + capex
    return operating_cash_flow - capex


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    ratio = numerator / denominator
    if not isfinite(ratio):
        return None
    return float(ratio)


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        numeric = float(value)
        if isfinite(numeric):
            return numeric
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        cleaned = text.replace(",", "").replace("%", "")
        try:
            numeric = float(cleaned)
        except ValueError:
            return None
        if isfinite(numeric):
            return numeric
        return None

    return None


def _compute_beta_suite(snapshot: MarketSnapshot) -> dict[str, float | str | None]:
    benchmark = _resolve_benchmark_ticker(snapshot)
    paired_close = _download_pair_close_history(snapshot.ticker, benchmark)
    if paired_close.empty:
        return {
            "benchmark": benchmark,
            "beta_1m": None,
            "beta_1y": None,
            "beta_2y": None,
            "beta_5y": None,
            "beta_weekly": None,
        }

    daily_returns = paired_close.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    betas: dict[str, float | str | None] = {
        "benchmark": benchmark,
    }

    if daily_returns.empty:
        betas.update(
            {
                "beta_1m": None,
                "beta_1y": None,
                "beta_2y": None,
                "beta_5y": None,
                "beta_weekly": None,
            }
        )
        return betas

    last_date = daily_returns.index.max()
    for window_key, offset in BETA_LOOKBACK_OFFSETS.items():
        cutoff = last_date - offset
        window = daily_returns[daily_returns.index >= cutoff]
        min_obs = BETA_MIN_OBSERVATIONS.get(window_key, 20)
        betas[f"beta_{window_key}"] = _beta_from_returns(window, min_obs=min_obs)

    weekly_prices = paired_close.resample("W-FRI").last().dropna()
    weekly_returns = weekly_prices.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    if weekly_returns.empty:
        betas["beta_weekly"] = None
    else:
        weekly_last = weekly_returns.index.max()
        weekly_cutoff = weekly_last - pd.DateOffset(years=1)
        weekly_window = weekly_returns[weekly_returns.index >= weekly_cutoff]
        betas["beta_weekly"] = _beta_from_returns(weekly_window, min_obs=BETA_WEEKLY_MIN_OBSERVATIONS)

    return betas


def _resolve_benchmark_ticker(snapshot: MarketSnapshot) -> str:
    ticker = (snapshot.ticker or "").strip().upper()
    if ticker.endswith(".NS"):
        return "^NSEI"
    if ticker.endswith(".BO"):
        return "^BSESN"

    exchange = ""
    if snapshot.company_metadata:
        exchange = str(snapshot.company_metadata.get("exchange") or "").upper()
    if not exchange and snapshot.info:
        exchange = str(snapshot.info.get("exchange") or "").upper()

    if exchange.startswith("NSE"):
        return "^NSEI"
    if exchange.startswith("BSE"):
        return "^BSESN"
    return "^GSPC"


def _download_pair_close_history(stock_ticker: str, benchmark_ticker: str) -> pd.DataFrame:
    tickers = f"{stock_ticker} {benchmark_ticker}"
    try:
        raw = yf.download(
            tickers=tickers,
            period="5y",
            interval="1d",
            auto_adjust=True,
            actions=False,
            progress=False,
            group_by="column",
            threads=False,
        )
    except Exception:
        return pd.DataFrame(columns=["stock", "benchmark"])

    stock_close = _extract_close_series(raw, stock_ticker)
    benchmark_close = _extract_close_series(raw, benchmark_ticker)

    if stock_close.empty or benchmark_close.empty:
        return pd.DataFrame(columns=["stock", "benchmark"])

    frame = pd.concat(
        [
            stock_close.rename("stock"),
            benchmark_close.rename("benchmark"),
        ],
        axis=1,
    ).dropna()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return frame


def _extract_close_series(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype="float64")

    frame = raw.copy()
    normalized_ticker = (ticker or "").strip().upper()
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = [str(item).upper() for item in frame.columns.get_level_values(0)]
        level1 = [str(item).upper() for item in frame.columns.get_level_values(1)]
        if normalized_ticker in level1:
            frame = frame.xs(normalized_ticker, axis=1, level=1, drop_level=True)
        elif normalized_ticker in level0:
            frame = frame.xs(normalized_ticker, axis=1, level=0, drop_level=True)
        else:
            return pd.Series(dtype="float64")

    if "Close" in frame.columns:
        series = pd.to_numeric(frame["Close"], errors="coerce")
    elif "Adj Close" in frame.columns:
        series = pd.to_numeric(frame["Adj Close"], errors="coerce")
    else:
        return pd.Series(dtype="float64")

    if not isinstance(series.index, pd.DatetimeIndex):
        try:
            series.index = pd.to_datetime(series.index, errors="coerce")
        except Exception:
            return pd.Series(dtype="float64")
    series = series[~series.index.isna()]
    if series.index.tz is not None:
        series.index = series.index.tz_convert(None)
    return series.dropna().sort_index()


def _beta_from_returns(window: pd.DataFrame, min_obs: int) -> float | None:
    if window.empty:
        return None
    required = window[["stock", "benchmark"]].dropna()
    if len(required) < min_obs:
        return None

    benchmark_var = float(required["benchmark"].var())
    if not isfinite(benchmark_var) or benchmark_var <= 0:
        return None

    covariance = float(required["stock"].cov(required["benchmark"]))
    if not isfinite(covariance):
        return None

    beta = covariance / benchmark_var
    if not isfinite(beta):
        return None
    return float(beta)
