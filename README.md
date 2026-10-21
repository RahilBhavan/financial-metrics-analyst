# Financial metrics analyst

A dependency-free MCP server and CLI that returns SEC financial facts and ratios for **Apple (AAPL), Microsoft (MSFT), and NVIDIA (NVDA)** with full filing provenance, plus a Claude treasury-analyst agent that answers questions over it and [dat-accretion](https://github.com/RahilBhavan/dat-accretion)'s per-share engine.

## Results

- **161/161 evaluation cases pass:** filing values, provenance, exact ratios, question intent, tool refusals, scope behavior and real reference cases (`python3 -B -m financial_metrics.evaluate`).
- **MCP 2025-11-25 over stdio, hand-written on the standard library:** 7 tools with closed input and full nested output schemas. The official `mcp==1.30.0` Python SDK passes 28/28 interoperability checks in a separate CI job.
- **Treasury-analyst agent, frozen 50-task eval (Claude Haiku 5.5, one run):** correct tool and arguments on 42/42 in-scope tasks, 8/8 out-of-scope refusals, 0 false refusals. A deterministic gate traced all 368 numbers in delivered answers to a tool result and withheld 1 answer.
- **Refuses rather than guesses:** ambiguous prompts such as "Microsoft profit 2025" return `needs_clarification`, unsupported metrics are refused, and a newer conflicting filing blocks a stale value. The Kraft Heinz reference case flags FY2017 operating income restated from $6,773M to $6,057M.

**How it works:** facts are selected from bundled SEC XBRL snapshots by exact period, tag and filing rules, ratios are computed with exact rational arithmetic, and every number carries its filing accession; the agent's model only proposes tool calls and writes prose.

**Run the tests:** `python3 -B -m unittest discover -s tests` (114 tests, standard library only; one dat-accretion rebuild test is skipped unless `DAT_ACCRETION_REPO` is set)

It reports revenue, gross profit, operating income, net income attributable to the issuer (NetIncomeLoss), gross margin, operating margin, and revenue growth. The baseline server and CLI need no account, API key, model, package installation, or network connection; the standard-library baseline requires Python 3.9 or newer. Annual coverage is issuer-specific through FY2026, and one reviewed NVIDIA quarter demonstrates exact-quarter selection. Only the optional agent calls a model. All six planned improvements are implemented; see [IMPROVEMENT-PLAN.md](IMPROVEMENT-PLAN.md).

## Treasury-analyst agent

A Claude tool-use loop answers questions such as "How did BitMine's last ATM raise change ETH per share?" over this server, which now also serves three read-only tools built on [dat-accretion](https://github.com/RahilBhavan/dat-accretion)'s per-share engine. The model only proposes tool calls and writes prose. A deterministic check withholds any answer containing a number that no tool returned.

**Frozen 50-task eval, one run, 2026-10-21.** Model `claude-haiku-5-5`, reached through the **Claude Code CLI adapter** (`claude -p --output-format json`, built-in tools disabled, JSON-text tool protocol), not the Messages API: this machine has no API key. The tasks were committed (450af5b) before any agent run. The prompt and tracer were built on the separate `evals/dev-questions.json` and were not changed after the run.

| Metric | Result |
| --- | ---: |
| Tool selection (42 in-scope tasks) | 42 / 42 (100%) |
| Arguments: scored args match and the call returns the expected record | 42 / 42 (100%) |
| Expected numbers quoted in the delivered answer | 41 / 42 (97.6%) |
| Numbers in delivered answers traced to a tool result | 368 / 368 (100%, enforced by the gate) |
| Numbers in first drafts traced, before the gate | 379 / 383 (99.0%) |
| Answers withheld by the gate | 1 (S06) |
| Out-of-scope refusals | 8 / 8 |
| False refusals on in-scope tasks | 0 |
| Latency per task, p50 / p90 / max | 6.3 s / 9.3 s / 13.3 s |
| Tokens per task, mean (input incl. cache + output) | 10,249 |
| Cost per task, mean (CLI-reported, list price) | $0.0013; $0.066 for all 50 |
| Tool calls per task, mean | 1.2 |

By category: treasury actions 16/16, coins per share 9/9, break-even 7/7, SEC facts 9/10 on every column except tool and arguments (10/10). Full records: [reports/agent-runs.jsonl](reports/agent-runs.jsonl); scores: [reports/agent-eval.json](reports/agent-eval.json); a script-free viewer: [reports/agent-transcripts.html](reports/agent-transcripts.html).

**Known failures and limits**

- **S06 withheld (Microsoft FY2026 gross margin).** The first draft paraphrased the warning code `snapshot_older_than_7_days` as "older than 7 days". The tracer does not read numbers embedded in identifiers, so it flagged "7". The rewrite then mistyped the period start as 2026-07-01, and the gate withheld the answer. The second rejection was a real error caught; the first was a tracer false positive. The same "7" caused the other three first-draft rejections (S07, S09, S10), which passed after one rewrite. This was not fixed after the run, because that would tune against the frozen set.
- The tasks are templated and name exact weeks and metrics, so these rates do not measure open-ended or ambiguous questions. One run per task at default sampling; no repeats or variance estimate.
- Expected numbers come from the same deterministic tools, so the eval measures the agent's tool use and quoting, not tool correctness. Tool correctness rests on the existing 161-case evaluation and dat-accretion's own tests.
- Tracing compares magnitudes at the precision shown. It accepts rounding and drops sign ("reduced by 0.85 bps" traces to −0.849852). Small integers must match exactly. Dates, accessions and URLs must appear verbatim. It proves that a number came from a tool result, not that it is attached to the right label.
- Latency includes about 1 s of CLI start-up per model turn. Cost and tokens are the CLI's figures. The Messages API backend (`AnthropicMessages`, default `claude-haiku-5-5`) is unit-tested against the request and response shape but has not been run live.
- Treasury data is a frozen export of dat-accretion commit `ce3b715` (weeks 2026-05-31 to 2026-10-11). BitMine does not file per-week ATM sales, so its "ATM" answers use `est_issuance` rows, labeled estimated. dat-accretion computes in binary floating point; values are served with ten significant digits.

**Run it**

```sh
python3 -B -m financial_metrics.agent "How did BitMine's last ATM raise change ETH per share?"            # ANTHROPIC_API_KEY set: Messages API
python3 -B -m financial_metrics.agent --backend claude-code "What is BitMine's BMNP break-even price?"  # local Claude Code CLI
python3 -B -m financial_metrics.agent_eval --backend claude-code    # rewrites reports/agent-runs.jsonl and agent-eval.json
python3 -B scripts/render_agent_transcripts.py                      # reports/agent-transcripts.html
python3 -B scripts/export_dat_snapshot.py --dat-repo ../dat-accretion   # refresh data/treasury/snapshot.json
```

**Treasury tools.** `get_treasury_actions` (capital actions, most recent first, with the engine's exact change in net coins per share, basis points, USD value to common and the 8-K), `get_coins_per_share` (one stated week or two, with the change between them) and `get_break_even` (liquidation preference × net mNAV for STRC and BMNP). `scripts/export_dat_snapshot.py` runs `dat.engine.attribute` on a clean dat-accretion checkout. It refuses to write if the rebuild differs from that checkout's `attribution.csv` or `weekly.csv`. A CI job rebuilds the snapshot at the pinned commit and requires byte equality. Tests pin method.md's STRC anchor ($3.893M to common) and the memo's break-evens ($119.07 and $99.79), and they check that every served number carries an SEC filing URL and accession.

## Run it

```sh
cd financial-metrics-analyst
python3 -B -m financial_metrics demo
python3 -B -m financial_metrics demo --html reports/demo.html
python3 -B -m financial_metrics analyze --ticker MSFT --years 2026 --as-of 2026-07-29
python3 -B -m financial_metrics analyze --ticker NVDA --years 2024 2025 2026 --as-of 2026-02-25
python3 -B -m financial_metrics ask "What were Apple's net sales and operating profit in FY2023 through FY2025?"
python3 -B -m financial_metrics ask 'Microsoft profit 2025'
```

The last request asks you to choose operating income or net income; it returns `needs_clarification` and exit **3**. Submit a new question with that choice. Unsupported requests return `refused` and exit **2**. Successful and explicitly partial analyses return **0**. Use `--json` for structured output, `--details` for expanded text, or `--html PATH` for a local report with expandable evidence. HTML writing belongs to the operator CLI, not the MCP tools.

After moving the folder, change only the `cd` path. Open [reports/demo.html](reports/demo.html) for Apple, [reports/microsoft-demo.html](reports/microsoft-demo.html) for Microsoft, or [reports/nvidia-demo.html](reports/nvidia-demo.html) for NVIDIA. All three are standalone, script-free reports with tables, nearby warning references, source links, and expandable audit records.

## Expected results

Amounts below are USD millions. JSON uses full USD decimal strings.

| Apple metric | FY2023 | FY2024 | FY2025 |
| --- | ---: | ---: | ---: |
| Revenue | 383,285 | 391,035 | 416,161 |
| Operating income | 114,301 | 123,216 | 133,050 |
| Net income | 96,995 | 93,736 | 112,010 |
| Operating margin | 29.82% | 31.51% | 31.97% |
| Revenue growth | −2.80% | 2.02% | 6.43% |

Apple FY2023 contains 371 days; FY2022 and FY2024 contain 364. Both affected growth comparisons carry warnings. FY2022 revenue is a reviewed supporting input, so there are still only three visible report years. The [2025 Apple statement](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm) provides the nine main amounts; the [2024 statement](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm) provides FY2022 revenue of $394,328 million.

Microsoft uses years ending June 30. Its FY2023–2025 revenue is $211,915 million, $245,122 million, and $281,724 million. The independently checked [2025 annual report](https://www.microsoft.com/investor/reports/ar25/index.html) provides those years; the [2024 report](https://www.microsoft.com/investor/reports/ar24/index.html) provides FY2022 revenue of $198,270 million. FY2024 has 366 days, so the adjacent growth comparisons carry duration warnings.

**Microsoft FY2026 is reviewed** from its FY2026 Form 10-K (accession 0001193125-26-323660). Revenue was $331.839 billion, gross profit $225.465 billion, operating income $155.237 billion, and net income $133.749 billion. NVIDIA FY2024–FY2026 and Q2 FY2027 are also reviewed from SEC filings. See [the source research](docs/issuer-expansion-research.md) and [NVIDIA ground truth](data/nvda/ground-truth.json).

## Selection and accounting rules

- Match the exact reviewed start/end dates, USD, approved US-GAAP tags, annual filing forms, and `fp=FY`. The filing's `fy` is stored separately as `reported_fy`; a comparative fact can describe an earlier year.
- Verify accession, filing date, report date, issuer, and safe document name against submissions metadata. Only the available submissions history is indexed.
- Select the latest eligible filing on or before the inclusive `as_of` date. A rejected same-end annual candidate at the same or a newer filing date blocks an older value. Unknown candidate dates also block. The result identifies the blockers instead of silently returning a stale number.
- The blocker test treats unknown durations or durations of at least 300 days as potentially annual. Known shorter quarter/YTD facts are rejected but do not block an otherwise valid annual fact. This is a reviewed-period policy, not a general detector for every malformed SEC record.
- Collapse identical duplicates. Conflicting eligible values on a single filing date produce ambiguity. Preserve original values and filing history; a changed value is a revision candidate, not proof of a formal restatement. Quarterly selection applies the same conflict and blocker rules to quarter-length 10-Q and 10-Q/A candidates.
- Ratios use one filing accession. Growth may use the latest common filing only when both comparative values equal the latest individually selected values. This choice is disclosed. A changed latest value prevents substitution.
- Gross margin = gross profit / revenue × 100. Operating margin = operating income / revenue × 100. Growth = (current revenue − prior revenue) / prior revenue × 100. Revenue denominators must be positive. Missing inputs stay unavailable; they never become zero.
- Keep exact input decimals and exact rational percentages. Decimal renderings use 34 significant digits; display percentages use two decimal places and `ROUND_HALF_EVEN`.

`as_of` cannot exceed the snapshot date. Filing-date filtering cannot reconstruct intraday availability or undo subsequent corrections to historical API records. A snapshot older than seven days generates a warning; set `FINANCIAL_METRICS_TODAY=YYYY-MM-DD` to fix that clock. Refreshing does not automatically review new years or quarters; policy changes still require source checks.

## Real reference cases

The bundled Kraft Heinz case exercises the same selector but is **not an interactive issuer**. Its [restatement note](https://www.sec.gov/Archives/edgar/data/1637459/000163745919000049/R9.htm) reports FY2017 operating income of $6,773 million originally and $6,057 million after restatement and recasting. The $716 million difference includes an $80 million error-correction effect and a $636 million accounting-presentation change. The generic selector flags the changed value; the separate source card explains it.

The named standard revenue tag is genuinely absent from that company's downloaded API taxonomy, even though its filing reports net sales. This is missing tag coverage, not zero or absent business revenue. KHC also reports noncontrolling interests, so its attributable net income differs from consolidated net income; that needs its own statement review, which is another reason not to expose it as a supported issuer. See [the reference card](data/reference-cases/khc/ground-truth.json).

## Questions and optional model proposals

`ask` accepts issuer names or tickers, common metric synonyms, year lists or ranges, and an optional explicit filing cutoff. Missing company, years, metrics, or ambiguous profit/margin/change prompts produce clarification. Unsupported extra requests are not silently discarded. This remains a bounded parser, not unrestricted natural-language understanding.

An optional host can propose **arguments only**, validated by the same deterministic tools. To exercise that boundary without installing or calling a model:

```sh
python3 -B -m financial_metrics proposal <<'JSON'
{"ticker":"MSFT","fiscal_years":[2025],"metrics":["revenue","operating_margin"],"as_of":"2025-07-30"}
JSON
```

Proposals cannot contain financial answers, URLs, filenames, or executable actions. Validation checks allowed arguments and scope; it does not prove that a model faithfully interpreted the original question. There is no model in the baseline. The optional agent above measures model behavior and token costs on its frozen tasks; injection resistance has not been measured.

## MCP hosting and contracts

The server implements MCP **2025-11-25** over newline-delimited JSON-RPC stdio: initialization, initialized notification, ping, tool discovery, and tool calls. It exposes `resolve_company`, `get_annual_facts`, `get_quarterly_facts`, and `calculate_metrics`, plus the three treasury tools above. Quarterly coverage is intentionally limited to NVIDIA Q2 FY2027 until more periods are reviewed. It offers no HTTP transport or arbitrary network, file, or execution capability.

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

Adjust executable and project paths when moving computers. The launcher works from an unrelated directory. The seven tools publish and enforce closed input and **full nested output schemas**, including provenance, history, warnings, ratios, context, unavailable rows, and refusals. Invalid generated output becomes an `invalid_tool_output` refusal. Schemas validate structure; separate source and arithmetic checks validate financial meaning.

```sh
python3 -B -m financial_metrics smoke
python3 -B -m unittest discover -s tests -v
python3 -B -m financial_metrics.evaluate
```

`evaluate` writes each case and the AAPL, MSFT, and NVDA demos into `reports/`, and prints unit-test counts and timing. `python3 scripts/regenerate_reports.py` rewrites every committed report against a fixed clock (`--today YYYY-MM-DD`, default the newest snapshot capture date); CI fails if the committed reports drift. The optional independent SDK check needs Python 3.10 or newer and a separate environment:

```sh
python3.11 -m venv .venv-sdk
.venv-sdk/bin/python -m pip install -r requirements-sdk-test.txt
.venv-sdk/bin/python -B scripts/verify_sdk.py
```

It uses the official `mcp==1.30.0` client and an independent JSON Schema validator. This is interoperability evidence, not full protocol certification or a test in every desktop host.

## Optional SEC refresh

The separate operator command downloads **AAPL, MSFT, or NVDA** from issuer-specific fixed SEC endpoints. It refuses redirects and overwrites, bounds response sizes, uses timeouts and retries, and throttles each process. Use your own real contact information and follow the [SEC developer guidance](https://www.sec.gov/about/developer-resources).

```sh
python3 -B -m financial_metrics fetch --ticker NVDA --output local-snapshots/new-capture --user-agent 'YourProject your-real-contact@example.com'
python3 -B -m financial_metrics demo --data-dir local-snapshots/new-capture
```

A custom data directory loads only its own reviewed issuer. The bundled default loads all three. The refresher was tested with controlled HTTP responses; live refresh using a user's contact was not run. The supplied raw snapshots were downloaded with curl. Their manifests record source URLs, sizes, hashes, and capture-day packaging timestamps. Hashes detect changes relative to a trusted manifest; they do not authenticate an untrusted manifest.

## Read next

[WALKTHROUGH.md](WALKTHROUGH.md) traces one answer through the code. [EVALUATION.md](EVALUATION.md) records measured results and limitations. Independent source transcriptions live in `data/ground-truth.json`, `data/msft/ground-truth.json`, `data/nvda/ground-truth.json`, and `data/reference-cases/khc/ground-truth.json`. Adversarial synthetic modifications exist only in tests.
