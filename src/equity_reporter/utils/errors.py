from __future__ import annotations


class ReportError(Exception):
    """Base exception for report generation."""


class DataUnavailableError(ReportError):
    """Raised when market data cannot be loaded."""


class ValidationError(ReportError):
    """Raised when required data is malformed or missing."""


class ChartRenderError(ReportError):
    """Raised when chart rendering fails."""


class NvidiaServiceError(ReportError):
    """Base exception for Nvidia AI integration failures."""


class NvidiaConfigurationError(NvidiaServiceError):
    """Raised when Nvidia runtime configuration is missing or invalid."""


class NvidiaAuthError(NvidiaServiceError):
    """Raised when Nvidia rejects authentication or permissions."""


class NvidiaRateLimitError(NvidiaServiceError):
    """Raised when Nvidia rate/usage limits are exceeded."""


class NvidiaTimeoutError(NvidiaServiceError):
    """Raised when Nvidia request execution times out."""


class NvidiaInvalidResponseError(NvidiaServiceError):
    """Raised when Nvidia returns an unusable response payload."""


class NvidiaTransientUpstreamError(NvidiaServiceError):
    """Raised for retryable upstream/provider failures."""


class NvidiaUpstreamError(NvidiaServiceError):
    """Raised for non-retryable upstream/provider failures."""
