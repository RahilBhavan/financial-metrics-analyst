"""Financial tools for a T3 conversation: no model API, MCP server, or credentials.

Use scope/tools to discover coverage, call to inspect a record, and answer to replay a
bounded call list and render only the selected evidence. JSON requests arrive on stdin.
"""
import argparse
import json
import sys
import time

from .contracts import TEXT, obj, validate_schema
from .direct import DirectClient
from .domain import DEFAULT_DATA
from .evidence import evidence_catalog, render_selection
from .policy import CASH_FLOW_TAGS, METRICS, QUARTER_METRICS, Refusal
from .tools import TOOLS
from .tracing import trace_numbers

MAX_REQUEST_BYTES = 1024 * 1024
MAX_CALLS = 24
CALL = obj({'name': {'type': 'string', 'enum': [t['name'] for t in TOOLS]}, 'arguments': {'type': 'object'}})
ANSWER = obj({'question': {'type': 'string', 'maxLength': 500},
              'calls': {'type': 'array', 'items': CALL, 'minItems': 1, 'maxItems': MAX_CALLS},
              'evidence': {'type': 'array', 'items': TEXT, 'minItems': 1, 'maxItems': 40}}, optional=('question',))


def scope(data_dir=DEFAULT_DATA):
    with DirectClient(data_dir) as client:
        profiles = client.reviewed_profiles().values()
    return {'status': 'ok', 'annual_metrics': list(METRICS), 'quarterly_metrics': list(QUARTER_METRICS),
            'cash_flow': {'metrics': list(CASH_FLOW_TAGS), 'frequency': 'annual and standalone quarter', 'unit': 'signed USD'},
            'issuers': [{'ticker': p['ticker'], 'name': p['name'], 'cik': p['cik'], 'annual_years': sorted(p['periods']),
                        'quarters': [{'fiscal_year': y, 'quarter': q, 'start': dates[0], 'end': dates[1]}
                                     for (y, q), dates in sorted(p['quarters'].items())]} for p in profiles],
            'treasury_firms': ['MSTR', 'BMNR', 'SBET'],
            'limits': 'Reviewed snapshots only. Resolve each issuer for its cached as_of date. No forecasts, advice or live prices.'}


def inspect_call(request, client, index=0):
    validate_schema(request, CALL)
    result = client.call_raw(request['name'], request['arguments'])
    return {'status': result['structuredContent']['status'], 'data': result['structuredContent'],
            'is_error': result['isError'], 'answer_evidence': evidence_catalog(result['structuredContent'], index)}


def answer(request, client):
    """Replay real calls, ignoring model-supplied results/prose; bind each delivered value to a record."""
    validate_schema(request, ANSWER)
    started = time.perf_counter()
    results, calls, catalog = [], [], {}
    for index, call in enumerate(request['calls']):
        inspected = inspect_call(call, client, index)
        results.append(inspected['data'])
        catalog.update(inspected['answer_evidence'])
        calls.append({'turn': 1, 'name': call['name'], 'arguments': call['arguments'],
                      'status': inspected['status'], 'result_index': index})
    selection = {'evidence': request['evidence']}
    try:
        rendered = render_selection(selection, catalog)
    except ValueError as exc:
        raise Refusal('invalid_evidence', str(exc))
    traces = trace_numbers(rendered, results)
    if any(not trace['traced'] for trace in traces):
        raise Refusal('untraced_evidence', 'Selected evidence could not be traced; no financial answer was returned.')
    return {'status': 'answered', 'backend': 't3-native-direct', 'question': request.get('question', ''),
            'answer': rendered, 'evidence': request['evidence'], 'traces': traces, 'results': results,
            'tool_calls': calls, 'drafts': [{'text': rendered, 'selection': selection, 'traces': traces}],
            'turns': 1, 'usage': {}, 'cost_usd': None,
            'latency_ms': round((time.perf_counter() - started) * 1000, 1)}


def read_request(stream):
    raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw.encode('utf-8')) > MAX_REQUEST_BYTES:
        raise Refusal('request_too_large', 'JSON request exceeds one MiB.')
    try:
        return json.loads(raw)
    except ValueError:
        raise Refusal('invalid_json', 'Pass one JSON request on stdin.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('scope', 'tools', 'call', 'answer'))
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA))
    parser.add_argument('--index', type=int, default=0, help='Evidence call index for inspection, 0 to 23')
    parser.add_argument('--text', action='store_true', help='Print only the verified final answer')
    args = parser.parse_args()
    try:
        if not 0 <= args.index < MAX_CALLS:
            raise Refusal('invalid_index', 'Evidence call index must be between zero and twenty-three.')
        if args.command == 'scope':
            result = scope(args.data_dir)
        elif args.command == 'tools':
            result = {'status': 'ok', 'tools': [{k: t[k] for k in ('name', 'description', 'inputSchema')} for t in TOOLS]}
        else:
            request = read_request(sys.stdin)
            with DirectClient(args.data_dir) as client:
                result = inspect_call(request, client, args.index) if args.command == 'call' else answer(request, client)
    except Refusal as exc:
        result = exc.as_dict()
    except (OSError, RuntimeError) as exc:
        result = Refusal('runtime_failure', str(exc)).as_dict()
    if args.text and result.get('status') == 'answered':
        print(result['answer'])
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
    return 2 if result['status'] == 'refused' else 0


if __name__ == '__main__':
    raise SystemExit(main())
