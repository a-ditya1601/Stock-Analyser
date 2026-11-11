from __future__ import annotations

from typing import Any

__all__ = ["app", "create_app", "generate_report_bytes"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from equity_reporter.api.app import app

        return app
    if name == "create_app":
        from equity_reporter.api.app import create_app

        return create_app
    if name == "generate_report_bytes":
        from equity_reporter.api.report_service import generate_report_bytes

        return generate_report_bytes
    raise AttributeError(name)
