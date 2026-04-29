"""
Splits markdown documents into overlapping character-window chunks,
each tagged with source metadata for citation in responses.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_document(doc: dict) -> list[dict]:
    """
    Split a single doc dict into chunks.

    Args:
        doc: {url, title, content_md, fetched_at, source_label (optional)}

    Returns:
        List of chunk dicts compatible with ChromaDB upsert:
        {id, document, metadata: {source_url, title, chunk_index, ingestion_date, source_label}}
    """
    text = doc.get("content_md", "").strip()
    if not text:
        return []

    url = doc.get("url", "")
    title = doc.get("title", "Untitled")
    fetched_at = doc.get("fetched_at", "unknown")
    source_label = doc.get("source_label", "AWS Documentation")

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunk_text = text[start:end].strip()

        if len(chunk_text) > 50:  # skip near-empty trailing chunks
            chunk_id = hashlib.md5(f"{url}#{len(chunks)}".encode()).hexdigest()
            chunks.append({
                "id": chunk_id,
                "document": chunk_text,
                "metadata": {
                    "source_url": url,
                    "title": title,
                    "chunk_index": len(chunks),
                    "ingestion_date": fetched_at,
                    "source_label": source_label,
                },
            })

        if end >= len(text):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP

    return chunks


def chunk_documents(docs: list[dict]) -> list[dict]:
    """Chunk a list of documents and return a flat list of chunk dicts."""
    all_chunks = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc))
    return all_chunks
