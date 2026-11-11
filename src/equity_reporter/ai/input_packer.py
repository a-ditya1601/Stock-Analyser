from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

import pandas as pd

from equity_reporter.models import MarketSnapshot, MetricSignal, ProjectionScenarios, ScoreCard

DATA_UNAVAILABLE = "Data Unavailable"


def build_ai_input_payload(
    snapshot: MarketSnapshot,
    signals: dict[str, Any],
    projections: ProjectionScenarios,
    scorecard: ScoreCard,
) -> dict[str, Any]:
    fundamental_signals = _as_signal_map(signals.get("fundamental_signals"))
    technical_signals = _as_signal_map(signals.get("technical_signals"))
    volume_signals = _as_signal_map(signals.get("volume_signals"))
    fibonacci_signal = signals.get("fibonacci_signal")
    fib_signal = fibonacci_signal if isinstance(fibonacci_signal, MetricSignal) else None
    peer_signals = _as_signal_map(signals.get("peer_signals"))

    history_start, history_end, history_rows = _history_window(snapshot.history)

    payload = {
        "meta": {
            "ticker": _normalize_value(snapshot.ticker),
            "company_name": _normalize_value((snapshot.company_metadata or {}).get("company_name")),
            "exchange": _normalize_value((snapshot.company_metadata or {}).get("exchange")),
            "currency": _normalize_value(_resolve_currency(snapshot)),
            "current_price": _normalize_value(snapshot.current_price),
            "report_date": _normalize_value(snapshot.fetched_at),
            "risk_profile": _normalize_value(signals.get("risk_profile")),
            "history_start_date": _normalize_value(history_start),
            "history_end_date": _normalize_value(history_end),
            "history_rows": _normalize_value(history_rows),
            "history_source": _normalize_value(getattr(snapshot, "history_source", None)),
            "history_note": _normalize_value(getattr(snapshot, "history_note", None)),
        },
        "fundamentals": {
            "sources": _normalize_dict(signals.get("fundamental_sources") or {}),
            "forward_pe": _metric_payload(
                value=signals.get("forward_pe"),
                metric_signal=fundamental_signals.get("valuation_pe_trend"),
            ),
            "trailing_pe": _metric_payload(
                value=signals.get("trailing_pe"),
                metric_signal=fundamental_signals.get("valuation_pe_trend"),
            ),
            "return_on_equity": _metric_payload(
                value=signals.get("return_on_equity"),
                metric_signal=fundamental_signals.get("return_on_equity"),
            ),
            "return_on_capital_employed": _metric_payload(
                value=signals.get("return_on_capital_employed"),
                metric_signal=fundamental_signals.get("return_on_capital_employed"),
            ),
            "profit_margin": _metric_payload(
                value=signals.get("profit_margin"),
                metric_signal=fundamental_signals.get("profit_margin"),
            ),
            "operating_margin": _metric_payload(
                value=signals.get("operating_margin"),
                metric_signal=fundamental_signals.get("operating_margin"),
            ),
            "debt_to_equity": _metric_payload(
                value=signals.get("debt_to_equity"),
                metric_signal=fundamental_signals.get("debt_to_equity"),
            ),
            "current_ratio": _metric_payload(
                value=signals.get("current_ratio"),
                metric_signal=fundamental_signals.get("current_ratio"),
            ),
            "quarterly_revenue_growth": _metric_payload(
                value=signals.get("quarterly_revenue_growth"),
                metric_signal=fundamental_signals.get("quarterly_revenue_growth"),
            ),
            "free_cash_flow": _metric_payload(
                value=signals.get("free_cash_flow"),
                metric_signal=fundamental_signals.get("fcf_vs_debt"),
            ),
            "total_debt": _metric_payload(
                value=signals.get("total_debt"),
                metric_signal=fundamental_signals.get("fcf_vs_debt"),
            ),
            "provider_beta": _normalize_value(signals.get("provider_beta")),
            "beta_1y_daily": _metric_payload(
                value=signals.get("beta"),
                metric_signal=fundamental_signals.get("beta_profile_fit"),
            ),
            "beta_2y_daily": _normalize_value(signals.get("beta_2y")),
            "beta_5y_daily": _normalize_value(signals.get("beta_5y")),
            "beta_1m_daily": _normalize_value(signals.get("beta_1m")),
            "beta_weekly": _normalize_value(signals.get("beta_weekly")),
            "beta_benchmark": _normalize_value(signals.get("beta_benchmark")),
            "short_ratio": _metric_payload(
                value=signals.get("short_ratio"),
                metric_signal=fundamental_signals.get("short_ratio"),
            ),
            "short_percent_of_float": _metric_payload(
                value=signals.get("short_percent_of_float"),
                metric_signal=fundamental_signals.get("short_percent_of_float"),
            ),
        },
        "technical": {
            "latest_close": _normalize_value(signals.get("latest_close")),
            "sma_20": _normalize_value(signals.get("sma_20")),
            "sma_50": _normalize_value(signals.get("sma_50")),
            "sma_200": _normalize_value(signals.get("sma_200")),
            "sma_signal": _normalize_signal(technical_signals.get("sma_crossover")),
            "rsi_14": _metric_payload(
                value=signals.get("rsi_14"),
                metric_signal=technical_signals.get("rsi_14"),
            ),
            "macd": _normalize_value(signals.get("macd")),
            "macd_signal_line": _normalize_value(signals.get("macd_signal")),
            "macd_crossover_signal": _normalize_signal(technical_signals.get("macd_crossover")),
            "bollinger_lower": _normalize_value(signals.get("bb_lower")),
            "bollinger_middle": _normalize_value(signals.get("bb_middle")),
            "bollinger_upper": _normalize_value(signals.get("bb_upper")),
            "bollinger_signal": _normalize_signal(technical_signals.get("bollinger_position")),
            "adx_14": _metric_payload(
                value=signals.get("adx_14"),
                metric_signal=technical_signals.get("adx_trend_strength"),
            ),
            "ichimoku_span_a": _normalize_value(signals.get("ichimoku_span_a")),
            "ichimoku_span_b": _normalize_value(signals.get("ichimoku_span_b")),
            "ichimoku_signal": _normalize_signal(technical_signals.get("ichimoku_cloud")),
        },
        "volume_flow": {
            "latest_volume": _normalize_value(signals.get("latest_volume")),
            "on_balance_volume": _normalize_value(signals.get("obv")),
            "obv_30d_trend": _metric_payload(
                value=signals.get("obv_30d_slope"),
                metric_signal=volume_signals.get("obv_30d_trend"),
            ),
            "avg_volume_10d": _normalize_value(signals.get("avg_volume_10d")),
            "avg_volume_3m": _normalize_value(signals.get("avg_volume_3m")),
            "relative_volume_10d_3m": _metric_payload(
                value=signals.get("relative_volume_10d_3m"),
                metric_signal=volume_signals.get("relative_volume_10d_3m"),
            ),
        },
        "derivatives_smart_money": {
            "pcr": _metric_payload(
                value=signals.get("fno_pcr"),
                metric_signal=volume_signals.get("pcr_sentiment"),
            ),
            "futures_oi_buildup": _metric_payload(
                value=signals.get("fno_futures_oi_buildup"),
                metric_signal=volume_signals.get("futures_oi_buildup"),
            ),
            "rollover_pct": _metric_payload(
                value=signals.get("fno_rollover_pct"),
                metric_signal=volume_signals.get("rollover_percentage"),
            ),
            "iv_percentile": _metric_payload(
                value=signals.get("fno_iv_percentile"),
                metric_signal=volume_signals.get("iv_percentile"),
            ),
            "atm_iv": _normalize_value(signals.get("fno_atm_iv")),
            "max_pain": _normalize_value(signals.get("fno_max_pain")),
            "expiry": _normalize_value(signals.get("fno_expiry")),
            "availability_status": _normalize_value(signals.get("fno_availability_status")),
            "availability_note": _normalize_value(signals.get("fno_note")),
            "text_block": _normalize_value(signals.get("fno_text_block")),
        },
        "fibonacci": {
            "high_6m": _normalize_value(signals.get("high_6m")),
            "low_6m": _normalize_value(signals.get("low_6m")),
            "level_0_382": _normalize_value(signals.get("fib_0_382")),
            "level_0_500": _normalize_value(signals.get("fib_0_500")),
            "level_0_618": _normalize_value(signals.get("fib_0_618")),
            "support_breakout_signal": _normalize_signal(fib_signal),
        },
        "peer_relativity": {
            "peer_list": _normalize_value(signals.get("peer_list")),
            "target_forward_pe": _normalize_value(signals.get("peer_target_forward_pe")),
            "peer_avg_forward_pe": _normalize_value(signals.get("peer_avg_forward_pe")),
            "pe_to_sector_pe_ratio": _metric_payload(
                value=signals.get("peer_pe_to_sector_pe_ratio"),
                metric_signal=peer_signals.get("peer_pe_to_sector_pe_ratio"),
            ),
            "forward_pe_premium_pct": _metric_payload(
                value=signals.get("peer_forward_pe_premium_pct"),
                metric_signal=peer_signals.get("peer_forward_pe_premium"),
            ),
            "target_price_to_sales": _normalize_value(signals.get("peer_target_ps")),
            "peer_avg_price_to_sales": _normalize_value(signals.get("peer_avg_ps")),
            "price_to_sales_premium_pct": _metric_payload(
                value=signals.get("peer_ps_premium_pct"),
                metric_signal=peer_signals.get("peer_ps_premium"),
            ),
            "target_profit_margin": _normalize_value(signals.get("peer_target_margin")),
            "peer_avg_profit_margin": _normalize_value(signals.get("peer_avg_margin")),
            "profit_margin_spread_pct": _metric_payload(
                value=signals.get("peer_margin_spread_pct"),
                metric_signal=peer_signals.get("peer_margin_spread"),
            ),
            "target_revenue_growth": _normalize_value(signals.get("peer_target_growth")),
            "peer_avg_revenue_growth": _normalize_value(signals.get("peer_avg_growth")),
            "revenue_growth_spread_pct": _metric_payload(
                value=signals.get("peer_growth_spread_pct"),
                metric_signal=peer_signals.get("peer_growth_spread"),
            ),
            "peer_text_block": _normalize_value(signals.get("peer_sector_text")),
        },
        "projections": {
            "atr_14": _normalize_value(projections.atr_14),
            "estimated_monthly_swing": _normalize_value(projections.monthly_swing),
            "methodology": _normalize_value(projections.methodology),
            "projection_confidence": _normalize_value(projections.projection_confidence),
            "support_levels": _normalize_value(projections.support_levels),
            "resistance_levels": _normalize_value(projections.resistance_levels),
            "volume_profile_poc": _normalize_value(projections.volume_profile_poc),
            "volume_profile_hvns": _normalize_value(projections.volume_profile_hvns),
            "scenario_probabilities": _normalize_dict(projections.scenario_probabilities),
            "fallback_reason": _normalize_value(projections.fallback_reason),
            "horizons": _normalize_horizons(projections),
            "analyst_mean_target": _normalize_value(projections.analyst_target_mean),
            "analyst_low_target": _normalize_value(projections.analyst_target_low),
            "analyst_high_target": _normalize_value(projections.analyst_target_high),
            "analyst_opinions": _normalize_value(projections.analyst_opinions),
            "analyst_blend_applied": _normalize_value(projections.analyst_blend_applied),
            "analyst_blend_weights": _normalize_dict(projections.blend_weights),
        },
        "scoring": {
            "data_coverage_pct": _normalize_value(scorecard.data_coverage_pct),
            "category_scores_pct": _normalize_dict(scorecard.category_scores),
            "category_weights": _normalize_dict(scorecard.category_weights),
            "metric_breakdown": _normalize_metric_breakdown(scorecard.metric_signals),
        },
    }
    return _normalize_dict(payload)


