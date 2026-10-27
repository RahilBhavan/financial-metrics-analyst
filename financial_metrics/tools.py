"""The bounded capabilities exposed to an MCP client: four SEC fact tools and three treasury tools."""

import json

from .policy import ANNUAL_TAGS, MAX_YEARS, METRICS, PROFILES, QUARTERS, QUARTER_METRICS, Refusal
from .contracts import DATE, REVIEWED_YEAR, output_schema, treasury_output_schema, validate_schema
from .treasury import ACTIONS, FIRMS


TICKERS = ", ".join(profile["ticker"] for profile in PROFILES.values())
QUARTER_YEARS = sorted({year for year, _ in QUARTERS})


def analysis_schema(metrics):
    return {"type": "object", "additionalProperties": False,
            "required": ["cik", "fiscal_years", "metrics", "as_of"],
            "properties": {
                "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
                "fiscal_years": {"type": "array", "minItems": 1, "maxItems": MAX_YEARS, "uniqueItems": True,
                                 "items": REVIEWED_YEAR},
                "metrics": {"type": "array", "minItems": 1, "maxItems": len(metrics), "uniqueItems": True,
                            "items": {"type": "string", "enum": list(metrics)}},
                "as_of": DATE,
            }}


TOOLS = [
    {"name": "resolve_company", "description": "Resolve one reviewed ticker (" + TICKERS + ") to its issuer using the bundled SEC submissions snapshot. No network or fuzzy search.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["ticker"],
                     "properties": {"ticker": {"type": "string", "pattern": "^[A-Za-z]{1,5}$"}}}},
    {"name": "get_annual_facts", "description": "Read reviewed annual income, operating/investing/financing cash flows and cash capital expenditures (signed USD) for " + TICKERS + " (FY2023-FY2025, plus FY2026 for MSFT and NVDA where reviewed), with filing provenance, candidate rejections, and revision history. A metric the issuer's income statement does not report, such as gross profit for a bank-like filer, is returned as insufficient_data, never zero. as_of is inclusive and cannot exceed the snapshot date.",
     "inputSchema": analysis_schema(tuple(ANNUAL_TAGS))},
    {"name": "get_quarterly_facts", "description": "Read the reviewed fiscal quarters (six reviewed 10-Q periods per issuer in the snapshot, Q1 to Q3; the fiscal fourth quarter has no 10-Q) using exact quarter dates. Income facts are direct three-month records; cash-flow totals and cash capex use current YTD minus preceding-quarter YTD with both filing sources. Free cash flow is operating cash flow minus cash capital expenditures. Other quarters are refused.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["cik", "fiscal_year", "quarter", "metrics", "as_of"],
                     "properties": {
                         "cik": {"type": "string", "pattern": "^[0-9]{10}$"},
                         "fiscal_year": {"type": "integer", "minimum": min(QUARTER_YEARS), "maximum": max(QUARTER_YEARS)},
                         "quarter": {"type": "string", "enum": sorted({quarter for _, quarter in QUARTERS})},
                         "metrics": {"type": "array", "minItems": 1, "maxItems": len(QUARTER_METRICS), "uniqueItems": True,
                                     "items": {"type": "string", "enum": list(QUARTER_METRICS)}},
                         "as_of": DATE}}},
    {"name": "calculate_metrics", "description": "Calculate reviewed annual facts, gross and operating margins, revenue growth and free cash flow (operating cash flow minus cash capital expenditures) for " + TICKERS + ". Percentages are exact rational results rendered as decimal strings. Unsupported scope is refused.",
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
