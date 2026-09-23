"""Selection and arithmetic have no network, model, shell, or write access."""

import hashlib
import json
import os
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
from pathlib import Path

from .policy import CIK, TAGS, MAX_YEARS, METRICS, POLICY, PROFILES, Refusal

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise Refusal("invalid_date", "Dates must use YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise Refusal("invalid_date", "Date does not exist.")


def today():
    # A fixed clock (YYYY-MM-DD) makes regenerated reports byte-identical across runs.
    fixed = os.environ.get("FINANCIAL_METRICS_TODAY")
    return iso_date(fixed) if fixed else date.today()


def number(value):
    # A JSON float must never be rounded through a binary float on ingestion.
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise Refusal("invalid_value", "Financial values must be exact decimal numbers.")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise Refusal("invalid_value", "Invalid decimal financial value.")
    if not result.is_finite() or len(result.as_tuple().digits) > 30 or abs(result.adjusted()) > 24:
        raise Refusal("invalid_value", "Financial value is nonfinite or outside size limits.")
    return result


def decimal_text(value):
    return format(value, "f")


def percentage(numerator, denominator):
    """Retain an exact fraction because repeating ratios have no finite decimal."""
    ratio = Fraction(numerator) * 100 / Fraction(denominator)
    with localcontext() as context:
        context.prec = 34
        context.rounding = ROUND_HALF_EVEN
        value = Decimal(ratio.numerator) / Decimal(ratio.denominator)
        # Quantization needs room for all integer digits even for extreme ratios.
        context.prec = max(34, value.adjusted() + 3)
        return {
            "value": decimal_text(value),
            "display_value": decimal_text(value.quantize(Decimal("0.01"))),
            "exact_fraction": {"numerator": str(ratio.numerator), "denominator": str(ratio.denominator)},
            "precision": {"significant_digits": 34, "rounding": "ROUND_HALF_EVEN", "display_places": 2},
        }


class Analyst:
    def __init__(self, data_dir=DEFAULT_DATA, profile=None):
        self.data_dir = Path(data_dir)
        try:
            self.manifest = json.loads((self.data_dir / "manifest.json").read_text())
            payloads = {}
            for name in ("companyfacts.json", "submissions.json"):
                raw = (self.data_dir / name).read_bytes()
                if len(raw) > 8 * 1024 * 1024:
                    raise Refusal("invalid_snapshot", "Snapshot exceeds the size limit.")
                if hashlib.sha256(raw).hexdigest() != self.manifest["files"][name]["sha256"]:
                    raise Refusal("snapshot_integrity", "Snapshot hash does not match its manifest.")
                payloads[name] = json.loads(raw, parse_float=Decimal)
            self.facts = payloads["companyfacts.json"]
            self.submissions = payloads["submissions.json"]
            identity = str(self.facts["cik"]).zfill(10)
            self.profile = profile or PROFILES.get(identity)
            if self.profile is None:
                raise Refusal("unsupported_company", "Snapshot issuer has no reviewed profile.")
            self.cik = self.profile["cik"]
            self.periods = self.profile["periods"]
            self.support_periods = self.profile["support_periods"]
            self.captured_date = iso_date(self.manifest["captured_at"][:10])
            if self.manifest["evidence_kind"] != "sec_api_snapshot":
                raise Refusal("invalid_snapshot", "This loader requires a labeled SEC API snapshot.")
            if identity != self.cik or str(self.submissions["cik"]).zfill(10) != self.cik:
                raise Refusal("wrong_entity", "Snapshot identity does not match the reviewed issuer.")
            recent = self.submissions["filings"]["recent"]
            keys = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
            if len({len(recent[k]) for k in keys}) != 1:
                raise Refusal("invalid_snapshot", "Filing metadata arrays have different lengths.")
            self.filings = {}
            for i, accn in enumerate(recent["accessionNumber"]):
                record = {k: recent[k][i] for k in keys}
                if accn in self.filings and self.filings[accn] != record:
                    raise Refusal("invalid_snapshot", "Conflicting accession metadata.")
                self.filings[accn] = record
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise Refusal("invalid_snapshot", "Missing or malformed snapshot files: " + type(exc).__name__)

    def context(self, as_of):
        warnings = []
        age = (today() - self.captured_date).days
        if age > 7:
            warnings.append("snapshot_older_than_7_days: historical results only; refresh separately for current coverage")
        unreviewed = [f["reportDate"] for f in self.filings.values()
                      if f["form"] == "10-K" and f["filingDate"] <= as_of and f["reportDate"] > self.periods[max(self.periods)][1]]
        if unreviewed:
            warnings.append("newer_annual_filing_outside_reviewed_scope: " + ", ".join(sorted(set(unreviewed))))
        return {
            "company": {k: self.profile[k] for k in ("cik", "name", "ticker")},
            "as_of": as_of, "snapshot_captured_at": self.manifest["captured_at"],
            "evidence_kind": self.manifest["evidence_kind"],
            "snapshot_sha256": self.manifest["files"]["companyfacts.json"]["sha256"],
            "policy": POLICY, "warnings": warnings,
        }

    def resolve_company(self, ticker):
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Za-z]{1,5}", ticker):
            raise Refusal("invalid_ticker", "Supply one ticker, for example AAPL.")
        if ticker.upper() != self.profile["ticker"] or self.submissions.get("tickers", []).count(self.profile["ticker"]) != 1:
            raise Refusal("unsupported_company", "Ticker does not match this verified issuer snapshot.")
        return {"status": "ok", **{k: self.profile[k] for k in ("cik", "name", "ticker")},
                "lookup_timestamp": self.manifest["captured_at"], "lookup_is_cached": True,
                "source_url": "https://data.sec.gov/submissions/CIK" + self.cik + ".json"}

    def validate(self, cik, fiscal_years, metrics, as_of, allowed):
        if cik != self.cik:
            raise Refusal("unsupported_company", "CIK does not match this reviewed issuer.")
        if not isinstance(fiscal_years, list) or not 1 <= len(fiscal_years) <= MAX_YEARS:
            raise Refusal("unsupported_years", "Request 1 to " + str(MAX_YEARS) + " reviewed fiscal years.")
        if any(type(y) is not int or y not in self.periods for y in fiscal_years) or len(set(fiscal_years)) != len(fiscal_years):
            raise Refusal("unsupported_years", "Supported years for this issuer are: " + ", ".join(map(str, sorted(self.periods))) + ".")
        if (not isinstance(metrics, list) or not 1 <= len(metrics) <= len(allowed)
                or any(not isinstance(m, str) or m not in allowed for m in metrics)
                or len(set(metrics)) != len(metrics)):
            raise Refusal("unsupported_metric", "Supported metrics: " + ", ".join(allowed))
        requested_date = iso_date(as_of)
        if requested_date > self.captured_date:
            raise Refusal("as_of_after_snapshot", "Cannot establish facts after snapshot date " + str(self.captured_date))

    def _select(self, year, metric, as_of):
        start, end = {**self.support_periods, **self.periods}[year]
        tag = self.profile.get("tags", TAGS)[metric]
        eligible, rejected, dangerous = [], [], []
        counts = Counter()
        units = self.facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
        for unit, rows in units.items():
            for raw in rows:
                # Other years are irrelevant; retain same-end quarter/instant traps.
                if raw.get("end") != end:
                    continue
                reason = None
                accn = raw.get("accn", "")
                filing = self.filings.get(accn)
                known_date = filing["filingDate"] if filing else raw.get("filed")
                try:
                    stamp = iso_date(known_date).isoformat()
                except Refusal:
                    stamp = None
                try:
                    duration = (iso_date(end) - iso_date(raw.get("start"))).days + 1
                except Refusal:
                    duration = None
                annual_candidate = ((filing and filing["form"] in ("10-K", "10-K/A")) or raw.get("form") in ("10-K", "10-K/A")) and (duration is None or duration >= 300)
                if stamp and stamp > as_of:
                    reason = "filed_after_as_of"
                elif raw.get("start") != start:
                    reason = "period_mismatch"
                elif unit != "USD":
                    reason = "unit_mismatch"
                elif raw.get("form") not in ("10-K", "10-K/A") or raw.get("fp") != "FY":
                    reason = "not_annual_filing"
                else:
                    try:
                        filed = iso_date(raw.get("filed"))
                        if filed > iso_date(as_of):
                            reason = "filing_metadata_mismatch"
                        elif filed < iso_date(end):
                            reason = "filed_before_period_end"
                        elif (not filing or filing["form"] != raw["form"] or filing["filingDate"] != raw["filed"]
                              or filing["reportDate"] < end or type(raw.get("fy")) is not int
                              or raw["fy"] != int(filing["reportDate"][:4])):
                            reason = "filing_metadata_mismatch"
                        elif not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accn) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.htm[l]?", filing["primaryDocument"]):
                            reason = "unsafe_source_identifier"
                        else:
                            value = number(raw.get("val"))
                    except (Refusal, ValueError):
                        reason = "invalid_fact"
                if reason:
                    counts[reason] += 1
                    detail = {"accn": str(accn)[:100], "start": str(raw["start"])[:80] if raw.get("start") is not None else None,
                              "end": end, "unit": str(unit)[:80], "filed": stamp, "reason": reason}
                    if len(rejected) < 20:
                        rejected.append(detail)
                    if annual_candidate and reason != "filed_after_as_of":
                        dangerous.append(detail)
                    continue
                eligible.append({
                    "cik": self.cik, "metric": metric, "value": decimal_text(value), "unit": unit,
                    "period_start": start, "period_end": end, "fiscal_year": year,
                    "reported_fy": raw["fy"], "fp": raw["fp"], "form": raw["form"],
                    "filed": raw["filed"], "accn": accn, "tag": "us-gaap:" + tag,
                    "source_url": "https://www.sec.gov/Archives/edgar/data/" + str(int(self.cik)) + "/" + accn.replace("-", "") + "/" + filing["primaryDocument"],
                })
        audit = {"rejection_counts": dict(counts), "rejected_candidates": rejected,
                 "rejected_candidates_truncated": sum(counts.values()) - len(rejected)}
        base = {"fiscal_year": year, "metric": metric, "period_start": start, "period_end": end, **audit}
        if not eligible:
            return {**base, "status": "insufficient_data", "reason": "standard_tag_absent" if not units else "no_eligible_annual_USD_fact", "value": None}
        return self._choose(base, eligible, dangerous)

    @staticmethod
    def _choose(base, eligible, dangerous):
        """Shared by annual and quarterly selection: same-date conflicts and newer invalid candidates never fall back."""
        eligible.sort(key=lambda f: (f["filed"], f["accn"]))
        by_date = {}
        for fact in eligible:
            by_date.setdefault(fact["filed"], set()).add(number(fact["value"]))
        if any(len(values) != 1 for values in by_date.values()):
            return {**base, "status": "ambiguous", "reason": "conflicting_values_on_same_filing_date", "value": None}
        selected = eligible[-1]
        blockers = [r for r in dangerous if r["filed"] is None or r["filed"] >= selected["filed"]]
        if blockers:
            return {**base, "status": "insufficient_data", "reason": "newer_or_same_date_candidate_invalid",
                    "value": None, "blocking_candidates": blockers[:20], "blocking_candidates_total": len(blockers)}
        # Preserve all distinct filing/value records, including original provenance.
        history = list({(f["accn"], f["value"]): f for f in eligible}.values())
        changed = len({number(f["value"]) for f in history}) > 1
        return {**base, **selected, "status": "ok", "original": history[0], "history": history,
                "revision_candidate": changed,
                "warnings": ["value_changed_across_filings: review revision history"] if changed else []}

    def get_annual_facts(self, cik, fiscal_years, metrics, as_of):
        self.validate(cik, fiscal_years, metrics, as_of, tuple(TAGS))
        results = [self._select(y, m, as_of) for y in sorted(fiscal_years) for m in metrics]
        return self._response(results, as_of)

    def get_quarterly_facts(self, cik, fiscal_year, quarter, metrics, as_of):
        if cik != self.cik:
            raise Refusal("unsupported_company", "CIK does not match this reviewed issuer.")
        key = (fiscal_year, quarter)
        quarters = self.profile.get("quarters", {})
        if key not in quarters:
            raise Refusal("unsupported_quarter", "This issuer does not have that reviewed fiscal quarter.")
        if (not isinstance(metrics, list) or not 1 <= len(metrics) <= len(TAGS)
                or len(set(metrics)) != len(metrics) or any(metric not in TAGS for metric in metrics)):
            raise Refusal("unsupported_metric", "Quarterly facts support: " + ", ".join(TAGS))
        if iso_date(as_of) > self.captured_date:
            raise Refusal("as_of_after_snapshot", "Cannot establish facts after snapshot date " + str(self.captured_date))
        start, end = quarters[key]
        results = [self._select_quarter(fiscal_year, quarter, start, end, metric, as_of) for metric in metrics]
        return self._response(results, as_of)

    def _select_quarter(self, fiscal_year, quarter, start, end, metric, as_of):
        tag = self.profile.get("tags", TAGS)[metric]
        eligible, rejected, dangerous = [], [], []
        counts = Counter()
        units = self.facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
        for unit, rows in units.items():
            for raw in rows:
                if raw.get("end") != end:
                    continue
                reason = None
                accn = raw.get("accn", "")
                filing = self.filings.get(accn)
                known_date = filing["filingDate"] if filing else raw.get("filed")
                try:
                    stamp = iso_date(known_date).isoformat()
                except Refusal:
                    stamp = None
                try:
                    duration = (iso_date(end) - iso_date(raw.get("start"))).days + 1
                except Refusal:
                    duration = None
                # Quarter-length or unknown-length 10-Q records can block; year-to-date records cannot.
                quarter_candidate = ((filing and filing["form"] in ("10-Q", "10-Q/A")) or raw.get("form") in ("10-Q", "10-Q/A")) and (duration is None or duration < 120)
                if stamp and stamp > as_of:
                    reason = "filed_after_as_of"
                elif raw.get("start") != start:
                    reason = "period_mismatch"
                elif unit != "USD":
                    reason = "unit_mismatch"
                elif raw.get("form") not in ("10-Q", "10-Q/A") or raw.get("fp") != quarter:
                    reason = "not_quarterly_filing"
                else:
                    try:
                        if iso_date(raw.get("filed")) > iso_date(as_of):
                            reason = "filing_metadata_mismatch"
                        elif (not filing or filing["form"] != raw["form"] or filing["filingDate"] != raw["filed"]
                              or filing["reportDate"] != end or raw.get("fy") != fiscal_year):
                            reason = "filing_metadata_mismatch"
                        elif not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accn) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.htm[l]?", filing["primaryDocument"]):
                            reason = "unsafe_source_identifier"
                        else:
                            value = number(raw.get("val"))
                    except Refusal:
                        reason = "invalid_fact"
                if reason:
                    counts[reason] += 1
                    detail = {"accn": str(accn)[:100], "start": str(raw["start"])[:80] if raw.get("start") is not None else None,
                              "end": end, "unit": str(unit)[:80], "filed": stamp, "reason": reason}
                    if len(rejected) < 20:
                        rejected.append(detail)
                    if quarter_candidate and reason != "filed_after_as_of":
                        dangerous.append(detail)
                    continue
                eligible.append({
                    "cik": self.cik, "metric": metric, "value": decimal_text(value), "unit": unit,
                    "period_start": start, "period_end": end, "fiscal_year": fiscal_year,
                    "reported_fy": raw["fy"], "fp": raw["fp"], "form": raw["form"], "filed": raw["filed"],
                    "accn": accn, "tag": "us-gaap:" + tag,
                    "source_url": "https://www.sec.gov/Archives/edgar/data/" + str(int(self.cik)) + "/" + accn.replace("-", "") + "/" + filing["primaryDocument"],
                })
        audit = {"rejection_counts": dict(counts), "rejected_candidates": rejected,
                 "rejected_candidates_truncated": sum(counts.values()) - len(rejected)}
        base = {"fiscal_year": fiscal_year, "metric": metric, "period_start": start, "period_end": end, **audit}
        if not eligible:
            return {**base, "status": "insufficient_data", "reason": "no_eligible_quarterly_USD_fact", "value": None}
        return self._choose(base, eligible, dangerous)

    def _response(self, results, as_of):
        return {"status": "ok" if all(r["status"] == "ok" for r in results) else "partial",
                "context": self.context(as_of), "results": results}

    def calculate_metrics(self, cik, fiscal_years, metrics, as_of):
        self.validate(cik, fiscal_years, metrics, as_of, METRICS)
        results = []
        for year in sorted(fiscal_years):
            for metric in metrics:
                if metric in TAGS:
                    results.append(self._select(year, metric, as_of))
                    continue
                base = {"fiscal_year": year, "metric": metric, "unit": "percent",
                        "period_start": self.periods[year][0], "period_end": self.periods[year][1], "value": None}
                if metric == "revenue_growth" and year - 1 not in {**self.support_periods, **self.periods}:
                    results.append({**base, "status": "insufficient_data", "reason": "prior_year_outside_reviewed_scope"})
                    continue
                revenue = self._select(year, "revenue", as_of)
                if metric == "operating_margin":
                    other = self._select(year, "operating_income", as_of)
                elif metric == "gross_margin":
                    other = self._select(year, "gross_profit", as_of)
                else:
                    other = self._select(year - 1, "revenue", as_of)
                inputs = [revenue, other]
                base["inputs"] = inputs
                if any(f["status"] != "ok" for f in inputs):
                    results.append({**base, "status": "insufficient_data", "reason": "operand_unavailable"})
                    continue
                basis_warnings = []
                if revenue["accn"] != other["accn"] and metric == "revenue_growth":
                    left = {f["accn"]: f for f in revenue["history"]}
                    right = {f["accn"]: f for f in other["history"]}
                    common = [a for a in left.keys() & right.keys()
                              if number(left[a]["value"]) == number(revenue["value"])
                              and number(right[a]["value"]) == number(other["value"])]
                    if common:
                        accn = max(common, key=lambda a: (left[a]["filed"], a))
                        basis_warnings.append("comparison_uses_common_filing: " + accn + "; both values match latest eligible disclosures")
                        revenue = {**revenue, **left[accn]}
                        other = {**other, **right[accn]}
                        inputs = [revenue, other]
                        base["inputs"] = inputs
                if revenue["accn"] != other["accn"]:
                    results.append({**base, "status": "insufficient_data", "reason": "inconsistent_filing_basis"})
                    continue
                current, previous = number(revenue["value"]), number(other["value"])
                denominator = current if metric in ("operating_margin", "gross_margin") else previous
                if denominator <= 0:
                    results.append({**base, "status": "insufficient_data", "reason": "nonpositive_revenue_denominator"})
                    continue
                warnings = sorted(set(revenue["warnings"] + other["warnings"] + basis_warnings))
                if metric == "revenue_growth":
                    if (iso_date(revenue["period_start"]) - iso_date(other["period_end"])).days != 1:
                        results.append({**base, "status": "insufficient_data", "reason": "noncontiguous_periods"})
                        continue
                    durations = [(iso_date(f["period_end"]) - iso_date(f["period_start"])).days + 1 for f in inputs]
                    if durations[0] != durations[1]:
                        warnings.append("unequal_period_lengths: current " + str(durations[0]) + " days, prior " + str(durations[1]) + " days; reported growth, not week-normalized")
                    # Fraction subtraction avoids ambient Decimal context rounding.
                    numerator = Fraction(current) - Fraction(previous)
                    formula = "(current_revenue - prior_revenue) / prior_revenue * 100"
                else:
                    numerator = previous
                    formula = ("gross_profit / revenue * 100" if metric == "gross_margin"
                               else "operating_income / revenue * 100")
                results.append({**base, **percentage(numerator, denominator), "status": "ok", "formula": formula, "warnings": warnings})
        return self._response(results, as_of)


