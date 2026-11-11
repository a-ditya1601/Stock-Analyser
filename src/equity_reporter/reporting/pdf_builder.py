from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

from equity_reporter.ai.output_parser import SECTION_SPECS, merge_analysis_sections, parse_ai_analysis_sections
from equity_reporter.config import CATEGORY_METRIC_WEIGHTS, CATEGORY_WEIGHTS, PROJECTION_HORIZON_MONTHS, VERDICT_TIERS
from equity_reporter.models import MetricSignal, MarketSnapshot, ProjectionScenarios, ScoreCard, SignalLabel
from equity_reporter.reporting.narrative import NarrativeBundle, build_narratives

DISCLAIMER_TEXT = (
    "This report is algorithmically generated from public market data for educational and informational purposes "
    "only and does not constitute financial, investment, or trading advice."
)

DATA_UNAVAILABLE = "Data Unavailable"

COLOR_NAVY = (12, 38, 74)
COLOR_NAVY_DARK = (8, 28, 56)
COLOR_HEADER_BG = (222, 231, 244)
COLOR_ROW_A = (248, 250, 253)
COLOR_ROW_B = (238, 242, 248)
COLOR_BORDER = (77, 108, 150)
COLOR_TEXT_DARK = (20, 24, 28)
COLOR_TEXT_LIGHT = (255, 255, 255)

CURRENCY_SYMBOL_BY_CODE: dict[str, str] = {
    "USD": "$",
    "INR": "₹",
    "EUR": "EUR ",
    "GBP": "GBP ",
    "JPY": "JPY ",
    "CAD": "CAD ",
    "AUD": "AUD ",
}
UNICODE_FONT_FAMILY = "DejaVuSans"
PDF_PAGE4_SECTION_SPECS: tuple[tuple[str, str], ...] = tuple(
    (key, title) for key, title in SECTION_SPECS
)


class ResearchPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.base_font_family = "Helvetica"
        self._enable_unicode_font_family()
        self.set_auto_page_break(auto=True, margin=14)
        self.set_margins(10, 10, 10)

    def footer(self) -> None:
        self.set_y(-7)
        self.set_font(self.base_font_family, "", 7)
        self.set_text_color(100, 100, 100)
        self.cell(0, 4, f"Page {self.page_no()}", align="R")

    def _enable_unicode_font_family(self) -> None:
        font_paths = _locate_unicode_font_paths()
        if not font_paths:
            return

        try:
            self.add_font(UNICODE_FONT_FAMILY, "", str(font_paths[""]))
            self.add_font(UNICODE_FONT_FAMILY, "B", str(font_paths["B"]))
            self.add_font(UNICODE_FONT_FAMILY, "I", str(font_paths["I"]))
            self.add_font(UNICODE_FONT_FAMILY, "BI", str(font_paths["BI"]))
            self.base_font_family = UNICODE_FONT_FAMILY
        except Exception:
            return


