from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import exp, isfinite, sqrt
from typing import Any

import pandas as pd

from equity_reporter.config import (
    ATR_PERIOD,
    PROJECTION_HORIZON_MONTHS,
    TRADING_DAYS_PER_MONTH,
)
from equity_reporter.models import MarketSnapshot, MetricSignal, ProjectionRange, ProjectionScenarios, SignalLabel


METHODOLOGY_HYBRID = "Hybrid Quant + IV + Support/Resistance Gravity"
METHODOLOGY_ATR_FALLBACK = "ATR fallback"
FORWARD_SAMPLE_MINIMUM = 30
VOLUME_PROFILE_BINS = 40
IV_FRONT_HORIZON_WEIGHT = 0.65
GRAVITY_WEIGHT = 0.35
MAX_GRAVITY_ADJUSTMENT_SHARE = 0.35
HORIZON_TRADING_DAYS: dict[str, int] = {
    "1-2 months": 42,
    "3-4 months": 84,
    "5-6 months": 126,
}
ANALYST_BLEND_CAPS: dict[int, float] = {
    2: 0.10,
    4: 0.20,
    6: 0.30,
}


@dataclass(slots=True)
class LevelCandidate:
    price: float
    kind: str
    strength: float = 1.0
    recency: float = 0.0
    volume_confirmed: bool = False


@dataclass(slots=True)
class LevelCluster:
    price: float
    kinds: set[str] = field(default_factory=set)
    strength: float = 0.0
    touches: int = 0
    volume_confirmed: bool = False

    def as_payload(self) -> dict[str, Any]:
        return {
            "price": round(self.price, 4),
            "strength": round(min(100.0, self.strength), 2),
            "touches": self.touches,
            "types": sorted(self.kinds),
            "volume_confirmed": self.volume_confirmed,
        }


def build_projections(snapshot: MarketSnapshot, signals: dict[str, Any]) -> ProjectionScenarios:
    history = snapshot.history.copy()
    high = _to_numeric_series(history, "High")
    low = _to_numeric_series(history, "Low")
    close = _to_numeric_series(history, "Close")
    volume = _to_numeric_series(history, "Volume")

    latest_close = _resolve_latest_close(snapshot, close)
    if latest_close is None or latest_close <= 0:
        return ProjectionScenarios(
            methodology=METHODOLOGY_ATR_FALLBACK,
            projection_confidence="Low",
            fallback_reason="Latest close was unavailable.",
        )

    atr_14 = _compute_atr_14(high, low, close)
    monthly_swing = atr_14 * sqrt(TRADING_DAYS_PER_MONTH) if atr_14 is not None else None
    analyst_data = _extract_analyst_targets(snapshot.info)
    analyst_base = analyst_data["mean"] or analyst_data["median"]
    bias = _directional_bias(signals)
    volume_profile = _build_volume_profile(high, low, close, volume)
    levels = _build_level_clusters(
        history=history,
        signals=signals,
        latest_close=latest_close,
        atr_14=atr_14,
        volume_profile=volume_profile,
    )

    support_clusters = sorted(
        [cluster for cluster in levels if cluster.price <= latest_close],
        key=lambda cluster: (cluster.strength, -abs(latest_close - cluster.price)),
        reverse=True,
    )
    resistance_clusters = sorted(
        [cluster for cluster in levels if cluster.price >= latest_close],
        key=lambda cluster: (cluster.strength, -abs(cluster.price - latest_close)),
        reverse=True,
    )

    scenarios = ProjectionScenarios(
        atr_14=atr_14,
        monthly_swing=monthly_swing,
        methodology=METHODOLOGY_HYBRID,
        projection_confidence=_projection_confidence(close, levels, signals),
        support_levels=[cluster.as_payload() for cluster in support_clusters[:5]],
        resistance_levels=[cluster.as_payload() for cluster in resistance_clusters[:5]],
        volume_profile_poc=volume_profile.get("poc"),
        volume_profile_hvns=volume_profile.get("hvns", []),
        analyst_target_mean=analyst_data["mean"],
        analyst_target_low=analyst_data["low"],
        analyst_target_high=analyst_data["high"],
        analyst_opinions=analyst_data["opinions"],
    )

    fallback_reasons: list[str] = []

    for label, months in PROJECTION_HORIZON_MONTHS.items():
        horizon_days = HORIZON_TRADING_DAYS.get(label, max(1, months * TRADING_DAYS_PER_MONTH))
        quant_range = _build_historical_quantile_range(latest_close, close, horizon_days, bias)
        if quant_range is None:
            quant_range = _build_volatility_range(latest_close, monthly_swing, months, bias)
            fallback_reasons.append(f"{label}: historical sample count below {FORWARD_SAMPLE_MINIMUM}; used ATR fallback.")

        blended_range = quant_range
        if months <= 2:
            iv_range = _build_options_expected_move_range(latest_close, signals, bias)
            if iv_range is not None:
                blended_range = _blend_ranges(quant_range, iv_range, IV_FRONT_HORIZON_WEIGHT)
            else:
                fallback_reasons.append(f"{label}: ATM IV unavailable; used historical/ATR range.")

        analyst_weight = _analyst_blend_weight(months, analyst_data["opinions"], analyst_base)
        if analyst_weight > 0 and analyst_base is not None:
            analyst_range = _build_analyst_range(
                analyst_base=analyst_base,
                analyst_low=analyst_data["low"],
                analyst_high=analyst_data["high"],
                reference_range=blended_range,
            )
            blended_range = _blend_ranges(blended_range, analyst_range, analyst_weight)
            scenarios.analyst_blend_applied = True

        gravity_range = _apply_support_resistance_gravity(
            blended_range,
            latest_close=latest_close,
            atr_14=atr_14,
            support_clusters=support_clusters,
            resistance_clusters=resistance_clusters,
        )

        scenarios.horizons[label] = _ordered_range(gravity_range)
        scenarios.blend_weights[label] = analyst_weight
        scenarios.scenario_probabilities[label] = _scenario_probabilities(bias)

    scenarios.fallback_reason = " ".join(dict.fromkeys(fallback_reasons))
    if not levels:
        scenarios.projection_confidence = "Low"
        scenarios.fallback_reason = (scenarios.fallback_reason + " Support/resistance clusters unavailable.").strip()
    return scenarios


