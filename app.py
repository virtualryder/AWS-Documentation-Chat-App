"""
AWS Expert Architect — Streamlit Chat Application
Customer-workspace edition: persistent customers, conversations, and documents.

Run with:
    streamlit run app.py
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title="AWS Expert Architect",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

logging.basicConfig(level=logging.INFO)

# ── Session state ─────────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        # Workspace
        "ws_customer_id":       None,
        "ws_conversation_id":   None,
        "ws_agent":             None,
        "ws_messages":          [],   # display messages for current conversation
        # KB
        "kb_count":             0,
        # UI flags
        "show_new_customer":    False,
        "show_edit_customer":   False,
        "confirm_delete_conv":  None,  # conv_id pending delete confirmation
        "confirm_delete_cust":  False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── DB helpers (imported lazily to avoid startup failures) ────────────────────

def _db():
    """Return all needed pg_client functions in one import."""
    from vectorstore import pg_client
    return pg_client


# ── Utility functions ─────────────────────────────────────────────────────────

def _make_title(prompt: str) -> str:
    """Generate a short conversation title from the first user message."""
    clean = prompt.strip().replace("\n", " ")
    if len(clean) <= 58:
        return clean
    cut = clean[:58].rfind(" ")
    return clean[:cut if cut > 20 else 58] + "…"


def _build_customer_context(customer: dict) -> str:
    """Combine a customer's arch_context with their active uploaded documents."""
    parts = []
    arch = (customer.get("arch_context") or "").strip()
    if arch:
        parts.append(arch)
    try:
        docs = _db().get_customer_documents(customer["id"])
        for doc in docs:
            if doc.get("is_active"):
                parts.append(
                    f"--- Uploaded document: {doc['filename']} ---\n{doc['extracted_text']}"
                )
    except Exception:
        pass
    return "\n\n".join(parts)


def _load_conversation(conv_id: str) -> None:
    """
    Load a conversation from the DB into session state.
    Rebuilds the AWSChatAgent history from stored message rows, including
    the exact Anthropic tool-use / tool-result block structures.
    """
    from agent.chat_agent import AWSChatAgent

    db_msgs = _db().get_messages(conv_id)

    # Rebuild agent history
    agent = AWSChatAgent()
    agent.history = []
    for m in db_msgs:
        if m["message_type"] == "text":
            agent.history.append({"role": m["role"], "content": m["content_text"]})
        else:
            # tool_use or tool_result — restore the exact block structure
            agent.history.append({
                "role": m["role"],
                "content": json.loads(m["content_json"]),
            })

    # UI display messages (only turns the user sees)
    st.session_state.ws_messages = [
        {"role": m["role"], "content": m["display_content"]}
        for m in db_msgs if m["is_display_turn"]
    ]

    st.session_state.ws_agent = agent
    st.session_state.ws_conversation_id = conv_id


def _save_exchange(conv_id: str, user_prompt: str,
                   new_history_entries: list, assistant_response: str) -> None:
    """
    Persist a complete user→agent exchange to the messages table in one transaction.
    Handles text turns, tool-use turns, and tool-result turns correctly.
    """
    db = _db()
    next_idx = db.get_next_turn_index(conv_id)
    rows = []

    for i, entry in enumerate(new_history_entries):
        role = entry["role"]
        content = entry["content"]

        if isinstance(content, str):
            # Plain text turn
            is_user = role == "user"
            rows.append({
                "conversation_id": conv_id,
                "turn_index":      next_idx + i,
                "role":            role,
                "message_type":    "text",
                "content_text":    content,
                "content_json":    None,
                "display_content": user_prompt if is_user else assistant_response,
                "is_display_turn": True,
            })
        else:
            # Tool-use (assistant) or tool-result (user) — store full JSON
            msg_type = "tool_use" if role == "assistant" else "tool_result"
            rows.append({
                "conversation_id": conv_id,
                "turn_index":      next_idx + i,
                "role":            role,
                "message_type":    msg_type,
                "content_text":    None,
                "content_json":    json.dumps(content, default=str),
                "display_content": None,
                "is_display_turn": False,
            })

    db.save_messages_batch(rows)
    db.bump_conversation(conv_id)


