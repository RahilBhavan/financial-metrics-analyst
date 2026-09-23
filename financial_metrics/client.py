"""A real subprocess MCP client for demos and transport tests, no paid API."""

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

from .server import VERSION


class Client:
    def __init__(self, data_dir=None):
        command = [sys.executable, "-B", "-m", "financial_metrics.server"]
        if data_dir is not None:
            command.extend(["--data-dir", str(Path(data_dir).resolve())])
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, cwd=str(Path(__file__).resolve().parent.parent),
                                        text=True, encoding="utf-8", bufsize=1)
        self.responses = queue.Queue()
        self.diagnostics = []
        self.next_id = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self.stderr_reader.start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.responses.put(json.loads(line))
            except ValueError:
                self.responses.put(RuntimeError("Non-JSON data on server stdout"))
        self.responses.put(RuntimeError("Server closed stdout"))

    def _read_stderr(self):
        for line in self.process.stderr:
            if len(self.diagnostics) < 20:
                self.diagnostics.append(line.rstrip())

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        try:
            response = self.responses.get(timeout=10)
        except queue.Empty:
            raise RuntimeError("MCP server did not respond within 10 seconds")
        if isinstance(response, Exception):
            raise response
        if response.get("id") != self.next_id or response.get("jsonrpc") != "2.0":
            raise RuntimeError("Invalid response correlation")
        return response

    def initialize(self):
        reply = self.request("initialize", {"protocolVersion": VERSION, "capabilities": {},
                                             "clientInfo": {"name": "financial-metrics-demo", "version": "0.1.0"}})
        if reply.get("result", {}).get("protocolVersion") != VERSION:
            raise RuntimeError("MCP protocol negotiation failed")
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return reply["result"]

    def call(self, name, arguments):
        reply = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in reply:
            raise RuntimeError(reply["error"]["message"])
        result = reply["result"]
        if json.loads(result["content"][0]["text"]) != result["structuredContent"]:
            raise RuntimeError("Text and structured results differ")
        return result["structuredContent"]

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        self.stderr_reader.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        try:
            self.initialize()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *args):
        self.close()


def smoke(data_dir=None):
    with Client(data_dir) as client:
        names = [t["name"] for t in client.request("tools/list")["result"]["tools"]]
        if names != ["resolve_company", "get_annual_facts", "get_quarterly_facts", "calculate_metrics"]:
            raise RuntimeError("Unexpected tool list")
        resolved = client.call("resolve_company", {"ticker": "AAPL"})
        as_of = resolved["lookup_timestamp"][:10]
        args = {"cik": resolved["cik"], "fiscal_years": [2023, 2024, 2025], "as_of": as_of}
        facts = client.call("get_annual_facts", {**args, "metrics": ["revenue", "operating_income", "net_income"]})
        metrics = client.call("calculate_metrics", {**args, "metrics": ["operating_margin", "revenue_growth"]})
        refused = client.call("calculate_metrics", {**args, "metrics": ["ebitda"]})
        if facts["status"] != "ok" or refused["status"] != "refused":
            raise RuntimeError("Smoke result mismatch")
        counts = {"facts": len(facts["results"]), "numeric_ratios": sum(r["status"] == "ok" for r in metrics["results"])}
        if counts != {"facts": 9, "numeric_ratios": 6}:
            raise RuntimeError("Unexpected metric coverage")
    return {"status": "ok", "protocol": VERSION, "transport": "stdio subprocess",
            "tools": names, **counts, "unsupported_metric_refused": True, "server_exit_code": client.process.returncode}


if __name__ == "__main__":
    print(json.dumps(smoke(), indent=2))
