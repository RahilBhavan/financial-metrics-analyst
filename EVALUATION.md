# Evaluation record

This file records the 1,226-case source and intent evaluation (947 before cash-flow coverage), the SDK check and their reproduction commands. The agent's 50-task evaluation is in [docs/treasury-agent.md](docs/treasury-agent.md).

**T3-native completion, 26 October 2026.** Six integration questions passed through a T3-hosted Codex model using direct local calls, without a model API key or project MCP setup (`reports/t3-smoke.json`). The requests are saved in `evals/t3-requests.json` and replayed in CI without a model call. Direct-path tests deny network/subprocess events and remove model keys. The native evidence command re-executes calls rather than accepting model-supplied results or prose.

**Update, 26 October 2026 (cash flow and agent completion).** 200 unit tests run (199 pass, one treasury-rebuild skip). The deterministic evaluation passes 1,226/1,226: the prior 947 cases plus 93 independently transcribed annual cash-flow values and 186 provenance/history checks. The official SDK passes 37/37 checks, including cash-flow values/signs and refusal of quarterly cash flow. Native Claude Code MCP hosting passes 4/4 checks (`reports/host-smoke.json`). The live SEC refresh passes all 50 issuer/quarter checks at the bundled filing cutoffs (`reports/live-refresh-ten-issuers.json`). Model development evaluations and their two repeats are documented in [docs/treasury-agent.md](docs/treasury-agent.md); the frozen holdout stays unchanged. The optional live Messages API smoke is explicitly `not_run` without an API key (`reports/api-smoke.json`).

**Completion audit (same date).** Current-agent compatibility: 42/42 financial tasks and 8/8 refusals on a fresh run of the original unchanged task file (`reports/agent-current/`). The evidence renderer exposes all public numeric treasury fields, and regression tests reject prose without digits, incorrect field/week selections, sign mismatches and malformed refusal arguments. Six schema-valid tool-text injection runs omitted the injected output; five passed strict task checks, while one correct answer omitted an expected optional action filter (`reports/agent-tool-injection/`). See the agent documentation for the exact limits. The optional Messages API adapter has not been exercised live. The user-selected T3-native route replaces that requirement; see docs/t3.md and reports/t3-smoke.json.

Annual cash-flow source cards (`data/*/cash-flow-ground-truth.json`, plus the root Apple card) come from the visible cash-flow statements in each cited filing, independently of companyfacts. `scripts/review_cash_flows.py` checks year headers, signed values and continuation tables and never opens companyfacts. The server uses the same exact-date, filing-cutoff, revision and blocker rules as annual income facts. Quarterly cash flow is refused rather than inferred from year-to-date totals.

**Historical update, 26 October 2026 (multi-model review fixes).** 168 test methods run (167 pass, one skipped as before) on Python 3.14.7 and 3.9. The source and intent evaluation passes 947/947 and the official SDK check passes 33/33. A three-model review (Claude Opus 5.5, GPT 6.1 Sol, Gemini 4 Argon) found no wrong bundled numbers. It did find failures that a refresh or ordinary use would trigger, now fixed with regression tests in `tests/test_regressions.py`:

- Annual and quarterly selection share one implementation. Quarters gain the filed-before-period-end check, parsed report dates, and a 70–119-day blocker window, so one-month stubs do not block. Annual years ending in the first week of January may carry the prior `fy`. A quarterly metric whose tag is absent from the issuer's taxonomy now reports `standard_tag_absent`, as annual results do. The 20 affected "not reported" expectations changed accordingly.
- Snapshots can include SEC's paged submission files, and `fetch` downloads them. On the real KHC case, a missing older filing used to make the restated value the silent "original"; it now raises `history_incomplete`.
- The live refresh check compares only the financial answer, covers every issuer and reviewed quarter, and returns with the restored workflow.
- `analyze` defaults to the data directory's issuer and its reviewed years, adds `--quarter`, and surfaces server stderr. `smoke --data-dir` works for every issuer. The `ask` parser handles `between X and Y`, en dashes, `thru`, `FY24`, `vs`, plurals, gross margin, gross-profit clarification, and change questions; question intent grew from 32 to 78 cases.
- MCP: null `params` are accepted, errors with an unknown id omit `id`, client responses get no reply, non-object arguments return -32602, refusal codes name the failed field, `date-time` requires RFC 3339, and quarterly outputs reject annual forms.
- Scope (tickers, years, quarters, tags) derives from `PROFILES`, with a consistency test. Issuers in subdirectories load on first use. Ratio operands omit the candidate audit, and margins use the same common-filing rule as growth. The Microsoft demo shows FY2023–FY2026.

