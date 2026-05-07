"""
AWS Architect Assistant — Streamlit Chat Application
Customer-workspace edition: persistent customers, conversations, and documents.

Run with:
    streamlit run app.py
"""

import json
import logging
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title="AWS Architect Assistant",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

logging.basicConfig(level=logging.INFO)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Push main content below Streamlit's native toolbar (~52 px).
   1rem was too small and caused the first row to slide under the toolbar. */
.block-container {
    padding-top: 3.75rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1400px !important;
}
/* Tighter sidebar so more customers fit without scrolling */
section[data-testid="stSidebar"] button { text-align: left !important; }
section[data-testid="stSidebar"] .block-container {
    padding-top: 0.5rem !important;
}
/* Subtle AWS-orange accent on active tab */
button[data-baseweb="tab"][aria-selected="true"] {
    border-bottom: 3px solid #FF9900 !important;
    font-weight: 600 !important;
}
/* Make metric labels a little smaller so the sidebar stays compact */
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "ws_customer_id":      None,
        "ws_conversation_id":  None,
        "ws_agent":            None,
        "ws_messages":         [],
        "kb_count":            0,
        "show_new_customer":   False,
        "show_edit_customer":  False,
        "confirm_delete_conv": None,
        "confirm_delete_cust": False,
        "discovery_results":   {},   # {customer_id: {"text": ..., "website": ..., "notes": ...}}
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Stage constants ────────────────────────────────────────────────────────────

STAGE_OPTIONS = ["Prospect", "Active Opportunity", "POC / Pilot", "Closed Won", "Inactive"]

STAGE_COLORS = {
    "Prospect":           "#6c757d",
    "Active Opportunity": "#0d6efd",
    "POC / Pilot":        "#fd7e14",
    "Closed Won":         "#198754",
    "Inactive":           "#adb5bd",
}

STAGE_EMOJI = {
    "Prospect":           "⬜",
    "Active Opportunity": "🔵",
    "POC / Pilot":        "🟠",
    "Closed Won":         "🟢",
    "Inactive":           "⚫",
}


# ── Time-ago helper ────────────────────────────────────────────────────────────

def _time_ago(dt) -> str:
    """Convert a datetime to a human-readable relative string."""
    from datetime import datetime, timezone
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = int((now - dt).total_seconds())
    if diff < 120:
        return "just now"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    if diff < 86400 * 7:
        return f"{diff // 86400}d ago"
    return f"{diff // (86400 * 7)}w ago"


# ── Copy-to-clipboard button (JavaScript component) ───────────────────────────

def _copy_button(text: str, label: str = "📋 Copy") -> None:
    import json
    import streamlit.components.v1 as components
    escaped = json.dumps(text)
    components.html(
        f"""
        <button
            onclick="navigator.clipboard.writeText({escaped}).then(
                () => {{ this.textContent='✅ Copied!';
                         setTimeout(()=>this.textContent='{label}', 2000); }},
                () => {{ this.textContent='❌ Failed'; }}
            )"
            style="background:#FF9900;color:white;border:none;padding:7px 14px;
                   border-radius:6px;cursor:pointer;font-size:0.85rem;
                   width:100%;font-family:sans-serif;font-weight:600;">
            {label}
        </button>
        """,
        height=42,
    )


# ── Auto-save a discovery brief as a conversation ─────────────────────────────