def _metric_payload(value: Any, metric_signal: MetricSignal | None) -> dict[str, Any]:
    return {
        "value": _normalize_value(value),
        "signal": _normalize_signal(metric_signal),
    }


def _normalize_signal(signal: MetricSignal | None) -> dict[str, Any] | str:
    if signal is None:
        return DATA_UNAVAILABLE
    return {
        "key": _normalize_value(signal.key),
        "label": _normalize_value(getattr(signal.label, "value", None)),
        "score": _normalize_value(signal.score),
        "available": _normalize_value(signal.available),
        "value": _normalize_value(signal.value),
        "note": _normalize_value(signal.note),
    }


def _normalize_metric_breakdown(metric_signals: dict[str, MetricSignal]) -> list[dict[str, Any]] | str:
    if not metric_signals:
        return DATA_UNAVAILABLE

    rows: list[dict[str, Any]] = []
    for metric_key in sorted(metric_signals):
        metric = metric_signals[metric_key]
        rows.append(
            {
                "metric": _normalize_value(metric_key),
                "label": _normalize_value(getattr(metric.label, "value", None)),
                "score": _normalize_value(metric.score),
                "weight_points": _normalize_value(metric.weight),
                "contribution_points": _normalize_value(metric.weight * metric.score),
                "available": _normalize_value(metric.available),
                "value": _normalize_value(metric.value),
                "note": _normalize_value(metric.note),
            }
        )
    return rows or DATA_UNAVAILABLE


