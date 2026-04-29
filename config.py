import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent
DOCS_PATH = str(BASE_DIR / "docs")

# PostgreSQL (Railway injects DATABASE_URL automatically)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_NAME = "claude-sonnet-4-6"
MAX_TOKENS = 32000

# ChromaDB
COLLECTION_NAME = "aws_docs"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Chunking
CHUNK_SIZE = 800       # characters
CHUNK_OVERLAP = 100    # characters

# Retrieval
TOP_K = 8

# Scraping
REQUEST_DELAY = 0.75   # seconds between requests
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MIN_CONTENT_LENGTH = 300  # skip pages shorter than this