def _save_brief_as_conversation(
    db, customer_id: str, customer_name: str,
    website: str, notes: str, brief_text: str,
) -> str:
    """Save a generated brief as a conversation and return the conversation ID."""
    from datetime import date as _date
    title = f"🎯 Brief — {_date.today().strftime('%b %d, %Y')}"
    conv_id = db.create_conversation(customer_id)
    db.update_conversation_title(conv_id, title[:58])

    parts = [f"Generate a discovery brief for {customer_name}."]
    if website:
        parts.append(f"Website: {website}")
    if notes:
        parts.append(f"Notes: {notes}")
    user_msg = "\n".join(parts)

    next_idx = db.get_next_turn_index(conv_id)
    db.save_messages_batch([
        {
            "conversation_id": conv_id,
            "turn_index":      next_idx,
            "role":            "user",
            "message_type":    "text",
            "content_text":    user_msg,
            "content_json":    None,
            "display_content": user_msg,
            "is_display_turn": True,
        },
        {
            "conversation_id": conv_id,
            "turn_index":      next_idx + 1,
            "role":            "assistant",
            "message_type":    "text",
            "content_text":    brief_text,
            "content_json":    None,
            "display_content": brief_text,
            "is_display_turn": True,
        },
    ])
    db.bump_conversation(conv_id)
    return conv_id


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _db():
    from vectorstore import pg_client
    return pg_client


# ── Utility functions ──────────────────────────────────────────────────────────

def _make_title(prompt: str) -> str:
    clean = prompt.strip().replace("\n", " ")
    if len(clean) <= 58:
        return clean
    cut = clean[:58].rfind(" ")
    return clean[:cut if cut > 20 else 58] + "…"


def _build_customer_context(customer: dict) -> str:
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
    from agent.chat_agent import AWSChatAgent
    db_msgs = _db().get_messages(conv_id)
    agent = AWSChatAgent()
    agent.history = []
    for m in db_msgs:
        if m["message_type"] == "text":
            agent.history.append({"role": m["role"], "content": m["content_text"]})
        else:
            agent.history.append({
                "role": m["role"],
                "content": json.loads(m["content_json"]),
            })
    st.session_state.ws_messages = [
        {"role": m["role"], "content": m["display_content"]}
        for m in db_msgs if m["is_display_turn"]
    ]
    st.session_state.ws_agent = agent
    st.session_state.ws_conversation_id = conv_id


