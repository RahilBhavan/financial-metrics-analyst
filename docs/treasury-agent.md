# Treasury-analyst agent

This page describes the optional Claude agent, its three treasury tools, and its frozen 50-task evaluation. The MCP server and CLI do not need it. Code: `financial_metrics/agent.py`, `financial_metrics/tracing.py`, `financial_metrics/agent_eval.py` and `financial_metrics/treasury.py`.

## What the agent does

The agent is a Claude tool-use loop. It starts this package's MCP stdio server as a subprocess, sends the model the server's seven tools plus a `refuse` tool, and answers questions such as "How did BitMine's last ATM raise change ETH per share?". The model only proposes tool calls and writes prose. Tools run in the server process with their own schema validation. The model gets no shell, file or network access.

Before the agent delivers an answer, `tracing.trace_numbers` checks every number in the answer against the tool results of that run. An answer with an untraced number gets one rewrite request. If the rewrite also fails, the agent withholds the answer with status `abstained_untraced`.

The agent has two model backends:

- `AnthropicMessages` calls the Messages API with native tool use. It needs `ANTHROPIC_API_KEY`. The default model is `claude-haiku-5-5`. Unit tests check the request and response shape. It has not been run live.
- `ClaudeCodeCLI` runs `claude -p --output-format json` with built-in tools disabled. It puts the tool catalog in the system prompt, and the model replies with one JSON object per turn. The recorded evaluation used this backend because the build machine has no API key.

## Treasury tools

The server serves three read-only tools built on [dat-accretion](https://github.com/RahilBhavan/dat-accretion)'s per-share engine, for Strategy (MSTR), BitMine (BMNR) and SharpLink (SBET):

- `get_treasury_actions` lists capital actions, most recent first. Each action has the engine's exact change in net coins per share, basis points, USD value to common and the 8-K.
- `get_coins_per_share` returns one stated week or two, with the change between them.
- `get_break_even` returns liquidation preference × net mNAV for STRC and BMNP.

`scripts/export_dat_snapshot.py` runs `dat.engine.attribute` on a clean dat-accretion checkout and writes `data/treasury/snapshot.json`. It refuses to write if the rebuild differs from that checkout's `attribution.csv` or `weekly.csv`. The `treasury-snapshot` CI job rebuilds the snapshot at the pinned commit and requires byte equality. Tests pin method.md's STRC anchor ($3.893M to common) and the memo's break-evens ($119.07 and $99.79). They also check that every served number carries an SEC filing URL and accession.

## Frozen 50-task evaluation

One run on 2026-10-21. Model `claude-haiku-5-5` through the Claude Code CLI backend, not the Messages API. The tasks in `evals/agent-tasks.json` were committed (450af5b) before any agent run. The prompt and tracer were built on the separate `evals/dev-questions.json` and were not changed after the run. Source: `reports/agent-eval.json`.

| Metric | Result |
| --- | ---: |
| Tool selection (42 in-scope tasks) | 42 / 42 (100%) |
| Arguments: scored arguments match and the call returns the expected record | 42 / 42 (100%) |
| Expected numbers quoted in the delivered answer | 41 / 42 (97.6%) |
| Numbers in delivered answers traced to a tool result | 368 / 368 (100%, enforced by the gate) |
| Numbers in first drafts traced, before the gate | 379 / 383 (99.0%) |
| Answers withheld by the gate | 1 (S06) |
| Out-of-scope refusals | 8 / 8 |
| False refusals on in-scope tasks | 0 |
| Latency per task, p50 / p90 / max | 6.3 s / 9.3 s / 13.3 s |
| Tokens per task, mean (input including cache, plus output) | 10,249 |
| Cost per task, mean (CLI-reported, list price) | $0.0013; $0.066 for all 50 |
| Tool calls per task, mean | 1.2 |

By category: treasury actions 16/16, coins per share 9/9, break-even 7/7. SEC facts scored 10/10 on tool and arguments and 9/10 on every other column. Full records are in [reports/agent-runs.jsonl](../reports/agent-runs.jsonl), scores are in [reports/agent-eval.json](../reports/agent-eval.json), and [reports/agent-transcripts.html](../reports/agent-transcripts.html) is a script-free transcript viewer.

## Known failures and limits

- **S06 withheld (Microsoft FY2026 gross margin).** The first draft paraphrased the warning code `snapshot_older_than_7_days` as "older than 7 days". The tracer does not read numbers inside identifiers, so it flagged "7". The rewrite then mistyped the period start as 2026-07-01, and the gate withheld the answer. The second rejection caught a real error. The first was a tracer false positive. The same "7" caused the other three first-draft rejections (S07, S09, S10), which passed after one rewrite. This was not fixed after the run, because a fix would tune against the frozen set.
- The tasks are templated and name exact weeks and metrics, so these rates do not measure open-ended or ambiguous questions. Each task ran once at default sampling. There are no repeats and no variance estimate.
- Expected numbers come from the same deterministic tools. The evaluation measures the agent's tool use and quoting, not tool correctness. Tool correctness rests on the 161-case evaluation in [EVALUATION.md](../EVALUATION.md) and dat-accretion's own tests.
- Tracing compares magnitudes at the precision shown. It accepts rounding and drops sign ("reduced by 0.85 bps" traces to −0.849852). Small integers must match exactly. Dates, accessions and URLs must appear verbatim. Tracing proves that a number came from a tool result. It does not prove that the number is attached to the right label.
- Latency includes about 1 s of CLI start-up per model turn. Cost and tokens are the CLI's figures.
- Prompt-injection resistance has not been measured.
- Treasury data is a frozen export of dat-accretion commit `ce3b715` (weeks 2026-05-31 to 2026-10-11). BitMine does not file per-week ATM sales, so its "ATM" answers use `est_issuance` rows, labeled estimated. dat-accretion computes in binary floating point. The tools serve values with ten significant digits.

## Run it

```sh
python3 -B -m financial_metrics.agent "How did BitMine's last ATM raise change ETH per share?"            # ANTHROPIC_API_KEY set: Messages API
python3 -B -m financial_metrics.agent --backend claude-code "What is BitMine's BMNP break-even price?"  # local Claude Code CLI
python3 -B -m financial_metrics.agent_eval --backend claude-code    # rewrites reports/agent-runs.jsonl and agent-eval.json
python3 -B scripts/render_agent_transcripts.py                      # writes reports/agent-transcripts.html
python3 -B scripts/export_dat_snapshot.py --dat-repo ../dat-accretion   # refreshes data/treasury/snapshot.json
```

Without `ANTHROPIC_API_KEY`, the agent defaults to the `claude-code` backend, which needs a signed-in `claude` CLI on `PATH`. The CLI default model alias is `haiku`. Both backends call a Claude model, so a run uses account credit.
