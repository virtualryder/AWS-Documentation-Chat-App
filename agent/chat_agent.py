"""
Agentic chat loop using Claude claude-sonnet-4-6 with tool use.

The agent:
1. Receives a user message (and optional customer architecture context)
2. Calls tools to search indexed AWS docs or fetch live pages
3. Loops until Claude produces a final answer (stop_reason == "end_turn")
4. Returns the assistant's response text
"""

import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import ANTHROPIC_API_KEY, MODEL_NAME, MAX_TOKENS
from agent.tools import TOOLS
from agent.tool_executor import execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an elite AWS Solutions Architect with deep expertise across all AWS services, \
architectural patterns, and the AWS Well-Architected Framework. You have designed and \
implemented hundreds of production architectures for enterprises of all sizes.

Your audience may have minimal AWS experience. Be thorough, never assume prior \
knowledge, and always explain the "why" behind every decision.

═══════════════════════════════════════════════════════
RESEARCH PROCESS — TWO PASSES, ALWAYS
═══════════════════════════════════════════════════════

### PASS 1 — Research (do this BEFORE writing your answer)
1. Call search_aws_knowledge_base with multiple targeted queries (different angles).
2. Call it again if the first results have relevance < 0.4 or miss key aspects.
3. FRESHNESS CHECK: If any retrieved chunk has ingestion_date older than 14 days AND \
   the topic involves a rapidly-evolving service (Bedrock, SageMaker, EKS, Lambda, \
   AgentCore, or any AI/ML service), call fetch_aws_page on that source URL to verify \
   the content is still current.
4. If knowledge base coverage is insufficient overall, call fetch_aws_page on the most \
   relevant official AWS documentation URL to fill the gap.
5. Collect ALL evidence BEFORE drafting your answer.

### PASS 2 — Synthesis
Using ONLY retrieved evidence, write your customer-ready answer following the mandatory \
structure below. Never answer from memory alone.

═══════════════════════════════════════════════════════
OUTPUT LABELING — REQUIRED ON EVERY CLAIM
═══════════════════════════════════════════════════════

Label every factual claim, recommendation, and design decision with one of:

  ✅ Documented Fact       — directly supported by retrieved AWS documentation
  💡 Design Recommendation — best practice or architecture choice per AWS guidance
  🔄 Alternative Option    — a valid alternative with different trade-offs
  ⚠️  Assumption           — inferred due to missing customer detail; state what you assumed

This single discipline dramatically reduces false confidence and helps the customer \
understand what is confirmed vs. what is your professional judgment.

═══════════════════════════════════════════════════════
UNCERTAINTY HANDLING
═══════════════════════════════════════════════════════

Use these explicit phrases when appropriate — never paper over gaps:
- "I could not verify this in the currently indexed AWS documentation."
- "This recommendation is inferred from related AWS guidance, not directly confirmed."
- "This needs verification against the live AWS page before implementation: [URL]"
- "My knowledge base does not yet cover this — I recommend ingesting [topic] for a \
   grounded answer."

═══════════════════════════════════════════════════════
CITATION FORMAT
═══════════════════════════════════════════════════════

Cite every factual claim inline:
  [Page Title](URL)  ·  *Indexed: YYYY-MM-DD*

For live-fetched pages (not yet in the knowledge base), use:
  [Page Title](URL)  ·  *Live-fetched: YYYY-MM-DD*

═══════════════════════════════════════════════════════
MANDATORY ANSWER STRUCTURE (Architecture Questions)
═══════════════════════════════════════════════════════

### 1. Customer Situation Summary
Restate the customer's environment, goals, and constraints in your own words to \
confirm understanding.

### 2. Key Assumptions
List every gap you filled with inference. Mark each ⚠️ Assumption so the customer \
can correct you before acting on the plan.

### 3. Recommended Architecture
Your primary recommendation with high-level justification.
Use a text diagram to show component relationships when helpful:
  Customer → [CloudFront] → [ALB] → [ECS Fargate] → [RDS Aurora]

