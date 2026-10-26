"""Fetch live SEC data for each reviewed issuer and compare it with the bundled snapshots.

Operator-run and networked, so it is not part of the default tests. SEC requires a real
contact in the User-Agent: pass --user-agent "name you@example.com". Writes a JSON report.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from financial_metrics.__main__ import analyze  # noqa: E402
from financial_metrics.fetch import fetch_snapshot  # noqa: E402
from financial_metrics.domain import AUDIT_KEYS  # noqa: E402
from financial_metrics.policy import METRICS, PROFILES, TAGS  # noqa: E402

# Every reviewed period, derived from the profiles: (ticker, bundled directory, years, quarter or None).
CHECKS = [(p["ticker"], str(Path("data", p["directory"])), sorted(p["periods"]), None) for p in PROFILES.values()]
CHECKS += [(p["ticker"], str(Path("data", p["directory"])), [year], quarter)
           for p in PROFILES.values() for year, quarter in sorted(p.get("quarters", {}))]


def fact_keys(path):
    doc = json.loads(Path(path, "companyfacts.json").read_text())
    return {
        (tag, unit, r.get("start"), r["end"], r["accn"], r["form"]): r["val"]
        for tag, body in doc["facts"].get("us-gaap", {}).items()
        for unit, rows in body["units"].items()
        for r in rows
    }


def recent(path):
    r = json.loads(Path(path, "submissions.json").read_text())["filings"]["recent"]
    return {a: (f, d) for a, f, d in zip(r["accessionNumber"], r["form"], r["filingDate"])}


def reviewed_output(result):
    """The financial answer only: values, provenance, arithmetic, and result warnings.

    Snapshot identity (capture time, companyfacts hash) and the candidate audit (rejected
    candidates, including filings after the cutoff) change whenever SEC adds a filing,
    so they are reported separately rather than counted as a change in reviewed output.
    """
    result = json.loads(json.dumps(result, default=str))
    results = [{k: v for k, v in row.items() if k not in AUDIT_KEYS} for row in result.get("results") or []]
    return json.dumps({"status": result["status"], "results": results,
                       "warnings": [w for w in result.get("context", {}).get("warnings", []) if not w.startswith("snapshot_older_than")]},
                      sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--output", default=str(ROOT / "reports" / "live-refresh.json"))
    args = parser.parse_args()
    report = {}
    with tempfile.TemporaryDirectory() as tmp:
        for ticker, bundled, years, quarter in CHECKS:
            live = str(Path(tmp, ticker))
            if not Path(live).exists():
                fetch_snapshot(live, args.user_agent, ticker)
            old, new = fact_keys(ROOT / bundled), fact_keys(live)
            old_recent, new_recent = recent(ROOT / bundled), recent(live)
            # one explicit as_of keeps both runs on the same filing cutoff
            as_of = json.loads(Path(ROOT, bundled, 'manifest.json').read_text())['captured_at'][:10]
            metrics = list(TAGS) if quarter else list(METRICS)
            a = analyze(str(ROOT / bundled), ticker, years, metrics, as_of, quarter)
            b = analyze(live, ticker, years, metrics, as_of, quarter)
            dropped = sorted(set(old_recent) - set(new_recent))
            label = ticker + (" " + quarter + " FY" + str(years[0]) if quarter else "")
            report[label] = {
                "companyfacts_added": len(set(new) - set(old)),
                "companyfacts_removed": len(set(old) - set(new)),
                "companyfacts_changed": sum(1 for k in old if k in new and old[k] != new[k]),
                "new_filings": sorted(set(new_recent) - set(old_recent)),
                "dropped_from_recent_window": len(dropped),
                "dropped_annual_or_quarterly": [old_recent[a] for a in dropped if old_recent[a][0].startswith("10-")],
                "snapshot_identical": a.get("context", {}).get("snapshot_sha256") == b.get("context", {}).get("snapshot_sha256"),
                "reviewed_output_identical": reviewed_output(a) == reviewed_output(b),
            }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(r["reviewed_output_identical"] and not r["companyfacts_changed"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
