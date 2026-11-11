from __future__ import annotations

from equity_reporter.models import ProjectionScenarios, ScoreCard
from equity_reporter.reporting.narrative import NarrativeBundle
from equity_reporter.reporting.pdf_builder import (
    ResearchPDF,
    _add_page_4_comprehensive_analysis,
    _draw_structured_analysis_text,
)


def test_structured_ai_text_spills_to_multiple_pages_when_long() -> None:
    pdf = ResearchPDF()
    pdf.add_page()

    sections = []
    for index in range(1, 10):
        body = " ".join(
            [
                f"This is a long analysis paragraph for section {index} with detailed cross-metric commentary."
                for _ in range(70)
            ]
        )
        sections.append(f"## {index}. Section {index}\n{body}")
    long_text = "\n\n".join(sections)

    _draw_structured_analysis_text(pdf, long_text)

    assert pdf.page_no() >= 2


def test_page4_preserves_multiline_ai_text_for_section_parser(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _capture_text(_pdf: ResearchPDF, text: str, fallback_sections=None) -> None:  # noqa: ANN001
        captured["text"] = text

    monkeypatch.setattr(
        "equity_reporter.reporting.pdf_builder._draw_structured_analysis_text",
        _capture_text,
    )

    pdf = ResearchPDF()
    scorecard = ScoreCard(
        final_score=55.0,
        verdict="HOLD / NEUTRAL",
        data_coverage_pct=80.0,
        category_scores={"fundamental": 60.0, "technical": 52.0, "volume_risk": 48.0},
    )
    projections = ProjectionScenarios()
    narratives = NarrativeBundle()
    ai_text = (
        "## 1. Fundamental Deep-Dive & Valuation\n"
        "AI unique marker one.\n\n"
        "## 2. Technical Posture & Volume Accumulation\n"
        "AI unique marker two.\n"
    )

    _add_page_4_comprehensive_analysis(
        pdf,
        scorecard,
        projections,
        narratives,
        currency_code="USD",
        ai_analysis_text=ai_text,
        ai_analysis_status="Applied",
        ai_analysis_note="debug",
    )

    assert "AI unique marker one." in captured["text"]
    assert "AI unique marker two." in captured["text"]
    assert "\n## 2. Technical Posture & Volume Accumulation\n" in captured["text"]


def test_page4_renders_sector_relativity_section(monkeypatch) -> None:
    captured_lines: list[str] = []

    def _capture_wrapped_text(_pdf: ResearchPDF, text: str, line_height: float) -> None:  # noqa: ANN001
        _ = line_height
        captured_lines.append(text)

    monkeypatch.setattr(
        "equity_reporter.reporting.pdf_builder._write_wrapped_multiline",
        _capture_wrapped_text,
    )
    monkeypatch.setattr(
        "equity_reporter.reporting.pdf_builder._draw_structured_section_body",
        lambda *_args, **_kwargs: None,
    )

    pdf = ResearchPDF()
    pdf.add_page()
    ai_text = "\n\n".join(
        [
            "## 1. Fundamental Deep-Dive & Valuation\nSection one body.",
            "## 2. Technical Posture & Volume Accumulation\nSection two body.",
            "## 3. Volatility & Risk Matrix\nSection three body.",
            "## 4. Tactical Execution Plan\nSection four body.",
            "## 5. Manual Trade Management & Invalidation Rules\nSection five body.",
            "## 6. Scenario Modeling & Price Action Matrix\nSection six body.",
            "## 7. Macro Stress Test\nSection seven body.",
            "## 8. Sector Relativity (Conditional)\nSection eight body.",
            "## 9. Executive Summary & Verdict\nSection nine body.",
        ]
    )

    _draw_structured_analysis_text(pdf, ai_text)

    assert "1. Fundamental Deep-Dive & Valuation" in captured_lines
    assert "8. Sector Relativity (Conditional)" in captured_lines
    assert "9. Executive Summary & Verdict" in captured_lines
