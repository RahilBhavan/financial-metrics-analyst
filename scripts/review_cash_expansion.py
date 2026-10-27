"""Independently transcribe visible cash-flow tables, including YTD inputs and cash capex.

Never reads companyfacts or imports the selection/calculation engine. Quarterly source
cards retain both statements used in subtraction; capex is a positive cash outflow.
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.review_filings import Tables, SPECS, fetch, filing_url, header_years, snapshot_filings, to_int
from financial_metrics.policy import PROFILES

METRICS = ('operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow', 'capital_expenditures')
CAPEX = re.compile(r'^(?:purchases|payments|additions|capital expenditures).*(?:property|productive|equipment|capitalized|software)', re.I)


def statement(path, scale, year, continuing_capex=False):
    parser = Tables()
    parser.feed(Path(path).read_text(encoding='utf-8', errors='replace'))
    accumulated, expected_years = {}, None
    for table in parser.tables:
        found, parts = {}, {}
        for row in table:
            cells = []
            for cell in row:
                if cell == ')' and cells:
                    cells[-1] += ')'
                elif cell and cell != '$':
                    cells.append(cell)
            if not cells:
                continue
            label = cells[0].lower().replace('\xa0', ' ').replace('(', '').replace(')', '')
            partial = 'continuing operations' in label or 'discontinued operations' in label
            metric = None
            for kind in ('operating', 'investing', 'financing'):
                activity = r'(?:operating activities|operations)' if kind == 'operating' else kind + r'(?: activities)?'
                if re.search(r'^(?:net )?cash (?:generated|provided|used|flows|from).*' + activity + (r'(?: of (?:continuing|discontinued) operations)?[:.]?$' if partial else r'[:.]?$'), label):
                    metric = kind + '_cash_flow'
            if CAPEX.search(label) and not re.search(r'accrued|not paid|non.cash|principal|proceeds|held for sale', label):
                metric = 'capital_expenditures'
            if metric:
                numbers = [c for c in cells[1:] if re.fullmatch(r'\(?-?[\d,]+\)?|[—–-]', c)]
                if metric == 'capital_expenditures' and ('investing_cash_flow' in found or 'financing_cash_flow' in found):
                    continue  # Financing and supplemental additions are outside the investing cash-capex tag.
                if numbers and partial:
                    parts.setdefault(metric, []).append((cells[0], numbers))
                    continue
                if numbers:
                    if metric in found and metric == 'capital_expenditures' and continuing_capex:
                        continue  # AMD separately presents discontinued-operation capex after continuing operations.
                    if metric in found:
                        raise ValueError('ambiguous cash statement row: ' + metric + ' in ' + str(path))
                    found[metric] = (cells[0], numbers)
        if continuing_capex:
            for metric, rows in parts.items():
                if metric not in found:
                    if len({len(numbers) for _, numbers in rows}) != 1:
                        raise ValueError('Inconsistent continuing/discontinued columns')
                    sums = [sum(to_int(numbers[i], 1) for _, numbers in rows) for i in range(len(rows[0][1]))]
                    found[metric] = (' + '.join(label for label, _ in rows), [str(n) for n in sums])
        if (len(table) < 20 and not accumulated) or not found:
            continue
        try:
            years = header_years(table)
        except ValueError:
            continue
        if len(years) == 4 and years[:2] == years[2:]:
            # Microsoft presents three-month columns first, then year-to-date columns.
            years = years[2:]
            found = {m: (label, numbers[2:]) for m, (label, numbers) in found.items()}
        if expected_years != years:
            accumulated, expected_years = {}, years
        accumulated.update(found)
        found = dict(accumulated)
        if not set(METRICS[:3]) <= set(found):
            continue
        if years.count(year) != 1 or any(len(numbers) != len(years) for _, numbers in found.values()):
            raise ValueError('ambiguous cash statement columns in ' + str(path))
        i = years.index(year)
        values = {m: to_int(numbers[i], scale) for m, (_, numbers) in found.items()}
        values['capital_expenditures'] = abs(values['capital_expenditures']) if 'capital_expenditures' in values else None
        return values, {m: label for m, (label, _) in found.items()}
    raise ValueError('No complete cash statement in ' + str(path))


def read(profile, filing, year, cache, user_agent):
    values, labels = statement(fetch(cache, user_agent, int(profile['cik']), filing), SPECS[profile['ticker']]['scale'], year, continuing_capex=profile['ticker'] == 'AMD')
    return {'accession': filing['accessionNumber'], 'filed': filing['filingDate'], 'end': filing['reportDate'],
            'source_url': filing_url(int(profile['cik']), filing), 'labels': labels,
            **{k: str(v) if v is not None else None for k, v in values.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--user-agent', required=True)
    parser.add_argument('--ticker', action='append')
    args = parser.parse_args()
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    for profile in PROFILES.values():
        if args.ticker and profile['ticker'] not in args.ticker:
            continue
        directory = ROOT / 'data' / profile['directory']
        _, filings = snapshot_filings(profile['directory'])
        years = {}
        for year, (start, end) in profile['periods'].items():
            # Original annual source supplies all three years when possible.
            candidates = sorted((f for f in filings if f['form'] == '10-K' and end <= f['reportDate']), key=lambda f: f['filingDate'])
            filing = candidates[0]
            row = read(profile, filing, int(end[:4]), args.cache, args.user_agent)
            years[str(year)] = {'start': start, **row}
            years[str(year)]['free_cash_flow'] = (str(int(row['operating_cash_flow']) - int(row['capital_expenditures']))
                                                     if row['capital_expenditures'] is not None else None)
        quarters = []
        for q in json.loads((directory / 'ground-truth.json').read_text())['reviewed_quarters']:
            filing = next(f for f in filings if f['accessionNumber'] == q['filing_accession'])
            current = read(profile, filing, int(q['end'][:4]), args.cache, args.user_agent)
            inputs = [current]
            previous_end = (date.fromisoformat(q['start']) - timedelta(days=1)).isoformat()
            if q['quarter'] != 'Q1':
                previous = min((f for f in filings if f['form'] == '10-Q' and f['reportDate'] == previous_end), key=lambda f: f['filingDate'])
                inputs.append(read(profile, previous, int(previous['reportDate'][:4]), args.cache, args.user_agent))
            values = {m: (int(current[m]) - (int(inputs[1][m]) if len(inputs) == 2 else 0))
                      if all(row[m] is not None for row in inputs) else None for m in METRICS}
            values['free_cash_flow'] = (values['operating_cash_flow'] - values['capital_expenditures']
                                    if values['capital_expenditures'] is not None else None)
            quarters.append({**{k: q[k] for k in ('fiscal_year', 'quarter', 'start', 'end', 'filed')},
                             'inputs': inputs, **{k: str(v) if v is not None else None for k, v in values.items()}})
        card = {'verification': 'Visible SEC cash-flow statements only; no companyfacts or runtime calculation engine read.',
                'ticker': profile['ticker'], 'unit': 'USD', 'years': years, 'quarters': quarters}
        (directory / 'cash-expansion-ground-truth.json').write_text(json.dumps(card, indent=2) + '\n')
        print(profile['ticker'], len(years), 'annual statements and', len(quarters), 'quarters checked', flush=True)


if __name__ == '__main__':
    main()
