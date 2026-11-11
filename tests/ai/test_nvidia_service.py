from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any

import pytest

from equity_reporter.ai.nvidia_service import NvidiaService
from equity_reporter.utils.errors import (
    NvidiaAuthError,
    NvidiaConfigurationError,
    NvidiaInvalidResponseError,
    NvidiaRateLimitError,
    NvidiaTimeoutError,
    NvidiaTransientUpstreamError,
)


@dataclass
class _FakeMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeMessage


class _FakeResponse:
    def __init__(self, *, content: str | None = None, choices: list[_FakeChoice] | None = None):
        self.choices = choices if choices is not None else [_FakeChoice(message=_FakeMessage(content=content))]


class _FakeCompletions:
    def __init__(self, side_effects: list[Any]):
        self.side_effects = side_effects
        self.calls = 0
        self.last_request: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        index = min(self.calls, len(self.side_effects) - 1)
        self.calls += 1
        effect = self.side_effects[index]
        if isinstance(effect, Exception):
            raise effect
        return effect


class _FakeChat:
    def __init__(self, side_effects: list[Any]):
        self.completions = _FakeCompletions(side_effects)


class _FakeClient:
    def __init__(self, side_effects: list[Any]):
        self.chat = _FakeChat(side_effects)


def _service_with_effects(
    side_effects: list[Any],
    *,
    retry_attempts: int = 1,
    timeout_seconds: int = 2,
    sleep_events: list[float] | None = None,
) -> NvidiaService:
    recorder = sleep_events if sleep_events is not None else []
    return NvidiaService(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="deepseek-ai/deepseek-v4-pro",
        retry_attempts=retry_attempts,
        timeout_seconds=timeout_seconds,
        client_factory=lambda *_: _FakeClient(side_effects),
        sleep_fn=lambda seconds: recorder.append(seconds),
    )


def test_nvidia_requires_api_key() -> None:
    service = NvidiaService(
        api_key="",
        client_factory=lambda *_: _FakeClient([_FakeResponse(content="unused")]),
    )
    with pytest.raises(NvidiaConfigurationError):
        service.generate_text(system_prompt="system", user_prompt="user")


def test_nvidia_sends_openai_compatible_chat_payload() -> None:
    client = _FakeClient([_FakeResponse(content="  hello world  ")])
    service = NvidiaService(
        api_key="test-key",
        base_url="https://integrate.api.nvidia.com/v1",
        model="deepseek-ai/deepseek-v4-pro",
        max_output_tokens=1234,
        temperature=0.2,
        client_factory=lambda api_key, base_url: client,
    )

    output = service.generate_text(system_prompt="system", user_prompt="user")

    assert output == "hello world"
    assert client.chat.completions.last_request == {
        "model": "deepseek-ai/deepseek-v4-pro",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        "temperature": 0.2,
        "max_tokens": 1234,
        "timeout": 180,
    }


def test_nvidia_default_retry_is_single_attempt() -> None:
    client = _FakeClient([Exception("503 service unavailable"), _FakeResponse(content="recovered")])
    sleep_events: list[float] = []
    service = NvidiaService(
        api_key="test-key",
        model="deepseek-ai/deepseek-v4-pro",
        client_factory=lambda *_: client,
        sleep_fn=lambda seconds: sleep_events.append(seconds),
    )
    with pytest.raises(NvidiaTransientUpstreamError):
        service.generate_text(system_prompt="system", user_prompt="user")

    assert client.chat.completions.calls == 1
    assert sleep_events == []


def test_nvidia_retries_transient_upstream_errors() -> None:
    sleep_events: list[float] = []
    service = _service_with_effects(
        [Exception("503 service unavailable"), _FakeResponse(content="recovered")],
        retry_attempts=3,
        sleep_events=sleep_events,
    )
    output = service.generate_text(system_prompt="system", user_prompt="user")
    assert output == "recovered"
    assert sleep_events == [0.5]


def test_nvidia_retries_rate_limit_then_raises() -> None:
    sleep_events: list[float] = []
    service = _service_with_effects(
        [Exception("429 quota exceeded"), Exception("429 quota exceeded"), Exception("429 quota exceeded")],
        retry_attempts=3,
        sleep_events=sleep_events,
    )
    with pytest.raises(NvidiaRateLimitError):
        service.generate_text(system_prompt="system", user_prompt="user")
    assert sleep_events == [0.5, 1.0]


def test_nvidia_auth_errors_do_not_retry() -> None:
    sleep_events: list[float] = []
    service = _service_with_effects([Exception("401 invalid api key")], sleep_events=sleep_events)
    with pytest.raises(NvidiaAuthError):
        service.generate_text(system_prompt="system", user_prompt="user")
    assert sleep_events == []


def test_nvidia_invalid_response_raises() -> None:
    service = _service_with_effects([_FakeResponse(choices=[])], retry_attempts=1)
    with pytest.raises(NvidiaInvalidResponseError):
        service.generate_text(system_prompt="system", user_prompt="user")


def test_nvidia_timeout_is_mapped() -> None:
    def _slow_response(**_: Any) -> _FakeResponse:
        sleep(0.05)
        return _FakeResponse(content="slow")

    client = _FakeClient([_FakeResponse(content="placeholder")])
    client.chat.completions.create = _slow_response  # type: ignore[method-assign]
    service = NvidiaService(
        api_key="test-key",
        model="deepseek-ai/deepseek-v4-pro",
        timeout_seconds=0,
        retry_attempts=1,
        client_factory=lambda *_: client,
    )
    with pytest.raises(NvidiaTimeoutError):
        service.generate_text(system_prompt="system", user_prompt="user")


def test_nvidia_error_messages_do_not_leak_provider_payload() -> None:
    service = _service_with_effects([Exception("401 invalid api key nvapi-secret-example")], retry_attempts=1)
    with pytest.raises(NvidiaAuthError) as exc_info:
        service.generate_text(system_prompt="system", user_prompt="user")
    assert "nvapi-secret-example" not in str(exc_info.value)