def _normalize_horizons(projections: ProjectionScenarios) -> dict[str, Any] | str:
    if not projections.horizons:
        return DATA_UNAVAILABLE

    output: dict[str, Any] = {}
    for horizon, values in projections.horizons.items():
        output[horizon] = {
            "bear_case": _normalize_value(values.bear),
            "base_case": _normalize_value(values.base),
            "bull_case": _normalize_value(values.bull),
        }
    return output or DATA_UNAVAILABLE


def _normalize_dict(value: dict[str, Any]) -> dict[str, Any] | str:
    if not value:
        return DATA_UNAVAILABLE
    return {str(key): _normalize_value(item) for key, item in value.items()}


def _normalize_value(value: Any) -> Any:
    if value is None:
        return DATA_UNAVAILABLE

    if isinstance(value, bool):
        return value

    if isinstance(value, MetricSignal):
        return _normalize_signal(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, (int, float)):
        if isinstance(value, float):
            if not isfinite(value) or pd.isna(value):
                return DATA_UNAVAILABLE
        return value

    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else DATA_UNAVAILABLE

    if isinstance(value, dict):
        if not value:
            return DATA_UNAVAILABLE
        return {str(key): _normalize_value(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        if not value:
            return DATA_UNAVAILABLE
        return [_normalize_value(item) for item in value]

    if pd.isna(value):  # type: ignore[arg-type]
        return DATA_UNAVAILABLE

    return str(value)


def _as_signal_map(value: Any) -> dict[str, MetricSignal]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, MetricSignal] = {}
    for key, item in value.items():
        if isinstance(item, MetricSignal):
            output[str(key)] = item
    return output


def _history_window(history: pd.DataFrame | None) -> tuple[str | None, str | None, int | None]:
    if history is None or history.empty:
        return None, None, None

    try:
        index = history.index
        if len(index) == 0:
            return None, None, 0
        start = index.min()
        end = index.max()
        start_iso = _to_iso_date(start)
        end_iso = _to_iso_date(end)
        return start_iso, end_iso, int(len(history))
    except Exception:
        return None, None, int(len(history))


def _to_iso_date(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, pd.Timestamp):
        if value.tz is not None:
            return value.tz_convert(None).strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d")

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    try:
        parsed = pd.to_datetime(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        if parsed.tz is not None:
            return parsed.tz_convert(None).strftime("%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    return str(parsed)


def _resolve_currency(snapshot: MarketSnapshot) -> str | None:
    candidates = (
        (snapshot.company_metadata or {}).get("currency"),
        (snapshot.info or {}).get("currency"),
        (snapshot.fast_info or {}).get("currency"),
    )
    for candidate in candidates:
        if isinstance(candidate, str):
            cleaned = candidate.strip().upper()
            if cleaned:
                return cleaned
    return None
