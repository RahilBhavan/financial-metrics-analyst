# Financial metrics analyst

For financial questions about SEC facts, ratios, annual/quarterly cash flows, cash capex and free cash flow or the bundled crypto-treasury records, read `.agents/skills/financial-metrics/SKILL.md` and use its T3-native local workflow. No model API key or MCP setup is needed. The current T3 model interprets the question; Python validates and renders the financial answer.

For engineering tasks, preserve the standard-library runtime, exact decimal/rational arithmetic, issuer-specific reviewed periods, source provenance and closed tool contracts. The optional MCP server and external model adapters remain compatibility interfaces.

Verify changes with `python3 -B -m unittest discover -s tests`, `python3 -B -m financial_metrics smoke`, and `python3 -B scripts/regenerate_reports.py`. Reports must reproduce without drift. The optional SDK check uses `requirements-sdk-test.txt`. Keep historical model evaluations intact; write new runs to separate report directories.
