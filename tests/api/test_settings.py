from __future__ import annotations

from equity_reporter.api import settings


def test_numeric_env_parsing_with_bounds(monkeypatch) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_REPORTS", "4")
    monkeypatch.setenv("REPORT_QUEUE_WAIT_SECONDS", "3.5")
    monkeypatch.setenv("REPORT_REQUEST_TIMEOUT_SECONDS", "240")

    assert settings.get_max_concurrent_reports() == 4
    assert settings.get_report_queue_wait_seconds() == 3.5
    assert settings.get_report_request_timeout_seconds() == 240


def test_invalid_numeric_env_values_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_REPORTS", "-1")
    monkeypatch.setenv("REPORT_QUEUE_WAIT_SECONDS", "999")
    monkeypatch.setenv("REPORT_REQUEST_TIMEOUT_SECONDS", "abc")

    assert settings.get_max_concurrent_reports() == settings.DEFAULT_MAX_CONCURRENT_REPORTS
    assert settings.get_report_queue_wait_seconds() == settings.DEFAULT_REPORT_QUEUE_WAIT_SECONDS
    assert settings.get_report_request_timeout_seconds() == settings.DEFAULT_REPORT_REQUEST_TIMEOUT_SECONDS


def test_nvidia_env_parsing(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", " test-key ")
    monkeypatch.setenv("NVIDIA_BASE_URL", " https://example.test/v1 ")
    monkeypatch.setenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-pro")
    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("NVIDIA_MAX_OUTPUT_TOKENS", "3000")
    monkeypatch.setenv("NVIDIA_TEMPERATURE", "0.35")

    assert settings.get_nvidia_api_key() == "test-key"
    assert settings.get_nvidia_base_url() == "https://example.test/v1"
    assert settings.get_nvidia_model() == "deepseek-ai/deepseek-v4-pro"
    assert settings.get_nvidia_timeout_seconds() == 45
    assert settings.get_nvidia_max_output_tokens() == 3000
    assert settings.get_nvidia_temperature() == 0.35
    assert settings.is_nvidia_configured() is True


def test_nvidia_invalid_env_values_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "   ")
    monkeypatch.setenv("NVIDIA_BASE_URL", "   ")
    monkeypatch.setenv("NVIDIA_MODEL", "   ")
    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "oops")
    monkeypatch.setenv("NVIDIA_MAX_OUTPUT_TOKENS", "-5")
    monkeypatch.setenv("NVIDIA_TEMPERATURE", "3.7")

    assert settings.get_nvidia_api_key() is None
    assert settings.get_nvidia_base_url() == settings.DEFAULT_NVIDIA_BASE_URL
    assert settings.get_nvidia_model() == settings.DEFAULT_NVIDIA_MODEL
    assert settings.get_nvidia_timeout_seconds() == settings.DEFAULT_NVIDIA_TIMEOUT_SECONDS
    assert settings.get_nvidia_max_output_tokens() == settings.DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS
    assert settings.get_nvidia_temperature() == settings.DEFAULT_NVIDIA_TEMPERATURE
    assert settings.is_nvidia_configured() is False


def test_nvidia_peer_env_parsing(monkeypatch) -> None:
    monkeypatch.setenv("NVIDIA_PEER_MODEL", "deepseek-ai/deepseek-v4-pro")
    monkeypatch.setenv("NVIDIA_PEER_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "40")

    assert settings.get_nvidia_peer_model() == "deepseek-ai/deepseek-v4-pro"
    assert settings.get_nvidia_peer_timeout_seconds() == 25


def test_nvidia_peer_env_defaults_and_bounds(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_PEER_MODEL", raising=False)
    monkeypatch.delenv("NVIDIA_PEER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("NVIDIA_TIMEOUT_SECONDS", "41")
    assert settings.get_nvidia_peer_model() == settings.DEFAULT_NVIDIA_PEER_MODEL
    assert settings.get_nvidia_peer_timeout_seconds() == settings.DEFAULT_NVIDIA_PEER_TIMEOUT_SECONDS

    monkeypatch.setenv("NVIDIA_PEER_TIMEOUT_SECONDS", "9999")
    assert settings.get_nvidia_peer_timeout_seconds() == settings.DEFAULT_NVIDIA_PEER_TIMEOUT_SECONDS


def test_nvidia_narrative_enablement_defaults_and_overrides(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_NVIDIA_NARRATIVE", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    assert settings.is_nvidia_narrative_enabled() is False

    monkeypatch.setenv("ENABLE_NVIDIA_NARRATIVE", "0")
    assert settings.is_nvidia_narrative_enabled() is False

    monkeypatch.setenv("ENABLE_NVIDIA_NARRATIVE", "1")
    assert settings.is_nvidia_narrative_enabled() is True

    monkeypatch.setenv("NVIDIA_API_KEY", "")
    assert settings.is_nvidia_narrative_enabled() is False


def test_nvidia_peer_discovery_enablement(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_NVIDIA_PEER_DISCOVERY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    assert settings.is_nvidia_peer_discovery_enabled() is False

    monkeypatch.setenv("ENABLE_NVIDIA_PEER_DISCOVERY", "0")
    assert settings.is_nvidia_peer_discovery_enabled() is False

    monkeypatch.setenv("ENABLE_NVIDIA_PEER_DISCOVERY", "1")
    assert settings.is_nvidia_peer_discovery_enabled() is True

    monkeypatch.setenv("NVIDIA_API_KEY", "")
    assert settings.is_nvidia_peer_discovery_enabled() is False
