from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from typing import Any

from equity_reporter.ai.input_packer import DATA_UNAVAILABLE, build_ai_input_payload
from equity_reporter.models import MarketSnapshot, ProjectionScenarios, ScoreCard


@dataclass(slots=True, frozen=True)
class PromptComposeResult:
    system_prompt: str
    user_prompt: str
    payload: dict[str, Any]
    payload_json: str


def build_structured_prompt_input(
    snapshot: MarketSnapshot,
    signals: dict[str, Any],
    projections: ProjectionScenarios,
    scorecard: ScoreCard,
) -> PromptComposeResult:
    payload = build_ai_input_payload(snapshot, signals, projections, scorecard)
    payload["sector_relativity_peer_data"] = _normalize_for_prompt(signals.get("peer_sector_data"))
    payload["sector_relativity_peer_text"] = _normalize_for_prompt(signals.get("peer_sector_text"))
    payload = _normalize_payload(payload)

    payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    benchmark = _extract_benchmark(payload)
    current_price = _extract_current_price(payload)
    sector_data_state = _extract_sector_data_state(payload)
    peer_context_text = _extract_peer_context_text(payload)
    derivatives_context_text = _extract_derivatives_context_text(payload)
    available_horizons = _extract_available_horizons(payload)

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        benchmark=benchmark,
        current_price=current_price,
        sector_data_state=sector_data_state,
        peer_context_text=peer_context_text,
        derivatives_context_text=derivatives_context_text,
        available_horizons=available_horizons,
        payload_json=payload_json,
    )
    return PromptComposeResult(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        payload=payload,
        payload_json=payload_json,
    )


def _build_system_prompt() -> str:
    return (
        "Act as a 160 IQ Senior Portfolio Manager and Quantitative Equity Analyst at a top-tier hedge fund. "
        "Be brutally objective, data-driven, and highly professional. Avoid fluff, vague claims, and cliches. "
        "Reason internally and output only the final answer."
    )


def _build_user_prompt(
    *,
    benchmark: str,
    current_price: str,
    sector_data_state: str,
    peer_context_text: str,
    derivatives_context_text: str,
    available_horizons: str,
    payload_json: str,
) -> str:
    return (
        "Your objective is to analyze the provided financial, technical, volume/flow, volatility, and scoring data "
        "for one asset and produce a ruthless, objective, actionable equity research report.\n\n"
        "Cross-reference metrics to form a coherent thesis. Do not merely define indicators.\n\n"
        "Use this strict hierarchy in your output:\n\n"
        "## 1. Fundamental Deep-Dive & Valuation\n"
        "* Analyze Growth vs Valuation using Quarterly Revenue Growth, Profit Margin, Operating Margin, Trailing/Forward P/E.\n"
        "* Assess capital efficiency using Return on Equity and Return on Capital Employed (ROCE).\n"
        "* Assess capital structure using Debt to Equity and Total Debt.\n"
        "* Explicitly call out critical missing fields marked as Data Unavailable and explain limitations.\n\n"
        "## 2. Technical Posture & Institutional Liquidity\n"
        "* Determine macro trend with SMA50/SMA200 and Ichimoku.\n"
        "* Evaluate momentum using RSI and MACD.\n"
        "* Evaluate institutional flow using OBV, Relative Volume, and Volume Profile "
        "(Point of Control & High Volume Nodes).\n\n"
        "## 3. Volatility, F&O, & Risk Matrix\n"
        "* Analyze Beta across provided timeframes (Weekly, 1M, 1Y, 2Y, 5Y).\n"
        "* Assess short-term volatility expectations using Options Implied Volatility (IV) "
        "and put/call positioning, if available.\n"
        f"* {derivatives_context_text}\n"
        f"* Explain likely behavior during a broader correction based on benchmark beta (Benchmark: {benchmark}).\n\n"
        "## 4. Tactical Execution Plan\n"
        f"* Assume current price is {current_price}.\n"
        "* Define entry zones using mathematical S/R Gravity Wells "
        "(confluence of Volume Profile, Fibonacci, SMAs, and other provided levels).\n"
        "* Define stop-loss/risk controls based on breakdown below the strongest structural Gravity Well.\n"
        "* Recommend position sizing logic factoring in volatility, F&O context, and trend risk.\n\n"
        "## 5. Manual Trade Management & Invalidation Rules\n"
        "* Thesis Invalidation (Bailout): define 1-2 specific daily/weekly price-action setups that break the thesis and mandate immediate manual exit.\n"
        "* Profit-Taking Schedule: provide a clear scale-out plan for the 2-6 month horizon (for example, partial exits at projection targets and trailing rules for the remainder).\n"
        "* Active Monitoring Checklist: provide 2 leading indicators from provided data to check weekly for trend exhaustion risk.\n\n"
        "## 6. Scenario Modeling & Probability Matrix\n"
        f"* Interpret the provided Hybrid Quant projections ({available_horizons}).\n"
        "* For the 1-2 month horizon, anchor the thesis heavily to the Options IV Expected Move, if available.\n"
        "* For the 3-6 month horizons, interpret targets as Empirical Historical Return Quantiles "
        "adjusted by S/R Gravity Wells.\n"
        "* Do not treat projections as linear targets; analyze them as statistical probability curves.\n\n"
        "## 7. Macro Stress Test\n"
        f"* Assume a sudden 5% correction in benchmark index ({benchmark}) or a rate-hike shock.\n"
        "* Evaluate fragility using Trailing P/E, Weekly vs 1Y Beta, Debt burden, and Profit Margin buffer.\n"
        f"* Sector peer context (if available): {peer_context_text}\n"
        f"* Sector peer data state in this run: {sector_data_state}.\n"
        '* Conclude whether this asset behaves as "flight to safety" or "first to be liquidated".\n\n'
        "## 8. Sector Relativity & Peer Valuations\n"
        "* Compare valuation and growth against the provided deterministic peer basket.\n"
        "* Use PE-to-sector-PE ratio to judge whether the target trades at a discount, parity, or premium to peers.\n"
        "* Classify the asset as a sector leader, at parity, or a laggard with explicit evidence from provided spreads.\n"
        "* If sector peer data is Data Unavailable, explicitly state that sector relativity cannot be concluded "
        "and omit comparison.\n\n"
        "## 9. Executive Summary & Verdict\n"
        "* Provide a definitive verdict (Strong Buy, Buy, Hold, Sell, Strong Sell).\n"
        "* Summarize core thesis in 3-4 sentences.\n"
        "* Identify one biggest upside catalyst and one biggest risk.\n\n"
        "Critical constraints:\n"
        "1) Use ONLY the provided payload. Do not use external data, news, events, or web knowledge.\n"
        "2) Do not hallucinate missing metrics. If missing, explicitly write Data Unavailable.\n"
        "3) Ground every claim in provided numbers/signals.\n"
        "4) Keep output concise but decision-useful.\n\n"
        "Raw Data for Analysis (JSON):\n"
        f"{payload_json}"
    )


