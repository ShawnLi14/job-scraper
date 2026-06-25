#!/usr/bin/env python3
"""Run the job scraper and post new listings to Discord."""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from discord_notify import post_new_jobs
from scrape_quant_jobs import run

LOG_DIR = Path(__file__).parent / "logs"


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / "pipeline.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape jobs and notify Discord of new postings.")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SCRAPE_WORKERS", "8")))
    parser.add_argument("--dry-run", action="store_true", help="Scrape only; do not save history or post to Discord")
    parser.add_argument("--no-discord", action="store_true", help="Run scraper but skip Discord notifications")
    args = parser.parse_args()

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    mention_role_id = os.environ.get("DISCORD_MENTION_ROLE_ID", "").strip() or None

    if not args.dry_run and not args.no_discord and not webhook_url:
        _log("ERROR: DISCORD_WEBHOOK_URL is not set")
        return 1

    _log("Starting scrape…")
    result = run(workers=args.workers, persist_history=not args.dry_run)
    if result is None:
        _log("ERROR: run() returned None (diagnose mode?)")
        return 1

    _log(
        f"Done: {len(result.new_jobs)} new, "
        f"{len(result.returning_jobs)} returning, "
        f"{len(result.all_jobs)} total, "
        f"{len(result.errors)} firm errors"
    )

    if result.errors:
        for name, err in sorted(result.errors.items()):
            _log(f"  scrape error [{name}]: {err[:200]}")

    if args.dry_run:
        _log("Dry run — history not saved, Discord skipped")
        return 0

    if result.new_jobs and not args.no_discord:
        try:
            batches = post_new_jobs(
                result.new_jobs,
                webhook_url,
                mention_role_id=mention_role_id,
            )
            _log(f"Posted {len(result.new_jobs)} new job(s) to Discord ({batches} message batch(es))")
        except Exception as e:
            _log(f"WARNING: Discord post failed (scrape still saved): {e}")
    elif not result.new_jobs:
        _log("No new jobs — staying silent on Discord")

    return 0


if __name__ == "__main__":
    sys.exit(main())
