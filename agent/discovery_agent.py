"""
Discovery Brief Agent — generates a pre-call customer discovery brief.

Takes structured customer inputs (name, industry, website, notes) and
runs a multi-pass agentic research loop:
  1. Web search (Tavily) for company intelligence
  2. AWS KB search for relevant architecture patterns
  3. Synthesis into a Presidio-branded call-prep brief

Usage:
    from agent.discovery_agent import DiscoveryAgent
    agent = DiscoveryAgent()
    brief = agent.generate_brief(
        customer_name="Acme Corp",
        industry="Healthcare",
        website="https://acme.com",
        notes="CTO will be on the call. 500 employees, evaluating cloud options.",
    )
"""

import logging
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, MODEL_NAME, MAX_TOKENS
from agent.tools import DISCOVERY_TOOLS
from agent.tool_executor import execute_tool

logger = logging.getLogger(__name__)

# ── System prompt ──────────────────────────────────────────────────────────────

DISCOVERY_SYSTEM_PROMPT = """\
You are a senior Solution Architect at Presidio Technology, an AWS Premier Partner \
and managed services provider. You are preparing for a first meeting with a prospective \
customer. Your job is to produce a thorough, actionable pre-call discovery brief that \
arms the sales and technical team for a high-impact conversation.

Presidio's core practice areas — weave these in where they naturally fit:
  • Managed Cloud Operations — 24/7 monitoring, FinOps, cost optimization, AWS Managed Services
  • Security Practice — Zero Trust architecture, SOC services, PCI / HIPAA / SOC 2 / FedRAMP compliance
  • Data & AI / Analytics — data platform builds, MLOps, generative AI on AWS Bedrock
  • Cloud Migration & Modernization — lift-and-shift, re-architecture, containerization
  • Modern Workplace — end-user computing, VDI, AWS WorkSpaces

Presidio differentiates from going direct to AWS because Presidio provides:
  - Managed services overlay (24/7 ops, alerting, patching, cost governance)
  - Deep security practice embedded into every engagement
  - Faster time-to-value via pre-built playbooks and proven delivery methodology
  - Dedicated TAM and account team continuity
  - Multi-cloud and hybrid flexibility (not AWS-only)

═══════════════════════════════════════════════════════
RESEARCH PROCESS — DO THIS BEFORE WRITING THE BRIEF
═══════════════════════════════════════════════════════

Run ALL research steps before writing a single word of the brief output.

Step 1 — Web Research (use search_web multiple times):
  • Search for the company overview, what they do, employee count, funding, industry
  • Search for recent news: acquisitions, product launches, leadership changes, financial results
  • Search for technology signals: job postings mentioning AWS/Azure/GCP/Kubernetes/data,
    press releases about digital transformation, case studies, tech stack mentions
  • Search for industry-specific compliance or regulatory context (e.g. HIPAA for healthcare)

Step 2 — Internal AWS Knowledge Base (use search_aws_knowledge_base):
  • Search for reference architectures relevant to the customer's industry
  • Search for prescriptive guidance for their likely use cases
  • Search for AWS solutions in their vertical

Step 3 — Optional deep fetch:
  • If you find a highly relevant AWS reference architecture URL, use fetch_aws_page to get details

Gather ALL evidence first, then write the brief.

═══════════════════════════════════════════════════════
MANDATORY OUTPUT STRUCTURE
═══════════════════════════════════════════════════════

Produce the brief in this exact structure. Do not omit any section.

---

## 🎯 Discovery Brief: {customer_name}
**Presidio AWS Practice** | {today_date} | {industry}

---

### 1. Company Intelligence
- What the company does (2–3 plain-English sentences)
- Size indicators: employees, revenue, funding stage, public/private
- Recent notable events (last 12 months): funding rounds, M&A, product launches, leadership hires
- Technology signals: what tech they already use/buy, cloud maturity indicators from job postings or press
- Key business priorities inferred from public information

---

### 2. Likely Pain Points by Persona

**🏢 CIO / CDO — Strategic**
- 3–5 strategic challenges this CIO likely faces given their industry and company stage
- How cloud strategy, cost optimization, or digital transformation connects to their agenda
- *Presidio angle:* How Presidio's managed cloud advisory and FinOps practice directly addresses this

**🔒 CISO / VP Security — Risk & Compliance**
- 3–5 security and compliance concerns specific to their industry
- Likely compliance frameworks they must satisfy (e.g. PCI-DSS, HIPAA, SOC 2, FedRAMP)
- *Presidio angle:* How Presidio's security practice (Zero Trust, SOC, compliance automation) helps

**⚙️ VP Engineering / CTO — Technical**
- 3–5 technical challenges: scalability, developer velocity, platform debt, cloud maturity
- What their engineers likely care about day-to-day
- *Presidio angle:* How Presidio's architecture and migration teams accelerate their outcomes

---

### 3. AWS Use-Case Hypotheses
*Top 3 AWS use cases to explore — ranked by fit with this customer*

**Hypothesis 1: [Name the use case]**
- **Why it fits:** 2–3 sentences connecting it to the company's situation
- **AWS Services:** Key services involved
- **Presidio Delivery Model:** How Presidio specifically delivers this (not just native AWS)
- **Reference Pattern:** Relevant AWS reference architecture or prescriptive guidance

**Hypothesis 2: [Name the use case]**
- **Why it fits:** ...
- **AWS Services:** ...
- **Presidio Delivery Model:** ...
- **Reference Pattern:** ...

**Hypothesis 3: [Name the use case]**
- **Why it fits:** ...
- **AWS Services:** ...
- **Presidio Delivery Model:** ...
- **Reference Pattern:** ...

---

### 4. Discovery Questions *(15 total — 5 per persona)*

**For the CIO / CDO:**
1. ...
2. ...
3. ...
4. ...
5. ...

**For the CISO / VP Security:**
1. ...
2. ...
3. ...
4. ...
5. ...

**For the VP Engineering / CTO:**
1. ...
2. ...
3. ...
4. ...
5. ...

---

### 5. Stakeholder Map

| Role | Likely Priority | Decision Power | Anticipated Objection |
|------|----------------|---------------|----------------------|
| CIO | | High | |
| CISO | | High | |
| VP Engineering | | Medium | |
| Procurement | Cost justification | Gating | Budget / vendor approval process |
| [Other inferred roles] | | | |

---

### 6. Presidio Positioning

- **Primary value message for this customer:** One punchy sentence tailored to their situation
- **Why Presidio over going direct to AWS:** Specific to their situation (managed ops, security, speed)
- **Likely competition in the room:** Other SIs, MSPs, or consulting firms they may be talking to
- **Cost of inaction:** What happens if they delay or do nothing

---

### 7. Recommended Meeting Agenda *(45 minutes)*

| Time | Segment | Goal |
|------|---------|------|
| 0–5 min | Introductions & ground rules | Align on agenda, confirm attendees and roles |
| 5–15 min | Their priorities — open discovery | Listen, confirm or refute hypotheses |
| 15–25 min | Hypothesis sharing | Present top 2–3 use cases, gauge resonance |
| 25–35 min | Architecture / solution concepts | Show relevant reference architecture, Presidio delivery model |
| 35–42 min | Presidio differentiators & next steps | Managed services value prop, proposed engagement path |
| 42–45 min | Q&A / close | Confirm next meeting, action items |

---

### 8. Pre-Call Checklist

- [ ] Confirm who is attending — get titles and LinkedIn profiles ahead of time
- [ ] Check if customer has an existing AWS account (AWS Direct vs. via Partner)
- [ ] Look up any existing Presidio relationship or prior engagement history
- [ ] Prepare a 1-slide architecture concept for the top use case hypothesis
- [ ] Review the customer's public tech job postings for cloud/infra signals
- [ ] Confirm customer's AWS region preferences and data residency requirements
- [ ] Check for any active AWS programs (MAP, WAFR, Immersion Day) they qualify for

---
*Generated by Presidio AWS Practice Assistant · Validate with account team before customer use*
"""


