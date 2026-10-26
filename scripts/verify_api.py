"""Run a bounded live Messages API smoke test; exits 2 and records not_run without a key."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from financial_metrics.agent import AnthropicMessages, DEFAULT_MODEL, run
from financial_metrics.agent_eval import score
from financial_metrics.client import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--output', default=str(ROOT / 'reports' / 'api-smoke.json'))
    args = parser.parse_args()
    report = {'backend': 'anthropic-messages-api', 'model_requested': args.model,
              'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'checks': []}
    if not os.environ.get('ANTHROPIC_API_KEY'):
        report.update(status='not_run', reason='ANTHROPIC_API_KEY is not available', passed=0, total=3)
        exit_code = 2
    else:
        tasks = json.loads((ROOT / 'evals' / 'agent-expanded-tasks.json').read_text())['tasks']
        backend = AnthropicMessages(args.model)
        with Client() as client:
            for task in tasks:
                if task['id'] not in ('A01', 'C01', 'Q01'):
                    continue
                record = run(task['question'], backend, client)
                scored = score(task, record)
                passed = scored['tool_correct'] and scored['arguments_correct'] and scored['answer_numbers_correct']
                report['checks'].append({'task_id': task['id'], 'passed': passed, 'score': scored, 'run': record})
        report.update(status='passed' if all(c['passed'] for c in report['checks']) else 'failed',
                      passed=sum(c['passed'] for c in report['checks']), total=len(report['checks']))
        exit_code = 0 if report['status'] == 'passed' else 1
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(report['status'], str(report['passed']) + '/' + str(report['total']))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
