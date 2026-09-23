"""The four bounded capabilities exposed to an MCP client."""

import json

from .policy import METRICS, TAGS, Refusal
from .contracts import output_schema, validate_schema


def analysis_schema(metrics):
    return {"type": "object", "additionalProperties": False,
            "required": ["cik", "fiscal_years", "metrics", "as_of"],
            "properties": {
                "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
                "fiscal_years": {"type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
                                 "items": {"type": "integer", "minimum": 2023, "maximum": 2026}},
                "metrics": {"type": "array", "minItems": 1, "maxItems": len(metrics), "uniqueItems": True,
                            "items": {"type": "string", "enum": list(metrics)}},
                "as_of": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
            }}


TOOLS = [
    {"name": "resolve_company", "description": "Resolve AAPL, MSFT, or NVDA to its reviewed issuer using the bundled SEC submissions snapshot. No network or fuzzy search.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["ticker"],
                     "properties": {"ticker": {"type": "string", "pattern": "^[A-Za-z]{1,5}$"}}}},
    {"name": "get_annual_facts", "description": "Read reviewed AAPL, MSFT, and NVDA annual facts through FY2026 where available, with filing provenance, candidate rejections, and revision history. as_of is inclusive and cannot exceed the snapshot date.",
     "inputSchema": analysis_schema(tuple(TAGS))},
    {"name": "get_quarterly_facts", "description": "Read NVIDIA's reviewed Q2 FY2027 facts using exact quarter dates, excluding year-to-date values. Additional quarters remain outside the reviewed scope.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["cik", "fiscal_year", "quarter", "metrics", "as_of"],
                     "properties": {
                         "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
                         "fiscal_year": {"type": "integer", "minimum": 2027, "maximum": 2027},
                         "quarter": {"type": "string", "enum": ["Q2"]},
                         "metrics": {"type": "array", "minItems": 1, "maxItems": len(TAGS), "uniqueItems": True,
                                     "items": {"type": "string", "enum": list(TAGS)}},
                         "as_of": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}}}},
    {"name": "calculate_metrics", "description": "Calculate reviewed annual facts, gross and operating margins, and revenue growth for AAPL, MSFT, and NVDA. Percentages are exact rational results rendered as decimal strings. Unsupported scope is refused.",
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