def render_pdf(
    snapshot: MarketSnapshot,
    signals: dict[str, Any],
    scorecard: ScoreCard,
    projections: ProjectionScenarios,
    chart_path: Path,
    output_path: Path,
    ai_analysis_text: str | None = None,
    ai_analysis_status: str | None = None,
    ai_analysis_note: str | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    narratives = build_narratives(scorecard, signals)
    currency_code = _resolve_currency_code(snapshot)

    pdf = ResearchPDF()
    _add_page_1_tear_sheet(pdf, snapshot, signals, scorecard, projections, chart_path, currency_code)
    _add_page_2_fundamental_risk(pdf, signals, projections, narratives, currency_code)
    _add_page_3_technical_flow(pdf, signals, narratives)
    _add_page_4_comprehensive_analysis(
        pdf,
        scorecard,
        projections,
        narratives,
        currency_code,
        ai_analysis_text=ai_analysis_text,
        ai_analysis_status=ai_analysis_status,
        ai_analysis_note=ai_analysis_note,
    )
    _add_page_5_methodology(pdf, scorecard)

    pdf.output(str(output_path))
    return output_path


def _add_page_1_tear_sheet(
    pdf: ResearchPDF,
    snapshot: MarketSnapshot,
    signals: dict[str, Any],
    scorecard: ScoreCard,
    projections: ProjectionScenarios,
    chart_path: Path,
    currency_code: str,
) -> None:
    pdf.add_page()

    _draw_tearsheet_header(pdf, snapshot, scorecard, currency_code)
    _draw_verdict_box(pdf, scorecard)
    _draw_chart_centerpiece(pdf, chart_path)
    _draw_projections_table(pdf, projections, currency_code, title="Timeframe Projections")
    pdf.ln(3)
    _draw_risk_sentiment_panel(pdf, signals, projections)


def _add_page_2_fundamental_risk(
    pdf: ResearchPDF,
    signals: dict[str, Any],
    projections: ProjectionScenarios,
    narratives: NarrativeBundle,
    currency_code: str,
) -> None:
    pdf.add_page()
    _section_title(pdf, "Fundamental Health & Risk Profile")

    core_rows = _build_core_fundamental_rows(signals, narratives.metric_notes, currency_code)
    _draw_subheading(pdf, "Core Fundamentals")
    _draw_table(
        pdf,
        headers=["Metric", "Value", "Signal", "Automated Note"],
        rows=core_rows,
        col_widths=[42, 30, 24, 94],
        max_lines=2,
    )

    pdf.ln(2)
    risk_rows = _build_advanced_risk_rows(signals, projections, narratives.metric_notes)
    _draw_subheading(pdf, "Advanced Risk & Volatility Profile")
    _draw_table(
        pdf,
        headers=["Metric", "Value", "Signal", "Automated Note"],
        rows=risk_rows,
        col_widths=[42, 30, 24, 94],
        max_lines=2,
    )

    pdf.ln(2)
    peer_rows = _build_peer_relative_rows(signals, narratives.metric_notes)
    _draw_subheading(pdf, "Peer Relative Valuation")
    _draw_table(
        pdf,
        headers=["Metric", "Value", "Signal", "Automated Note"],
        rows=peer_rows,
        col_widths=[42, 40, 24, 84],
        max_lines=3,
    )

    benchmark = signals.get("beta_benchmark")
    benchmark_text = str(benchmark) if benchmark else DATA_UNAVAILABLE
    pdf.ln(2)
    pdf.set_font(pdf.base_font_family, "I", 9)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.multi_cell(0, 5, f"* Beta Benchmark: {benchmark_text}")


def _add_page_3_technical_flow(pdf: ResearchPDF, signals: dict[str, Any], narratives: NarrativeBundle) -> None:
    pdf.add_page()
    _section_title(pdf, "Technical & Order Flow Breakdown")

    technical_rows = _build_technical_rows(signals, narratives.metric_notes)
    _draw_subheading(pdf, "Technical Indicators")
    _draw_table(
        pdf,
        headers=["Metric", "Value", "Signal", "Automated Note"],
        rows=technical_rows,
        col_widths=[44, 38, 24, 84],
        max_lines=3,
    )

    pdf.ln(2)
    flow_rows = _build_volume_momentum_rows(signals, narratives.metric_notes)
    _draw_subheading(pdf, "Volume & Momentum")
    _draw_table(
        pdf,
        headers=["Metric", "Value", "Signal", "Automated Note"],
        rows=flow_rows,
        col_widths=[44, 38, 24, 84],
        max_lines=3,
    )

    pdf.ln(2)
    fno_rows = _build_derivatives_sentiment_rows(signals, narratives.metric_notes)
    _draw_subheading(pdf, "Derivatives & Sentiment")
    _draw_table(
        pdf,
        headers=["Metric", "Value", "Signal", "Automated Note"],
        rows=fno_rows,
        col_widths=[44, 38, 24, 84],
        max_lines=3,
    )


def _add_page_4_comprehensive_analysis(
    pdf: ResearchPDF,
    scorecard: ScoreCard,
    projections: ProjectionScenarios,
    narratives: NarrativeBundle,
    currency_code: str,
    ai_analysis_text: str | None = None,
    ai_analysis_status: str | None = None,
    ai_analysis_note: str | None = None,
) -> None:
    pdf.add_page()
    _section_title(pdf, "Comprehensive Asset Analysis")

    analysis_status = _safe_text(ai_analysis_status)
    analysis_note = _safe_text(ai_analysis_note)
    analysis_text = _safe_multiline_text(ai_analysis_text)
    if analysis_text == DATA_UNAVAILABLE:
        analysis_text = _build_deterministic_comprehensive_text(scorecard, narratives)
        analysis_status = "Deterministic v2 (AI Fallback)"
        analysis_note = "AI narrative text was unavailable in this run, so deterministic narrative was used."
    fallback_sections = _build_deterministic_section_map(scorecard, narratives)

    _draw_subheading(pdf, "Narrative Source")
    pdf.set_font(pdf.base_font_family, "", 9)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    source_line = f"Narrative Source: {analysis_status}"
    if analysis_note != DATA_UNAVAILABLE:
        source_line = f"{source_line}. {analysis_note}"
    pdf.multi_cell(0, 5, source_line)
    pdf.ln(1)

    _draw_subheading(pdf, "Generated Narrative")
    _draw_structured_analysis_text(pdf, analysis_text, fallback_sections=fallback_sections)

    _draw_subheading(pdf, "Analyst Context")
    analyst_rows = [
        ["Analyst Mean Target", _fmt_currency(projections.analyst_target_mean, currency_code)],
        ["Analyst Low Target", _fmt_currency(projections.analyst_target_low, currency_code)],
        ["Analyst High Target", _fmt_currency(projections.analyst_target_high, currency_code)],
        ["Number of Analyst Opinions", _fmt_int(projections.analyst_opinions)],
        ["Analyst Blend Applied", "Yes" if projections.analyst_blend_applied else "No"],
        [
            "Blend Weights (2m | 4m | 6m)",
            (
                f"{_fmt_percent(projections.blend_weights.get('1-2 months'))} | "
                f"{_fmt_percent(projections.blend_weights.get('3-4 months'))} | "
                f"{_fmt_percent(projections.blend_weights.get('5-6 months'))}"
            ),
        ],
    ]
    _draw_kv_table(pdf, analyst_rows, key_width=74)

    pdf.ln(2)
    _draw_subheading(pdf, "Model Scores")
    model_rows = [
        ["Fundamental Score", _fmt_percent(scorecard.category_scores.get("fundamental"))],
        ["Technical Score", _fmt_percent(scorecard.category_scores.get("technical"))],
        ["Volume/Risk/F&O Score", _fmt_percent(scorecard.category_scores.get("volume_risk"))],
        ["Peer Relativity Score", _fmt_percent(scorecard.category_scores.get("peer_relativity"))],
        ["Final Confidence", _fmt_percent(scorecard.final_score)],
        ["Data Coverage", _fmt_percent(scorecard.data_coverage_pct)],
    ]
    _draw_kv_table(pdf, model_rows, key_width=74)


def _add_page_5_methodology(pdf: ResearchPDF, scorecard: ScoreCard) -> None:
    pdf.add_page()
    _section_title(pdf, "Scoring Methodology & Breakdown")

    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.set_font(pdf.base_font_family, "", 9)
    configured_metric_count = len(
        {metric_key for metric_group in CATEGORY_METRIC_WEIGHTS.values() for metric_key in metric_group}
    )
    category_weight_text = ", ".join(
        f"{_category_label(category)} {weight:.0f}"
        for category, weight in CATEGORY_WEIGHTS.items()
    )
    methodology_text = (
        "1) Each metric is scored from 0.0 to 1.0 using deterministic threshold rules.\n"
        "2) Category points are computed with top-level category weights "
        f"({category_weight_text}) and normalized metric weights within each category.\n"
        "3) Final Confidence % = total earned points / max possible points across available metrics x 100.\n"
        "4) Missing metrics are excluded from the confidence denominator, so missing fields are not auto-penalized.\n"
        f"5) Data Coverage % = available metric count / total configured metrics ({configured_metric_count}) x 100.\n"
        "6) Verdict is mapped from confidence bands using fixed deterministic thresholds."
    )
    pdf.multi_cell(0, 5, methodology_text)

    pdf.ln(2)
    _draw_subheading(pdf, "Projection Methodology")
    projection_methodology_text = (
        "The price projection engine uses a hybrid quantitative model rather than a fixed ATR-only band. "
        "Historical forward-return distributions produce the initial bear/base/bull quantiles for each horizon. "
        "When ATM implied volatility is available from options/F&O data, the 1-2 month range is heavily blended "
        "with the options expected move: Price x IV x sqrt(days to expiry / 365). "
        "The model then evaluates support/resistance confluence from swing highs/lows, Fibonacci levels, "
        "SMA20/50/200, Bollinger Bands, Ichimoku spans, Max Pain, and a lightweight Volume Profile. "
        "Volume Profile identifies the Point of Control and High Volume Nodes, which increase level strength. "
        "Targets are not hard-snapped to these levels; strong confluence zones act as gravity wells that softly "
        "pull raw statistical targets toward market structure while preserving the underlying distribution. "
        "Analyst targets, when available, are secondary inputs with capped influence by horizon. "
        "If historical samples, IV, or volume profile data are unavailable, the engine degrades gracefully to "
        "historical-return or ATR fallback ranges."
    )
    pdf.set_font(pdf.base_font_family, "", 9)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.multi_cell(0, 5, projection_methodology_text)

    pdf.ln(2)
    _draw_subheading(pdf, "Within-Category Metric Allocation")
    metric_weight_rows = [
        [_category_label(category), _format_metric_weight_block(metric_weights)]
        for category, metric_weights in CATEGORY_METRIC_WEIGHTS.items()
    ]
    _draw_kv_table(pdf, metric_weight_rows, key_width=54)

    pdf.ln(2)
    _draw_subheading(pdf, "Signal Label Guide")
    label_rows = [
        ["Bullish", "Positive/supportive signal under model thresholds."],
        ["Neutral", "Mixed or balanced reading with limited directional edge."],
        ["Warning", "Cautionary flag; elevated risk or less favorable setup."],
        ["Bearish", "Negative pressure under current model thresholds."],
        ["Info", "Informational context row; shown for completeness and may not drive core score."],
        ["Data Unavailable", "Source data was missing for this metric in the current run."],
    ]
    _draw_kv_table(pdf, label_rows, key_width=62)

    pdf.ln(2)
    _draw_subheading(pdf, "Category Weighting")
    weight_rows = [[_category_label(name), _fmt_percent(weight)] for name, weight in CATEGORY_WEIGHTS.items()]
    _draw_kv_table(pdf, weight_rows, key_width=84)

    pdf.ln(2)
    _draw_subheading(pdf, "Verdict Tiers")
    tier_rows = _build_verdict_tier_rows()
    _draw_kv_table(pdf, tier_rows, key_width=84)

    pdf.ln(3)
    pdf.set_fill_color(*COLOR_NAVY_DARK)
    pdf.set_text_color(*COLOR_TEXT_LIGHT)
    pdf.set_font(pdf.base_font_family, "B", 10)
    pdf.multi_cell(0, 6, DISCLAIMER_TEXT, border=1, fill=True)


def _draw_tearsheet_header(pdf: ResearchPDF, snapshot: MarketSnapshot, scorecard: ScoreCard, currency_code: str) -> None:
    company_name = snapshot.company_metadata.get("company_name") if snapshot.company_metadata else None
    title_name = company_name or snapshot.ticker
    as_of = (
        snapshot.fetched_at.astimezone().strftime("%Y-%m-%d %H:%M")
        if snapshot.fetched_at
        else datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    pdf.set_fill_color(*COLOR_NAVY)
    pdf.set_draw_color(*COLOR_BORDER)
    pdf.set_text_color(*COLOR_TEXT_LIGHT)

    pdf.set_font(pdf.base_font_family, "B", 16)
    pdf.cell(0, 10, f"{title_name} ({snapshot.ticker})", border=1, fill=True, ln=True)

    pdf.set_font(pdf.base_font_family, "", 9)
    pdf.cell(95, 7, f"Current Price: {_fmt_currency(snapshot.current_price, currency_code)}", border=1, fill=True)
    pdf.cell(95, 7, f"Report Date: {as_of}", border=1, fill=True, ln=True)
    pdf.cell(190, 7, f"Data Coverage: {_fmt_percent(scorecard.data_coverage_pct)}", border=1, fill=True, ln=True)
    history_note = getattr(snapshot, "history_note", "") or getattr(snapshot, "history_source", "")
    if history_note:
        pdf.cell(190, 6, f"Price History Source: {_safe_text(str(history_note))}", border=1, fill=True, ln=True)
    pdf.ln(3)


def _draw_verdict_box(pdf: ResearchPDF, scorecard: ScoreCard) -> None:
    pdf.set_draw_color(*COLOR_BORDER)
    pdf.set_fill_color(225, 235, 249)
    pdf.set_text_color(*COLOR_TEXT_DARK)

    pdf.set_font(pdf.base_font_family, "B", 11)
    pdf.cell(125, 8, "Final Verdict", border=1, fill=True)
    pdf.cell(65, 8, "Confidence", border=1, fill=True, ln=True)

    pdf.set_font(pdf.base_font_family, "B", 18)
    pdf.cell(125, 14, scorecard.verdict, border=1, fill=True)
    pdf.cell(65, 14, _fmt_percent(scorecard.final_score), border=1, fill=True, ln=True)
    pdf.ln(3)


def _draw_chart_centerpiece(pdf: ResearchPDF, chart_path: Path) -> None:
    pdf.set_font(pdf.base_font_family, "B", 10)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.cell(0, 6, "6-Month Candlestick Chart (Volume + SMA50/200 + Fibonacci)", ln=True)

    chart_h = 86.0
    y = pdf.get_y() + 1
    if chart_path.exists():
        pdf.image(str(chart_path), x=12, y=y, w=186, h=chart_h)
        pdf.set_y(y + chart_h + 3)
    else:
        pdf.set_font(pdf.base_font_family, "", 9)
        pdf.multi_cell(0, 5, f"Chart image: {DATA_UNAVAILABLE}")
        pdf.ln(2)


def _draw_projections_table(
    pdf: ResearchPDF,
    projections: ProjectionScenarios,
    currency_code: str,
    title: str,
) -> None:
    _draw_subheading(pdf, title)

    rows: list[list[str]] = []
    ordered_horizons = list(PROJECTION_HORIZON_MONTHS.keys()) + [
        key for key in projections.horizons.keys() if key not in PROJECTION_HORIZON_MONTHS
    ]
    for horizon in ordered_horizons:
        if horizon not in projections.horizons:
            continue
        rng = projections.horizons[horizon]
        rows.append(
            [
                horizon,
                _fmt_currency(rng.bear, currency_code),
                _fmt_currency(rng.base, currency_code),
                _fmt_currency(rng.bull, currency_code),
            ]
        )

    if not rows:
        rows = [[DATA_UNAVAILABLE, DATA_UNAVAILABLE, DATA_UNAVAILABLE, DATA_UNAVAILABLE]]

    _draw_table(
        pdf,
        headers=["Horizon", "Bear Case", "Base Case", "Bull Case"],
        rows=rows,
        col_widths=[46, 48, 48, 48],
        max_lines=1,
        line_height=4.2,
        body_font_size=8.8,
    )
    _draw_projection_method_note(pdf, projections, currency_code)


def _draw_projection_method_note(
    pdf: ResearchPDF,
    projections: ProjectionScenarios,
    currency_code: str,
) -> None:
    method = _safe_text(projections.methodology)
    confidence = _safe_text(projections.projection_confidence)
    support = _format_projection_levels(projections.support_levels, currency_code)
    resistance = _format_projection_levels(projections.resistance_levels, currency_code)
    fallback = _safe_text(projections.fallback_reason)

    lines = [
        f"Projection Method: {method}",
        f"Projection Confidence: {confidence}",
        f"Key Support: {support}",
        f"Key Resistance: {resistance}",
    ]
    if fallback != DATA_UNAVAILABLE:
        lines.append(f"Fallback Notes: {fallback}")

    pdf.set_font(pdf.base_font_family, "", 8.2)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.multi_cell(0, 4.4, "\n".join(lines))


def _format_projection_levels(levels: list[dict[str, Any]], currency_code: str) -> str:
    if not levels:
        return DATA_UNAVAILABLE
    formatted: list[str] = []
    for level in levels[:3]:
        price = _to_float(level.get("price")) if isinstance(level, dict) else None
        strength = _to_float(level.get("strength")) if isinstance(level, dict) else None
        if price is None:
            continue
        if strength is None:
            formatted.append(_fmt_currency(price, currency_code))
        else:
            formatted.append(f"{_fmt_currency(price, currency_code)} ({strength:.0f})")
    return " | ".join(formatted) if formatted else DATA_UNAVAILABLE


def _draw_risk_sentiment_panel(
    pdf: ResearchPDF,
    signals: dict[str, Any],
    projections: ProjectionScenarios,
) -> None:
    _draw_subheading(pdf, "Risk & Sentiment Panel")

    adx_value = _fmt_number(_to_float(signals.get("adx_14")))
    adx_signal = _as_signal_map(signals.get("technical_signals")).get("adx_trend_strength")
    if adx_signal is not None and adx_signal.label != SignalLabel.MISSING:
        adx_display = f"{adx_value} ({adx_signal.label.value.title()})"
    else:
        adx_display = adx_value

    _draw_table(
        pdf,
        headers=["1Y Daily Beta", "5Y Daily Beta", "ATR(14)", "ADX Trend Strength"],
        rows=[
            [
                _fmt_number(_to_float(signals.get("beta"))),
                _fmt_number(_to_float(signals.get("beta_5y"))),
                _fmt_number(_to_float(projections.atr_14)),
                adx_display,
            ]
        ],
        col_widths=[47.5, 47.5, 47.5, 47.5],
        max_lines=2,
        line_height=4.2,
        body_font_size=8.6,
    )


def _draw_table(
    pdf: ResearchPDF,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float],
    max_lines: int = 3,
    line_height: float = 4.2,
    body_font_size: float = 8.4,
) -> None:
    _draw_table_header(pdf, headers, col_widths)

    pdf.set_font(pdf.base_font_family, "", body_font_size)
    pdf.set_text_color(*COLOR_TEXT_DARK)

    pad_x = 0.7
    pad_y = 0.8
    for row_index, row in enumerate(rows):
        wrapped_cells = [
            _wrap_text(
                pdf,
                str(cell_value),
                _cell_text_width(pdf, col_widths[col_index], pad_x),
                max_lines=None,
            )
            for col_index, cell_value in enumerate(row)
        ]
        row_line_count = max(len(lines) for lines in wrapped_cells)
        row_height = max((line_height * row_line_count) + (2 * pad_y), 6.6)

        if _needs_page_break(pdf, row_height):
            pdf.add_page()
            _draw_table_header(pdf, headers, col_widths)
            pdf.set_font(pdf.base_font_family, "", body_font_size)
            pdf.set_text_color(*COLOR_TEXT_DARK)

        fill_color = COLOR_ROW_A if row_index % 2 == 0 else COLOR_ROW_B

        x_start = pdf.get_x()
        y_start = pdf.get_y()

        for col_index, lines in enumerate(wrapped_cells):
            x_cell = x_start + sum(col_widths[:col_index])
            text_block = "\n".join(lines)

            pdf.set_fill_color(*fill_color)
            pdf.rect(x_cell, y_start, col_widths[col_index], row_height, style="F")
            pdf.set_draw_color(*COLOR_BORDER)
            pdf.rect(x_cell, y_start, col_widths[col_index], row_height, style="D")

            pdf.set_xy(x_cell + pad_x, y_start + pad_y)
            pdf.multi_cell(
                col_widths[col_index] - (2.0 * pad_x),
                line_height,
                text_block,
                border=0,
                align="L",
                max_line_height=line_height,
            )
            pdf.set_xy(x_cell + col_widths[col_index], y_start)

        pdf.set_xy(x_start, y_start + row_height)


def _draw_table_header(pdf: ResearchPDF, headers: list[str], col_widths: list[float]) -> None:
    if _needs_page_break(pdf, 10):
        pdf.add_page()

    pdf.set_fill_color(*COLOR_HEADER_BG)
    pdf.set_draw_color(*COLOR_BORDER)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.set_font(pdf.base_font_family, "B", 9)

    for index, header in enumerate(headers):
        pdf.cell(col_widths[index], 7, header, border=1, fill=True)
    pdf.ln()


def _draw_subheading(pdf: ResearchPDF, title: str) -> None:
    if _needs_page_break(pdf, 9):
        pdf.add_page()

    pdf.set_fill_color(*COLOR_NAVY_DARK)
    pdf.set_text_color(*COLOR_TEXT_LIGHT)
    pdf.set_font(pdf.base_font_family, "B", 10)
    pdf.cell(0, 7, title, border=1, fill=True, ln=True)


def _draw_kv_table(pdf: ResearchPDF, rows: list[list[str]], key_width: float = 78) -> None:
    value_width = 190 - key_width
    table_rows = [[_safe_text(row[0]), _safe_text(row[1])] for row in rows]
    _draw_table(
        pdf,
        headers=["Field", "Value"],
        rows=table_rows,
        col_widths=[key_width, value_width],
        max_lines=2,
        line_height=4.2,
        body_font_size=8.8,
    )


def _draw_paragraph_block(pdf: ResearchPDF, title: str, paragraph: str) -> None:
    _draw_subheading(pdf, title)
    pdf.set_font(pdf.base_font_family, "", 9)
    pdf.set_text_color(*COLOR_TEXT_DARK)
    pdf.multi_cell(0, 5, paragraph)
    pdf.ln(1)


def _draw_structured_analysis_text(
    pdf: ResearchPDF,
    text: str,
    fallback_sections: dict[str, str] | None = None,
) -> None:
    parsed_sections = parse_ai_analysis_sections(text)
    merged_sections = merge_analysis_sections(parsed_sections, fallback_sections)

    for section_key, section_title in PDF_PAGE4_SECTION_SPECS:
        if _needs_page_break(pdf, 9):
            pdf.add_page()
        pdf.set_font(pdf.base_font_family, "B", 10.5)
        pdf.set_text_color(*COLOR_TEXT_DARK)
        _write_wrapped_multiline(pdf, section_title, line_height=6.0)
        pdf.ln(0.6)

        body = merged_sections.get(section_key, DATA_UNAVAILABLE)
        _draw_structured_section_body(pdf, body)
        pdf.ln(1.2)


def _draw_structured_section_body(pdf: ResearchPDF, body: str) -> None:
    normalized = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    has_content = False

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            if has_content:
                pdf.ln(1)
            continue

        has_content = True
        if line.startswith("* ") or line.startswith("- "):
            line = f"- {line[2:].strip()}"

        pdf.set_font(pdf.base_font_family, "", 9)
        pdf.set_text_color(*COLOR_TEXT_DARK)
        _write_wrapped_multiline(pdf, line, line_height=5.0)

    if not has_content:
        pdf.set_font(pdf.base_font_family, "", 9)
        pdf.set_text_color(*COLOR_TEXT_DARK)
        _write_wrapped_multiline(pdf, DATA_UNAVAILABLE, line_height=5.0)


def _write_wrapped_multiline(pdf: ResearchPDF, text: str, line_height: float) -> None:
    content_width = max(20.0, pdf.w - pdf.l_margin - pdf.r_margin - (2.0 * pdf.c_margin) - 0.4)
    wrapped = _wrap_text(pdf, text, content_width, max_lines=None)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, line_height, "\n".join(wrapped))


def _section_title(pdf: ResearchPDF, title: str) -> None:
    pdf.set_fill_color(*COLOR_NAVY)
    pdf.set_text_color(*COLOR_TEXT_LIGHT)
    pdf.set_draw_color(*COLOR_BORDER)
    pdf.set_font(pdf.base_font_family, "B", 13)
    pdf.cell(0, 9, title, border=1, fill=True, ln=True)
    pdf.ln(2)


def _build_core_fundamental_rows(
    signals: dict[str, Any],
    metric_notes: dict[str, str],
    currency_code: str,
) -> list[list[str]]:
    signal_map = _as_signal_map(signals.get("fundamental_signals"))
    sources = signals.get("fundamental_sources") if isinstance(signals.get("fundamental_sources"), dict) else {}
    fcf_label = "Free Cash Flow (TTM)" if "TTM" in str(sources.get("free_cash_flow") or "") else "Free Cash Flow"
    return [
        _metric_row("Forward P/E", signals.get("forward_pe"), signal_map.get("valuation_pe_trend"), metric_notes),
        _metric_row("Trailing P/E", signals.get("trailing_pe"), signal_map.get("valuation_pe_trend"), metric_notes),
        _metric_row(
            "Profit Margin",
            signals.get("profit_margin"),
            signal_map.get("profit_margin"),
            metric_notes,
            as_percent=True,
        ),
        _metric_row(
            "Operating Margin",
            signals.get("operating_margin"),
            signal_map.get("operating_margin"),
            metric_notes,
            as_percent=True,
        ),
        _metric_row(
            "Return on Equity",
            signals.get("return_on_equity"),
            signal_map.get("return_on_equity"),
            metric_notes,
            as_percent=True,
        ),
        _metric_row(
            "Return on Capital Employed",
            signals.get("return_on_capital_employed"),
            signal_map.get("return_on_capital_employed"),
            metric_notes,
            as_percent=True,
        ),
        _metric_row(
            "Debt to Equity",
            signals.get("debt_to_equity"),
            signal_map.get("debt_to_equity"),
            metric_notes,
            as_multiple=True,
        ),
        _metric_row("Current Ratio", signals.get("current_ratio"), signal_map.get("current_ratio"), metric_notes),
        _metric_row(
            "Quarterly Rev Growth",
            signals.get("quarterly_revenue_growth"),
            signal_map.get("quarterly_revenue_growth"),
            metric_notes,
            as_percent=True,
        ),
        _metric_row(
            fcf_label,
            signals.get("free_cash_flow"),
            signal_map.get("fcf_vs_debt"),
            metric_notes,
            as_currency=True,
            currency_code=currency_code,
        ),
        _metric_row(
            "Total Debt",
            signals.get("total_debt"),
            signal_map.get("fcf_vs_debt"),
            metric_notes,
            as_currency=True,
            currency_code=currency_code,
        ),
    ]


