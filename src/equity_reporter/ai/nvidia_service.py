from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from time import sleep as default_sleep
from typing import Any, Callable

from equity_reporter.api.settings import (
    get_nvidia_api_key,
    get_nvidia_base_url,
    get_nvidia_max_output_tokens,
    get_nvidia_model,
    get_nvidia_temperature,
    get_nvidia_timeout_seconds,
)
from equity_reporter.utils.errors import (
    NvidiaAuthError,
    NvidiaConfigurationError,
    NvidiaInvalidResponseError,
    NvidiaRateLimitError,
    NvidiaServiceError,
    NvidiaTimeoutError,
    NvidiaTransientUpstreamError,
    NvidiaUpstreamError,
)
from equity_reporter.utils.logging_utils import get_logger

RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    NvidiaRateLimitError,
    NvidiaTimeoutError,
    NvidiaTransientUpstreamError,
)

AUTH_ERROR_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "permission denied",
    "invalid api key",
    "api key not valid",
    "access denied",
)
RATE_LIMIT_ERROR_MARKERS = (
    "429",
    "rate limit",
    "resource_exhausted",
    "quota",
    "too many requests",
)
TIMEOUT_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "deadline exceeded",
)
TRANSIENT_ERROR_MARKERS = (
    "500",
    "502",
    "503",
    "504",
    "service unavailable",
    "temporarily unavailable",
    "unavailable",
    "internal error",
    "upstream",
    "connection reset",
)


@dataclass(slots=True, frozen=True)
class NvidiaRequestPayload:
    model: str
    messages: list[dict[str, str]]
    max_tokens: int
    temperature: float


class NvidiaService:
    """OpenAI-compatible Nvidia client with retry + strict error mapping."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        retry_attempts: int = 1,
        retry_backoff_seconds: float = 0.5,
        client_factory: Callable[[str, str], Any] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else get_nvidia_api_key()) or ""
        self.base_url = base_url or get_nvidia_base_url()
        self.model = model or get_nvidia_model()
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else get_nvidia_timeout_seconds()
        self.max_output_tokens = (
            max_output_tokens if max_output_tokens is not None else get_nvidia_max_output_tokens()
        )
        self.temperature = temperature if temperature is not None else get_nvidia_temperature()
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._client_factory = client_factory or _default_client_factory
        self._sleep_fn = sleep_fn or default_sleep
        self._client: Any | None = None
        self._logger = get_logger(__name__)

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key.strip():
            raise NvidiaConfigurationError("Nvidia AI is not configured. Set NVIDIA_API_KEY in environment.")

        system_clean = " ".join((system_prompt or "").split()).strip()
        user_clean = " ".join((user_prompt or "").split()).strip()
        if not system_clean or not user_clean:
            raise NvidiaInvalidResponseError("Nvidia prompt payload is empty or malformed.")

        request = self._build_request_payload(system_prompt=system_prompt, user_prompt=user_prompt)

        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = self._execute_request_with_timeout(request)
                return self._extract_text(response)
            except NvidiaServiceError as exc:
                self._logger.warning(
                    "nvidia.request.failed model=%s attempt=%s/%s category=%s",
                    self.model,
                    attempt,
                    self.retry_attempts,
                    type(exc).__name__,
                )
                if isinstance(exc, RETRYABLE_ERRORS) and attempt < self.retry_attempts:
                    self._sleep_fn(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                    continue
                raise

        raise NvidiaUpstreamError("Nvidia request failed after retry attempts were exhausted.")

    def _build_request_payload(self, *, system_prompt: str, user_prompt: str) -> NvidiaRequestPayload:
        return NvidiaRequestPayload(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_prompt.strip()},
            ],
            max_tokens=int(self.max_output_tokens),
            temperature=float(self.temperature),
        )

    def _execute_request_with_timeout(self, request: NvidiaRequestPayload) -> Any:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._execute_request, request)
        try:
            return future.result(timeout=self.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise NvidiaTimeoutError("Nvidia request timed out before completion.") from exc
        finally:
            # Do not block report generation waiting for a provider call that already exceeded our SLA.
            executor.shutdown(wait=False, cancel_futures=True)

    def _execute_request(self, request: NvidiaRequestPayload) -> Any:
        client = self._get_client()
        try:
            return client.chat.completions.create(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise _map_provider_error(exc) from exc

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            self._client = self._client_factory(self.api_key, self.base_url)
        except NvidiaServiceError:
            raise
        except Exception as exc:
            raise NvidiaConfigurationError(
                "Nvidia client initialization failed. Check SDK installation and API key setup."
            ) from exc
        return self._client

    def _extract_text(self, response: Any) -> str:
        choices = getattr(response, "choices", None)
        if isinstance(choices, list) and choices:
            message = getattr(choices[0], "message", None)
            content = _safe_text(getattr(message, "content", None))
            if content:
                return content

        raise NvidiaInvalidResponseError("Nvidia returned an empty or unsupported response payload.")


def _default_client_factory(api_key: str, base_url: str) -> Any:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise NvidiaConfigurationError(
            "OpenAI SDK is unavailable. Install dependency 'openai' before using Nvidia AI."
        ) from exc

    try:
        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
    except Exception as exc:
        raise NvidiaConfigurationError(
            "Nvidia client could not be initialized. Verify NVIDIA_API_KEY and account access."
        ) from exc


def _map_provider_error(exc: Exception) -> NvidiaServiceError:
    message = _normalize_error_text(exc)

    if any(marker in message for marker in AUTH_ERROR_MARKERS):
        return NvidiaAuthError("Nvidia authentication failed. Check API key and permissions.")
    if any(marker in message for marker in RATE_LIMIT_ERROR_MARKERS):
        return NvidiaRateLimitError("Nvidia rate or quota limit reached. Please retry shortly.")
    if any(marker in message for marker in TIMEOUT_ERROR_MARKERS):
        return NvidiaTimeoutError("Nvidia request timed out before completion.")
    if any(marker in message for marker in TRANSIENT_ERROR_MARKERS):
        return NvidiaTransientUpstreamError("Nvidia service is temporarily unavailable. Please retry.")
    return NvidiaUpstreamError("Nvidia request failed due to an upstream provider error.")


def _normalize_error_text(exc: Exception) -> str:
    raw = str(exc or "")
    return " ".join(raw.lower().split())


def _safe_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned
