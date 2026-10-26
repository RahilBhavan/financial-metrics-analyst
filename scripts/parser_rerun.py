"""Rerun the question parser for "Microsoft profit 2026" and check the figures the cards print.

    python3 -B scripts/parser_rerun.py [--out reports/parser-rerun-2026-10-26.log]

Runs the real CLI three times (ambiguous question, then each offered choice), prints every command
with its exit code and JSON, and exits 1 if any figure, accession, exit code or the snapshot-age
warning differs from what the Microsoft card states. It does not refresh the snapshot: that needs
an SEC User-Agent with a real contact address, which is the operator's to supply
(`python3 -B -m financial_metrics fetch --ticker MSFT --output DIR --user-agent 'Name email'`).
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "operating_income": ("Microsoft operating income 2026", "155237000000"),
    "net_income": ("Microsoft net income 2026", "133749000000"),
}
ACCESSION, PERIOD_END, STALE_WARNING = "0001193125-26-323660", "2026-06-30", "snapshot_older_than_7_days"


def ask(question, *flags):
    run = subprocess.run([sys.executable, "-B", "-m", "financial_metrics", "ask", "--json", *flags, question],
                         cwd=ROOT, capture_output=True, text=True)
    return run.returncode, json.loads(run.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    out = parser.parse_args().out
    log, problems = [], []

    def record(command, code, body):
        log.append(f"$ {command}\nexit {code}\n{json.dumps(body, indent=2)}\n")

    code, body = ask("Microsoft profit 2026")
    record("python3 -B -m financial_metrics ask --json 'Microsoft profit 2026'", code, body)
    if (code, body.get("status"), body.get("choices")) != (3, "needs_clarification", ["Operating income", "Net income"]):
        problems.append("'Microsoft profit 2026' did not ask operating income or net income (exit 3)")

    snapshot = None
    for metric, (question, value) in EXPECTED.items():
        code, body = ask(question, "--details")
        record(f"python3 -B -m financial_metrics ask --json --details '{question}'", code, body)
        result = body["results"][0] if body.get("results") else {}
        snapshot = body.get("context", {})
        seen = (code, result.get("value"), result.get("accn"), result.get("form"), result.get("period_end"))
        if seen != (0, value, ACCESSION, "10-K", PERIOD_END):
            problems.append(f"{metric}: expected {value} {ACCESSION} 10-K {PERIOD_END}, got {seen}")
        if STALE_WARNING not in " ".join(snapshot.get("warnings", [])):
            problems.append(f"{metric}: snapshot-age warning missing")

    captured = datetime.fromisoformat(snapshot["snapshot_captured_at"])
    age = (datetime.now(timezone.utc).date() - captured.date()).days
    summary = [f"Rerun {date.today()}: snapshot captured {captured.date()} ({age} days old); "
               f"operating income 155.237B, net income 133.749B, {ACCESSION}.",
               "Result: " + ("MISMATCH: " + "; ".join(problems) if problems else "all figures match the card."),
               f"Snapshot older than 7 days: {'yes, not refreshed (needs an SEC contact User-Agent)' if age > 7 else 'no'}."]
    text = "\n".join(summary) + "\n\n" + "\n".join(log)
    if out:
        out.write_text(text)
    print(text)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