def _build_advanced_risk_rows(
    signals: dict[str, Any],
    projections: ProjectionScenarios,
    metric_notes: dict[str, str],
) -> list[list[str]]:
    signal_map = _as_signal_map(signals.get("fundamental_signals"))

    return [
        _metric_row("1Y Beta", signals.get("beta"), signal_map.get("beta_profile_fit"), metric_notes),
        _informational_row(
            "2Y Beta",
            _fmt_number(_to_float(signals.get("beta_2y"))),
            "Self-computed beta over trailing 2 years using benchmark daily returns.",
        ),
        _informational_row(
            "5Y Beta",
            _fmt_number(_to_float(signals.get("beta_5y"))),
            "Self-computed beta over trailing 5 years using benchmark daily returns.",
        ),
        _informational_row(
            "1M Beta",
            _fmt_number(_to_float(signals.get("beta_1m"))),
            "Self-computed beta over trailing 1 month using benchmark daily returns.",
        ),
        _informational_row(
            "Weekly Beta",
            _fmt_number(_to_float(signals.get("beta_weekly"))),
            "Self-computed beta using trailing 1-year weekly returns.",
        ),
        _informational_row("ATR(14)", _fmt_number(_to_float(projections.atr_14)), "Average True Range over 14 periods."),
        _informational_row(
            "Est. Monthly Swing",
            _fmt_number(_to_float(projections.monthly_swing)),
            "Estimated monthly move derived from ATR and trading-day scaling.",
        ),
    ]