class DiscoveryAgent:
    """
    One-shot discovery brief generator.
    Call generate_brief() with customer info; returns a rich markdown brief.
    """

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Copy .env and add your key."
            )
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ── Status helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _search_summary(result: str) -> str:
        import re
        count_m = re.search(r"Found (\d+) relevant", result)
        count = count_m.group(1) if count_m else "?"
        relevances = re.findall(r"relevance: ([\d.]+)", result)
        max_rel = max(float(r) for r in relevances) if relevances else 0.0
        return f"→ {count} KB chunks · best match {max_rel:.2f}"

    @staticmethod
    def _web_search_summary(result: str) -> str:
        import re
        count_m = re.search(r"Found (\d+) web result", result)
        count = count_m.group(1) if count_m else "?"
        return f"→ {count} web results retrieved"

    # ── Main method ────────────────────────────────────────────────────────

    def generate_brief(
        self,
        customer_name: str,
        industry: str = "",
        website: str = "",
        notes: str = "",
        arch_context: str = "",
        status_callback=None,
        text_stream_callback=None,
    ) -> str:
        """
        Research a customer and generate a discovery brief.

        Args:
            customer_name: Company name.
            industry: Customer industry (e.g. "Healthcare", "Financial Services").
            website: Company website URL (used as a research seed).
            notes: Free-text call notes or additional context.
            arch_context: Existing architecture context from the customer workspace.
            status_callback: Optional fn(str) for live status messages.
            text_stream_callback: Optional fn(str) for streamed text tokens.

        Returns:
            The full discovery brief as a markdown string.
        """
        def _emit(msg: str):
            if status_callback:
                status_callback(msg)

        today = date.today().strftime("%B %d, %Y")

        # Build the user prompt with all available inputs
        user_parts = [
            f"Generate a complete discovery brief for the following customer.",
            f"",
            f"**Customer Name:** {customer_name}",
        ]
        if industry:
            user_parts.append(f"**Industry:** {industry}")
        if website:
            user_parts.append(f"**Company Website:** {website}")
        if notes:
            user_parts.append(f"**Call Notes / Context:**\n{notes}")
        if arch_context:
            user_parts.append(
                f"**Known Architecture Context (from workspace):**\n{arch_context}"
            )
        user_parts += [
            f"",
            f"**Today's Date:** {today}",
            f"",
            "Please research this company thoroughly using the available tools before "
            "writing the brief. Fill in the mandatory output structure completely.",
        ]

        user_message = "\n".join(user_parts)

        # Substitute customer_name and date into the system prompt
        system = DISCOVERY_SYSTEM_PROMPT.replace("{customer_name}", customer_name)
        system = system.replace("{today_date}", today)
        system = system.replace("{industry}", industry or "Unknown Industry")

        messages = [{"role": "user", "content": user_message}]
        had_tool_calls = False

        # Agentic loop
        while True:
            if had_tool_calls:
                _emit("✍️  Composing discovery brief…")
            else:
                _emit("🧠  Sending research request to Claude…")

            with self.client.messages.stream(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=DISCOVERY_TOOLS,
                messages=messages,
            ) as stream:
                if text_stream_callback:
                    for token in stream.text_stream:
                        text_stream_callback(token)
                response = stream.get_final_message()

            if response.stop_reason == "tool_use":
                had_tool_calls = True

                messages.append({
                    "role": "assistant",
                    "content": response.content,
                })

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input

                    if tool_name == "search_web":
                        q = tool_input.get("query", "")
                        _emit(f"🌐  Web search: \"{q}\"")
                    elif tool_name == "search_aws_knowledge_base":
                        q = tool_input.get("query", "")
                        n = tool_input.get("n_results", 8)
                        _emit(f"🔍  KB search ({n} results): \"{q}\"")
                    elif tool_name == "fetch_aws_page":
                        url = tool_input.get("url", "")
                        parsed = urlparse(url)
                        display = parsed.netloc + parsed.path[:50]
                        _emit(f"📄  Fetching: {display}")

                    logger.info("Discovery tool: %s  input=%s", tool_name, tool_input)
                    result = execute_tool(tool_name, tool_input)

                    if tool_name == "search_web":
                        _emit(f"   {self._web_search_summary(result)}")
                    elif tool_name == "search_aws_knowledge_base":
                        _emit(f"   {self._search_summary(result)}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                messages.append({
                    "role": "user",
                    "content": tool_results,
                })

            elif response.stop_reason == "end_turn":
                response_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        response_text = block.text
                        break
                return response_text

            else:
                logger.warning("Unexpected stop_reason: %s", response.stop_reason)
                return "An unexpected error occurred generating the discovery brief. Please try again."
