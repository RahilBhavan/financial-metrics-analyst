# Implementation plan: six reliability and usability improvements

Requested 21 September 2026. Original planning notes remain historical documents; this plan governs the upgrade.

| Step | Work | Acceptance evidence | Status |
| --- | --- | --- | --- |
| 1 | Detect rejected newer annual candidates and prevent silent fallback to older facts. Include the blocking candidate in the explanation. | Tests for bad values, currency, metadata, as-of exclusions, and legitimate quarterly duplicates. | Complete |
| 2 | Review Apple FY2022 revenue as a supporting input and calculate FY2023 growth while retaining three visible report years. | Independent filing transcription; exact ratio check; coherent comparative filing selection. | Complete |
| 3 | Add a second reviewed issuer and real filing cases for a revision, unavailable standard tags, and a different fiscal calendar. | Source-linked reference cards, unmodified SEC snapshots or labeled exact extracts, tests against independently read filings. | Complete |
| 4 | Show a compact financial table with adjacent warnings and expandable formula/provenance detail. | Text report and portable local HTML report; checks for escaping, units, warnings, and evidence links. | Complete |
| 5 | Recognize common question variants and return explicit clarification requests for missing or ambiguous intent. Keep any model-supplied proposal behind the same deterministic validation. | Accepted-paraphrase and refusal/clarification corpus; no silent dropping of unsupported requests. | Complete |
| 6 | Publish and enforce complete output schemas for facts, ratios, context, warnings, provenance, and refusals. | Independent JSON Schema checks, malformed-output rejection tests, and official MCP client smoke tests. | Complete |
| Release | Update the walkthrough, evaluation, and reproducible reports. | Final tests, demos, SDK check, raw counts, report regeneration check. | Complete |

Implementation stays in this project workspace, with one agent, no paid model requirement, no deployment, and no external messaging. Public SEC reads are allowed. Each source-backed example will distinguish a real restatement from an unclassified revision, and distinguish a missing API tag from a company not disclosing a financial measure.

## Completion evidence

- 77 test methods passed with zero failures, errors, or skips.
- 161/161 separately enumerated evaluation cases passed across three issuers, real reference cases, intent handling, and refusal behavior.
- 21/21 official MCP SDK and independent nested-schema checks passed.
- `reports/demo.html`, `reports/microsoft-demo.html`, and `reports/nvidia-demo.html` contain the compact tables and expandable evidence.
- `scripts/regenerate_reports.py` rewrites every committed report from current code, and CI fails if they drift; `EVALUATION.md` states remaining scope and source limitations.

Microsoft FY2026 is now reviewed; its source values and accession are in `data/msft/ground-truth.json`. Kraft Heinz is a source-backed reference case only. No model or deployment was introduced. Original planning notes outside this project were preserved.
