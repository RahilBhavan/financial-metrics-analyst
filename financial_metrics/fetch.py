"""Optional operator-run SEC snapshot acquisition. Never exposed through MCP."""

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .policy import MAX_SNAPSHOT_BYTES, PROFILES, Refusal

TICKER_CIKS = {profile["ticker"]: cik for cik, profile in PROFILES.items()}


def endpoints_for(cik):
    return {
        "companyfacts.json": "https://data.sec.gov/api/xbrl/companyfacts/CIK" + cik + ".json",
        "submissions.json": "https://data.sec.gov/submissions/CIK" + cik + ".json",
    }


ENDPOINTS = endpoints_for(TICKER_CIKS["AAPL"])
MAX_BYTES = MAX_SNAPSHOT_BYTES
MAX_SUBMISSION_PAGES = 10
SUBMISSIONS_URL = "https://data.sec.gov/submissions/"


def page_names(cik, submissions_raw):
    """SEC moves filings beyond the newest ~1,000 into paged files; old 10-Ks are needed for history."""
    try:
        files = json.loads(submissions_raw)["filings"].get("files", [])
        names = [entry["name"] for entry in files]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Refusal("invalid_response", "SEC submissions did not describe its paged filing history.")
    if len(names) > MAX_SUBMISSION_PAGES or any(not isinstance(n, str) or not re.fullmatch("CIK" + cik + r"-submissions-[0-9]{3}\.json", n) for n in names):
        raise Refusal("invalid_response", "Unexpected SEC submissions page names.")
    return names


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refusal("redirect_refused", "SEC client does not follow redirects.")


class SECClient:
    def __init__(self, user_agent, cik=TICKER_CIKS["AAPL"], opener=None, sleep=time.sleep):
        if (not isinstance(user_agent, str) or len(user_agent) > 200 or not re.fullmatch(r"[\x20-\x7e]+", user_agent)
                or "@" not in user_agent):
            raise Refusal("invalid_user_agent", "Use an identifying ASCII User-Agent containing your real contact email.")
        self.user_agent = user_agent
        if cik not in PROFILES:
            raise Refusal("unsupported_company", "Refresh supports the reviewed issuers: " + ", ".join(sorted(TICKER_CIKS)) + ".")
        self.cik = cik
        self.endpoints = endpoints_for(cik)
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.sleep = sleep

    def allow_pages(self, names):
        for name in names:
            self.endpoints[name] = SUBMISSIONS_URL + name

    def get(self, filename):
        if filename not in self.endpoints:
            raise Refusal("endpoint_refused", "Only the fixed SEC companyfacts and submissions endpoints are allowed.")
        page = filename not in ("companyfacts.json", "submissions.json")
        for attempt in range(3):
            self.sleep(0.5)
            request = urllib.request.Request(self.endpoints[filename], headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            try:
                with self.opener.open(request, timeout=10) as response:
                    if response.geturl() != self.endpoints[filename]:
                        raise Refusal("redirect_refused", "Unexpected response URL.")
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise Refusal("response_too_large", "SEC response exceeds " + str(MAX_BYTES // (1024 * 1024)) + " MiB.")
                try:
                    document = json.loads(raw)
                    # Paged submissions hold bare filing arrays without an issuer field.
                    if page and not isinstance(document["accessionNumber"], list):
                        raise TypeError()
                    if not page and str(document["cik"]).zfill(10) != self.cik:
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


def manifest_for(payloads, captured_at, cik):
    profile = PROFILES[cik]
    endpoints = {**endpoints_for(cik), **{name: SUBMISSIONS_URL + name for name in payloads if name.startswith("CIK")}}
    return {"evidence_kind": "sec_api_snapshot", "captured_at": captured_at,
            "scope_review": profile["ticker"] + " reviewed periods only; future periods require human review.",
            "files": {name: {"source_url": endpoints[name], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                      for name, raw in payloads.items()}}


def fetch_snapshot(output_dir, user_agent, ticker="AAPL"):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise Refusal("target_exists", "Choose a new directory; existing snapshots are never overwritten.")
    if not isinstance(ticker, str) or ticker.upper() not in TICKER_CIKS:
        raise Refusal("unsupported_company", "Refresh supports: " + ", ".join(sorted(TICKER_CIKS)) + ".")
    cik = TICKER_CIKS[ticker.upper()]
    client = SECClient(user_agent, cik)
    payloads = {name: client.get(name) for name in endpoints_for(cik)}
    pages = page_names(cik, payloads["submissions.json"])
    client.allow_pages(pages)
    payloads.update({name: client.get(name) for name in pages})
    captured_at = datetime.now(timezone.utc).isoformat()
    manifest = manifest_for(payloads, captured_at, cik)
    # Every request succeeds before creating any deliverable.
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (output_dir / name).write_bytes(raw)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"status": "ok", "directory": str(output_dir), "manifest": manifest}
