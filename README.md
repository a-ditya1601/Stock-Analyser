# Equity Research Reporter

Automated equity analysis and professional PDF report generation with CLI + web app support.

For the latest backend reliability/security pass, see:
- `V1_1_HARDENING_CHECKLIST.md`

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional backend environment:

```powershell
copy .env.example .env
```

Runtime keys in `.env`:

```text
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_LOG_LEVEL=info
REPORT_REQUEST_TIMEOUT_SECONDS=180
MAX_CONCURRENT_REPORTS=2
REPORT_QUEUE_WAIT_SECONDS=5
ALLOWED_ORIGINS=
```

Optional Nvidia AI keys (comprehensive analysis remains deterministic unless explicitly enabled):

```text
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=deepseek-ai/deepseek-v4-pro
NVIDIA_PEER_MODEL=deepseek-ai/deepseek-v4-pro
NVIDIA_TIMEOUT_SECONDS=180
NVIDIA_PEER_TIMEOUT_SECONDS=30
NVIDIA_MAX_OUTPUT_TOKENS=4096
NVIDIA_TEMPERATURE=0.2
ENABLE_NVIDIA_NARRATIVE=0
ENABLE_NVIDIA_PEER_DISCOVERY=0
```

Peer discovery for sector-relative valuation is deterministic by default. It reads a local sector/industry universe from `.cache/company_universe.json`, ranks same-industry peers first, falls back to same-sector peers, and then uses the manual peer cache when needed.

Comprehensive analysis uses the local deterministic v2 engine by default; the Nvidia narrative path remains available in source and can be enabled later with `ENABLE_NVIDIA_NARRATIVE=1`.

If `ind_nifty500list.csv` exists in the project root, the refresh command uses it as the India seed list automatically and falls back to its company/industry values when Yahoo metadata is incomplete.

Refresh the local peer universe manually:

```powershell
python refresh_universe.py
```

For a full resumable India + US company universe refresh:

```powershell
python refresh_universe.py --markets IN,US --batch-size 50
```

If interrupted, run the same command again to resume. To force a rebuild:

```powershell
python refresh_universe.py --markets IN,US --fresh --batch-size 50
```

For a quick smoke refresh without enriching the full India + US universe:

```powershell
python refresh_universe.py --limit-per-market 25
```

For a very fast India-only seed from `ind_nifty500list.csv`:

```powershell
python refresh_universe.py --markets IN --seed-only
```

Optional Angel One SmartAPI keys (used only for Indian `.NS` / `.BO` F&O metrics; reports still generate if omitted):

```text
ANGEL_API_KEY=
ANGEL_CLIENT_ID=
ANGEL_PIN=
ANGEL_TOTP_SECRET=
```

Indian F&O metrics use Angel One SmartAPI plus Angel's official ScripMaster token file. Global/US option metrics use `yfinance`; single-stock futures fields remain unavailable on that route and are excluded from scoring.

## CLI (Default Flow)

```powershell
python main.py AAPL --risk-profile balanced
python main.py "Apple" --risk-profile balanced
python main.py NVDA --output-dir reports --output-name "NVDA Deep Dive" --overwrite
```

## Backend API (FastAPI)

Run with `uvicorn`:

```powershell
.venv\Scripts\python.exe -m uvicorn equity_reporter.api.app:app --host 127.0.0.1 --port 8000 --reload --app-dir src
```

Or run the thin helper entrypoint:

```powershell
python web_main.py --host 127.0.0.1 --port 8000 --reload
```

Health endpoint:

```text
GET http://127.0.0.1:8000/api/health
```

Available API endpoints:

- `GET /api/health` - liveness check.
- `GET /api/meta/risk-profiles` - risk profile options for UI dropdowns.
- `POST /api/reports/generate` - returns a downloadable PDF stream.

API hardening notes:
- Responses include `X-Request-ID` for traceability in logs and support debugging.
- Basic security headers are applied (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).
- Report generation concurrency is guarded by `MAX_CONCURRENT_REPORTS` with queue timeout `REPORT_QUEUE_WAIT_SECONDS`.

Example generate payload:

```json
{
  "query": "Apple",
  "riskProfile": "balanced"
}
```

## Dev Integration (Frontend + Backend)

1. Start backend:

```powershell
.venv\Scripts\python.exe -m uvicorn equity_reporter.api.app:app --host 127.0.0.1 --port 8000 --reload --app-dir src
```

2. Start frontend (in another terminal):

```powershell
cd web
copy .env.example .env
npm install
npm run dev
```

Dev defaults:

```text
VITE_API_BASE_URL=                      # empty -> use Vite proxy (/api)
VITE_DEV_API_PROXY_TARGET=http://127.0.0.1:8000
```

## Prod Integration (Single Deploy Target)

Build frontend assets:

```powershell
cd web
npm run build
```

Run backend:

```powershell
cd ..
.venv\Scripts\python.exe -m uvicorn equity_reporter.api.app:app --host 0.0.0.0 --port 8000 --log-level info --app-dir src
```

In production mode, FastAPI serves:
- API endpoints under `/api/*`
- React static bundle from `web/dist` for all non-API routes

## CORS (Cloud Flexibility)

Set `ALLOWED_ORIGINS` as comma-separated origins when frontend and backend are hosted on different origins:

```text
ALLOWED_ORIGINS=https://your-frontend.example.com,http://localhost:5173
```

If frontend and backend are served from the same FastAPI host in production, CORS is typically not needed.

## Docker (Cloud-Ready Single Container)

Build image:

```powershell
docker build -t chart-analyser:latest .
```

Run container:

```powershell
docker run --rm -p 8000:8000 --env-file .env chart-analyser:latest
```

Container production start command:

```text
uvicorn equity_reporter.api.app:app --host ${WEB_HOST:-0.0.0.0} --port ${WEB_PORT:-8000} --log-level ${WEB_LOG_LEVEL:-info} --app-dir src
```

Generated PDFs are ephemeral in v1 (request-scoped temp files, no persistent storage).

### One-Command Local Docker Run

```powershell
.\run-docker.ps1 -Rebuild
```

Stop:

```powershell
.\stop-docker.ps1
```

Compose alternative:

```powershell
docker compose up -d --build
docker compose down
```

## Testing

Backend API acceptance tests:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests/api/test_api_endpoints.py -q
```

Frontend UI tests:

```powershell
cd web
npm run test:run
```
