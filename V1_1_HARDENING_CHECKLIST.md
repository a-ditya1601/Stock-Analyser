# v1.1 Hardening Checklist

## 1) API Reliability and Safety
- [x] Add request traceability via `X-Request-ID`.
- [x] Add baseline security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- [x] Standardize API error envelope with `detail` and optional `requestId`.
- [x] Add global exception handlers for HTTP, validation, and unexpected errors.
- [x] Add report-generation concurrency guard (`MAX_CONCURRENT_REPORTS`) with queue timeout (`REPORT_QUEUE_WAIT_SECONDS`).

## 2) Market-Data Resilience
- [x] Add retry/backoff for 1-year history fetch path before hard-fail.
- [x] Add retry/backoff for metadata/info fetch path.
- [x] Keep graceful abort behavior and invalid/delisted hints.

## 3) Runtime/Operations
- [x] Expand environment config surface for concurrency controls.
- [x] Add docker-compose healthcheck for `/api/health`.
- [x] Keep CLI and web behavior aligned on shared pipeline.

## 4) Verification
- [x] Add API hardening tests (headers, error envelope, queue timeout, mocked success path).
- [x] Add settings parsing tests for bounds/default fallback.
- [x] Run backend test suite (`pytest`) successfully.
- [x] Run frontend test suite (`vitest`) successfully.
- [x] Run Docker rebuild + health + PDF smoke generation successfully.