**Update, 25 October 2026 (ten issuers, four quarters each).** Seven issuers (Coinbase, Strategy, Robinhood, Block, PayPal, Visa, Tesla) joined Apple, Microsoft and NVIDIA, and every issuer now has its four latest reviewed 10-Q quarters (40 in all). 134 test methods run (133 pass, one skipped as before) on Python 3.9, 3.11, 3.13 and 3.14.7. The source and intent evaluation passes 885/885. The official SDK check passes 33/33, five calls more than before: Visa, an amended Robinhood 10-K, a Tesla quarter, a Coinbase quarter with an unreported metric, and a refused quarter. The table below shows the groups. The paragraphs after it describe the 21 October and 23 September records and are kept as history.

| Evaluation group (26 October 2026) | Passed / total | What it checks |
| --- | ---: | --- |
| annual cash-flow values | 93 / 93 | Signed operating, investing and financing cash flow against independent filing cards |
| cash-flow provenance | 186 / 186 | Periods, CIK, unit, standard tags and reviewed filing/value in history |
| filing values | 300 / 300 | Every annual and quarterly value against the card transcribed from the filing |
| provenance | 250 / 250 | Accession, filing URL, dates, tag, unit, filing date and form per value |
| exact ratios | 78 / 78 | Gross margin, operating margin and growth against exact rational arithmetic |
| point in time | 96 / 96 | An earlier cutoff returns the older filing's values; a quarter is invisible the day before its 10-Q |
| stale values | 25 / 25 | The older filing stays the original; revision flags match the filing text; a newer relabelled PayPal record blocks a later cutoff |
| question answers | 18 / 18 | Natural-language questions on the new issuers return the card's values, or "not reported" |
| question intent | 78 / 78 | Accepted paraphrases, clarifications (profit, margin, change, missing company, year or metric) and refusals |
| tool refusals | 42 / 42 | Unreviewed year, quarter, ticker, metric, future cutoff and bad quarter labels, for each added issuer |
| scope behavior | 47 / 47 | Duration warnings, and metrics an issuer does not report staying unavailable instead of zero |
| supporting values | 10 / 10 | The prior-year revenue that growth needs, with its filing |
| real reference cases | 3 / 3 | Kraft Heinz restatement and missing revenue tag |

Expected values for the seven added issuers, and for every issuer's quarters, come from `scripts/review_filings.py`. It reads the visible income statement in each cited filing document and never opens `companyfacts.json`. The first full run agreed with the server on every value. That includes NVIDIA's Q2 FY2027 quarter, which an earlier hand transcription had already recorded. Two disagreements surfaced and were fixed in the script: Robinhood's 2026 quarters first used consolidated net income instead of net income attributable to Robinhood, and a negative amount split across two cells in one Strategy 10-Q. The SEC API holds no facts for the PayPal and Visa 10-Qs filed in July 2026 (re-fetched on 25 October), so those two quarters are not reviewed and the next-oldest are used.

The expansion also changed one rule. A later 10-Q repeats each quarter as its prior-year comparative. The quarter selector used to treat that record as a metadata mismatch, which blocked any quarter older than a year at the latest cutoff. It now accepts the record when its fiscal year matches its own filing, so the comparative becomes a revision candidate. Identical values remain unflagged. All 40 reviewed quarters returned their card values, and the values in a later 10-Q's comparative columns matched the original 10-Q everywhere they exist.

