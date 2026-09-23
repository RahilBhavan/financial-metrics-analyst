"""Offline evaluation against independently transcribed primary-source cards."""
import io
import json
import os
import platform
import statistics
import time
import unittest
from datetime import date
from fractions import Fraction
from pathlib import Path

from .client import Client
from .domain import Analyst, DEFAULT_DATA, today
from .policy import CIK, METRICS, PROFILES, TAGS, KHC_REFERENCE_PROFILE, Refusal
from .questions import parse_question
from .presentation import render, render_html

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = [('AAPL', DEFAULT_DATA), ('MSFT', DEFAULT_DATA / 'msft'), ('NVDA', DEFAULT_DATA / 'nvda'),
             ('KHC_reference', DEFAULT_DATA / 'reference-cases/khc')]
# Each run checks one ground-truth card's years at the cutoff where its cited filing is the latest.
ANNUAL_RUNS = [('AAPL', DEFAULT_DATA, 'demo', [2023, 2024, 2025], '2026-09-21'),
               ('MSFT', DEFAULT_DATA / 'msft', 'microsoft-demo', [2023, 2024, 2025], '2025-07-30'),
               ('MSFT', DEFAULT_DATA / 'msft', None, [2026], '2026-09-21'),
               ('NVDA', DEFAULT_DATA / 'nvda', 'nvidia-demo', [2024, 2025, 2026], '2026-02-25')]