def _refresh_kb_count():
    try:
        st.session_state.kb_count = _db().get_chunk_count()
    except Exception:
        st.session_state.kb_count = 0


def _select_customer(customer_id: str | None) -> None:
    """Switch to a different customer, auto-loading their most recent conversation."""
    st.session_state.ws_customer_id = customer_id
    st.session_state.ws_conversation_id = None
    st.session_state.ws_agent = None
    st.session_state.ws_messages = []
    st.session_state.show_edit_customer = False
    st.session_state.confirm_delete_conv = None

    # Auto-load most recent conversation (get_conversations returns newest first)
    if customer_id:
        try:
            convs = _db().get_conversations(customer_id)
            if convs:
                _load_conversation(convs[0]["id"])
        except Exception:
            pass


def _select_conversation(conv_id: str) -> None:
    """Open a conversation, rebuilding agent history from DB."""
    _load_conversation(conv_id)


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### ☁️ AWS Expert Architect")
    st.caption("Powered by Claude + RAG over live AWS documentation")
    st.divider()

    # ── Customer workspace ────────────────────────────────────────────────────
    st.markdown("**Workspace**")

    db = _db()
    try:
        all_customers = db.get_customers()
    except Exception:
        all_customers = []

    customer_names = [c["name"] for c in all_customers]
    customer_ids   = [c["id"]   for c in all_customers]

    # Determine current selectbox index
    current_cid = st.session_state.ws_customer_id
    try:
        current_idx = customer_ids.index(current_cid) + 1  # +1 for the placeholder
    except ValueError:
        current_idx = 0

    col_sel, col_new = st.columns([3, 1])
    selected_idx = col_sel.selectbox(
        "Customer",
        options=range(len(all_customers) + 1),
        format_func=lambda i: "— select —" if i == 0 else customer_names[i - 1],
        index=current_idx,
        label_visibility="collapsed",
    )
    if col_new.button("＋", help="Create new customer", use_container_width=True):
        st.session_state.show_new_customer = True
        st.session_state.show_edit_customer = False

    # Apply customer selection
    if selected_idx == 0:
        if current_cid is not None:
            _select_customer(None)
            st.rerun()
    else:
        chosen_id = customer_ids[selected_idx - 1]
        if chosen_id != current_cid:
            _select_customer(chosen_id)
            st.rerun()

    # ── Conversations (only when a customer is selected) ──────────────────────
    if st.session_state.ws_customer_id:
        st.divider()
        cid = st.session_state.ws_customer_id
        cvid = st.session_state.ws_conversation_id

        col_ch, col_cn = st.columns([3, 1])
        col_ch.markdown("**Conversations**")
        if col_cn.button("＋", key="new_conv", help="New conversation", use_container_width=True):
            new_cvid = db.create_conversation(cid)
            _select_conversation(new_cvid)
            st.rerun()

        try:
            convs = db.get_conversations(cid)
        except Exception:
            convs = []

        if not convs:
            st.caption("No conversations yet. Click ＋ to start one.")
        else:
            for conv in convs:
                is_active = conv["id"] == cvid
                label = ("▶ " if is_active else "   ") + conv["title"]

                # Pending delete confirmation
                if st.session_state.confirm_delete_conv == conv["id"]:
                    st.warning(f"Delete **{conv['title']}**?")
                    dc1, dc2 = st.columns(2)
                    if dc1.button("Yes, delete", key=f"del_yes_{conv['id']}", use_container_width=True):
                        db.delete_conversation(conv["id"])
                        if cvid == conv["id"]:
                            st.session_state.ws_conversation_id = None
                            st.session_state.ws_agent = None
                            st.session_state.ws_messages = []
                        st.session_state.confirm_delete_conv = None
                        st.rerun()
                    if dc2.button("Cancel", key=f"del_no_{conv['id']}", use_container_width=True):
                        st.session_state.confirm_delete_conv = None
                        st.rerun()
                else:
                    bc1, bc2 = st.columns([5, 1])
                    if bc1.button(label, key=f"conv_{conv['id']}", use_container_width=True):
                        _select_conversation(conv["id"])
                        st.rerun()
                    if bc2.button("✕", key=f"del_{conv['id']}", help="Delete", use_container_width=True):
                        st.session_state.confirm_delete_conv = conv["id"]
                        st.rerun()

    # ── Knowledge base (collapsed) ────────────────────────────────────────────
    st.divider()
    _refresh_kb_count()
    kb_count = st.session_state.kb_count

    with st.expander(f"📚 Knowledge Base — {kb_count:,} chunks", expanded=False):
        try:
            manifest = db.get_manifest()
            sources = manifest.get("sources", {})
            col1, col2 = st.columns(2)
            col1.metric("Chunks", f"{kb_count:,}")
            col2.metric("Sources", len(sources))
            if manifest.get("last_updated"):
                st.caption(f"Updated: {manifest['last_updated'][:10]}")
        except Exception:
            st.caption("KB stats unavailable")

        if kb_count == 0:
            st.info("⏳ Initial indexing in progress (~15 min on first boot).")

        from scraper.aws_doc_urls import SEED_URLS

        AUTO_INDEXED_DISPLAY = {
            "Compute":   ["Lambda", "EC2", "ECS", "EKS"],
            "Storage":   ["S3", "EFS"],
            "Databases": ["RDS", "DynamoDB", "Redshift", "ElastiCache"],
            "Networking":["VPC", "Route 53", "CloudFront", "API Gateway"],
            "Security":  ["IAM", "KMS", "Cognito", "GuardDuty"],
            "Analytics": ["Glue", "Kinesis", "Athena"],
            "Messaging": ["SQS", "SNS", "EventBridge", "Step Functions"],
            "AI / ML":   ["SageMaker", "Bedrock", "Bedrock AgentCore"],
            "DevOps":    ["CloudFormation", "CloudWatch", "CloudTrail"],
        }
        with st.expander("✅ 30 auto-indexed services", expanded=False):
            st.caption("Indexed at boot, refreshed weekly. No action needed.")
            for cat, svcs in AUTO_INDEXED_DISPLAY.items():
                st.caption(f"**{cat}:** " + " · ".join(svcs))
            st.caption(
                "ℹ️ Other AWS services are handled via live page fetch when asked about."
            )

        OPTIONAL_CATEGORIES = {
            "Extended AI / ML": [
                "comprehend", "rekognition", "transcribe", "textract",
                "polly", "translate", "lex", "forecast", "personalize",
            ],
            "Extended Analytics": ["emr", "quicksight", "opensearch"],
            "Extended DevOps": ["codebuild", "codepipeline", "codecommit", "cdk"],
            "Extended Security": ["securityhub", "waf", "organizations", "systems_manager"],
            "Extended Storage & Transfer": ["fsx", "transfer", "datasync"],
            "Guidance & Solutions": [
                "prescriptive_guidance", "solutions_library", "reference_architecture",
            ],
        }

        st.markdown("**Add optional services**")
        st.caption("Each adds ~4–6 min.")
        selected_keys: list[str] = []
        with st.expander("Select additional services", expanded=False):
            for category, keys in OPTIONAL_CATEGORIES.items():
                st.markdown(f"**{category}**")
                cols = st.columns(2)
                for i, key in enumerate(keys):
                    info = SEED_URLS.get(key, {})
                    label = (
                        info.get("name", key)
                        .replace(" Developer Guide", "")
                        .replace(" User Guide", "")
                        .replace(" Management Guide", "")
                        .replace(" Documentation", "")
                    )
                    if cols[i % 2].checkbox(label, key=f"chk_{key}"):
                        selected_keys.append(key)

            custom_topics = st.text_input(
                "Or enter keywords",
                placeholder="e.g. nlp, big data, ci/cd",
            )
            max_pages = st.slider("Max pages per service", 5, 100, 20, 5)

        ingest_disabled = not selected_keys and not custom_topics
        if st.button(
            "Fetch & Index Selected" if not ingest_disabled else "Select services to index",
            use_container_width=True,
            disabled=ingest_disabled,
            key="ingest_btn",
        ):
            final_keys = list(selected_keys)
            if custom_topics:
                from ingestion.ingest_pipeline import resolve_seed_keys, run_ingestion
                topic_list = [t.strip() for t in custom_topics.split(",") if t.strip()]
                final_keys.extend(resolve_seed_keys(topic_list))
            else:
                from ingestion.ingest_pipeline import run_ingestion

            final_keys = list(dict.fromkeys(final_keys))
            with st.spinner(f"Ingesting {len(final_keys)} service(s)…"):
                summary = run_ingestion(final_keys, max_pages, save_to_disk=False)
            _refresh_kb_count()
            st.success(
                f"Done! {summary['chunks_indexed']:,} chunks from {summary['pages_scraped']} pages."
            )
            if summary["skipped"]:
                st.warning(f"Skipped: {', '.join(summary['skipped'])}")
            st.rerun()

    # ── Bottom actions ────────────────────────────────────────────────────────
    st.divider()
    if st.button("Refresh KB count", use_container_width=True):
        _refresh_kb_count()
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AREA — state machine
# ═══════════════════════════════════════════════════════════════════════════════

