"""Regressions for the October 2026 multi-model review findings; synthetic mutations of real snapshots are labeled."""
import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from financial_metrics.client import smoke
from financial_metrics.contracts import output_schema, validate_schema
from financial_metrics.domain import Analyst, AnalystService, DEFAULT_DATA, snapshot_ticker
from financial_metrics.fetch import SECClient, fetch_snapshot
from financial_metrics.policy import (ANNUAL_YEARS, KHC_REFERENCE_PROFILE, PROFILES, QUARTERS, TAGS,
                                      TICKERS, Refusal)
from financial_metrics.presentation import render
from financial_metrics.questions import COMPANIES, PROPOSAL_SCHEMA, validate_proposal
from financial_metrics.server import Session, serve
from financial_metrics.tools import TOOLS, call_tool

ROOT = DEFAULT_DATA.parent
NVDA = '0001045810'


def cli(*args):
    return subprocess.run([sys.executable, '-B', '-m', 'financial_metrics', *args], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=60)


class QuarterlyComparativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Analyst(DEFAULT_DATA / 'nvda')

    def test_real_prior_year_quarter_survives_next_years_comparative(self):
        # Real data: the Q2 FY2027 10-Q repeats Q2 FY2026 as a comparative column with fy=2027.
        analyst = copy.deepcopy(self.baseline)
        analyst.profile['quarters'][(2026, 'Q2')] = ('2025-04-28', '2025-07-27')
        before = analyst.get_quarterly_facts(NVDA, 2026, 'Q2', ['revenue'], '2025-09-01')['results'][0]
        after = analyst.get_quarterly_facts(NVDA, 2026, 'Q2', ['revenue'], '2026-09-21')['results'][0]
        self.assertEqual((before['status'], before['value']), ('ok', '46743000000'))
        self.assertEqual((after['status'], after['value']), ('ok', '46743000000'))
        self.assertEqual(after['reported_fy'], 2027)
        self.assertEqual(after['original']['accn'], before['accn'])

    def test_synthetic_next_year_10q_comparative_keeps_q2_fy2027(self):
        analyst = copy.deepcopy(self.baseline)
        units = analyst.facts['facts']['us-gaap']['Revenues']['units']['USD']
        fact = next(r for r in units if r.get('start') == '2026-04-27' and r['end'] == '2026-07-26' and r['form'] == '10-Q')
        later = {**fact, 'accn': '0001045810-27-000050', 'fy': 2028, 'filed': '2027-08-25'}
        units.append(later)
        analyst.filings[later['accn']] = {**analyst.filings[fact['accn']], 'accessionNumber': later['accn'],
                                          'filingDate': '2027-08-25', 'reportDate': '2027-07-25'}
        analyst.captured_date = analyst.captured_date.replace(year=2027, month=9, day=1)
        row = analyst.get_quarterly_facts(NVDA, 2027, 'Q2', ['revenue'], '2027-09-01')['results'][0]
        self.assertEqual((row['status'], row['value'], row['accn']), ('ok', '96221000000', later['accn']))

    def test_synthetic_comparative_with_wrong_fy_still_blocks(self):
        analyst = copy.deepcopy(self.baseline)
        units = analyst.facts['facts']['us-gaap']['Revenues']['units']['USD']
        fact = next(r for r in units if r.get('start') == '2026-04-27' and r['end'] == '2026-07-26' and r['form'] == '10-Q')
        later = {**fact, 'accn': '0001045810-27-000050', 'fy': 2027, 'filed': '2027-08-25'}
        units.append(later)
        analyst.filings[later['accn']] = {**analyst.filings[fact['accn']], 'accessionNumber': later['accn'],
                                          'filingDate': '2027-08-25', 'reportDate': '2027-07-25'}
        analyst.captured_date = analyst.captured_date.replace(year=2027, month=9, day=1)
        row = analyst.get_quarterly_facts(NVDA, 2027, 'Q2', ['revenue'], '2027-09-01')['results'][0]
        self.assertEqual(row['reason'], 'newer_or_same_date_candidate_invalid')

    def test_synthetic_quarter_filed_before_period_end_rejected(self):
        analyst = copy.deepcopy(self.baseline)
        units = analyst.facts['facts']['us-gaap']['Revenues']['units']['USD']
        fact = next(r for r in units if r.get('start') == '2026-04-27' and r['end'] == '2026-07-26' and r['form'] == '10-Q')
        fact['filed'] = '2026-07-01'
        analyst.filings[fact['accn']]['filingDate'] = '2026-07-01'
        row = analyst.get_quarterly_facts(NVDA, 2027, 'Q2', ['revenue'], '2026-07-01')['results'][0]
        self.assertEqual(row['status'], 'insufficient_data')
        self.assertEqual(row['rejection_counts'].get('filed_before_period_end'), 1)

    def test_synthetic_malformed_report_date_is_invalid_not_accepted(self):
        quarterly = copy.deepcopy(self.baseline)
        units = quarterly.facts['facts']['us-gaap']['Revenues']['units']['USD']
        fact = next(r for r in units if r.get('start') == '2026-04-27' and r['end'] == '2026-07-26' and r['form'] == '10-Q')
        quarterly.filings[fact['accn']]['reportDate'] = '2026-99-99'
        self.assertNotEqual(quarterly.get_quarterly_facts(NVDA, 2027, 'Q2', ['revenue'], '2026-09-21')['status'], 'ok')
        annual = Analyst()
        annual.filings['0000320193-25-000079']['reportDate'] = '2025-99-99'
        self.assertEqual(annual._select(2025, 'revenue', '2026-09-21')['status'], 'insufficient_data')

    def test_one_month_stub_does_not_block_a_quarter(self):
        analyst = copy.deepcopy(self.baseline)
        units = analyst.facts['facts']['us-gaap']['Revenues']['units']['USD']
        fact = next(r for r in units if r.get('start') == '2026-04-27' and r['end'] == '2026-07-26' and r['form'] == '10-Q')
        units.append({**fact, 'start': '2026-06-29', 'val': 'NaN'})
        self.assertEqual(analyst.get_quarterly_facts(NVDA, 2027, 'Q2', ['revenue'], '2026-09-21')['status'], 'ok')


