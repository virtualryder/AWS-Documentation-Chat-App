"""
Singleton factory for the ChromaDB persistent client and collection.

IMPORTANT: The same SentenceTransformerEmbeddingFunction instance must be used
at both ingestion and query time, or similarity scores will be meaningless.
This module enforces that by acting as the single source of truth.
"""

import sys
import logging
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CHROMA_PATH, COLLECTION_NAME, EMBEDDING_MODEL, TOP_K

logger = logging.getLogger(__name__)

# Module-level singletons — created once on first import
_client: chromadb.PersistentClient | None = None
_embedding_fn: SentenceTransformerEmbeddingFunction | None = None
_collection: chromadb.Collection | None = None


def _init():
    global _client, _embedding_fn, _collection
    if _collection is not None:
        return

    logger.info("Initialising ChromaDB at %s", CHROMA_PATH)
    Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)

    _client = chromadb.PersistentClient(path=CHROMA_PATH)
    _embedding_fn = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("Collection '%s' ready — %d chunks", COLLECTION_NAME, _collection.count())


def get_collection() -> chromadb.Collection:
    """Return the shared collection, initialising it on first call."""
    _init()
    return _collection


def get_chunk_count() -> int:
    """Return the current number of indexed chunks."""
    _init()
    return _collection.count()


def query_docs(text: str, n_results: int = TOP_K) -> list[dict]:
    """
    Semantic search over the indexed AWS documentation.

    Returns a list of dicts:
        {content, source_url, title, ingestion_date, source_label, relevance}
    sorted by descending relevance (1.0 = perfect match, 0.0 = no match).
    """
    _init()
    count = _collection.count()
    if count == 0:
        return []

    n = min(n_results, count)
    results = _collection.query(
        query_texts=[text],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({
            "content": doc,
            "source_url": meta.get("source_url", ""),
            "title": meta.get("title", "AWS Documentation"),
            "ingestion_date": meta.get("ingestion_date", "unknown"),
            "source_label": meta.get("source_label", "AWS Documentation"),
            "tier": meta.get("tier", 1),
            "relevance": round(1.0 - dist, 3),
        })

    # Sort highest relevance first (chromadb already does this, but be explicit)
    output.sort(key=lambda x: x["relevance"], reverse=True)
    return output
