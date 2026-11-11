from __future__ import annotations

import argparse

import uvicorn

from equity_reporter.api.settings import (
    VALID_LOG_LEVELS,
    get_web_host,
    get_web_log_level,
    get_web_port,
    load_environment,
)


def build_parser() -> argparse.ArgumentParser:
    load_environment()

    parser = argparse.ArgumentParser(
        prog="equity-research-reporter-web",
        description="Run the FastAPI web server for Equity Research Reporter.",
    )
    parser.add_argument(
        "--host",
        default=get_web_host(),
        help="Bind host for the web server. Default uses WEB_HOST env.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=get_web_port(),
        help="Bind port for the web server. Default uses WEB_PORT env.",
    )
    parser.add_argument(
        "--log-level",
        default=get_web_log_level(),
        choices=sorted(VALID_LOG_LEVELS),
        help="Uvicorn log level. Default uses WEB_LOG_LEVEL env.",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    uvicorn.run(
        "equity_reporter.api.app:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
