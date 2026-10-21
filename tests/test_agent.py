import io
import json
import unittest
from types import SimpleNamespace

from financial_metrics import agent_eval
from financial_metrics.agent import ABSTAIN, AnthropicMessages, ClaudeCodeCLI, run
from financial_metrics.client import Client
from financial_metrics.tracing import quotes, trace_numbers

ACTION = {"status": "ok", "actions": [{"week_end": "2026-07-19", "action": "buyback_common", "usd": "85885800.00",
                                       "effect_bps_of_coins_per_share": "0.849852", "coins_per_share_change": "-0.000006389294409",
                                       "provenance": {"filing_url": "https://www.sec.gov/Archives/edgar/data/1829311/000149315226033855/ex99-1.htm",
                                                      "accession": "0001493152-26-033855", "filed": "2026-07-20"}}],
          "warnings": ["biases S upward by up to 0.55% at 2026-10-11."]}


def untraced(answer, results=(ACTION,), question=""):
    return [t["text"] for t in trace_numbers(answer, list(results), question) if not t["traced"]]


class TracingTests(unittest.TestCase):
    def test_numbers_at_the_precision_shown(self):
        for answer in ("$85.9M", "$85.89 million", "$85,885,800", "85885800.00", "0.85 bps", "0.849852 basis points",
                       "−0.000006389 ETH", "-6.389294409e-06", "reduced by 0.0000064 ETH per share", "0.55%"):
            with self.subTest(answer=answer):
                self.assertEqual(untraced(answer), [])
        for answer in ("$85.8M", "0.86 bps", "$86 million dollars and 0.9 bps", "1,000 shares", "9.50%"):
            with self.subTest(answer=answer):
                self.assertNotEqual(untraced(answer), [])

    def test_small_integers_must_match_exactly(self):
        self.assertEqual(untraced("2 weeks", [{"m": "1.998"}]), ["2"])
        self.assertEqual(untraced("2 weeks", [{"count": 2}]), [])

    def test_dates_accessions_and_urls_are_verbatim(self):
        url = ACTION["actions"][0]["provenance"]["filing_url"]
        self.assertEqual(untraced("Week ending 2026-07-19, filed 2026-07-20 (" + url + ", 0001493152-26-033855)."), [])
        self.assertEqual(untraced("July 19, 2026"), [])
        self.assertEqual(untraced("week ending 2026-07-26"), ["2026-07-26"])
        self.assertEqual(untraced("accession 0001493152-26-099999"), ["0001493152-26-099999"])
        self.assertEqual(untraced(url.replace("033855", "033856")), [url.replace("033855", "033856")])

    def test_date_fragments_cannot_launder_small_numbers(self):
        self.assertEqual(untraced("It bought 28 ETH in 2026.", [{"week_end": "2026-06-28"}]), ["28"])

    def test_question_numbers_and_fiscal_labels(self):
        facts = {"results": [{"fiscal_year": 2025, "value": "416161000000"}]}
        self.assertEqual(untraced("FY2025 revenue was $416.2 billion ($416 billion rounded).", [facts]), [])
        self.assertEqual(untraced("In Q2 the 10-K and 8-K said nothing new about the 3 weeks.", [], "the last 3 weeks"), [])

    def test_quotes(self):
        self.assertTrue(quotes("Revenue was $416.16 billion.", "416161000000"))
        self.assertTrue(quotes("It fell 80.26 bps.", "-80.2646"))
        self.assertFalse(quotes("It fell 80.3 bps.", "-80.2146"))
        self.assertFalse(quotes("No numbers here.", "1"))


