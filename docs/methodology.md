# Selection rules, reference cases and the CLI

This page explains how the server picks one SEC fact per period, how it computes ratios, what the Kraft Heinz reference case shows, and how the CLI handles questions, proposals and refreshes. Code: `financial_metrics/policy.py`, `financial_metrics/domain.py`, `financial_metrics/questions.py` and `financial_metrics/fetch.py`.

## Expected results

Amounts are USD millions. JSON uses full USD decimal strings. Source: `reports/demo.txt`.

| Apple metric | FY2023 | FY2024 | FY2025 |
| --- | ---: | ---: | ---: |
| Revenue | 383,285 | 391,035 | 416,161 |
| Gross profit | 169,148 | 180,683 | 195,201 |
| Operating income | 114,301 | 123,216 | 133,050 |
| Net income | 96,995 | 93,736 | 112,010 |
| Gross margin | 44.13% | 46.21% | 46.91% |
| Operating margin | 29.82% | 31.51% | 31.97% |
| Revenue growth | −2.80% | 2.02% | 6.43% |

Apple FY2023 contains 371 days. FY2022 and FY2024 contain 364. Both affected growth comparisons carry warnings. FY2022 revenue is a reviewed supporting input, so the report still shows only three years. The [2025 Apple statement](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm) provides the main amounts. The [2024 statement](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm) provides FY2022 revenue of $394,328 million.