### 4. Alternative Architectures (always provide exactly 2)
For each alternative:
- What it is and how it differs from the primary
- When you would choose this approach instead
- Key trade-offs vs. the primary recommendation
Label each choice ✅, 💡, or ⚠️ appropriately.

### 5. Why This Architecture Fits
Connect each design decision to the customer's stated goals, constraints, compliance \
needs, and skill level.

### 6. Component Deep-Dive
For EACH AWS service in the recommended architecture:
- **What it is**: Plain-English definition (no assumed knowledge)
- **Why we're using it**: The specific problem it solves here
- **Key configuration**: Exact settings, values, and why each matters
- **On-premises analogy**: Compare to a familiar concept (e.g., "think of this like...")
- **Common mistakes**: What to watch out for during setup

### 7. Step-by-Step Implementation Guide
Numbered steps a beginner could follow end-to-end:
- AWS Console navigation: Service → Section → Button/Action
- AWS CLI commands with EVERY flag explained in plain English
- What to verify/test after each step
- Approximate time for each step

### 8. Security, Networking & IAM
- IAM roles and policies required (with example policy JSON where helpful)
- VPC design, subnets, and security group rules
- Encryption at rest and in transit
- Compliance and audit considerations

### 9. Cost & Operations
- Rough monthly cost range (low / typical / high)
- Key cost drivers to watch
- Reserved Instance or Savings Plan opportunities
- Operational overhead estimate

### 10. Trade-offs Summary
| Factor | Recommended | Alternative 1 | Alternative 2 |
|---|---|---|---|
| Cost | | | |
| Complexity | | | |
| Performance | | | |
| Scalability | | | |
| Operational burden | | | |

### 11. Sources & Freshness Note
Bulleted list of all cited documentation with retrieval dates.

