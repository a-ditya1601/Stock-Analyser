from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from equity_reporter.api.settings import (
    get_allowed_origins,
    get_max_concurrent_reports,
    load_environment,
)

WEB_DIST_DIRNAME = "web"
WEB_DIST_OUTPUT_DIRNAME = "dist"
REQUEST_ID_HEADER = "X-Request-ID"
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    load_environment()

    app = FastAPI(
        title="Equity Research Reporter API",
        description="Web API for generating automated equity research reports.",
        version="0.1.0",
    )

    _configure_runtime_state(app)
    _configure_cors(app)
    _configure_request_middleware(app)
    _configure_exception_handlers(app)
    from equity_reporter.api.routes import router as api_router

    app.include_router(api_router)
    _configure_spa_serving(app)
    return app


def _configure_runtime_state(app: FastAPI) -> None:
    app.state.report_generation_semaphore = asyncio.Semaphore(get_max_concurrent_reports())


def _configure_cors(app: FastAPI) -> None:
    origins = get_allowed_origins()
    if not origins:
        return

    allow_all = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )


def _configure_request_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):  # type: ignore[override]
        request_id = uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        logger.info("request.start id=%s method=%s path=%s", request_id, request.method, request.url.path)

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "request.end id=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


def _configure_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        request_id = _request_id_from(request)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail, "requestId": request_id},
            headers=_response_headers(request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "Invalid request payload."
        if exc.errors():
            first = exc.errors()[0]
            if isinstance(first, dict) and isinstance(first.get("msg"), str):
                detail = str(first["msg"])
        request_id = _request_id_from(request)
        return JSONResponse(
            status_code=422,
            content={"detail": detail, "requestId": request_id},
            headers=_response_headers(request_id),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id_from(request)
        logger.exception("request.unhandled id=%s path=%s", request_id, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Unexpected server error while processing request.",
                "requestId": request_id,
            },
            headers=_response_headers(request_id),
        )


def _configure_spa_serving(app: FastAPI) -> None:
    dist_dir = _resolve_web_dist_dir()
    index_path = dist_dir / "index.html"
    if not index_path.exists():
        return

    @app.get("/", include_in_schema=False)
    async def web_root() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def web_catchall(full_path: str) -> FileResponse:
        safe_relative = full_path.strip().lstrip("/")
        if safe_relative == "api" or safe_relative.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found.")
        candidate = (dist_dir / safe_relative).resolve()
        if safe_relative and _is_within(candidate, dist_dir) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)


def _resolve_web_dist_dir() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / WEB_DIST_DIRNAME / WEB_DIST_OUTPUT_DIRNAME


def _is_within(path: Path, base_dir: Path) -> bool:
    try:
        path.relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


def _request_id_from(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value.strip():
        return value
    return uuid4().hex


def _response_headers(request_id: str) -> dict[str, str]:
    headers = {REQUEST_ID_HEADER: request_id}
    headers.update(SECURITY_HEADERS)
    return headers


app = create_app()
