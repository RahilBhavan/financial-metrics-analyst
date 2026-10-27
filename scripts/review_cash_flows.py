"""Read annual cash-flow statements independently of companyfacts; write reviewed source cards."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.review_filings import Tables, SPECS, fetch, filing_url, header_years, snapshot_filings, to_int
from financial_metrics.policy import CASH_FLOW_TAGS, PROFILES


def read_statement(path, scale):
    parser = Tables()
    parser.feed(Path(path).read_text(encoding='utf-8', errors='replace'))
    accumulated = {}
    expected_years = None
    for table in parser.tables:
        found = {}
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
            if 'continuing operations' in label or 'discontinued operations' in label:
                continue
            for kind in ('operating', 'investing', 'financing'):
                activity = r'(?:operating activities|operations)' if kind == 'operating' else kind + r'(?: activities)?'
                if re.search(r'^(?:net )?cash (?:generated|provided|used|flows|from).*' + activity + r'[:.]?$', label):
                    numbers = [c for c in cells[1:] if re.fullmatch(r'\(?-?[\d,]+\)?|[—–-]', c)]
                    if numbers:
                        found[kind + '_cash_flow'] = (cells[0], numbers)
        if found:
            try:
                years = header_years(table)
            except ValueError:
                continue
            if len(years) != 3 or len(set(years)) != 3:
                continue
            if any(len(numbers) != 3 for _, numbers in found.values()):
                raise ValueError('ambiguous cash-flow columns in ' + str(path))
            if expected_years != years:
                accumulated = {}
                expected_years = years
            for metric, row in found.items():
                if metric in accumulated and accumulated[metric] != row:
                    raise ValueError('conflicting statement rows: ' + metric)
                accumulated[metric] = row
            if set(accumulated) == set(CASH_FLOW_TAGS):
                return {year: {m: str(to_int(numbers[i], scale)) for m, (_, numbers) in accumulated.items()}
                        for i, year in enumerate(years)}, {m: label for m, (label, _) in accumulated.items()}
    raise ValueError('No three-year cash-flow statement in ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--user-agent', required=True)
    args = parser.parse_args()
    Path(args.cache).mkdir(parents=True, exist_ok=True)
    for profile in PROFILES.values():
        spec = SPECS[profile['ticker']]
        cik, filings = snapshot_filings(profile['directory'])
        annual = sorted((f for f in filings if f['form'] == '10-K'), key=lambda f: f['filingDate'], reverse=True)
        remaining, years = set(profile['periods']), {}
        for filing in annual:
            if not remaining:
                break
            values, labels = read_statement(fetch(args.cache, args.user_agent, cik, filing), spec['scale'])
            for year in sorted(remaining & set(values)):
                start, end = profile['periods'][year]
                years[str(year)] = {'start': start, 'end': end, 'accession': filing['accessionNumber'],
                                    'filed': filing['filingDate'], 'source_url': filing_url(cik, filing),
                                    'labels': labels, **values[year]}
                remaining.remove(year)
        if remaining:
            raise ValueError('Missing years: ' + str(remaining))
        card = {'verification': 'Visible annual cash-flow statement; scripts/review_cash_flows.py never reads companyfacts.',
                'ticker': profile['ticker'], 'cik': profile['cik'], 'unit': 'USD', 'years': years}
        path = ROOT / 'data' / profile['directory'] / 'cash-flow-ground-truth.json'
        path.write_text(json.dumps(card, indent=2) + '\n')
        print(profile['ticker'], len(years), 'years reviewed', flush=True)


if __name__ == '__main__':
    main()
