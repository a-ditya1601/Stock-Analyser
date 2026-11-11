from __future__ import annotations

import argparse
from pathlib import Path

from equity_reporter.analysis.company_universe import refresh_company_universe


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the local company sector/industry universe cache.")
    parser.add_argument(
        "--markets",
        default="IN,US",
        help="Comma-separated market universe list. Supported: IN, US. Default: IN,US.",
    )
    parser.add_argument(
        "--limit-per-market",
        type=int,
        default=None,
        help="Optional cap per market, useful for smoke testing the refresh command.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.05,
        help="Delay between yfinance enrichment calls. Default: 0.05.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path. Defaults to .cache/company_universe.json at repo root.",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help=(
            "Build a fast local universe from bundled CSV seed data only. "
            "Currently useful for ind_nifty500list.csv; skips slow yfinance enrichment."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from existing cache/state and skip fresh entries. Enabled by default.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore existing cache/state and rebuild from scratch.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Write progress every N enriched tickers. Default: 50.",
    )
    parser.add_argument(
        "--stale-after-days",
        type=int,
        default=30,
        help="Skip already refreshed entries newer than this many days. Default: 30.",
    )
    args = parser.parse_args()

    markets = [part.strip().upper() for part in args.markets.split(",") if part.strip()]
    output_path = Path(args.output).expanduser().resolve() if args.output else None

    def _print_progress(processed: int, total: int, failed: int, pending: int) -> None:
        print(
            f"Progress: {processed}/{total} processed | {failed} failed/partial | {pending} pending",
            flush=True,
        )

    entries = refresh_company_universe(
        markets=markets,
        limit_per_market=args.limit_per_market,
        pause_seconds=max(0.0, args.pause_seconds),
        path=output_path,
        seed_only=args.seed_only,
        resume=args.resume,
        fresh=args.fresh,
        batch_size=args.batch_size,
        stale_after_days=args.stale_after_days,
        progress_callback=_print_progress,
    )
    print(f"Refreshed {len(entries)} company universe entries.")
    if output_path is not None:
        print(f"Wrote: {output_path}")
    else:
        print("Wrote: .cache/company_universe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
