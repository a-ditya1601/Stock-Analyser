from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from equity_reporter.api.app import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    text_fragments: list[str] = []
    for page in reader.pages:
        text_fragments.append(page.extract_text() or "")
    return "\n".join(text_fragments)


@pytest.mark.integration
def test_generate_report_for_valid_ticker_returns_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/reports/generate",
        json={"query": "AAPL", "riskProfile": "balanced"},
    )
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/pdf")
    assert "attachment; filename=" in response.headers.get("content-disposition", "")
    assert response.content.startswith(b"%PDF")


@pytest.mark.integration
def test_generate_report_for_company_name_resolves_ticker_returns_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/reports/generate",
        json={"query": "Apple", "riskProfile": "balanced"},
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    disposition = response.headers.get("content-disposition", "")
    assert "AAPL_Equity_Research_Report.pdf" in disposition


def test_generate_report_invalid_input_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/reports/generate",
        json={"query": "   ", "riskProfile": "balanced"},
    )
    assert response.status_code == 422
    payload = response.json()
    assert "detail" in payload


@pytest.mark.integration
def test_generate_report_sparse_and_etf_paths_return_pdf_with_partial_data_notes(client: TestClient) -> None:
    for query in ("SPY", "TEMP"):
        response = client.post(
            "/api/reports/generate",
            json={"query": query, "riskProfile": "balanced"},
        )
        assert response.status_code == 200, f"Expected PDF response for {query}, got {response.status_code}"
        assert response.content.startswith(b"%PDF"), f"Response for {query} is not a PDF payload."

        extracted_text = _extract_pdf_text(response.content).lower()
        assert "unavailable in this run" in extracted_text, (
            f"Expected partial-data note for {query}. "
            f"Extracted snippet: {extracted_text[:600]}"
        )
