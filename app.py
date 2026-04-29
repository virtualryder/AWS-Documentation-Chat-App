"""
AWS Expert Architect — Streamlit Chat Application

Run with:
    streamlit run app.py
"""

import sys
import logging
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="AWS Expert Architect",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

logging.basicConfig(level=logging.INFO)

# ── Session state initialisation ──────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "agent" not in st.session_state:
    st.session_state.agent = None
if "customer_context" not in st.session_state:
    st.session_state.customer_context = ""
if "kb_count" not in st.session_state:
    st.session_state.kb_count = 0
if "uploaded_doc_text" not in st.session_state:
    st.session_state.uploaded_doc_text = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_agent():
    """Lazily initialise the chat agent (one per session)."""
    if st.session_state.agent is None:
        try:
            from agent.chat_agent import AWSChatAgent
            st.session_state.agent = AWSChatAgent()
        except ValueError as e:
            st.error(str(e))
            st.stop()
    return st.session_state.agent


def refresh_kb_count():
    try:
        from vectorstore.chroma_client import get_chunk_count
        st.session_state.kb_count = get_chunk_count()
    except Exception:
        st.session_state.kb_count = 0


def load_manifest() -> dict:
    try:
        import json
        from config import DOCS_PATH
        manifest_path = Path(DOCS_PATH) / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def build_full_customer_context() -> str:
    """Combine typed context with any uploaded document text."""
    parts = []
    if st.session_state.customer_context.strip():
        parts.append(st.session_state.customer_context.strip())
    if st.session_state.uploaded_doc_text.strip():
        parts.append(st.session_state.uploaded_doc_text.strip())
    return "\n\n".join(parts)


