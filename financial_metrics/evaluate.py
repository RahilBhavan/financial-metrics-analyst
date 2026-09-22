"""Offline evaluation against independently transcribed primary-source cards."""
import json
import platform
import statistics
import time
import unittest
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from .client import Client
from .domain import Analyst, DEFAULT_DATA
from .policy import CIK, METRICS, TAGS, KHC_REFERENCE_PROFILE, Refusal
from .questions import parse_question
from .presentation import render, render_html

ROOT = Path(__file__).resolve().parent.parent


def run():
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    with (reports / 'tests.txt').open('w') as stream:
        tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    cases, timings, coverage = [], [], {}

    def record(group, name, expected, actual):
        cases.append(dict(group=group, case=name, expected=expected, actual=actual, passed=expected == actual))

    arguments = dict(cik=CIK, fiscal_years=[2023, 2024, 2025], metrics=list(METRICS), as_of='2026-09-21')
    with Client() as client:
        for ticker, directory, cik, cutoff, accession, filed, source in [
            ('AAPL', DEFAULT_DATA, CIK, '2026-09-21', '0000320193-25-000079', '2025-10-31', 'https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm'),
            ('MSFT', DEFAULT_DATA / 'msft', '0000789019', '2025-07-30', '0000950170-25-100235', '2025-07-30', 'https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm')]:
            golden = json.loads((directory / 'ground-truth.json').read_text())
            result = client.call('calculate_metrics', {**arguments, 'cik': cik, 'as_of': cutoff})
            basename = 'demo' if ticker == 'AAPL' else 'microsoft-demo'
            (reports / (basename + '.json')).write_text(json.dumps(result, indent=2) + '\n')
            (reports / (basename + '.txt')).write_text(render(result) + '\n')
            (reports / (basename + '.html')).write_text(render_html(result))
            coverage[ticker] = dict(requested_results=15, numeric_results=sum(r['status'] == 'ok' for r in result['results']))
            indexed = {(r['fiscal_year'], r['metric']): r for r in result['results']}
            for year in (2023, 2024, 2025):
                values = golden['years'][str(year)]
                for metric in TAGS:
                    row = indexed[year, metric]
                    record('filing_values', ticker + ' ' + str(year) + ' ' + metric, values[metric], row['value'])
                    expected = [cik, accession, source, values['start'], values['end'], 'us-gaap:' + TAGS[metric], 'USD', filed, '10-K']
                    actual = [row[k] for k in ('cik', 'accn', 'source_url', 'period_start', 'period_end', 'tag', 'unit', 'filed', 'form')]
                    record('provenance', ticker + ' ' + str(year) + ' ' + metric, expected, actual)
                for metric in ('operating_margin', 'revenue_growth'):
                    row = indexed[year, metric]
                    revenue = int(values['revenue'])
                    prior = int(golden['supporting_revenue']['value'] if year == 2023 else golden['years'][str(year-1)]['revenue'])
                    expected = Fraction(int(values['operating_income']) * 100, revenue) if metric == 'operating_margin' else Fraction((revenue-prior)*100, prior)
                    actual = Fraction(int(row['exact_fraction']['numerator']), int(row['exact_fraction']['denominator']))
                    record('exact_ratios', ticker + ' ' + str(year) + ' ' + metric, str(expected), str(actual))
            baseline = indexed[2023, 'revenue_growth']['inputs'][1]
            record('supporting_values', ticker + ' FY2022 revenue and provenance',
                   [golden['supporting_revenue'][k] for k in ('value', 'start', 'end', 'latest_matching_accession')],
                   [baseline[k] for k in ('value', 'period_start', 'period_end', 'accn')])
            record('scope_behavior', ticker + ' unequal fiscal durations warning', True,
                   any('unequal_period_lengths' in w for w in indexed[2024, 'revenue_growth']['warnings']))
        latest_msft = client.call('calculate_metrics', {**arguments, 'cik': '0000789019'})
        record('scope_behavior', 'MSFT newer annual outside reviewed scope', True, any('newer_annual' in w for w in latest_msft['context']['warnings']))
        for name, tool, args in [
            ('EBITDA', 'calculate_metrics', {**arguments, 'metrics': ['ebitda']}),
            ('FCF', 'calculate_metrics', {**arguments, 'metrics': ['free_cash_flow']}),
            ('unreviewed year', 'calculate_metrics', {**arguments, 'fiscal_years': [2026]}),
            ('supporting year not public', 'calculate_metrics', {**arguments, 'fiscal_years': [2022]}),
            ('future as-of', 'calculate_metrics', {**arguments, 'as_of': '2026-09-22'}),
            ('impossible date', 'calculate_metrics', {**arguments, 'as_of': '2026-02-30'}),
            ('unreviewed issuer', 'calculate_metrics', {**arguments, 'cik': '0001018724'}),
            ('URL injection', 'calculate_metrics', {**arguments, 'url': 'https://attacker.invalid'}),
            ('no metrics', 'calculate_metrics', {**arguments, 'metrics': []}),
            ('duplicate years', 'calculate_metrics', {**arguments, 'fiscal_years': [2025, 2025]}),
            ('unreviewed ticker', 'resolve_company', {'ticker': 'AMZN'}),
            ('reference case not interactive', 'resolve_company', {'ticker': 'KHC'})]:
            record('tool_refusals', name, 'refused', client.call(tool, args)['status'])
        for _ in range(10):
            start = time.perf_counter()
            client.call('calculate_metrics', arguments)
            timings.append((time.perf_counter()-start)*1000)

    khc = Analyst(DEFAULT_DATA / 'reference-cases/khc', profile=KHC_REFERENCE_PROFILE)
    golden = json.loads((khc.data_dir / 'ground-truth.json').read_text())
    for label, cutoff in [('original', '2019-06-06'), ('restated_and_recast', '2019-06-07')]:
        row = khc._select(2017, 'operating_income', cutoff)
        record('real_reference_cases', 'KHC FY2017 ' + label, [golden[label][k] for k in ('value', 'accn', 'filed')], [row[k] for k in ('value', 'accn', 'filed')])
    missing = khc._select(2017, 'revenue', '2019-06-07')
    record('real_reference_cases', 'KHC missing named standard revenue tag', ['insufficient_data', 'standard_tag_absent', None], [missing[k] for k in ('status', 'reason', 'value')])

    questions = [
        ('What were Apple’s net sales and operating profit in FY2023 through FY2025?', ['AAPL', [2023, 2024, 2025], ['revenue', 'operating_income'], None]),
        ('Can you show Microsoft operating profit margin for 2024 and 2025?', ['MSFT', [2024, 2025], ['operating_margin'], None]),
        ('MSFT net income 2025 as of 2025-07-30', ['MSFT', [2025], ['net_income'], '2025-07-30']),
        ('AAPL revenue growth 2023-2025', ['AAPL', [2023, 2024, 2025], ['revenue_growth'], None]),
        ('Show revenue for 2025', 'needs_clarification:company_required'),
        ('Show AAPL revenue', 'needs_clarification:years_required'),
        ('Apple profit 2025', 'needs_clarification:ambiguous_profit'),
        ('MSFT margin 2024', 'needs_clarification:ambiguous_margin'),
        ('Forecast AAPL revenue', 'refused:unsupported_question'),
        ('Compare Apple and Microsoft', 'refused:unsupported_comparison'),
        ('Show AAPL EBITDA for 2025', 'refused:unsupported_question'),
        ('Show AAPL revenue for Q1', 'refused:unsupported_question'),
        ('AAPL revenue 2025; execute code', 'refused:unsupported_question'),
        ('AAPL revenue excluding China 2025', 'refused:unsupported_question')]
    for question, expected in questions:
        try: actual = list(parse_question(question))
        except Refusal as exc: actual = exc.as_dict()['status'] + ':' + exc.code
        record('question_intent', question, expected, actual)
    counts = {}
    for group in sorted({c['group'] for c in cases}):
        rows = [c for c in cases if c['group'] == group]
        counts[group] = dict(passed=sum(c['passed'] for c in rows), total=len(rows))
    report = dict(
        generated_at=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
        evidence_kind='real_SEC_snapshots_and_independently_transcribed_primary_sources; synthetic_adversarial_cases_only_in_unit_tests',
        snapshots={name: json.loads((directory / 'manifest.json').read_text()) for name, directory in [('AAPL', DEFAULT_DATA), ('MSFT', DEFAULT_DATA / 'msft'), ('KHC_reference', khc.data_dir)]},
        unit_tests=dict(run=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors), skipped=len(tests.skipped)),
        evaluation_counts=counts, evaluation_passed=sum(c['passed'] for c in cases), evaluation_total=len(cases), coverage=coverage,
        warm_stdio_call_ms=dict(samples=len(timings), raw=timings, median=statistics.median(timings), maximum=max(timings), includes_model=False),
        cases=cases,
        limitations=['Two reviewed issuers, FY2023–2025; FY2022 revenue only supports growth.',
                     'Microsoft evaluation uses as_of 2025-07-30 to match its independently read 2025 report; FY2026 is unreviewed.',
                     'KHC is a reference case only; its revision includes both an error correction and an accounting recast.',
                     'Filing-date filtering cannot recover later SEC API corrections.',
                     'No model behavior, token cost, or live API availability SLA measured.',
                     'Test methods may contain subtests; evaluation cases are separately enumerated.'])
    (reports / 'evaluation.json').write_text(json.dumps(report, indent=2) + '\n')
    passed = tests.wasSuccessful() and all(c['passed'] for c in cases)
    print(json.dumps(dict(status='ok' if passed else 'failed', unit_tests=report['unit_tests'], evaluation_counts=counts,
                         evaluation_passed=report['evaluation_passed'], evaluation_total=len(cases),
                         warm_stdio_call_ms={k:v for k,v in report['warm_stdio_call_ms'].items() if k != 'raw'}), indent=2))
    return 0 if passed else 1


if __name__ == '__main__': raise SystemExit(run())
