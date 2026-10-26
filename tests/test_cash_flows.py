import json
import tempfile
import unittest
from pathlib import Path

from financial_metrics.client import Client
from financial_metrics.policy import CASH_FLOW_TAGS, PROFILES
from financial_metrics.questions import parse_question
from scripts.review_cash_flows import read_statement

ROOT = Path(__file__).resolve().parents[1]


class CashFlowTests(unittest.TestCase):
    def test_all_signed_values_against_independent_filing_cards(self):
        with Client() as client:
            for profile in PROFILES.values():
                card = json.loads((ROOT / 'data' / profile['directory'] / 'cash-flow-ground-truth.json').read_text())
                as_of = client.call('resolve_company', {'ticker': profile['ticker']})['lookup_timestamp'][:10]
                args = {'cik': profile['cik'], 'fiscal_years': sorted(profile['periods']),
                        'metrics': list(CASH_FLOW_TAGS), 'as_of': as_of}
                annual = client.call('get_annual_facts', args)
                self.assertEqual(annual['status'], 'ok', profile['ticker'])
                self.assertEqual(client.call('calculate_metrics', args)['results'], annual['results'])
                for row in annual['results']:
                    with self.subTest(ticker=profile['ticker'], year=row['fiscal_year'], metric=row['metric']):
                        expected = card['years'][str(row['fiscal_year'])]
                        self.assertEqual(row['value'], expected[row['metric']])
                        self.assertEqual(row['unit'], 'USD')
                        self.assertTrue(any(h['accn'] == expected['accession'] and h['value'] == row['value'] for h in row['history']))
                year, quarter = max(profile['quarters'])
                rejected = client.call('get_quarterly_facts', {'cik': profile['cik'], 'fiscal_year': year, 'quarter': quarter,
                                                              'metrics': ['operating_cash_flow'], 'as_of': as_of})
                self.assertEqual((rejected['status'], rejected['code']), ('refused', 'unsupported_metric'))

    def test_cash_flow_questions(self):
        for metric in CASH_FLOW_TAGS:
            parsed = parse_question('Apple ' + metric.replace('_', ' ') + ' 2025')
            self.assertEqual(parsed[2], [metric])

    def test_statement_continuation_and_signed_values(self):
        header = '<tr><td>2025</td><td>2024</td><td>2023</td></tr>'
        html = '<table>' + header + '<tr><td>Net cash from operations</td><td>12</td><td>10</td><td>8</td></tr>'
        html += '<tr><td>Net cash used in investing</td><td>(4)</td><td>(3)</td><td>(2)</td></tr></table>'
        html += '<table>' + header + '<tr><td>Net cash used in financing</td><td>(5)</td><td>(4)</td><td>(3)</td></tr></table>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'filing.html'
            path.write_text(html)
            values, _ = read_statement(path, 1000000)
            self.assertEqual(values[2025], {'operating_cash_flow': '12000000', 'investing_cash_flow': '-4000000',
                                            'financing_cash_flow': '-5000000'})
            path.write_text(html.replace('<td>(5)</td>', '<td>5</td><td>99</td>'))
            with self.assertRaises(ValueError):
                read_statement(path, 1000000)
