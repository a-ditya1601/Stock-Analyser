from __future__ import annotations

from equity_reporter.models import ProjectionScenarios
from equity_reporter.reporting.narrative import NarrativeBundle
from equity_reporter.reporting.pdf_builder import ResearchPDF, _add_page_2_fundamental_risk


def test_page2_includes_peer_relative_valuation_table(monkeypatch) -> None:
    captured_subheadings: list[str] = []
    captured_tables: list[list[list[str]]] = []

    def _capture_subheading(_pdf: ResearchPDF, title: str) -> None:
        captured_subheadings.append(title)

    def _capture_table(_pdf: ResearchPDF, headers, rows, col_widths, **kwargs) -> None:  # noqa: ANN001
        _ = headers, col_widths, kwargs
        captured_tables.append(rows)

    monkeypatch.setattr("equity_reporter.reporting.pdf_builder._draw_subheading", _capture_subheading)
    monkeypatch.setattr("equity_reporter.reporting.pdf_builder._draw_table", _capture_table)

    pdf = ResearchPDF()
    signals = {
        "fundamental_signals": {},
        "peer_signals": {},
        "peer_list": ["AAA", "BBB", "CCC"],
        "beta_benchmark": "^NSEI",
    }
    narratives = NarrativeBundle()

    _add_page_2_fundamental_risk(
        pdf=pdf,
        signals=signals,
        projections=ProjectionScenarios(),
        narratives=narratives,
        currency_code="USD",
    )

    assert "Peer Relative Valuation" in captured_subheadings
    core_rows = captured_tables[0]
    assert any(row[0] == "Operating Margin" for row in core_rows)
    assert any(row[0] == "Return on Capital Employed" for row in core_rows)
    peer_rows = captured_tables[2]
    assert peer_rows[0][0] == "Automated Peer Basket"
    assert any(row[0] == "PE / Sector PE Ratio" for row in peer_rows)
    assert any(row[0] == "Forward P/E Relative" for row in peer_rows)