**Update, 21 October 2026 (branch `treasury-agent`).** 115 test methods pass on Python 3.14.7 and 3.9 (one, the dat-accretion snapshot rebuild, is skipped unless `DAT_ACCRETION_REPO` points at a checkout; it passed locally and runs in its own CI job). The source and intent evaluation still passes 161/161. The official SDK check now passes 28/28: it discovers seven tools and calls the three treasury tools, including one refusal. The agent's frozen 50-task trajectory eval is reported in [docs/treasury-agent.md](docs/treasury-agent.md) and in `reports/agent-eval.json`. The record below is the 23 September baseline.

Verified on 23 September 2026 with Python 3.9.6 for the baseline and Python 3.11.15 with `mcp==1.30.0` and `jsonschema==4.26.0` for independent client checks.

**Superseded baseline (23 September): 77 test methods passed, with no failures, errors, or skips; the 161-case evaluation passed 161/161; the official SDK check passed 21/21 checks. These historical figures are superseded by the latest update above.** Annual results now include gross profit and gross margin; NVIDIA Q2 FY2027 is the reviewed quarterly case.

| Evaluation group | Passed / total |
| --- | ---: |
| exact ratios | 30 / 30 |
| filing values | 44 / 44 |
| provenance | 44 / 44 |
| question intent | 14 / 14 |
| real reference cases | 3 / 3 |
| scope behavior | 11 / 11 |
| supporting values | 3 / 3 |
| tool refusals | 12 / 12 |

Every evaluation case includes expected and actual values in [reports/evaluation.json](reports/evaluation.json). Test methods can contain multiple subtests; these are not added to the method count. The unit suite and enumerated evaluation overlap in coverage, so their counts should not be combined into a single accuracy score.

## Evidence for the six improvements

1. **Invalid newer facts block fallback.** Synthetic mutations cover invalid amounts, wrong currency, shifted or absent start dates, filing metadata disagreement, misleading future raw dates, invalid annual flags, and unsafe source documents. A valid older fact does not escape these blockers. Separate checks preserve filing-cutoff exclusions and legitimate short-period records.
2. **FY2023 growth has a reviewed baseline.** Apple FY2022 revenue is independently transcribed from its 2024 filing. Exact rational arithmetic verifies −2.80% growth. The comparison uses a common filing whose values match the latest disclosures; a synthetic changed latest value prevents substitution. FY2022 remains unavailable as a public report year.
3. **Real source coverage extends beyond Apple.** Microsoft's twelve FY2023-FY2025 base amounts, nine ratios, June reporting dates, and supporting revenue pass against separate annual-report transcriptions. Microsoft FY2026 and NVIDIA FY2024-FY2026 plus Q2 FY2027 pass against their own source cards. Kraft Heinz's actual FY2017 revision and absent named revenue tag are tested on unmodified API snapshots. KHC is a reference case, not a supported interactive issuer.
4. **Reports have compact tables and expandable evidence.** Checks cover full-dollar versus million-dollar presentation, negative growth, warning references, formula detail, source links, HTML escaping, and script-free output. The CLI creates a standalone HTML report in a temporary directory during testing. No screenshot-based visual or cross-browser audit was performed.
5. **Questions accept useful variants and clarify ambiguity.** The evaluation contains accepted paraphrases, clarification cases, and refused requests. Additional tests cover ambiguous revenue change and optional JSON proposals. Proposal validation bounds permitted arguments; no model was called or evaluated.
6. **Output contracts validate nested records.** The server checks facts, original/history records, ratio operands, exact fractions, precision, warnings, context, and refusals. Missing accessions, floating-point amounts, impossible dates, unknown nested fields, zero denominators, missing warning arrays, and broken history fail closed. The independent JSON Schema validator separately rejects six malformed nested outputs.

The existing tests still cover exact decimal behavior, arithmetic signs and denominator rules, original provenance, as-of boundaries, duplicate/conflicting candidates, stale snapshots, hostile ignored descriptions, manifest integrity, transport framing and lifecycle, bounded refresh failure handling, and launch from an unrelated directory. A real subprocess answers with Python audit hooks denying network operations and file writes.