Microsoft uses years ending June 30. Its FY2023–FY2025 revenue is $211,915 million, $245,122 million and $281,724 million. The independently checked [2025 annual report](https://www.microsoft.com/investor/reports/ar25/index.html) provides those years. The [2024 report](https://www.microsoft.com/investor/reports/ar24/index.html) provides FY2022 revenue of $198,270 million. FY2024 has 366 days, so the adjacent growth comparisons carry duration warnings.

Microsoft FY2026 is reviewed from its FY2026 Form 10-K (accession 0001193125-26-323660). Revenue was $331.839 billion, gross profit $225.465 billion, operating income $155.237 billion and net income $133.749 billion. NVIDIA FY2024–FY2026 and Q2 FY2027 are also reviewed from SEC filings. See [issuer-expansion-research.md](issuer-expansion-research.md) and [the NVIDIA ground truth](../data/nvda/ground-truth.json).

## Selection and accounting rules

- Match the exact reviewed start and end dates, USD, approved US-GAAP tags, annual filing forms and `fp=FY`. The filing's `fy` is stored separately as `reported_fy`, because a comparative fact can describe an earlier year.
- Verify the accession, filing date, report date, issuer and safe document name against submissions metadata. Only the available submissions history is indexed.
- Select the latest eligible filing on or before the inclusive `as_of` date. A rejected same-end annual candidate at the same or a newer filing date blocks an older value. Unknown candidate dates also block. The result names the blockers instead of returning a stale number.
- The blocker test treats unknown durations, and durations of 300 days or more, as potentially annual. Known shorter quarter and year-to-date facts are rejected but do not block an otherwise valid annual fact. This is a reviewed-period policy, not a general detector for every malformed SEC record.
- Collapse identical duplicates. Conflicting eligible values on one filing date produce ambiguity. Keep the original values and filing history. A changed value is a revision candidate, not proof of a formal restatement. Quarterly selection applies the same conflict and blocker rules to quarter-length 10-Q and 10-Q/A candidates.
- Ratios use one filing accession. Growth may use the latest common filing only when both comparative values equal the latest individually selected values. The result discloses this choice. A changed latest value prevents substitution.
- Gross margin = gross profit / revenue × 100. Operating margin = operating income / revenue × 100. Growth = (current revenue − prior revenue) / prior revenue × 100. Revenue denominators must be positive. Missing inputs stay unavailable. They never become zero.
- Keep exact input decimals and exact rational percentages. Decimal renderings use 34 significant digits. Display percentages use two decimal places and `ROUND_HALF_EVEN`.

`as_of` cannot exceed the snapshot date. Filing-date filtering cannot reconstruct intraday availability or undo later corrections to historical API records. A snapshot older than seven days produces a warning. Set `FINANCIAL_METRICS_TODAY=YYYY-MM-DD` to fix that clock. A refresh does not review new years or quarters. Policy changes still need source checks.

## Ten issuers and reviewed quarters

The seven issuers added on 2026-10-25 use the same selector and the same snapshot method. Their annual periods are the calendar years 2023–2025 (Visa: fiscal years ending 30 September), with the prior fiscal year's revenue as the growth baseline.

| Issuer | Revenue tag | Not reported in the income statement | Reviewed quarters |
| --- | --- | --- | --- |
| Coinbase (COIN) | `Revenues` | gross profit | Q2, Q3 2025; Q1, Q2 2026 |
| Strategy (MSTR) | `RevenueFromContractWithCustomerExcludingAssessedTax` | none | Q2, Q3 2025; Q1, Q2 2026 |
| Robinhood (HOOD) | `Revenues` | gross profit, operating income | Q2, Q3 2025; Q1, Q2 2026 |
| Block (XYZ) | `Revenues` | none | Q2, Q3 2025; Q1, Q2 2026 |
| PayPal (PYPL) | `Revenues` | gross profit | Q1, Q2, Q3 2025; Q1 2026 |
| Visa (V) | `RevenueFromContractWithCustomerExcludingAssessedTax` | gross profit | fiscal Q2, Q3 2025; Q1, Q2 2026 |
| Tesla (TSLA) | `Revenues` | none | Q3 2025; Q1, Q2, Q3 2026 |

- **Quarters.** Each issuer's profile lists its four latest 10-Q periods that the SEC companyfacts API serves. Apple, Microsoft and NVIDIA got four quarters too. The fiscal fourth quarter has no 10-Q and is not offered. PayPal's and Visa's 10-Qs filed in July 2026 have no facts in the API (checked again on 2026-10-25), so their latest two quarters are not reviewed.
- **Fiscal years.** `fiscal_year_of` in `domain.py` gives a filing's fiscal year from its report date and the profile's `fye_month`. A later 10-Q repeats a quarter as its prior-year comparative. That record is accepted when its `fy` matches its own filing, so a changed comparative shows as a revision candidate and an identical one is collapsed.
- **Unreported metrics.** If the issuer's statement has no such line, the tag is absent and the result is `insufficient_data` with reason `standard_tag_absent`. Dependent margins say `operand_unavailable`.
- **Amended filings.** Robinhood's FY2025 10-K/A is a full re-filing that changes formatting only. The selector picks the later filing and keeps the 10-K as `original`.
- **Relabelled record.** PayPal's Q3 2025 10-Q lists the Q2 2025 net income again under `fp=Q3`. The value is the same, but the selector cannot tell that from an invalid record, so at later cutoffs Q2 2025 net income comes back `insufficient_data`. At 2025-10-27 or earlier it returns $1,261 million from the Q2 10-Q.
- **Expected values.** `scripts/review_filings.py` reads each filing document's income statement and writes the `ground-truth.json` card. It never reads companyfacts. Operator command: `python3 -B scripts/review_filings.py --cache DIR --user-agent 'Name email' --ticker COIN`.

## Kraft Heinz reference case

The bundled Kraft Heinz case runs the same selector, but Kraft Heinz is **not an interactive issuer**. Its [restatement note](https://www.sec.gov/Archives/edgar/data/1637459/000163745919000049/R9.htm) reports FY2017 operating income of $6,773 million originally and $6,057 million after restatement and recasting. The $716 million difference includes an $80 million error-correction effect and a $636 million presentation change. The selector flags the changed value. The separate source card explains it.

The named standard revenue tag is absent from the company's downloaded API taxonomy, even though its filing reports net sales. This is missing tag coverage, not zero revenue. Kraft Heinz also reports noncontrolling interests, so its attributable net income differs from consolidated net income. That difference needs its own statement review, which is another reason not to expose Kraft Heinz as a supported issuer. See [the reference card](../data/reference-cases/khc/ground-truth.json).

## Questions and model proposals

`ask` accepts issuer names or tickers, common metric synonyms, year lists or ranges, and an optional filing cutoff. A missing company, year or metric produces a clarification request. So do ambiguous "profit", "margin" and "change" prompts. The parser does not drop unsupported extra requests. It is a bounded parser, not general natural-language understanding.

| Outcome | Exit code |
| --- | ---: |
| Successful or explicitly partial analysis | 0 |
| `refused` (unsupported request) | 2 |
| `needs_clarification` (for example `ask 'Microsoft profit 2025'`) | 3 |

Use `--json` for structured output, `--details` for expanded text, or `--html PATH` for a local report with expandable evidence. The operator CLI writes HTML. The MCP tools do not write files.

An optional host can propose **arguments only**. The same deterministic tools validate them. To try that boundary without a model:

```sh
python3 -B -m financial_metrics proposal <<'JSON'
{"ticker":"MSFT","fiscal_years":[2025],"metrics":["revenue","operating_margin"],"as_of":"2025-07-30"}
JSON
```

Proposals cannot contain financial answers, URLs, filenames or executable actions. Validation checks the allowed arguments and scope. It does not prove that a model interpreted the original question correctly.

## Optional SEC refresh

The separate `fetch` operator command downloads any of the ten reviewed tickers from fixed issuer-specific SEC endpoints. It refuses redirects and overwrites, limits response sizes, uses timeouts and retries, and throttles each process. Use your own real contact information and follow the [SEC developer guidance](https://www.sec.gov/about/developer-resources).

```sh
python3 -B -m financial_metrics fetch --ticker NVDA --output local-snapshots/new-capture --user-agent 'YourProject your-real-contact@example.com'
python3 -B -m financial_metrics demo --data-dir local-snapshots/new-capture
```

A custom data directory loads only its own reviewed issuer. The bundled default loads all ten. Tests cover the refresher with controlled HTTP responses. A live refresh with a user's contact was not run. The bundled raw snapshots were downloaded with curl. Their manifests record source URLs, sizes, SHA-256 hashes and capture-day packaging timestamps. Hashes detect changes relative to a trusted manifest. They do not authenticate an untrusted manifest.
