from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency boundary.
    load_dotenv = None

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8000
DEFAULT_WEB_LOG_LEVEL = "info"
DEFAULT_REPORT_REQUEST_TIMEOUT_SECONDS = 180
DEFAULT_MAX_CONCURRENT_REPORTS = 2
DEFAULT_REPORT_QUEUE_WAIT_SECONDS = 5.0
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = "deepseek-ai/deepseek-v4-pro"
DEFAULT_NVIDIA_PEER_MODEL = "deepseek-ai/deepseek-v4-pro"
DEFAULT_NVIDIA_TIMEOUT_SECONDS = 180
DEFAULT_NVIDIA_PEER_TIMEOUT_SECONDS = 30
DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS = 4096
DEFAULT_NVIDIA_TEMPERATURE = 0.2
DEFAULT_ENABLE_NVIDIA_NARRATIVE = False
DEFAULT_ENABLE_NVIDIA_PEER_DISCOVERY = False

VALID_LOG_LEVELS = {"critical", "error", "warning", "info", "debug", "trace"}


def load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv()


def get_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if not raw.strip():
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def get_web_host() -> str:
    host = (os.getenv("WEB_HOST", DEFAULT_WEB_HOST) or "").strip()
    return host or DEFAULT_WEB_HOST


def get_web_port() -> int:
    return _parse_int_env("WEB_PORT", DEFAULT_WEB_PORT, min_value=1, max_value=65535)


def get_web_log_level() -> str:
    level = (os.getenv("WEB_LOG_LEVEL", DEFAULT_WEB_LOG_LEVEL) or "").strip().lower()
    if level in VALID_LOG_LEVELS:
        return level
    return DEFAULT_WEB_LOG_LEVEL


def get_report_request_timeout_seconds() -> int:
    return _parse_int_env(
        "REPORT_REQUEST_TIMEOUT_SECONDS",
        DEFAULT_REPORT_REQUEST_TIMEOUT_SECONDS,
        min_value=10,
        max_value=1800,
    )


def get_max_concurrent_reports() -> int:
    return _parse_int_env(
        "MAX_CONCURRENT_REPORTS",
        DEFAULT_MAX_CONCURRENT_REPORTS,
        min_value=1,
        max_value=16,
    )


def get_report_queue_wait_seconds() -> float:
    return _parse_float_env(
        "REPORT_QUEUE_WAIT_SECONDS",
        DEFAULT_REPORT_QUEUE_WAIT_SECONDS,
        min_value=0.5,
        max_value=60.0,
    )


def get_nvidia_api_key() -> str | None:
    raw = os.getenv("NVIDIA_API_KEY")
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return cleaned


def get_nvidia_base_url() -> str:
    raw = os.getenv("NVIDIA_BASE_URL")
    if raw is None:
        return DEFAULT_NVIDIA_BASE_URL
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_NVIDIA_BASE_URL
    return cleaned


def get_nvidia_model() -> str:
    raw = os.getenv("NVIDIA_MODEL")
    if raw is None:
        return DEFAULT_NVIDIA_MODEL
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_NVIDIA_MODEL
    return cleaned


def get_nvidia_peer_model() -> str:
    raw = os.getenv("NVIDIA_PEER_MODEL")
    if raw is None:
        return DEFAULT_NVIDIA_PEER_MODEL
    cleaned = raw.strip()
    if not cleaned:
        return DEFAULT_NVIDIA_PEER_MODEL
    return cleaned


def get_nvidia_timeout_seconds() -> int:
    return _parse_int_env(
        "NVIDIA_TIMEOUT_SECONDS",
        DEFAULT_NVIDIA_TIMEOUT_SECONDS,
        min_value=5,
        max_value=600,
    )


def get_nvidia_peer_timeout_seconds() -> int:
    return _parse_int_env(
        "NVIDIA_PEER_TIMEOUT_SECONDS",
        DEFAULT_NVIDIA_PEER_TIMEOUT_SECONDS,
        min_value=5,
        max_value=600,
    )


def get_nvidia_max_output_tokens() -> int:
    return _parse_int_env(
        "NVIDIA_MAX_OUTPUT_TOKENS",
        DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS,
        min_value=256,
        max_value=32768,
    )


def get_nvidia_temperature() -> float:
    return _parse_float_env(
        "NVIDIA_TEMPERATURE",
        DEFAULT_NVIDIA_TEMPERATURE,
        min_value=0.0,
        max_value=2.0,
    )


def is_nvidia_configured() -> bool:
    return get_nvidia_api_key() is not None


def is_nvidia_narrative_enabled() -> bool:
    raw = os.getenv("ENABLE_NVIDIA_NARRATIVE")
    if raw is None:
        if not DEFAULT_ENABLE_NVIDIA_NARRATIVE:
            return False
        return is_nvidia_configured()

    cleaned = raw.strip().lower()
    if not cleaned:
        if not DEFAULT_ENABLE_NVIDIA_NARRATIVE:
            return False
        return is_nvidia_configured()
    if cleaned in {"1", "true", "yes", "on"}:
        return is_nvidia_configured()
    if cleaned in {"0", "false", "no", "off"}:
        return False
    if not DEFAULT_ENABLE_NVIDIA_NARRATIVE:
        return False
    return is_nvidia_configured()


def is_nvidia_peer_discovery_enabled() -> bool:
    raw = os.getenv("ENABLE_NVIDIA_PEER_DISCOVERY")
    if raw is None:
        if not DEFAULT_ENABLE_NVIDIA_PEER_DISCOVERY:
            return False
        return is_nvidia_configured()

    cleaned = raw.strip().lower()
    if not cleaned:
        if not DEFAULT_ENABLE_NVIDIA_PEER_DISCOVERY:
            return False
        return is_nvidia_configured()
    if cleaned in {"1", "true", "yes", "on"}:
        return is_nvidia_configured()
    if cleaned in {"0", "false", "no", "off"}:
        return False
    if not DEFAULT_ENABLE_NVIDIA_PEER_DISCOVERY:
        return False
    return is_nvidia_configured()


def _parse_int_env(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return default
    if min_value is not None and value < min_value:
        return default
    if max_value is not None and value > max_value:
        return default
    return value


def _parse_float_env(
    name: str,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return default
    if min_value is not None and value < min_value:
        return default
    if max_value is not None and value > max_value:
        return default
    return value
