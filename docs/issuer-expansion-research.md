# Issuer expansion research

Research date: 2026-09-22

This note records primary-source evidence for extending the project's reviewed annual scope and adding a bounded NVIDIA profile. Dollar values below are U.S. dollars; tables show millions for readability. The SEC Company Facts API was used to verify the exact standard XBRL tags, fact periods, accessions, filing dates, forms, and fiscal-period labels. The linked SEC filings independently show the reported statements and filing metadata.

## 1. Microsoft FY2026

Microsoft's FY2026 reporting period is **2025-07-01 through 2026-06-30**. Its Form 10-K was filed **2026-07-29** under accession **0001193125-26-323660** with primary document **`msft-20260630.htm`**. The [SEC filing index](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/0001193125-26-323660-index.htm) identifies the filing; the [filed Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm) reports the income statement.

| Fiscal year | Period | Revenue | Operating income | Net income | Source accession |
|---|---|---:|---:|---:|---|
| FY2026 | 2025-07-01–2026-06-30 | $331,839 | $155,237 | $133,749 | 0001193125-26-323660 |
| FY2025 comparative | 2024-07-01–2025-06-30 | $281,724 | $128,528 | $101,832 | 0001193125-26-323660 |

The exact SEC standard tags are:

- Revenue: `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`
- Operating income: `us-gaap:OperatingIncomeLoss`
- Net income: `us-gaap:NetIncomeLoss`

The FY2025 comparative revenue in the FY2026 filing is therefore suitable for a common-filing FY2026 growth calculation: `(331839000000 - 281724000000) / 281724000000`. The FY2025 comparative and FY2026 value have identical tag, unit, accession, and form metadata.

## 2. Bounded NVIDIA annual profile

NVIDIA Corporation is CIK **0001045810**, ticker **NVDA**. A bounded annual profile for FY2024–FY2026 is well supported. NVIDIA uses a 52/53-week fiscal calendar, so hard-coded calendar-year dates would be incorrect.

### Reviewed periods and values

The latest FY2026 10-K presents all three years together in one audited Consolidated Statement of Income. It reports these exact values in millions in the [filed statement](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm#i960a813759784ef7a2efbae7a78f01b7_61):

| Fiscal year | Exact period | Revenue | Gross profit | Operating income | Net income |
|---|---|---:|---:|---:|---:|
| FY2024 | 2023-01-30–2024-01-28 | $60,922 | $44,301 | $32,972 | $29,760 |
| FY2025 | 2024-01-29–2025-01-26 | $130,497 | $97,858 | $81,453 | $72,880 |
| FY2026 | 2025-01-27–2026-01-25 | $215,938 | $153,463 | $130,387 | $120,067 |

For a consistent latest-disclosure selector, all twelve annual facts are available from the FY2026 10-K under accession **0001045810-26-000021**, filed **2026-02-25**, primary document **`nvda-20260125.htm`**, `form=10-K`, and `fp=FY`. The [SEC filing index](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/0001045810-26-000021-index.htm) confirms the accession, filing date, report date, and primary document.

The original annual filings are also useful for source-history tests:

| Fiscal year | Original accession | Filing date | Report date | Primary document |
|---|---|---|---|---|
| FY2024 | 0001045810-24-000029 | 2024-02-21 | 2024-01-28 | `nvda-20240128.htm` |
| FY2025 | 0001045810-25-000023 | 2025-02-26 | 2025-01-26 | `nvda-20250126.htm` |
| FY2026 | 0001045810-26-000021 | 2026-02-25 | 2026-01-25 | `nvda-20260125.htm` |

The [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm) and [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm) reproduce the earlier-year values; the FY2026 filing reproduces FY2024 and FY2025 again without changing these values.

### Exact standard tags

- Revenue: `us-gaap:Revenues`
- Gross profit: `us-gaap:GrossProfit`
- Operating income: `us-gaap:OperatingIncomeLoss`
- Net income: `us-gaap:NetIncomeLoss`

NVIDIA's recent revenue facts use `us-gaap:Revenues`, not the revenue tag currently used for Apple and Microsoft. `RevenueFromContractWithCustomerExcludingAssessedTax` exists in NVIDIA's Company Facts history only for older periods and must not be treated as the current annual revenue tag. Issuer profiles therefore need a per-issuer revenue tag mapping.

### Calendar and selection limitations

- Fiscal labels must be assigned from the reviewed issuer profile, not SEC `frame` values. For example, NVIDIA FY2026 ends in calendar 2026 but its Company Facts frame is `CY2025` because the fiscal year begins in 2025.
- FY2024 is a 364-day period, FY2025 is a 364-day period, and FY2026 is a 364-day period based on inclusive reporting boundaries.
- The FY2026 filing is the clean common source for comparisons because it presents FY2024–FY2026 together and the reproduced values agree with the original filings.
- Gross profit is available as a standard tag throughout the requested annual and quarterly scope, so it can be added without an issuer-specific extension tag.

## 3. Recent NVIDIA quarter

The most recent filed quarter as of this research date is **Q2 FY2027**, the three months **2026-04-27 through 2026-07-26**. NVIDIA's Form 10-Q labels the report “For the Quarter Ended July 26, 2026.” It was filed **2026-08-26** under accession **0001045810-26-000075**, primary document **`nvda-20260726.htm`**. The [SEC filing index](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/0001045810-26-000075-index.htm) confirms its metadata.

| Fiscal quarter | Exact period | Revenue | Gross profit | Operating income | Net income |
|---|---|---:|---:|---:|---:|
| Q2 FY2027 | 2026-04-27–2026-07-26 | $96,221 | $72,142 | $63,734 | $59,688 |

The [unaudited condensed statement of income](https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm#i22ad2bf3cdcc48399b276eeca78c1170_10) presents the three-month amounts separately from the six-month year-to-date amounts. The Company Facts records use:

- `us-gaap:Revenues`, start `2026-04-27`, end `2026-07-26`, `fp=Q2`, value `96221000000`
- `us-gaap:GrossProfit`, same period and metadata, value `72142000000`
- `us-gaap:OperatingIncomeLoss`, same period and metadata, value `63734000000`
- `us-gaap:NetIncomeLoss`, same period and metadata, value `59688000000`

The same filing also contains six-month facts starting `2026-01-26`. A quarter selector must require the exact reviewed three-month start date, because selecting solely by end date, form, and `fp=Q2` could confuse the discrete quarter with the year-to-date period.

## Implementation-ready conclusions

1. Microsoft FY2026 can be added directly with the existing three tags and period policy. Its FY2025 comparative in the same filing supports revenue growth on a common filing basis.
2. NVIDIA FY2024–FY2026 can be added as a three-year reviewed profile using the FY2026 10-K as the latest common disclosure.
3. NVIDIA needs issuer-specific revenue tag `us-gaap:Revenues`; the other three tags are standard and match the existing operating-income and net-income mappings.
4. Adding gross profit requires a fourth base metric tag, `us-gaap:GrossProfit`, and any derived gross-margin metric should divide it by revenue from the same filing and exact period.
5. Quarterly support should begin as an explicit NVIDIA Q2 FY2027 allowlist entry and require the exact start/end dates. It should not generalize annual duration rules to quarterly facts.
6. All cited values are GAAP amounts from SEC filings. No adjusted or non-GAAP figures are included.

## Primary data endpoints consulted

- [Microsoft SEC Company Facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json)
- [Microsoft SEC submissions](https://data.sec.gov/submissions/CIK0000789019.json)
- [NVIDIA SEC Company Facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json)
- [NVIDIA SEC submissions](https://data.sec.gov/submissions/CIK0001045810.json)