End EVERY architecture response with:
> 🕐 **Freshness Note**: Knowledge base content indexed on [earliest–latest dates shown \
> in retrieved chunks]. Live verification performed on [today's date] for \
> [any services where you called fetch_aws_page].
> ⚠️ AWS documentation — especially for Bedrock, SageMaker, and AI/ML services — \
> changes frequently. Verify all configuration details against the official \
> documentation before implementation.

═══════════════════════════════════════════════════════
SOURCE TIER AWARENESS
═══════════════════════════════════════════════════════

When constructing your answer, weight sources by tier:

  Tier 1 (Primary Truth) — AWS product docs, Bedrock docs, AgentCore docs
    → Use for: what a service does, APIs, features, limits, exact setup steps

  Tier 2 (Implementation Guidance) — AWS Prescriptive Guidance, Architecture Center
    → Use for: design decisions, recommended patterns, trade-offs, step-by-step guidance

  Tier 3 (Solution Accelerators) — AWS Solutions Library
    → Use for: vetted packaged solutions, repeatable deployment patterns

If a Tier 1 source contradicts a Tier 2/3 source, the Tier 1 source wins. Say so explicitly.

═══════════════════════════════════════════════════════
CUSTOMER CONTEXT ANALYSIS
═══════════════════════════════════════════════════════

When a customer architecture is provided, always analyze:
- Current infrastructure components and their AWS equivalents
- Business goals and how to measure success
- Constraints (budget, timeline, compliance, skill level, existing AWS footprint)
- Gaps and risks in the current environment
- Security and compliance concerns to flag BEFORE proposing changes
"""

CUSTOMER_CONTEXT_HEADER = """\
## Customer's Current Architecture
{context}

---
Please analyze the above environment and answer my question based on this context.

## My Question
"""


class AWSChatAgent:
    """
    Stateful chat agent. Maintains conversation history across turns.
    Create one instance per user session.
    """

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. "
                "Copy .env.example to .env and add your key."
            )
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.history: list[dict] = []

    # ── Status message helpers ────────────────────────────────────────────

    @staticmethod
    def _search_summary(result: str) -> str:
        """Parse a KB search result string and return a one-line summary."""
        count_m = re.search(r"Found (\d+) relevant", result)
        count = count_m.group(1) if count_m else "?"
        relevances = re.findall(r"relevance: ([\d.]+)", result)
        max_rel = max(float(r) for r in relevances) if relevances else 0.0
        tier1 = result.count("Tier 1")
        tier2 = result.count("Tier 2")
        tier3 = result.count("Tier 3")
        tier_parts = []
        if tier1:
            tier_parts.append(f"T1×{tier1}")
        if tier2:
            tier_parts.append(f"T2×{tier2}")
        if tier3:
            tier_parts.append(f"T3×{tier3}")
        tier_str = " " + " ".join(tier_parts) if tier_parts else ""
        return f"→ {count} chunks{tier_str} · best match {max_rel:.2f}"

    @staticmethod
    def _fetch_summary(result: str) -> str:
        """Return a one-line summary of a fetch_aws_page result."""
        if "Failed to fetch" in result or "Refused to fetch" in result:
            return "→ Failed to retrieve page"
        chars = len(result)
        return f"→ {chars:,} chars retrieved from live page"

    # ── Main chat method ──────────────────────────────────────────────────

    def chat(
        self,
        user_message: str,
        customer_context: str = "",
        status_callback=None,
    ) -> str:
        """
        Send a message and return the assistant's full response.

        Args:
            user_message: The user's question.
            customer_context: Optional description of the customer's environment.
            status_callback: Optional fn(str) called with status updates.
                Each call emits one line shown in the UI research log.

        Returns:
            The assistant's response text.
        """
        def _emit(msg: str):
            if status_callback:
                status_callback(msg)

        # Prepend customer context if provided
        if customer_context and customer_context.strip():
            full_message = CUSTOMER_CONTEXT_HEADER.format(
                context=customer_context.strip()
            ) + user_message
        else:
            full_message = user_message

        self.history.append({"role": "user", "content": full_message})

        had_tool_calls = False

        # Agentic loop
        while True:
            # Announce what Claude is about to do
            if had_tool_calls:
                _emit("✍️  Composing architecture response...")
            else:
                _emit("🧠  Sending question to Claude Sonnet 4.6...")

            with self.client.messages.stream(
                model=MODEL_NAME,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.history,
            ) as stream:
                response = stream.get_final_message()

            if response.stop_reason == "tool_use":
                had_tool_calls = True

                # Append the full assistant content (required before tool results)
                self.history.append({
                    "role": "assistant",
                    "content": response.content,
                })

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input

                    # ── Before-call status ────────────────────────────────
                    if tool_name == "search_aws_knowledge_base":
                        query = tool_input.get("query", "")
                        n = tool_input.get("n_results", 8)
                        _emit(f"🔍  Searching knowledge base ({n} results): \"{query}\"")

                    elif tool_name == "fetch_aws_page":
                        url = tool_input.get("url", "")
                        parsed = urlparse(url)
                        display = parsed.netloc + parsed.path[:55]
                        if len(parsed.path) > 55:
                            display += "…"
                        _emit(f"🌐  Fetching live AWS page: {display}")

                    logger.info("Tool call: %s  input=%s", tool_name, tool_input)
                    result = execute_tool(tool_name, tool_input)
                    logger.debug("Tool result: %d chars", len(result))

                    # ── After-call summary ────────────────────────────────
                    if tool_name == "search_aws_knowledge_base":
                        _emit(f"   {self._search_summary(result)}")
                    elif tool_name == "fetch_aws_page":
                        _emit(f"   {self._fetch_summary(result)}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                # Append tool results as a user turn
                self.history.append({
                    "role": "user",
                    "content": tool_results,
                })

            elif response.stop_reason == "end_turn":
                response_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        response_text = block.text
                        break

                self.history.append({
                    "role": "assistant",
                    "content": response_text,
                })

                return response_text

            else:
                logger.warning("Unexpected stop_reason: %s", response.stop_reason)
                return "An unexpected error occurred. Please try again."

    def clear_history(self):
        """Reset conversation history (but keep the agent configured)."""
        self.history = []

    @property
    def turn_count(self) -> int:
        """Number of user/assistant exchange pairs."""
        return len([m for m in self.history if m["role"] == "user"])
