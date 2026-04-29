"""
Scheduled documentation refresh — re-indexes services whose content is stale.

Designed to run as a Railway Cron service on a weekly schedule.

Usage
-----
Weekly refresh (default — re-indexes anything older than 7 days):
    python refresh_ingest.py

Custom staleness threshold:
    python refresh_ingest.py --max-age-days 14

Force re-index everything regardless of age:
    python refresh_ingest.py --force-all

Preview what would be refreshed without actually doing it:
    python refresh_ingest.py --dry-run

Railway Cron schedule (every Sunday at 3 AM UTC):
    0 3 * * 0

How to set up the Railway Cron service
---------------------------------------
1. In your Railway project, click + New → Empty Service
2. Name it "weekly-doc-refresh"
3. Set the start command: python refresh_ingest.py
4. Go to Settings → Cron Schedule → enter:  0 3 * * 0
5. Add the same environment variables as your main service
   (DATABASE_URL is injected automatically when services share a project)
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [refresh_ingest] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 7
PAGES_PER_SERVICE = 20


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Refresh stale AWS documentation in the knowledge base.")
    p.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Re-index services older than this many days (default: {DEFAULT_MAX_AGE_DAYS})",
    )
    p.add_argument(
        "--force-all",
        action="store_true",
        help="Re-index all primary services regardless of age",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be refreshed without actually doing it",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    from scraper.aws_doc_urls import PRIMARY_SEED_KEYS
    from vectorstore.pg_client import get_manifest
    from ingestion.ingest_pipeline import run_ingestion

    # ── Determine which services need refreshing ───────────────────────────────
    try:
        manifest = get_manifest()
    except Exception as exc:
        logger.error("Could not load manifest from database: %s", exc)
        sys.exit(1)

    sources = manifest.get("sources", {})
    now = datetime.now(timezone.utc)

    stale_keys: list[str] = []
    fresh_count = 0

    logger.info("Checking freshness of %d primary services (threshold: %d days):",
                len(PRIMARY_SEED_KEYS), args.max_age_days)

    for key in PRIMARY_SEED_KEYS:
        if args.force_all:
            stale_keys.append(key)
            logger.info("  %-28s → forced re-index", key)
            continue

        source = sources.get(key)
        if not source:
            stale_keys.append(key)
            logger.info("  %-28s → never indexed", key)
            continue

        try:
            ts = source.get("crawl_timestamp", "")
            last_crawl = datetime.fromisoformat(ts)
            if last_crawl.tzinfo is None:
                last_crawl = last_crawl.replace(tzinfo=timezone.utc)
            age_days = (now - last_crawl).days

            if age_days >= args.max_age_days:
                stale_keys.append(key)
                logger.info("  %-28s → %d days old — stale, will refresh", key, age_days)
            else:
                fresh_count += 1
                logger.info("  %-28s → %d days old — fresh, skipping", key, age_days)
        except (KeyError, ValueError, TypeError):
            stale_keys.append(key)
            logger.info("  %-28s → no valid timestamp — will re-index", key)

    logger.info("")
    logger.info("Summary: %d stale / %d fresh", len(stale_keys), fresh_count)

    if not stale_keys:
        logger.info("All services are up to date. Nothing to do.")
        return

    if args.dry_run:
        logger.info("[DRY RUN] Would refresh: %s", ", ".join(stale_keys))
        return

    # ── Re-index stale services ────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("Starting refresh of %d service(s)...", len(stale_keys))
    logger.info("=" * 60)

    def progress(message: str, current: int, total: int) -> None:
        if total > 0:
            pct = int(current / total * 100)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            logger.info("[%s] %3d%%  %s", bar, pct, message)
        else:
            logger.info("%s", message)

    try:
        summary = run_ingestion(
            seed_keys=stale_keys,
            max_pages_per_seed=PAGES_PER_SERVICE,
            save_to_disk=False,
            progress_callback=progress,
        )
    except Exception as exc:
        logger.error("Refresh failed: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Refresh complete.")
    logger.info("  Services refreshed : %d", summary["seeds_processed"])
    logger.info("  Pages scraped      : %d", summary["pages_scraped"])
    logger.info("  Chunks indexed     : %s", f"{summary['chunks_indexed']:,}")
    if summary["skipped"]:
        logger.warning("  Skipped            : %s", ", ".join(summary["skipped"]))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
