from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any

import yfinance as yf

from equity_reporter.ai.nvidia_service import NvidiaService
from equity_reporter.analysis.company_universe import find_deterministic_peers
from equity_reporter.api.settings import (
    get_nvidia_peer_model,
    get_nvidia_peer_timeout_seconds,
)
from equity_reporter.config import (
    PEER_FORWARD_PE_PREMIUM_BANDS,
    PEER_GROWTH_SPREAD_BANDS,
    PEER_MARGIN_SPREAD_BANDS,
    PEER_PE_TO_SECTOR_PE_RATIO_BANDS,
    PEER_PS_PREMIUM_BANDS,
)
from equity_reporter.models import MetricSignal, SignalLabel, ThresholdBand
from equity_reporter.utils.errors import NvidiaServiceError

DATA_UNAVAILABLE = "Data Unavailable"
PEER_DATA_FALLBACK_TEXT = "Sector peer data unavailable for comparison. Analysis isolated to absolute metrics."

_MAX_VERIFIED_PEERS = 6
_CACHE_TTL = timedelta(days=30)
_CACHE_FILE_PATH = Path(__file__).resolve().parents[3] / ".cache" / "peer_baskets.json"
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-^=]{1,24}$")
_BUILT_IN_PEER_OVERRIDES: dict[str, list[str]] = {
    "DATAPATTNS.NS": ["BEL.NS", "HAL.NS", "BDL.NS", "ASTRAMICRO.NS", "MTARTECH.NS"],
    "KEI.NS": ["POLYCAB.NS", "HAVELLS.NS", "FINCABLES.NS", "RRKABEL.NS", "STLTECH.NS"],
    "RELIANCE.NS": ["IOC.NS", "BPCL.NS", "MRPL.NS", "OIL.NS"],
    "AAPL": ["MSFT", "GOOGL", "AMZN", "META", "HPQ"],
    "NVDA": ["AMD", "INTC", "MU"],
    "SPY": ["IVV", "VOO", "VTI", "QQQ", "DIA", "RSP"],
}

_PEER_DISCOVERY_SYSTEM_PROMPT = (
    "You are a financial data assistant. Your only job is to identify the top 4 to 6 publicly traded direct "
    "competitors for the provided stock ticker. "
    "IF the ticker ends in '.NS' or '.BO', you MUST return Indian competitors with their correct Yahoo Finance "
    "ticker symbols using '.NS' or '.BO'. "
    "Return ONLY a Python-parsable list of strings representing the ticker symbols. "
    "Do not include markdown formatting, backticks, or conversational text. "
    "Example output: ['HAL.NS', 'BEL.NS', 'BDL.NS']"
)


def get_auto_peers(
    target_ticker: str,
    target_metadata: dict[str, Any] | None = None,
    target_info: dict[str, Any] | None = None,
) -> list[str]:
    normalized_target = _normalize_symbol(target_ticker)
    if normalized_target is None:
        return []

    override_peers = _load_builtin_peer_override(normalized_target)
    if override_peers:
        _persist_peer_basket(normalized_target, override_peers)
        return override_peers

    cached_peers = _load_cached_peer_basket(normalized_target)
    if cached_peers:
        return cached_peers

    deterministic_peers = find_deterministic_peers(
        normalized_target,
        target_metadata=target_metadata,
        target_info=target_info,
    )
    if deterministic_peers:
        _persist_peer_basket(normalized_target, deterministic_peers)
        return deterministic_peers

    return []


def get_nvidia_peers(target_ticker: str) -> list[str]:
    normalized_target = _normalize_symbol(target_ticker)
    if normalized_target is None:
        return []

    try:
        service = NvidiaService(
            model=get_nvidia_peer_model(),
            timeout_seconds=get_nvidia_peer_timeout_seconds(),
            retry_attempts=1,
        )
        raw_response = service.generate_text(
            system_prompt=_PEER_DISCOVERY_SYSTEM_PROMPT,
            user_prompt=f"Ticker: {normalized_target}",
        )
    except NvidiaServiceError:
        return []
    except Exception:
        return []

    parsed_symbols = _parse_model_peer_list(raw_response)
    if not parsed_symbols:
        return []

    cleaned_symbols = _sanitize_model_symbols(parsed_symbols, normalized_target)
    if not cleaned_symbols:
        return []

    return _filter_tradable_symbols(cleaned_symbols)


