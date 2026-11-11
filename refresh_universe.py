from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_src_path() -> None:
    root = Path(__file__).resolve().parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main() -> int:
    _bootstrap_src_path()
    from equity_reporter.tools.refresh_universe import main as refresh_main

    return refresh_main()


if __name__ == "__main__":
    raise SystemExit(main())
