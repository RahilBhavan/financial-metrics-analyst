"""The bounded capabilities exposed to an MCP client: four SEC fact tools and three treasury tools."""

import json

from .policy import MAX_YEARS, METRICS, TAGS, Refusal
from .contracts import output_schema, treasury_output_schema, validate_schema
from .treasury import ACTIONS, FIRMS


def analysis_schema(metrics):
    return {"type": "object", "additionalProperties": False,
            "required": ["cik", "fiscal_years", "metrics", "as_of"],
            "properties": {
                "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
                "fiscal_years": {"type": "array", "minItems": 1, "maxItems": MAX_YEARS, "uniqueItems": True,
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

DATE_ARG = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}
FIRM_ARG = {"type": "string", "enum": list(FIRMS)}
TREASURY_SCOPE = ("Strategy is MSTR (BTC), BitMine is BMNR (ETH), SharpLink is SBET (ETH). Data: dat-accretion's frozen export of "
                  "8-K/10-Q-sourced weekly states and capital actions from June 2026, on Strategy's net coins per share definition. ")
TREASURY_TOOLS = [
    {"name": "get_treasury_actions", "description": TREASURY_SCOPE + "List capital actions, most recent first, each with its exact "
     "effect on net coins per share (dat-accretion engine recompute), basis points of coins per share, USD value to common, and "
     "the SEC filing. action filters by type: issue_common (filed common sales, e.g. Strategy ATM), est_issuance (BitMine and "
     "SharpLink do not file per-week ATM sales; BitMine's weekly common issuance is estimated from share count and reserve "
     "changes), buyback_common, issue_pref, retire_pref, buy_coin, sell_coin, carry (preferred dividends, interest, staking). "
     "Weeks filter on the stated week ending date, inclusive. The first stated week is an anchor with no measured effects.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["firm"],
                     "properties": {"firm": FIRM_ARG, "action": {"type": "string", "enum": list(ACTIONS)},
                                    "week_from": DATE_ARG, "week_to": DATE_ARG,
                                    "limit": {"type": "integer", "minimum": 1, "maximum": 20}}}},
    {"name": "get_coins_per_share", "description": TREASURY_SCOPE + "Net coins per diluted share, net mNAV, prices, diluted shares "
     "and coin holdings for one stated week (default: latest), with its 8-K. compare_to adds a second stated week and the change "
     "between them (week_end minus compare_to).",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["firm"],
                     "properties": {"firm": FIRM_ARG, "week_end": DATE_ARG, "compare_to": DATE_ARG}}},
    {"name": "get_break_even", "description": TREASURY_SCOPE + "Preferred rotation break-even for one stated week (default: latest): "
     "liquidation preference ($100) x net mNAV. Strategy's rotation (issue common, retire STRC) adds net coins per share while STRC "
     "trades below it; BitMine's (issue BMNP, buy back common) while BMNP trades above it. SharpLink has no preferred and is refused.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["firm"],
                     "properties": {"firm": FIRM_ARG, "week_end": DATE_ARG}}},
]
for tool in TREASURY_TOOLS:
    tool["outputSchema"] = treasury_output_schema(tool["name"])
    tool["annotations"] = {"readOnlyHint": True, "openWorldHint": False}
TOOLS = TOOLS + TREASURY_TOOLS


def call_tool(analyst, name, arguments):
    definition = next((tool for tool in TOOLS if tool["name"] == name), None)
    if definition is None:
        raise Refusal("unknown_tool", "Unknown tool.")
    try:
        validate_schema(arguments, definition["inputSchema"])
        target = analyst
        if definition in TREASURY_TOOLS:
            target = getattr(analyst, "treasury", None)
            if target is None:
                raise Refusal("unsupported_tool", "This server instance has no treasury snapshot loaded.")
        result = getattr(target, name)(**arguments)
    except Refusal as exc:
        result = exc.as_dict()
    try:
        validate_schema(result, definition["outputSchema"], "result")
    except Refusal:
        result = Refusal("invalid_tool_output", "Generated result failed its output contract; no financial answer was returned.").as_dict()
    return {"structuredContent": result,
            "content": [{"type": "text", "text": json.dumps(result, allow_nan=False, separators=(",", ":"))}],
            "isError": result["status"] == "refused"}
