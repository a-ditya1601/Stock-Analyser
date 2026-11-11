from __future__ import annotations

import argparse
from pathlib import Path

from equity_reporter.api.settings import load_environment
from equity_reporter.pipeline import RunConfig, run_report
from equity_reporter.utils.errors import ReportError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="equity-research-reporter",
        description="Generate an equity research PDF report for a given ticker.",
    )
    parser.add_argument("ticker", help="Ticker symbol, e.g. AAPL or RELIANCE.NS")
    parser.add_argument(
        "--risk-profile",
        choices=["defensive", "balanced", "aggressive"],
        default="balanced",
        help="Risk lens used for risk-aware scoring modules.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "reports",
        help="Directory where the final PDF report will be written.",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Optional custom PDF file name (with or without .pdf extension).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing report file if the destination already exists.",
    )
    return parser


def main() -> int:
    load_environment()
    parser = build_parser()
    args = parser.parse_args()

    config = RunConfig(
        ticker=args.ticker.strip(),
        risk_profile=args.risk_profile,
        output_dir=args.output_dir,
        output_name=args.output_name,
        overwrite=args.overwrite,
    )

    try:
        output_path = run_report(config)
        print(f"Report generated: {output_path}")
    except ReportError as exc:
        parser.exit(status=2, message=f"Error: {exc}\n")
    except Exception as exc:  # pragma: no cover - defensive boundary.
        parser.exit(
            status=2,
            message=(
                "Error: Unexpected failure while generating the report. "
                "Please retry, and if it persists verify dependencies/network access. "
                f"Details: {exc}\n"
            ),
        )

    return 0
