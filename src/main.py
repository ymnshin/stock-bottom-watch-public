from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from app_service import PROJECT_ROOT, run_stock_watch, save_stock_watch_state
from discord_client import post_or_print, print_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Japanese stock bottom watch notifier")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    parser.add_argument("--watchlist", type=Path, default=PROJECT_ROOT / "watchlist.csv")
    parser.add_argument("--state-path", type=Path, default=PROJECT_ROOT / "data" / "state.json")
    parser.add_argument("--reset-state", action="store_true", help="Delete saved state before running")
    parser.add_argument("--dry-run", action="store_true", help="Always print report instead of posting")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    _load_dotenv(PROJECT_ROOT / ".env")

    result = run_stock_watch(
        config_path=args.config,
        watchlist_path=args.watchlist,
        state_path=args.state_path,
        reset_state=args.reset_state,
        write_history_cache=not args.dry_run,
    )
    logging.info(
        "Analyzed %d/%d tickers; failures=%d; dry_run=%s",
        len(result.analyses), len(result.watchlist_tickers), len(result.failures), args.dry_run,
    )
    if not result.analyses:
        raise RuntimeError("No stocks could be analyzed; report and state update aborted")
    webhook_url = None if args.dry_run else os.getenv("DISCORD_WEBHOOK_URL")
    post_or_print(result.report, webhook_url)

    if not args.dry_run:
        save_stock_watch_state(result, args.state_path)
    return 0


def _load_dotenv(path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print_error(f"ERROR: {exc}")
        raise
