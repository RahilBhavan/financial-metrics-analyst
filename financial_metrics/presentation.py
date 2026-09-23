"""Compact tables and local HTML with native expandable evidence sections."""

from decimal import Decimal, localcontext
from html import escape

LABELS = {"revenue": "Revenue", "gross_profit": "Gross profit", "operating_income": "Operating income",
          "net_income": "Net income", "gross_margin": "Gross margin",
          "operating_margin": "Operating margin", "revenue_growth": "Revenue growth"}


def display(row):
    if row["status"] != "ok":
        return "Unavailable"
    if row["unit"] == "percent":
        return row["display_value"] + "%"
    with localcontext() as context:
        context.prec = 60
        amount = format(Decimal(row["value"]) / Decimal(1000000), ",f")
        return amount.rstrip("0").rstrip(".") if "." in amount else amount


def table_data(result):
    years = sorted({r["fiscal_year"] for r in result["results"]})
    metrics = list(dict.fromkeys(r["metric"] for r in result["results"]))
    lookup = {(r["fiscal_year"], r["metric"]): r for r in result["results"]}
    notes, references = [], {}
    for row in result["results"]:
        messages = row.get("warnings", []) if row["status"] == "ok" else [row["reason"]]
        for message in messages:
            notes.append((row, message))
            references.setdefault((row["fiscal_year"], row["metric"]), []).append(len(notes))
    return years, metrics, lookup, notes, references


def detail_lines(row):
    lines = []
    if row["status"] != "ok":
        lines.append("Unavailable: " + row["reason"])
        for blocker in row.get("blocking_candidates", []):
            lines.append("Blocked by " + blocker["accn"] + " filed " + str(blocker["filed"]) + ": " + blocker["reason"])
    if row.get("formula"):
        lines.append("Formula: " + row["formula"])
        lines.append("Exact percentage: " + row["exact_fraction"]["numerator"] + "/" + row["exact_fraction"]["denominator"])
    for source in row.get("inputs", [row]):
        if source["status"] != "ok":
            if source is not row:
                lines.extend(detail_lines(source))
            continue
        lines.append(source["metric"] + ": " + source["value"] + " USD; " + source["period_start"] + " to " + source["period_end"])
        lines.append(source["tag"] + "; " + source["form"] + "; filed " + source["filed"] + "; " + source["accn"])
        lines.append(source["source_url"])
        if source.get("revision_candidate"):
            lines.append("Revision history: " + "; ".join(f["filed"] + " " + f["value"] + " USD" for f in source["history"]))
    return lines


def render(result, details=False):
    if result["status"] in ("refused", "needs_clarification"):
        prefix = "Clarification needed" if result["status"] == "needs_clarification" else "Refused"
        choices = " Options: " + "; ".join(result["choices"]) if "choices" in result else ""
        return prefix + " (" + result["code"] + "): " + result["message"] + choices
    context = result["context"]
    company = context["company"]
    years, metrics, lookup, notes, references = table_data(result)
    lines = [company["name"] + " | " + company["ticker"] + " | CIK " + company["cik"],
             "As of " + context["as_of"] + "; SEC snapshot " + context["snapshot_captured_at"],
             "Amounts: USD millions. Percentages: 2 decimal places. FY labels use each issuer's fiscal calendar.", ""]
    cells = [["Metric"] + ["FY" + str(y) for y in years]]
    for metric in metrics:
        cells.append([LABELS[metric]] + [display(lookup[y, metric]) + "".join(" [" + str(n) + "]" for n in references.get((y, metric), [])) for y in years])
    widths = [max(len(row[i]) for row in cells) for i in range(len(cells[0]))]
    for i, row in enumerate(cells):
        lines.append(" | ".join(cell.ljust(widths[j]) for j, cell in enumerate(row)))
        if i == 0:
            lines.append("-+-".join("-" * width for width in widths))
    for y in years:
        row = lookup[y, metrics[0]]
        lines.append("FY" + str(y) + ": " + row["period_start"] + " to " + row["period_end"])
    for warning in context["warnings"]:
        lines.append("Snapshot warning: " + warning)
    for n, (row, message) in enumerate(notes, 1):
        lines.append("[" + str(n) + "] FY" + str(row["fiscal_year"]) + " " + LABELS[row["metric"]] + ": " + message)
    sources = sorted({source["source_url"] for row in result["results"] for source in row.get("inputs", [row]) if source["status"] == "ok"})
    lines.extend(["", "Source filings:"] + sources)
    if details:
        for row in result["results"]:
            lines.extend(["", "FY" + str(row["fiscal_year"]) + " " + LABELS[row["metric"]]] + detail_lines(row))
    else:
        lines.append("Use --details for formulas and provenance, --json for full audit data, or --html for expandable evidence.")
    return "\n".join(line.rstrip() for line in lines)