def _normalize_payload(value: Any) -> Any:
    return _normalize_for_prompt(value)


def _normalize_for_prompt(value: Any) -> Any:
    if value is None:
        return DATA_UNAVAILABLE

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else DATA_UNAVAILABLE

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not isfinite(value):
            return DATA_UNAVAILABLE
        return value

    if isinstance(value, dict):
        if not value:
            return DATA_UNAVAILABLE
        normalized = {str(k): _normalize_for_prompt(v) for k, v in value.items()}
        return normalized if normalized else DATA_UNAVAILABLE

    if isinstance(value, (list, tuple, set)):
        if not value:
            return DATA_UNAVAILABLE
        normalized_items = [_normalize_for_prompt(item) for item in value]
        return normalized_items if normalized_items else DATA_UNAVAILABLE

    return str(value)


def _extract_benchmark(payload: dict[str, Any]) -> str:
    fundamentals = payload.get("fundamentals")
    if isinstance(fundamentals, dict):
        benchmark = fundamentals.get("beta_benchmark")
        if isinstance(benchmark, str) and benchmark.strip():
            return benchmark.strip()
    return DATA_UNAVAILABLE


def _extract_current_price(payload: dict[str, Any]) -> str:
    meta = payload.get("meta")
    if isinstance(meta, dict):
        price = meta.get("current_price")
        if isinstance(price, (int, float)):
            return str(price)
        if isinstance(price, str) and price.strip():
            return price.strip()
    return DATA_UNAVAILABLE


def _extract_available_horizons(payload: dict[str, Any]) -> str:
    projections = payload.get("projections")
    if not isinstance(projections, dict):
        return DATA_UNAVAILABLE
    horizons = projections.get("horizons")
    if isinstance(horizons, dict) and horizons:
        keys = [str(key) for key in horizons.keys()]
        return ", ".join(keys)
    return DATA_UNAVAILABLE


def _extract_peer_context_text(payload: dict[str, Any]) -> str:
    value = payload.get("sector_relativity_peer_text")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DATA_UNAVAILABLE


def _extract_derivatives_context_text(payload: dict[str, Any]) -> str:
    derivatives = payload.get("derivatives_smart_money")
    if isinstance(derivatives, dict):
        text_block = derivatives.get("text_block")
        if isinstance(text_block, str) and text_block.strip():
            return text_block.strip()
    return DATA_UNAVAILABLE


def _extract_sector_data_state(payload: dict[str, Any]) -> str:
    peer_data = payload.get("sector_relativity_peer_data")
    if isinstance(peer_data, dict):
        peer_list = peer_data.get("peer_list")
        if isinstance(peer_list, list) and peer_list:
            return "Provided"
        if isinstance(peer_list, str) and peer_list != DATA_UNAVAILABLE:
            return "Provided"
    return DATA_UNAVAILABLE