## Independent MCP check

On 23 September, before the treasury tools existed, the official Python SDK negotiated MCP 2025-11-25, discovered exactly four tools, validated their input and output schema documents, called every tool, checked all three issuers, exercised a refusal, compared text with structured content, and pinged. `jsonschema` uses its date format checker for the independent nested validations.

The current 37 checks, which cover all seven tools, are recorded individually in [reports/sdk-smoke.json](reports/sdk-smoke.json). This establishes the tested stdio interaction with a second client implementation. It is not certification of every MCP feature or evidence that each desktop host has been configured.

## Measured timing

Ten warm sequential calls over one running MCP subprocess had a **7.532 ms median** and **7.876 ms maximum** in the 23 September `evaluate` run. A run on 21 October 2026 with Python 3.14.7 measured a 4.405 ms median. `evaluate` prints these figures; they stay out of the committed report because they change on every run. These timings include selection, calculations, nested validation, and local transport; they exclude startup, acquisition, and model inference. No production latency or throughput claim is made.

## Reproduction and exit statuses

Run commands from the project directory. `python3 scripts/regenerate_reports.py` reruns the commands below, checks their exit statuses, and rewrites each report against a fixed clock. CI fails if the committed reports differ from a fresh run.

| Command | Exit | Result |
| --- | ---: | --- |
| `python3 -B -m financial_metrics.evaluate` | 0 | Baseline 77 tests, superseded by 200 (one skipped); 1,226 evaluation cases; AAPL, MSFT and NVDA reports; printed timing |
| `python3 -B -m financial_metrics smoke` | 0 | Nine facts, six numeric ratios, expected refusal, clean subprocess exit |
| `python3 -B -m financial_metrics demo --html /tmp/apple-report.html` | 0 | Three-year Apple table and expandable local report |
| `python3 -B -m financial_metrics ask "What were Apple's net sales and operating profit in FY2023 through FY2025?"` | 0 | Six requested facts through MCP |
| `python3 -B -m financial_metrics ask 'Apple profit 2025' --json` | 3 | Expected clarification among gross profit, operating income and net income |
| `python3 -B -m financial_metrics analyze --metrics ebitda` | 2 | Expected refusal |
| `python3 -B -m financial_metrics analyze --years 2023 --metrics revenue --as-of 2024-10-31 --json` | 0 | Original Apple FY2023 accession selected |
| `python3 -B -m financial_metrics analyze --ticker MSFT --years 2023 2024 2025 2026` | 0 | Four reviewed years, FY2023-FY2026, with no scope warning |
| `python3 -B -m financial_metrics proposal --json` with recorded JSON stdin | 0 | Bounded Microsoft request; tool-computed values |
| Separate SDK environment: `python -B scripts/verify_sdk.py` | 0 | Baseline 21/21, superseded by 37/37 independent checks |
| `python3 -m compileall -q financial_metrics tests scripts server_stdio.py` with workspace cache | 0 | Syntax compilation passed |

A regression test initially constructed a conflicting quarterly record instead of an annual one. Correcting the fixture to the intended annual interval made the ambiguity check meaningful; the final suite passed. Earlier runs from the parent folder and with an unwritable default bytecode cache were corrected by using the project working directory and an explicit workspace cache. No application defect from these attempts remains unresolved.

## Source evidence

Added on 25 October 2026. Each card in `data/<issuer>/ground-truth.json` names the filing accession and document for every value. Annual values come from the FY2025 Form 10-K income statement (three years); the older FY2024 10-K supplies FY2022 revenue and the point-in-time values.

