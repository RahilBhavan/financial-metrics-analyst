"""Deterministic command-line analyst; all analysis crosses MCP stdio."""

import argparse
import json
import sys
from pathlib import Path

from .client import Client, smoke
from .domain import DEFAULT_DATA
from .fetch import fetch_snapshot
from .policy import METRICS, Refusal

from .questions import parse_question, validate_proposal
from .presentation import render, render_html


def analyze(data_dir, ticker, years, metrics, as_of):
    with Client(data_dir) as client:
        resolved = client.call("resolve_company", {"ticker": ticker})
        if resolved["status"] == "refused":
            return resolved
        as_of = as_of or resolved["lookup_timestamp"][:10]
        return client.call("calculate_metrics", {"cik": resolved["cik"], "fiscal_years": years, "metrics": metrics, "as_of": as_of})


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
            p.add_argument("--ticker", default="AAPL")
            p.add_argument("--years", nargs="+", type=int, default=[2023, 2024, 2025])
            p.add_argument("--metrics", nargs="+", default=list(METRICS))
            p.add_argument("--as-of")
    p = sub.add_parser("smoke")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA))
    p = sub.add_parser("fetch")
    p.add_argument("--output", required=True)
    p.add_argument("--user-agent", required=True)
    p.add_argument("--ticker", choices=("AAPL", "MSFT", "NVDA"), default="AAPL")
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
                ticker, years, metrics, as_of = args.ticker, args.years, args.metrics, args.as_of
            result = analyze(args.data_dir, ticker, years, metrics, as_of)
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