def _build_technical_rows(signals: dict[str, Any], metric_notes: dict[str, str]) -> list[list[str]]:
    technical = _as_signal_map(signals.get("technical_signals"))
    fib_signal = signals.get("fibonacci_signal") if isinstance(signals.get("fibonacci_signal"), MetricSignal) else None

    sma_value = (
        f"{_fmt_number(_to_float(signals.get('sma_20')))} / "
        f"{_fmt_number(_to_float(signals.get('sma_50')))} / "
        f"{_fmt_number(_to_float(signals.get('sma_200')))}"
    )
    macd_value = f"{_fmt_number(_to_float(signals.get('macd')))} / {_fmt_number(_to_float(signals.get('macd_signal')))}"
    bb_value = (
        f"{_fmt_number(_to_float(signals.get('bb_lower')))} | "
        f"{_fmt_number(_to_float(signals.get('bb_middle')))} | "
        f"{_fmt_number(_to_float(signals.get('bb_upper')))}"
    )
    ichimoku = (
        f"{_fmt_number(_to_float(signals.get('ichimoku_span_a')))} / "
        f"{_fmt_number(_to_float(signals.get('ichimoku_span_b')))}"
    )
    fib_levels = (
        f"{_fmt_number(_to_float(signals.get('fib_0_382')))} | "
        f"{_fmt_number(_to_float(signals.get('fib_0_500')))} | "
        f"{_fmt_number(_to_float(signals.get('fib_0_618')))}"
    )

    return [
        _metric_row_text(
            "SMA20 / SMA50 / SMA200",
            sma_value,
            technical.get("sma_crossover"),
            "sma_crossover",
            metric_notes,
        ),
        _metric_row("RSI(14)", signals.get("rsi_14"), technical.get("rsi_14"), metric_notes),
        _metric_row_text("MACD / Signal", macd_value, technical.get("macd_crossover"), "macd_crossover", metric_notes),
        _metric_row_text(
            "Bollinger Bands (L|M|U)",
            bb_value,
            technical.get("bollinger_position"),
            "bollinger_position",
            metric_notes,
        ),
        _metric_row_text("Ichimoku Span A/B", ichimoku, technical.get("ichimoku_cloud"), "ichimoku_cloud", metric_notes),
        _metric_row_text(
            "Fib Levels (0.382|0.5|0.618)",
            fib_levels,
            fib_signal,
            "fibonacci_support_breakout",
            metric_notes,
        ),
    ]


def _build_volume_momentum_rows(signals: dict[str, Any], metric_notes: dict[str, str]) -> list[list[str]]:
    technical = _as_signal_map(signals.get("technical_signals"))
    volume = _as_signal_map(signals.get("volume_signals"))
    return [
        _metric_row(
            "OBV 30-Day Trend",
            signals.get("obv_30d_slope"),
            volume.get("obv_30d_trend"),
            metric_notes,
            as_percent=True,
            already_percent=False,
        ),
        _metric_row(
            "Relative Vol 10D/3M",
            signals.get("relative_volume_10d_3m"),
            volume.get("relative_volume_10d_3m"),
            metric_notes,
        ),
        _metric_row("ADX(14)", signals.get("adx_14"), technical.get("adx_trend_strength"), metric_notes),
    ]


