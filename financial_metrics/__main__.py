"""Deterministic command-line analyst; all analysis crosses MCP stdio."""

import argparse
import json
import sys
from pathlib import Path

from .client import Client, smoke
from .domain import DEFAULT_DATA, snapshot_ticker
from .fetch import TICKER_CIKS, fetch_snapshot
from .policy import METRICS, PROFILE_BY_TICKER, TAGS, Refusal

from .questions import parse_question, validate_proposal
from .presentation import render, render_html


def analyze(data_dir, ticker, years, metrics, as_of, quarter=None):
    with Client(data_dir) as client:
        resolved = client.call("resolve_company", {"ticker": ticker})
        if resolved["status"] == "refused":
            return resolved
        as_of = as_of or resolved["lookup_timestamp"][:10]
        if quarter:
            if not years:
                labels = sorted({q for _, q in PROFILE_BY_TICKER.get(ticker, {}).get("quarters", {})})
                raise Refusal("unsupported_quarter", "This issuer has no reviewed " + quarter + " quarter. Reviewed: " + ", ".join(labels) + ".")
            if len(years) != 1:
                raise Refusal("unsupported_years", "Name exactly one fiscal year with --quarter.")
            # Quarterly ratios are not calculated; the tool refuses them rather than dropping them here.
            return client.call("get_quarterly_facts", {"cik": resolved["cik"], "fiscal_year": years[0], "quarter": quarter,
                                                       "metrics": metrics or list(TAGS), "as_of": as_of})
        return client.call("calculate_metrics", {"cik": resolved["cik"], "fiscal_years": years, "metrics": metrics or list(METRICS), "as_of": as_of})


def defaults(data_dir, ticker, years, quarter):
    """Omitted options mean the snapshot's own issuer and all of its reviewed periods."""
    ticker = (ticker or snapshot_ticker(data_dir) or "AAPL").upper()
    profile = PROFILE_BY_TICKER.get(ticker)
    if years is None and profile:
        # A quarter defaults to its latest reviewed fiscal year.
        years = sorted({y for y, q in profile["quarters"] if q == quarter})[-1:] if quarter else sorted(profile["periods"])
    return ticker, years


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "analyze", "ask", "proposal"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", default=str(DEFAULT_DATA))
        p.add_argument("--json", action="store_true")
        p.add_argument("--details", action="store_true")
        p.add_argument("--html", metavar="PATH", help="Write a standalone report to this local path")
        if name == "ask":
            p.add_argument("question")
        elif name != "proposal":
            p.add_argument("--ticker", help="Defaults to the issuer of --data-dir")
            p.add_argument("--years", nargs="+", type=int, help="Defaults to every reviewed year for the issuer")
            p.add_argument("--quarter", help="Read reviewed quarterly facts, for example Q2 with --years 2027")
            p.add_argument("--metrics", nargs="+", help="Defaults to every annual metric, or every fact for --quarter")
            p.add_argument("--as-of")
    p = sub.add_parser("smoke")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA))
    p = sub.add_parser("fetch")
    p.add_argument("--output", required=True)
    p.add_argument("--user-agent", required=True)
    p.add_argument("--ticker", choices=sorted(TICKER_CIKS), default="AAPL")
    args = parser.parse_args()
    try:
        if args.command == "smoke":
            result = smoke(args.data_dir)
        elif args.command == "fetch":
            result = fetch_snapshot(args.output, args.user_agent, args.ticker)
        else:
            if args.command == "ask":
                ticker, years, metrics, as_of = parse_question(args.question)
            elif args.command == "proposal":
                raw = sys.stdin.read(65537)
                if len(raw) > 65536:
                    raise Refusal("proposal_too_large", "Proposal exceeds 64 KiB.")
                try:
                    proposal = json.loads(raw)
                except ValueError:
                    raise Refusal("invalid_proposal", "Proposal must be a JSON object on stdin.")
                ticker, years, metrics, as_of = validate_proposal(proposal)
            else:
                args.quarter = args.quarter.upper() if getattr(args, "quarter", None) else None
                ticker, years = defaults(args.data_dir, args.ticker, args.years, args.quarter)
                metrics, as_of = args.metrics, args.as_of
            result = analyze(args.data_dir, ticker, years, metrics, as_of, getattr(args, "quarter", None))
    except Refusal as exc:
        result = exc.as_dict()
    except (RuntimeError, OSError) as exc:
        result = {"status": "refused", "code": "runtime_failure", "message": str(exc)}
    if getattr(args, "html", None):
        try:
            Path(args.html).write_text(render_html(result), encoding="utf-8")
        except OSError as exc:
            print("Could not write HTML report: " + str(exc), file=sys.stderr)
            return 2
    if getattr(args, "json", False) or args.command in ("fetch", "smoke"):
        print(json.dumps(result, indent=2))
    else:
        print(render(result, details=args.details))
    return {"refused": 2, "needs_clarification": 3}.get(result["status"], 0)


if __name__ == "__main__":
    sys.exit(main())
