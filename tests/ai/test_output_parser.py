from __future__ import annotations

from equity_reporter.ai.input_packer import DATA_UNAVAILABLE
from equity_reporter.ai.output_parser import merge_analysis_sections, parse_ai_analysis_sections


def test_output_parser_extracts_numbered_sections() -> None:
    text = """
## 1. Fundamental Deep-Dive & Valuation
Valuation is elevated but growth remains solid.

## 2. Technical Posture & Volume Accumulation
SMA trend is supportive and OBV confirms accumulation.

## 9. Executive Summary & Verdict
Strong setup with trend tailwind.
""".strip()

    parsed = parse_ai_analysis_sections(text)

    assert "growth remains solid" in parsed["fundamental_valuation"]
    assert "OBV confirms accumulation" in parsed["technical_volume"]
    assert parsed["executive_summary_verdict"].startswith("Strong setup")


def test_output_parser_merge_autofills_missing_sections() -> None:
    parsed = {
        "executive_summary_verdict": "AI summary.",
        "technical_volume": "AI technical section.",
    }
    fallback = {
        "executive_summary_verdict": "Fallback summary.",
        "fundamental_valuation": "Fallback fundamental.",
        "technical_volume": "Fallback technical.",
        "volatility_risk": "Fallback risk.",
        "tactical_execution": "Fallback execution.",
        "manual_trade_management": "Fallback manual trade plan.",
        "scenario_modeling": "Fallback scenarios.",
        "macro_stress_test": "Fallback macro.",
        "sector_relativity": "Fallback sector.",
    }

    merged = merge_analysis_sections(parsed, fallback)

    assert merged["executive_summary_verdict"] == "AI summary."
    assert merged["technical_volume"] == "AI technical section."
    assert merged["fundamental_valuation"] == "Fallback fundamental."
    assert merged["manual_trade_management"] == "Fallback manual trade plan."
    assert merged["sector_relativity"] == "Fallback sector."


def test_output_parser_merge_defaults_to_data_unavailable_without_fallback() -> None:
    merged = merge_analysis_sections({}, {})
    assert all(value == DATA_UNAVAILABLE for value in merged.values())
