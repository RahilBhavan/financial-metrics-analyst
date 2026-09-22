"""Small MCP stdio server for the pinned 2025-11-25 protocol subset.

Implements initialization, ping, tools/list, and tools/call. No HTTP, sampling,
resources, tasks, or arbitrary execution. stdout is reserved for JSON-RPC.
"""

import argparse
import json
import sys

from .domain import AnalystService, DEFAULT_DATA
from .policy import Refusal
from .tools import TOOLS, call_tool

VERSION = "2025-11-25"
MAX_LINE = 65536


def error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class Session:
    def __init__(self, analyst):
        self.analyst = analyst
        self.initialized = False
        self.ready = False

    def receive(self, message):
        if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
                or not isinstance(message.get("method"), str)):
            return error(None, -32600, "Invalid JSON-RPC request")
        request_id = message.get("id")
        notification = "id" not in message
        if not notification and (type(request_id) not in (int, str)):
            return error(None, -32600, "Request id must be a string or integer")
        method = message["method"]
        params = message.get("params", {})
        if not isinstance(params, dict):
            return None if notification else error(request_id, -32602, "params must be an object")
        if notification:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None
        if method == "initialize":
            if self.initialized:
                return error(request_id, -32600, "Session already initialized")
            if (not isinstance(params.get("protocolVersion"), str)
                    or not isinstance(params.get("capabilities"), dict)
                    or not isinstance(params.get("clientInfo"), dict)
                    or not all(isinstance(params["clientInfo"].get(k), str) for k in ("name", "version"))):
                return error(request_id, -32602, "Invalid initialization parameters")
            self.initialized = True
            # MCP negotiation returns a supported version if the offered version differs.
            result = {"protocolVersion": VERSION, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "financial-metrics-analyst", "version": "0.1.0"},
                      "instructions": "Use structuredContent. Missing values are not zero. Preserve period, revision, snapshot, and comparability warnings."}
        elif method == "ping":
            result = {}
        elif not self.ready:
            return error(request_id, -32600, "Complete initialize and notifications/initialized first")
        elif method == "tools/list":
            if params.get("cursor") is not None:
                return error(request_id, -32602, "This fixed tool list has no pagination cursor")
            result = {"tools": TOOLS}
        elif method == "tools/call":
            if not isinstance(params.get("name"), str):
                return error(request_id, -32602, "Tool name is required")
            try:
                result = call_tool(self.analyst, params["name"], params.get("arguments", {}))
            except Refusal:
                return error(request_id, -32602, "Unknown tool")
        else:
            return error(request_id, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(analyst, reader=None, writer=None):
    reader = reader or sys.stdin.buffer
    writer = writer or sys.stdout
    session = Session(analyst)
    while True:
        line = reader.readline(MAX_LINE + 1)
        if not line:
            break
        if len(line) > MAX_LINE:
            response = error(None, -32600, "Message exceeds 64 KiB limit; connection closed")
            writer.write(json.dumps(response) + "\n")
            writer.flush()
            return
        try:
            message = json.loads(line.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError, RecursionError):
            response = error(None, -32700, "Invalid UTF-8 JSON")
        else:
            try:
                response = session.receive(message)
            except Exception:
                # Never expose local file paths, arbitrary data, or a traceback to a caller.
                print("Internal tool failure", file=sys.stderr)
                response = None if isinstance(message, dict) and "id" not in message else error(message.get("id") if isinstance(message, dict) else None, -32603, "Internal error")
        if response is not None:
            writer.write(json.dumps(response, allow_nan=False, separators=(",", ":")) + "\n")
            writer.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA))
    args = parser.parse_args()
    try:
        serve(AnalystService(args.data_dir))
    except Refusal as exc:
        print(exc.code + ": " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
