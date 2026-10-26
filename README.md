# Financial metrics analyst: an MCP server for SEC facts and ratios with filing provenance

[![CI](https://github.com/RahilBhavan/financial-metrics-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/RahilBhavan/financial-metrics-analyst/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![Apple FY2023–FY2025 report from the bundled SEC snapshot: revenue, gross profit, operating income, net income, margins and growth in USD millions, with footnoted warnings on the two growth figures that compare years of unequal length](docs/images/apple-demo-report.png)

This project has two parts. The first is a hand-written MCP stdio server and CLI on the Python standard library. It returns SEC XBRL facts and exact ratios for ten issuers (Apple, Microsoft, NVIDIA, Coinbase, Strategy, Robinhood, Block, PayPal, Visa and Tesla), plus crypto-treasury per-share figures from [dat-accretion](https://github.com/RahilBhavan/dat-accretion). Every number carries its filing accession, and the server calls no model. The second part is an optional Claude agent that answers questions through that server, with a deterministic gate that withholds any answer containing a number no tool returned.

## What it does

- **MCP server.** MCP 2025-11-25 over stdio, without the MCP SDK. It has 7 tools with closed input and full nested output schemas: 4 SEC tools (`resolve_company`, `get_annual_facts`, `get_quarterly_facts`, `calculate_metrics`) and 3 read-only treasury tools.
- **SEC coverage.** Revenue, gross profit, operating income, net income attributable to the issuer, gross margin, operating margin and revenue growth for 10 issuers: FY2023–FY2025 each, plus FY2026 for Microsoft and NVIDIA. Each issuer also has its 4 latest reviewed 10-Q quarters (40 in all). A metric the issuer's income statement does not report (gross profit for Coinbase, Robinhood, PayPal and Visa; operating income for Robinhood) is returned as unavailable, never zero.
- **Refuses rather than guesses.** "Microsoft profit 2025" returns `needs_clarification` (exit 3). An unsupported metric returns `refused` (exit 2). A newer conflicting filing blocks a stale value. The Kraft Heinz reference case flags FY2017 operating income restated from $6,773M to $6,057M.
- **Treasury-analyst agent (optional).** A Claude tool-use loop over the server. The model proposes tool calls and writes prose. It does not compute numbers.

| Check | Result | Source |
| --- | --- | --- |
| Source and intent evaluation | 947 / 947 cases pass (161 before the ten-issuer expansion) | `reports/evaluation.json` |
| Unit tests | 167 run, 166 pass, 1 skipped | `python3 -B -m unittest discover -s tests` |
| Official `mcp==1.30.0` SDK interoperability | 33 / 33 checks pass | `reports/sdk-smoke.json` |
| Agent: correct tool and arguments, 42 in-scope tasks | 42 / 42 | `reports/agent-eval.json` |
| Agent: out-of-scope refusals, false refusals | 8 / 8, 0 | `reports/agent-eval.json` |
| Agent: numbers in delivered answers traced to a tool result | 368 / 368; 1 answer withheld | `reports/agent-eval.json` |

The agent results come from one run of a frozen 50-task set on 2026-10-21 with `claude-haiku-5-5` through the Claude Code CLI, at a mean cost of $0.0013 per task. [docs/treasury-agent.md](docs/treasury-agent.md) has the full table and known failures.

## How it works

- `policy.py` defines the reviewed issuers, fiscal periods and approved US-GAAP tags.
- `domain.py` selects one fact per period from the bundled SEC snapshots by exact dates, tag, form and filing cutoff, records rejected candidates and revisions, and computes exact rational ratios.
- `contracts.py` and `tools.py` define the tools and validate every output; invalid output becomes an `invalid_tool_output` refusal.
- `server.py` is the stdio JSON-RPC server; `client.py` drives it as a subprocess for the CLI.
- `treasury.py` serves the frozen dat-accretion export.
- `agent.py` runs the model loop; `tracing.py` checks each number in a draft answer against the run's tool results.

All modules live in `financial_metrics/`.

## Run it

You need Python 3.9 or newer. The server, CLI and tests need no packages, account, API key or network.

```sh
git clone https://github.com/RahilBhavan/financial-metrics-analyst
cd financial-metrics-analyst
python3 -B -m unittest discover -s tests
python3 -B -m financial_metrics smoke
python3 -B -m financial_metrics demo
```

On Python 3.9 and 3.14.7 the test command printed `Ran 167 tests` and `OK (skipped=1)`; CI also runs 3.11 and 3.13. The skipped test rebuilds the treasury snapshot and runs only when `DAT_ACCRETION_REPO` points at a dat-accretion checkout.

More commands:

```sh
python3 -B -m financial_metrics analyze --ticker NVDA --as-of 2026-02-25   # every reviewed NVIDIA year
python3 -B -m financial_metrics analyze --ticker NVDA --quarter Q2          # latest reviewed Q2, labeled Q2 FY2027
python3 -B -m financial_metrics ask 'Microsoft profit 2025'   # needs_clarification, exit 3
python3 -B -m financial_metrics.evaluate                      # 947 cases; rewrites files in reports/
```

To use the server from an MCP host, point the host's stdio configuration at `server_stdio.py` (it also works under `python -P`), or run `pip install -e .` for `financial-metrics` and `financial-metrics-mcp` commands. Use an editable install: the snapshots in `data/` are not packaged. See [docs/mcp-server.md](docs/mcp-server.md) for the configuration and the SDK check, which needs Python 3.10 or newer and `requirements-sdk-test.txt`.

The agent needs a Claude model. Set `ANTHROPIC_API_KEY` for the Messages API backend, or have a signed-in `claude` CLI for the `claude-code` backend:

```sh
python3 -B -m financial_metrics.agent --backend claude-code "What is BitMine's BMNP break-even price?"
```

## Repository layout

- `financial_metrics/`: the server, CLI, selection logic, tools, agent and evaluations.
- `server_stdio.py`: the absolute-path launcher for MCP hosts.
- `data/`: SEC snapshots with manifests and ground-truth cards, plus the treasury export.
- `evals/`: the frozen agent tasks and the separate development questions.
- `tests/`: unit and subprocess tests.
- `reports/`: committed demo reports, evaluation results, SDK check output and agent transcripts.
- `scripts/`: report regeneration, the SDK check, the filing review tool, the treasury export and the transcript renderer.
- `docs/`: methodology, server and agent documentation, and source research.
- `.github/workflows/`: lint (pyflakes), tests on Python 3.9, 3.11 and 3.13, the SDK check and the treasury snapshot rebuild.

## Documentation

- [docs/methodology.md](docs/methodology.md): fact selection and accounting rules, expected values, the Kraft Heinz case, CLI exit codes, proposals and the SEC refresh.
- [docs/mcp-server.md](docs/mcp-server.md): protocol, tool list, host configuration and the SDK interoperability check.
- [docs/treasury-agent.md](docs/treasury-agent.md): the agent loop, the number gate, the treasury tools and the 50-task evaluation with known failures.
- [docs/issuer-expansion-research.md](docs/issuer-expansion-research.md): primary-source evidence for Microsoft FY2026 and NVIDIA.
- [EVALUATION.md](EVALUATION.md): the 947-case evaluation by group, reproduction commands and remaining limits.
- [WALKTHROUGH.md](WALKTHROUGH.md): one answer traced through the code, in reading order.
- [IMPROVEMENT-PLAN.md](IMPROVEMENT-PLAN.md): the September 2026 reliability plan and its completion evidence.

## Sources

- SEC companyfacts and submissions API responses, stored unmodified in `data/`. Apple, Microsoft and Kraft Heinz were captured on 2026-09-21, NVIDIA on 2026-09-22 and the seven added issuers on 2026-10-25. Each `manifest.json` records source URLs, byte counts and SHA-256 hashes.
- Ground-truth cards (`data/*/ground-truth.json`) are transcriptions from the issuers' 10-K, 10-Q and annual-report filings, linked in [EVALUATION.md](EVALUATION.md). The seven added issuers' cards, and every issuer's quarters, are read from the filing documents' income statements by `scripts/review_filings.py`, which never opens companyfacts.
- Treasury data is a frozen export of dat-accretion commit `ce3b715`, weeks 2026-05-31 to 2026-10-11. It is built from 8-K and 10-Q filings plus CoinGecko and Yahoo daily closes; CI rebuilds it and requires byte equality.

## Scope and limits

- Independent portfolio work, not affiliated with the SEC, Anthropic or any issuer named here.
- Coverage is bounded: 10 issuers, reviewed annual periods and 4 reviewed 10-Q quarters each. The SEC API held no facts for the PayPal and Visa 10-Qs filed in July 2026, so those quarters are not reviewed. Other quarters, EBITDA, cash flow, valuation, IFRS and currency conversion are unsupported. JPMorgan was left out: its companyfacts holds no gross profit or operating income facts and its 7.99 MB file sits just under the loader's 8 MiB limit.
- The agent evaluation predates the wider coverage and its prompt still names three issuers.
- The SDK check is interoperability evidence with one second client, not protocol certification or a test in each desktop host.
- The agent evaluation is one run of templated tasks. It does not measure open-ended questions, run-to-run variance or prompt-injection resistance. The Messages API backend has not been run live.
- Filing-date filtering does not recreate past API contents. A changed value is flagged as a revision, not classified as a restatement without a source.
- A live SEC refresh with a real contact User-Agent was run once, on 2026-10-18, for AAPL, MSFT and NVDA (`reports/live-refresh.json`). `scripts/live_refresh_check.py` now covers all ten issuers and every reviewed quarter, but has not been rerun live since.

## License

[MIT](LICENSE). The license covers this project's code, not SEC filings, issuer reports or third-party market data.

Part of [Rahil Bhavan's projects](https://github.com/RahilBhavan).
