"""Rewrite every committed report from current code against a fixed clock.

Run from anywhere; reruns must leave `git diff reports/` empty. The SDK report
(reports/sdk-smoke.json) needs the optional mcp package and is written by
scripts/verify_sdk.py instead.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PROPOSAL = {"ticker": "MSFT", "fiscal_years": [2025], "metrics": ["revenue", "operating_margin"], "as_of": "2025-07-30"}
# (output file, CLI arguments, stdin, expected exit status)
COMMANDS = [
    ("stdio-smoke.json", ["smoke"], None, 0),
    ("question-demo.txt", ["ask", "What were Apple's net sales and operating profit in FY2023 through FY2025?"], None, 0),
    ("clarification-demo.json", ["ask", "Apple profit 2025", "--json"], None, 3),
    ("refusal-demo.txt", ["analyze", "--metrics", "ebitda"], None, 2),
    ("historical-demo.json", ["analyze", "--years", "2023", "--metrics", "revenue", "--as-of", "2024-10-31", "--json"], None, 0),
    ("microsoft-latest-demo.txt", ["analyze", "--ticker", "MSFT", "--years", "2023", "2024", "2025", "2026"], None, 0),
    ("proposal-demo.json", ["proposal", "--json"], json.dumps(PROPOSAL), 0),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", help="Fixed clock (YYYY-MM-DD); defaults to the newest snapshot capture date")
    args = parser.parse_args()
    if args.today:
        os.environ["FINANCIAL_METRICS_TODAY"] = args.today
    sys.path.insert(0, str(ROOT))
    from financial_metrics import evaluate

    # evaluate fixes the clock (if unset) before it writes evaluation.json and the issuer demos.
    status = evaluate.run()
    for name, command, stdin, expected in COMMANDS:
        result = subprocess.run([sys.executable, "-B", "-m", "financial_metrics", *command], cwd=str(ROOT),
                                input=stdin, text=True, capture_output=True, timeout=60)
        if result.returncode != expected:
            print(name + ": exit " + str(result.returncode) + ", expected " + str(expected) + "\n" + result.stderr, file=sys.stderr)
            status = 1
        (REPORTS / name).write_text(result.stdout)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
