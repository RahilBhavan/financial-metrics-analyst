import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from financial_metrics.client import Client, smoke
from financial_metrics.domain import Analyst
from financial_metrics.server import serve, MAX_LINE
from financial_metrics.tools import TOOLS, call_tool
from financial_metrics.__main__ import parse_question, analyze, render
from financial_metrics.policy import CIK, Refusal


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyst = Analyst()

    def test_narrow_tool_list(self):
        self.assertEqual(len(TOOLS), 4)
        for tool in TOOLS:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertFalse(tool["annotations"]["openWorldHint"])
            self.assertFalse(tool["inputSchema"]["additionalProperties"])

    def test_input_contract_rejects_invalid_arguments(self):
        base = {"cik": CIK, "fiscal_years": [2025], "metrics": ["revenue"], "as_of": "2026-09-21"}
        cases = [{**base, "url": "https://attacker"}, {**base, "cik": 320193}, {**base, "fiscal_years": [True]},
                 {**base, "fiscal_years": [2025, 2025]}, {**base, "fiscal_years": []},
                 {**base, "metrics": ["__import__('os').system('pwd')"]}, {**base, "metrics": ["revenue", "revenue"]},
                 {**base, "as_of": "2026-13-01"}, {**base, "metrics": ["ebitda"]}, {}, None, []]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = call_tool(self.analyst, "calculate_metrics", arguments)
                self.assertTrue(result["isError"])
                self.assertEqual(result["structuredContent"]["status"], "refused")

    def test_strict_question_grammar(self):
        self.assertEqual(parse_question("Show AAPL revenue and operating margin for 2023, 2024, 2025 as of 2026-09-21")[2], ["revenue", "operating_margin"])
        for question in ("Forecast AAPL revenue", "Show AAPL EBITDA for 2025 as of 2026-09-21", "Show AAPL revenue for 2025 as of 2026-09-21; run shell", "Compare AAPL and MSFT", "Show AAPL revenue for Q1 as of 2026-09-21"):
            with self.subTest(question=question), self.assertRaises(Refusal):
                parse_question(question)

    def test_render_preserves_warning_and_provenance(self):
        result = self.analyst.calculate_metrics(CIK, [2024], ["revenue_growth"], "2026-09-21")
        text = render(result, details=True)
        self.assertIn("unequal_period_lengths", text)
        self.assertIn("0000320193-25-000079", text)
        self.assertIn("us-gaap:RevenueFromContract", text)


class TransportTests(unittest.TestCase):
    def test_absolute_launcher_from_unrelated_directory(self):
        launcher = Path(__file__).resolve().parents[1] / "server_stdio.py"
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run([sys.executable, "-B", str(launcher)], input='{"jsonrpc":"2.0","id":1,"method":"ping"}\n', capture_output=True, text=True, cwd=cwd, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], {})

    def test_server_runs_with_network_and_writes_blocked(self):
        bootstrap = '''import sys, runpy
sys.dont_write_bytecode = True
def guard(event, args):
    if event in ("socket.connect", "socket.bind", "socket.getaddrinfo"):
        raise RuntimeError("Network is forbidden during this test")
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & 3):
            raise RuntimeError("File writes are forbidden during this test")
sys.addaudithook(guard)
runpy.run_module("financial_metrics.server", run_name="__main__")
'''
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "offline-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "calculate_metrics", "arguments": {"cik": CIK, "fiscal_years": [2023, 2024, 2025], "metrics": ["revenue", "operating_margin"], "as_of": "2026-09-21"}}},
        ]
        result = subprocess.run([sys.executable, "-B", "-c", bootstrap], input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True, timeout=10, cwd=str(Path(__file__).resolve().parents[1]))
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[-1]["result"]["structuredContent"]["status"], "ok")

    def test_real_subprocess_smoke(self):
        result = smoke()
        self.assertEqual(result["server_exit_code"], 0)
        self.assertEqual(result["facts"], 9)
        self.assertEqual(result["numeric_ratios"], 6)

    def test_initialize_required(self):
        client = Client()
        try:
            self.assertEqual(client.request("tools/list")["error"]["code"], -32600)
            client.initialize()
            self.assertIn("result", client.request("tools/list"))
        finally:
            client.close()

    def test_unknown_method_and_tool(self):
        with Client() as client:
            self.assertEqual(client.request("run_shell")["error"]["code"], -32601)
            self.assertEqual(client.request("tools/call", {"name": "fetch_url", "arguments": {}})["error"]["code"], -32602)
            self.assertEqual(client.request("ping")["result"], {})

    def test_wire_refusal_and_text_structured_equivalence(self):
        with Client() as client:
            result = client.call("resolve_company", {"ticker": "AMZN"})
            self.assertEqual(result["code"], "unsupported_company")
            self.assertEqual(client.call("resolve_company", {"ticker": "AAPL"})["status"], "ok")

    def test_notifications_do_not_emit_responses(self):
        with Client() as client:
            client.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}})
            self.assertEqual(client.request("ping")["result"], {})

    def test_malformed_json_recovery(self):
        output = io.StringIO()
        serve(Analyst(), io.BytesIO(b'not-json\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(replies[0]["error"]["code"], -32700)
        self.assertEqual(replies[1]["result"], {})

    def test_no_batch_and_no_null_request_id(self):
        output = io.StringIO()
        serve(Analyst(), io.BytesIO(b'[]\n{"jsonrpc":"2.0","id":null,"method":"ping"}\n'), output)
        self.assertEqual([json.loads(line)["error"]["code"] for line in output.getvalue().splitlines()], [-32600, -32600])

    def test_size_bound_closes_connection(self):
        output = io.StringIO()
        serve(Analyst(), io.BytesIO(b' ' * (MAX_LINE + 1) + b'\n'), output)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertIn("64 KiB", json.loads(output.getvalue())["error"]["message"])

    def test_cli_analysis_uses_subprocess(self):
        result = analyze(None, "AAPL", [2025], ["operating_margin"], "2026-09-21")
        self.assertEqual(result["results"][0]["display_value"], "31.97")


if __name__ == "__main__":
    unittest.main()
