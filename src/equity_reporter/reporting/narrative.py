from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from equity_reporter.config import CATEGORY_METRIC_WEIGHTS
from equity_reporter.models import MetricSignal, ScoreCard, SignalLabel

METRIC_FRIENDLY_NAMES: dict[str, str] = {
    "valuation_pe_trend": "valuation trend",
    "return_on_equity": "return on equity",
    "return_on_capital_employed": "return on capital employed",
    "profit_margin": "profit margin",
    "operating_margin": "operating margin",
    "debt_to_equity": "debt-to-equity",
    "current_ratio": "current ratio",
    "quarterly_revenue_growth": "quarterly revenue growth",
    "beta_profile_fit": "beta risk-fit",
    "short_ratio": "short ratio",
    "short_percent_of_float": "short interest as % of float",
    "fcf_vs_debt": "FCF vs debt coverage",
    "sma_crossover": "SMA trend regime",
    "rsi_14": "RSI momentum",
    "macd_crossover": "MACD crossover",
    "bollinger_position": "Bollinger position",
    "adx_trend_strength": "ADX trend strength",
    "ichimoku_cloud": "Ichimoku cloud state",
    "fibonacci_support_breakout": "Fibonacci support/breakout",
    "obv_30d_trend": "OBV 30-day flow trend",
    "relative_volume_10d_3m": "10D vs 3M relative volume",
    "futures_oi_buildup": "futures OI build-up",
    "rollover_percentage": "rollover percentage",
    "pcr_sentiment": "PCR sentiment",
    "iv_percentile": "IV percentile",
    "peer_forward_pe_premium": "peer forward P/E premium",
    "peer_pe_to_sector_pe_ratio": "PE-to-sector-PE ratio",
    "peer_ps_premium": "peer P/S premium",
    "peer_margin_spread": "peer profit margin spread",
    "peer_growth_spread": "peer revenue growth spread",
}

CATEGORY_FRIENDLY_NAMES: dict[str, str] = {
    "fundamental": "Fundamental",
    "technical": "Technical",
    "volume_risk": "Volume/Risk/F&O",
    "peer_relativity": "Peer Relativity",
}


@dataclass(slots=True)
class NarrativeBundle:
    metric_notes: dict[str, str] = field(default_factory=dict)
    category_notes: dict[str, str] = field(default_factory=dict)
    overall_note: str = ""


def build_narratives(scorecard: ScoreCard, signals: dict[str, Any]) -> NarrativeBundle:
    metric_notes = _build_metric_notes(scorecard.metric_signals)
    category_notes = _build_category_notes(scorecard)
    overall_note = _build_overall_note(scorecard)
    return NarrativeBundle(metric_notes=metric_notes, category_notes=category_notes, overall_note=overall_note)


def _build_metric_notes(metric_signals: dict[str, MetricSignal]) -> dict[str, str]:
    notes: dict[str, str] = {}
    for key, signal in metric_signals.items():
        metric_name = METRIC_FRIENDLY_NAMES.get(key, key.replace("_", " "))

        if not signal.available or signal.label == SignalLabel.MISSING:
            notes[key] = f"{metric_name.title()} data was unavailable in this run."
            continue

        if signal.note:
            notes[key] = signal.note
            continue

        if signal.label == SignalLabel.BULLISH:
            notes[key] = f"{metric_name.title()} is supportive for the current outlook."
        elif signal.label == SignalLabel.BEARISH:
            notes[key] = f"{metric_name.title()} is a negative pressure point in the setup."
        elif signal.label == SignalLabel.WARNING:
            notes[key] = f"{metric_name.title()} is a risk flag and should be monitored closely."
        else:
            notes[key] = f"{metric_name.title()} is currently neutral/indecisive."
    return notes


def _build_category_notes(scorecard: ScoreCard) -> dict[str, str]:
    output: dict[str, str] = {}

    for category, category_score in scorecard.category_scores.items():
        label = _category_label(category_score)
        weighted_metrics = _top_category_drivers(category, scorecard.metric_signals)
        friendly_category = CATEGORY_FRIENDLY_NAMES.get(category, category.title())

        if weighted_metrics:
            drivers_text = ", ".join(weighted_metrics[:2])
            note = (
                f"{friendly_category} posture is {label} at {category_score:.1f}%, "
                f"led by {drivers_text}."
            )
        else:
            note = f"{friendly_category} posture is {label} at {category_score:.1f}% with limited metric coverage."
        output[category] = note

    return output


def _build_overall_note(scorecard: ScoreCard) -> str:
    score = scorecard.final_score
    if score >= 75:
        tone = "strongly constructive"
    elif score >= 60:
        tone = "constructive with selective risk"
    elif score >= 45:
        tone = "balanced and indecisive"
    elif score >= 30:
        tone = "cautious with downside pressure"
    else:
        tone = "highly defensive"

    return (
        f"Overall setup is {tone}: final confidence is {score:.2f}% "
        f"with data coverage of {scorecard.data_coverage_pct:.2f}%."
    )


def _category_label(score: float) -> str:
    if score >= 70:
        return "bullish"
    if score <= 40:
        return "bearish"
    return "neutral"


def _top_category_drivers(category: str, metric_signals: dict[str, MetricSignal]) -> list[str]:
    metric_keys = CATEGORY_METRIC_WEIGHTS.get(category, {})
    scored: list[tuple[float, str]] = []

    for metric_key in metric_keys:
        signal = metric_signals.get(metric_key)
        if signal is None:
            continue
        contribution = signal.weight * signal.score
        metric_name = METRIC_FRIENDLY_NAMES.get(metric_key, metric_key.replace("_", " "))
        scored.append((contribution, metric_name))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [name for _, name in scored]