def _save_exchange(conv_id, user_prompt, new_history_entries, assistant_response):
    db = _db()
    next_idx = db.get_next_turn_index(conv_id)
    rows = []
    for i, entry in enumerate(new_history_entries):
        role    = entry["role"]
        content = entry["content"]
        if isinstance(content, str):
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
    """Switch to a customer; auto-load their most recent conversation."""
    st.session_state.ws_customer_id     = customer_id
    st.session_state.ws_conversation_id = None
    st.session_state.ws_agent           = None
    st.session_state.ws_messages        = []
    st.session_state.show_edit_customer = False
    st.session_state.confirm_delete_conv = None
    if customer_id:
        try:
            convs = _db().get_conversations(customer_id)
            if convs:
                _load_conversation(convs[0]["id"])
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    # ── App title ─────────────────────────────────────────────────────────────
    st.markdown("## ☁️ AWS Architect Assistant")
    st.caption("Knowledge Base — Powered by Claude + RAG over AWS docs")
    st.divider()

    # ── KB metrics ────────────────────────────────────────────────────────────
    _refresh_kb_count()
    kb_count = st.session_state.kb_count
    db_side  = _db()

    try:
        manifest = db_side.get_manifest()
        sources  = manifest.get("sources", {})
        c1, c2   = st.columns(2)
        c1.metric("Chunks",  f"{kb_count:,}")
        c2.metric("Sources", len(sources))
        if manifest.get("last_updated"):
            st.caption(f"Updated: {manifest['last_updated'][:10]}")
    except Exception:
        st.metric("Chunks", f"{kb_count:,}")

    if kb_count == 0:
        st.info("⏳ Initial indexing in progress (~15 min on first boot).")

    AUTO_INDEXED_DISPLAY = {
        "Compute":    ["Lambda", "EC2", "ECS", "EKS"],
        "Storage":    ["S3", "EFS"],
        "Databases":  ["RDS", "DynamoDB", "Redshift", "ElastiCache"],
        "Networking": ["VPC", "Route 53", "CloudFront", "API Gateway"],
        "Security":   ["IAM", "KMS", "Cognito", "GuardDuty"],
        "Analytics":  ["Glue", "Kinesis", "Athena"],
        "Messaging":  ["SQS", "SNS", "EventBridge", "Step Functions"],
        "AI / ML":    ["SageMaker", "Bedrock", "Bedrock AgentCore"],
        "DevOps":     ["CloudFormation", "CloudWatch", "CloudTrail"],
    }
    with st.expander("✅ Indexed services", expanded=False):
        st.caption("Indexed at boot, refreshed weekly.")
        for cat, svcs in AUTO_INDEXED_DISPLAY.items():
            st.caption(f"**{cat}:** " + " · ".join(svcs))

    from scraper.aws_doc_urls import SEED_URLS
    OPTIONAL_CATEGORIES = {
        "Extended AI / ML": [
            "comprehend", "rekognition", "transcribe", "textract",
            "polly", "translate", "lex", "forecast", "personalize",
        ],
        "Extended Analytics":          ["emr", "quicksight", "opensearch"],
        "Extended DevOps":             ["codebuild", "codepipeline", "codecommit", "cdk"],
        "Extended Security":           ["securityhub", "waf", "organizations", "systems_manager"],
        "Extended Storage & Transfer": ["fsx", "transfer", "datasync"],
        "Guidance & Solutions": [
            "prescriptive_guidance", "solutions_library", "reference_architecture",
        ],
    }
    with st.expander("➕ Index additional services", expanded=False):
        selected_keys: list[str] = []
        for category, keys in OPTIONAL_CATEGORIES.items():
            st.markdown(f"**{category}**")
            cols = st.columns(2)
            for i, key in enumerate(keys):
                info  = SEED_URLS.get(key, {})
                label = (
                    info.get("name", key)
                    .replace(" Developer Guide", "")
                    .replace(" User Guide", "")
                    .replace(" Management Guide", "")
                    .replace(" Documentation", "")
                )
                if cols[i % 2].checkbox(label, key=f"chk_{key}"):
                    selected_keys.append(key)

        custom_topics = st.text_input("Or enter keywords", placeholder="e.g. nlp, big data")
        max_pages     = st.slider("Max pages per service", 5, 100, 20, 5)

        ingest_disabled = not selected_keys and not custom_topics
        if st.button(
            "Fetch & Index Selected" if not ingest_disabled else "Select services above",
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

    if st.button("Refresh KB count", use_container_width=True):
        _refresh_kb_count()
        st.rerun()

    # ── Customers ─────────────────────────────────────────────────────────────
    st.divider()

    cust_hdr, new_btn_col = st.columns([3, 1])
    cust_hdr.markdown("**Customers**")
    if new_btn_col.button("＋", help="Create new customer", use_container_width=True):
        st.session_state.show_new_customer  = True
        st.session_state.show_edit_customer = False
        st.rerun()

    try:
        all_customers = db_side.get_customers()
    except Exception:
        all_customers = []

    cid = st.session_state.ws_customer_id

    if not all_customers:
        st.caption("No customers yet. Click ＋ to create one.")
    else:
        # Single button row per customer (~46px each)
        scroll_h = min(len(all_customers) * 46 + 12, 400)
        with st.container(height=scroll_h, border=False):
            for c in all_customers:
                is_sel      = c["id"] == cid
                btn_type    = "primary" if is_sel else "secondary"
                stage       = c.get("stage", "Prospect")
                emoji       = STAGE_EMOJI.get(stage, "⬜")
                last_active = c.get("last_active_at")
                time_str    = f" · {_time_ago(last_active)}" if last_active else ""
                prefix      = "▶ " if is_sel else ""
                label       = f"{prefix}{c['name']}  {emoji}{time_str}"
                if st.button(
                    label,
                    key=f"cust_sidebar_{c['id']}",
                    use_container_width=True,
                    type=btn_type,
                    help=c.get("industry") or None,
                ):
                    if not is_sel:
                        _select_customer(c["id"])
                    else:
                        st.session_state.ws_conversation_id = None
                        st.session_state.ws_agent           = None
                        st.session_state.ws_messages        = []
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AREA — full width
# ═══════════════════════════════════════════════════════════════════════════════

db  = _db()
cid = st.session_state.ws_customer_id
cvid = st.session_state.ws_conversation_id

# Re-fetch customers for use in main area
try:
    all_customers = db.get_customers()
except Exception:
    all_customers = []

# ── New customer form ──────────────────────────────────────────────────────────
if st.session_state.show_new_customer:
    st.markdown("## Create Customer Workspace")
    st.caption("Each customer gets their own conversation history, context, and documents.")
    st.divider()

    with st.form("new_customer_form"):
        name     = st.text_input("Company / Customer name *", placeholder="Acme Corp")
        industry = st.text_input("Industry", placeholder="e.g. Retail, Healthcare, Financial Services")
        stage    = st.selectbox("Opportunity Stage", STAGE_OPTIONS, index=0)
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
            new_id = db.create_customer(name, industry, arch_ctx, stage)
            st.session_state.show_new_customer = False
            _select_customer(new_id)
            st.rerun()

    if cancelled:
        st.session_state.show_new_customer = False
        st.rerun()

# ── No customer selected ───────────────────────────────────────────────────────
elif cid is None:
    st.markdown(
        "<h1 style='margin-bottom:0.3rem'>☁️ AWS Architect Assistant</h1>",
        unsafe_allow_html=True,
    )
    st.caption("Select a customer from the sidebar, or create a new one to get started.")
    st.divider()
    if not all_customers:
        st.info(
            "**No customer workspaces yet.**\n\n"
            "Click the **＋** button next to Customers in the sidebar to create your first one."
        )
    else:
        st.markdown(
            f"You have **{len(all_customers)}** customer workspace"
            f"{'s' if len(all_customers) != 1 else ''}. "
            "Select one from the sidebar to open it."
        )

# ── Customer selected, no active conversation (profile view) ───────────────────
elif cvid is None:
    customer = db.get_customer(cid)
    if not customer:
        _select_customer(None)
        st.rerun()

    # Header
    hdr_col, edit_col, del_col = st.columns([6, 1, 1])
    stage      = customer.get("stage", "Prospect")
    stage_color = STAGE_COLORS.get(stage, "#6c757d")
    hdr_col.markdown(
        f"<h2 style='margin:0'>{customer['name']} "
        f"<span style='background:{stage_color};color:white;padding:2px 10px;"
        f"border-radius:12px;font-size:0.55em;vertical-align:middle;"
        f"font-weight:600;letter-spacing:0.03em'>{stage}</span></h2>",
        unsafe_allow_html=True,
    )
    if customer.get("industry"):
        hdr_col.caption(customer["industry"])

    if edit_col.button("✏️ Edit", use_container_width=True):
        st.session_state.show_edit_customer = not st.session_state.show_edit_customer
    if del_col.button("🗑️ Delete", use_container_width=True):
        st.session_state.confirm_delete_cust = True

    # Delete confirmation
    if st.session_state.confirm_delete_cust:
        st.error(f"Permanently delete **{customer['name']}** and all their conversations and documents?")
        dc1, dc2, _ = st.columns([1, 1, 4])
        if dc1.button("Yes, delete", type="primary"):
            db.delete_customer(cid)
            _select_customer(None)
            st.session_state.confirm_delete_cust = False
            st.rerun()
        if dc2.button("Cancel"):
            st.session_state.confirm_delete_cust = False
            st.rerun()

    # Edit form
    if st.session_state.show_edit_customer:
        with st.form("edit_customer_form"):
            st.markdown("**Edit Customer Profile**")
            new_name     = st.text_input("Name",     value=customer["name"])
            new_industry = st.text_input("Industry", value=customer.get("industry", ""))
            cur_stage    = customer.get("stage", "Prospect")
            new_stage    = st.selectbox(
                "Opportunity Stage",
                STAGE_OPTIONS,
                index=STAGE_OPTIONS.index(cur_stage) if cur_stage in STAGE_OPTIONS else 0,
            )
            new_ctx      = st.text_area(
                "Architecture Context",
                value=customer.get("arch_context", ""),
                height=200,
            )
            s1, s2 = st.columns(2)
            if s1.form_submit_button("Save Changes", type="primary", use_container_width=True):
                db.update_customer(cid, new_name, new_industry, new_ctx, new_stage)
                st.session_state.show_edit_customer = False
                st.rerun()
            if s2.form_submit_button("Cancel", use_container_width=True):
                st.session_state.show_edit_customer = False
                st.rerun()

    st.divider()

    tab_conv, tab_brief = st.tabs(["💬 Conversations", "🎯 Discovery Brief"])

    # ── Tab 1: Conversations + context/docs ───────────────────────────────────
    with tab_conv:
        conv_col, detail_col = st.columns([3, 2], gap="large")

        with conv_col:
            st.markdown("**Conversations**")

            if st.button("＋ Start New Conversation", type="primary", use_container_width=True):
                new_cvid = db.create_conversation(cid)
                _load_conversation(new_cvid)
                st.rerun()

            st.markdown("")

            try:
                convs = db.get_conversations(cid)
            except Exception:
                convs = []

            if not convs:
                st.caption("No conversations yet. Start one above.")
            else:
                for conv in convs:
                    with st.container(border=True):
                        updated = conv["updated_at"]
                        ts = updated.strftime("%b %d, %Y") if hasattr(updated, "strftime") else str(updated)[:10]

                        if st.session_state.confirm_delete_conv == conv["id"]:
                            st.warning(f"Delete **{conv['title']}**?")
                            y_col, n_col = st.columns(2)
                            if y_col.button("Yes, delete", key=f"del_yes_{conv['id']}", use_container_width=True):
                                db.delete_conversation(conv["id"])
                                st.session_state.confirm_delete_conv = None
                                st.rerun()
                            if n_col.button("Cancel", key=f"del_no_{conv['id']}", use_container_width=True):
                                st.session_state.confirm_delete_conv = None
                                st.rerun()
                        else:
                            title_col, open_col, del_col2 = st.columns([4, 2, 1])
                            title_col.markdown(f"**{conv['title']}**")
                            title_col.caption(ts)
                            if open_col.button("Open →", key=f"open_conv_{conv['id']}", use_container_width=True):
                                _load_conversation(conv["id"])
                                st.rerun()
                            if del_col2.button("✕", key=f"del_{conv['id']}", use_container_width=True):
                                st.session_state.confirm_delete_conv = conv["id"]
                                st.rerun()

        with detail_col:
            st.markdown("**Architecture Context**")
            ctx_text = (customer.get("arch_context") or "").strip()
            if ctx_text:
                st.text_area(
                    "ctx_view",
                    value=ctx_text,
                    height=200,
                    disabled=True,
                    label_visibility="collapsed",
                )
            else:
                st.caption("No architecture context yet. Click ✏️ Edit to add one.")

            st.divider()

            st.markdown("**Customer Documents**")
            st.caption("Active docs are injected into every conversation for this customer.")

            docs = db.get_customer_documents(cid)
            if docs:
                for doc in docs:
                    d1, d2, d3 = st.columns([5, 1, 1])
                    icon = "✅" if doc["is_active"] else "⬜"
                    d1.caption(f"{icon} {doc['filename']} ({doc['char_count']:,} chars)")
                    if d2.button(
                        "On" if doc["is_active"] else "Off",
                        key=f"tog_{doc['id']}",
                        help="Toggle",
                        use_container_width=True,
                    ):
                        db.toggle_customer_document(doc["id"], not doc["is_active"])
                        st.rerun()
                    if d3.button("✕", key=f"deldoc_{doc['id']}", use_container_width=True):
                        db.delete_customer_document(doc["id"])
                        st.rerun()

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
                st.success(f"{len(uploaded_files)} file(s) saved to this workspace.")
                st.rerun()

    # ── Tab 2: Discovery Brief ─────────────────────────────────────────────────
    with tab_brief:
        brief_left, brief_right = st.columns([2, 3], gap="large")

        with brief_left:
            st.markdown("**Generate New Brief**")
            st.caption("Tavily web search + AWS knowledge base → Presidio call-prep doc")

            disc_website = st.text_input(
                "Company website",
                placeholder="https://www.example.com",
                key=f"disc_website_{cid}",
            )
            disc_notes = st.text_area(
                "Call notes / context",
                placeholder=(
                    "e.g. CTO + CISO on the call.\n"
                    "500 employees, Series C, on-prem.\n"
                    "Interested in containers + cost reduction."
                ),
                height=100,
                key=f"disc_notes_{cid}",
            )
            generate_btn = st.button(
                "🎯 Generate Brief",
                type="primary",
                use_container_width=True,
                key=f"gen_brief_{cid}",
            )

            st.divider()
            st.markdown("**Saved Briefs**")

            try:
                all_convs_brief = db.get_conversations(cid)
                past_briefs = [c for c in all_convs_brief if c["title"].startswith("🎯 Brief")]
            except Exception:
                past_briefs = []

            if not past_briefs:
                st.caption("No briefs yet — generate one above.")
            else:
                for pb in past_briefs:
                    pb_ts = pb["updated_at"]
                    pb_label = pb["title"]
                    if st.button(pb_label, key=f"load_brief_{pb['id']}", use_container_width=True):
                        msgs = db.get_messages(pb["id"])
                        for m in msgs:
                            if m["role"] == "assistant" and m["is_display_turn"]:
                                st.session_state.discovery_results[cid] = {
                                    "text": m["display_content"],
                                    "conv_id": pb["id"],
                                }
                                break
                        st.rerun()
                    st.caption(_time_ago(pb_ts))

        with brief_right:
            if generate_btn:
                from agent.discovery_agent import DiscoveryAgent
                da = DiscoveryAgent()
                step_count = [0]
                accumulated_text = [""]

                with st.chat_message("assistant", avatar="🎯"):
                    text_placeholder = st.empty()

                    def _disc_text_cb(token: str):
                        accumulated_text[0] += token
                        text_placeholder.markdown(accumulated_text[0] + "▌")

                    def _disc_status_cb(msg: str):
                        step_count[0] += 1
                        st.write(msg)

                    with st.status("🔍 Researching company…", expanded=True) as brief_status:
                        brief_text = da.generate_brief(
                            customer_name=customer["name"],
                            industry=customer.get("industry", ""),
                            website=disc_website,
                            notes=disc_notes,
                            arch_context=customer.get("arch_context", ""),
                            status_callback=_disc_status_cb,
                            text_stream_callback=_disc_text_cb,
                        )
                        brief_status.update(
                            label=f"✅ Brief complete — {step_count[0]} research steps",
                            state="complete",
                            expanded=False,
                        )
                    text_placeholder.markdown(brief_text)

                # Auto-save and store in session
                saved_conv_id = _save_brief_as_conversation(
                    db, cid, customer["name"], disc_website, disc_notes, brief_text
                )
                st.session_state.discovery_results[cid] = {
                    "text": brief_text,
                    "conv_id": saved_conv_id,
                }
                st.caption("✅ Brief auto-saved to Conversations.")

            saved_brief = st.session_state.discovery_results.get(cid)
            if saved_brief and not generate_btn:
                dl_col, cp_col = st.columns(2)
                with dl_col:
                    safe_name = customer["name"].replace(" ", "_")
                    st.download_button(
                        "⬇️ Download .md",
                        data=saved_brief["text"],
                        file_name=f"discovery_brief_{safe_name}.md",
                        mime="text/markdown",
                        use_container_width=True,
                        key=f"dl_brief_{cid}",
                    )
                with cp_col:
                    _copy_button(saved_brief["text"])
                st.divider()
                st.markdown(saved_brief["text"])
            elif not generate_btn:
                st.info(
                    "Fill in the company website and any call notes on the left, "
                    "then click **🎯 Generate Brief** to create your pre-call document."
                )

# ── Active conversation ────────────────────────────────────────────────────────
else:
    customer = db.get_customer(cid)
    conv     = db.get_conversation(cvid)

    if not customer or not conv:
        st.session_state.ws_conversation_id = None
        st.rerun()

    # ── Header row ────────────────────────────────────────────────────────────
    hdr_col, new_col, back_col = st.columns([5, 1, 1])
    hdr_col.markdown(
        f"<p style='margin:0;color:#888;font-size:0.82em'>{customer['name']}</p>"
        f"<h3 style='margin:0'>{conv['title']}</h3>",
        unsafe_allow_html=True,
    )
    if new_col.button("＋ New", help="Start a new conversation", use_container_width=True):
        new_cvid = db.create_conversation(cid)
        _load_conversation(new_cvid)
        st.rerun()
    if back_col.button("← All", help="Back to conversation list", use_container_width=True):
        st.session_state.ws_conversation_id = None
        st.session_state.ws_agent           = None
        st.session_state.ws_messages        = []
        st.rerun()

    # ── Active context — shown expanded at the top ────────────────────────────
    ctx = _build_customer_context(customer)

    # Always show context section; expand if there is content
    ctx_label = (
        f"📋 Active Context — {customer['name']}"
        + (f" · {len(ctx):,} chars" if ctx else "")
    )
    with st.expander(ctx_label, expanded=bool(ctx)):
        if ctx:
            # Split into arch context and docs for cleaner display
            arch_ctx = (customer.get("arch_context") or "").strip()
            if arch_ctx:
                st.markdown("**Architecture Context**")
                st.text(arch_ctx[:2000] + ("\n…[truncated]" if len(arch_ctx) > 2000 else ""))

            docs = db.get_customer_documents(customer["id"])
            active_docs = [d for d in docs if d.get("is_active")]
            if active_docs:
                st.markdown(f"**Uploaded Documents** ({len(active_docs)} active)")
                for doc in active_docs:
                    st.caption(f"• {doc['filename']} — {doc['char_count']:,} chars")
        else:
            st.caption(
                "No architecture context or active documents for this customer. "
                "Click **← All** → ✏️ Edit to add context, or upload documents."
            )

    st.divider()

    # ── Ensure agent is initialized ───────────────────────────────────────────
    if st.session_state.ws_agent is None:
        _load_conversation(cvid)

    # ── Render existing messages ──────────────────────────────────────────────
    for msg in st.session_state.ws_messages:
        avatar = "🧑‍💼" if msg["role"] == "user" else "☁️"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # ── Chat input ────────────────────────────────────────────────────────────
    prompt = st.chat_input("Ask an AWS architecture question…")

    if prompt:
        # Auto-title on first message
        if not st.session_state.ws_messages:
            title = _make_title(prompt)
            db.update_conversation_title(cvid, title)
            conv = {"id": cvid, "title": title}

        st.session_state.ws_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑‍💼"):
            st.markdown(prompt)

        agent              = st.session_state.ws_agent
        history_len_before = len(agent.history)
        step_count         = [0]
        status_ref         = [None]
        accumulated_text   = [""]

        with st.chat_message("assistant", avatar="☁️"):
            text_placeholder = st.empty()

            def _text_cb(token: str):
                accumulated_text[0] += token
                text_placeholder.markdown(accumulated_text[0] + "▌")

            def _status_cb(msg: str):
                step_count[0] += 1
                st.write(msg)
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
            text_placeholder.markdown(response)

        new_entries = agent.history[history_len_before:]
        _save_exchange(cvid, prompt, new_entries, response)
        st.session_state.ws_messages.append({"role": "assistant", "content": response})
