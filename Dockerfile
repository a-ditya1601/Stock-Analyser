# syntax=docker/dockerfile:1

FROM node:22-alpine AS web-build
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY main.py web_main.py refresh_universe.py README.md ./
COPY .env.example ./
COPY --from=web-build /app/web/dist ./web/dist

EXPOSE 8000

CMD ["sh", "-c", "uvicorn equity_reporter.api.app:app --host ${WEB_HOST:-0.0.0.0} --port ${WEB_PORT:-8000} --log-level ${WEB_LOG_LEVEL:-info} --app-dir src"]
