from __future__ import annotations

from equity_reporter.models import ProjectionScenarios
from equity_reporter.reporting.charts import _build_legend_handles, _extract_projection_levels


def test_extract_projection_levels_includes_support_resistance_and_poc() -> None:
    projections = ProjectionScenarios(
        support_levels=[
            {"price": 95.0, "strength": 80},
            {"price": 90.0, "strength": 70},
        ],
        resistance_levels=[
            {"price": 110.0, "strength": 85},
            {"price": 115.0, "strength": 65},
        ],
        volume_profile_poc=101.5,
    )

    levels, colors, flags = _extract_projection_levels(projections)

    assert levels == [95.0, 90.0, 110.0, 115.0, 101.5]
    assert len(colors) == len(levels)
    assert flags == {"support": True, "resistance": True, "poc": True}


def test_build_legend_handles_creates_clean_proxy_labels() -> None:
    handles = _build_legend_handles(
        {
            "sma50": True,
            "sma200": True,
            "fib": True,
            "support": True,
            "resistance": True,
            "poc": True,
        }
    )

    assert [handle.get_label() for handle in handles] == [
        "50-Day SMA",
        "200-Day SMA",
        "Fibonacci Retracements",
        "Support Clusters",
        "Resistance Clusters",
        "Volume POC",
    ]