def _to_numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype="float64")
    series = frame[column]
    if isinstance(series, pd.DataFrame):
        if series.empty:
            return pd.Series(dtype="float64")
        series = series.iloc[:, 0]
    return pd.to_numeric(series, errors="coerce")


def _resolve_latest_close(snapshot: MarketSnapshot, close: pd.Series) -> float | None:
    if snapshot.current_price is not None and snapshot.current_price > 0:
        return float(snapshot.current_price)
    non_null = close.dropna()
    if non_null.empty:
        return None
    value = float(non_null.iloc[-1])
    return value if value > 0 else None


def _compute_atr_14(high: pd.Series, low: pd.Series, close: pd.Series) -> float | None:
    frame = pd.DataFrame({"high": high, "low": low, "close": close}).dropna()
    if len(frame) < ATR_PERIOD + 1:
        return None

    prev_close = frame["close"].shift(1)
    tr_components = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    true_range = tr_components.max(axis=1)
    atr = true_range.rolling(window=ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    non_null = atr.dropna()
    if non_null.empty:
        return None
    return float(non_null.iloc[-1])


def _build_historical_quantile_range(
    latest_close: float,
    close: pd.Series,
    horizon_days: int,
    bias: float,
) -> ProjectionRange | None:
    valid_close = close.dropna()
    valid_close = valid_close[valid_close > 0]
    if len(valid_close) <= horizon_days + FORWARD_SAMPLE_MINIMUM:
        return None

    forward_returns = (valid_close.shift(-horizon_days) / valid_close).dropna()
    forward_returns = forward_returns[forward_returns > 0]
    if len(forward_returns) < FORWARD_SAMPLE_MINIMUM:
        return None

    log_forward_returns = forward_returns.apply(lambda value: _safe_log(value)).dropna()
    if len(log_forward_returns) < FORWARD_SAMPLE_MINIMUM:
        return None

    bear_return = float(log_forward_returns.quantile(0.20))
    base_return = float(log_forward_returns.quantile(0.50))
    bull_return = float(log_forward_returns.quantile(0.80))
    bear = latest_close * exp(bear_return)
    base = latest_close * exp(base_return)
    bull = latest_close * exp(bull_return)
    width = max(0.0, bull - bear)
    base = base + (bias * 0.15 * width)
    return ProjectionRange(bear=max(0.01, bear), base=max(0.01, base), bull=max(0.01, bull))


def _safe_log(value: float) -> float | None:
    try:
        from math import log

        if value <= 0:
            return None
        output = log(value)
        return output if isfinite(output) else None
    except (TypeError, ValueError):
        return None


def _build_volatility_range(
    latest_close: float,
    monthly_swing: float | None,
    months: int,
    bias: float,
) -> ProjectionRange:
    if monthly_swing is None:
        return ProjectionRange(bear=latest_close, base=latest_close, bull=latest_close)

    horizon_move = monthly_swing * sqrt(months)
    base_drift = horizon_move * 0.20 * bias
    bear = max(0.01, latest_close - (1.00 * horizon_move))
    base = max(0.01, latest_close + base_drift)
    bull = max(0.01, latest_close + (1.20 * horizon_move))
    return ProjectionRange(bear=bear, base=base, bull=bull)


def _build_options_expected_move_range(
    latest_close: float,
    signals: dict[str, Any],
    bias: float,
) -> ProjectionRange | None:
    atm_iv = _to_float(signals.get("fno_atm_iv"))
    if atm_iv is None:
        return None
    iv_decimal = atm_iv / 100.0 if atm_iv > 1.0 else atm_iv
    if iv_decimal <= 0:
        return None
    days_to_expiry = _days_to_expiry(signals.get("fno_expiry")) or 42
    expected_move = latest_close * iv_decimal * sqrt(days_to_expiry / 365.0)
    if expected_move <= 0:
        return None
    return ProjectionRange(
        bear=max(0.01, latest_close - expected_move),
        base=max(0.01, latest_close + (bias * expected_move * 0.20)),
        bull=max(0.01, latest_close + expected_move),
    )


def _days_to_expiry(raw_expiry: Any) -> int | None:
    if raw_expiry is None:
        return None
    text = str(raw_expiry).strip()
    if not text:
        return None
    parsed: date | None = None
    for fmt in ("%Y-%m-%d", "%d%b%Y", "%d%b%y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            parsed = datetime.strptime(text.upper(), fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    return max(1, (parsed - date.today()).days)


def _build_volume_profile(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> dict[str, Any]:
    frame = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume}).dropna().tail(252)
    frame = frame[(frame["volume"] > 0) & (frame["high"] > 0) & (frame["low"] > 0) & (frame["close"] > 0)]
    if len(frame) < 20:
        return {"poc": None, "hvns": []}

    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    price_min = float(typical.min())
    price_max = float(typical.max())
    if price_max <= price_min:
        return {"poc": price_min, "hvns": [price_min]}

    bins = min(VOLUME_PROFILE_BINS, max(10, len(frame) // 4))
    bucket = pd.cut(typical, bins=bins, include_lowest=True)
    profile = frame.groupby(bucket, observed=True)["volume"].sum()
    if profile.empty:
        return {"poc": None, "hvns": []}

    poc_interval = profile.idxmax()
    poc = _interval_midpoint(poc_interval)
    threshold = float(profile.quantile(0.80))
    hvns = [
        _interval_midpoint(interval)
        for interval, bucket_volume in profile.items()
        if float(bucket_volume) >= threshold
    ]
    hvns = sorted({round(value, 4) for value in hvns if value is not None})
    return {"poc": round(poc, 4) if poc is not None else None, "hvns": hvns}


def _interval_midpoint(interval: Any) -> float | None:
    try:
        return float((interval.left + interval.right) / 2.0)
    except AttributeError:
        return None


def _build_level_clusters(
    *,
    history: pd.DataFrame,
    signals: dict[str, Any],
    latest_close: float,
    atr_14: float | None,
    volume_profile: dict[str, Any],
) -> list[LevelCluster]:
    candidates = _level_candidates_from_signals(signals)
    candidates.extend(_swing_level_candidates(history))

    poc = _to_float(volume_profile.get("poc"))
    if poc is not None:
        candidates.append(LevelCandidate(price=poc, kind="Volume POC", strength=2.5, volume_confirmed=True))
    for hvn in volume_profile.get("hvns", []):
        hvn_value = _to_float(hvn)
        if hvn_value is not None:
            candidates.append(LevelCandidate(price=hvn_value, kind="Volume HVN", strength=2.0, volume_confirmed=True))

    candidates = [candidate for candidate in candidates if candidate.price > 0 and isfinite(candidate.price)]
    if not candidates:
        return []

    tolerance = _cluster_tolerance(latest_close, atr_14)
    candidates.sort(key=lambda candidate: candidate.price)
    clusters: list[LevelCluster] = []
    for candidate in candidates:
        cluster = _nearest_cluster(clusters, candidate.price, tolerance)
        if cluster is None:
            clusters.append(
                LevelCluster(
                    price=candidate.price,
                    kinds={candidate.kind},
                    strength=_candidate_strength(candidate),
                    touches=1,
                    volume_confirmed=candidate.volume_confirmed,
                )
            )
            continue

        old_weight = max(cluster.strength, 1.0)
        new_weight = _candidate_strength(candidate)
        cluster.price = ((cluster.price * old_weight) + (candidate.price * new_weight)) / (old_weight + new_weight)
        cluster.kinds.add(candidate.kind)
        cluster.strength += new_weight
        cluster.touches += 1
        cluster.volume_confirmed = cluster.volume_confirmed or candidate.volume_confirmed

    for cluster in clusters:
        confluence_bonus = max(0, len(cluster.kinds) - 1) * 6.0
        volume_bonus = 15.0 if cluster.volume_confirmed else 0.0
        touch_bonus = min(15.0, cluster.touches * 2.0)
        cluster.strength = min(100.0, (cluster.strength * 8.0) + confluence_bonus + volume_bonus + touch_bonus)

    return sorted(clusters, key=lambda cluster: cluster.price)


def _level_candidates_from_signals(signals: dict[str, Any]) -> list[LevelCandidate]:
    specs = (
        ("sma_20", "SMA20", 1.6),
        ("sma_50", "SMA50", 2.2),
        ("sma_200", "SMA200", 2.4),
        ("bb_lower", "Bollinger Lower", 1.5),
        ("bb_middle", "Bollinger Mid", 1.0),
        ("bb_upper", "Bollinger Upper", 1.5),
        ("ichimoku_span_a", "Ichimoku Span A", 1.6),
        ("ichimoku_span_b", "Ichimoku Span B", 1.6),
        ("fib_0_382", "Fibonacci 38.2%", 2.0),
        ("fib_0_500", "Fibonacci 50.0%", 1.8),
        ("fib_0_618", "Fibonacci 61.8%", 2.3),
        ("high_6m", "6M High", 2.0),
        ("low_6m", "6M Low", 2.0),
        ("fno_max_pain", "Options Max Pain", 1.7),
    )
    output: list[LevelCandidate] = []
    for key, kind, strength in specs:
        value = _to_float(signals.get(key))
        if value is not None:
            output.append(LevelCandidate(price=value, kind=kind, strength=strength))
    return output


def _swing_level_candidates(history: pd.DataFrame) -> list[LevelCandidate]:
    high = _to_numeric_series(history, "High").dropna().tail(126)
    low = _to_numeric_series(history, "Low").dropna().tail(126)
    volume = _to_numeric_series(history, "Volume").reindex(high.index.union(low.index)).fillna(0.0)
    candidates: list[LevelCandidate] = []

    for series, kind in ((high, "Swing High"), (low, "Swing Low")):
        if len(series) < 7:
            continue
        for position in range(3, len(series) - 3):
            window = series.iloc[position - 3 : position + 4]
            value = float(series.iloc[position])
            if kind == "Swing High" and value < float(window.max()):
                continue
            if kind == "Swing Low" and value > float(window.min()):
                continue
            recency = position / max(1, len(series) - 1)
            vol_value = _to_float(volume.get(series.index[position]))
            candidates.append(LevelCandidate(price=value, kind=kind, strength=1.2 + recency, recency=recency, volume_confirmed=bool(vol_value)))

    return candidates


def _cluster_tolerance(latest_close: float, atr_14: float | None) -> float:
    atr_component = (atr_14 or 0.0) * 0.50
    pct_component = latest_close * 0.01
    return max(pct_component, atr_component, 0.01)


def _nearest_cluster(clusters: list[LevelCluster], price: float, tolerance: float) -> LevelCluster | None:
    matches = [cluster for cluster in clusters if abs(cluster.price - price) <= tolerance]
    if not matches:
        return None
    return min(matches, key=lambda cluster: abs(cluster.price - price))


def _candidate_strength(candidate: LevelCandidate) -> float:
    return max(0.5, candidate.strength + (candidate.recency * 0.5))


def _apply_support_resistance_gravity(
    rng: ProjectionRange,
    *,
    latest_close: float,
    atr_14: float | None,
    support_clusters: list[LevelCluster],
    resistance_clusters: list[LevelCluster],
) -> ProjectionRange:
    radius = max((atr_14 or 0.0) * 2.0, latest_close * 0.03, 0.01)
    return ProjectionRange(
        bear=_gravity_adjust(
            rng.bear,
            latest_close=latest_close,
            radius=radius,
            clusters=support_clusters,
        ),
        base=_gravity_adjust(
            rng.base,
            latest_close=latest_close,
            radius=radius,
            clusters=support_clusters + resistance_clusters,
        ),
        bull=_gravity_adjust(
            rng.bull,
            latest_close=latest_close,
            radius=radius,
            clusters=resistance_clusters,
        ),
    )


def _gravity_adjust(
    raw_target: float,
    *,
    latest_close: float,
    radius: float,
    clusters: list[LevelCluster],
) -> float:
    if not clusters or raw_target <= 0:
        return max(0.01, raw_target)

    weighted_delta = 0.0
    total_pull = 0.0
    for cluster in clusters:
        distance = abs(raw_target - cluster.price)
        proximity = exp(-distance / radius)
        strength_norm = min(1.0, cluster.strength / 100.0)
        pull = GRAVITY_WEIGHT * strength_norm * proximity
        weighted_delta += pull * (cluster.price - raw_target)
        total_pull += pull

    if total_pull <= 0:
        return max(0.01, raw_target)

    delta = weighted_delta / total_pull * min(1.0, total_pull)
    max_adjustment = abs(raw_target - latest_close) * MAX_GRAVITY_ADJUSTMENT_SHARE
    if max_adjustment <= 0:
        max_adjustment = radius * 0.25
    delta = max(-max_adjustment, min(max_adjustment, delta))
    return max(0.01, raw_target + delta)


def _directional_bias(signals: dict[str, Any]) -> float:
    weighted_scores: list[tuple[float, float]] = []

    sma_20 = _to_float(signals.get("sma_20"))
    sma_50 = _to_float(signals.get("sma_50"))
    sma_200 = _to_float(signals.get("sma_200"))
    if sma_20 is not None and sma_50 is not None and sma_200 is not None:
        if sma_20 > sma_50 > sma_200:
            weighted_scores.append((1.0, 1.4))
        elif sma_20 < sma_50 < sma_200:
            weighted_scores.append((-1.0, 1.4))
        elif sma_50 > sma_200:
            weighted_scores.append((0.45, 1.0))
        else:
            weighted_scores.append((-0.45, 1.0))

    macd = _to_float(signals.get("macd"))
    macd_signal = _to_float(signals.get("macd_signal"))
    if macd is not None and macd_signal is not None:
        weighted_scores.append((0.55 if macd > macd_signal else -0.55, 0.9))

    rsi = _to_float(signals.get("rsi_14"))
    if rsi is not None:
        if 45 <= rsi <= 65:
            weighted_scores.append((0.30, 0.6))
        elif rsi < 30:
            weighted_scores.append((0.20, 0.5))
        elif rsi > 75:
            weighted_scores.append((-0.45, 0.6))

    obv_slope = _to_float(signals.get("obv_30d_slope"))
    if obv_slope is not None:
        weighted_scores.append((0.45 if obv_slope > 0 else -0.45, 0.8))

    relative_volume = _to_float(signals.get("relative_volume_10d_3m"))
    if relative_volume is not None:
        if relative_volume >= 1.15:
            weighted_scores.append((0.25, 0.4))
        elif relative_volume < 0.85:
            weighted_scores.append((-0.25, 0.4))

    for signal_map_name in ("technical_signals", "volume_signals", "peer_signals", "fundamental_signals"):
        signal_map = signals.get(signal_map_name)
        if isinstance(signal_map, dict):
            for signal in signal_map.values():
                score = _signal_bias(signal)
                if score is not None:
                    weighted_scores.append((score, 0.45))

    if not weighted_scores:
        return 0.0
    numerator = sum(score * weight for score, weight in weighted_scores)
    denominator = sum(weight for _, weight in weighted_scores)
    return max(-1.0, min(1.0, numerator / denominator))


def _signal_bias(signal: Any) -> float | None:
    if not isinstance(signal, MetricSignal) or not signal.available:
        return None
    if signal.label == SignalLabel.BULLISH:
        return 0.6
    if signal.label == SignalLabel.BEARISH:
        return -0.6
    if signal.label == SignalLabel.WARNING:
        return -0.3
    if signal.label == SignalLabel.NEUTRAL:
        return 0.0
    return None


def _scenario_probabilities(bias: float) -> dict[str, float]:
    bull = max(0.10, min(0.45, 0.25 + (bias * 0.10)))
    bear = max(0.10, min(0.45, 0.25 - (bias * 0.10)))
    base = max(0.30, 1.0 - bull - bear)
    total = bull + base + bear
    return {
        "bear": round((bear / total) * 100.0, 2),
        "base": round((base / total) * 100.0, 2),
        "bull": round((bull / total) * 100.0, 2),
    }


def _projection_confidence(close: pd.Series, levels: list[LevelCluster], signals: dict[str, Any]) -> str:
    valid_close = close.dropna()
    has_iv = _to_float(signals.get("fno_atm_iv")) is not None
    if len(valid_close) >= 252 and len(levels) >= 5 and has_iv:
        return "High"
    if len(valid_close) >= 180 and len(levels) >= 3:
        return "Medium"
    return "Low"


def _extract_analyst_targets(info: dict[str, Any]) -> dict[str, float | int | None]:
    return {
        "mean": _to_float(info.get("targetMeanPrice")),
        "median": _to_float(info.get("targetMedianPrice")),
        "low": _to_float(info.get("targetLowPrice")),
        "high": _to_float(info.get("targetHighPrice")),
        "opinions": _to_int(info.get("numberOfAnalystOpinions")),
    }


def _analyst_blend_weight(
    months: int,
    opinions: int | None,
    analyst_base: float | None,
) -> float:
    if analyst_base is None or analyst_base <= 0:
        return 0.0

    if opinions is None or opinions <= 0:
        opinion_weight = 0.08
    elif opinions < 5:
        opinion_weight = 0.12
    elif opinions < 10:
        opinion_weight = 0.18
    elif opinions < 20:
        opinion_weight = 0.24
    else:
        opinion_weight = 0.30

    cap = ANALYST_BLEND_CAPS.get(months, 0.20)
    return min(cap, max(0.0, opinion_weight))


def _build_analyst_range(
    analyst_base: float,
    analyst_low: float | None,
    analyst_high: float | None,
    reference_range: ProjectionRange,
) -> ProjectionRange:
    default_half_band = max(
        abs(reference_range.bull - reference_range.base),
        abs(reference_range.base - reference_range.bear),
    )

    if analyst_low is None:
        analyst_low = max(0.01, analyst_base - default_half_band)
    if analyst_high is None:
        analyst_high = max(0.01, analyst_base + default_half_band)

    return ProjectionRange(
        bear=max(0.01, analyst_low),
        base=max(0.01, analyst_base),
        bull=max(0.01, analyst_high),
    )


def _blend_ranges(
    primary_range: ProjectionRange,
    secondary_range: ProjectionRange,
    secondary_weight: float,
) -> ProjectionRange:
    primary_weight = 1.0 - secondary_weight
    return ProjectionRange(
        bear=(primary_range.bear * primary_weight) + (secondary_range.bear * secondary_weight),
        base=(primary_range.base * primary_weight) + (secondary_range.base * secondary_weight),
        bull=(primary_range.bull * primary_weight) + (secondary_range.bull * secondary_weight),
    )


def _ordered_range(rng: ProjectionRange) -> ProjectionRange:
    values = sorted([max(0.01, rng.bear), max(0.01, rng.base), max(0.01, rng.bull)])
    return ProjectionRange(bear=values[0], base=values[1], bull=values[2])


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if not isfinite(numeric) or numeric <= 0:
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        numeric = int(value)
        if numeric < 0:
            return None
        return numeric
    except (TypeError, ValueError):
        return None
