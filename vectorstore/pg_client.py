"""
PostgreSQL + pgvector client — replaces ChromaDB.

Stores document chunks and their embeddings in a single Postgres database.
Schema:
  doc_chunks          — chunk text + vector embedding + metadata
  ingestion_manifest  — JSON manifest (last_updated, sources, total_chunks)

Environment variable required:
  DATABASE_URL  — standard Postgres connection string
                  e.g. postgresql://user:pass@host:5432/dbname
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATABASE_URL, EMBEDDING_MODEL, TOP_K

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384  # dimensionality of all-MiniLM-L6-v2

# Module-level singletons
_conn: Optional[psycopg2.extensions.connection] = None
_model: Optional[SentenceTransformer] = None


# ── Embedding model ───────────────────────────────────────────────────────────

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _embed(texts: list[str]) -> list[np.ndarray]:
    """Return a list of embedding vectors for the given texts."""
    model = _get_model()
    return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


# ── Database connection ───────────────────────────────────────────────────────

def _get_conn() -> psycopg2.extensions.connection:
    """Return a live connection, reconnecting if the previous one dropped."""
    global _conn
    try:
        if _conn is not None and not _conn.closed:
            # Quick liveness check
            with _conn.cursor() as cur:
                cur.execute("SELECT 1")
            return _conn
    except psycopg2.OperationalError:
        pass

    if not DATABASE_URL:
        raise ValueError(
            "DATABASE_URL is not set. "
            "Add it to your .env file or Railway environment variables."
        )

    logger.info("Connecting to PostgreSQL")
    _conn = psycopg2.connect(DATABASE_URL)
    register_vector(_conn)
    _init_schema(_conn)
    return _conn


def _init_schema(conn: psycopg2.extensions.connection) -> None:
    """Create tables and index if they don't already exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS doc_chunks (
                id              TEXT PRIMARY KEY,
                document        TEXT        NOT NULL,
                embedding       vector({EMBEDDING_DIM}),
                source_url      TEXT        DEFAULT '',
                title           TEXT        DEFAULT 'AWS Documentation',
                ingestion_date  TEXT        DEFAULT 'unknown',
                source_label    TEXT        DEFAULT 'AWS Documentation',
                tier            INTEGER     DEFAULT 1
            )
        """)

        # HNSW index — works with zero rows, no lists parameter required
        cur.execute("""
            CREATE INDEX IF NOT EXISTS doc_chunks_embedding_hnsw
            ON doc_chunks USING hnsw (embedding vector_cosine_ops)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_manifest (
                id          INTEGER PRIMARY KEY DEFAULT 1,
                data        JSONB       NOT NULL DEFAULT '{}',
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Ensure the singleton manifest row exists
        cur.execute("""
            INSERT INTO ingestion_manifest (id, data)
            VALUES (1, '{"last_updated": null, "total_chunks": 0, "sources": {}}')
            ON CONFLICT (id) DO NOTHING
        """)

    conn.commit()
    logger.info("PostgreSQL schema ready")


# ── Public API ────────────────────────────────────────────────────────────────

def get_chunk_count() -> int:
    """Return the number of indexed chunks."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM doc_chunks")
        return cur.fetchone()[0]


def upsert_chunks(chunks: list[dict]) -> None:
    """
    Embed and upsert a list of chunk dicts into doc_chunks.

    Each chunk dict must have:
        id        — unique string identifier
        document  — raw text content
        metadata  — dict with keys: source_url, title, ingestion_date,
                    source_label, tier (and optionally chunk_index)
    """
    if not chunks:
        return

    texts = [c["document"] for c in chunks]
    embeddings = _embed(texts)

    conn = _get_conn()
    rows = []
    for chunk, emb in zip(chunks, embeddings):
        meta = chunk.get("metadata", {})
        rows.append((
            chunk["id"],
            chunk["document"],
            emb.tolist(),
            meta.get("source_url", ""),
            meta.get("title", "AWS Documentation"),
            meta.get("ingestion_date", "unknown"),
            meta.get("source_label", "AWS Documentation"),
            int(meta.get("tier", 1)),
        ))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO doc_chunks
                (id, document, embedding, source_url, title,
                 ingestion_date, source_label, tier)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                document       = EXCLUDED.document,
                embedding      = EXCLUDED.embedding,
                source_url     = EXCLUDED.source_url,
                title          = EXCLUDED.title,
                ingestion_date = EXCLUDED.ingestion_date,
                source_label   = EXCLUDED.source_label,
                tier           = EXCLUDED.tier
            """,
            rows,
            template="(%s, %s, %s::vector, %s, %s, %s, %s, %s)",
        )
    conn.commit()
    logger.info("Upserted %d chunks", len(chunks))


def query_docs(text: str, n_results: int = TOP_K) -> list[dict]:
    """
    Semantic search over indexed AWS documentation.

    Returns a list of dicts:
        {content, source_url, title, ingestion_date, source_label, tier, relevance}
    sorted by descending relevance (1.0 = perfect match).
    """
    conn = _get_conn()

    count = get_chunk_count()
    if count == 0:
        return []

    n = min(n_results, count)
    embedding = _embed([text])[0].tolist()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                document,
                source_url,
                title,
                ingestion_date,
                source_label,
                tier,
                1 - (embedding <=> %s::vector) AS relevance
            FROM doc_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (embedding, embedding, n),
        )
        rows = cur.fetchall()

    return [
        {
            "content": row[0],
            "source_url": row[1],
            "title": row[2],
            "ingestion_date": row[3],
            "source_label": row[4],
            "tier": row[5],
            "relevance": round(float(row[6]), 3),
        }
        for row in rows
    ]


# ── Manifest (stored in Postgres, not on disk) ────────────────────────────────

def get_manifest() -> dict:
    """Load the ingestion manifest from the database."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM ingestion_manifest WHERE id = 1")
            row = cur.fetchone()
        if row:
            return row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as exc:
        logger.warning("Could not load manifest: %s", exc)
    return {"last_updated": None, "total_chunks": 0, "sources": {}}


def save_manifest(manifest: dict) -> None:
    """Persist the ingestion manifest to the database."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_manifest (id, data, updated_at)
            VALUES (1, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                data       = EXCLUDED.data,
                updated_at = NOW()
            """,
            (json.dumps(manifest),),
        )
    conn.commit()
