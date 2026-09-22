"""Optional operator-run SEC snapshot acquisition. Never exposed through MCP."""

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .policy import CIK, Refusal

ENDPOINTS = {
    "companyfacts.json": "https://data.sec.gov/api/xbrl/companyfacts/CIK" + CIK + ".json",
    "submissions.json": "https://data.sec.gov/submissions/CIK" + CIK + ".json",
}
MAX_BYTES = 8 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refusal("redirect_refused", "SEC client does not follow redirects.")


class SECClient:
    def __init__(self, user_agent, opener=None, sleep=time.sleep):
        if (not isinstance(user_agent, str) or len(user_agent) > 200 or not re.fullmatch(r"[\x20-\x7e]+", user_agent)
                or "@" not in user_agent):
            raise Refusal("invalid_user_agent", "Use an identifying ASCII User-Agent containing your real contact email.")
        self.user_agent = user_agent
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.sleep = sleep

    def get(self, filename):
        if filename not in ENDPOINTS:
            raise Refusal("endpoint_refused", "Only the two fixed Apple SEC endpoints are allowed.")
        for attempt in range(3):
            self.sleep(0.5)
            request = urllib.request.Request(ENDPOINTS[filename], headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            try:
                with self.opener.open(request, timeout=10) as response:
                    if response.geturl() != ENDPOINTS[filename]:
                        raise Refusal("redirect_refused", "Unexpected response URL.")
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise Refusal("response_too_large", "SEC response exceeds 8 MiB.")
                try:
                    document = json.loads(raw)
                    if str(document["cik"]).zfill(10) != CIK:
                        raise Refusal("wrong_entity", "SEC response identifies a different issuer.")
                except (ValueError, KeyError, TypeError):
                    raise Refusal("invalid_response", "SEC did not return the expected JSON document.")
                return raw
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise Refusal("sec_http_error", "SEC returned HTTP " + str(exc.code) + "; existing offline snapshot is unchanged.")
                self.sleep(2 ** attempt)
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise Refusal("sec_unavailable", "SEC request failed after three attempts; use the bundled offline snapshot.")
                self.sleep(2 ** attempt)
        raise Refusal("sec_unavailable", "SEC request failed.")


def manifest_for(payloads, captured_at):
    return {"evidence_kind": "sec_api_snapshot", "captured_at": captured_at,
            "scope_review": "Apple FY2023-FY2025 only; future annual periods require human review.",
            "files": {name: {"source_url": ENDPOINTS[name], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                      for name, raw in payloads.items()}}


def fetch_snapshot(output_dir, user_agent):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise Refusal("target_exists", "Choose a new directory; existing snapshots are never overwritten.")
    client = SECClient(user_agent)
    payloads = {name: client.get(name) for name in ENDPOINTS}
    captured_at = datetime.now(timezone.utc).isoformat()
    manifest = manifest_for(payloads, captured_at)
    # Both requests succeed before creating any deliverable.
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (output_dir / name).write_bytes(raw)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"status": "ok", "directory": str(output_dir), "manifest": manifest}
