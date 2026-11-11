from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import re
from typing import Any

from equity_reporter.ai.analysis_generator import generate_comprehensive_analysis
from equity_reporter.analysis.fibonacci import compute_fibonacci_signals
from equity_reporter.analysis.fno_data import compute_fno_signals
from equity_reporter.analysis.fundamentals import compute_fundamental_signals
from equity_reporter.analysis.peers import (
    PEER_DATA_FALLBACK_TEXT,
    build_peer_signals,
    build_peer_valuation_text,
    calculate_relative_valuation,
    get_auto_peers,
    get_peer_group_averages,
)
from equity_reporter.analysis.projections import build_projections
from equity_reporter.analysis.scoring import compute_scorecard
from equity_reporter.analysis.technical import compute_technical_signals
from equity_reporter.analysis.volume import compute_volume_signals
from equity_reporter.data.fetcher import fetch_chart_context_history, fetch_market_snapshot
from equity_reporter.data.resolver import resolve_ticker_input
from equity_reporter.data.validator import validate_market_snapshot
from equity_reporter.reporting.charts import cleanup_temp_chart, render_chart
from equity_reporter.reporting.pdf_builder import render_pdf
from equity_reporter.models import MarketSnapshot
from equity_reporter.utils.errors import DataUnavailableError, ReportError
from equity_reporter.utils.logging_utils import get_logger


@dataclass(slots=True)
class RunConfig:
    ticker: str
    risk_profile: str
    output_dir: Path
    output_name: str | None = None
    overwrite: bool = False


def run_report(config: RunConfig) -> Path:
    logger = get_logger(__name__)
    requested = config.ticker.strip()
    if not requested:
        raise ReportError("Ticker or company name cannot be empty.")

    logger.info("Starting report pipeline for %s", requested)

    snapshot = _fetch_snapshot_with_name_fallback(requested, logger)
    validate_market_snapshot(snapshot)

    signals: dict[str, object] = {}
    signals.update(compute_fundamental_signals(snapshot, config.risk_profile))
    signals.update(_build_peer_context(snapshot, signals))
    signals.update(compute_technical_signals(snapshot))
    signals.update(compute_volume_signals(snapshot))
    signals.update(_merge_fno_context(signals, compute_fno_signals(snapshot)))
    signals.update(compute_fibonacci_signals(snapshot))

    projections = build_projections(snapshot, signals)
    scorecard = compute_scorecard(signals)
    ai_analysis = generate_comprehensive_analysis(snapshot, signals, projections, scorecard)
    output_path = _resolve_output_path(config, snapshot.ticker)
    chart_context_history = fetch_chart_context_history(snapshot.ticker)

    chart_path: Path | None = None
    try:
        chart_path = render_chart(
            snapshot,
            signals,
            output_path.parent,
            chart_history=chart_context_history,
            projections=projections,
        )
        pdf_path = render_pdf(
            snapshot,
            signals,
            scorecard,
            projections,
            chart_path,
            output_path,
            ai_analysis_text=ai_analysis.text,
            ai_analysis_status=ai_analysis.status_label,
            ai_analysis_note=ai_analysis.status_note,
        )
    finally:
        cleanup_temp_chart(chart_path)

    logger.info("Report pipeline finished: %s", pdf_path)
    return pdf_path


