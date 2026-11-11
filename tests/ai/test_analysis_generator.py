from __future__ import annotations

from datetime import datetime

import pandas as pd

from equity_reporter.ai.analysis_generator import generate_comprehensive_analysis
from equity_reporter.models import MarketSnapshot, ProjectionScenarios, ScoreCard
from equity_reporter.utils.errors import NvidiaAuthError


class _FakeNvidiaService:
    def __init__(self, response: str | Exception) -> None:
        self.response = response

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        assert system_prompt.strip()
        assert user_prompt.strip()
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _snapshot() -> MarketSnapshot:
    history = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Volume": [1000, 1100, 1200],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
    )
    return MarketSnapshot(
        ticker="TEST.NS",
        history=history,
        info={},
        current_price=102.0,
        company_metadata={"company_name": "Test Ltd", "currency": "INR"},
        fetched_at=datetime(2026, 4, 24, 15, 0),
    )


def _signals() -> dict[str, object]:
    return {
        "risk_profile": "balanced",
        "fundamental_signals": {},
        "technical_signals": {},
        "volume_signals": {},
        "fibonacci_signal": None,
    }


def _projections() -> ProjectionScenarios:
    return ProjectionScenarios()


def _scorecard() -> ScoreCard:
    return ScoreCard(
        final_score=52.0,
        verdict="HOLD / NEUTRAL",
        data_coverage_pct=70.0,
        category_scores={"fundamental": 55.0, "technical": 52.0, "volume_risk": 48.0},
        category_weights={"fundamental": 40.0, "technical": 35.0, "volume_risk": 25.0},
    )


def test_analysis_generator_uses_fallback_when_ai_disabled() -> None:
    result = generate_comprehensive_analysis(
        _snapshot(),
        _signals(),
        _projections(),
        _scorecard(),
        enable_ai=False,
    )
    assert result.used_ai is False
    assert result.status_label == "Deterministic v2 (Local, No External AI Call)"
    assert "local rule-based narrative" in result.status_note.lower()
    assert "## 1. Fundamental Deep-Dive & Valuation" in result.text
    assert "## 5. Manual Trade Management & Invalidation Rules" in result.text
    assert "## 6. Algorithmic System Triggers" not in result.text
    assert "## 8. Sector Relativity (Conditional)" in result.text
    assert "## 9. Executive Summary & Verdict" in result.text


def test_analysis_generator_can_be_forced_disabled_without_calling_nvidia_service(monkeypatch) -> None:
    class _NeverCalledService:
        def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:  # noqa: ARG002
            raise AssertionError("Nvidia service should not be called when AI is disabled")

    monkeypatch.setenv("ENABLE_NVIDIA_NARRATIVE", "1")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    result = generate_comprehensive_analysis(
        _snapshot(),
        _signals(),
        _projections(),
        _scorecard(),
        nvidia_service=_NeverCalledService(),  # type: ignore[arg-type]
        enable_ai=False,
    )
    assert result.used_ai is False
    assert result.status_label == "Deterministic v2 (Local, No External AI Call)"


def test_analysis_generator_default_disabled_even_when_nvidia_key_exists(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_NVIDIA_NARRATIVE", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    result = generate_comprehensive_analysis(
        _snapshot(),
        _signals(),
        _projections(),
        _scorecard(),
        nvidia_service=_FakeNvidiaService("## 9. Executive Summary & Verdict\nAI analysis body"),
    )
    assert result.used_ai is False
    assert result.status_label == "Deterministic v2 (Local, No External AI Call)"
    assert "AI analysis body" not in result.text


def test_analysis_generator_uses_ai_when_available() -> None:
    result = generate_comprehensive_analysis(
        _snapshot(),
        _signals(),
        _projections(),
        _scorecard(),
        enable_ai=True,
        nvidia_service=_FakeNvidiaService("## 9. Executive Summary & Verdict\nAI analysis body"),
    )
    assert result.used_ai is True
    assert result.status_label == "Nvidia Applied"
    assert "AI analysis body" in result.text


def test_analysis_generator_falls_back_on_nvidia_error() -> None:
    result = generate_comprehensive_analysis(
        _snapshot(),
        _signals(),
        _projections(),
        _scorecard(),
        enable_ai=True,
        nvidia_service=_FakeNvidiaService(NvidiaAuthError("bad credentials")),
    )
    assert result.used_ai is False
    assert result.status_label == "Deterministic v2 (AI Fallback)"
    assert "deterministic narrative" in result.status_note.lower()
