# Evaluation record

Verified on 21 September 2026 with Python 3.9.6 for the baseline and Python 3.11.15 with `mcp==1.30.0` for independent client checks.

**72 test methods passed, with no failures, errors, or skips. The separately enumerated source/intent evaluation passed 82/82 cases. The official SDK check passed 18/18 checks.** Each public issuer produces 15 numeric results across the three reviewed years.

| Evaluation group | Passed / total |
| --- | ---: |
| exact ratios | 12 / 12 |
| filing values | 18 / 18 |
| provenance | 18 / 18 |
| question intent | 14 / 14 |
| real reference cases | 3 / 3 |
| scope behavior | 3 / 3 |
| supporting values | 2 / 2 |
| tool refusals | 12 / 12 |

Every evaluation case includes expected and actual values in [reports/evaluation.json](reports/evaluation.json). Test methods can contain multiple subtests; these are not added to the method count. The unit suite and enumerated evaluation overlap in coverage, so their counts should not be combined into a single accuracy score.

## Evidence for the six improvements

1. **Invalid newer facts block fallback.** Synthetic mutations cover invalid amounts, wrong currency, shifted or absent start dates, filing metadata disagreement, misleading future raw dates, invalid annual flags, and unsafe source documents. A valid older fact does not escape these blockers. Separate checks preserve filing-cutoff exclusions and legitimate short-period records.
2. **FY2023 growth has a reviewed baseline.** Apple FY2022 revenue is independently transcribed from its 2024 filing. Exact rational arithmetic verifies −2.80% growth. The comparison uses a common filing whose values match the latest disclosures; a synthetic changed latest value prevents substitution. FY2022 remains unavailable as a public report year.
3. **Real source coverage extends beyond Apple.** Microsoft's nine base amounts, six ratios, June reporting dates, and supporting revenue pass against separate annual-report transcriptions. Kraft Heinz's actual FY2017 revision and absent named revenue tag are tested on unmodified API snapshots. KHC is a reference case, not a supported interactive issuer.
4. **Reports have compact tables and expandable evidence.** Checks cover full-dollar versus million-dollar presentation, negative growth, warning references, formula detail, source links, HTML escaping, and script-free output. The CLI creates a standalone HTML report in a temporary directory during testing. No screenshot-based visual or cross-browser audit was performed.
5. **Questions accept useful variants and clarify ambiguity.** The evaluation contains accepted paraphrases, clarification cases, and refused requests. Additional tests cover ambiguous revenue change and optional JSON proposals. Proposal validation bounds permitted arguments; no model was called or evaluated.
6. **Output contracts validate nested records.** The server checks facts, original/history records, ratio operands, exact fractions, precision, warnings, context, and refusals. Missing accessions, floating-point amounts, impossible dates, unknown nested fields, zero denominators, missing warning arrays, and broken history fail closed. The independent JSON Schema validator separately rejects six malformed nested outputs.

The existing tests still cover exact decimal behavior, arithmetic signs and denominator rules, original provenance, as-of boundaries, duplicate/conflicting candidates, stale snapshots, hostile ignored descriptions, manifest integrity, transport framing and lifecycle, bounded refresh failure handling, and launch from an unrelated directory. A real subprocess answers with Python audit hooks denying network operations and file writes.

## Independent MCP check

The official Python SDK negotiates MCP 2025-11-25, discovers exactly three tools, validates their input and output schema documents, calls every tool, checks both issuers, exercises a refusal, compares text with structured content, and pings. `jsonschema` uses its date format checker for the independent nested validations.

The 18 checks are recorded individually in [reports/sdk-smoke.json](reports/sdk-smoke.json). This establishes the tested stdio interaction with a second client implementation. It is not certification of every MCP feature or evidence that each desktop host has been configured.

## Measured timing

Ten warm sequential calls over one running MCP subprocess had a **5.645 ms median** and **5.843 ms maximum**. The report includes all samples. These timings include selection, calculations, nested validation, and local transport; they exclude startup, acquisition, and model inference. No production latency or throughput claim is made.

## Reproduction and exit statuses

Run commands from the project directory. Exact executable paths, arguments, stdin where relevant, output files, stderr, and exit statuses are captured in [reports/verification.json](reports/verification.json).