def _build_peer_context(snapshot: MarketSnapshot, signals: dict[str, Any]) -> dict[str, Any]:
    target_metrics = {
        "forwardPE": _to_float(signals.get("forward_pe")),
        "priceToSalesTrailing12Months": _to_float((snapshot.info or {}).get("priceToSalesTrailing12Months")),
        "profitMargins": _to_float(signals.get("profit_margin")),
        "revenueGrowth": _to_float(signals.get("quarterly_revenue_growth")),
    }

    peer_list = get_auto_peers(
        snapshot.ticker,
        target_metadata=snapshot.company_metadata,
        target_info=snapshot.info,
    )
    peer_averages = get_peer_group_averages(peer_list) if peer_list else _empty_peer_averages()
    peer_relative = calculate_relative_valuation(target_metrics, peer_averages)
    peer_text = build_peer_valuation_text(peer_list, target_metrics, peer_averages, peer_relative)
    peer_signals = build_peer_signals(peer_relative)

    peer_context = {
        "peer_list": peer_list,
        "target_metrics": target_metrics,
        "peer_group_averages": peer_averages,
        "relative_valuation": peer_relative,
        "text_block": peer_text,
    }

    return {
        "peer_sector_data": peer_context,
        "peer_sector_text": peer_text,
        "peer_signals": peer_signals,
        "peer_list": peer_list,
        "peer_target_forward_pe": peer_relative.get("target_forward_pe"),
        "peer_avg_forward_pe": peer_relative.get("peer_avg_forward_pe"),
        "peer_pe_to_sector_pe_ratio": peer_relative.get("pe_to_sector_pe_ratio"),
        "peer_forward_pe_premium_pct": peer_relative.get("forward_pe_premium_pct"),
        "peer_target_ps": peer_relative.get("target_ps"),
        "peer_avg_ps": peer_relative.get("peer_avg_ps"),
        "peer_ps_premium_pct": peer_relative.get("ps_premium_pct"),
        "peer_target_margin": peer_relative.get("target_margin"),
        "peer_avg_margin": peer_relative.get("peer_avg_margin"),
        "peer_margin_spread_pct": peer_relative.get("margin_spread_pct"),
        "peer_target_growth": peer_relative.get("target_growth"),
        "peer_avg_growth": peer_relative.get("peer_avg_growth"),
        "peer_growth_spread_pct": peer_relative.get("growth_spread_pct"),
        "peer_data_available": peer_text != PEER_DATA_FALLBACK_TEXT,
    }


def _empty_peer_averages() -> dict[str, float | None]:
    return {
        "forwardPE": None,
        "priceToSalesTrailing12Months": None,
        "profitMargins": None,
        "revenueGrowth": None,
    }


def _merge_fno_context(signals: dict[str, object], fno_context: dict[str, Any]) -> dict[str, Any]:
    fno_signals = fno_context.pop("fno_signals", {})
    volume_signals = signals.get("volume_signals")
    if isinstance(volume_signals, dict):
        merged_volume_signals = dict(volume_signals)
        if isinstance(fno_signals, dict):
            merged_volume_signals.update(fno_signals)
    else:
        merged_volume_signals = fno_signals if isinstance(fno_signals, dict) else {}

    return {
        **fno_context,
        "volume_signals": merged_volume_signals,
        "fno_signals": fno_signals,
    }


def _fetch_snapshot_with_name_fallback(requested: str, logger) -> MarketSnapshot:
    if _looks_like_company_name(requested):
        resolved_ticker = resolve_ticker_input(requested)
        logger.info("Resolved '%s' to ticker '%s'", requested, resolved_ticker)
        return fetch_market_snapshot(resolved_ticker)

    try:
        return fetch_market_snapshot(requested)
    except DataUnavailableError as first_error:
        resolved_ticker: str | None = None
        try:
            resolved_ticker = resolve_ticker_input(requested)
        except DataUnavailableError:
            raise first_error

        normalized_requested = requested.strip().upper()
        if not resolved_ticker or resolved_ticker.upper() == normalized_requested:
            raise first_error

        logger.info("Resolved '%s' to ticker '%s'", requested, resolved_ticker)
        return fetch_market_snapshot(resolved_ticker)


def _looks_like_company_name(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return False
    if " " in cleaned:
        return True
    return False


def _resolve_output_path(config: RunConfig, resolved_ticker: str) -> Path:
    output_dir = config.output_dir.expanduser().resolve()
    if output_dir.exists() and not output_dir.is_dir():
        raise ReportError(f"Output path is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = _normalize_output_name(resolved_ticker, config.output_name)
    candidate = output_dir / base_name
    if config.overwrite or not candidate.exists():
        return candidate
    return _next_available_path(candidate)


def _normalize_output_name(ticker: str, output_name: str | None) -> str:
    if output_name is not None and output_name.strip():
        name = output_name.strip()
        if not name.lower().endswith(".pdf"):
            name = f"{name}.pdf"
        return _safe_filename(name)

    safe_ticker = re.sub(r"[^A-Za-z0-9._-]+", "_", ticker).strip("._-")
    if not safe_ticker:
        safe_ticker = "TICKER"
    return f"{safe_ticker}_Equity_Research_Report.pdf"


def _safe_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\\\|?*]+', "_", name)
    safe = safe.replace("\n", "_").replace("\r", "_").strip()
    if not safe:
        return "Equity_Research_Report.pdf"
    return safe


def _next_available_path(path: Path) -> Path:
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2

    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if not isfinite(numeric):
            return None
        return numeric
    except (TypeError, ValueError):
        return None
