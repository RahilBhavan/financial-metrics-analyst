"""Absolute-path MCP launcher; works regardless of the client's working directory."""

import sys
from pathlib import Path

# python -P (safe path) omits the script directory, so add the package root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from financial_metrics.server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
