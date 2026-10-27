"""Verify requests chosen by a T3-hosted model through the real direct financial tools.

--questions prints the integration prompts. A T3 conversation supplies a JSON list of
{id, request} (or {id, refusal}) records. This verifier reruns all calls and scores the
actual selected evidence. It calls no model API and does not configure MCP.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from financial_metrics.agent_eval import score
from financial_metrics.direct import DirectClient
from financial_metrics.policy import Refusal
from financial_metrics.t3 import MAX_REQUEST_BYTES, answer, read_request

TASKS = ROOT / 'evals' / 't3-tasks.json'


def verify(responses):
    tasks = json.loads(TASKS.read_text())['tasks']
    if (not isinstance(responses, list) or len(responses) != len(tasks)
            or any(not isinstance(r, dict) or not isinstance(r.get('id'), str) for r in responses)
            or {r['id'] for r in responses} != {t['id'] for t in tasks}):
        raise Refusal('invalid_responses', 'Supply exactly one response for each integration task ID.')
    by_id = {r['id']: r for r in responses}
    checks = []
    with DirectClient() as client:
        for task in tasks:
            submitted = by_id[task['id']]
            if set(submitted) == {'id', 'request'} and isinstance(submitted['request'], dict):
                request = {**submitted['request'], 'question': task['question']}
                run = answer(request, client)
            elif (set(submitted) == {'id', 'refusal'} and isinstance(submitted['refusal'], str)
                  and 1 <= len(submitted['refusal']) <= 500):
                run = {'status': 'refused', 'refusal': submitted['refusal'], 'answer': None, 'traces': [],
                       'tool_calls': [], 'results': [], 'drafts': [], 'latency_ms': 0, 'turns': 1, 'usage': {}}
            else:
                raise Refusal('invalid_responses', 'Use an id with a request or a nonempty refusal.')
            scored = score(task, run)
            passed = (scored['tool_correct'] and scored['arguments_correct'] and scored['answer_numbers_correct']
                      if task['in_scope'] else scored['refusal_correct'])
            checks.append({'id': task['id'], 'passed': passed, 'score': scored, 'run': run})
    return {'host': 'T3 Code native conversation', 'transport': 'direct in-process financial tools',
            'model_api_required': False, 'mcp_required': False,
            'verification': 'Real tool replay of model-selected requests; task/field/sign/value checks, not an inference-cost benchmark.',
            'passed': sum(c['passed'] for c in checks), 'total': len(checks), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions', action='store_true')
    parser.add_argument('--requests', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports' / 't3-smoke.json')
    args = parser.parse_args()
    if args.questions:
        print(json.dumps([{k: task[k] for k in ('id', 'question')} for task in json.loads(TASKS.read_text())['tasks']], indent=2))
        return 0
    if args.requests is None:
        parser.error('--requests is required unless --questions is used')
    try:
        if args.requests.stat().st_size > MAX_REQUEST_BYTES:
            raise Refusal('request_too_large', 'Integration requests exceed one MiB.')
        with args.requests.open() as stream:
            report = verify(read_request(stream))
    except (Refusal, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(str(report['passed']) + '/' + str(report['total']) + ' T3-native checks passed')
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