class ScriptedBackend:
    label = "scripted"

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def step(self, system, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"content": reply, "model": "scripted-model", "cost_usd": 0.001,
                "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}


class FakeClient:
    def __init__(self, result=ACTION):
        self.calls, self.result = [], result

    def request(self, method, params=None):
        return {"result": {"tools": [{"name": "get_treasury_actions", "description": "d", "inputSchema": {"type": "object"}}]}}

    def call_raw(self, name, arguments):
        self.calls.append((name, arguments))
        return {"structuredContent": self.result, "isError": False}


def tool(name="get_treasury_actions", arguments=None, call_id="c1"):
    return {"type": "tool_use", "id": call_id, "name": name, "input": arguments or {"firm": "BMNR", "action": "buyback_common"}}


def text(value):
    return {"type": "text", "text": value}


class AgentLoopTests(unittest.TestCase):
    def test_tool_call_then_traced_answer(self):
        backend = ScriptedBackend([[tool()], [text("BitMine spent $85.9M in the week ending 2026-07-19 (0.85 bps).")]])
        client = FakeClient()
        record = run("question", backend, client)
        self.assertEqual(record["status"], "answered")
        self.assertEqual(client.calls, [("get_treasury_actions", {"firm": "BMNR", "action": "buyback_common"})])
        self.assertTrue(all(t["traced"] for t in record["traces"]))
        self.assertEqual(record["usage"]["input_tokens"], 20)
        self.assertAlmostEqual(record["cost_usd"], 0.002)
        result_block = backend.seen[1][2]["content"][0]
        self.assertEqual((result_block["type"], result_block["tool_use_id"]), ("tool_result", "c1"))
        self.assertEqual(json.loads(result_block["content"]), ACTION)

    def test_untraced_draft_gets_one_rewrite(self):
        backend = ScriptedBackend([[tool()], [text("It spent $90M.")], [text("It spent $85.9M.")]])
        record = run("q", backend, FakeClient())
        self.assertEqual((record["status"], len(record["drafts"])), ("answered", 2))
        self.assertIn("$90M", backend.seen[2][-1]["content"])

    def test_untraced_twice_is_withheld(self):
        record = run("q", ScriptedBackend([[tool()], [text("It spent $90M.")], [text("Still $91M.")]]), FakeClient())
        self.assertEqual((record["status"], record["answer"], record["traces"]), ("abstained_untraced", ABSTAIN, []))

    def test_answer_without_tools_cannot_carry_numbers(self):
        record = run("q", ScriptedBackend([[text("ETH per share was 0.0097.")], [text("It was 0.0097.")]]), FakeClient())
        self.assertEqual(record["status"], "abstained_untraced")

    def test_refusal(self):
        record = run("q", ScriptedBackend([[tool("refuse", {"reason": "forecast"})]]), FakeClient())
        self.assertEqual((record["status"], record["refusal"], record["tool_calls"]), ("refused", "forecast", []))

    def test_unknown_tool_and_non_object_arguments_never_reach_the_server(self):
        client = FakeClient()
        backend = ScriptedBackend([[tool("run_shell", {"cmd": "ls"}), tool(arguments=None, call_id="c2")], [text("No data.")]])
        backend.replies[0][1]["input"] = ["not", "an", "object"]
        record = run("q", backend, client)
        self.assertEqual(client.calls, [])
        self.assertEqual([c["status"] for c in record["tool_calls"]], ["rejected_by_agent", "rejected_by_agent"])
        self.assertEqual(record["status"], "answered")

    def test_turn_limit_and_backend_errors(self):
        self.assertEqual(run("q", ScriptedBackend([[tool()]] * 6), FakeClient())["status"], "abstained_max_turns")
        failed = run("q", ScriptedBackend([RuntimeError("rate limited")]), FakeClient())
        self.assertEqual((failed["status"], failed["errors"]), ("error", ["rate limited"]))

    def test_real_mcp_subprocess(self):
        backend = ScriptedBackend([[tool("get_break_even", {"firm": "MSTR"})],
                                   [text("STRC break-even was $119.07 in the week ending 2026-10-11; STRC closed at $99.65.")]])
        with Client() as client:
            record = run("At what STRC price does the rotation stop adding?", backend, client)
        self.assertEqual(record["status"], "answered")
        self.assertEqual(record["results"][0]["break_even"]["break_even_price_usd"], "119.07")


class BackendTests(unittest.TestCase):
    def test_cli_parse(self):
        self.assertEqual(ClaudeCodeCLI.parse('```json\n{"answer": "x"}\n```', 1), [text("x")])
        calls = ClaudeCodeCLI.parse('{"tool_calls": [{"name": "get_break_even", "arguments": {"firm": "MSTR"}}]}', 3)
        self.assertEqual(calls, [{"type": "tool_use", "id": "t3_0", "name": "get_break_even", "input": {"firm": "MSTR"}}])
        self.assertEqual(ClaudeCodeCLI.parse('Sure. {"refuse": "advice"}', 1)[0]["name"], "refuse")
        self.assertEqual(ClaudeCodeCLI.parse("plain prose", 1), [text("plain prose")])
        self.assertEqual(ClaudeCodeCLI.parse('{"other": 1}', 1), [text('{"other": 1}')])

    def test_cli_step_disables_builtin_tools_and_reads_usage(self):
        seen = {}

        def runner(command, **kwargs):
            seen["command"], seen["cwd"] = command, kwargs["cwd"]
            payload = {"is_error": False, "result": '{"answer": "done"}', "total_cost_usd": 0.0004,
                       "usage": {"input_tokens": 3, "output_tokens": 7, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 50},
                       "modelUsage": {"claude-haiku-5-5": {}}}
            return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)

        backend = ClaudeCodeCLI(runner=runner)
        tools = [{"name": "get_break_even", "description": "d", "inputSchema": {"type": "object"}}]
        reply = backend.step("SYSTEM", [{"role": "user", "content": "Q?"}], tools)
        command = seen["command"]
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", command)
        self.assertIn('"name":"get_break_even"', command[command.index("--system-prompt") + 1])
        self.assertTrue(command[-1].startswith("QUESTION: Q?"))
        self.assertEqual((reply["content"], reply["model"], reply["cost_usd"]), ([text("done")], "claude-haiku-5-5", 0.0004))
        self.assertEqual(reply["usage"]["cache_read_input_tokens"], 100)

    def test_cli_render_includes_calls_and_results(self):
        rendered = ClaudeCodeCLI.render([{"role": "user", "content": "Q"}, {"role": "assistant", "content": [tool()]},
                                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{}", "is_error": True}]}])
        self.assertIn("ASSISTANT TOOL CALL c1:", rendered)
        self.assertIn("TOOL RESULT c1 (error): {}", rendered)

    def test_messages_api_request_shape(self):
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout):
            seen["request"] = request
            return Response(json.dumps({"model": "claude-haiku-5-5", "content": [tool()],
                                        "usage": {"input_tokens": 900, "output_tokens": 40}}).encode())

        backend = AnthropicMessages(api_key="test-key", urlopen=urlopen)
        reply = backend.step("SYSTEM", [{"role": "user", "content": "Q"}],
                             [{"name": "get_break_even", "description": "d", "inputSchema": {"type": "object"}}])
        request = seen["request"]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(body["model"], "claude-haiku-5-5")
        self.assertEqual([t["name"] for t in body["tools"]], ["get_break_even", "refuse"])
        self.assertIn("input_schema", body["tools"][0])
        self.assertEqual((reply["content"][0]["name"], reply["usage"]["input_tokens"]), ("get_treasury_actions", 900))

    def test_messages_api_requires_key(self):
        import os
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                AnthropicMessages()
        finally:
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved


class EvalScoringTests(unittest.TestCase):
    ACTION_TASK = {"id": "A", "category": "treasury_actions", "in_scope": True, "expected_tools": ["get_treasury_actions"],
                   "expected_arguments": {"firm": "BMNR", "action": "buyback_common"},
                   "expected_record": {"week_end": "2026-07-19", "action": "buyback_common"},
                   "expected_numbers": [[{"field": "usd", "value": "85885800.00"}]]}

    def test_action_argument_windows(self):
        match = lambda args: agent_eval.arguments_match(self.ACTION_TASK, "get_treasury_actions", args, ACTION)
        self.assertTrue(match({"firm": "BMNR", "action": "buyback_common"}))
        self.assertTrue(match({"firm": "BMNR", "action": "buyback_common", "week_from": "2026-07-19", "week_to": "2026-07-19"}))
        self.assertFalse(match({"firm": "BMNR", "action": "buyback_common", "week_from": "2026-07-20"}))
        self.assertFalse(match({"firm": "BMNR", "action": "est_issuance"}))
        self.assertFalse(agent_eval.arguments_match(self.ACTION_TASK, "get_treasury_actions", {"firm": "BMNR", "action": "buyback_common"},
                                                    {"status": "ok", "actions": []}))

    def test_week_defaults_and_unordered_comparison(self):
        latest = agent_eval.LATEST["BMNR"]
        task = {"category": "coins_per_share", "expected_tools": ["get_coins_per_share"],
                "expected_arguments": {"firm": "BMNR", "week_end": latest, "compare_to": "2026-06-07"}, "expected_record": {"week_end": latest}}
        result = lambda week: {"status": "ok", "week": {"week_end": week}}
        self.assertTrue(agent_eval.arguments_match(task, "get_coins_per_share", {"firm": "BMNR", "compare_to": "2026-06-07"}, result(latest)))
        self.assertFalse(agent_eval.arguments_match(task, "get_coins_per_share", {"firm": "BMNR", "week_end": "2026-06-07", "compare_to": latest},
                                                    result("2026-06-07")))
        task["expected_record"] = {"week_end": "2026-06-07"}
        self.assertTrue(agent_eval.arguments_match(task, "get_coins_per_share", {"firm": "BMNR", "week_end": "2026-06-07", "compare_to": latest},
                                                   result("2026-06-07")))

    def test_sec_arguments_are_supersets(self):
        task = {"category": "sec_facts", "expected_tools": ["calculate_metrics"], "expected_record": {"metric": "revenue", "fiscal_year": 2025},
                "expected_arguments": {"cik": "0000320193", "fiscal_years": [2025], "metrics": ["revenue"]}}
        result = {"status": "ok", "results": [{"metric": "revenue", "fiscal_year": 2025, "status": "ok"}]}
        args = {"cik": "0000320193", "fiscal_years": [2024, 2025], "metrics": ["revenue", "net_income"], "as_of": "2026-09-21"}
        self.assertTrue(agent_eval.arguments_match(task, "calculate_metrics", args, result))
        self.assertFalse(agent_eval.arguments_match(task, "get_annual_facts", args, result))
        self.assertFalse(agent_eval.arguments_match(task, "calculate_metrics", {**args, "fiscal_years": [2024]}, result))

    def test_score_and_summary(self):
        answered = {"status": "answered", "answer": "BitMine spent $85.9M.", "tool_calls": [{"name": "get_treasury_actions",
                    "arguments": {"firm": "BMNR", "action": "buyback_common"}, "result_index": 0}], "results": [ACTION],
                    "drafts": [{"text": "x", "traces": [{"traced": False}]}, {"text": "y", "traces": [{"traced": True}]}],
                    "traces": [{"traced": True}], "latency_ms": 100.0, "cost_usd": 0.01, "turns": 3,
                    "usage": {"input_tokens": 10, "output_tokens": 5}}
        refused = {**answered, "status": "refused", "answer": None, "tool_calls": [], "results": [], "drafts": [], "traces": [],
                   "latency_ms": 300.0}
        oos = {"id": "O", "category": "out_of_scope", "in_scope": False}
        scores = [agent_eval.score(self.ACTION_TASK, answered), agent_eval.score(oos, refused)]
        self.assertTrue(scores[0]["tool_correct"] and scores[0]["arguments_correct"] and scores[0]["answer_numbers_correct"])
        summary = agent_eval.summarize(scores)
        self.assertEqual(summary["numbers_traced_delivered"]["rate"], 1.0)
        self.assertEqual(summary["numbers_traced_first_draft"], {"passed": 0, "total": 1, "rate": 0.0})
        self.assertEqual(summary["refusal_out_of_scope"]["rate"], 1.0)
        self.assertEqual(summary["latency_ms"]["p50"], 200.0)


class TranscriptViewerTests(unittest.TestCase):
    def test_static_viewer_escapes_and_has_no_script(self):
        import importlib.util
        import tempfile
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("viewer", root / "scripts" / "render_agent_transcripts.py")
        viewer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(viewer)
        run_record = {"task_id": "O01", "status": "refused", "refusal": "<script>alert(1)</script>", "answer": None, "tool_calls": [],
                      "results": [], "drafts": [], "traces": [], "latency_ms": 10.0, "cost_usd": None, "turns": 1,
                      "usage": {"input_tokens": 1, "output_tokens": 1}}
        report = agent_eval.report(agent_eval.TASKS, [run_record], {"backend": "scripted", "models_seen": ["m"]})
        with tempfile.TemporaryDirectory() as directory:
            runs, scored = Path(directory) / "runs.jsonl", Path(directory) / "eval.json"
            runs.write_text(json.dumps({"meta": {}}) + "\n" + json.dumps(run_record) + "\n")
            scored.write_text(json.dumps(report))
            html = viewer.render(runs, scored)
        self.assertNotIn("<script", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Should I buy MSTR stock right now?", html)


if __name__ == "__main__":
    unittest.main()
