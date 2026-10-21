"""Render reports/agent-runs.jsonl and reports/agent-eval.json as a static, script-free transcript viewer.

    python3 -B scripts/render_agent_transcripts.py   # writes reports/agent-transcripts.html
"""

import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ("body{font:16px/1.55 system-ui,sans-serif;color:#152538;background:#f4f7fa;margin:0;padding:32px}main{max-width:1100px;margin:auto}"
         "table{border-collapse:collapse;width:100%;background:white}th,td{padding:8px 12px;border-bottom:1px solid #d5dfe8;text-align:left;"
         "vertical-align:top}td.n{text-align:right}details{background:white;border:1px solid #d5dfe8;padding:14px;margin:12px 0}"
         "summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 ui-monospace,monospace}"
         ".meta{color:#405365}.fail{color:#a1260d}.ok{color:#1d6b36}blockquote{margin:8px 0;padding:8px 14px;border-left:3px solid #125c9e;"
         "background:#f8fafc}:focus-visible{outline:3px solid #156fd0;outline-offset:3px}@media(max-width:600px){body{padding:16px}}")


def mark(value):
    if value is None:
        return "<span class='meta'>n/a</span>"
    return "<span class='ok'>yes</span>" if value else "<span class='fail'>no</span>"


def rate(item):
    return str(item["passed"]) + " / " + str(item["total"]) + (" (" + format(item["rate"] * 100, ".1f") + "%)" if item["rate"] is not None else "")


def render(runs_path, eval_path):
    lines = Path(runs_path).read_text().splitlines()
    runs = [json.loads(line) for line in lines[1:]]
    report = json.loads(Path(eval_path).read_text())
    meta, summary = report["meta"], report["summary"]
    scores = {s["id"]: s for s in report["scores"]}
    tasks = {t["id"]: t for t in json.loads((ROOT / meta["tasks_file"]).read_text())["tasks"]}
    rows = [("Tool selection (in scope)", rate(summary["tool_selection"])), ("Arguments (in scope)", rate(summary["arguments"])),
            ("Expected numbers quoted (in scope)", rate(summary["answer_numbers"])),
            ("Numbers traced, delivered answers", rate(summary["numbers_traced_delivered"])),
            ("Numbers traced, first drafts", rate(summary["numbers_traced_first_draft"])),
            ("Answers withheld by the gate", str(summary["answers_withheld_untraced"])),
            ("Out-of-scope refusals", rate(summary["refusal_out_of_scope"])),
            ("False refusals (in scope)", str(summary["false_refusals_in_scope"])),
            ("Latency p50 / p90 (ms)", str(summary["latency_ms"]["p50"]) + " / " + str(summary["latency_ms"]["p90"])),
            ("Tokens per task (mean)", str(summary["tokens_per_task_mean"])),
            ("Cost per task (mean, USD)", str(summary["cost_usd_per_task_mean"]))]
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
             "<title>Treasury agent transcripts</title><style>" + STYLE + "</style></head><body><main>",
             "<h1>Treasury agent: 50 frozen tasks</h1>",
             "<p class='meta'>Backend " + escape(meta["backend"]) + ", model " + escape(", ".join(meta.get("models_seen", []))) + ", code "
             + escape(meta.get("code_commit", "")[:7]) + ", run " + escape(meta.get("started", "")) + ". Tasks sha256 "
             + escape(meta["tasks_sha256"][:12]) + ".</p><table><tbody>"]
    parts += ["<tr><th scope='row'>" + escape(k) + "</th><td class='n'>" + escape(v) + "</td></tr>" for k, v in rows]
    parts.append("</tbody></table>")
    for run in runs:
        task, score = tasks[run["task_id"]], scores[run["task_id"]]
        verdict = score["refusal_correct"] if not task["in_scope"] else (score["tool_correct"] and score["arguments_correct"] and score["answer_numbers_correct"])
        parts.append("<details><summary>" + escape(task["id"]) + " " + mark(verdict) + " " + escape(task["question"]) + "</summary>")
        parts.append("<p class='meta'>" + escape(run["status"]) + ", " + str(run["latency_ms"]) + " ms, " + str(score["tokens"]) + " tokens"
                     + (", $" + format(run["cost_usd"], ".5f") if run.get("cost_usd") is not None else "") + "</p>")
        if task["in_scope"]:
            parts.append("<p>Tool " + mark(score["tool_correct"]) + " · arguments " + mark(score["arguments_correct"])
                         + " · expected numbers " + mark(score["answer_numbers_correct"]) + "</p>")
        for call in run["tool_calls"]:
            parts.append("<pre>" + escape(call["name"] + " " + json.dumps(call["arguments"]) + " -> " + str(call["status"])) + "</pre>")
        if run.get("refusal") is not None:
            parts.append("<blockquote>Refused: " + escape(run["refusal"]) + "</blockquote>")
        elif run.get("answer"):
            parts.append("<blockquote>" + escape(run["answer"]) + "</blockquote>")
        for i, draft in enumerate(run["drafts"][:-1] if run["status"] == "answered" else run["drafts"]):
            bad = [t["text"] for t in draft["traces"] if not t["traced"]]
            parts.append("<p class='fail'>Draft " + str(i + 1) + " rejected; untraced: " + escape(", ".join(bad)) + "</p><pre>" + escape(draft["text"]) + "</pre>")
        if run["traces"]:
            parts.append("<table><thead><tr><th>Number in answer</th><th>Traced to</th><th>Tool value</th></tr></thead><tbody>")
            parts += ["<tr><td>" + escape(t["text"]) + "</td><td>" + escape(str(t["source"])) + "</td><td>" + escape(str(t["tool_value"] or ""))
                      + "</td></tr>" for t in run["traces"]]
            parts.append("</tbody></table>")
        parts.append("</details>")
    parts.append("</main></body></html>\n")
    return "".join(parts)


if __name__ == "__main__":
    reports = ROOT / "reports"
    (reports / "agent-transcripts.html").write_text(render(reports / "agent-runs.jsonl", reports / "agent-eval.json"))
    sys.exit(0)
