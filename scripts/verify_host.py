"""Verify the server in the actual Claude Code MCP host, using its signed-in model account.

Writes separate host evidence; this is not a desktop UI test or the optional agent backend.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_events(events, expected_tool, expected_value, expected_error=False):
    calls, results = [], []
    for event in events:
        content = event.get('message', {}).get('content', [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get('type') == 'tool_use':
                calls.append(block)
            elif block.get('type') == 'tool_result':
                results.append(block)
    ids = {c['id'] for c in calls if c['name'] == 'mcp__financial_metrics__' + expected_tool}
    matched = [r for r in results if r.get('tool_use_id') in ids and bool(r.get('is_error')) == expected_error]
    return bool(ids) and any(expected_value in json.dumps(r.get('content')) for r in matched)


def transport_evidence(events):
    """Keep protocol evidence and usage, excluding host settings, sessions and model thinking."""
    clean = []
    for event in events:
        blocks = [b for b in event.get('message', {}).get('content', []) if isinstance(b, dict) and b.get('type') in ('tool_use', 'tool_result')]
        if blocks:
            clean.append({'type': event['type'], 'message': {'content': blocks}})
        elif event.get('type') == 'result':
            clean.append({k: event[k] for k in ('type', 'is_error', 'result', 'modelUsage', 'total_cost_usd') if k in event})
    return clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='haiku')
    parser.add_argument('--output', default=str(ROOT / 'reports' / 'host-smoke.json'))
    args = parser.parse_args()
    config = {'mcpServers': {'financial_metrics': {'command': sys.executable, 'args': ['-B', str(ROOT / 'server_stdio.py')]}}}
    checks = [
        ('annual_cash_flow', 'get_annual_facts', '111482000000',
         'Call get_annual_facts for cik 0000320193, fiscal_years [2025], metrics ["operating_cash_flow"], as_of 2026-09-21.'),
        ('quarter', 'get_quarterly_facts', '2026-07-01',
         'Call get_quarterly_facts for cik 0001318605, fiscal_year 2026, quarter Q3, metrics ["revenue"], as_of 2026-10-25.'),
        ('treasury', 'get_break_even', '119.07', 'Call get_break_even for firm MSTR.'),
        ('refusal', 'get_annual_facts', 'unsupported_years',
         'Call get_annual_facts for cik 0000320193, fiscal_years [2026], metrics ["revenue"], as_of 2026-09-21.'),
    ]
    records = []
    with tempfile.TemporaryDirectory(prefix='fma-host-') as directory:
        path = Path(directory) / 'mcp.json'
        path.write_text(json.dumps(config))
        for name, tool, expected, prompt in checks:
            command = ['claude', '-p', '--model', args.model, '--output-format', 'stream-json', '--verbose',
                       '--tools', '', '--setting-sources', '', '--strict-mcp-config', '--mcp-config', str(path),
                       '--allowedTools', 'mcp__financial_metrics__*', '--no-session-persistence',
                       '--system-prompt', 'Use the requested MCP tool with the exact arguments. Never substitute an answer without calling the tool.', prompt]
            try:
                done = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=180)
                events = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
                passed = done.returncode == 0 and check_events(events, tool, expected, name == 'refusal')
                records.append({'check': name, 'passed': passed, 'exit_code': done.returncode, 'events': transport_evidence(events)})
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                records.append({'check': name, 'passed': False, 'error': str(exc)[:300]})
            print(name, records[-1]['passed'], flush=True)
    report = {'host': 'Claude Code CLI, native MCP tools', 'model_requested': args.model,
              'checks': records, 'passed': sum(r['passed'] for r in records), 'total': len(records)}
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    return 0 if all(r['passed'] for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