def run_ingestion(seed_keys, max_pages, save_to_disk):
    """Called by the sidebar ingestion button. Returns a summary dict."""
    from ingestion.ingest_pipeline import run_ingestion as _run

    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    def progress_callback(message, current, total):
        if total > 0:
            progress_bar.progress(current / total)
        status_text.text(message)

    summary = _run(
        seed_keys=seed_keys,
        max_pages_per_seed=max_pages,
        save_to_disk=save_to_disk,
        progress_callback=progress_callback,
    )

    progress_bar.progress(1.0)
    status_text.empty()
    return summary


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("☁️ AWS Expert Architect")
    st.caption("Powered by Claude Sonnet 4.6 + RAG")
    st.divider()

    # Knowledge base stats
    refresh_kb_count()
    manifest = load_manifest()
    sources = manifest.get("sources", {})

    col1, col2 = st.columns(2)
    col1.metric("Indexed Chunks", f"{st.session_state.kb_count:,}")
    col2.metric("Sources", len(sources))

    if st.session_state.kb_count == 0:
        st.warning("Knowledge base is empty. Ingest documentation below.")
    else:
        st.success("Knowledge base ready")
        if sources:
            tier_counts = {1: 0, 2: 0, 3: 0}
            for s in sources.values():
                tier_counts[s.get("tier", 1)] += 1
            st.caption(
                f"Tier 1 (Primary): {tier_counts[1]} · "
                f"Tier 2 (Guidance): {tier_counts[2]} · "
                f"Tier 3 (Solutions): {tier_counts[3]}"
            )
            if manifest.get("last_updated"):
                from datetime import datetime
                updated = manifest["last_updated"][:10]
                st.caption(f"Last updated: {updated}")

    st.divider()

    # ── Ingestion section ─────────────────────────────────────────────────
    st.subheader("Ingest Documentation")
    st.caption("Select topics to download and index from AWS documentation sites.")

    with st.expander("Select Topics / Services", expanded=st.session_state.kb_count == 0):
        from scraper.aws_doc_urls import SEED_URLS, TOPIC_KEYWORD_MAP

        # Group seeds by category for a cleaner UI
        CATEGORIES = {
            "Compute & Containers": ["lambda", "ec2", "ecs", "eks"],
            "Storage": ["s3", "efs"],
            "Databases": ["rds", "dynamodb", "redshift", "elasticache"],
            "Networking": ["vpc", "route53", "cloudfront", "api_gateway"],
            "Security & Identity": ["iam", "kms", "cognito", "guardduty"],
            "Analytics & Data": ["glue", "kinesis", "athena"],
            "Messaging & Integration": ["sqs", "sns", "eventbridge", "step_functions"],
            "AI / ML": ["sagemaker", "bedrock", "bedrock_agentcore"],
            "DevOps & Management": ["cloudformation", "cloudwatch", "cloudtrail"],
            "Special Sources": ["prescriptive_guidance", "solutions_library", "reference_architecture"],
        }

        selected_keys: list[str] = []
        for category, keys in CATEGORIES.items():
            with st.container():
                st.markdown(f"**{category}**")
                cols = st.columns(2)
                for i, key in enumerate(keys):
                    info = SEED_URLS.get(key, {})
                    label = info.get("name", key).replace(" Developer Guide", "").replace(" User Guide", "").replace(" Documentation", "")
                    if cols[i % 2].checkbox(label, key=f"chk_{key}"):
                        selected_keys.append(key)

        st.markdown("---")
        custom_topics = st.text_input(
            "Or type topic keywords",
            placeholder="e.g. serverless, data lake, security",
            help="Comma-separated topics — mapped to the most relevant seed URLs.",
        )

        max_pages = st.slider(
            "Max pages per topic",
            min_value=5,
            max_value=100,
            value=20,
            step=5,
            help="More pages = better coverage but slower ingestion.",
        )

        save_to_disk = st.checkbox(
            "Save markdown to docs/ folder",
            value=True,
            help="Keeps a dated copy of everything downloaded.",
        )

    ingest_btn = st.button("Fetch & Index Documentation", type="primary", use_container_width=True)

    if ingest_btn:
        # Resolve custom topic keywords to seed keys
        final_keys = list(selected_keys)
        if custom_topics:
            from ingestion.ingest_pipeline import resolve_seed_keys
            topic_list = [t.strip() for t in custom_topics.split(",") if t.strip()]
            resolved = resolve_seed_keys(topic_list)
            final_keys.extend(resolved)

        # Deduplicate
        final_keys = list(dict.fromkeys(final_keys))

        if not final_keys:
            st.sidebar.warning("Select at least one topic or enter keywords.")
        else:
            with st.spinner(f"Ingesting {len(final_keys)} topic(s)..."):
                summary = run_ingestion(final_keys, max_pages, save_to_disk)

            refresh_kb_count()
            st.sidebar.success(
                f"Done! {summary['chunks_indexed']:,} chunks indexed "
                f"from {summary['pages_scraped']} pages."
            )
            if summary["skipped"]:
                st.sidebar.warning(f"Skipped: {', '.join(summary['skipped'])}")
            st.rerun()

    st.divider()

    # ── Customer document upload ──────────────────────────────────────────
    st.subheader("Upload Customer Documents")
    st.caption("Upload architecture docs, diagrams notes, or RFPs. Text is extracted and added to the customer context.")

    uploaded_files = st.file_uploader(
        "Upload files",
        type=["pdf", "docx", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="Supported: PDF, Word (.docx), plain text (.txt, .md)",
    )

    if uploaded_files:
        from ingestion.document_parser import extract_text, format_uploaded_docs
        extracted = []
        for f in uploaded_files:
            text = extract_text(f.read(), f.name)
            extracted.append((f.name, text))
        st.session_state.uploaded_doc_text = format_uploaded_docs(extracted)
        st.success(f"{len(uploaded_files)} file(s) loaded into context.")
        with st.expander("Preview extracted text"):
            st.text(st.session_state.uploaded_doc_text[:2000] + (
                "\n...[truncated]" if len(st.session_state.uploaded_doc_text) > 2000 else ""
            ))
    elif st.session_state.uploaded_doc_text:
        if st.button("Clear uploaded docs"):
            st.session_state.uploaded_doc_text = ""
            st.rerun()
        else:
            st.caption("Uploaded doc text is active in context.")

    st.divider()

    # ── Customer context ──────────────────────────────────────────────────
    st.subheader("Customer Architecture Context")
    st.caption("Describe the customer's current environment. This is sent with every message.")
    st.session_state.customer_context = st.text_area(
        label="customer_context_input",
        label_visibility="collapsed",
        value=st.session_state.customer_context,
        height=180,
        placeholder=(
            "Example:\n"
            "We run a 3-tier web app on-premises with:\n"
            "- SQL Server 2019 (4TB data, 5,000 transactions/day)\n"
            "- IIS web servers (10 VMs, 8 vCPU, 32GB RAM each)\n"
            "- Windows file servers (50TB unstructured data)\n"
            "Goal: migrate to AWS, target 99.9% uptime, reduce OpEx by 30%."
        ),
    )

    st.divider()

    col_a, col_b = st.columns(2)
    if col_a.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.agent:
            st.session_state.agent.clear_history()
        st.rerun()

    if col_b.button("Refresh KB", use_container_width=True):
        refresh_kb_count()
        st.rerun()


# ── Main chat interface ───────────────────────────────────────────────────────

st.markdown(
    "<h1 style='margin-bottom:0'>☁️ AWS Expert Architect</h1>",
    unsafe_allow_html=True,
)
st.caption(
    "Ask me about AWS architectures, services, and implementation steps. "
    "I'll search indexed documentation before answering and cite every source."
)

full_ctx = build_full_customer_context()
if full_ctx:
    with st.expander(
        f"Active Customer Context ({len(full_ctx):,} chars)", expanded=False
    ):
        st.text(full_ctx[:3000] + ("\n...[truncated]" if len(full_ctx) > 3000 else ""))

st.divider()

# Render message history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑‍💼" if msg["role"] == "user" else "☁️"):
        st.markdown(msg["content"])

# ── Chat input ────────────────────────────────────────────────────────────────

prompt = st.chat_input(
    "Ask an AWS architecture question...",
    disabled=False,
)

if prompt:
    # Show user message immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍💼"):
        st.markdown(prompt)

    # Get agent response, showing research steps in a persistent status widget
    agent = get_agent()

    with st.chat_message("assistant", avatar="☁️"):

        step_count = [0]

        with st.status("🔬 Researching AWS documentation...", expanded=True) as research_status:

            def status_callback(msg: str):
                step_count[0] += 1
                st.write(msg)

            response = agent.chat(
                user_message=prompt,
                customer_context=build_full_customer_context(),
                status_callback=status_callback,
            )

            research_status.update(
                label=f"Research complete — {step_count[0]} steps",
                state="complete",
                expanded=False,
            )

        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