def _build_derivatives_sentiment_rows(signals: dict[str, Any], metric_notes: dict[str, str]) -> list[list[str]]:
    volume = _as_signal_map(signals.get("volume_signals"))
    status = _safe_text(signals.get("fno_availability_status"))
    status_note = _safe_text(signals.get("fno_note"))
    iv_percentile = _to_float(signals.get("fno_iv_percentile"))
    atm_iv = _to_float(signals.get("fno_atm_iv"))
    if iv_percentile is not None:
        iv_value = f"IV Percentile {_fmt_percent(iv_percentile, already_percent=True)}"
    elif atm_iv is not None:
        iv_value = f"ATM IV {_fmt_percent(atm_iv, already_percent=True)}"
    else:
        iv_value = DATA_UNAVAILABLE

    expiry = _safe_text(signals.get("fno_expiry"))
    max_pain_note = "Options max pain for nearest expiry."
    if expiry != DATA_UNAVAILABLE:
        max_pain_note = f"Options max pain for nearest expiry ({expiry})."

    return [
        _informational_row("F&O Availability", _format_fno_status(status), status_note),
        _metric_row("PCR", signals.get("fno_pcr"), volume.get("pcr_sentiment"), metric_notes),
        _metric_row_text(
            "Futures OI Build-up",
            _safe_text(signals.get("fno_futures_oi_buildup")),
            volume.get("futures_oi_buildup"),
            "futures_oi_buildup",
            metric_notes,
        ),
        _metric_row(
            "Rollover %",
            signals.get("fno_rollover_pct"),
            volume.get("rollover_percentage"),
            metric_notes,
            as_percent=True,
            already_percent=True,
        ),
        _metric_row_text(
            "IV Percentile / ATM IV",
            iv_value,
            volume.get("iv_percentile"),
            "iv_percentile",
            metric_notes,
        ),
        _informational_row("Max Pain", _fmt_number(_to_float(signals.get("fno_max_pain"))), max_pain_note),
    ]


def _format_fno_status(status: str) -> str:
    normalized = (status or "").strip().lower().replace("-", "_").replace(" ", "_")
    labels = {
        "available": "Available",
        "no_derivatives": "No Listed F&O/Options",
        "fetch_failed": "Exists/Requested, Fetch Failed",
        "unavailable": DATA_UNAVAILABLE,
    }
    return labels.get(normalized, _safe_text(status))


def _build_peer_relative_rows(signals: dict[str, Any], metric_notes: dict[str, str]) -> list[list[str]]:
    peer_signals = _as_signal_map(signals.get("peer_signals"))
    raw_peer_list = signals.get("peer_list")
    if isinstance(raw_peer_list, (list, tuple, set)):
        peer_list_value = _safe_text(", ".join(str(item) for item in raw_peer_list))
    elif isinstance(raw_peer_list, str):
        peer_list_value = _safe_text(raw_peer_list)
    else:
        peer_list_value = DATA_UNAVAILABLE
    basket_row = _informational_row(
        "Automated Peer Basket",
        peer_list_value,
        "Auto-discovered peers used for relative valuation comparison.",
    )

    rows = [
        basket_row,
        _metric_row_text(
            "PE / Sector PE Ratio",
            _fmt_number(_to_float(signals.get("peer_pe_to_sector_pe_ratio"))),
            peer_signals.get("peer_pe_to_sector_pe_ratio"),
            "peer_pe_to_sector_pe_ratio",
            metric_notes,
        ),
        _metric_row_text(
            "Forward P/E Relative",
            _peer_triplet_value(
                target=signals.get("peer_target_forward_pe"),
                peer_avg=signals.get("peer_avg_forward_pe"),
                delta=signals.get("peer_forward_pe_premium_pct"),
            ),
            peer_signals.get("peer_forward_pe_premium"),
            "peer_forward_pe_premium",
            metric_notes,
        ),
        _metric_row_text(
            "P/S Relative",
            _peer_triplet_value(
                target=signals.get("peer_target_ps"),
                peer_avg=signals.get("peer_avg_ps"),
                delta=signals.get("peer_ps_premium_pct"),
            ),
            peer_signals.get("peer_ps_premium"),
            "peer_ps_premium",
            metric_notes,
        ),
        _metric_row_text(
            "Profit Margin Spread",
            _peer_triplet_value(
                target=signals.get("peer_target_margin"),
                peer_avg=signals.get("peer_avg_margin"),
                delta=signals.get("peer_margin_spread_pct"),
                target_fraction=True,
                peer_avg_fraction=True,
                delta_is_percent=True,
            ),
            peer_signals.get("peer_margin_spread"),
            "peer_margin_spread",
            metric_notes,
        ),
        _metric_row_text(
            "Revenue Growth Spread",
            _peer_triplet_value(
                target=signals.get("peer_target_growth"),
                peer_avg=signals.get("peer_avg_growth"),
                delta=signals.get("peer_growth_spread_pct"),
                target_fraction=True,
                peer_avg_fraction=True,
                delta_is_percent=True,
            ),
            peer_signals.get("peer_growth_spread"),
            "peer_growth_spread",
            metric_notes,
        ),
    ]

    return rows


def _metric_row(
    name: str,
    value: Any,
    signal: MetricSignal | None,
    metric_notes: dict[str, str],
    as_percent: bool = False,
    already_percent: bool = True,
    as_currency: bool = False,
    as_multiple: bool = False,
    currency_code: str = "USD",
) -> list[str]:
    if as_currency:
        value_text = _fmt_currency(_to_float(value), currency_code)
    elif as_multiple:
        numeric = _to_float(value)
        value_text = DATA_UNAVAILABLE if numeric is None else f"{numeric:.2f}x"
    elif as_percent:
        value_text = _fmt_percent(_to_float(value), already_percent=already_percent)
    else:
        value_text = _fmt_number(_to_float(value))
    metric_key = signal.key if signal is not None else None
    return _metric_row_text(name, value_text, signal, metric_key, metric_notes)


def _metric_row_text(
    name: str,
    value_text: str,
    signal: MetricSignal | None,
    metric_key: str | None,
    metric_notes: dict[str, str],
) -> list[str]:
    signal_text = _signal_label(signal)
    note = _resolve_metric_note(signal, metric_key, metric_notes)
    return [name, _safe_text(value_text), signal_text, _safe_text(note)]


def _informational_row(name: str, value_text: str, note: str) -> list[str]:
    signal_text = DATA_UNAVAILABLE if value_text == DATA_UNAVAILABLE else "Info"
    if value_text == DATA_UNAVAILABLE:
        note = DATA_UNAVAILABLE
    return [name, _safe_text(value_text), signal_text, _safe_text(note)]


def _peer_triplet_value(
    target: Any,
    peer_avg: Any,
    delta: Any,
    *,
    target_fraction: bool = False,
    peer_avg_fraction: bool = False,
    delta_is_percent: bool = True,
) -> str:
    target_value = _to_float(target)
    peer_avg_value = _to_float(peer_avg)
    delta_value = _to_float(delta)

    if target_fraction:
        target_text = _fmt_percent(target_value, already_percent=False)
    else:
        target_text = _fmt_number(target_value)

    if peer_avg_fraction:
        peer_text = _fmt_percent(peer_avg_value, already_percent=False)
    else:
        peer_text = _fmt_number(peer_avg_value)

    if delta_is_percent:
        delta_text = _fmt_percent(delta_value, already_percent=True)
    else:
        delta_text = _fmt_number(delta_value)

    if DATA_UNAVAILABLE in {target_text, peer_text, delta_text}:
        return DATA_UNAVAILABLE
    return f"Tgt {target_text} | Avg {peer_text} | Delta {delta_text}"


