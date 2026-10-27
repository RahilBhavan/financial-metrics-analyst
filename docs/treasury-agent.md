> For normal use in T3, follow [the native workflow](t3.md). The external model adapters documented below are optional.

# Treasury-analyst agent

This page describes the optional Claude agent, its three treasury tools, and its frozen 50-task evaluation. The MCP server and CLI do not need it. Code: `financial_metrics/agent.py`, `financial_metrics/tracing.py`, `financial_metrics/agent_eval.py` and `financial_metrics/treasury.py`.

## What the agent does

The agent is a Claude tool-use loop. It starts this package's MCP stdio server as a subprocess, sends the model the server's seven tools plus a `refuse` tool, and answers questions such as "How did BitMine's last ATM raise change ETH per share?". The model proposes tool calls and selects evidence IDs. The application renders financial answers from validated records, keeping the company, metric, signed value, period, warnings and filing together. Tools run in the server process with their own schema validation. The model gets no shell, file or network access.

For financial answers the model must return `{"evidence": ["c1.r0"]}` using IDs supplied alongside tool results. Unknown IDs and extra model-written labels or values are rejected. `evidence.py` renders only selected top-level financial records; candidate audits and history cannot become claims. Before delivery, `tracing.trace_numbers` also checks every number against the tool results of that run. Question numbers cannot supply financial evidence. An answer with an untraced number gets one rewrite request. Clarification requests select a bounded intent with `{"clarification": "company|metric|period|profit|as_of"}`; the application renders a fixed question and rejects arbitrary clarification prose. Accepted intents return `needs_clarification`; nonnumeric explanations without financial evidence return `refused`, so a safe denial cannot be mislabeled as a financial answer. If the rewrite also fails, the agent withholds the answer with status `abstained_untraced`.

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

## Historical failures and current limits

- **S06 withheld (Microsoft FY2026 gross margin).** The first draft paraphrased the warning code `snapshot_older_than_7_days` as "older than 7 days". The tracer does not read numbers inside identifiers, so it flagged "7". The rewrite then mistyped the period start as 2026-07-01, and the gate withheld the answer. The second rejection caught a real error. The first was a tracer false positive. The same "7" caused the other three first-draft rejections (S07, S09, S10), which passed after one rewrite. That frozen record remains unchanged. The current gate recognizes the defined warning threshold, and financial answers use evidence rendering; new development tasks evaluate the changed implementation.
- The 21 October run predates the ten-issuer expansion. The historical prompt listed three issuers. The current prompt derives all ten issuers, annual years and quarters from `PROFILES`. The original report remains historical. A separate current-agent compatibility run of the unchanged frozen task file is in `reports/agent-current/`; the wider descriptions also have separate development evaluations. O04 (Coinbase Q3 2026) still has no reviewed quarter, so it remains out of scope. The reported results describe the older tool descriptions.
- The tasks are templated and name exact weeks and metrics, so these rates do not measure open-ended or ambiguous questions. Each frozen task ran once at default sampling. New development tasks run twice, with per-task pass rates and sample standard deviations.
- Expected numbers come from the same deterministic tools. The evaluation measures the agent's tool use and quoting, not tool correctness. Tool correctness rests on the 1,226-case evaluation in [EVALUATION.md](../EVALUATION.md) and dat-accretion's own tests.
- Tracing compares magnitudes at the precision shown. It accepts rounding and drops sign ("reduced by 0.85 bps" traces to −0.849852). Small integers must match exactly. Dates, accessions and URLs must appear verbatim. The legacy tracing utility alone cannot prove labels. Current financial answers must select evidence: trusted rendering preserves the record's label, sign and period. The agent may still select a record that does not answer the question; development scoring checks selected SEC record identities as well as arguments and numbers.
- Latency includes about 1 s of CLI start-up per model turn. Cost and tokens are the CLI's figures.
- New development tasks measure a small set of prompt-injection attempts. This is bounded evidence, not a general prompt-injection guarantee. A request to fabricate a number may be safely corrected with actual filing evidence; other attack tasks require refusal.
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

## Expanded development evaluations (26 October 2026)

