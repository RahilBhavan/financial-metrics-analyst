# Financial metrics analyst

An offline analyst for **Apple (AAPL), Microsoft (MSFT), and NVIDIA (NVDA)**. It reports revenue, gross profit, operating income, consolidated net income, gross margin, operating margin, and revenue growth through a real MCP stdio subprocess. Annual coverage is issuer-specific through FY2026; one reviewed NVIDIA quarter demonstrates exact-quarter selection. Every number retains its source filing and exact inputs.

All six improvements are implemented; see [IMPROVEMENT-PLAN.md](IMPROVEMENT-PLAN.md). The standard-library baseline requires Python 3.9 or newer. No account, API key, model, package installation, or network connection is needed.

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

After moving the folder, change only the `cd` path. Open [reports/demo.html](reports/demo.html) for Apple or [reports/microsoft-demo.html](reports/microsoft-demo.html) for Microsoft. Both are standalone, script-free reports with tables, nearby warning references, source links, and expandable audit records.

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

**Microsoft FY2026 is reviewed.** Revenue was $331.839 billion, gross profit $225.465 billion, operating income $155.237 billion, and net income $133.749 billion. NVIDIA FY2024–FY2026 and Q2 FY2027 are also reviewed from SEC filings. See [the source research](docs/issuer-expansion-research.md) and [NVIDIA ground truth](data/nvda/ground-truth.json).

## Selection and accounting rules

- Match the exact reviewed start/end dates, USD, approved US-GAAP tags, annual filing forms, and `fp=FY`. The filing's `fy` is stored separately as `reported_fy`; a comparative fact can describe an earlier year.
- Verify accession, filing date, report date, issuer, and safe document name against submissions metadata. Only the available submissions history is indexed.
- Select the latest eligible filing on or before the inclusive `as_of` date. A rejected same-end annual candidate at the same or a newer filing date blocks an older value. Unknown candidate dates also block. The result identifies the blockers instead of silently returning a stale number.
- The blocker test treats unknown durations or durations of at least 300 days as potentially annual. Known shorter quarter/YTD facts are rejected but do not block an otherwise valid annual fact. This is a reviewed-period policy, not a general detector for every malformed SEC record.
- Collapse identical duplicates. Conflicting eligible values on a single filing date produce ambiguity. Preserve original values and filing history; a changed value is a revision candidate, not proof of a formal restatement.
- Ratios use one filing accession. Growth may use the latest common filing only when both comparative values equal the latest individually selected values. This choice is disclosed. A changed latest value prevents substitution.
- Operating margin = operating income / revenue × 100. Growth = (current revenue − prior revenue) / prior revenue × 100. Revenue denominators must be positive. Missing inputs stay unavailable; they never become zero.
- Keep exact input decimals and exact rational percentages. Decimal renderings use 34 significant digits; display percentages use two decimal places and `ROUND_HALF_EVEN`.

`as_of` cannot exceed the snapshot date. Filing-date filtering cannot reconstruct intraday availability or undo subsequent corrections to historical API records. A snapshot older than seven days generates a warning. Refreshing does not automatically review new years or quarters; policy changes still require source checks.

## Real reference cases

The bundled Kraft Heinz case exercises the same selector but is **not an interactive issuer**. Its [restatement note](https://www.sec.gov/Archives/edgar/data/1637459/000163745919000049/R9.htm) reports FY2017 operating income of $6,773 million originally and $6,057 million after restatement and recasting. The $716 million difference includes an $80 million error-correction effect and a $636 million accounting-presentation change. The generic selector flags the changed value; the separate source card explains it.

The named standard revenue tag is genuinely absent from that company's downloaded API taxonomy, even though its filing reports net sales. This is missing tag coverage, not zero or absent business revenue. KHC's net-income attribution also differs from the reviewed AAPL/MSFT convention, which is another reason not to expose it as a supported issuer. See [the reference card](data/reference-cases/khc/ground-truth.json).

## Questions and optional model proposals

`ask` accepts issuer names or tickers, common metric synonyms, year lists or ranges, and an optional explicit filing cutoff. Missing company, years, metrics, or ambiguous profit/margin/change prompts produce clarification. Unsupported extra requests are not silently discarded. This remains a bounded parser, not unrestricted natural-language understanding.

An optional host can propose **arguments only**, validated by the same deterministic tools. To exercise that boundary without installing or calling a model:

```sh
python3 -B -m financial_metrics proposal <<'JSON'
{"ticker":"MSFT","fiscal_years":[2025],"metrics":["revenue","operating_margin"],"as_of":"2025-07-30"}
JSON
```

Proposals cannot contain financial answers, URLs, filenames, or executable actions. Validation checks allowed arguments and scope; it does not prove that a model faithfully interpreted the original question. There is no model in the baseline, and model behavior, token costs, and injection resistance have not been measured.

## MCP hosting and contracts

The server implements MCP **2025-11-25** over newline-delimited JSON-RPC stdio: initialization, initialized notification, ping, tool discovery, and tool calls. It exposes `resolve_company`, `get_annual_facts`, `get_quarterly_facts`, and `calculate_metrics`. Quarterly coverage is intentionally limited to NVIDIA Q2 FY2027 until more periods are reviewed. It offers no HTTP transport or arbitrary network, file, or execution capability.

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

Adjust executable and project paths when moving computers. The launcher works from an unrelated directory. The four tools publish and enforce closed input and **full nested output schemas**, including provenance, history, warnings, ratios, context, unavailable rows, and refusals. Invalid generated output becomes an `invalid_tool_output` refusal. Schemas validate structure; separate source and arithmetic checks validate financial meaning.

```sh
python3 -B -m financial_metrics smoke
python3 -B -m unittest discover -s tests -v
python3 -B -m financial_metrics.evaluate
```

`evaluate` writes each case, raw timing samples, test logs, and both issuer demos into `reports/`. The optional independent SDK check needs Python 3.10 or newer and a separate environment:

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

A custom data directory loads only its own reviewed issuer. The bundled default loads both. The refresher was tested with controlled HTTP responses; live refresh using a user's contact was not run. The supplied raw snapshots were downloaded with curl. Their manifests record source URLs, sizes, hashes, and capture-day packaging timestamps. Hashes detect changes relative to a trusted manifest; they do not authenticate an untrusted manifest.

## Read next

[WALKTHROUGH.md](WALKTHROUGH.md) traces one answer through the code. [EVALUATION.md](EVALUATION.md) records measured results and limitations. Independent source transcriptions live in `data/ground-truth.json`, `data/msft/ground-truth.json`, and `data/reference-cases/khc/ground-truth.json`. Adversarial synthetic modifications exist only in tests.
