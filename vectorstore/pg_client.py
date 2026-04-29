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
import uuid
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

    _init_customer_schema(conn)
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


# ═══════════════════════════════════════════════════════════════════════════════
# Customer Workspace Schema + CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def _init_customer_schema(conn: psycopg2.extensions.connection) -> None:
    """Create customer workspace tables if they don't already exist."""
    with conn.cursor() as cur:
        # Customers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                industry     TEXT DEFAULT '',
                arch_context TEXT DEFAULT '',
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS customers_name_idx
            ON customers (name)
        """)

        # Conversations
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                title       TEXT DEFAULT 'New Conversation',
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS conversations_customer_idx
            ON conversations (customer_id, updated_at DESC)
        """)

        # Messages — stores both display turns and raw Anthropic tool turns
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                turn_index      INTEGER NOT NULL,
                role            TEXT NOT NULL,
                message_type    TEXT NOT NULL,
                content_text    TEXT,
                content_json    TEXT,
                display_content TEXT,
                is_display_turn BOOLEAN DEFAULT FALSE,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS messages_conv_idx
            ON messages (conversation_id, turn_index ASC)
        """)

        # Customer documents
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customer_documents (
                id             TEXT PRIMARY KEY,
                customer_id    TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                filename       TEXT NOT NULL,
                extracted_text TEXT NOT NULL,
                char_count     INTEGER DEFAULT 0,
                is_active      BOOLEAN DEFAULT TRUE,
                uploaded_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS customer_docs_idx
            ON customer_documents (customer_id, is_active)
        """)


# ── Customer CRUD ─────────────────────────────────────────────────────────────

def create_customer(name: str, industry: str = "", arch_context: str = "") -> str:
    customer_id = str(uuid.uuid4())
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customers (id, name, industry, arch_context) VALUES (%s, %s, %s, %s)",
            (customer_id, name.strip(), industry.strip(), arch_context.strip()),
        )
    conn.commit()
    return customer_id


def get_customers() -> list[dict]:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, industry, arch_context, created_at, updated_at "
            "FROM customers ORDER BY name ASC"
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "name": r[1], "industry": r[2],
         "arch_context": r[3], "created_at": r[4], "updated_at": r[5]}
        for r in rows
    ]


def get_customer(customer_id: str) -> dict | None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, industry, arch_context, created_at, updated_at "
            "FROM customers WHERE id = %s",
            (customer_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "industry": row[2],
            "arch_context": row[3], "created_at": row[4], "updated_at": row[5]}


def update_customer(customer_id: str, name: str, industry: str, arch_context: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE customers SET name=%s, industry=%s, arch_context=%s, updated_at=NOW() "
            "WHERE id=%s",
            (name.strip(), industry.strip(), arch_context.strip(), customer_id),
        )
    conn.commit()


def delete_customer(customer_id: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM customers WHERE id = %s", (customer_id,))
    conn.commit()


# ── Conversation CRUD ─────────────────────────────────────────────────────────

def create_conversation(customer_id: str, title: str = "New Conversation") -> str:
    conv_id = str(uuid.uuid4())
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (id, customer_id, title) VALUES (%s, %s, %s)",
            (conv_id, customer_id, title),
        )
    conn.commit()
    return conv_id


def get_conversations(customer_id: str) -> list[dict]:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, created_at, updated_at "
            "FROM conversations WHERE customer_id = %s "
            "ORDER BY updated_at DESC",
            (customer_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in rows]


def get_conversation(conv_id: str) -> dict | None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, customer_id, title, created_at, updated_at "
            "FROM conversations WHERE id = %s",
            (conv_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "customer_id": row[1], "title": row[2],
            "created_at": row[3], "updated_at": row[4]}


def update_conversation_title(conv_id: str, title: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE conversations SET title=%s, updated_at=NOW() WHERE id=%s",
            (title, conv_id),
        )
    conn.commit()


def bump_conversation(conv_id: str) -> None:
    """Touch updated_at to keep the conversation sorted to the top."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE conversations SET updated_at=NOW() WHERE id=%s", (conv_id,))
    conn.commit()


def delete_conversation(conv_id: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
    conn.commit()


# ── Message persistence ───────────────────────────────────────────────────────

def get_next_turn_index(conv_id: str) -> int:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(turn_index) + 1, 0) FROM messages WHERE conversation_id = %s",
            (conv_id,),
        )
        return cur.fetchone()[0]


def save_messages_batch(rows: list[dict]) -> None:
    """
    Persist a batch of message rows in a single transaction.

    Each row dict must have:
        conversation_id, turn_index, role, message_type,
        content_text (or None), content_json (or None),
        display_content (or None), is_display_turn
    """
    if not rows:
        return
    conn = _get_conn()
    data = [
        (
            str(uuid.uuid4()),
            r["conversation_id"],
            r["turn_index"],
            r["role"],
            r["message_type"],
            r.get("content_text"),
            r.get("content_json"),
            r.get("display_content"),
            r.get("is_display_turn", False),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO messages
                (id, conversation_id, turn_index, role, message_type,
                 content_text, content_json, display_content, is_display_turn)
            VALUES %s
            """,
            data,
        )
    conn.commit()


def get_messages(conv_id: str) -> list[dict]:
    """
    Return all messages for a conversation ordered by turn_index.
    Used to reconstruct both the UI display list and the Anthropic agent history.
    """
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT turn_index, role, message_type,
                   content_text, content_json, display_content, is_display_turn
            FROM messages
            WHERE conversation_id = %s
            ORDER BY turn_index ASC
            """,
            (conv_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "turn_index":      row[0],
            "role":            row[1],
            "message_type":    row[2],
            "content_text":    row[3],
            "content_json":    row[4],
            "display_content": row[5],
            "is_display_turn": row[6],
        }
        for row in rows
    ]


def clear_conversation_messages(conv_id: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
        cur.execute("UPDATE conversations SET updated_at=NOW() WHERE id=%s", (conv_id,))
    conn.commit()


# ── Customer document CRUD ────────────────────────────────────────────────────

def save_customer_document(customer_id: str, filename: str, extracted_text: str) -> str:
    doc_id = str(uuid.uuid4())
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_documents (id, customer_id, filename, extracted_text, char_count)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (doc_id, customer_id, filename, extracted_text, len(extracted_text)),
        )
    conn.commit()
    return doc_id


def get_customer_documents(customer_id: str) -> list[dict]:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, filename, extracted_text, char_count, is_active, uploaded_at "
            "FROM customer_documents WHERE customer_id = %s ORDER BY uploaded_at ASC",
            (customer_id,),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "filename": r[1], "extracted_text": r[2],
         "char_count": r[3], "is_active": r[4], "uploaded_at": r[5]}
        for r in rows
    ]


def toggle_customer_document(doc_id: str, is_active: bool) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("UPDATE customer_documents SET is_active=%s WHERE id=%s", (is_active, doc_id))
    conn.commit()


def delete_customer_document(doc_id: str) -> None:
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM customer_documents WHERE id = %s", (doc_id,))
    conn.commit()
