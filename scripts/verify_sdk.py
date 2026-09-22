"""Optional independent MCP interoperability check; requires mcp==1.30.0."""

import asyncio
import copy
import importlib.metadata
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    checks = []
    params = StdioServerParameters(command=sys.executable, args=["-B", "-m", "financial_metrics.server"], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            checks.append({"case": "protocol negotiation", "passed": init.protocolVersion == "2025-11-25"})
            tools = (await session.list_tools()).tools
            checks.append({"case": "three named tools", "passed": {t.name for t in tools} == {"resolve_company", "get_annual_facts", "calculate_metrics"}})
            for tool in tools:
                Draft202012Validator.check_schema(tool.inputSchema)
                Draft202012Validator.check_schema(tool.outputSchema)
                checks.append({"case": tool.name + " valid schemas", "passed": True})
            schemas = {t.name: t.outputSchema for t in tools}
            arguments = {"cik": "0000320193", "fiscal_years": [2023, 2024, 2025], "metrics": ["revenue"], "as_of": "2026-09-21"}
            calls = [("resolve_company", {"ticker": "AAPL"}, "ok"),
                     ("get_annual_facts", arguments, "ok"),
                     ("calculate_metrics", {**arguments, "metrics": ["operating_margin", "revenue_growth"]}, "ok"),
                     ("calculate_metrics", {**arguments, "metrics": ["ebitda"]}, "refused"),
                     ("resolve_company", {"ticker": "MSFT"}, "ok"),
                     ("calculate_metrics", {**arguments, "cik": "0000789019", "metrics": ["revenue", "net_income", "operating_income", "operating_margin", "revenue_growth"]}, "ok")]
            for tool, args, status in calls:
                result = await session.call_tool(tool, args)
                Draft202012Validator(schemas[tool], format_checker=FormatChecker()).validate(result.structuredContent)
                checks.append({"case": tool + " " + status,
                               "passed": result.structuredContent["status"] == status and json.loads(result.content[0].text) == result.structuredContent and result.isError == (status == "refused")})
            # Exercise a second validator against deliberately malformed nested output.
            valid = (await session.call_tool("calculate_metrics", {**arguments, "metrics": ["revenue_growth"]})).structuredContent
            validator = Draft202012Validator(schemas["calculate_metrics"], format_checker=FormatChecker())
            for defect in ("missing accession", "float amount", "invalid date", "unknown nested field", "zero denominator", "missing history tag"):
                broken = copy.deepcopy(valid)
                row = broken["results"][0]
                fact = row["inputs"][0]
                if defect == "missing accession": del fact["accn"]
                elif defect == "float amount": fact["value"] = 1.1
                elif defect == "invalid date": fact["filed"] = "2025-02-30"
                elif defect == "unknown nested field": fact["execute"] = "shell"
                elif defect == "zero denominator": row["exact_fraction"]["denominator"] = "0"
                elif defect == "missing history tag": del fact["history"][0]["tag"]
                rejected = False
                try: validator.validate(broken)
                except ValidationError: rejected = True
                checks.append({"case": "independent rejection: " + defect, "passed": rejected})
            await session.send_ping()
            checks.append({"case": "ping", "passed": True})
    report = {"sdk": "mcp", "sdk_version": importlib.metadata.version("mcp"), "python": sys.version.split()[0],
              "transport": "stdio subprocess", "passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks}
    (ROOT / "reports" / "sdk-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if all(c["passed"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