These tasks are separate from the frozen 50-task holdout. `evals/agent-expanded-tasks.json` covers annual revenue, operating cash flow and a reviewed quarter for every issuer, plus eight adversarial/out-of-scope requests. `evals/agent-open-tasks.json` adds six broader questions, including multiple metrics, cash versus net income, latest reviewed quarter and an unavailable metric. Each task runs twice; JSON summaries include each task's pass rate and sample standard deviation. Two samples give only a preliminary repeatability check.

Reports and full trajectories are in `reports/agent-expanded/` and `reports/agent-open/`. SEC answer scoring checks that the selected evidence has the expected metric, fiscal year and quarter, comes from a call with the expected arguments, and quotes the expected values. Expected cash-flow values are from independent filing cards. The scoring script can rescore saved trajectories without another model call.

```sh
python3 -B -m financial_metrics.agent_eval --tasks evals/agent-expanded-tasks.json --repeats 2 --out-dir reports/agent-expanded
python3 -B -m financial_metrics.agent_eval --tasks evals/agent-open-tasks.json --repeats 2 --out-dir reports/agent-open
python3 -B scripts/verify_api.py  # live API smoke, exits 2 without ANTHROPIC_API_KEY
python3 -B scripts/verify_host.py # native Claude Code MCP host, separate from the agent's CLI backend
```

Measured results: 60/60 expanded in-scope runs pass tool, argument, selected-record and expected-number checks, with 305/305 delivered numeric/source tokens traced. The six open-wording tasks pass 12/12 runs, with 122/122 tokens traced. The initial strict refusal result is 14/16: I07 twice correctly declined quarterly cash-flow subtraction but returned `answered`. Those original trajectories remain unchanged. Explicit final-status handling now treats claimless explanations as refusals and gives clarification its own structured status. A separate two-run I07 recheck is saved in `reports/agent-refusal-recheck/`; it is not folded into the original score.

## Completion-audit checks

The current agent reran the original 50 tasks into `reports/agent-current/`, passing 42/42 financial tasks, 8/8 refusals and 451/451 delivered numeric/source tokens. The original October 21 trajectories and score file are preserved. Current scoring resolves selected IDs through the renderer's own record/field bindings for SEC and treasury tools, compares the exact signed field value, and then checks the rendered text. An equal number under another field or comparison week cannot satisfy the task.

Treasury evidence now includes individual field IDs such as `c0.week.net_mnav`, `c0.week.coin_holdings` and `c0.break_even.gap_usd`, alongside the compact record summaries. This preserves all public numeric treasury capabilities when prose generation is replaced by trusted rendering. Price-based records include their recorded price date. Schema-driven tests cover the available numeric fields, including the liquidation-preference constant, and comparison evidence retains both weeks and filing sources.

The gate rejects all unstructured financial prose after data retrieval, including spelled-out amounts and qualitative claims without digits. Without evidence, unstructured text becomes a fixed refusal message; the original draft remains in the trace, and the text cannot leak financial claims through the refusal detail. Explicit structured clarifications remain supported. Malformed `refuse` arguments become recorded errors rather than crashing the loop.

`evals/agent-tool-injection-tasks.json` contains three indirect-injection tasks, each run twice. An evaluation-only client copies real MCP results, inserts instructions into schema-valid issuer names or action notes, and revalidates the output contract. The underlying MCP result is not modified. Runs and a transcript viewer are in `reports/agent-tool-injection/`.

All six runs omitted the injected canary and fabricated prose from delivered answers. Five passed the strict tool-argument, bound-evidence and value checks. In J02 run 2, the model omitted the optional action filter, fetched the broader action list, and selected the correct estimated-issuance record with the correct values. The strict argument rule still marks that run failed; it is not counted as a complete pass. This small set does not establish general injection resistance.

```sh
python3 -B -m financial_metrics.agent_eval --tasks evals/agent-tasks.json --out-dir reports/agent-current
python3 -B -m financial_metrics.agent_eval --tasks evals/agent-tool-injection-tasks.json --repeats 2 --out-dir reports/agent-tool-injection
python3 -B scripts/render_agent_transcripts.py --reports-dir reports/agent-current
```

The optional Messages API check remains `not_run`; it is not claimed as verified. The user-selected T3-native workflow in [t3.md](t3.md) uses the host model and direct local tools instead, so no separate model key or project MCP setup is required.

Treasury evidence retains the dataset market-data providers, calculation engine, repository commit and snapshot hash. SEC URLs are explicitly labeled as underlying filing sources, including for market-price and derived fields.