cid  = st.session_state.ws_customer_id
cvid = st.session_state.ws_conversation_id

# ── State: new customer form ──────────────────────────────────────────────────
if st.session_state.show_new_customer:
    st.markdown("## Create Customer Workspace")
    st.caption("Each customer gets their own conversation history, context, and documents.")
    st.divider()

    with st.form("new_customer_form"):
        name     = st.text_input("Company / Customer name *", placeholder="Acme Corp")
        industry = st.text_input("Industry", placeholder="e.g. Retail, Healthcare, Financial Services")
        arch_ctx = st.text_area(
            "Current architecture context",
            height=200,
            placeholder=(
                "Describe the customer's current environment:\n"
                "- Infrastructure (on-prem, cloud, hybrid)\n"
                "- Key workloads and data volumes\n"
                "- Compliance requirements\n"
                "- Migration goals and timeline"
            ),
        )
        col_save, col_cancel = st.columns(2)
        submitted = col_save.form_submit_button("Create Workspace", type="primary", use_container_width=True)
        cancelled = col_cancel.form_submit_button("Cancel", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("Customer name is required.")
        else:
            new_id = _db().create_customer(name, industry, arch_ctx)
            _select_customer(new_id)
            st.session_state.show_new_customer = False
            st.rerun()

    if cancelled:
        st.session_state.show_new_customer = False
        st.rerun()

# ── State: no customer selected ───────────────────────────────────────────────
elif cid is None:
    st.markdown(
        "<h1 style='margin-bottom:0'>☁️ AWS Expert Architect</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Select a customer workspace from the sidebar, or create a new one to get started.")
    st.divider()

    try:
        customers = _db().get_customers()
    except Exception:
        customers = []

    if not customers:
        st.info(
            "**No customer workspaces yet.**\n\n"
            "Click **＋** next to the customer selector in the sidebar to create your first one."
        )
    else:
        st.markdown("### Your Customer Workspaces")
        cols = st.columns(min(len(customers), 3))
        for i, c in enumerate(customers):
            with cols[i % 3]:
                with st.container(border=True):
                    st.markdown(f"**{c['name']}**")
                    if c.get("industry"):
                        st.caption(c["industry"])
                    n_convs = len(_db().get_conversations(c["id"]))
                    st.caption(f"{n_convs} conversation{'s' if n_convs != 1 else ''}")
                    if st.button("Open", key=f"open_{c['id']}", use_container_width=True):
                        _select_customer(c["id"])
                        st.rerun()

# ── State: customer selected, no conversation ─────────────────────────────────
elif cvid is None:
    db = _db()
    customer = db.get_customer(cid)
    if not customer:
        _select_customer(None)
        st.rerun()

    # Header
    col_h, col_edit, col_del = st.columns([6, 1, 1])
    col_h.markdown(f"<h2 style='margin:0'>{customer['name']}</h2>", unsafe_allow_html=True)
    if customer.get("industry"):
        col_h.caption(customer["industry"])

    if col_edit.button("✏️ Edit", use_container_width=True):
        st.session_state.show_edit_customer = not st.session_state.show_edit_customer
    if col_del.button("🗑️ Delete", use_container_width=True):
        st.session_state.confirm_delete_cust = True

    # Delete customer confirmation
    if st.session_state.confirm_delete_cust:
        st.error(
            f"Permanently delete **{customer['name']}** and all their conversations and documents?"
        )
        dc1, dc2, _ = st.columns([1, 1, 4])
        if dc1.button("Yes, delete", type="primary"):
            db.delete_customer(cid)
            _select_customer(None)
            st.session_state.confirm_delete_cust = False
            st.rerun()
        if dc2.button("Cancel"):
            st.session_state.confirm_delete_cust = False
            st.rerun()

    st.divider()

    # Edit customer form (inline toggle)
    if st.session_state.show_edit_customer:
        with st.form("edit_customer_form"):
            st.markdown("**Edit Customer Profile**")
            new_name     = st.text_input("Name", value=customer["name"])
            new_industry = st.text_input("Industry", value=customer.get("industry", ""))
            new_ctx      = st.text_area(
                "Architecture Context",
                value=customer.get("arch_context", ""),
                height=220,
            )
            s1, s2 = st.columns(2)
            if s1.form_submit_button("Save Changes", type="primary", use_container_width=True):
                db.update_customer(cid, new_name, new_industry, new_ctx)
                st.session_state.show_edit_customer = False
                st.rerun()
            if s2.form_submit_button("Cancel", use_container_width=True):
                st.session_state.show_edit_customer = False
                st.rerun()
        st.divider()

    # Two-column layout: context + documents | conversations
    left, right = st.columns([3, 2])

    with left:
        # Architecture context (read-only view with edit inline above)
        st.markdown("**Architecture Context**")
        ctx = (customer.get("arch_context") or "").strip()
        if ctx:
            st.text_area(
                "arch_ctx_view",
                value=ctx,
                height=160,
                disabled=True,
                label_visibility="collapsed",
            )
        else:
            st.caption("No architecture context set. Click ✏️ Edit to add one.")

        st.divider()

        # Documents
        st.markdown("**Customer Documents**")
        st.caption("Uploaded docs are included in every conversation for this customer.")

        docs = db.get_customer_documents(cid)
        if docs:
            for doc in docs:
                d1, d2, d3 = st.columns([5, 1, 1])
                icon = "✅" if doc["is_active"] else "⬜"
                d1.caption(f"{icon} {doc['filename']} ({doc['char_count']:,} chars)")
                if d2.button(
                    "On" if doc["is_active"] else "Off",
                    key=f"tog_{doc['id']}",
                    help="Toggle active",
                    use_container_width=True,
                ):
                    db.toggle_customer_document(doc["id"], not doc["is_active"])
                    st.rerun()
                if d3.button("✕", key=f"deldoc_{doc['id']}", help="Remove", use_container_width=True):
                    db.delete_customer_document(doc["id"])
                    st.rerun()
        else:
            st.caption("No documents uploaded yet.")

        uploaded_files = st.file_uploader(
            "Upload files",
            type=["pdf", "docx", "txt", "md"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if uploaded_files:
            from ingestion.document_parser import extract_text
            for f in uploaded_files:
                text = extract_text(f.read(), f.name)
                db.save_customer_document(cid, f.name, text)
            st.success(f"{len(uploaded_files)} file(s) saved to this customer workspace.")
            st.rerun()

    with right:
        st.markdown("**Conversations**")
        try:
            convs = db.get_conversations(cid)
        except Exception:
            convs = []

        if st.button("＋ Start New Conversation", type="primary", use_container_width=True):
            new_cvid = db.create_conversation(cid)
            _select_conversation(new_cvid)
            st.rerun()

        if not convs:
            st.caption("No conversations yet. Start one above.")
        else:
            for conv in convs:
                with st.container(border=True):
                    updated = conv["updated_at"]
                    if hasattr(updated, "strftime"):
                        ts = updated.strftime("%b %d, %Y")
                    else:
                        ts = str(updated)[:10]
                    st.caption(ts)
                    st.markdown(f"**{conv['title']}**")
                    if st.button("Open", key=f"open_conv_{conv['id']}", use_container_width=True):
                        _select_conversation(conv["id"])
                        st.rerun()

# ── State: active conversation ────────────────────────────────────────────────
else:
    db = _db()
    customer = db.get_customer(cid)
    conv     = db.get_conversation(cvid)

    if not customer or not conv:
        st.session_state.ws_conversation_id = None
        st.rerun()

    # Breadcrumb header
    col_bc, col_back = st.columns([5, 1])
    col_bc.markdown(
        f"<p style='margin:0;color:#888;font-size:0.85em'>"
        f"{customer['name']}</p>"
        f"<h3 style='margin:0'>{conv['title']}</h3>",
        unsafe_allow_html=True,
    )
    if col_back.button("← Back", use_container_width=True):
        st.session_state.ws_conversation_id = None
        st.session_state.ws_agent = None
        st.session_state.ws_messages = []
        st.rerun()

    # Active context banner (collapsible)
    ctx = _build_customer_context(customer)
    if ctx:
        with st.expander(
            f"Active Context: {customer['name']} ({len(ctx):,} chars)", expanded=False
        ):
            st.text(ctx[:3000] + ("\n…[truncated]" if len(ctx) > 3000 else ""))

    st.divider()

    # Ensure agent is initialized (handles page reloads mid-conversation)
    if st.session_state.ws_agent is None:
        _load_conversation(cvid)

    # Render existing messages
    for msg in st.session_state.ws_messages:
        avatar = "🧑‍💼" if msg["role"] == "user" else "☁️"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Chat input
    prompt = st.chat_input("Ask an AWS architecture question…")

    if prompt:
        # Auto-title on first user message
        if not st.session_state.ws_messages:
            title = _make_title(prompt)
            db.update_conversation_title(cvid, title)
            # Update sidebar title immediately in this run
            conv = {"id": cvid, "title": title}

        # Add user message to local state and render immediately
        st.session_state.ws_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑‍💼"):
            st.markdown(prompt)

        # Get agent response
        agent = st.session_state.ws_agent
        history_len_before = len(agent.history)
        step_count = [0]
        status_ref = [None]
        accumulated_text = [""]

        with st.chat_message("assistant", avatar="☁️"):
            # Placeholder for streaming text — created first so it appears above
            # the status box, then filled in as tokens arrive during synthesis
            text_placeholder = st.empty()

            def _text_cb(token: str):
                accumulated_text[0] += token
                text_placeholder.markdown(accumulated_text[0] + "▌")

            def _status_cb(msg: str):
                step_count[0] += 1
                st.write(msg)
                # Update the status header to reflect the current phase
                sr = status_ref[0]
                if sr is not None:
                    if "Composing" in msg:
                        sr.update(label="✍️ Creating your architecture response…")
                    elif "Fetching" in msg:
                        sr.update(label="🌐 Retrieving live AWS documentation…")
                    elif "Searching" in msg:
                        sr.update(label="🔍 Searching knowledge base…")

            with st.status("🧠 Analyzing your question…", expanded=True) as research_status:
                status_ref[0] = research_status
                response = agent.chat(
                    user_message=prompt,
                    customer_context=ctx,
                    status_callback=_status_cb,
                    text_stream_callback=_text_cb,
                )
                research_status.update(
                    label=f"✅ Research complete — {step_count[0]} steps",
                    state="complete",
                    expanded=False,
                )
            # Final clean render (removes streaming cursor, proper markdown)
            text_placeholder.markdown(response)

        # Persist the full exchange (all tool turns + final response) to DB
        new_entries = agent.history[history_len_before:]
        _save_exchange(cvid, prompt, new_entries, response)

        # Add response to local display state
        st.session_state.ws_messages.append({"role": "assistant", "content": response})
