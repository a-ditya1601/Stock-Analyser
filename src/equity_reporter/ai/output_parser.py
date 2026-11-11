from __future__ import annotations

import re

from equity_reporter.ai.input_packer import DATA_UNAVAILABLE

SECTION_SPECS: tuple[tuple[str, str], ...] = (
    ("fundamental_valuation", "1. Fundamental Deep-Dive & Valuation"),
    ("technical_volume", "2. Technical Posture & Volume Accumulation"),
    ("volatility_risk", "3. Volatility & Risk Matrix"),
    ("tactical_execution", "4. Tactical Execution Plan"),
    ("manual_trade_management", "5. Manual Trade Management & Invalidation Rules"),
    ("scenario_modeling", "6. Scenario Modeling & Price Action Matrix"),
    ("macro_stress_test", "7. Macro Stress Test"),
    ("sector_relativity", "8. Sector Relativity (Conditional)"),
    ("executive_summary_verdict", "9. Executive Summary & Verdict"),
)

_SECTION_KEY_BY_NUMBER: dict[int, str] = {
    index + 1: key for index, (key, _) in enumerate(SECTION_SPECS)
}

_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(\d+)\s*[.)-]?\s*(.+?)\s*(?:\*\*)?\s*$"
)


def parse_ai_analysis_sections(text: str | None) -> dict[str, str]:
    cleaned_text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not cleaned_text.strip():
        return {}

    sections: dict[str, list[str]] = {key: [] for key, _ in SECTION_SPECS}
    active_key: str | None = None

    for raw_line in cleaned_text.split("\n"):
        line = raw_line.rstrip()
        matched = _HEADING_RE.match(line)
        if matched:
            section_number = _to_int(matched.group(1))
            if section_number in _SECTION_KEY_BY_NUMBER:
                active_key = _SECTION_KEY_BY_NUMBER[section_number]
                continue

        if active_key is None:
            continue
        sections[active_key].append(line)

    output: dict[str, str] = {}
    for key, values in sections.items():
        text_block = _normalize_block("\n".join(values))
        if text_block:
            output[key] = text_block
    return output


def merge_analysis_sections(
    parsed_sections: dict[str, str] | None,
    fallback_sections: dict[str, str] | None,
) -> dict[str, str]:
    parsed = parsed_sections or {}
    fallback = fallback_sections or {}
    merged: dict[str, str] = {}

    for key, _ in SECTION_SPECS:
        parsed_value = _normalize_block(parsed.get(key, ""))
        if parsed_value:
            merged[key] = parsed_value
            continue

        fallback_value = _normalize_block(fallback.get(key, ""))
        if fallback_value:
            merged[key] = fallback_value
            continue

        merged[key] = DATA_UNAVAILABLE

    return merged


def _normalize_block(value: str) -> str:
    lines = [line.rstrip() for line in (value or "").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except Exception:
        return None
