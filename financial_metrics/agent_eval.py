"""Trajectory evaluation of the treasury-analyst agent on the frozen task set.

    python3 -B -m financial_metrics.agent_eval --backend claude-code
    python3 -B -m financial_metrics.agent_eval --rescore reports/agent-runs.jsonl

Runs every task in evals/agent-tasks.json through agent.run over a real MCP subprocess, writes
each full run record to reports/agent-runs.jsonl and the scored summary to
reports/agent-eval.json. Scoring follows the rules in the task file's header and never calls a
model. --rescore recomputes the summary from saved runs without rerunning the agent.
"""

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .client import Client
from .tracing import quotes
from .treasury import TreasuryService

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "evals" / "agent-tasks.json"
LATEST = {firm: weeks[-1]["week_end"] for firm, weeks in TreasuryService().weeks.items()}


def _has_record(task, result):
    record = task["expected_record"]
    if not isinstance(result, dict) or result.get("status") not in ("ok", "partial"):
        return False
    if task["category"] == "treasury_actions":
        return any(r["week_end"] == record["week_end"] and r["action"] == record["action"] for r in result.get("actions", []))
    if task["category"] == "coins_per_share":
        return result["week"]["week_end"] == record["week_end"]
    if task["category"] == "break_even":
        return result["break_even"]["week_end"] == record["week_end"]
    return any(r.get("metric") == record["metric"] and r.get("fiscal_year") == record["fiscal_year"] and r.get("status") == "ok"
               for r in result.get("results", []))


def arguments_match(task, name, arguments, result):
    """Scored-argument rule from the task header; the call must also return the expected record."""
    expected = task["expected_arguments"]
    if name not in task["expected_tools"] or not isinstance(arguments, dict) or not _has_record(task, result):
        return False
    if task["category"] == "treasury_actions":
        week = task["expected_record"]["week_end"]
        return (arguments.get("firm") == expected["firm"] and arguments.get("action") == expected["action"]
                and arguments.get("week_from", week) <= week <= arguments.get("week_to", week))
    if task["category"] in ("coins_per_share", "break_even"):
        firm = expected["firm"]
        if arguments.get("firm") != firm:
            return False
        week = arguments.get("week_end", LATEST.get(firm))
        if "compare_to" in expected:
            return {week, arguments.get("compare_to")} == {expected["week_end"], expected["compare_to"]}
        return week == expected["week_end"]
    for key, value in expected.items():
        if key in ("fiscal_years", "metrics"):
            if not isinstance(arguments.get(key), list) or not set(value) <= set(arguments[key]):
                return False
        elif arguments.get(key) != value:
            return False
    return True


def score(task, run):
    calls = run["tool_calls"]
    results = run.get("results", [])
    answered = run["status"] == "answered"
    delivered = run["traces"] if answered else []
    first = run["drafts"][0]["traces"] if run["drafts"] else []
    out = {"id": task["id"], "category": task["category"], "in_scope": task["in_scope"], "status": run["status"],
           "latency_ms": run["latency_ms"], "cost_usd": run.get("cost_usd"), "turns": run["turns"],
           "tokens": sum(run["usage"].values()), "tool_calls": len(calls),
           "numbers_delivered": len(delivered), "numbers_delivered_traced": sum(t["traced"] for t in delivered),
           "numbers_first_draft": len(first), "numbers_first_draft_traced": sum(t["traced"] for t in first),
           "rewrites": max(len(run["drafts"]) - 1, 0)}
    if not task["in_scope"]:
        out.update(refusal_correct=run["status"] == "refused", data_tool_calls=len(calls))
        return out
    result_of = lambda call: results[call["result_index"]] if call.get("result_index") is not None else None
    out["tool_correct"] = any(c["name"] in task["expected_tools"] for c in calls)
    out["arguments_correct"] = any(arguments_match(task, c["name"], c["arguments"], result_of(c)) for c in calls)
    out["answer_numbers_correct"] = answered and all(any(quotes(run["answer"], item["value"]) for item in group)
                                                     for group in task["expected_numbers"])
    out["false_refusal"] = run["status"] == "refused"
    return out


