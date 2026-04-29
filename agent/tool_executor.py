"""
Python-side implementations of the tools defined in agent/tools.py.
Each function receives the parsed tool input and returns a plain string
that becomes the content of the ToolResultBlockParam sent back to Claude.
"""

import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from vectorstore.pg_client import query_docs
from scraper.aws_scraper import AWSScraper

logger = logging.getLogger(__name__)

_scraper: AWSScraper | None = None

ALLOWED_FETCH_DOMAINS = {
    "docs.aws.amazon.com",
    "aws.amazon.com",
    "repost.aws",
}


def _get_scraper() -> AWSScraper:
    global _scraper
    if _scraper is None:
        _scraper = AWSScraper()
    return _scraper


def execute_tool(name: str, tool_input: dict) -> str:
    """Dispatch a tool call by name and return its string result."""
    if name == "search_aws_knowledge_base":
        return _search_knowledge_base(tool_input)
    elif name == "fetch_aws_page":
        return _fetch_aws_page(tool_input)
    else:
        return f"Unknown tool: {name}"


# ── Tool implementations ──────────────────────────────────────────────────────

def _search_knowledge_base(tool_input: dict) -> str:
    query = tool_input.get("query", "").strip()
    n_results = min(int(tool_input.get("n_results", 8)), 15)

    if not query:
        return "Error: query parameter is required."

    results = query_docs(query, n_results=n_results)

    if not results:
        return (
            "No results found in the local knowledge base for this query. "
            "The knowledge base may not yet contain documentation for this topic. "
            "Consider using fetch_aws_page with a relevant AWS documentation URL, "
            "or advise the user to ingest more documentation via the sidebar."
        )

    lines = [f"Found {len(results)} relevant documentation chunks:\n"]
    for i, r in enumerate(results, 1):
        tier = r.get("tier", 1)
        tier_label = {1: "Tier 1 — Primary Truth", 2: "Tier 2 — Implementation Guidance", 3: "Tier 3 — Solution Accelerator"}.get(tier, "Tier 1")
        lines.append(f"--- Chunk {i} (relevance: {r['relevance']:.2f}) ---")
        lines.append(f"Title: {r['title']}")
        lines.append(f"Source: {r['source_label']}  [{tier_label}]")
        lines.append(f"URL: {r['source_url']}")
        lines.append(f"Indexed on: {r['ingestion_date']}")
        lines.append("")
        # Truncate very long chunks to avoid token overflow
        content = r["content"]
        if len(content) > 2000:
            content = content[:2000] + "\n[... truncated ...]"
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


def _fetch_aws_page(tool_input: dict) -> str:
    url = tool_input.get("url", "").strip()

    if not url:
        return "Error: url parameter is required."

    # Validate domain for security
    parsed = urlparse(url)
    if parsed.netloc not in ALLOWED_FETCH_DOMAINS:
        return (
            f"Refused to fetch '{url}'. "
            f"Only AWS documentation domains are permitted: {', '.join(ALLOWED_FETCH_DOMAINS)}"
        )

    logger.info("Fetching live page: %s", url)
    scraper = _get_scraper()
    doc = scraper.scrape_page(url)

    if not doc:
        return f"Failed to fetch or parse content from: {url}"

    lines = [
        f"[LIVE PAGE — not indexed — fetched {doc['fetched_at']}]",
        f"Title: {doc['title']}",
        f"URL: {url}",
        "",
    ]

    content = doc["content_md"]
    # Limit to ~6000 chars to avoid overwhelming the context window
    if len(content) > 6000:
        content = content[:6000] + "\n\n[... page truncated — fetch a more specific URL for details ...]"

    lines.append(content)
    return "\n".join(lines)
