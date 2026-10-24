# Financial metrics analyst: an MCP server for SEC facts and ratios with filing provenance

[![CI](https://github.com/RahilBhavan/financial-metrics-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/RahilBhavan/financial-metrics-analyst/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![Apple FY2023–FY2025 report from the bundled SEC snapshot: revenue, gross profit, operating income, net income, margins and growth in USD millions, with footnoted warnings on the two growth figures that compare years of unequal length](docs/images/apple-demo-report.png)

This project has two parts. The first is a hand-written MCP stdio server and CLI on the Python standard library. It returns SEC XBRL facts and exact ratios for Apple, Microsoft and NVIDIA, plus crypto-treasury per-share figures from [dat-accretion](https://github.com/RahilBhavan/dat-accretion). Every number carries its filing accession, and the server calls no model. The second part is an optional Claude agent that answers questions through that server, with a deterministic gate that withholds any answer containing a number no tool returned.

## What it does

- **MCP server.** MCP 2025-11-25 over stdio, without the MCP SDK. It has 7 tools with closed input and full nested output schemas: 4 SEC tools (`resolve_company`, `get_annual_facts`, `get_quarterly_facts`, `calculate_metrics`) and 3 read-only treasury tools.
- **SEC coverage.** Revenue, gross profit, operating income, net income attributable to the issuer, gross margin, operating margin and revenue growth. Annual coverage runs through FY2026 per issuer, plus one reviewed NVIDIA quarter (Q2 FY2027).
- **Refuses rather than guesses.** "Microsoft profit 2025" returns `needs_clarification` (exit 3). An unsupported metric returns `refused` (exit 2). A newer conflicting filing blocks a stale value. The Kraft Heinz reference case flags FY2017 operating income restated from $6,773M to $6,057M.
- **Treasury-analyst agent (optional).** A Claude tool-use loop over the server. The model proposes tool calls and writes prose. It does not compute numbers.

| Check | Result | Source |
| --- | --- | --- |
| Source and intent evaluation | 161 / 161 cases pass | `reports/evaluation.json` |
| Unit tests | 114 run, 113 pass, 1 skipped | `python3 -B -m unittest discover -s tests` |
| Official `mcp==1.30.0` SDK interoperability | 28 / 28 checks pass | `reports/sdk-smoke.json` |
| Agent: correct tool and arguments, 42 in-scope tasks | 42 / 42 | `reports/agent-eval.json` |
| Agent: out-of-scope refusals, false refusals | 8 / 8, 0 | `reports/agent-eval.json` |
| Agent: numbers in delivered answers traced to a tool result | 368 / 368; 1 answer withheld | `reports/agent-eval.json` |

The agent results come from one run of a frozen 50-task set on 2026-10-21, with `claude-haiku-5-5` through the Claude Code CLI. Mean cost was $0.0013 per task. [docs/treasury-agent.md](docs/treasury-agent.md) has the full table and the known failures.

## How it works

- `financial_metrics/policy.py` defines the reviewed issuers, fiscal periods and approved US-GAAP tags.
- `financial_metrics/domain.py` selects one fact per period from the bundled SEC snapshots by exact dates, tag, form and filing cutoff. It records rejected candidates and revisions and computes exact rational ratios.
- `financial_metrics/contracts.py` and `tools.py` define the tools and validate every output. Output that fails validation becomes an `invalid_tool_output` refusal.
- `financial_metrics/server.py` is the stdio JSON-RPC server. `client.py` drives it as a subprocess for the CLI (`financial_metrics/__main__.py`).
- `financial_metrics/treasury.py` serves the frozen dat-accretion export in `data/treasury/snapshot.json`.
- `financial_metrics/agent.py` runs the model loop. `tracing.py` checks each number in a draft answer against the run's tool results.

## Run it

You need Python 3.9 or newer. The server, CLI and tests need no packages, account, API key or network.

```sh
git clone https://github.com/RahilBhavan/financial-metrics-analyst
cd financial-metrics-analyst
python3 -B -m unittest discover -s tests
python3 -B -m financial_metrics smoke
python3 -B -m financial_metrics demo
```

On Python 3.9, 3.11, 3.13 and 3.14.7 the test command printed `Ran 114 tests` and `OK (skipped=1)`. The skipped test rebuilds the treasury snapshot and runs only when `DAT_ACCRETION_REPO` points at a dat-accretion checkout.

More commands:

```sh
python3 -B -m financial_metrics analyze --ticker NVDA --years 2024 2025 2026 --as-of 2026-02-25
python3 -B -m financial_metrics ask "What were Apple's net sales and operating profit in FY2023 through FY2025?"
python3 -B -m financial_metrics ask 'Microsoft profit 2025'   # needs_clarification, exit 3
python3 -B -m financial_metrics demo --html reports/demo.html
python3 -B -m financial_metrics.evaluate                      # 161 cases; rewrites files in reports/
```

To use the server from an MCP host, point the host's stdio configuration at `server_stdio.py`. See [docs/mcp-server.md](docs/mcp-server.md) for the configuration and the SDK check, which needs Python 3.10 or newer and `requirements-sdk-test.txt`.

The agent needs a Claude model. Set `ANTHROPIC_API_KEY` for the Messages API backend, or have a signed-in `claude` CLI for the `claude-code` backend:

```sh
python3 -B -m financial_metrics.agent --backend claude-code "What is BitMine's BMNP break-even price?"
```

## Repository layout

- `financial_metrics/`: the server, CLI, selection logic, tools, agent and evaluations.
- `server_stdio.py`: the absolute-path launcher for MCP hosts.
- `data/`: SEC snapshots with manifests and ground-truth cards for AAPL, MSFT, NVDA and the Kraft Heinz reference case, plus the treasury export.
- `evals/`: the frozen agent tasks and the separate development questions.
- `tests/`: unit and subprocess tests.
- `reports/`: committed demo reports, evaluation results, SDK check output and agent transcripts.
- `scripts/`: report regeneration, the SDK check, the treasury export and the transcript renderer.
- `docs/`: methodology, server and agent documentation, and source research.
- `.github/workflows/`: CI tests on Python 3.9, 3.11 and 3.13, runs the SDK check and rebuilds the treasury snapshot.

## Documentation

- [docs/methodology.md](docs/methodology.md): fact selection and accounting rules, expected values, the Kraft Heinz case, CLI exit codes, proposals and the SEC refresh.
- [docs/mcp-server.md](docs/mcp-server.md): protocol, tool list, host configuration and the SDK interoperability check.
- [docs/treasury-agent.md](docs/treasury-agent.md): the agent loop, the number gate, the treasury tools and the 50-task evaluation with known failures.
- [docs/issuer-expansion-research.md](docs/issuer-expansion-research.md): primary-source evidence for Microsoft FY2026 and the NVIDIA profile.
- [EVALUATION.md](EVALUATION.md): the 161-case evaluation by group, reproduction commands and remaining limits.
- [WALKTHROUGH.md](WALKTHROUGH.md): one answer traced through the code, in reading order.
- [IMPROVEMENT-PLAN.md](IMPROVEMENT-PLAN.md): the six-step reliability plan from September 2026 and its completion evidence.

## Sources

- SEC companyfacts and submissions API responses, stored unmodified in `data/`. Apple, Microsoft and Kraft Heinz were captured on 2026-09-21 and NVIDIA on 2026-09-22. Each `manifest.json` records source URLs, byte counts and SHA-256 hashes.
- Ground-truth cards (`data/*/ground-truth.json`) are manual transcriptions from the issuers' 10-K, 10-Q and annual-report filings, linked in [EVALUATION.md](EVALUATION.md).
- Treasury data is a frozen export of dat-accretion commit `ce3b715`, weeks 2026-05-31 to 2026-10-11. dat-accretion builds it from 8-K and 10-Q filings, CoinGecko daily closes for BTC and ETH, and Yahoo daily closes for common and preferred shares. CI rebuilds it and requires byte equality.

## Scope and limits

- This is independent portfolio work. It is not affiliated with the SEC, Anthropic or any issuer named here.
- Coverage is narrow: 3 interactive issuers with reviewed annual periods and 1 reviewed NVIDIA quarter. Other quarters, EBITDA, cash flow, valuation, IFRS and currency conversion are unsupported.
- The SDK check is interoperability evidence with one second client, not protocol certification or a test in each desktop host.
- The agent evaluation is one run of templated tasks. It does not measure open-ended questions, run-to-run variance or prompt-injection resistance. The Messages API backend has not been run live.
- Filing-date filtering does not recreate past API contents. A changed value is flagged as a revision, not classified as a restatement without a source.
- No live SEC refresh with a user's contact information was run.

## License

[MIT](LICENSE). The license covers this project's code, not SEC filings, issuer reports or third-party market data.

Part of [Rahil Bhavan's projects](https://github.com/RahilBhavan).