class AnalystService:
    """Route the tools to fixed reviewed issuer snapshots."""

    def __init__(self, data_dir=DEFAULT_DATA):
        root = Path(data_dir)
        primary = Analyst(root)
        self.issuers = {primary.cik: primary}
        if root.resolve() == DEFAULT_DATA.resolve():
            for cik, profile in PROFILES.items():
                if cik != primary.cik:
                    self.issuers[cik] = Analyst(root / profile["directory"])

    def resolve_company(self, ticker):
        if not isinstance(ticker, str):
            raise Refusal("invalid_ticker", "Ticker must be a string.")
        matches = [a for a in self.issuers.values() if a.profile["ticker"] == ticker.upper()]
        if len(matches) != 1:
            raise Refusal("unsupported_company", "Reviewed companies are AAPL, MSFT, and NVDA; custom snapshots contain only their own issuer.")
        return matches[0].resolve_company(ticker)

    def _issuer(self, cik):
        if not isinstance(cik, str) or cik not in self.issuers:
            raise Refusal("unsupported_company", "CIK is not in the loaded reviewed snapshots.")
        return self.issuers[cik]

    def get_annual_facts(self, cik, fiscal_years, metrics, as_of):
        return self._issuer(cik).get_annual_facts(cik, fiscal_years, metrics, as_of)

    def calculate_metrics(self, cik, fiscal_years, metrics, as_of):
        return self._issuer(cik).calculate_metrics(cik, fiscal_years, metrics, as_of)

    def get_quarterly_facts(self, cik, fiscal_year, quarter, metrics, as_of):
        return self._issuer(cik).get_quarterly_facts(cik, fiscal_year, quarter, metrics, as_of)