def _signal_label(signal: MetricSignal | None) -> str:
    if signal is None or signal.label == SignalLabel.MISSING:
        return DATA_UNAVAILABLE
    return signal.label.value.title()


def _resolve_metric_note(
    signal: MetricSignal | None,
    metric_key: str | None,
    metric_notes: dict[str, str],
) -> str:
    if metric_key and metric_key in metric_notes:
        return metric_notes[metric_key]
    if signal is None or signal.label == SignalLabel.MISSING:
        return DATA_UNAVAILABLE
    return signal.note or "System-generated metric note."


def _build_deterministic_section_map(scorecard: ScoreCard, narratives: NarrativeBundle) -> dict[str, str]:
    fundamental_para = _synthesize_paragraph(
        prefix=narratives.category_notes.get("fundamental", "Fundamental posture summary is unavailable."),
        notes=[
            narratives.metric_notes.get("valuation_pe_trend"),
            narratives.metric_notes.get("profit_margin"),
            narratives.metric_notes.get("operating_margin"),
            narratives.metric_notes.get("return_on_equity"),
            narratives.metric_notes.get("return_on_capital_employed"),
            narratives.metric_notes.get("quarterly_revenue_growth"),
            narratives.metric_notes.get("fcf_vs_debt"),
        ],
    )
    technical_para = _synthesize_paragraph(
        prefix=narratives.category_notes.get("technical", "Technical posture summary is unavailable."),
        notes=[
            narratives.metric_notes.get("sma_crossover"),
            narratives.metric_notes.get("fibonacci_support_breakout"),
            narratives.metric_notes.get("ichimoku_cloud"),
            narratives.metric_notes.get("adx_trend_strength"),
            narratives.metric_notes.get("macd_crossover"),
        ],
    )
    flow_para = _synthesize_paragraph(
        prefix=narratives.category_notes.get("volume_risk", "Order-flow posture summary is unavailable."),
        notes=[
            narratives.metric_notes.get("obv_30d_trend"),
            narratives.metric_notes.get("relative_volume_10d_3m"),
            narratives.metric_notes.get("futures_oi_buildup"),
            narratives.metric_notes.get("rollover_percentage"),
            narratives.metric_notes.get("pcr_sentiment"),
            narratives.metric_notes.get("iv_percentile"),
            narratives.metric_notes.get("beta_profile_fit"),
        ],
    )

    return {
        "executive_summary_verdict": (
            f"Final verdict is {scorecard.verdict} with confidence {scorecard.final_score:.2f}% "
            f"and data coverage {scorecard.data_coverage_pct:.2f}%."
        ),
        "fundamental_valuation": fundamental_para,
        "technical_volume": f"{technical_para}\n{flow_para}",
        "volatility_risk": "Volatility context relies on model beta and ADX-derived trend-state interpretation.",
        "tactical_execution": "Use projection ranges and technical support/resistance zones for entry and risk planning.",
        "manual_trade_management": (
            "Use predefined manual invalidation and monitoring rules to manage exits and position scaling "
            "without relying on ad-hoc discretionary overrides."
        ),
        "scenario_modeling": (
            "Use bull/base/bear projections already generated by the deterministic projection engine."
        ),
        "macro_stress_test": (
            "Stress behavior should be inferred from beta profile, leverage posture, profitability cushion, "
            "and peer-relative valuation spreads when available."
        ),
        "sector_relativity": _synthesize_paragraph(
            prefix=narratives.category_notes.get(
                "peer_relativity",
                "Sector relativity summary is unavailable in this run.",
            ),
            notes=[
                narratives.metric_notes.get("peer_forward_pe_premium"),
                narratives.metric_notes.get("peer_pe_to_sector_pe_ratio"),
                narratives.metric_notes.get("peer_ps_premium"),
                narratives.metric_notes.get("peer_margin_spread"),
                narratives.metric_notes.get("peer_growth_spread"),
            ],
        ),
    }


def _build_deterministic_comprehensive_text(scorecard: ScoreCard, narratives: NarrativeBundle) -> str:
    sections = _build_deterministic_section_map(scorecard, narratives)
    lines: list[str] = []
    for section_key, section_title in SECTION_SPECS:
        lines.append(f"## {section_title}")
        lines.append(str(sections.get(section_key, DATA_UNAVAILABLE)))
        lines.append("")
    return "\n".join(lines).strip()


def _synthesize_paragraph(prefix: str, notes: list[str | None]) -> str:
    unique_notes: list[str] = []
    seen: set[str] = set()
    for note in notes:
        cleaned = " ".join((note or "").split())
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        unique_notes.append(cleaned)

    if not unique_notes:
        return prefix

    merged = " ".join(unique_notes)
    if prefix:
        return f"{prefix} {merged}".strip()
    return merged


def _build_metric_contribution_rows(scorecard: ScoreCard) -> list[list[str]]:
    category_by_metric: dict[str, str] = {}
    for category, metric_weights in CATEGORY_METRIC_WEIGHTS.items():
        for metric_key in metric_weights:
            category_by_metric[metric_key] = category

    rows: list[list[str]] = []
    for metric_key in sorted(scorecard.metric_signals):
        signal = scorecard.metric_signals[metric_key]
        category = category_by_metric.get(metric_key, "unmapped")
        weight_pts = signal.weight
        contribution = signal.weight * signal.score

        rows.append(
            [
                _metric_label(metric_key),
                _category_label(category),
                _fmt_percent(signal.score * 100.0),
                _fmt_number(weight_pts),
                _fmt_number(contribution),
            ]
        )

    if not rows:
        rows.append([DATA_UNAVAILABLE, DATA_UNAVAILABLE, DATA_UNAVAILABLE, DATA_UNAVAILABLE, DATA_UNAVAILABLE])
    return rows


def _build_verdict_tier_rows() -> list[list[str]]:
    sorted_tiers = sorted(VERDICT_TIERS, key=lambda tier: tier.min_score, reverse=True)
    if not sorted_tiers:
        return [[DATA_UNAVAILABLE, DATA_UNAVAILABLE]]

    rows: list[list[str]] = []
    for index, tier in enumerate(sorted_tiers):
        upper_bound = 100.0 if index == 0 else sorted_tiers[index - 1].min_score - 0.01
        lower_bound = tier.min_score
        rows.append([tier.verdict, f"{lower_bound:.2f}% to {upper_bound:.2f}%"])
    return rows


def _format_metric_weight_block(metric_weights: dict[str, float]) -> str:
    if not metric_weights:
        return DATA_UNAVAILABLE

    ordered = sorted(metric_weights.items(), key=lambda item: item[1], reverse=True)
    parts: list[str] = []
    for metric_key, weight in ordered:
        metric_label = _metric_label(metric_key)
        parts.append(f"{metric_label}: {weight:.2f}")
    return " | ".join(parts)


