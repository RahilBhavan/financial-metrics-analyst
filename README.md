# Financial metrics analyst

An offline analyst for **Apple (AAPL) and Microsoft (MSFT), fiscal 2023–2025**. It reports revenue, operating income, consolidated net income, operating margin, and revenue growth through a real MCP stdio subprocess. Every number retains its source filing and exact inputs.

All six improvements are implemented; see [IMPROVEMENT-PLAN.md](IMPROVEMENT-PLAN.md). The standard-library baseline requires Python 3.9 or newer. No account, API key, model, package installation, or network connection is needed.

## Quickstart

Python 3.9 or newer, standard library only. No install step, no API key, no network access.

```sh
git clone https://github.com/RahilBhavan/financial-metrics-analyst.git
cd financial-metrics-analyst
python3 -B -m unittest discover -s tests -v    # unit tests
python3 -B -m financial_metrics.evaluate       # full evaluation, writes reports/
python3 -B -m financial_metrics smoke          # MCP stdio round trip
python3 -B -m financial_metrics demo           # Apple FY2023-2025 report
```

## Results

Every figure below comes from [reports/evaluation-summary.json](reports/evaluation-summary.json), written by `python3 -B -m financial_metrics.evaluate`.

| Measure | Value |
| --- | ---: |
| Unit tests | 72 run, 0 failures, 0 errors, 0 skipped |
| Evaluation checks | 82/82 passed |
| Exact ratio checks | 12/12 |
| Filing value checks | 18/18 |
| Provenance checks | 18/18 |
| Question intent checks | 14/14 |
| Tool refusal checks | 12/12 |
| Real reference cases | 3/3 |
| Scope behavior checks | 3/3 |
| Supporting value checks | 2/2 |
| Warm MCP stdio call, median of 10 | 5.64 ms |

The timing excludes any model. Per-case records are in [reports/evaluation.json](reports/evaluation.json); the method and its limits are in [EVALUATION.md](EVALUATION.md).

## Run it

```sh
cd financial-metrics-analyst
python3 -B -m financial_metrics demo
python3 -B -m financial_metrics demo --html reports/demo.html
python3 -B -m financial_metrics analyze --ticker MSFT --as-of 2025-07-30
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

**Microsoft FY2026 is outside the reviewed scope.** Its API snapshot includes a newer annual filing, but that report could not be independently checked in this work. The default cutoff warns about this; the captured Microsoft demo uses `--as-of 2025-07-30` to align with the independently read 2025 report. Later comparative values for the reviewed years remain eligible under the declared selection policy.

## Selection and accounting rules

- Match the exact reviewed start/end dates, USD, approved US-GAAP tags, annual filing forms, and `fp=FY`. The filing's `fy` is stored separately as `reported_fy`; a comparative fact can describe an earlier year.
- Verify accession, filing date, report date, issuer, and safe document name against submissions metadata. Only the available submissions history is indexed.
- Select the latest eligible filing on or before the inclusive `as_of` date. A rejected same-end annual candidate at the same or a newer filing date blocks an older value. Unknown candidate dates also block. The result identifies the blockers instead of silently returning a stale number.
- The blocker test treats unknown durations or durations of at least 300 days as potentially annual. Known shorter quarter/YTD facts are rejected but do not block an otherwise valid annual fact. This is a reviewed-period policy, not a general detector for every malformed SEC record.
- Collapse identical duplicates. Conflicting eligible values on a single filing date produce ambiguity. Preserve original values and filing history; a changed value is a revision candidate, not proof of a formal restatement.
- Ratios use one filing accession. Growth may use the latest common filing only when both comparative values equal the latest individually selected values. This choice is disclosed. A changed latest value prevents substitution.
- Operating margin = operating income / revenue × 100. Growth = (current revenue − prior revenue) / prior revenue × 100. Revenue denominators must be positive. Missing inputs stay unavailable; they never become zero.
- Keep exact input decimals and exact rational percentages. Decimal renderings use 34 significant digits; display percentages use two decimal places and `ROUND_HALF_EVEN`.

`as_of` cannot exceed the snapshot date. Filing-date filtering cannot reconstruct intraday availability or undo subsequent corrections to historical API records. A snapshot older than seven days generates a warning. Refreshing does not automatically review new years or expand issuer coverage.

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

The server implements MCP **2025-11-25** over newline-delimited JSON-RPC stdio: initialization, initialized notification, ping, tool discovery, and tool calls. It exposes exactly `resolve_company`, `get_annual_facts`, and `calculate_metrics`. It offers no HTTP transport or arbitrary network, file, or execution capability.

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

Adjust executable and project paths when moving computers. The launcher works from an unrelated directory. The three tools publish and enforce closed input and **full nested output schemas**, including provenance, history, warnings, ratios, context, unavailable rows, and refusals. Invalid generated output becomes an `invalid_tool_output` refusal. Schemas validate structure; separate source and arithmetic checks validate financial meaning.

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

The separate operator command downloads **Apple only** from two fixed SEC endpoints. It refuses redirects and overwrites, bounds response sizes, uses timeouts and retries, and throttles each process. Use your own real contact information and follow the [SEC developer guidance](https://www.sec.gov/about/developer-resources).

```sh
python3 -B -m financial_metrics fetch --output local-snapshots/new-capture --user-agent 'YourProject your-real-contact@example.com'
python3 -B -m financial_metrics demo --data-dir local-snapshots/new-capture
```

A custom data directory loads only its own reviewed issuer. The bundled default loads both. The refresher was tested with controlled HTTP responses; live refresh using a user's contact was not run. The supplied raw snapshots were downloaded with curl. Their manifests record source URLs, sizes, hashes, and capture-day packaging timestamps. Hashes detect changes relative to a trusted manifest; they do not authenticate an untrusted manifest.

## Read next

[WALKTHROUGH.md](WALKTHROUGH.md) traces one answer through the code. [EVALUATION.md](EVALUATION.md) records measured results and limitations. Independent source transcriptions live in `data/ground-truth.json`, `data/msft/ground-truth.json`, and `data/reference-cases/khc/ground-truth.json`. Adversarial synthetic modifications exist only in tests.
