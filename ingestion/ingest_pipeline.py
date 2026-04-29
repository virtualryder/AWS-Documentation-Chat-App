"""
Orchestrates the full ingestion pipeline:
  scrape → chunk → embed → upsert into PostgreSQL (pgvector) → save to disk

Can be run directly:
    python -m ingestion.ingest_pipeline --topics lambda s3 --max-pages 20

Or called programmatically from the Streamlit app.
"""

import argparse
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.aws_scraper import AWSScraper
from scraper.aws_doc_urls import SEED_URLS, TOPIC_KEYWORD_MAP
from ingestion.chunker import chunk_documents
from vectorstore.pg_client import upsert_chunks, get_chunk_count, get_manifest, save_manifest
from config import DOCS_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

UPSERT_BATCH_SIZE = 100


def _load_manifest() -> dict:
    return get_manifest()


def _save_manifest(manifest: dict) -> None:
    manifest["last_updated"] = datetime.now().isoformat()
    save_manifest(manifest)


def _content_hash(docs: list[dict]) -> str:
    combined = "".join(d.get("content_md", "") for d in docs)
    return hashlib.md5(combined.encode()).hexdigest()[:12]


def resolve_seed_keys(topics: list[str]) -> list[str]:
    """
    Map user-supplied topic strings to seed URL keys.
    Supports partial keyword matching via TOPIC_KEYWORD_MAP.
    Falls back to treating the topic as a direct seed key.
    """
    keys: set[str] = set()
    for topic in topics:
        topic_lower = topic.lower().strip()
        matched = False
        for keyword, seed_keys in TOPIC_KEYWORD_MAP.items():
            if keyword in topic_lower or topic_lower in keyword:
                keys.update(seed_keys)
                matched = True
        # Also check direct key match
        if topic_lower in SEED_URLS:
            keys.add(topic_lower)
            matched = True
        if not matched:
            logger.warning("No seed URL found for topic '%s' — skipping", topic)
    return list(keys)


def run_ingestion(
    seed_keys: list[str],
    max_pages_per_seed: int = 20,
    save_to_disk: bool = True,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict:
    """
    Main ingestion function.

    Args:
        seed_keys: List of keys from SEED_URLS to ingest.
        max_pages_per_seed: Max pages to crawl per seed URL.
        save_to_disk: Whether to persist raw markdown to the docs/ folder.
        progress_callback: Optional fn(message, current, total) for UI updates.

    Returns:
        Summary dict {seeds_processed, pages_scraped, chunks_indexed, skipped}
    """
    scraper = AWSScraper()
    manifest = _load_manifest()

    total = len(seed_keys)
    pages_scraped = 0
    chunks_indexed = 0
    skipped = []

    for i, key in enumerate(seed_keys):
        seed_info = SEED_URLS.get(key)
        if not seed_info:
            logger.warning("Unknown seed key '%s' — skipping", key)
            skipped.append(key)
            continue

        name = seed_info["name"]
        url = seed_info["url"]
        source_label = seed_info["source_label"]
        tier = seed_info.get("tier", 1)

        if progress_callback:
            progress_callback(f"Fetching: {name}", i, total)

        logger.info("[%d/%d] Crawling: %s", i + 1, total, url)
        crawl_start = datetime.now().isoformat()
        docs = scraper.crawl(url, max_pages=max_pages_per_seed)

        # Tag each doc with source metadata for citation and tier-awareness
        for doc in docs:
            doc["source_label"] = source_label
            doc["tier"] = tier

        if save_to_disk and docs:
            scraper.save_to_disk(docs, source_label)

        if not docs:
            logger.warning("No pages retrieved for '%s'", key)
            skipped.append(key)
            continue

        pages_scraped += len(docs)

        # Chunk
        chunks = chunk_documents(docs)
        logger.info("  %d pages → %d chunks", len(docs), len(chunks))

        # Inject tier into chunk metadata before upserting
        for c in chunks:
            c["metadata"]["tier"] = tier

        # Upsert in batches
        for batch_start in range(0, len(chunks), UPSERT_BATCH_SIZE):
            batch = chunks[batch_start:batch_start + UPSERT_BATCH_SIZE]
            upsert_chunks(batch)

        chunks_indexed += len(chunks)
        logger.info("  Indexed %d chunks for '%s'", len(chunks), name)

        # Update manifest entry for this source
        manifest["sources"][key] = {
            "name": name,
            "seed_url": url,
            "source_label": source_label,
            "tier": tier,
            "crawl_timestamp": crawl_start,
            "pages_scraped": len(docs),
            "chunks_indexed": len(chunks),
            "content_hash": _content_hash(docs),
        }

    manifest["total_chunks"] = get_chunk_count()
    _save_manifest(manifest)

    if progress_callback:
        progress_callback("Done", total, total)

    return {
        "seeds_processed": total - len(skipped),
        "pages_scraped": pages_scraped,
        "chunks_indexed": chunks_indexed,
        "skipped": skipped,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="Ingest AWS documentation into the vector store.")
    p.add_argument(
        "--topics",
        nargs="+",
        help="Topic/service names to ingest (e.g. lambda s3 serverless)",
        default=None,
    )
    p.add_argument(
        "--keys",
        nargs="+",
        help="Exact seed keys to ingest (e.g. lambda s3 bedrock)",
        default=None,
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Ingest all configured seed URLs (slow)",
    )
    p.add_argument("--max-pages", type=int, default=20, help="Max pages per seed")
    p.add_argument("--no-disk", action="store_true", help="Skip saving markdown to disk")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.all:
        seed_keys = list(SEED_URLS.keys())
    elif args.keys:
        seed_keys = args.keys
    elif args.topics:
        seed_keys = resolve_seed_keys(args.topics)
    else:
        print("Specify --topics, --keys, or --all")
        sys.exit(1)

    print(f"Ingesting seeds: {seed_keys}")
    summary = run_ingestion(
        seed_keys=seed_keys,
        max_pages_per_seed=args.max_pages,
        save_to_disk=not args.no_disk,
    )
    print(f"\nIngestion complete:")
    print(f"  Seeds processed : {summary['seeds_processed']}")
    print(f"  Pages scraped   : {summary['pages_scraped']}")
    print(f"  Chunks indexed  : {summary['chunks_indexed']}")
    if summary["skipped"]:
        print(f"  Skipped         : {summary['skipped']}")
