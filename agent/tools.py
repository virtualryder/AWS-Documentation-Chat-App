"""
Anthropic tool schema definitions passed to client.messages.create(tools=...).
"""

TOOLS = [
    {
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
    },
    {
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
    },
]