def get_peer_group_averages(peer_list: list[str]) -> dict[str, float | None]:
    metrics = {
        "forwardPE": [],
        "priceToSalesTrailing12Months": [],
        "profitMargins": [],
        "revenueGrowth": [],
    }

    for peer in peer_list:
        symbol = str(peer or "").strip().upper()
        if not symbol:
            continue

        try:
            info = yf.Ticker(symbol).info or {}
        except Exception:
            continue

        for metric_key in metrics:
            value = _to_float(info.get(metric_key))
            if value is None:
                continue
            metrics[metric_key].append(value)

    return {
        "forwardPE": _mean(metrics["forwardPE"]),
        "priceToSalesTrailing12Months": _mean(metrics["priceToSalesTrailing12Months"]),
        "profitMargins": _mean(metrics["profitMargins"]),
        "revenueGrowth": _mean(metrics["revenueGrowth"]),
    }


def calculate_relative_valuation(
    target_metrics_dict: dict[str, Any],
    peer_averages_dict: dict[str, float | None],
) -> dict[str, float | None]:
    target_forward_pe = _to_float(target_metrics_dict.get("forwardPE"))
    target_ps = _to_float(target_metrics_dict.get("priceToSalesTrailing12Months"))
    target_margin = _to_float(target_metrics_dict.get("profitMargins"))
    target_growth = _to_float(target_metrics_dict.get("revenueGrowth"))

    peer_forward_pe = _to_float(peer_averages_dict.get("forwardPE"))
    peer_ps = _to_float(peer_averages_dict.get("priceToSalesTrailing12Months"))
    peer_margin = _to_float(peer_averages_dict.get("profitMargins"))
    peer_growth = _to_float(peer_averages_dict.get("revenueGrowth"))

    return {
        "target_forward_pe": target_forward_pe,
        "peer_avg_forward_pe": peer_forward_pe,
        "pe_to_sector_pe_ratio": _safe_ratio(target_forward_pe, peer_forward_pe),
        "forward_pe_premium_pct": _premium_pct(target_forward_pe, peer_forward_pe),
        "target_ps": target_ps,
        "peer_avg_ps": peer_ps,
        "ps_premium_pct": _premium_pct(target_ps, peer_ps),
        "target_margin": target_margin,
        "peer_avg_margin": peer_margin,
        "margin_spread_pct": _spread_pct_points(target_margin, peer_margin),
        "target_growth": target_growth,
        "peer_avg_growth": peer_growth,
        "growth_spread_pct": _spread_pct_points(target_growth, peer_growth),
    }


def build_peer_valuation_text(
    peer_list: list[str],
    target_metrics_dict: dict[str, Any],
    peer_averages_dict: dict[str, float | None],
    relative_valuation: dict[str, float | None],
) -> str:
    if not peer_list:
        return PEER_DATA_FALLBACK_TEXT

    target_fpe = _fmt_number(_to_float(target_metrics_dict.get("forwardPE")))
    peer_fpe = _fmt_number(_to_float(peer_averages_dict.get("forwardPE")))
    fpe_premium = _fmt_percent_number(relative_valuation.get("forward_pe_premium_pct"))

    target_ps = _fmt_number(_to_float(target_metrics_dict.get("priceToSalesTrailing12Months")))
    peer_ps = _fmt_number(_to_float(peer_averages_dict.get("priceToSalesTrailing12Months")))

    target_margin = _fmt_percent_number(_fraction_to_percent(_to_float(target_metrics_dict.get("profitMargins"))))
    peer_margin = _fmt_percent_number(_fraction_to_percent(_to_float(peer_averages_dict.get("profitMargins"))))
    margin_spread = _fmt_percent_number(relative_valuation.get("margin_spread_pct"))

    target_growth = _fmt_percent_number(_fraction_to_percent(_to_float(target_metrics_dict.get("revenueGrowth"))))
    peer_growth = _fmt_percent_number(_fraction_to_percent(_to_float(peer_averages_dict.get("revenueGrowth"))))
    growth_spread = _fmt_percent_number(relative_valuation.get("growth_spread_pct"))

    basket = ", ".join(peer_list)
    return (
        f"Automated Peer Basket: {basket}. "
        f"VALUATION: Target Forward P/E is {target_fpe} vs Peer Avg {peer_fpe} "
        f"(a {_pct_text(fpe_premium)} premium/discount). "
        f"Target P/S is {target_ps} vs Peer Avg {peer_ps}. "
        f"EFFICIENCY & GROWTH: Target Profit Margin is {_pct_text(target_margin)} vs Peer Avg {_pct_text(peer_margin)} "
        f"(a {_pct_text(margin_spread)} spread). "
        f"Target Rev Growth is {_pct_text(target_growth)} vs Peer Avg {_pct_text(peer_growth)} "
        f"(a {_pct_text(growth_spread)} spread)."
    )


