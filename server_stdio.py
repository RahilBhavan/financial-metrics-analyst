"""Absolute-path MCP launcher; works regardless of the client's working directory."""

from financial_metrics.server import main

if __name__ == "__main__":
    raise SystemExit(main())
