"""The only three capabilities exposed to an MCP client."""

import json

from .policy import METRICS, TAGS, Refusal
from .contracts import output_schema, validate_schema


def analysis_schema(metrics):
    return {"type": "object", "additionalProperties": False,
            "required": ["cik", "fiscal_years", "metrics", "as_of"],
            "properties": {
                "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
                "fiscal_years": {"type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
                                 "items": {"type": "integer", "minimum": 2023, "maximum": 2025}},
                "metrics": {"type": "array", "minItems": 1, "maxItems": len(metrics), "uniqueItems": True,
                            "items": {"type": "string", "enum": list(metrics)}},
                "as_of": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
            }}


TOOLS = [
    {"name": "resolve_company", "description": "Resolve AAPL or MSFT to its reviewed issuer using the bundled SEC submissions snapshot. No network or fuzzy search.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["ticker"],
                     "properties": {"ticker": {"type": "string", "pattern": "^[A-Za-z]{1,5}$"}}}},
    {"name": "get_annual_facts", "description": "Read reviewed AAPL/MSFT FY2023-FY2025 USD annual facts with filing provenance, candidate rejections, and revision history. as_of is inclusive and cannot exceed the snapshot date.",
     "inputSchema": analysis_schema(tuple(TAGS))},
    {"name": "calculate_metrics", "description": "Calculate reviewed AAPL/MSFT annual metrics with exact inputs and rational results. Percentages are decimal strings. FY2022 revenue supports FY2023 growth. Growth flags unequal fiscal period lengths. Unsupported scope is refused.",
     "inputSchema": analysis_schema(METRICS)},
]
for tool in TOOLS:
    tool["outputSchema"] = output_schema(tool["name"])
    tool["annotations"] = {"readOnlyHint": True, "openWorldHint": False}


def call_tool(analyst, name, arguments):
    definition = next((tool for tool in TOOLS if tool["name"] == name), None)
    if definition is None:
        raise Refusal("unknown_tool", "Unknown tool.")
    try:
        validate_schema(arguments, definition["inputSchema"])
        result = getattr(analyst, name)(**arguments)
    except Refusal as exc:
        result = exc.as_dict()
    try:
        validate_schema(result, definition["outputSchema"], "result")
    except Refusal:
        result = Refusal("invalid_tool_output", "Generated result failed its output contract; no financial answer was returned.").as_dict()
    return {"structuredContent": result,
            "content": [{"type": "text", "text": json.dumps(result, allow_nan=False, separators=(",", ":"))}],
            "isError": result["status"] == "refused"}
