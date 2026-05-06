"""
Anthropic tool schema definitions passed to client.messages.create(tools=...).

TOOLS              — chat agent: KB search + live AWS page fetch
DISCOVERY_TOOLS    — discovery agent: web search + KB search + live AWS page fetch
"""

_SEARCH_WEB_TOOL = {
    "name": "search_web",
    "description": (
        "Search the public web for company intelligence, news, tech stack signals, "
        "recent announcements, funding, M&A activity, and industry context. "
        "Use this to research a customer before a discovery call. "
        "Run multiple queries to cover: company overview, recent news, technology signals, "
        "and any industry-specific regulatory or compliance context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A specific search query. Be targeted. "
                    "Examples: 'Acme Corp company overview employees industry', "
                    "'Acme Corp AWS cloud migration 2024', "
                    "'Acme Corp HIPAA compliance security'"
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Number of web results to return (default 5, max 10).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

_SEARCH_KB_TOOL = {
    "name": "search_aws_knowledge_base",
    "description": (
        "Search the locally indexed AWS documentation knowledge base using semantic search. "
        "ALWAYS call this tool first when you need information about any AWS service, "
        "architecture pattern, best practice, or implementation detail. "
        "Returns the most relevant documentation chunks with source URLs and retrieval dates."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A descriptive search query. Be specific — include the service name, "
                    "feature, and what you need to know. "
                    "Example: 'Lambda function configuration memory timeout best practices'"
                ),
            },
            "n_results": {
                "type": "integer",
                "description": "Number of documentation chunks to retrieve (default 8, max 15).",
                "default": 8,
            },
        },
        "required": ["query"],
    },
}

_FETCH_AWS_PAGE_TOOL = {
    "name": "fetch_aws_page",
    "description": (
        "Fetch and read a specific AWS documentation page directly from the web. "
        "Use this when:\n"
        "  1. The knowledge base returns low-relevance results for your query, OR\n"
        "  2. The user references a specific AWS URL, OR\n"
        "  3. You need the most current information on a rapidly-changing service.\n"
        "Only use URLs from: docs.aws.amazon.com, aws.amazon.com/solutions, "
        "aws.amazon.com/prescriptive-guidance, aws.amazon.com/architecture."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full HTTPS URL of the AWS documentation page to fetch.",
            },
        },
        "required": ["url"],
    },
}

# Chat agent: no web search (stays focused on AWS docs)
TOOLS = [_SEARCH_KB_TOOL, _FETCH_AWS_PAGE_TOOL]

# Discovery agent: web search first, then KB, then optional live fetch
DISCOVERY_TOOLS = [_SEARCH_WEB_TOOL, _SEARCH_KB_TOOL, _FETCH_AWS_PAGE_TOOL]
