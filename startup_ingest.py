"""
Startup ingestion script — runs automatically on first Railway deployment.

Behaviour:
  - If the knowledge base already has data → exits immediately (idempotent).
  - If the knowledge base is empty → ingests all primary AWS services and exits.

Run order (set in railway.toml):
  python startup_ingest.py & streamlit run app.py ...
  ↑ background                ↑ starts immediately, doesn't wait

Estimated runtime on first boot: ~15-20 minutes (30 services × 20 pages each).
Every subsequent restart completes in <1 second.
"""

import logging
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [startup_ingest] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Primary services to index on first boot ────────────────────────────────────
# All Tier 1 (official AWS product documentation).
# Ordered roughly by how frequently they appear in architecture conversations.

DEFAULT_SEED_KEYS = [
    # Compute & Containers
    "lambda",
    "ec2",
    "ecs",
    "eks",
    # Storage
    "s3",
    "efs",
    # Databases
    "rds",
    "dynamodb",
    "redshift",
    "elasticache",
    # Networking
    "vpc",
    "route53",
    "cloudfront",
    "api_gateway",
    # Security & Identity
    "iam",
    "kms",
    "cognito",
    "guardduty",
    # Analytics & Data
    "glue",
    "kinesis",
    "athena",
    # Messaging & Integration
    "sqs",
    "sns",
    "eventbridge",
    "step_functions",
    # AI / ML
    "sagemaker",
    "bedrock",
    "bedrock_agentcore",
    # DevOps & Management
    "cloudformation",
    "cloudwatch",
    "cloudtrail",
]

# Pages per service — 20 gives good coverage of each service's core content.
# Lower this to 10 if you need faster cold starts.
PAGES_PER_SERVICE = 20


def main() -> None:
    # ── Check if already populated ─────────────────────────────────────────────
    try:
        from vectorstore.pg_client import get_chunk_count
        count = get_chunk_count()
    except Exception as exc:
        logger.error("Could not connect to the database: %s", exc)
        logger.error("Ensure DATABASE_URL is set and the Postgres service is running.")
        sys.exit(1)

    if count > 0:
        logger.info(
            "Knowledge base already contains %s chunks — skipping ingestion.", f"{count:,}"
        )
        return

    # ── First boot: ingest everything ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Knowledge base is empty — starting initial ingestion.")
    logger.info("%d services × up to %d pages each", len(DEFAULT_SEED_KEYS), PAGES_PER_SERVICE)
    logger.info("Estimated time: 15-20 minutes. The app is already available.")
    logger.info("=" * 60)

    from ingestion.ingest_pipeline import run_ingestion

    def progress(message: str, current: int, total: int) -> None:
        if total > 0:
            pct = int(current / total * 100)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            logger.info("[%s] %3d%%  %s", bar, pct, message)
        else:
            logger.info("%s", message)

    try:
        summary = run_ingestion(
            seed_keys=DEFAULT_SEED_KEYS,
            max_pages_per_seed=PAGES_PER_SERVICE,
            save_to_disk=False,   # ephemeral filesystem on Railway — no point saving
            progress_callback=progress,
        )
    except Exception as exc:
        logger.error("Ingestion failed: %s", exc, exc_info=True)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Initial ingestion complete.")
    logger.info("  Services indexed : %d", summary["seeds_processed"])
    logger.info("  Pages scraped    : %d", summary["pages_scraped"])
    logger.info("  Chunks indexed   : %s", f"{summary['chunks_indexed']:,}")
    if summary["skipped"]:
        logger.warning("  Skipped          : %s", ", ".join(summary["skipped"]))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