def days(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def fraction(row):
    return Fraction(int(row['exact_fraction']['numerator']), int(row['exact_fraction']['denominator']))


def run():
    reports = ROOT / 'reports'
    reports.mkdir(exist_ok=True)
    # Reports are rendered against a fixed clock so reruns are byte-identical.
    os.environ.setdefault('FINANCIAL_METRICS_TODAY', max(
        json.loads((directory / 'manifest.json').read_text())['captured_at'][:10] for _, directory in SNAPSHOTS))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    tests = unittest.TextTestRunner(stream=io.StringIO(), verbosity=2).run(suite)
    cases, timings, coverage = [], [], {}

    def record(group, name, expected, actual):
        cases.append(dict(group=group, case=name, expected=expected, actual=actual, passed=expected == actual))

    arguments = dict(cik=CIK, fiscal_years=[2023, 2024, 2025], metrics=list(METRICS), as_of='2026-09-21')
    with Client() as client:
        for ticker, directory, basename, years, cutoff in ANNUAL_RUNS:
            cik = next(c for c, p in PROFILES.items() if p['ticker'] == ticker)
            tags = PROFILES[cik].get('tags', TAGS)
            golden = json.loads((directory / 'ground-truth.json').read_text())
            support = golden['supporting_revenue']
            result = client.call('calculate_metrics', {**arguments, 'cik': cik, 'fiscal_years': years, 'as_of': cutoff})
            if basename:
                (reports / (basename + '.json')).write_text(json.dumps(result, indent=2) + '\n')
                (reports / (basename + '.txt')).write_text(render(result) + '\n')
                (reports / (basename + '.html')).write_text(render_html(result))
            label = ticker + ' FY' + str(years[0]) + ('' if len(years) == 1 else '-FY' + str(years[-1]))
            coverage[label] = dict(requested_results=len(result['results']), numeric_results=sum(r['status'] == 'ok' for r in result['results']))
            indexed = {(r['fiscal_year'], r['metric']): r for r in result['results']}
            for year in years:
                values = golden['years'][str(year)]
                prior = support if year - 1 == support['fiscal_year'] else golden['years'][str(year - 1)]
                name = ticker + ' ' + str(year) + ' '
                for metric in TAGS:
                    row = indexed[year, metric]
                    record('filing_values', name + metric, values[metric], row['value'])
                    expected = [cik, values.get('accession') or golden.get('accession') or golden['filing_accession'],
                                values.get('filing_url') or golden.get('filing_url') or golden['source_url'],
                                values['start'], values['end'], 'us-gaap:' + tags[metric], 'USD',
                                values.get('filed') or golden['filing_date'], '10-K']
                    actual = [row[k] for k in ('cik', 'accn', 'source_url', 'period_start', 'period_end', 'tag', 'unit', 'filed', 'form')]
                    record('provenance', name + metric, expected, actual)
                revenue = int(values['revenue'])
                previous = int(prior.get('value') or prior['revenue'])
                for metric, expected in [('gross_margin', Fraction(int(values['gross_profit']) * 100, revenue)),
                                         ('operating_margin', Fraction(int(values['operating_income']) * 100, revenue)),
                                         ('revenue_growth', Fraction((revenue - previous) * 100, previous))]:
                    record('exact_ratios', name + metric, str(expected), str(fraction(indexed[year, metric])))
                record('scope_behavior', name + 'unequal fiscal durations warning',
                       days(values['start'], values['end']) != days(prior['start'], prior['end']),
                       any('unequal_period_lengths' in w for w in indexed[year, 'revenue_growth']['warnings']))
            if years[0] - 1 == support['fiscal_year']:
                baseline = indexed[years[0], 'revenue_growth']['inputs'][1]
                record('supporting_values', ticker + ' FY' + str(support['fiscal_year']) + ' revenue and provenance',
                       [support[k] for k in ('value', 'start', 'end', 'latest_matching_accession')],
                       [baseline[k] for k in ('value', 'period_start', 'period_end', 'accn')])
        quarter = json.loads((DEFAULT_DATA / 'nvda/ground-truth.json').read_text())['reviewed_quarter']
        result = client.call('get_quarterly_facts', {'cik': '0001045810', 'fiscal_year': quarter['fiscal_year'], 'quarter': quarter['quarter'],
                                                     'metrics': list(TAGS), 'as_of': quarter['filed']})
        for row in result['results']:
            name = 'NVDA ' + quarter['quarter'] + ' FY' + str(quarter['fiscal_year']) + ' ' + row['metric']
            record('filing_values', name, quarter[row['metric']], row['value'])
            record('provenance', name,
                   [quarter[k] for k in ('filing_accession', 'filing_url', 'start', 'end', 'filed')] + ['10-Q', quarter['quarter']],
                   [row[k] for k in ('accn', 'source_url', 'period_start', 'period_end', 'filed', 'form', 'fp')])
        latest_msft = client.call('calculate_metrics', {**arguments, 'cik': '0000789019'})
        record('scope_behavior', 'MSFT FY2026 included in reviewed scope', False,
               any('newer_annual' in w for w in latest_msft['context']['warnings']))
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
    # Timings and interpreter details vary per run, so they are printed but kept out of the committed report.
    latency = dict(samples=len(timings), median=statistics.median(timings), maximum=max(timings), includes_model=False)
    report = dict(
        clock=today().isoformat(),
        evidence_kind='real_SEC_snapshots_and_independently_transcribed_primary_sources; synthetic_adversarial_cases_only_in_unit_tests',
        snapshots={name: json.loads((directory / 'manifest.json').read_text()) for name, directory in SNAPSHOTS},
        unit_tests=dict(run=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors), skipped=len(tests.skipped)),
        evaluation_counts=counts, evaluation_passed=sum(c['passed'] for c in cases), evaluation_total=len(cases), coverage=coverage,
        cases=cases,
        limitations=['Three reviewed issuers with issuer-specific annual coverage; one NVIDIA quarter is reviewed.',
                     'Microsoft legacy evaluation uses as_of 2025-07-30 to match its independently read 2025 report; FY2026 has separate source checks.',
                     'KHC is a reference case only; its revision includes both an error correction and an accounting recast.',
                     'Filing-date filtering cannot recover later SEC API corrections.',
                     'No model behavior, token cost, or live API availability SLA measured.',
                     'Test methods may contain subtests; evaluation cases are separately enumerated.'])
    (reports / 'evaluation.json').write_text(json.dumps(report, indent=2) + '\n')
    passed = tests.wasSuccessful() and all(c['passed'] for c in cases)
    print(json.dumps(dict(status='ok' if passed else 'failed', unit_tests=report['unit_tests'], evaluation_counts=counts,
                         evaluation_passed=report['evaluation_passed'], evaluation_total=len(cases),
                         python=platform.python_version(), warm_stdio_call_ms=latency), indent=2))
    return 0 if passed else 1


if __name__ == '__main__': raise SystemExit(run())
