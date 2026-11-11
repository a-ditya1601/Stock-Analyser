from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response, status

from equity_reporter.api.report_service import generate_report_bytes
from equity_reporter.api.settings import (
    get_report_queue_wait_seconds,
    get_report_request_timeout_seconds,
)
from equity_reporter.api.schemas import (
    ApiErrorResponse,
    HealthResponse,
    ReportGenerateRequest,
    RiskProfilesResponse,
)
from equity_reporter.config import RISK_PROFILES
from equity_reporter.utils.errors import DataUnavailableError, ReportError, ValidationError

router = APIRouter(prefix="/api")

DEFAULT_RISK_PROFILE = "balanced"

INVALID_OR_UNSUPPORTED_MARKERS = (
    "could not resolve",
    "cannot be empty",
    "invalid ticker",
    "ticker may be invalid",
    "not yet supported",
    "possibly delisted",
    "no rows returned",
    "no historical market data returned",
    "no usable ohlc rows",
)
UPSTREAM_TIMEOUT_MARKERS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "rate limit",
    "too many requests",
    "service unavailable",
)
UPSTREAM_FAILURE_MARKERS = (
    "primary error:",
    "fallback error:",
    "connection",
    "ssl",
    "failed to decrypt",
    "bad gateway",
    "upstream",
)


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health_check() -> HealthResponse:
    return HealthResponse()


@router.get("/meta/risk-profiles", response_model=RiskProfilesResponse, tags=["meta"])
def risk_profiles() -> RiskProfilesResponse:
    return RiskProfilesResponse(
        riskProfiles=[*RISK_PROFILES],
        defaultRiskProfile=DEFAULT_RISK_PROFILE,
    )


@router.post(
    "/reports/generate",
    responses={
        400: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        502: {"model": ApiErrorResponse},
        503: {"model": ApiErrorResponse},
        500: {"model": ApiErrorResponse},
    },
    tags=["reports"],
)
async def generate_report(payload: ReportGenerateRequest, request: Request) -> Response:
    semaphore = request.app.state.report_generation_semaphore
    queue_wait = get_report_queue_wait_seconds()
    acquired = False

    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=queue_wait)
        acquired = True
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Server is busy generating other reports. "
                "Please retry in a few moments."
            ),
        ) from exc

    request_timeout = get_report_request_timeout_seconds()
    try:
        filename, file_bytes, mime_type = await asyncio.wait_for(
            asyncio.to_thread(
                generate_report_bytes,
                payload.query,
                payload.riskProfile,
            ),
            timeout=request_timeout,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Report generation timed out while waiting for market data. "
                "Please retry in a few moments."
            ),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except DataUnavailableError as exc:
        mapped_status, mapped_detail = _map_data_unavailable_error(exc)
        raise HTTPException(status_code=mapped_status, detail=mapped_detail) from exc
    except ReportError as exc:
        status_code = _map_report_error_status(exc)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive API boundary.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected server error while generating report.",
        ) from exc
    finally:
        if acquired:
            semaphore.release()

    return Response(
        content=file_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _map_report_error_status(exc: ReportError) -> int:
    lowered = str(exc).lower()
    if any(marker in lowered for marker in INVALID_OR_UNSUPPORTED_MARKERS):
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _map_data_unavailable_error(exc: DataUnavailableError) -> tuple[int, str]:
    message = str(exc).strip() or "Market data unavailable from upstream sources."
    lowered = message.lower()

    if any(marker in lowered for marker in INVALID_OR_UNSUPPORTED_MARKERS):
        return status.HTTP_404_NOT_FOUND, message
    if any(marker in lowered for marker in UPSTREAM_TIMEOUT_MARKERS):
        return (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Market data provider is temporarily unavailable or timed out. Please retry shortly.",
        )
    if any(marker in lowered for marker in UPSTREAM_FAILURE_MARKERS):
        return (
            status.HTTP_502_BAD_GATEWAY,
            "Market data provider returned an upstream error. Please retry.",
        )
    return status.HTTP_503_SERVICE_UNAVAILABLE, message
