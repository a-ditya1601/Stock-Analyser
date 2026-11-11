from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # Keep third-party provider noise out of CLI output; user-facing errors are raised explicitly.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return logging.getLogger(name)