def build_peer_signals(relative_valuation: dict[str, float | None]) -> dict[str, MetricSignal]:
    return {
        "peer_pe_to_sector_pe_ratio": _score_from_bands(
            key="peer_pe_to_sector_pe_ratio",
            value=_to_float(relative_valuation.get("pe_to_sector_pe_ratio")),
            bands=PEER_PE_TO_SECTOR_PE_RATIO_BANDS,
            note=(
                "PE-to-sector-PE ratio compares target forward P/E with the peer basket average; "
                "lower ratios indicate a valuation discount versus sector peers."
            ),
        ),
        "peer_forward_pe_premium": _score_from_bands(
            key="peer_forward_pe_premium",
            value=_to_float(relative_valuation.get("forward_pe_premium_pct")),
            bands=PEER_FORWARD_PE_PREMIUM_BANDS,
            note=(
                "Forward P/E premium compares target valuation against peer average; "
                "lower premium (or discount) is generally supportive."
            ),
        ),
        "peer_ps_premium": _score_from_bands(
            key="peer_ps_premium",
            value=_to_float(relative_valuation.get("ps_premium_pct")),
            bands=PEER_PS_PREMIUM_BANDS,
            note=(
                "Price-to-sales premium compares top-line valuation against peers; "
                "large premiums require stronger execution."
            ),
        ),
        "peer_margin_spread": _score_from_bands(
            key="peer_margin_spread",
            value=_to_float(relative_valuation.get("margin_spread_pct")),
            bands=PEER_MARGIN_SPREAD_BANDS,
            note="Profit margin spread measures operating efficiency advantage versus peer average.",
        ),
        "peer_growth_spread": _score_from_bands(
            key="peer_growth_spread",
            value=_to_float(relative_valuation.get("growth_spread_pct")),
            bands=PEER_GROWTH_SPREAD_BANDS,
            note="Revenue growth spread tracks relative expansion pace versus peer basket.",
        ),
    }


def _parse_model_peer_list(raw_response: str) -> list[Any]:
    cleaned = _strip_code_fences(raw_response)
    candidates = [cleaned]
    bracket_block = _extract_first_bracket_block(cleaned)
    if bracket_block and bracket_block != cleaned:
        candidates.append(bracket_block)

    for candidate in candidates:
        parsed = _parse_candidate_list(candidate)
        if parsed is not None:
            return parsed
    return []


def _parse_candidate_list(text: str) -> list[Any] | None:
    if not text:
        return None

    for parser in (_parse_with_literal_eval, _parse_with_json):
        parsed = parser(text)
        if parsed is None:
            continue
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, (tuple, set)):
            return list(parsed)
        if isinstance(parsed, dict):
            peers = parsed.get("peers") or parsed.get("symbols")
            if isinstance(peers, list):
                return peers
    return None


def _parse_with_literal_eval(text: str) -> Any | None:
    try:
        return ast.literal_eval(text)
    except Exception:
        return None


def _parse_with_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.splitlines()
    if not lines:
        return cleaned

    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    if lines and lines[0].strip().lower() in {"python", "py", "json"}:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _extract_first_bracket_block(text: str) -> str:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start : end + 1].strip()


def _sanitize_model_symbols(parsed_symbols: list[Any], target_ticker: str) -> list[str]:
    target_base = _base_symbol(target_ticker)
    is_indian_target = target_ticker.endswith(".NS") or target_ticker.endswith(".BO")

    deduped: list[str] = []
    seen: set[str] = set()
    for raw in parsed_symbols:
        symbol = _normalize_symbol(raw)
        if symbol is None:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)

        if symbol == target_ticker:
            continue
        if _base_symbol(symbol) == target_base:
            continue

        if is_indian_target and not (symbol.endswith(".NS") or symbol.endswith(".BO")):
            continue

        deduped.append(symbol)
        if len(deduped) >= _MAX_VERIFIED_PEERS:
            break

    return deduped


