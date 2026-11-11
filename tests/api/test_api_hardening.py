from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from equity_reporter.api.app import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_includes_request_id_and_security_headers(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("x-request-id")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_validation_error_returns_standard_error_shape_with_request_id(client: TestClient) -> None:
    response = client.post("/api/reports/generate", json={"riskProfile": "balanced"})
    assert response.status_code == 422
    payload = response.json()
    assert isinstance(payload.get("detail"), str)
    assert isinstance(payload.get("requestId"), str)
    assert payload["requestId"]
    assert response.headers.get("x-request-id") == payload["requestId"]


def test_report_generation_success_uses_request_id_header(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_generate_report_bytes(query: str, risk_profile: str = "balanced") -> tuple[str, bytes, str]:
        _ = (query, risk_profile)
        return "TEST_Equity_Research_Report.pdf", b"%PDF-1.7\n%%EOF", "application/pdf"

    monkeypatch.setattr("equity_reporter.api.routes.generate_report_bytes", _fake_generate_report_bytes)

    response = client.post(
        "/api/reports/generate",
        json={"query": "TEST", "riskProfile": "balanced"},
    )
    assert response.status_code == 200
    assert response.headers.get("x-request-id")
    assert response.headers.get("content-type", "").startswith("application/pdf")
    assert response.content.startswith(b"%PDF")


def test_queue_timeout_fast_fails_when_server_is_busy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class _NeverAcquireSemaphore:
        async def acquire(self) -> None:
            await asyncio.sleep(3600)

        def release(self) -> None:
            return None

    original_semaphore = app.state.report_generation_semaphore
    app.state.report_generation_semaphore = _NeverAcquireSemaphore()
    monkeypatch.setattr("equity_reporter.api.routes.get_report_queue_wait_seconds", lambda: 0.5)

    try:
        response = client.post(
            "/api/reports/generate",
            json={"query": "AAPL", "riskProfile": "balanced"},
        )
    finally:
        app.state.report_generation_semaphore = original_semaphore

    assert response.status_code == 503
    payload = response.json()
    assert "busy generating other reports" in str(payload.get("detail", "")).lower()
    assert isinstance(payload.get("requestId"), str)