def summarize(scores):
    in_scope = [s for s in scores if s["in_scope"]]
    out_scope = [s for s in scores if not s["in_scope"]]
    ratio = lambda part, whole: {"passed": part, "total": whole, "rate": round(part / whole, 4) if whole else None}
    delivered = sum(s["numbers_delivered"] for s in scores)
    drafts = sum(s["numbers_first_draft"] for s in scores)
    costs = [s["cost_usd"] for s in scores if s["cost_usd"] is not None]
    latencies = [s["latency_ms"] for s in scores]
    statuses = {}
    for s in scores:
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
    by_category = {}
    for s in in_scope:
        c = by_category.setdefault(s["category"], {"tasks": 0, "tool": 0, "arguments": 0, "answer_numbers": 0})
        c["tasks"] += 1
        c["tool"] += s["tool_correct"]
        c["arguments"] += s["arguments_correct"]
        c["answer_numbers"] += s["answer_numbers_correct"]
    return {
        "tasks": len(scores), "statuses": statuses,
        "tool_selection": ratio(sum(s["tool_correct"] for s in in_scope), len(in_scope)),
        "arguments": ratio(sum(s["arguments_correct"] for s in in_scope), len(in_scope)),
        "answer_numbers": ratio(sum(s["answer_numbers_correct"] for s in in_scope), len(in_scope)),
        "numbers_traced_delivered": ratio(sum(s["numbers_delivered_traced"] for s in scores), delivered),
        "numbers_traced_first_draft": ratio(sum(s["numbers_first_draft_traced"] for s in scores), drafts),
        "answers_withheld_untraced": statuses.get("abstained_untraced", 0),
        "refusal_out_of_scope": ratio(sum(s["refusal_correct"] for s in out_scope), len(out_scope)),
        "false_refusals_in_scope": sum(s["false_refusal"] for s in in_scope),
        "latency_ms": {"p50": round(statistics.median(latencies), 1), "p90": round(sorted(latencies)[int(0.9 * (len(latencies) - 1))], 1),
                       "max": max(latencies)} if latencies else None,
        "tokens_per_task_mean": round(statistics.mean(s["tokens"] for s in scores), 1) if scores else None,
        "cost_usd_per_task_mean": round(statistics.mean(costs), 6) if costs else None,
        "cost_usd_total": round(sum(costs), 6) if costs else None,
        "tool_calls_per_task_mean": round(statistics.mean(s["tool_calls"] for s in scores), 2) if scores else None,
        "by_category": by_category,
    }


def report(tasks_file, runs, meta):
    data = json.loads(Path(tasks_file).read_text())
    by_id = {t["id"]: t for t in data["tasks"]}
    scores = [score(by_id[r["task_id"]], r) for r in runs]
    return {"meta": {**meta, "tasks_file": str(Path(tasks_file).resolve().relative_to(ROOT)),
                     "tasks_sha256": hashlib.sha256(Path(tasks_file).read_bytes()).hexdigest()},
            "summary": summarize(scores), "scores": scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=("claude-code", "anthropic"), default="claude-code")
    parser.add_argument("--model")
    parser.add_argument("--tasks", default=str(TASKS))
    parser.add_argument("--only", help="Comma-separated task ids")
    parser.add_argument("--out-dir", default=str(ROOT / "reports"))
    parser.add_argument("--rescore", metavar="RUNS_JSONL")
    args = parser.parse_args()
    out = Path(args.out_dir)
    if args.rescore:
        lines = Path(args.rescore).read_text().splitlines()
        meta = json.loads(lines[0])["meta"]
        runs = [json.loads(line) for line in lines[1:]]
    else:
        from .agent import AnthropicMessages, ClaudeCodeCLI, DEFAULT_MODEL, run
        backend = AnthropicMessages(args.model or DEFAULT_MODEL) if args.backend == "anthropic" else ClaudeCodeCLI(args.model or "haiku")
        tasks = json.loads(Path(args.tasks).read_text())["tasks"]
        if args.only:
            wanted = set(args.only.split(","))
            tasks = [t for t in tasks if t["id"] in wanted]
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        meta = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "backend": backend.label,
                "model_requested": args.model or (DEFAULT_MODEL if args.backend == "anthropic" else "haiku"),
                "code_commit": commit, "python": platform.python_version()}
        runs = []
        out.mkdir(parents=True, exist_ok=True)
        with (out / "agent-runs.jsonl").open("w") as sink, Client() as client:
            sink.write(json.dumps({"meta": meta}) + "\n")
            for task in tasks:
                record = {"task_id": task["id"], **run(task["question"], backend, client)}
                runs.append(record)
                sink.write(json.dumps(record) + "\n")
                sink.flush()
                print(task["id"], record["status"], record["latency_ms"], "ms", flush=True)
        meta["models_seen"] = sorted({r["model"] for r in runs if r["model"]})
    result = report(args.tasks, runs, meta)
    (out / "agent-eval.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
