# AWS Documentation Chat App

An agentic RAG (Retrieval-Augmented Generation) application that lets you ask natural-language architecture questions and receive grounded, cited answers drawn directly from official AWS documentation.

Built with **Claude Sonnet 4.6** (Anthropic) + **ChromaDB** + **Streamlit**.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40%2B-red)
![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5%2B-green)
![Claude](https://img.shields.io/badge/Claude-Sonnet%204.6-purple)

---

## What It Does

The app acts as an **AWS Solutions Architect on demand**. You describe your customer's environment (or paste an architecture doc), ask a question, and the agent:

1. **Searches** a locally indexed vector knowledge base of AWS documentation
2. **Fetches live AWS docs pages** when the KB is sparse or content may be stale
3. **Synthesizes** a structured 11-section architecture response grounded entirely in retrieved documentation
4. **Labels every claim** — `✅ Documented Fact`, `💡 Design Recommendation`, `🔄 Alternative Option`, or `⚠️ Assumption` — so you always know what's confirmed vs. inferred
5. **Cites every source** inline with retrieval dates and flags content freshness

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Streamlit Frontend                    │
│  Sidebar: topic selector · doc upload · customer context │
│  Main: chat interface · live research status feed        │
└────────────────────┬─────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────────┐
│               Claude Sonnet 4.6 Agent Loop               │
│  System prompt enforces: research-first, grounded only   │
│  Tools: search_aws_knowledge_base · fetch_aws_page       │
└──────────┬──────────────────────────┬────────────────────┘
           │                          │
           ▼                          ▼
┌─────────────────────┐   ┌──────────────────────────────┐
│  ChromaDB (local)   │   │  Live AWS Documentation      │
│  SentenceTransformer│   │  docs.aws.amazon.com         │
│  all-MiniLM-L6-v2   │   │  aws.amazon.com/solutions    │
│  Cosine similarity  │   │  aws.amazon.com/architecture │
└─────────────────────┘   └──────────────────────────────┘
           ▲
           │  Index pipeline
┌──────────┴───────────────────────────────────────────────┐
│  Ingestion Pipeline                                      │
│  BFS crawler → HTML→Markdown → chunker → embedder       │
│  30+ AWS services · 3 source tiers · manifest tracking  │
└──────────────────────────────────────────────────────────┘
```

### Module layout

```
aws-documentation-chat-app/
├── app.py                    # Streamlit UI entry point
├── config.py                 # Paths, model, chunking, retrieval settings
├── requirements.txt
├── .env.example              # Copy to .env and add your Anthropic key
│
├── agent/
│   ├── chat_agent.py         # Agentic loop (streaming Claude API calls)
│   ├── tools.py              # Tool schemas passed to Claude
│   └── tool_executor.py      # Python implementations of each tool
│
├── scraper/
│   ├── aws_scraper.py        # BFS crawler: HTML fetch → clean markdown
│   └── aws_doc_urls.py       # 34 seed URLs, crawl boundaries, topic keyword map
│
├── ingestion/
│   ├── ingest_pipeline.py    # Orchestrates crawl → chunk → embed → upsert
│   ├── chunker.py            # Overlapping character-window chunking
│   └── document_parser.py   # PDF / DOCX / TXT text extraction (customer uploads)
│
└── vectorstore/
    └── chroma_client.py      # ChromaDB singleton + semantic query interface
```

---

## Key Features

### Grounding & Anti-Hallucination
- Agent is **required** to search the knowledge base before drafting any answer
- All responses labeled with confidence level (`✅ / 💡 / 🔄 / ⚠️`)
- Explicit uncertainty language when docs don't cover a topic
- **Freshness check**: for rapidly-evolving services (Bedrock, SageMaker, EKS), the agent re-fetches the live AWS page if the indexed content is older than 14 days

### Source Tier System
| Tier | Source | Used For |
|---|---|---|
| **Tier 1** | AWS product docs, Bedrock docs | What a service does, APIs, limits, exact setup |
| **Tier 2** | AWS Prescriptive Guidance, Architecture Center | Design patterns, trade-offs, step-by-step guidance |
| **Tier 3** | AWS Solutions Library | Packaged solutions, repeatable deployment patterns |

If a Tier 1 source contradicts Tier 2/3, the agent says so explicitly.

### 34 Indexed Services (out of the box)
Lambda, EC2, ECS, EKS, S3, EFS, RDS, DynamoDB, Redshift, ElastiCache, VPC, Route 53, CloudFront, API Gateway, IAM, KMS, Cognito, GuardDuty, Glue, Kinesis, Athena, SQS, SNS, EventBridge, Step Functions, SageMaker, Bedrock, Bedrock AgentCore, CloudFormation, CloudWatch, CloudTrail, AWS Prescriptive Guidance, AWS Solutions Library, AWS Reference Architecture

### Structured 11-Section Architecture Response
Every architecture question generates:
1. Customer Situation Summary
2. Key Assumptions
3. Recommended Architecture (with ASCII diagram)
4. Two Alternative Architectures
5. Why This Architecture Fits
6. Component Deep-Dive (plain-English + analogies + common mistakes)
7. Step-by-Step Implementation Guide
8. Security, Networking & IAM
9. Cost & Operations
10. Trade-offs Summary Table
11. Sources & Freshness Note

### Customer Context
- Paste a description of the customer's current environment (servers, databases, goals) into the sidebar — it's injected into every message
- Upload architecture docs, RFPs, or notes (PDF, DOCX, TXT, MD) — text is extracted and added to context automatically

---

## Getting Started

### Prerequisites
- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/settings/keys)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/AWS-Documentation-Chat-App.git
cd AWS-Documentation-Chat-App

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### Run

```bash
streamlit run app.py
```

### Index Your First Service

1. Open the app in your browser (default: `http://localhost:8501`)
2. In the sidebar, expand **Select Topics / Services**
3. Check the services you want (e.g. Lambda, S3, VPC)
4. Set **Max pages per topic** (20 is a good starting point)
5. Click **Fetch & Index Documentation**
6. Once indexing completes, start asking questions

### CLI Ingestion (alternative)

```bash
# Ingest specific services
python -m ingestion.ingest_pipeline --keys lambda s3 vpc --max-pages 20

# Ingest by topic keywords
python -m ingestion.ingest_pipeline --topics serverless "data lake" security

# Ingest everything (slow — ~30 min)
python -m ingestion.ingest_pipeline --all --max-pages 20
```

---

## Example Questions

> *"We run a 3-tier web app on-prem with SQL Server, IIS, and Windows file servers. We want to migrate to AWS, target 99.9% uptime, and reduce OpEx by 30%. Where do we start?"*

> *"Design a serverless data pipeline that ingests clickstream events, enriches them with ML predictions, and loads them into a data warehouse for BI reporting."*

> *"What's the difference between SQS and EventBridge, and when would I use each in a microservices architecture?"*

> *"Walk me through setting up least-privilege IAM roles for an ECS Fargate task that reads from S3 and writes to DynamoDB."*

---

## Configuration Reference

| Setting | File | Default | Description |
|---|---|---|---|
| `MODEL_NAME` | `config.py` | `claude-sonnet-4-6` | Claude model to use |
| `MAX_TOKENS` | `config.py` | `32000` | Max response tokens |
| `TOP_K` | `config.py` | `8` | Chunks retrieved per KB search |
| `CHUNK_SIZE` | `config.py` | `800` | Characters per chunk |
| `CHUNK_OVERLAP` | `config.py` | `100` | Overlap between chunks |
| `REQUEST_DELAY` | `config.py` | `0.75s` | Delay between scraper requests |
| `MIN_CONTENT_LENGTH` | `config.py` | `300` | Skip pages shorter than this |

---

## Notes

- The ChromaDB vector store (`chroma_store/`) and downloaded markdown (`docs/`) are created locally and excluded from version control via `.gitignore`
- Re-running ingestion on the same service upserts by content hash — no duplicate chunks
- A `docs/manifest.json` tracks what was indexed and when, shown in the sidebar

---

## Tech Stack

| Component | Technology |
|---|---|
| LLM | Claude Sonnet 4.6 (Anthropic) via streaming API |
| Agent framework | Native Anthropic tool use (no LangChain) |
| Vector store | ChromaDB (persistent, local) |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers) |
| Web scraping | requests + BeautifulSoup4 + markdownify |
| Frontend | Streamlit |
| Doc parsing | pdfplumber (PDF), python-docx (Word) |

---

## License

MIT