| Command | Exit | Result |
| --- | ---: | --- |
| `python3 -B -m financial_metrics.evaluate` | 0 | 72 tests; 82 evaluation cases; both issuer reports and timing samples |
| `python3 -B -m financial_metrics smoke` | 0 | Nine facts, six numeric ratios, expected refusal, clean subprocess exit |
| `python3 -B -m financial_metrics demo --html reports/demo.html` | 0 | Three-year Apple table and expandable local report |
| `python3 -B -m financial_metrics ask "What were Apple's net sales and operating profit in FY2023 through FY2025?"` | 0 | Six requested facts through MCP |
| `python3 -B -m financial_metrics ask 'Apple profit 2025' --json` | 3 | Expected clarification between operating and net income |
| `python3 -B -m financial_metrics analyze --metrics ebitda` | 2 | Expected refusal |
| `python3 -B -m financial_metrics analyze --years 2023 --metrics revenue --as-of 2024-10-31 --json` | 0 | Original Apple FY2023 accession selected |
| `python3 -B -m financial_metrics analyze --ticker MSFT` | 0 | Reviewed results plus newer-annual-scope warning |
| `python3 -B -m financial_metrics proposal --json` with recorded JSON stdin | 0 | Bounded Microsoft request; tool-computed values |
| Separate SDK environment: `python -B scripts/verify_sdk.py` | 0 | 18/18 independent checks |
| `python3 -m compileall -q financial_metrics tests scripts server_stdio.py` with workspace cache | 0 | Syntax compilation passed |

A regression test initially constructed a conflicting quarterly record instead of an annual one. Correcting the fixture to the intended annual interval made the ambiguity check meaningful; the final suite passed. Earlier runs from the parent folder and with an unwritable default bytecode cache were corrected by using the project working directory and an explicit workspace cache. No application defect from these attempts remains unresolved.

## Source evidence

Raw `companyfacts.json` and `submissions.json` files are unmodified SEC response bodies. Each issuer/reference directory has a manifest containing URLs, byte counts, SHA-256 hashes, and a capture-day packaging timestamp. Source cards are independent manual transcriptions, not generated from the extraction being tested.

- Apple main values: [2025 10-K, statement page 29](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm). Supporting FY2022 revenue: [2024 10-K, statement page 29](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm).
- Microsoft main values: [2025 annual report, Income Statements](https://www.microsoft.com/investor/reports/ar25/index.html). Supporting FY2022 revenue: [2024 annual report](https://www.microsoft.com/investor/reports/ar24/index.html). The main provenance evaluation uses cutoff July 30, 2025 to match the independently reviewed filing. Latest API comparatives for reviewed years may use a later accession.
- Kraft Heinz: [restatement and recast bridge](https://www.sec.gov/Archives/edgar/data/1637459/000163745919000049/R9.htm). Original FY2017 operating income of $6.773 billion becomes $6.057 billion after an $80 million restatement effect and a $636 million presentation change. The filing also reports net sales despite the missing named standard revenue tag in companyfacts.

API downloads succeeded. Some direct archive HTML requests returned HTTP 403; public web readers and issuer annual reports supplied the independent statement checks. Microsoft FY2026 could not be independently checked and remains unreviewed. Complete filing HTML is not bundled. Offline checks reproduce comparisons to the source cards; independently auditing those transcriptions requires opening the cited source documents.

## Remaining limits

- Two reviewed companies, three report years, and supporting FY2022 revenue. This is not a general issuer, taxonomy, or accounting-basis resolver. KHC's net-income attribution illustrates why additional issuers need separate review.
- Historical filing-date filtering does not recreate past API contents or intraday availability. Changed values are flagged; formal restatement classification requires source evidence.
- Quarters, forecasts, EBITDA, cash flow, valuation, IFRS, currency conversion, and unreviewed fiscal years remain unsupported.
- The optional refresher supports Apple only and uses controlled HTTP test doubles for success, retries, timeouts, redirects, size limits, wrong identity, and partial failures. No live refresh using the user's contact information or source-availability SLA was measured.
- Full nested schemas constrain structure. They do not by themselves establish correct source transcription, arithmetic, or semantic consistency; those have separate tests.
- No paid or local language model was run. Natural-language interpretation remains bounded, and model-generated proposal fidelity has not been evaluated.
- Snapshot integrity assumes a trusted local manifest. There is no remote service, authentication deployment, publication, or external messaging.

The plan's local implementation and verification gates are complete. Archive integrity and extracted-copy execution are recorded separately in `reports/package-verification.json` when packaging completes.
