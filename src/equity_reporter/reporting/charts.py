from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from matplotlib.lines import Line2D
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from equity_reporter.config import DEFAULT_CHART_LOOKBACK_DAYS
from equity_reporter.models import MarketSnapshot, ProjectionScenarios
from equity_reporter.utils.errors import ChartRenderError

TEMP_CHART_DIR_NAME = "_temp_charts"
SMA50_COLOR = "#1565C0"
SMA200_COLOR = "#C62828"
FIB_COLORS = {
    "fib_0_382": "#FB8C00",
    "fib_0_500": "#8E24AA",
    "fib_0_618": "#2E7D32",
}
SUPPORT_LINE_COLOR = "#00897B"
RESISTANCE_LINE_COLOR = "#D84315"
POC_LINE_COLOR = "#3949AB"


def render_chart(
    snapshot: MarketSnapshot,
    signals: dict[str, Any],
    output_dir: Path,
    chart_history: pd.DataFrame | None = None,
    projections: ProjectionScenarios | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / TEMP_CHART_DIR_NAME
    temp_dir.mkdir(parents=True, exist_ok=True)

    chart_path = temp_dir / _chart_filename(snapshot.ticker)

    full_frame = _prepare_chart_source_frame(chart_history, snapshot.history)
    if full_frame.empty:
        raise ChartRenderError(f"No valid OHLCV rows available to render chart for {snapshot.ticker}.")

    enriched = full_frame.copy()
    # Strict windows avoid visually misleading partial-window SMAs.
    enriched["SMA50"] = enriched["Close"].rolling(window=50, min_periods=50).mean()
    enriched["SMA200"] = enriched["Close"].rolling(window=200, min_periods=200).mean()

    frame = enriched.tail(DEFAULT_CHART_LOOKBACK_DAYS).copy()
    if frame.empty:
        raise ChartRenderError(f"No valid OHLCV rows available to render chart for {snapshot.ticker}.")

    add_plots: list[Any] = []
    legend_flags = {
        "sma50": False,
        "sma200": False,
        "fib": False,
        "support": False,
        "resistance": False,
        "poc": False,
    }
    if frame["SMA50"].notna().any():
        add_plots.append(mpf.make_addplot(frame["SMA50"], color=SMA50_COLOR, width=1.25, panel=0))
        legend_flags["sma50"] = True
    if frame["SMA200"].notna().any():
        add_plots.append(mpf.make_addplot(frame["SMA200"], color=SMA200_COLOR, width=1.30, panel=0))
        legend_flags["sma200"] = True

    fib_levels, fib_colors = _extract_fibonacci_levels(signals)
    legend_flags["fib"] = bool(fib_levels)
    projection_levels, projection_colors, projection_flags = _extract_projection_levels(projections)
    legend_flags.update(projection_flags)
    overlay_levels = fib_levels + projection_levels
    overlay_colors = fib_colors + projection_colors
    price_ylim = _build_price_ylim(frame, overlay_levels)
    hlines = None
    if overlay_levels:
        hlines = {
            "hlines": overlay_levels,
            "colors": overlay_colors,
            "linestyle": "--",
            "linewidths": 0.95,
            "alpha": 0.9,
        }

    style = mpf.make_mpf_style(
        base_mpf_style="classic",
        marketcolors=mpf.make_marketcolors(
            up="#2E7D32",
            down="#C62828",
            edge="inherit",
            wick="inherit",
            volume="inherit",
            ohlc="inherit",
        ),
        facecolor="#FFFFFF",
        figcolor="#FFFFFF",
        gridstyle=":",
        gridcolor="#D7DCE5",
        y_on_right=True,
        rc={
            "font.size": 10,
            "axes.titlesize": 20,
            "axes.labelsize": 12,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "axes.linewidth": 0.8,
            "axes.edgecolor": "#4B5563",
        },
    )

    try:
        fig, axes = mpf.plot(
            frame,
            type="candle",
            style=style,
            addplot=add_plots if add_plots else None,
            volume=True,
            ylabel="Price",
            ylabel_lower="Volume",
            title=f"{snapshot.ticker} - 6M Price Action",
            hlines=hlines,
            ylim=price_ylim,
            xrotation=0,
            datetime_format="%b %Y",
            show_nontrading=False,
            panel_ratios=(3, 1),
            figratio=(16, 9),
            figscale=1.0,
            update_width_config=_build_width_config(len(frame)),
            tight_layout=False,
            returnfig=True,
        )
        legend = _add_external_legend(fig, legend_flags)
        fig.subplots_adjust(bottom=0.24)
        savefig_kwargs: dict[str, Any] = {
            "dpi": 220,
            "bbox_inches": "tight",
            "pad_inches": 0.18,
        }
        if legend is not None:
            savefig_kwargs["bbox_extra_artists"] = [legend]
        fig.savefig(str(chart_path), **savefig_kwargs)
        plt.close(fig)
    except Exception as exc:  # pragma: no cover - rendering backend dependent.
        _safe_unlink(chart_path)
        raise ChartRenderError(f"Unable to render chart for {snapshot.ticker}: {exc}") from exc

    if not chart_path.exists():
        raise ChartRenderError(f"Chart file was not created for {snapshot.ticker}.")
    return chart_path


def cleanup_temp_chart(chart_path: Path | None) -> None:
    if chart_path is None:
        return
    if chart_path.parent.name != TEMP_CHART_DIR_NAME:
        return

    _safe_unlink(chart_path)


def _prepare_chart_source_frame(chart_history: pd.DataFrame | None, fallback_history: pd.DataFrame) -> pd.DataFrame:
    primary = _prepare_chart_frame(chart_history) if chart_history is not None else pd.DataFrame()
    if not primary.empty:
        return primary
    return _prepare_chart_frame(fallback_history)


def _prepare_chart_frame(history: pd.DataFrame | None) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    frame = history.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        try:
            frame.index = pd.to_datetime(frame.index, errors="coerce")
        except Exception:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    frame = frame[~frame.index.isna()]
    if frame.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert(None)

    required = ["Open", "High", "Low", "Close", "Volume"]
    for column in required:
        if column not in frame.columns:
            frame[column] = pd.NA
        series = frame[column]
        if isinstance(series, pd.DataFrame):
            if series.empty:
                frame[column] = pd.Series(dtype="float64", index=frame.index)
            else:
                frame[column] = series.iloc[:, 0]
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"], how="any")
    frame["Volume"] = frame["Volume"].fillna(0.0).clip(lower=0.0)
    return frame[required]


def _extract_fibonacci_levels(signals: dict[str, Any]) -> tuple[list[float], list[str]]:
    levels: list[float] = []
    colors: list[str] = []
    for key in ("fib_0_382", "fib_0_500", "fib_0_618"):
        value = _to_float(signals.get(key))
        if value is None:
            continue
        levels.append(value)
        colors.append(FIB_COLORS.get(key, "#555555"))
    return levels, colors


def _extract_projection_levels(projections: ProjectionScenarios | None) -> tuple[list[float], list[str], dict[str, bool]]:
    flags = {"support": False, "resistance": False, "poc": False}
    if projections is None:
        return [], [], flags

    levels: list[float] = []
    colors: list[str] = []
    for item in projections.support_levels[:3]:
        if _append_level(levels, colors, _level_price(item), SUPPORT_LINE_COLOR):
            flags["support"] = True
    for item in projections.resistance_levels[:3]:
        if _append_level(levels, colors, _level_price(item), RESISTANCE_LINE_COLOR):
            flags["resistance"] = True
    if _append_level(levels, colors, _to_float(projections.volume_profile_poc), POC_LINE_COLOR):
        flags["poc"] = True
    return levels, colors, flags


def _level_price(item: Any) -> float | None:
    if isinstance(item, dict):
        return _to_float(item.get("price"))
    return None


def _append_level(levels: list[float], colors: list[str], value: float | None, color: str) -> bool:
    if value is None:
        return False
    if any(abs(existing - value) / max(abs(value), 0.01) <= 0.001 for existing in levels):
        return False
    levels.append(value)
    colors.append(color)
    return True


def _build_legend_handles(flags: dict[str, bool]) -> list[Line2D]:
    specs = (
        ("sma50", "50-Day SMA", SMA50_COLOR, "-"),
        ("sma200", "200-Day SMA", SMA200_COLOR, "-"),
        ("fib", "Fibonacci Retracements", "#6B7280", "--"),
        ("support", "Support Clusters", SUPPORT_LINE_COLOR, "--"),
        ("resistance", "Resistance Clusters", RESISTANCE_LINE_COLOR, "--"),
        ("poc", "Volume POC", POC_LINE_COLOR, "--"),
    )
    return [
        Line2D([0], [0], color=color, linestyle=linestyle, linewidth=1.4, label=label)
        for key, label, color, linestyle in specs
        if flags.get(key)
    ]


def _add_external_legend(fig: Any, flags: dict[str, bool]) -> Any | None:
    handles = _build_legend_handles(flags)
    if not handles:
        return None
    return fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.015),
        ncol=min(len(handles), 4),
        frameon=False,
        fontsize=8,
        handlelength=2.4,
        columnspacing=1.2,
    )