def _filter_tradable_symbols(symbols: list[str]) -> list[str]:
    output: list[str] = []
    for symbol in symbols:
        if _is_tradable_symbol(symbol):
            output.append(symbol)
    return output


def _is_tradable_symbol(symbol: str) -> bool:
    info = _safe_info(symbol)
    quote_type = str(info.get("quoteType") or "").strip().upper()
    if quote_type == "INDEX":
        return False

    if info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None:
        return True

    try:
        history = yf.Ticker(symbol).history(period="1mo", interval="1d")
    except Exception:
        return False

    if history is None:
        return False
    return bool(getattr(history, "empty", True) is False)


def _load_cached_peer_basket(target_ticker: str) -> list[str]:
    payload = _read_cache_payload()
    entry = payload.get(target_ticker)
    if not isinstance(entry, dict):
        return []

    cached_at = _parse_cache_timestamp(entry.get("updated_at"))
    if cached_at is None:
        return []
    if datetime.now(timezone.utc) - cached_at > _CACHE_TTL:
        return []

    peers = entry.get("peers")
    if not isinstance(peers, list):
        return []

    normalized = _sanitize_model_symbols(peers, target_ticker)
    if not normalized:
        return []

    return _filter_tradable_symbols(normalized)


def _persist_peer_basket(target_ticker: str, peers: list[str]) -> None:
    normalized = _sanitize_model_symbols(peers, target_ticker)
    if not normalized:
        return

    payload = _read_cache_payload()
    payload[target_ticker] = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "peers": normalized,
    }
    _write_cache_payload(payload)


def _load_builtin_peer_override(target_ticker: str) -> list[str]:
    peers = _BUILT_IN_PEER_OVERRIDES.get(target_ticker)
    if not peers:
        return []

    normalized = _sanitize_model_symbols(peers, target_ticker)
    if not normalized:
        return []
    return _filter_tradable_symbols(normalized)


def _read_cache_payload() -> dict[str, Any]:
    try:
        raw = _CACHE_FILE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

    try:
        parsed = json.loads(raw)
    except Exception:
        return {}

    if not isinstance(parsed, dict):
        return {}
    return parsed


def _write_cache_payload(payload: dict[str, Any]) -> None:
    try:
        _CACHE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _CACHE_FILE_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(_CACHE_FILE_PATH)
    except Exception:
        return


def _parse_cache_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_info(symbol: str) -> dict[str, Any]:
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


def _normalize_symbol(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip().upper()
    if not text:
        return None
    if not _SYMBOL_PATTERN.match(text):
        return None
    return text


def _base_symbol(value: str) -> str:
    return value.split(".", 1)[0]


def _score_from_bands(
    key: str,
    value: float | None,
    bands: tuple[ThresholdBand, ...],
    note: str,
) -> MetricSignal:
    if value is None:
        return MetricSignal(
            key=key,
            value=None,
            label=SignalLabel.MISSING,
            score=0.0,
            available=False,
            note=f"{note} Metric is unavailable.",
        )

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


def _premium_pct(target: float | None, peer_avg: float | None) -> float | None:
    if target is None or peer_avg is None or peer_avg == 0:
        return None
    return ((target / peer_avg) - 1.0) * 100.0


def _safe_ratio(target: float | None, peer_avg: float | None) -> float | None:
    if target is None or peer_avg is None or peer_avg == 0:
        return None
    return target / peer_avg


def _spread_pct_points(target_fraction: float | None, peer_fraction: float | None) -> float | None:
    if target_fraction is None or peer_fraction is None:
        return None
    return (target_fraction * 100.0) - (peer_fraction * 100.0)


def _fraction_to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100.0


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


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


def _fmt_number(value: float | None) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    return f"{value:.2f}"


def _fmt_percent_number(value: float | None) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    return f"{value:.2f}"


def _pct_text(value: str) -> str:
    if value == DATA_UNAVAILABLE:
        return DATA_UNAVAILABLE
    return f"{value}%"
