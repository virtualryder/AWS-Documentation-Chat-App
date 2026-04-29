"""
Fetches AWS documentation pages using requests + BeautifulSoup,
converts HTML to clean markdown, and respects crawl boundaries.
"""

import time
import re
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import markdownify

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    REQUEST_DELAY, REQUEST_TIMEOUT, USER_AGENT, MIN_CONTENT_LENGTH, DOCS_PATH
)
from scraper.aws_doc_urls import ALLOWED_DOMAINS, CRAWL_BOUNDARIES

logger = logging.getLogger(__name__)

# CSS selectors tried in order to find main content — most specific first
CONTENT_SELECTORS = [
    "div#main-col-body",
    "div#main-content",
    "div[role='main']",
    "main",
    "article",
    "div.awsui-article",
    "div.lb-col-main",
    "div.main-body",
    "div.content",
    "body",
]

# Tags to strip before converting to markdown
NOISE_TAGS = ["nav", "footer", "header", "aside", "script", "style", "noscript"]
NOISE_CLASSES = re.compile(
    r"(nav|sidebar|footer|header|breadcrumb|menu|toc|feedback|"
    r"cookie|banner|advertisement|social|share|related|subnav|"
    r"awsnav|lb-nav|lb-footer|lb-header)",
    re.IGNORECASE,
)


class AWSScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_time = 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def scrape_page(self, url: str) -> dict | None:
        """
        Fetch a single URL and return a doc dict, or None on failure.

        Returns:
            {url, title, content_md, source_url, fetched_at, word_count}
        """
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        title = self._extract_title(soup)
        content_md = self._extract_content(soup, url)

        if len(content_md) < MIN_CONTENT_LENGTH:
            logger.debug("Skipping %s — content too short (%d chars)", url, len(content_md))
            return None

        return {
            "url": url,
            "title": title,
            "content_md": content_md,
            "source_url": url,
            "fetched_at": datetime.now().strftime("%Y-%m-%d"),
            "word_count": len(content_md.split()),
        }

    def crawl(self, seed_url: str, max_pages: int = 30) -> list[dict]:
        """
        BFS crawl starting at seed_url, staying within allowed boundaries.
        Returns a list of doc dicts.
        """
        visited: set[str] = set()
        queue: list[str] = [self._normalise(seed_url)]
        results: list[dict] = []

        seed_parsed = urlparse(seed_url)
        base_path = self._base_path(seed_parsed)

        while queue and len(results) < max_pages:
            url = queue.pop(0)
            norm = self._normalise(url)
            if norm in visited:
                continue
            visited.add(norm)

            doc = self.scrape_page(url)
            if doc:
                results.append(doc)
                # Discover sub-links within boundary
                sub_links = self._extract_links(doc["content_md"], url, base_path)
                for link in sub_links:
                    if self._normalise(link) not in visited:
                        queue.append(link)

        logger.info("Crawl complete: %d pages from %s", len(results), seed_url)
        return results

    def save_to_disk(self, docs: list[dict], source_label: str) -> None:
        """
        Persist downloaded docs to docs/<YYYY-MM-DD>/<source_label>/<slug>.md
        so the user has a dated audit trail of what was downloaded.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        safe_label = re.sub(r"[^\w\-]", "_", source_label)
        out_dir = Path(DOCS_PATH) / today / safe_label
        out_dir.mkdir(parents=True, exist_ok=True)

        for doc in docs:
            slug = self._url_to_slug(doc["url"])
            filepath = out_dir / f"{slug}.md"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"---\n")
                f.write(f"title: {doc['title']}\n")
                f.write(f"source_url: {doc['url']}\n")
                f.write(f"fetched_at: {doc['fetched_at']}\n")
                f.write(f"---\n\n")
                f.write(f"# {doc['title']}\n\n")
                f.write(doc["content_md"])

    # ── Private helpers ───────────────────────────────────────────────────

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _extract_title(self, soup: BeautifulSoup) -> str:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        title_tag = soup.find("title")
        if title_tag:
            # Strip boilerplate like " - AWS Documentation"
            raw = title_tag.get_text(strip=True)
            return re.sub(r"\s*[-|].*$", "", raw).strip()
        return "Untitled"

    def _extract_content(self, soup: BeautifulSoup, url: str) -> str:
        # Strip noise elements
        for tag in soup.find_all(NOISE_TAGS):
            tag.decompose()
        for tag in soup.find_all(class_=NOISE_CLASSES):
            tag.decompose()
        for tag in soup.find_all(id=NOISE_CLASSES):
            tag.decompose()

        # Find the main content container
        main = None
        for selector in CONTENT_SELECTORS:
            main = soup.select_one(selector)
            if main:
                break

        if not main:
            return ""

        # Convert to markdown
        md = markdownify.markdownify(
            str(main),
            heading_style="ATX",
            bullets="-",
            strip=["img", "button", "input", "form"],
        )

        # Clean up
        md = re.sub(r"\n{3,}", "\n\n", md)
        md = re.sub(r"[ \t]+\n", "\n", md)
        md = re.sub(r"\[.*?\]\(#.*?\)", "", md)  # remove in-page anchor links
        return md.strip()

    def _extract_links(self, content_md: str, base_url: str, base_path: str) -> list[str]:
        """Extract markdown links that stay within the crawl boundary.

        AWS documentation uses mostly relative hrefs. After markdownify
        conversion those appear as [text](/path/to/page.html) or
        [text](../sibling.html) — not as absolute https:// URLs.
        We resolve every href against base_url before filtering.
        """
        links = []

        for match in re.finditer(r"\[.*?\]\(([^)\s]+)\)", content_md):
            href = match.group(1).strip()

            # Skip anchors, mailto, javascript, and empty hrefs
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue

            # Resolve relative hrefs to absolute URLs
            absolute = urljoin(base_url, href)
            p = urlparse(absolute)

            if p.netloc not in ALLOWED_DOMAINS:
                continue

            # Strip query strings and fragments for deduplication
            clean = f"https://{p.netloc}{p.path}"

            # Check crawl boundary
            boundaries = CRAWL_BOUNDARIES.get(p.netloc, [])
            in_boundary = any(p.path.startswith(b) for b in boundaries)
            if not in_boundary:
                continue

            # Stay within the base path of the seed to avoid crawling
            # the entire AWS docs site from a single seed
            if p.path.startswith(base_path):
                links.append(clean)

        return list(set(links))

    def _base_path(self, parsed) -> str:
        """Return the path prefix (up to the 4th segment) to scope crawls."""
        parts = [p for p in parsed.path.split("/") if p]
        return "/" + "/".join(parts[:3]) + "/"

    def _normalise(self, url: str) -> str:
        p = urlparse(url)
        return f"https://{p.netloc}{p.path}".rstrip("/")

    def _url_to_slug(self, url: str) -> str:
        p = urlparse(url)
        slug = p.path.strip("/").replace("/", "_")
        return re.sub(r"[^\w\-]", "_", slug)[:100] or "index"