def _build_width_config(row_count: int) -> dict[str, float]:
    if row_count <= 45:
        candle_width = 0.85
        volume_width = 0.80
    elif row_count <= 90:
        candle_width = 0.70
        volume_width = 0.62
    else:
        candle_width = 0.58
        volume_width = 0.52

    return {
        "candle_width": candle_width,
        "candle_linewidth": 0.55,
        "volume_width": volume_width,
        "volume_linewidth": 0.4,
    }


def _build_price_ylim(frame: pd.DataFrame, fib_levels: list[float]) -> tuple[float, float] | None:
    low = pd.to_numeric(frame.get("Low"), errors="coerce")
    high = pd.to_numeric(frame.get("High"), errors="coerce")
    sma50 = pd.to_numeric(frame.get("SMA50"), errors="coerce")
    sma200 = pd.to_numeric(frame.get("SMA200"), errors="coerce")

    floor_candidates = [
        _series_min(low),
        _series_min(sma50),
        _series_min(sma200),
        _min_positive(fib_levels),
    ]
    cap_candidates = [
        _series_max(high),
        _series_max(sma50),
        _series_max(sma200),
        _max_positive(fib_levels),
    ]

    floor = _first_valid_min(floor_candidates)
    cap = _first_valid_max(cap_candidates)
    if floor is None or cap is None or cap <= floor:
        return None

    pad = max((cap - floor) * 0.06, 0.5)
    return (max(0.01, floor - pad), cap + pad)


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        if numeric <= 0:
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def _series_min(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    non_null = series.dropna()
    if non_null.empty:
        return None
    return float(non_null.min())


def _series_max(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    non_null = series.dropna()
    if non_null.empty:
        return None
    return float(non_null.max())


def _min_positive(values: list[float]) -> float | None:
    valid = [value for value in values if value > 0]
    if not valid:
        return None
    return float(min(valid))


def _max_positive(values: list[float]) -> float | None:
    valid = [value for value in values if value > 0]
    if not valid:
        return None
    return float(max(valid))


def _first_valid_min(candidates: list[float | None]) -> float | None:
    valid = [value for value in candidates if value is not None]
    if not valid:
        return None
    return float(min(valid))


def _first_valid_max(candidates: list[float | None]) -> float | None:
    valid = [value for value in candidates if value is not None]
    if not valid:
        return None
    return float(max(valid))


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        return


def _chart_filename(ticker: str) -> str:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    token = uuid4().hex[:8]
    safe_ticker = ticker.replace(".", "_")
    return f"{safe_ticker}_{stamp}_{token}.png"
