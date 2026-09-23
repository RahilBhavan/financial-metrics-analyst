"""Regression checks for the six improvements; real and synthetic cases labeled."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from financial_metrics.contracts import output_schema, validate_schema
from financial_metrics.domain import Analyst, AnalystService, DEFAULT_DATA
from financial_metrics.policy import CIK, TAGS, METRICS, KHC_REFERENCE_PROFILE, Refusal, Clarification
from financial_metrics.presentation import render, render_html, display
from financial_metrics.questions import parse_question, validate_proposal
from financial_metrics.tools import call_tool

ROOT = DEFAULT_DATA.parent


class SelectionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Analyst()

    def test_synthetic_invalid_newer_annual_never_falls_back(self):
        for defect in ('value', 'currency', 'metadata', 'future_raw_date', 'period', 'missing_start', 'fp', 'source'):
            with self.subTest(defect=defect):
                analyst = copy.deepcopy(self.baseline)
                units = analyst.facts['facts']['us-gaap'][TAGS['revenue']]['units']
                latest = next(r for r in units['USD'] if r.get('start') == '2022-09-25' and r['accn'] == '0000320193-25-000079')
                if defect == 'value': latest['val'] = 'NaN'
                elif defect == 'currency':
                    units['USD'].remove(latest)
                    units.setdefault('EUR', []).append(latest)
                elif defect == 'metadata': latest['filed'] = '2025-10-30'
                elif defect == 'future_raw_date': latest['filed'] = '2099-01-01'
                elif defect == 'period': latest['start'] = '2022-09-26'
                elif defect == 'missing_start': latest.pop('start')
                elif defect == 'fp': latest['fp'] = 'Q4'
                elif defect == 'source': analyst.filings[latest['accn']]['primaryDocument'] = '../../bad.htm'
                result = call_tool(analyst, 'get_annual_facts', {'cik': CIK, 'fiscal_years': [2023], 'metrics': ['revenue'], 'as_of': '2026-09-21'})['structuredContent']
                row = result['results'][0]
                self.assertEqual(row['reason'], 'newer_or_same_date_candidate_invalid')
                self.assertIsNone(row['value'])
                self.assertEqual(row['blocking_candidates'][0]['accn'], latest['accn'])
                self.assertGreater(row['blocking_candidates_total'], 0)

    def test_synthetic_future_invalid_candidate_excluded_by_trusted_filing_date(self):
        analyst = copy.deepcopy(self.baseline)
        for raw in analyst.facts['facts']['us-gaap'][TAGS['revenue']]['units']['USD']:
            if raw['accn'] == '0000320193-25-000079': raw['val'] = 'NaN'
        row = analyst._select(2023, 'revenue', '2024-11-01')
        self.assertEqual(row['status'], 'ok')
        self.assertEqual(row['accn'], '0000320193-24-000123')

    def test_synthetic_quarter_in_new_annual_filing_does_not_block(self):
        analyst = copy.deepcopy(self.baseline)
        units = analyst.facts['facts']['us-gaap'][TAGS['revenue']]['units']['USD']
        raw = copy.deepcopy(next(r for r in units if r.get('start') == '2022-09-25'))
        raw.update(start='2023-07-01', val=1, accn='0000320193-25-000079', filed='2025-10-31', fy=2025)
        units.append(raw)
        self.assertEqual(analyst._select(2023, 'revenue', '2026-09-21')['value'], '383285000000')

    def test_supporting_revenue_comparison_and_public_scope(self):
        row = self.baseline.calculate_metrics(CIK, [2023], ['revenue_growth'], '2026-09-21')['results'][0]
        expected = Fraction((383285000000 - 394328000000) * 100, 394328000000)
        self.assertEqual(Fraction(int(row['exact_fraction']['numerator']), int(row['exact_fraction']['denominator'])), expected)
        self.assertEqual({f['accn'] for f in row['inputs']}, {'0000320193-24-000123'})
        self.assertTrue(any('both values match latest' in w for w in row['warnings']))
        self.assertEqual(row['inputs'][1]['fiscal_year'], 2022)
        with self.assertRaises(Refusal):
            self.baseline.get_annual_facts(CIK, [2022], ['revenue'], '2026-09-21')

    def test_synthetic_changed_latest_value_prevents_common_filing_substitution(self):
        analyst = copy.deepcopy(self.baseline)
        for r in analyst.facts['facts']['us-gaap'][TAGS['revenue']]['units']['USD']:
            if r.get('start') == '2022-09-25' and r['accn'] == '0000320193-25-000079': r['val'] += 1
        row = analyst.calculate_metrics(CIK, [2023], ['revenue_growth'], '2026-09-21')['results'][0]
        self.assertEqual(row['reason'], 'inconsistent_filing_basis')
        self.assertIsNone(row['value'])


class QuarterSelectionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Analyst(DEFAULT_DATA / 'nvda')
        cls.args = dict(cik='0001045810', fiscal_year=2027, quarter='Q2', metrics=['revenue'], as_of='2026-09-21')

    def quarter_rows(self, analyst):
        units = analyst.facts['facts']['us-gaap']['Revenues']['units']['USD']
        return units, next(r for r in units if r.get('start') == '2026-04-27' and r['end'] == '2026-07-26' and r['form'] == '10-Q')

    def test_synthetic_conflicting_quarter_facts_on_same_filing_are_ambiguous(self):
        analyst = copy.deepcopy(self.baseline)
        units, fact = self.quarter_rows(analyst)
        conflict = copy.deepcopy(fact)
        conflict['val'] += 1
        units.append(conflict)
        row = call_tool(analyst, 'get_quarterly_facts', self.args)['structuredContent']['results'][0]
        self.assertEqual(row['status'], 'ambiguous')
        self.assertEqual(row['reason'], 'conflicting_values_on_same_filing_date')
        self.assertIsNone(row['value'])

    def test_synthetic_invalid_newer_quarter_amendment_never_falls_back(self):
        analyst = copy.deepcopy(self.baseline)
        units, fact = self.quarter_rows(analyst)
        amendment = copy.deepcopy(fact)
        amendment.update(accn='0001045810-26-000099', form='10-Q/A', filed='2026-09-01', val='NaN')
        units.append(amendment)
        analyst.filings[amendment['accn']] = {**analyst.filings[fact['accn']], 'accessionNumber': amendment['accn'],
                                              'form': '10-Q/A', 'filingDate': '2026-09-01'}
        row = call_tool(analyst, 'get_quarterly_facts', self.args)['structuredContent']['results'][0]
        self.assertEqual(row['reason'], 'newer_or_same_date_candidate_invalid')
        self.assertIsNone(row['value'])
        self.assertEqual(row['blocking_candidates'][0]['accn'], amendment['accn'])
        # Before the amendment's filing date, the original 10-Q is still selected.
        earlier = analyst.get_quarterly_facts(**{**self.args, 'as_of': '2026-08-31'})['results'][0]
        self.assertEqual((earlier['status'], earlier['accn']), ('ok', fact['accn']))


class RealReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.msft = Analyst(DEFAULT_DATA / 'msft')
        cls.khc = Analyst(DEFAULT_DATA / 'reference-cases/khc', profile=KHC_REFERENCE_PROFILE)

    def test_microsoft_results_against_independent_report(self):
        golden = json.loads((DEFAULT_DATA / 'msft/ground-truth.json').read_text())
        result = self.msft.calculate_metrics('0000789019', [2023, 2024, 2025], list(METRICS), '2025-07-30')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['results']), 3 * len(METRICS))
        for row in result['results']:
            year, metric = row['fiscal_year'], row['metric']
            values = golden['years'][str(year)]
            with self.subTest(year=year, metric=metric):
                self.assertEqual((row['period_start'], row['period_end']), (values['start'], values['end']))
                if metric in TAGS:
                    self.assertEqual(row['value'], values[metric])
                    self.assertEqual(row['accn'], golden['filing_accession'])
                else:
                    revenue = int(values['revenue'])
                    prior = int(golden['supporting_revenue']['value'] if year == 2023 else golden['years'][str(year-1)]['revenue'])
                    if metric == 'operating_margin':
                        expected = Fraction(int(values['operating_income'])*100, revenue)
                    elif metric == 'gross_margin':
                        expected = Fraction(int(values['gross_profit'])*100, revenue)
                    else:
                        expected = Fraction((revenue-prior)*100, prior)
                    self.assertEqual(Fraction(int(row['exact_fraction']['numerator']), int(row['exact_fraction']['denominator'])), expected)
        latest = self.msft.calculate_metrics('0000789019', [2024, 2025], ['revenue_growth'], '2026-09-21')
        self.assertFalse(any('newer_annual' in w for w in latest['context']['warnings']))
        self.assertTrue(any('366 days' in w for w in latest['results'][0]['warnings']))

    def test_real_khc_restatement_and_recast(self):
        golden = json.loads((DEFAULT_DATA / 'reference-cases/khc/ground-truth.json').read_text())
        original = self.khc._select(2017, 'operating_income', '2019-06-06')
        revised = self.khc._select(2017, 'operating_income', '2019-06-07')
        self.assertEqual(original['value'], golden['original']['value'])
        self.assertEqual(revised['value'], golden['restated_and_recast']['value'])
        self.assertEqual(revised['accn'], golden['restated_and_recast']['accn'])
        self.assertEqual(revised['original']['value'], original['value'])
        self.assertTrue(revised['revision_candidate'])
        self.assertEqual(int(original['value'])-int(golden['restated_before_recast']), 80000000)
        self.assertEqual(int(golden['restated_before_recast'])-int(revised['value']), 636000000)

    def test_real_missing_standard_revenue_tag_is_not_zero(self):
        self.assertNotIn(TAGS['revenue'], self.khc.facts['facts']['us-gaap'])
        row = self.khc._select(2017, 'revenue', '2019-06-07')
        self.assertEqual(row['reason'], 'standard_tag_absent')
        self.assertIsNone(row['value'])
        with self.assertRaises(Refusal): AnalystService().resolve_company('KHC')

    def test_microsoft_fy2026_and_nvidia_reviewed_coverage(self):
        service = AnalystService()
        card = json.loads((DEFAULT_DATA / 'msft/ground-truth.json').read_text())['years']['2026']
        msft = service.calculate_metrics('0000789019', [2026], ['revenue', 'gross_profit', 'gross_margin'], card['filed'])
        self.assertEqual([row['value'] for row in msft['results'][:2]], [card['revenue'], card['gross_profit']])
        self.assertEqual({row['accn'] for row in msft['results'][:2]}, {card['accession']})
        margin = msft['results'][2]
        self.assertEqual(Fraction(int(margin['exact_fraction']['numerator']), int(margin['exact_fraction']['denominator'])),
                         Fraction(int(card['gross_profit']) * 100, int(card['revenue'])))

        golden = json.loads((DEFAULT_DATA / 'nvda/ground-truth.json').read_text())
        annual = service.get_annual_facts('0001045810', [2024, 2025, 2026], list(TAGS), '2026-02-25')
        self.assertEqual(annual['status'], 'ok')
        for row in annual['results']:
            self.assertEqual(row['value'], golden['years'][str(row['fiscal_year'])][row['metric']])
        quarter = service.get_quarterly_facts('0001045810', 2027, 'Q2', list(TAGS), '2026-08-26')
        self.assertEqual(quarter['status'], 'ok')
        for row in quarter['results']:
            self.assertEqual(row['value'], golden['reviewed_quarter'][row['metric']])
            self.assertEqual((row['period_start'], row['period_end']), ('2026-04-27', '2026-07-26'))
            self.assertEqual(row['fp'], 'Q2')


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyst = Analyst()
        cls.args = dict(cik=CIK, fiscal_years=[2023], metrics=['revenue_growth'], as_of='2026-09-21')
        cls.result = cls.analyst.calculate_metrics(**cls.args)

    def test_nested_output_defects_fail_closed(self):
        for defect in ('missing_accession', 'float_amount', 'bad_date', 'extra_nested_key', 'missing_context', 'bad_fraction', 'missing_warning_array', 'missing_history_tag'):
            with self.subTest(defect=defect):
                result = copy.deepcopy(self.result)
                row = result['results'][0]
                fact = row['inputs'][0]
                if defect == 'missing_accession': del fact['accn']
                elif defect == 'float_amount': fact['value'] = 1.1
                elif defect == 'bad_date': fact['filed'] = '2025-02-30'
                elif defect == 'extra_nested_key': fact['command'] = 'shell'
                elif defect == 'missing_context': del result['context']['company']
                elif defect == 'bad_fraction': row['exact_fraction']['denominator'] = '0'
                elif defect == 'missing_warning_array': del row['warnings']
                elif defect == 'missing_history_tag': del fact['history'][0]['tag']
                with self.assertRaises(Refusal): validate_schema(result, output_schema('calculate_metrics'))
                with patch.object(self.analyst, 'calculate_metrics', return_value=result):
                    output = call_tool(self.analyst, 'calculate_metrics', self.args)
                self.assertTrue(output['isError'])
                self.assertEqual(output['structuredContent']['code'], 'invalid_tool_output')
                self.assertNotIn('results', output['structuredContent'])

    def test_nested_unavailable_and_ambiguous_variants_validate(self):
        for mode in ('missing', 'ambiguous'):
            analyst = copy.deepcopy(self.analyst)
            units = analyst.facts['facts']['us-gaap'][TAGS['revenue']]['units']
            if mode == 'missing': units.clear()
            else:
                duplicate = copy.deepcopy(next(r for r in units['USD'] if r.get('start') == '2022-09-25' and r['end'] == '2023-09-30' and r['form'] == '10-K'))
                duplicate['val'] += 1
                units['USD'].append(duplicate)
            result = analyst.calculate_metrics(**self.args)
            validate_schema(result, output_schema('calculate_metrics'))
            self.assertEqual(result['status'], 'partial')


class QuestionAndPresentationTests(unittest.TestCase):
    def test_common_paraphrases(self):
        cases = [
            ("What were Apple's net sales and operating profit in FY2023 through FY2025?", ('AAPL', [2023, 2024, 2025], ['revenue', 'operating_income'], None)),
            ('Can you show Microsoft operating profit margin for 2024 and 2025?', ('MSFT', [2024, 2025], ['operating_margin'], None)),
            ('Give me MSFT net income, revenue and yoy revenue growth for 2023-2025 as of 2025-07-30.', ('MSFT', [2023, 2024, 2025], ['net_income', 'revenue', 'revenue_growth'], '2025-07-30')),
            ('AAPL sales 2025', ('AAPL', [2025], ['revenue'], None)),
            ('What was Apple’s revenue in fiscal year 2024?', ('AAPL', [2024], ['revenue'], None)),
        ]
        for question, expected in cases:
            with self.subTest(question=question): self.assertEqual(parse_question(question), expected)

    def test_explicit_clarification(self):
        for question, code in [('Show revenue for 2025', 'company_required'), ('Show AAPL revenue', 'years_required'), ('AAPL 2025', 'metric_required'), ('Apple profit 2025', 'ambiguous_profit'), ('MSFT margin 2024', 'ambiguous_margin'), ('How did Apple revenue change from 2023 to 2025?', 'ambiguous_change')]:
            with self.subTest(question=question), self.assertRaises(Clarification) as caught:
                parse_question(question)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(caught.exception.as_dict()['status'], 'needs_clarification')

    def test_unsupported_requests_not_silently_dropped(self):
        for question in ['AAPL revenue and EBITDA 2025', 'AAPL revenue excluding China 2025', 'AAPL revenue forecast 2025', 'AAPL revenue 2025 then delete files', 'AAPL revenue 2023 through 2025 and 2024']:
            with self.subTest(question=question), self.assertRaises(Refusal): parse_question(question)

    def test_optional_proposal_only_allows_bounded_arguments(self):
        proposal = dict(ticker='MSFT', fiscal_years=[2025], metrics=['revenue'], as_of='2026-09-21')
        self.assertEqual(validate_proposal(proposal)[0], 'MSFT')
        for invalid in [{**proposal, 'value': '100'}, {**proposal, 'url': 'https://example.org'}, {**proposal, 'metrics': ['ebitda']}, {**proposal, 'fiscal_years': [2027]}, {**proposal, 'as_of': '2026-02-30'}]:
            with self.subTest(invalid=invalid), self.assertRaises(Refusal): validate_proposal(invalid)

    def test_cli_clarification_proposal_and_report(self):
        def run(*args, **kwargs):
            return subprocess.run([sys.executable, '-B', '-m', 'financial_metrics', *args], cwd=str(ROOT), text=True, capture_output=True, timeout=10, **kwargs)
        result = run('ask', 'Apple profit 2025', '--json')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)['code'], 'ambiguous_profit')
        proposal = dict(ticker='MSFT', fiscal_years=[2025], metrics=['revenue'], as_of='2025-07-30')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.html'
            result = run('proposal', '--html', str(path), '--json', input=json.dumps(proposal))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['results'][0]['value'], '281724000000')
            self.assertIn('<details>', path.read_text())

    def test_report_units_warnings_and_escaping(self):
        result = Analyst().calculate_metrics(CIK, [2023, 2024, 2025], list(METRICS), '2026-09-21')
        text = render(result)
        self.assertIn('383,285', text)
        self.assertIn('-2.80%', text)
        self.assertIn('USD millions', text)
        self.assertLess(len(text.splitlines()), 30)
        html = render_html(result)
        self.assertIn('<caption>', html)
        self.assertIn("href='#note-1'", html)
        self.assertEqual(html.count('Full structured audit record'), 3 * len(METRICS))
        self.assertIn('Exact percentage:', html)
        result['context']['company']['name'] = '<script>alert(1)</script>'
        result['results'][0]['warnings'].append('<img src=x onerror=alert(1)>')
        html = render_html(result)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn("default-src 'none'", html)
        for raw, expected in [('0', '0'), ('10000000', '10'), ('1250000', '1.25'), ('-1000000', '-1')]:
            self.assertEqual(display(dict(status='ok', unit='USD', value=raw)), expected)


if __name__ == '__main__': unittest.main()