| Issuer | Annual filing | Notes |
| --- | --- | --- |
| Coinbase (COIN) | FY2025 10-K, 0001679788-26-000015 | No gross profit line |
| Strategy (MSTR) | FY2025 10-K, 0001050446-26-000020 | Net income is the line before preferred dividends; revenue tag is `RevenueFromContractWithCustomerExcludingAssessedTax` |
| Robinhood (HOOD) | FY2025 10-K 0001783879-26-000023, amended by 10-K/A 0001783879-26-000029 | No gross profit or operating income line. The 10-K/A fixes formatting only, so the server selects it and keeps the 10-K as the FY2025 original |
| Block (XYZ) | FY2025 10-K, 0001628280-26-012254 | Net income attributable to common stockholders |
| PayPal (PYPL) | FY2025 10-K, 0001633917-26-000024 | No gross profit line |
| Visa (V) | FY2025 10-K, 0001403161-25-000089 (fiscal year ends 30 September) | No gross profit line |
| Tesla (TSLA) | FY2025 10-K, 0001628280-26-003952 | Net income attributable to common stockholders |

Raw `companyfacts.json` and `submissions.json` files are unmodified SEC response bodies. Each issuer/reference directory has a manifest containing URLs, byte counts, SHA-256 hashes, and a capture-day packaging timestamp. Source cards are independent manual transcriptions, not generated from the extraction being tested.

- Apple main values: [2025 10-K, statement page 29](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm). Supporting FY2022 revenue: [2024 10-K, statement page 29](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm).
- Microsoft main values: [2025 annual report, Income Statements](https://www.microsoft.com/investor/reports/ar25/index.html). Supporting FY2022 revenue: [2024 annual report](https://www.microsoft.com/investor/reports/ar24/index.html). The main provenance evaluation uses cutoff July 30, 2025 to match the independently reviewed filing. Latest API comparatives for reviewed years may use a later accession.
- Microsoft FY2026: [FY2026 Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm), accession 0001193125-26-323660. NVIDIA: [FY2026 Form 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm), FY2023 supporting revenue from the [FY2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm), and the [Q2 FY2027 Form 10-Q](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm).
- Kraft Heinz: [restatement and recast bridge](https://www.sec.gov/Archives/edgar/data/1637459/000163745919000049/R9.htm). Original FY2017 operating income of $6.773 billion becomes $6.057 billion after an $80 million restatement effect and a $636 million presentation change. The filing also reports net sales despite the missing named standard revenue tag in companyfacts.

API downloads succeeded. At capture time some direct archive HTML requests returned HTTP 403, so public web readers and issuer annual reports supplied the independent statement checks; the SEC archive now returns HTTP 200 when requested with a User-Agent header. Microsoft FY2026 is reviewed: its revenue, gross profit, operating income, and net income match a fresh SEC companyfacts fetch made on 2026-09-23 for accession 0001193125-26-323660. Complete filing HTML is not bundled. Offline checks reproduce comparisons to the source cards; independently auditing those transcriptions requires opening the cited source documents.

## Remaining limits

- Ten reviewed companies with issuer-specific annual coverage and four reviewed 10-Q quarters each. This remains a bounded issuer and accounting policy, not a general taxonomy resolver. KHC's net-income attribution illustrates why additional issuers need separate review.
- Historical filing-date filtering does not recreate past API contents or intraday availability. Changed values are flagged; formal restatement classification requires source evidence.
- Quarters beyond the four reviewed per issuer (including the fiscal fourth quarter, which has no 10-Q), forecasts, EBITDA, quarterly cash flow, capital expenditures, free cash flow, valuation, IFRS, currency conversion, and unreviewed fiscal years remain unsupported.
- The optional refresher supports all ten tickers and uses controlled HTTP test doubles for success, retries, timeouts, redirects, size limits, wrong identity, and partial failures. The 26 October live refresh passed all ten issuers and forty quarters. No source-availability SLA is measured.
- Full nested schemas constrain structure. They do not by themselves establish correct source transcription, arithmetic, or semantic consistency; those have separate tests.
- The baseline evaluation calls no model. The optional treasury-analyst agent, added in October, is evaluated separately. Natural-language interpretation remains bounded. The separate model evaluations check tool arguments and selected evidence, with per-task repeat statistics.
- Snapshot integrity assumes a trusted local manifest. There is no remote service, authentication deployment, publication, or external messaging.

The plan's local implementation and verification gates are complete.