def _metric_label(metric_key: str) -> str:
    short_names = {
        "valuation_pe_trend": "Valuation P/E Trend",
        "return_on_equity": "Return on Equity",
        "return_on_capital_employed": "Return on Capital Employed",
        "profit_margin": "Profit Margin",
        "operating_margin": "Operating Margin",
        "debt_to_equity": "Debt to Equity",
        "current_ratio": "Current Ratio",
        "quarterly_revenue_growth": "Quarterly Revenue Growth",
        "beta_profile_fit": "Beta Profile Fit",
        "fcf_vs_debt": "FCF vs Debt",
        "sma_crossover": "SMA Crossover",
        "rsi_14": "RSI(14)",
        "macd_crossover": "MACD Crossover",
        "bollinger_position": "Bollinger Position",
        "adx_trend_strength": "ADX Trend Strength",
        "ichimoku_cloud": "Ichimoku Cloud",
        "fibonacci_support_breakout": "Fibonacci Support/Breakout",
        "obv_30d_trend": "OBV 30D Trend",
        "relative_volume_10d_3m": "Relative Vol 10D/3M",
        "futures_oi_buildup": "Futures OI Build-up",
        "rollover_percentage": "Rollover %",
        "pcr_sentiment": "PCR Sentiment",
        "iv_percentile": "IV Percentile",
        "peer_forward_pe_premium": "Peer Forward P/E Premium",
        "peer_pe_to_sector_pe_ratio": "PE / Sector PE Ratio",
        "peer_ps_premium": "Peer P/S Premium",
        "peer_margin_spread": "Peer Margin Spread",
        "peer_growth_spread": "Peer Growth Spread",
    }
    return short_names.get(metric_key, metric_key.replace("_", " ").title())


def _category_label(category_key: str) -> str:
    if category_key == "volume_risk":
        return "Volume/Risk/F&O"
    return category_key.replace("_", " ").title()


def _as_signal_map(value: Any) -> dict[str, MetricSignal]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, MetricSignal] = {}
    for key, item in value.items():
        if isinstance(item, MetricSignal):
            result[str(key)] = item
    return result


def _needs_page_break(pdf: ResearchPDF, required_height: float) -> bool:
    return (pdf.get_y() + required_height) > (pdf.h - pdf.b_margin)


def _cell_text_width(pdf: ResearchPDF, col_width: float, padding_x: float) -> float:
    usable = col_width - (2.0 * padding_x) - (2.0 * pdf.c_margin)
    return max(4.0, usable - 0.4)


def _wrap_text(pdf: ResearchPDF, value: str, max_width: float, max_lines: int | None = None) -> list[str]:
    text = " ".join((value or "").split())
    if not text:
        return [DATA_UNAVAILABLE]

    lines: list[str] = []
    current = ""

    for token in text.split(" "):
        token_chunks = [token]
        if pdf.get_string_width(token) > max_width:
            token_chunks = _split_long_token(pdf, token, max_width)

        for chunk in token_chunks:
            if not current:
                current = chunk
                continue

            candidate = f"{current} {chunk}"
            if pdf.get_string_width(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = chunk
                if max_lines is not None and len(lines) >= max_lines - 1:
                    break

        if max_lines is not None and len(lines) >= max_lines - 1:
            break

    if current:
        lines.append(current)

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]

    if max_lines is not None:
        consumed = " ".join(lines)
        if consumed != text:
            last = lines[-1]
            while last and pdf.get_string_width(f"{last}...") > max_width:
                last = last[:-1]
            lines[-1] = (last if last else "") + "..."

    return lines


def _split_long_token(pdf: ResearchPDF, token: str, max_width: float) -> list[str]:
    parts: list[str] = []
    current = ""

    for char in token:
        candidate = current + char
        if candidate and pdf.get_string_width(candidate) <= max_width:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = char

    if current:
        parts.append(current)

    return parts if parts else [token]


def _fmt_currency(value: float | None, currency_code: str = "USD") -> str:
    if value is None:
        return DATA_UNAVAILABLE
    prefix = CURRENCY_SYMBOL_BY_CODE.get(currency_code.upper(), f"{currency_code.upper()} ")
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{prefix}{value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{prefix}{value / 1_000:.2f}K"
    return f"{prefix}{value:,.2f}"


def _fmt_number(value: float | None) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    return f"{value:.2f}"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    return str(value)


def _fmt_percent(value: float | None, already_percent: bool = True) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    numeric = value
    if already_percent:
        if abs(numeric) <= 1.0:
            numeric = numeric * 100.0
    else:
        numeric = numeric * 100.0
    return f"{numeric:.2f}%"


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_text(value: str | None) -> str:
    cleaned = " ".join((value or "").split())
    return cleaned if cleaned else DATA_UNAVAILABLE


def _safe_multiline_text(value: str | None) -> str:
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else DATA_UNAVAILABLE


def _resolve_currency_code(snapshot: MarketSnapshot) -> str:
    candidates = (
        snapshot.company_metadata.get("currency") if snapshot.company_metadata else None,
        snapshot.info.get("currency") if snapshot.info else None,
        snapshot.fast_info.get("currency") if snapshot.fast_info else None,
    )
    for candidate in candidates:
        if isinstance(candidate, str):
            cleaned = candidate.strip().upper()
            if cleaned:
                return cleaned
    inferred = _infer_currency_from_ticker(snapshot.ticker)
    if inferred is not None:
        return inferred
    return "USD"


def _infer_currency_from_ticker(ticker: str) -> str | None:
    normalized = (ticker or "").strip().upper()
    if normalized.endswith(".NS") or normalized.endswith(".BO"):
        return "INR"
    return None


def _locate_unicode_font_paths() -> dict[str, Path]:
    try:
        from matplotlib import font_manager

        detected_regular = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
        regular_path = Path(detected_regular)
        if detected_regular and regular_path.exists():
            parent = regular_path.parent
            bold = parent / "DejaVuSans-Bold.ttf"
            italic = parent / "DejaVuSans-Oblique.ttf"
            bold_italic = parent / "DejaVuSans-BoldOblique.ttf"
            return {
                "": regular_path,
                "B": bold if bold.exists() else regular_path,
                "I": italic if italic.exists() else regular_path,
                "BI": bold_italic if bold_italic.exists() else regular_path,
            }
    except Exception:
        pass

    windows_regular = Path(r"C:\Windows\Fonts\arial.ttf")
    if windows_regular.exists():
        windows_bold = Path(r"C:\Windows\Fonts\arialbd.ttf")
        windows_italic = Path(r"C:\Windows\Fonts\ariali.ttf")
        windows_bold_italic = Path(r"C:\Windows\Fonts\arialbi.ttf")
        return {
            "": windows_regular,
            "B": windows_bold if windows_bold.exists() else windows_regular,
            "I": windows_italic if windows_italic.exists() else windows_regular,
            "BI": windows_bold_italic if windows_bold_italic.exists() else windows_regular,
        }

    linux_regular = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if linux_regular.exists():
        linux_parent = linux_regular.parent
        linux_bold = linux_parent / "DejaVuSans-Bold.ttf"
        linux_italic = linux_parent / "DejaVuSans-Oblique.ttf"
        linux_bold_italic = linux_parent / "DejaVuSans-BoldOblique.ttf"
        return {
            "": linux_regular,
            "B": linux_bold if linux_bold.exists() else linux_regular,
            "I": linux_italic if linux_italic.exists() else linux_regular,
            "BI": linux_bold_italic if linux_bold_italic.exists() else linux_regular,
        }

    return {}