class FiscalCalendarTests(unittest.TestCase):
    def test_early_january_year_end_carries_prior_fiscal_year(self):
        # Real pattern from the bundled KHC data: FY2015 ended 2016-01-03 and is tagged fy=2015.
        khc = Analyst(DEFAULT_DATA / 'reference-cases/khc', profile=KHC_REFERENCE_PROFILE)
        filing = {'reportDate': '2016-01-03'}
        self.assertTrue(khc._fiscal_year_matches({'fy': 2015, 'fp': 'FY'}, filing))
        self.assertTrue(khc._fiscal_year_matches({'fy': 2016, 'fp': 'FY'}, filing))
        self.assertFalse(khc._fiscal_year_matches({'fy': 2014, 'fp': 'FY'}, filing))
        self.assertFalse(khc._fiscal_year_matches({'fy': 2015, 'fp': 'FY'}, {'reportDate': '2016-03-31'}))


class SubmissionHistoryTests(unittest.TestCase):
    def test_older_filing_missing_from_index_is_flagged_not_promoted(self):
        # Real KHC restatement; the original 10-K's metadata is removed to simulate it leaving "recent".
        khc = Analyst(DEFAULT_DATA / 'reference-cases/khc', profile=KHC_REFERENCE_PROFILE)
        del khc.filings['0001637459-18-000015']
        row = khc._select(2017, 'operating_income', '2019-06-07')
        self.assertEqual(row['value'], '6057000000')
        self.assertTrue(any(w.startswith('history_incomplete') and '0001637459-18-000015' in w for w in row['warnings']))

    def test_paged_submissions_are_indexed(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for name in ('companyfacts.json', 'submissions.json'):
                os.symlink(DEFAULT_DATA / name, root / name)
            page_name = 'CIK0000320193-submissions-001.json'
            page = {'accessionNumber': ['0000320193-14-000001'], 'filingDate': ['2014-10-27'], 'reportDate': ['2014-09-27'],
                    'form': ['10-K'], 'primaryDocument': ['aapl-20140927.htm']}
            raw = json.dumps(page).encode()
            (root / page_name).write_bytes(raw)
            manifest = json.loads((DEFAULT_DATA / 'manifest.json').read_text())
            manifest['files'][page_name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            analyst = Analyst(root)
            self.assertEqual(analyst.filings['0000320193-14-000001']['form'], '10-K')
            (root / page_name).write_bytes(raw.replace(b'10-K', b'10-Q'))
            with self.assertRaises(Refusal) as error:
                Analyst(root)
            self.assertEqual(error.exception.code, 'snapshot_integrity')

    def test_fetch_downloads_paged_submissions(self):
        submissions = json.dumps({'cik': '320193', 'filings': {'recent': {}, 'files': [
            {'name': 'CIK0000320193-submissions-001.json'}]}}).encode()
        bodies = {'https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json': b'{"cik":320193}',
                  'https://data.sec.gov/submissions/CIK0000320193.json': submissions,
                  'https://data.sec.gov/submissions/CIK0000320193-submissions-001.json': b'{"accessionNumber":[]}'}

        def respond(request, timeout):
            response = io.BytesIO(bodies[request.full_url])
            response.geturl = lambda: request.full_url
            return response

        offline = lambda agent, cik: SECClient(agent, cik, opener=Mock(open=Mock(side_effect=respond)), sleep=Mock())
        with tempfile.TemporaryDirectory() as root, patch('financial_metrics.fetch.SECClient', side_effect=offline):
            result = fetch_snapshot(Path(root) / 'snap', 'TestAgent test@example.test')
            self.assertIn('CIK0000320193-submissions-001.json', result['manifest']['files'])
            self.assertTrue((Path(root) / 'snap/CIK0000320193-submissions-001.json').exists())

    def test_hostile_page_names_refused(self):
        client = SECClient('TestAgent test@example.test', opener=Mock(), sleep=Mock())
        with self.assertRaises(Refusal):
            client.get('CIK0000320193-submissions-001.json')
        from financial_metrics.fetch import page_names
        for name in ('../x.json', 'CIK0000789019-submissions-001.json', 'https://evil/CIK0000320193-submissions-001.json'):
            with self.subTest(name=name), self.assertRaises(Refusal):
                page_names('0000320193', json.dumps({'filings': {'files': [{'name': name}]}}))


class RefreshCheckTests(unittest.TestCase):
    def test_reviewed_output_ignores_snapshot_identity_only(self):
        spec = importlib.util.spec_from_file_location('live_refresh_check', ROOT / 'scripts/live_refresh_check.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = Analyst().calculate_metrics(PROFILES['0000320193']['cik'], [2025], ['revenue'], '2026-09-21')
        moved = copy.deepcopy(result)
        moved['context'].update(snapshot_sha256='0' * 64, snapshot_captured_at='2026-10-18T00:00:00+00:00')
        self.assertEqual(module.reviewed_output(result), module.reviewed_output(moved))
        moved['results'][0]['value'] = '1'
        self.assertNotEqual(module.reviewed_output(result), module.reviewed_output(moved))
        checked = {(ticker, tuple(years), quarter) for ticker, _, years, quarter in module.CHECKS}
        self.assertIn(('MSFT', (2023, 2024, 2025, 2026), None), checked)
        self.assertIn(('NVDA', (2027,), 'Q2'), checked)


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyst = Analyst()

    def session(self):
        session = Session(self.analyst)
        session.receive({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
        return session

    def test_null_params_on_initialized_notification(self):
        session = self.session()
        self.assertIsNone(session.receive({'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': None}))
        self.assertIn('tools', session.receive({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': None})['result'])

    def test_unknown_id_is_omitted_not_null(self):
        output = io.StringIO()
        serve(self.analyst, io.BytesIO(b'not-json\n[]\n'), output)
        for reply in map(json.loads, output.getvalue().splitlines()):
            self.assertNotIn('id', reply)

    def test_client_responses_get_no_reply(self):
        session = self.session()
        self.assertIsNone(session.receive({'jsonrpc': '2.0', 'id': 6, 'result': {}}))
        self.assertIsNone(session.receive({'jsonrpc': '2.0', 'id': 7, 'error': {'code': 1, 'message': 'x'}}))

    def test_non_object_tool_arguments_are_protocol_errors(self):
        session = self.session()
        session.receive({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        reply = session.receive({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                 'params': {'name': 'calculate_metrics', 'arguments': []}})
        self.assertEqual(reply['error']['code'], -32602)

    def test_server_version_is_package_version(self):
        from financial_metrics import __version__
        reply = Session(self.analyst).receive({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
        self.assertEqual(reply['result']['serverInfo']['version'], __version__)


class ContractCodeTests(unittest.TestCase):
    def test_refusal_codes_name_the_failed_field(self):
        service = AnalystService()
        quarter = call_tool(service, 'get_quarterly_facts', {'cik': NVDA, 'fiscal_year': 2027, 'quarter': 'Q3',
                                                             'metrics': ['revenue'], 'as_of': '2026-09-21'})
        self.assertEqual(quarter['structuredContent']['code'], 'unsupported_quarter')
        with self.assertRaises(Refusal) as error:
            validate_proposal({'ticker': 'AMZN', 'fiscal_years': [2025], 'metrics': ['revenue']})
        self.assertEqual(error.exception.code, 'unsupported_company')
        metric = call_tool(service, 'calculate_metrics', {'cik': NVDA, 'fiscal_years': [2025], 'metrics': ['ebitda'], 'as_of': '2026-09-21'})
        self.assertEqual(metric['structuredContent']['code'], 'unsupported_metric')

    def test_date_time_requires_rfc3339(self):
        schema = {'type': 'string', 'format': 'date-time'}
        for good in ('2026-09-21T22:17:57+00:00', '2026-09-21T22:17:57.5Z', '2026-09-21t22:17:57z'):
            validate_schema(good, schema)
        for bad in ('2026-09-21X22:17:57+00:00', '2026-09-21 22:17:57+00:00', '2026-09-21T22:17:57', '2026-02-30T00:00:00Z'):
            with self.subTest(bad=bad), self.assertRaises(Refusal):
                validate_schema(bad, schema)

    def test_quarterly_output_rejects_annual_forms(self):
        result = Analyst(DEFAULT_DATA / 'nvda').get_quarterly_facts(NVDA, 2027, 'Q2', ['revenue'], '2026-09-21')
        schema = output_schema('get_quarterly_facts')
        validate_schema(result, schema, 'result')
        broken = copy.deepcopy(result)
        broken['results'][0]['form'] = '10-K'
        with self.assertRaises(Refusal):
            validate_schema(broken, schema, 'result')

    def test_proposal_cutoff_is_optional(self):
        self.assertIsNone(validate_proposal({'ticker': 'MSFT', 'fiscal_years': [2025], 'metrics': ['revenue']})[3])

    def test_ratio_operands_omit_candidate_audit(self):
        row = Analyst().calculate_metrics('0000320193', [2025], ['operating_margin'], '2026-09-21')['results'][0]
        self.assertTrue(all('rejected_candidates' not in operand for operand in row['inputs']))
        self.assertTrue(all(operand['source_url'] for operand in row['inputs']))


class QuestionVariantTests(unittest.TestCase):
    def test_variants_from_the_review(self):
        from financial_metrics.questions import parse_question
        cases = {'Apple revenue between 2023 and 2025': [2023, 2024, 2025], 'Apple revenue 2023–2025': [2023, 2024, 2025],
                 'Apple revenue 2023 thru 2025': [2023, 2024, 2025], 'Apple revenue 2023 and 2025': [2023, 2025],
                 'AAPL revenue FY2025 vs FY2024': [2024, 2025], 'Apple revenue FY24': [2024]}
        for question, years in cases.items():
            with self.subTest(question=question):
                self.assertEqual(parse_question(question)[1], years)
        self.assertEqual(parse_question('Apple gross profit margin 2024')[2], ['gross_margin'])
        self.assertEqual(parse_question('Apple sales growth 2024')[2], ['revenue_growth'])
        self.assertEqual(parse_question("What's Apple's revenues in 2025?")[2], ['revenue'])
        for question, code in [('Apple margin 2024', 'ambiguous_margin'), ('Apple profit 2025', 'ambiguous_profit'),
                               ('How did Apple operating margin change from 2023 to 2025?', 'ambiguous_change')]:
            with self.subTest(question=question), self.assertRaises(Refusal) as error:
                parse_question(question)
            self.assertEqual(error.exception.code, code)
        with self.assertRaises(Refusal) as error:
            parse_question('Apple margin 2024')
        self.assertEqual(error.exception.choices, ['Gross margin', 'Operating margin'])


class ScopeConsistencyTests(unittest.TestCase):
    """Every interface derives its scope from PROFILES; this fails if one drifts."""

    def test_interfaces_agree_with_profiles(self):
        tools = {tool['name']: tool for tool in TOOLS}
        years = tools['calculate_metrics']['inputSchema']['properties']['fiscal_years']['items']
        self.assertEqual((years['minimum'], years['maximum']), (ANNUAL_YEARS[0], ANNUAL_YEARS[-1]))
        quarter = tools['get_quarterly_facts']['inputSchema']['properties']
        self.assertEqual(set(quarter['quarter']['enum']), {q for _, q in QUARTERS})
        self.assertEqual(set(PROPOSAL_SCHEMA['properties']['ticker']['enum']), set(TICKERS))
        self.assertEqual(set(COMPANIES.values()), set(TICKERS))
        for profile in PROFILES.values():
            self.assertTrue(set(profile['periods']) <= set(ANNUAL_YEARS))
            self.assertIn(profile['ticker'], tools['resolve_company']['description'])


class CliTests(unittest.TestCase):
    def test_issuer_defaults_cover_every_reviewed_issuer(self):
        for ticker in TICKERS:
            with self.subTest(ticker=ticker):
                result = cli('analyze', '--ticker', ticker, '--json')
                self.assertEqual(result.returncode, 0, result.stdout)
                years = sorted({r['fiscal_year'] for r in json.loads(result.stdout)['results']})
                self.assertEqual(years, sorted(next(p for p in PROFILES.values() if p['ticker'] == ticker)['periods']))

    def test_demo_and_smoke_infer_issuer_from_data_dir(self):
        self.assertEqual(snapshot_ticker(DEFAULT_DATA / 'nvda'), 'NVDA')
        self.assertEqual(cli('demo', '--data-dir', 'data/nvda').returncode, 0)
        self.assertEqual(smoke(DEFAULT_DATA / 'nvda')['facts'], 9)

    def test_quarter_option_labels_quarter(self):
        result = cli('analyze', '--ticker', 'NVDA', '--quarter', 'Q2')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('Q2 FY2027', result.stdout)
        self.assertNotIn('| FY2027', result.stdout)

    def test_quarter_option_refuses_instead_of_dropping(self):
        ratio = cli('analyze', '--ticker', 'NVDA', '--quarter', 'Q2', '--metrics', 'revenue', 'gross_margin', '--json')
        self.assertEqual((ratio.returncode, json.loads(ratio.stdout)['code']), (2, 'unsupported_metric'))
        missing = cli('analyze', '--ticker', 'AAPL', '--quarter', 'Q4', '--json')
        self.assertEqual((missing.returncode, json.loads(missing.stdout)['code']), (2, 'unsupported_quarter'))

    def test_failed_issuer_load_fails_the_same_way_twice(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for item in DEFAULT_DATA.iterdir():
                if item.name != 'msft':
                    os.symlink(item, root / item.name)
            (root / 'msft').mkdir()
            for item in (DEFAULT_DATA / 'msft').iterdir():
                if item.name != 'companyfacts.json':
                    os.symlink(item, root / 'msft' / item.name)
            (root / 'msft/companyfacts.json').write_text('{}')
            service = AnalystService(root)
            for _ in range(2):
                with self.assertRaises(Refusal) as error:
                    service.resolve_company('MSFT')
                self.assertEqual(error.exception.code, 'snapshot_integrity')

    def test_server_diagnostics_reach_the_user(self):
        result = cli('analyze', '--data-dir', '/nonexistent-snapshot')
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid_snapshot', result.stdout)

    def test_copied_data_directory_keeps_every_issuer(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for item in DEFAULT_DATA.iterdir():
                os.symlink(item, root / item.name)
            service = AnalystService(root)
            for ticker in TICKERS:
                self.assertEqual(service.resolve_company(ticker)['status'], 'ok')

    def test_quarterly_render_names_failed_operand(self):
        analyst = Analyst()
        for raw in analyst.facts['facts']['us-gaap'][TAGS['revenue']]['units']['USD']:
            if raw['end'] == '2022-09-24':
                raw['val'] = 'NaN'
        result = analyst.calculate_metrics('0000320193', [2023], ['revenue_growth'], '2026-09-21')
        self.assertIn('FY2022 revenue: Unavailable', render(result, details=True))


if __name__ == '__main__':
    unittest.main()
