"""Transcribe reviewed values from the filings' visible income statements, never from companyfacts.

For each issuer this downloads the primary filing documents named in the issuer's committed
submissions snapshot, reads the Consolidated Statements of Operations table, and writes the
ground-truth card that the evaluation compares the server against. It never reads
companyfacts.json, so the card stays independent of the extraction under test.

    python3 -B scripts/review_filings.py --cache ~/scratch/filings --user-agent 'Name email' --ticker COIN
    python3 -B scripts/review_filings.py --cache ~/scratch/filings --user-agent 'Name email' --all

Operator tool, not part of the server. Requests are throttled and use the fixed SEC archive path.
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
METRICS = ("revenue", "gross_profit", "operating_income", "net_income")
NUMBER = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$|^[—–-]$")
YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
OPERATING = (r"(?:operating (?:income|loss|\(loss\) income|income \(loss\))"
             r"|(?:income|loss|\(loss\) income|income \(loss\)) from operations)")
COMMON = {
    "revenue": [r"total (?:net )?revenues?", r"total net sales", r"(?:net )?revenues?", r"net sales"],
    "gross_profit": [r"gross (?:profit|margin)"],
    "operating_income": [OPERATING],
    "net_income": [r"net (?:income|loss|\(loss\) income|income \(loss\))"],
}
# directory, fiscal-year-end month (a quarter ending after it belongs to the next fiscal year),
# statement scale and the metrics the issuer's statements do not report.
SPECS = {
    "AAPL": dict(directory=".", fye=9, scale=10**6, snapshot_date=None),
    "MSFT": dict(directory="msft", fye=6, scale=10**6),
    "NVDA": dict(directory="nvda", fye=1, scale=10**6),
    "COIN": dict(directory="coin", fye=12, scale=10**3, missing=("gross_profit",)),
    "MSTR": dict(directory="mstr", fye=12, scale=10**3),
    "HOOD": dict(directory="hood", fye=12, scale=10**6, missing=("gross_profit", "operating_income"),
                 net_income=[r"net income(?: \(loss\))? attributable to robinhood", r"net income(?: \(loss\))?"]),
    "XYZ": dict(directory="xyz", fye=12, scale=10**3,
                net_income=[r"net (?:income|loss|\(loss\) income|income \(loss\)) attributable to common stockholders"]),
    # The SEC companyfacts API (re-fetched 2026-10-25) holds no facts for the 10-Qs filed on 2026-07-28 (PYPL)
    # and 2026-07-29 (V), so those periods cannot be served from a snapshot and are not reviewed.
    "PYPL": dict(directory="pypl", fye=12, scale=10**6, missing=("gross_profit",), skip_reports=("2026-06-30",)),
    "V": dict(directory="v", fye=9, scale=10**6, missing=("gross_profit",), skip_reports=("2026-06-30",)),
    "TSLA": dict(directory="tsla", fye=12, scale=10**6,
                 net_income=[r"net income(?: \(loss\))? attributable to common stockholders"]),
}
SPECS.update({"AMD": dict(directory="amd", fye=12, scale=10**6),
              "INTC": dict(directory="intc", fye=12, scale=10**6,
                           net_income=[r"net income(?: \(loss\))? attributable to intel"])})
NEW_ISSUERS = ("AMD", "INTC", "COIN", "MSTR", "HOOD", "XYZ", "PYPL", "V", "TSLA")


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def clean_label(text):
    text = re.sub(r"\s*\(\w{1,2}\)$", "", text.strip().rstrip(":"))
    return re.sub(r"\s+", " ", text).lower()


def to_int(cell, scale):
    if cell in "—–-":
        return 0
    negative = cell.startswith("(")
    digits = cell.strip("()").replace(",", "")
    if "." in digits:
        raise ValueError("fractional statement amount " + cell)
    return (-1 if negative else 1) * int(digits) * scale


def statement_rows(table, spec):
    """Map each metric to (label, numeric cells), using the first pattern that finds a numeric row."""
    rows = []
    for row in table:
        cells = []
        for cell in row:
            if cell == ")" and cells:
                cells[-1] += ")"  # some filings put the closing bracket of a negative amount in its own cell
            elif cell and cell != "$":
                cells.append(cell)
        numbers = [c for c in cells[1:] if NUMBER.match(c)]
        if cells and numbers and not NUMBER.match(cells[0]):
            rows.append((clean_label(cells[0]), numbers))
    found = {}
    for metric in METRICS:
        if metric in spec.get("missing", ()):
            continue
        for pattern in spec.get(metric, COMMON[metric]):
            hit = next(((label, numbers) for label, numbers in rows if re.fullmatch(pattern, label)), None)
            if hit:
                found[metric] = hit
                break
    return found


def find_statement(path, spec, min_years=2):
    parser = Tables()
    parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    for table in parser.tables:
        text = " ".join(" ".join(row) for row in table).lower()
        if "before" not in text or "tax" not in text:
            continue
        found = statement_rows(table, spec)
        try:
            enough = len(header_years(table)) >= min_years
        except ValueError:
            enough = False
        if (enough and len(found) == len(METRICS) - len(spec.get("missing", ()))
                and all(not any("." in cell for cell in cells) for _, cells in found.values())):
            return table, found
    raise ValueError("no income statement found in " + str(path))


def header_years(table):
    for row in table[:12]:
        years = [YEAR.search(c).group(1) for c in row if c and YEAR.search(c) and len(c) < 40]
        if len(years) >= 2:
            return [int(y) for y in years]
    raise ValueError("no year header")


def column_values(table, found, spec, year, annual):
    years = header_years(table)
    if not annual and len(years) >= 4:
        years = years[:len(years) // 2]  # three-month columns come before the year-to-date columns
    if years.count(year) != 1:
        raise ValueError("ambiguous header years " + str(years))
    index = years.index(year)
    out = {}
    for metric, (_, numbers) in found.items():
        if len(numbers) < len(years):
            raise ValueError(metric + ": fewer numbers than columns")
        out[metric] = str(to_int(numbers[index], spec["scale"]))
    for metric in spec.get("missing", ()):
        out[metric] = None
    return out


def snapshot_filings(directory):
    recent = json.loads((DATA / directory / "submissions.json").read_text())["filings"]["recent"]
    cik = int(json.loads((DATA / directory / "submissions.json").read_text())["cik"])
    keys = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
    return cik, [dict(zip(keys, values)) for values in zip(*(recent[k] for k in keys))]


def fetch(cache, user_agent, cik, filing):
    path = Path(cache) / (filing["accessionNumber"] + "-" + filing["primaryDocument"])
    if not path.exists():
        url = filing_url(cik, filing)
        time.sleep(0.5)
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=120) as response:
            path.write_bytes(response.read())
    return path


def filing_url(cik, filing):
    return ("https://www.sec.gov/Archives/edgar/data/" + str(cik) + "/" + filing["accessionNumber"].replace("-", "")
            + "/" + filing["primaryDocument"])


def fiscal_year(end, fye):
    return end.year + (1 if end.month > fye else 0)


def review_quarters(ticker, spec, cache, user_agent, count=6):
    cik, filings = snapshot_filings(spec["directory"])
    periodic = sorted((f for f in filings if f["form"] in ("10-K", "10-Q")), key=lambda f: f["reportDate"])
    quarters = [f for f in periodic if f["form"] == "10-Q" and f["reportDate"] not in spec.get("skip_reports", ())][-count:]
    out = []
    for filing in quarters:
        end = date.fromisoformat(filing["reportDate"])
        previous = max(f["reportDate"] for f in periodic if f["reportDate"] < filing["reportDate"])
        start = date.fromisoformat(previous) + timedelta(days=1)
        since_year_end = [f for f in periodic if previous >= f["reportDate"] and f["form"] == "10-K"]
        last_year_end = max(f["reportDate"] for f in since_year_end)
        number = sum(1 for f in periodic if f["form"] == "10-Q" and last_year_end < f["reportDate"] <= filing["reportDate"])
        table, found = find_statement(fetch(cache, user_agent, cik, filing), spec)
        values = column_values(table, found, spec, end.year, annual=False)
        out.append({"fiscal_year": fiscal_year(end, spec["fye"]), "quarter": "Q" + str(number),
                    "start": start.isoformat(), "end": end.isoformat(), "filing_accession": filing["accessionNumber"],
                    "filed": filing["filingDate"], "filing_url": filing_url(cik, filing), "form": "10-Q", **values})
    return out


def pick_annual(filings, end_prefix):
    candidates = [f for f in filings if f["form"] == "10-K" and f["reportDate"].startswith(end_prefix)]
    return sorted(candidates, key=lambda f: f["filingDate"])[0]


def review_annual(ticker, spec, cache, user_agent):
    cik, filings = snapshot_filings(spec["directory"])
    annual = sorted((f for f in filings if f["form"] in ("10-K", "10-K/A")), key=lambda f: f["reportDate"])
    ends = sorted({f["reportDate"] for f in annual})
    latest, prior = ends[-1], ends[-2]
    ten_k = {end: min((f for f in annual if f["reportDate"] == end and f["form"] == "10-K"), key=lambda f: f["filingDate"]) for end in ends}
    amendments = {end: [f for f in annual if f["reportDate"] == end and f["form"] == "10-K/A" and f["primaryDocument"] == ten_k[end]["primaryDocument"]] for end in ends}
    for end in amendments:
        financial_amendments = []
        for filing in amendments[end]:
            try:
                find_statement(fetch(cache, user_agent, cik, filing), spec, min_years=3)
            except ValueError:
                continue  # A Part III-only amendment does not reissue the financial statements.
            financial_amendments.append(filing)
        amendments[end] = financial_amendments
    newest, older = ten_k[latest], ten_k[prior]
    result = {"years": {}, "newest": newest, "older": older, "amendments": amendments[latest]}
    for filing, key in ((newest, "newest"), (older, "older")):
        table, found = find_statement(fetch(cache, user_agent, cik, filing), spec, min_years=3)
        years = sorted(set(header_years(table)))
        result[key + "_values"] = {y: column_values(table, found, spec, y, annual=True) for y in years}
    return cik, result


def build_card(ticker, spec, cache, user_agent, profile):
    cik, review = review_annual(ticker, spec, cache, user_agent)
    newest, older = review["newest"], review["older"]
    years = {}
    for year, (start, end) in profile["periods"].items():
        values = review["newest_values"][year]
        latest = review["amendments"][-1] if review["amendments"] else newest
        entry = {"start": start, "end": end, "days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1,
                 "accession": latest["accessionNumber"], "filed": latest["filingDate"], "form": latest["form"],
                 "filing_url": filing_url(cik, latest), **{m: values[m] for m in METRICS}}
        if review["amendments"] and year == max(profile["periods"]):  # the year the amended filing reports as its own
            entry["original_accession"] = newest["accessionNumber"]
        years[str(year)] = entry
    (support_year, (start, end)), = profile["support_periods"].items()
    older_values = review["older_values"]
    # The reviewed FY(n-1) and FY(n-2) amounts in the older filing must agree with the newest filing where they overlap.
    overlap = {y: (older_values[y]["revenue"], review["newest_values"][y]["revenue"]) for y in older_values if y in review["newest_values"]}
    pit_years = {str(y): {"start": profile["periods"][y][0], "end": profile["periods"][y][1], **{m: older_values[y][m] for m in METRICS}}
                 for y in sorted(older_values) if y in profile["periods"]}
    as_of = (date.fromisoformat(newest["filingDate"]) - timedelta(days=1)).isoformat()
    return {
        "evidence_kind": "independently_checked_SEC_filing_values",
        "issuer": profile["name"], "cik": profile["cik"],
        "verification": ("Transcribed from the visible Consolidated Statements of Operations in each cited filing document by "
                         "scripts/review_filings.py (scale " + ("thousands" if spec["scale"] == 1000 else "millions")
                         + " of USD, converted to exact USD). companyfacts is not read. Metrics the statements do not report are null."),
        "statement_labels": {m: find_statement(fetch(cache, user_agent, cik, newest), spec, min_years=3)[1].get(m, (None,))[0] for m in METRICS},
        "years": years,
        "supporting_revenue": {"fiscal_year": support_year, "start": start, "end": end, "value": older_values[support_year]["revenue"],
                               "source_url": filing_url(cik, older),
                               "source_section": "Consolidated Statements of Operations, fiscal year " + str(support_year) + " revenue column",
                               "latest_matching_accession": older["accessionNumber"]},
        "point_in_time": {"as_of": as_of, "accession": older["accessionNumber"], "filed": older["filingDate"],
                          "form": older["form"], "filing_url": filing_url(cik, older), "years": pit_years,
                          "overlap_revenue_older_vs_newest": overlap},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--ticker", action="append")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if "@" not in args.user_agent:
        sys.exit("Use a User-Agent with real contact information.")
    sys.path.insert(0, str(ROOT))
    from financial_metrics.policy import PROFILES
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    tickers = list(SPECS) if args.all else args.ticker
    profiles = {p["ticker"]: p for p in PROFILES.values()}
    for ticker in tickers:
        spec, directory = SPECS[ticker], DATA / SPECS[ticker]["directory"]
        card_path = directory / "ground-truth.json"
        if ticker in NEW_ISSUERS:
            card = build_card(ticker, spec, args.cache, args.user_agent, profiles[ticker])
        else:
            card = json.loads(card_path.read_text())
        card.pop("reviewed_quarter", None)
        card["reviewed_quarters"] = review_quarters(ticker, spec, args.cache, args.user_agent)
        card_path.write_text(json.dumps(card, indent=2) + "\n")
        print(ticker, "quarters:", [(q["fiscal_year"], q["quarter"], q["revenue"]) for q in card["reviewed_quarters"]])


if __name__ == "__main__":
    main()