def render_html(result):
    if result["status"] not in ("ok", "partial"):
        return "<!doctype html><html lang='en'><meta charset='utf-8'><title>Analysis response</title><body><p>" + escape(render(result)) + "</p></body></html>"
    years, metrics, lookup, notes, refs = table_data(result)
    context = result["context"]
    company = context["company"]
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
             "<title>" + escape(company["name"]) + " financial metrics</title><style>",
             "body{font:16px/1.55 system-ui,sans-serif;color:#152538;background:#f4f7fa;margin:0;padding:32px}main{max-width:1100px;margin:auto}h1{margin-bottom:8px}table{border-collapse:collapse;width:100%;background:white}th,td{padding:14px;border-bottom:1px solid #d5dfe8;text-align:right}th:first-child{text-align:left}caption{text-align:left;margin:16px 0}.table-wrap{overflow:auto}details{background:white;border:1px solid #d5dfe8;padding:14px;margin:12px 0}summary{cursor:pointer;font-weight:600}a{color:#125c9e}.warning{color:#6c4200}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 ui-monospace,monospace}.meta{color:#405365}li{margin:8px 0}:focus-visible{outline:3px solid #156fd0;outline-offset:3px}@media(max-width:600px){body{padding:16px}th,td{padding:10px}}",
             "</style></head><body><main><h1>" + escape(company["name"]) + "</h1>",
             "<p class='meta'>" + escape(company["ticker"] + " · CIK " + company["cik"] + " · As of " + context["as_of"]) + "</p>",
             "<p class='meta'>SEC snapshot " + escape(context["snapshot_captured_at"]) + ". Issuer-specific reviewed fiscal periods.</p>"]
    for warning in context["warnings"]:
        parts.append("<p class='warning'>" + escape(warning) + "</p>")
    parts.append("<div class='table-wrap'><table><caption>Amounts in USD millions. Percentages rounded to two decimal places.</caption><thead><tr><th scope='col'>Metric</th>")
    parts.extend("<th scope='col'>FY" + str(y) + "</th>" for y in years)
    parts.append("</tr></thead><tbody>")
    for metric in metrics:
        parts.append("<tr><th scope='row'>" + escape(LABELS[metric]) + "</th>")
        for y in years:
            links = "".join(" <a class='warning' href='#note-" + str(n) + "' aria-label='Warning " + str(n) + "'>[" + str(n) + "]</a>" for n in refs.get((y, metric), []))
            parts.append("<td>" + escape(display(lookup[y, metric])) + links + "</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    for y in years:
        row = lookup[y, metrics[0]]
        parts.append("<p class='meta'>FY" + str(y) + ": " + row["period_start"] + " to " + row["period_end"] + "</p>")
    if notes:
        parts.append("<h2>Warnings and comparison notes</h2><ol>")
        for n, (row, message) in enumerate(notes, 1):
            parts.append("<li id='note-" + str(n) + "'>FY" + str(row["fiscal_year"]) + " " + escape(LABELS[row["metric"]] + ": " + message) + "</li>")
        parts.append("</ol>")
    parts.append("<h2>Explore the evidence</h2><p>Expand a result to see its formula, full dollar amounts, filing references, and audit record.</p>")
    import json
    for row in result["results"]:
        parts.append("<details><summary>FY" + str(row["fiscal_year"]) + " · " + escape(LABELS[row["metric"]]) + " · " + escape(display(row)) + "</summary>")
        for line in detail_lines(row):
            if line.startswith("https://www.sec.gov/Archives/edgar/data/"):
                parts.append("<p><a href='" + escape(line, quote=True) + "' rel='noreferrer'>Open source filing</a></p>")
            else:
                parts.append("<p>" + escape(line) + "</p>")
        parts.append("<details><summary>Full structured audit record</summary><pre>" + escape(json.dumps(row, indent=2)) + "</pre></details></details>")
    parts.append("</main></body></html>")
    return "\n".join(parts)
