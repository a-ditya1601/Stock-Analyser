from __future__ import annotations

from dataclasses import replace
from typing import Any

from equity_reporter.config import CATEGORY_METRIC_WEIGHTS, CATEGORY_WEIGHTS, VERDICT_TIERS
from equity_reporter.models import MetricSignal, ScoreCard, SignalLabel


def compute_scorecard(signals: dict[str, Any]) -> ScoreCard:
    category_weights = dict(CATEGORY_WEIGHTS)
    metric_weights = _normalize_metric_weight_map(CATEGORY_METRIC_WEIGHTS)
    flattened_signals = _collect_metric_signals(signals)
    configured_metric_keys = {
        metric_key for category_map in metric_weights.values() for metric_key in category_map
    }

    scorecard = ScoreCard()
    scorecard.category_weights = category_weights
    scorecard.category_scores = {category: 0.0 for category in category_weights}
    scorecard.max_score = float(sum(category_weights.values()))

    total_available_weight = 0.0
    final_points = 0.0
    available_metric_keys: set[str] = set()

    for category, category_weight in category_weights.items():
        per_metric_weights = metric_weights.get(category, {})
        category_available_weight = 0.0
        category_points = 0.0

        for metric_key, metric_weight in per_metric_weights.items():
            expected_weight = category_weight * metric_weight

            metric_signal = flattened_signals.get(metric_key) or _missing_signal(metric_key)
            metric_signal = replace(metric_signal, key=metric_key, weight=expected_weight)
            scorecard.metric_signals[metric_key] = metric_signal

            if not metric_signal.available:
                continue

            available_metric_keys.add(metric_key)
            score = _clamp(metric_signal.score, 0.0, 1.0)
            weighted_points = expected_weight * score
            total_available_weight += expected_weight
            final_points += weighted_points
            category_available_weight += expected_weight
            category_points += weighted_points

        if category_available_weight > 0:
            scorecard.category_scores[category] = round((category_points / category_available_weight) * 100.0, 2)

    for metric_key, metric_signal in flattened_signals.items():
        if metric_key not in scorecard.metric_signals:
            scorecard.metric_signals[metric_key] = replace(metric_signal, weight=0.0)

    confidence = (final_points / total_available_weight) * 100.0 if total_available_weight > 0 else 0.0
    scorecard.final_score = round(_clamp(confidence, 0.0, 100.0), 2)
    total_metric_count = len(configured_metric_keys)
    scorecard.data_coverage_pct = round(
        (len(available_metric_keys) / total_metric_count) * 100.0 if total_metric_count > 0 else 0.0,
        2,
    )
    scorecard.verdict = _resolve_verdict(scorecard.final_score)
    return scorecard


def _collect_metric_signals(signals: dict[str, Any]) -> dict[str, MetricSignal]:
    output: dict[str, MetricSignal] = {}

    for key in ("fundamental_signals", "technical_signals", "volume_signals", "peer_signals"):
        raw_group = signals.get(key)
        if not isinstance(raw_group, dict):
            continue
        for metric_key, metric_signal in raw_group.items():
            if isinstance(metric_signal, MetricSignal):
                output[metric_key] = metric_signal

    fib_signal = signals.get("fibonacci_signal")
    if isinstance(fib_signal, MetricSignal):
        metric_key = fib_signal.key if fib_signal.key else "fibonacci_support_breakout"
        output[metric_key] = fib_signal

    return output


def _normalize_metric_weight_map(
    raw_weights: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    for category, metric_map in raw_weights.items():
        cleaned = {key: max(0.0, float(weight)) for key, weight in metric_map.items()}
        total = sum(cleaned.values())
        if total <= 0:
            normalized[category] = {}
            continue
        normalized[category] = {key: weight / total for key, weight in cleaned.items()}
    return normalized


def _resolve_verdict(final_score: float) -> str:
    for tier in sorted(VERDICT_TIERS, key=lambda item: item.min_score, reverse=True):
        if final_score >= tier.min_score:
            return tier.verdict
    return "UNRATED"


def _missing_signal(metric_key: str) -> MetricSignal:
    return MetricSignal(
        key=metric_key,
        value=None,
        label=SignalLabel.MISSING,
        score=0.0,
        available=False,
        note="Metric signal unavailable in current run.",
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
