import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from financial_metrics.client import Client
from financial_metrics.direct import DirectClient
from financial_metrics.policy import Refusal
from financial_metrics.t3 import MAX_REQUEST_BYTES, answer, inspect_call, read_request, scope

ROOT = Path(__file__).resolve().parents[1]
CALL = {'name': 'get_annual_facts', 'arguments': {'cik': '0000320193', 'fiscal_years': [2025],
                                                'metrics': ['financing_cash_flow'], 'as_of': '2026-09-21'}}


class T3NativeTests(unittest.TestCase):
    def test_direct_tools_match_mcp_for_financial_results_and_refusals(self):
        calls = [CALL, {'name': 'resolve_company', 'arguments': {'ticker': 'MSFT'}},
                 {'name': 'calculate_metrics', 'arguments': {'cik': '0000789019', 'fiscal_years': [2026],
                                                            'metrics': ['gross_margin'], 'as_of': '2026-09-21'}},
                 {'name': 'get_quarterly_facts', 'arguments': {'cik': '0001318605', 'fiscal_year': 2026, 'quarter': 'Q3',
                                                             'metrics': ['revenue'], 'as_of': '2026-10-25'}},
                 {'name': 'get_treasury_actions', 'arguments': {'firm': 'BMNR', 'action': 'est_issuance'}},
                 {'name': 'get_coins_per_share', 'arguments': {'firm': 'MSTR'}},
                 {'name': 'get_break_even', 'arguments': {'firm': 'SBET'}}]
        with DirectClient() as direct, Client() as mcp:
            for call in calls:
                with self.subTest(tool=call['name']):
                    self.assertEqual(direct.call_raw(call['name'], call['arguments']), mcp.call_raw(call['name'], call['arguments']))

    def test_final_answer_replays_calls_and_binds_signed_value(self):
        with DirectClient() as client:
            inspected = inspect_call(CALL, client)
            inspected['data']['results'][0]['value'] = '999999999'
            receipt = answer({'calls': [CALL], 'evidence': ['c0.r0']}, client)
        self.assertIn('-120686000000 USD', receipt['answer'])
        self.assertNotIn('999999999', receipt['answer'])
        self.assertTrue(all(t['traced'] for t in receipt['traces']))

    def test_model_prose_result_injection_and_unknown_evidence_are_rejected(self):
        with DirectClient() as client:
            for payload in ({'calls': [CALL], 'evidence': ['c0.r0'], 'answer': 'a billion dollars'},
                            {'calls': [CALL], 'evidence': ['c0.r0'], 'results': [{'value': '42'}]},
                            {'calls': [CALL], 'evidence': ['c0.history.0']},
                            {'calls': [{'name': 'run_shell', 'arguments': {}}], 'evidence': ['c0.r0']}):
                with self.subTest(payload=payload), self.assertRaises(Refusal):
                    answer(payload, client)

    def test_direct_answer_works_with_network_and_subprocesses_denied_and_without_keys(self):
        program = '''import sys, runpy

def deny(event, args):
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.exec', 'os.posix_spawn'):
        raise RuntimeError('Forbidden side effect: ' + event)
sys.addaudithook(deny)
sys.argv = ['financial_metrics.t3', 'answer']
runpy.run_module('financial_metrics.t3', run_name='__main__')
'''
        env = dict(os.environ)
        env.pop('ANTHROPIC_API_KEY', None)
        env.pop('OPENAI_API_KEY', None)
        done = subprocess.run([sys.executable, '-B', '-c', program], cwd=ROOT, env=env,
                              input=json.dumps({'calls': [CALL], 'evidence': ['c0.r0']}), text=True, capture_output=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['status'], 'answered')

    def test_scope_respects_a_custom_single_issuer_snapshot(self):
        result = scope(ROOT / 'data' / 'msft')
        self.assertEqual([p['ticker'] for p in result['issuers']], ['MSFT'])
        self.assertEqual(result['issuers'][0]['annual_years'], [2023, 2024, 2025, 2026])

    def test_cli_malformed_and_oversized_requests_fail_closed(self):
        for value in ('not json', 'x' * (MAX_REQUEST_BYTES + 1), '"' + 'é' * (MAX_REQUEST_BYTES // 2) + '"'):
            with self.subTest(length=len(value)), self.assertRaises(Refusal):
                read_request(io.StringIO(value))
        done = subprocess.run([sys.executable, '-B', '-m', 'financial_metrics.t3', 'call'], cwd=ROOT,
                              input='[]', text=True, capture_output=True, timeout=10)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(json.loads(done.stdout)['status'], 'refused')
