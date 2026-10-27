import copy
import json
import unittest
from datetime import date, timedelta
from decimal import localcontext

from financial_metrics.direct import DirectClient
from financial_metrics.domain import Analyst, DEFAULT_DATA
from financial_metrics.evidence import evidence_catalog, render_selection
from financial_metrics.policy import PROFILES
from financial_metrics.presentation import render, render_html
from financial_metrics.tracing import trace_numbers

METRICS = ['operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow', 'capital_expenditures', 'free_cash_flow']


class CashExpansionTests(unittest.TestCase):
    def test_every_cash_card_value_and_filing_source(self):
        with DirectClient() as client:
            for profile in PROFILES.values():
                card = json.loads((DEFAULT_DATA / profile['directory'] / 'cash-expansion-ground-truth.json').read_text())
                for year, expected in card['years'].items():
                    result = client.call('calculate_metrics', {'cik': profile['cik'], 'fiscal_years': [int(year)],
                                                              'metrics': METRICS, 'as_of': expected['filed']})
                    self.assertNotEqual(result['status'], 'refused', result)
                    self.check_rows(result, expected, [expected])
                for expected in card['quarters']:
                    result = client.call('get_quarterly_facts', {'cik': profile['cik'], 'fiscal_year': expected['fiscal_year'],
                                                               'quarter': expected['quarter'], 'metrics': METRICS,
                                                               'as_of': expected['filed']})
                    self.assertNotEqual(result['status'], 'refused', result)
                    self.check_rows(result, expected, expected['inputs'])
                    earlier = (date.fromisoformat(expected['filed']) - timedelta(days=1)).isoformat()
                    early = client.call('get_quarterly_facts', {'cik': profile['cik'], 'fiscal_year': expected['fiscal_year'],
                                                              'quarter': expected['quarter'], 'metrics': ['operating_cash_flow'],
                                                              'as_of': earlier})
                    self.assertNotEqual(early['results'][0]['status'], 'ok')

    def check_rows(self, result, expected, sources):
        for row in result['results']:
            with self.subTest(company=result['context']['company']['ticker'], period=row['period_end'], metric=row['metric']):
                self.assertEqual(row['value'], expected[row['metric']], row)
                if expected[row['metric']] is None:
                    self.assertEqual(row['status'], 'insufficient_data')
                    continue
                self.assertEqual(row['status'], 'ok')
                self.assertEqual((row['period_start'], row['period_end']), (expected['start'], expected['end']))
                actual_sources = {operand['source_url'] for operand in row.get('inputs', [row])}
                self.assertEqual(actual_sources, {s['source_url'] for s in sources})
        answer = render_selection({'evidence': list(evidence_catalog(result, 0))}, evidence_catalog(result, 0))
        self.assertTrue(all(t['traced'] for t in trace_numbers(answer, [result])))
        self.assertIn('cash', render(result, details=True).lower())
        self.assertIn('<', render_html(result))

    def test_statement_reader_excludes_financing_and_noncash_property_additions(self):
        import tempfile
        from pathlib import Path
        from scripts.review_cash_expansion import statement
        rows = [('2025', '2024'), ('Net cash provided by operating activities', '100', '90'),
                ('Purchases of property and equipment', '(20)', '(15)'),
                ('Net cash used in investing activities', '(20)', '(15)'),
                ('Additions to property, plant, and equipment', '(8)', '(7)'),
                ('Net cash used in financing activities', '(5)', '(4)'),
                ('Additions to property, plant, and equipment', '99', '99')]
        html = '<table>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows) + '<tr></tr>' * 20 + '</table>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'filing.html'
            path.write_text(html)
            values, _ = statement(path, 1000000, 2025)
            self.assertEqual(values['capital_expenditures'], 20000000)

    def test_annual_reader_uses_consolidated_total_instead_of_discontinued_subtotal(self):
        import tempfile
        from pathlib import Path
        from scripts.review_cash_flows import read_statement
        rows = [('2025', '2024', '2023'),
                ('Net cash provided by operating activities of continuing operations', '80', '70', '60'),
                ('Net cash provided by operating activities of discontinued operations', '20', '10', '0'),
                ('Net cash provided by operating activities', '100', '80', '60'),
                ('Net cash used in investing activities', '(10)', '(9)', '(8)'),
                ('Net cash used in investing activities of discontinued operations', '(2)', '(1)', '(0)'),
                ('Net cash used in financing activities', '(5)', '(4)', '(3)')]
        html = '<table>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows) + '</table>'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'filing.html'
            path.write_text(html)
            values, _ = read_statement(path, 1)
            self.assertEqual(values[2025], {'operating_cash_flow': '100', 'investing_cash_flow': '-10', 'financing_cash_flow': '-5'})

    def test_missing_previous_ytd_never_returns_current_ytd_as_quarter(self):
        analyst = Analyst()
        units = analyst.facts['facts']['us-gaap']['NetCashProvidedByUsedInOperatingActivities']['units']['USD']
        units[:] = [r for r in units if r['end'] != '2025-12-27']
        row = analyst.get_quarterly_facts(analyst.cik, 2026, 'Q2', ['operating_cash_flow'], '2026-09-21')['results'][0]
        self.assertEqual((row['status'], row['value']), ('insufficient_data', None))

    def test_negative_capex_and_wrong_unit_are_not_used(self):
        for defect in ('negative', 'unit', 'metadata'):
            analyst = Analyst()
            block = analyst.facts['facts']['us-gaap']['PaymentsToAcquirePropertyPlantAndEquipment']['units']
            for r in block['USD']:
                if r.get('start') == '2025-09-28' and r['end'] == '2026-03-28':
                    if defect == 'negative':
                        r['val'] = -1
                    elif defect == 'metadata':
                        r['fy'] = 1900
            if defect == 'unit':
                block['EUR'] = block.pop('USD')
            row = analyst.get_quarterly_facts(analyst.cik, 2026, 'Q2', ['free_cash_flow'], '2026-09-21')['results'][0]
            self.assertEqual((row['status'], row['value']), ('insufficient_data', None), defect)

    def test_subtraction_is_exact_in_a_low_precision_decimal_context(self):
        analyst = Analyst()
        with localcontext() as context:
            context.prec = 2
            row = analyst.get_quarterly_facts(analyst.cik, 2026, 'Q2', ['free_cash_flow'], '2026-09-21')['results'][0]
        self.assertEqual(row['value'], '26731000000')
        self.assertEqual(len(row['inputs']), 4)

    def test_later_revision_of_prior_ytd_requires_current_ytd_reconciliation(self):
        for changed in (False, True):
            analyst = Analyst()
            rows = analyst.facts['facts']['us-gaap']['NetCashProvidedByUsedInOperatingActivities']['units']['USD']
            prior = copy.deepcopy(next(r for r in rows if r.get('start') == '2025-09-28' and r['end'] == '2025-12-27'))
            latest = max((f for f in analyst.filings.values() if f['form'] == '10-Q'), key=lambda f: f['filingDate'])
            prior.update(accn=latest['accessionNumber'], filed=latest['filingDate'], form=latest['form'], fy=2026, fp='Q3')
            if changed:
                prior['val'] = 1
            rows.append(prior)
            row = analyst.get_quarterly_facts(analyst.cik, 2026, 'Q2', ['operating_cash_flow'], '2026-09-21')['results'][0]
            if changed:
                self.assertEqual((row['status'], row.get('reason')), ('insufficient_data', 'prior_ytd_revised_after_current_ytd'))
            else:
                self.assertEqual((row['status'], row['value']), ('ok', '28702000000'))
