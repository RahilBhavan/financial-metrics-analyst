# MCP server: protocol, contracts and hosting

This page describes what the MCP server implements, how to connect a host to it, and how the independent SDK check works. Code: `financial_metrics/server.py`, `financial_metrics/tools.py`, `financial_metrics/contracts.py` and `server_stdio.py`.

## Protocol

The server implements MCP **2025-11-25** over newline-delimited JSON-RPC on stdio. It is hand-written on the Python standard library and does not use the MCP SDK. It handles `initialize`, `notifications/initialized`, `ping`, `tools/list` and `tools/call`. It has no HTTP transport and no arbitrary network, file or execution capability. The server calls no model.

## Tools

| Tool | Data | What it returns |
| --- | --- | --- |
| `resolve_company` | SEC submissions snapshot | The reviewed issuer for AAPL, MSFT or NVDA. No network or fuzzy search. |
| `get_annual_facts` | SEC companyfacts snapshot | Reviewed annual facts through FY2026 where available, with filing provenance, candidate rejections and revision history. |
| `get_quarterly_facts` | SEC companyfacts snapshot | NVIDIA Q2 FY2027 only, with exact quarter dates and no year-to-date values. |
| `calculate_metrics` | SEC companyfacts snapshot | Annual facts, gross and operating margins, and revenue growth as exact rational results. |
| `get_treasury_actions` | dat-accretion export | Capital actions for MSTR, BMNR and SBET, with the change in net coins per share. |
| `get_coins_per_share` | dat-accretion export | Net coins per diluted share for one or two weeks. |
| `get_break_even` | dat-accretion export | Preferred rotation break-even for STRC and BMNP. |

The treasury tools are described in [treasury-agent.md](treasury-agent.md).

All seven tools publish and enforce closed input schemas and **full nested output schemas**. The output schemas cover provenance, history, warnings, ratios, context, unavailable rows and refusals. If generated output fails validation, the server returns an `invalid_tool_output` refusal. Schemas validate structure. Separate source and arithmetic checks validate financial meaning.

## Connect a host

Use your host's stdio configuration with the absolute launcher path:

```json
{
  "mcpServers": {
    "financial-metrics": {
      "command": "/usr/bin/python3",
      "args": ["-B", "/absolute/path/to/financial-metrics-analyst/server_stdio.py"]
    }
  }
}
```

Change the executable and project paths when you move computers. The launcher works from an unrelated working directory.

## Check the server

```sh
python3 -B -m financial_metrics smoke
python3 -B -m unittest discover -s tests -v
python3 -B -m financial_metrics.evaluate
```

`smoke` starts the server as a subprocess, lists the seven tools, reads 9 facts and 6 numeric ratios, checks that an unsupported metric is refused, and confirms a clean exit. `evaluate` writes each case and the AAPL, MSFT and NVDA demos into `reports/`, and prints unit-test counts and timing. `python3 scripts/regenerate_reports.py` rewrites every committed report against a fixed clock (`--today YYYY-MM-DD`, default the newest snapshot capture date). CI fails if the committed reports drift.

## Independent SDK check

The optional SDK check needs Python 3.10 or newer in a separate environment:

```sh
python3.11 -m venv .venv-sdk
.venv-sdk/bin/python -m pip install --require-hashes -r requirements-sdk-test.txt
.venv-sdk/bin/python -B scripts/verify_sdk.py
```

It uses the official `mcp==1.30.0` client and the `jsonschema==4.26.0` validator. `requirements-sdk-test.txt` pins every transitive package by hash; it is compiled from `requirements-sdk-test.in` with `uv pip compile --generate-hashes --python-version 3.11 --python-platform linux`. It negotiates the protocol, discovers seven tools, validates their schema documents, calls every tool across all three issuers, exercises two refusals, checks that the independent validator rejects six malformed nested outputs, and pings. The 28 checks are recorded in [reports/sdk-smoke.json](../reports/sdk-smoke.json). This is interoperability evidence with a second client. It is not protocol certification or a test in every desktop host.
