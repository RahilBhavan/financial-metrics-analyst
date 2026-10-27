"""Selection and arithmetic have no network, model, shell, or write access."""

import hashlib
import json
import os
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
from pathlib import Path

from .policy import ANNUAL_TAGS, MAX_SNAPSHOT_BYTES, MAX_YEARS, METRICS, POLICY, PROFILES, QUARTER_METRICS, TAGS, Refusal

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"
FILING_KEYS = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
SUBMISSION_PAGE = r"CIK[0-9]{10}-submissions-[0-9]{3}\.json"
# Same-end records of these lengths could be a corrupted version of the reviewed period, so they block.
# A quarter blocker needs a quarter-like length, so one-month stub periods in a 10-Q do not block.
PERIOD_KINDS = {
    "annual": {"forms": ("10-K", "10-K/A"), "may_block": lambda days: days is None or days >= 300,
               "wrong_form": "not_annual_filing", "none": "no_eligible_annual_USD_fact"},
    "quarter": {"forms": ("10-Q", "10-Q/A"), "may_block": lambda days: days is None or 70 <= days < 120,
                "wrong_form": "not_quarterly_filing", "none": "no_eligible_quarterly_USD_fact"},
}
AUDIT_KEYS = ("rejection_counts", "rejected_candidates", "rejected_candidates_truncated")


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
            pages = sorted(name for name in self.manifest["files"] if re.fullmatch(SUBMISSION_PAGE, name))
            payloads = {}
            for name in ("companyfacts.json", "submissions.json", *pages):
                raw = (self.data_dir / name).read_bytes()
                if len(raw) > MAX_SNAPSHOT_BYTES:
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
            # SEC keeps about 1,000 filings in "recent"; older ones are only in paged files.
            self.filings = {}
            for block in [self.submissions["filings"]["recent"]] + [payloads[name] for name in pages]:
                if len({len(block[k]) for k in FILING_KEYS}) != 1:
                    raise Refusal("invalid_snapshot", "Filing metadata arrays have different lengths.")
                for i, accn in enumerate(block["accessionNumber"]):
                    record = {k: block[k][i] for k in FILING_KEYS}
                    if accn in self.filings and self.filings[accn] != record:
                        raise Refusal("invalid_snapshot", "Conflicting accession metadata.")
                    self.filings[accn] = record
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise Refusal("invalid_snapshot", "Missing or malformed snapshot files: " + type(exc).__name__)

    def fiscal_year_of(self, report_date):
        """Fiscal year a filing reports on: a period ending after the fiscal-year-end month belongs to the next year."""
        year, month = int(report_date[:4]), int(report_date[5:7])
        return year + (1 if month > self.profile.get("fye_month", 12) else 0)

    def context(self, as_of):
        warnings = []
        age = (today() - self.captured_date).days
        if age > 7:
            warnings.append("snapshot_older_than_7_days: historical results only; refresh separately for current coverage")
        unreviewed = [f["reportDate"] for f in self.filings.values()
                      if f["form"] in ("10-K", "10-K/A") and f["filingDate"] <= as_of and f["reportDate"] > self.periods[max(self.periods)][1]]
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
        return self._select_period(year, "FY", start, end, metric, as_of)

    def _fiscal_year_matches(self, raw, filing):
        """The fact's fy is its filing's fiscal year; a later filing repeats a period as a comparative under its own fy."""
        fy = raw.get("fy")
        if type(fy) is not int:
            return False
        report = iso_date(filing["reportDate"])
        if raw["fp"] == "FY":
            # 52/53-week years ending in early January carry the prior calendar year as fy.
            return fy == report.year or (fy == report.year - 1 and (report.month, report.day) <= (1, 7))
        return fy == self.fiscal_year_of(filing["reportDate"])

    def _select_period(self, fiscal_year, fp, start, end, metric, as_of, ytd=False):
        """Annual (fp FY) and quarterly selection share every eligibility and blocking rule."""
        kind = PERIOD_KINDS["annual" if fp == "FY" else "quarter"]
        if ytd:
            expected_duration = (iso_date(end) - iso_date(start)).days + 1
            kind = {**PERIOD_KINDS['quarter'], 'may_block': lambda days: days is None or abs(days - expected_duration) <= 10}
        tag = self.profile.get("tags", TAGS)[metric]
        eligible, rejected, dangerous, unindexed = [], [], [], []
        counts = Counter()
        units = self.facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
        for unit, rows in units.items():
            for raw in rows:
                # Other periods are irrelevant; retain same-end traps such as YTD or instant records.
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
                candidate = (((filing and filing["form"] in kind["forms"]) or raw.get("form") in kind["forms"])
                             and kind["may_block"](duration))
                if stamp and stamp > as_of:
                    reason = "filed_after_as_of"
                elif raw.get("start") != start:
                    reason = "period_mismatch"
                elif unit != "USD":
                    reason = "unit_mismatch"
                elif raw.get("form") not in kind["forms"] or (raw.get("fp") not in ("Q1", "Q2", "Q3") if ytd else raw.get("fp") != fp):
                    reason = kind["wrong_form"]
                elif not filing:
                    reason = "accession_not_indexed"
                else:
                    try:
                        filed = iso_date(raw.get("filed"))
                        if filed > iso_date(as_of):
                            reason = "filing_metadata_mismatch"
                        elif filed < iso_date(end):
                            reason = "filed_before_period_end"
                        elif (filing["form"] != raw["form"] or filing["filingDate"] != raw["filed"]
                              or iso_date(filing["reportDate"]) < iso_date(end)
                              or not self._fiscal_year_matches(raw, filing)):
                            reason = "filing_metadata_mismatch"
                        elif not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accn) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.htm[l]?", filing["primaryDocument"]):
                            reason = "unsafe_source_identifier"
                        else:
                            value = number(raw.get("val"))
                            if metric == "capital_expenditures" and value < 0:
                                raise Refusal("invalid_fact", "Cash capital expenditure payment must be nonnegative.")
                    except (Refusal, ValueError):
                        reason = "invalid_fact"
                if reason:
                    counts[reason] += 1
                    detail = {"accn": str(accn)[:100], "start": str(raw["start"])[:80] if raw.get("start") is not None else None,
                              "end": end, "unit": str(unit)[:80], "filed": stamp, "reason": reason}
                    if len(rejected) < 20:
                        rejected.append(detail)
                    if candidate and reason != "filed_after_as_of":
                        dangerous.append(detail)
                    if reason == "accession_not_indexed":
                        unindexed.append(detail)
                    continue
                eligible.append({
                    "cik": self.cik, "metric": metric, "value": decimal_text(value), "unit": unit,
                    "period_start": start, "period_end": end, "fiscal_year": fiscal_year,
                    "reported_fy": raw["fy"], "fp": raw["fp"], "form": raw["form"],
                    "filed": raw["filed"], "accn": accn, "tag": "us-gaap:" + tag,
                    "source_url": "https://www.sec.gov/Archives/edgar/data/" + str(int(self.cik)) + "/" + accn.replace("-", "") + "/" + filing["primaryDocument"],
                })
        audit = {"rejection_counts": dict(counts), "rejected_candidates": rejected,
                 "rejected_candidates_truncated": sum(counts.values()) - len(rejected)}
        base = {"fiscal_year": fiscal_year, "metric": metric, "period_start": start, "period_end": end, **audit}
        if fp != "FY":
            base["fp"] = fp
        if not eligible:
            return {**base, "status": "insufficient_data", "reason": "standard_tag_absent" if not units else kind["none"], "value": None}
        selected = self._choose(base, eligible, dangerous, unindexed)
        if metric == 'capital_expenditures' and selected['status'] == 'ok':
            basis = {'INTC': 'investing cash capex only; excludes property additions classified in financing activities',
                     'AMD': 'capex excludes discontinued operations; operating cash flow is consolidated',
                     'NVDA': 'includes property, equipment and intangible assets',
                     'V': 'includes property, equipment and technology',
                     'HOOD': 'property and equipment only; excludes separately filed capitalized software'}
            if self.profile['ticker'] in basis:
                selected['warnings'].append('cash_capex_scope: ' + basis[self.profile['ticker']])
        return selected

    @staticmethod
    def _choose(base, eligible, dangerous, unindexed=()):
        """Same-date conflicts and newer invalid candidates never fall back to an older value."""
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
        warnings = ["value_changed_across_filings: review revision history"] if changed else []
        older = sorted({r["accn"] for r in unindexed if r["filed"] is None or r["filed"] < selected["filed"]})
        if older:
            # Without submissions metadata the earliest disclosure cannot be verified, so "original" may be later.
            warnings.append("history_incomplete: earlier filing(s) missing from indexed submissions (" + ", ".join(older[:5])
                            + "); original value and revision status are unverified")
        return {**base, **selected, "status": "ok", "original": history[0], "history": history,
                "revision_candidate": changed, "warnings": warnings}

    def get_annual_facts(self, cik, fiscal_years, metrics, as_of):
        self.validate(cik, fiscal_years, metrics, as_of, tuple(ANNUAL_TAGS))
        results = [self._select(y, m, as_of) for y in sorted(fiscal_years) for m in metrics]
        return self._response(results, as_of)

    def get_quarterly_facts(self, cik, fiscal_year, quarter, metrics, as_of):
        if cik != self.cik:
            raise Refusal("unsupported_company", "CIK does not match this reviewed issuer.")
        key = (fiscal_year, quarter)
        quarters = self.profile.get("quarters", {})
        if key not in quarters:
            raise Refusal("unsupported_quarter", "This issuer does not have that reviewed fiscal quarter.")
        if (not isinstance(metrics, list) or not 1 <= len(metrics) <= len(QUARTER_METRICS)
                or len(set(metrics)) != len(metrics) or any(metric not in QUARTER_METRICS for metric in metrics)):
            raise Refusal("unsupported_metric", "Quarterly facts support: " + ", ".join(QUARTER_METRICS))
        if iso_date(as_of) > self.captured_date:
            raise Refusal("as_of_after_snapshot", "Cannot establish facts after snapshot date " + str(self.captured_date))
        start, end = quarters[key]
        results = [self._select_period(fiscal_year, quarter, start, end, metric, as_of) if metric in TAGS
                   else self._cash_result(fiscal_year, metric, as_of, quarter) for metric in metrics]
        return self._response(results, as_of)

    def _cash_result(self, year, metric, as_of, quarter=None):
        """Exact USD derivations retain every filed operand; never treat a YTD value as a quarter."""
        periods = self.profile['quarters'] if quarter else self.periods
        start, end = periods[(year, quarter) if quarter else year]
        base = {'fiscal_year': year, 'metric': metric, 'unit': 'USD', 'period_start': start,
                'period_end': end, 'fp': quarter or 'FY', 'value': None}
        metrics = ('operating_cash_flow', 'capital_expenditures') if metric == 'free_cash_flow' else (metric,)
        inputs, values, warnings = [], [], []
        for component in metrics:
            if quarter:
                # The preceding 10-K establishes the fiscal-year start, including 52/53-week calendars.
                annual_ends = [f['reportDate'] for f in self.filings.values()
                               if f['form'] == '10-K' and f['reportDate'] < end]
                if not annual_ends:
                    return {**base, 'status': 'insufficient_data', 'reason': 'fiscal_year_start_unavailable', 'inputs': inputs}
                fiscal_start = (iso_date(max(annual_ends)) + timedelta(days=1)).isoformat()
                if not 0 < (iso_date(end) - iso_date(fiscal_start)).days < 300:
                    return {**base, 'status': 'insufficient_data', 'reason': 'invalid_ytd_period', 'inputs': inputs}
                operands = [self._select_period(year, quarter, fiscal_start, end, component, as_of, ytd=True)]
                if quarter != 'Q1':
                    previous_end = (iso_date(start) - timedelta(days=1)).isoformat()
                    operands.append(self._select_period(year, 'Q' + str(int(quarter[1]) - 1), fiscal_start,
                                                        previous_end, component, as_of, ytd=True))
            else:
                operands = [self._select(year, component, as_of)]
            if any(row['status'] != 'ok' for row in operands):
                return {**base, 'status': 'insufficient_data', 'reason': 'operand_unavailable', 'inputs': inputs}
            inputs.extend({k: v for k, v in row.items() if k not in AUDIT_KEYS} for row in operands)
            value = Fraction(number(operands[0]['value']))
            if len(operands) == 2:
                if operands[1]['filed'] > operands[0]['filed']:
                    baseline = self._select_period(year, 'Q' + str(int(quarter[1]) - 1), fiscal_start,
                                                   previous_end, component, operands[0]['filed'], ytd=True)
                    if baseline['status'] != 'ok' or number(baseline['value']) != number(operands[1]['value']):
                        return {**base, 'status': 'insufficient_data', 'reason': 'prior_ytd_revised_after_current_ytd', 'inputs': inputs}
                value -= Fraction(number(operands[1]['value']))
            values.append(value)
            warnings.extend(w for row in operands for w in row['warnings'])
        if len({row['accn'] for row in inputs}) > 1:
            warnings.append('mixed_filing_basis: standalone quarter uses separately filed year-to-date operands')
        if metric == 'free_cash_flow':
            # Compare same endpoints on a common filing basis before subtracting capex.
            width = len(inputs) // 2
            if any(a['accn'] != b['accn'] for a, b in zip(inputs[:width], inputs[width:])):
                return {**base, 'status': 'insufficient_data', 'reason': 'inconsistent_filing_basis', 'inputs': inputs}
            if values[1] < 0:
                return {**base, 'status': 'insufficient_data', 'reason': 'negative_capital_expenditures', 'inputs': inputs}
            value = values[0] - values[1]
            formula = 'operating_cash_flow - capital_expenditures'
        else:
            value = values[0]
            formula = 'current_ytd - previous_ytd' if quarter != 'Q1' else 'current_ytd'
        # All input decimals terminate; Fraction preserves exact subtraction independently of ambient context.
        with localcontext() as context:
            context.prec = 100
            rendered = decimal_text(Decimal(value.numerator) / Decimal(value.denominator))
        return {**base, 'status': 'ok', 'value': rendered, 'formula': formula,
                'inputs': inputs, 'warnings': sorted(set(warnings))}

    def _response(self, results, as_of):
        return {"status": "ok" if all(r["status"] == "ok" for r in results) else "partial",
                "context": self.context(as_of), "results": results}

    def calculate_metrics(self, cik, fiscal_years, metrics, as_of):
        self.validate(cik, fiscal_years, metrics, as_of, METRICS)
        cache = {}

        def select(year, metric):
            if (year, metric) not in cache:
                cache[year, metric] = self._select(year, metric, as_of)
            return cache[year, metric]

        def operand(fact):
            # The requested fact rows carry the full candidate audit; ratio operands keep provenance only.
            return {k: v for k, v in fact.items() if k not in AUDIT_KEYS} if fact["status"] == "ok" else fact

        results = []
        for year in sorted(fiscal_years):
            for metric in metrics:
                if metric == 'free_cash_flow':
                    results.append(self._cash_result(year, metric, as_of))
                    continue
                if metric in ANNUAL_TAGS:
                    results.append(select(year, metric))
                    continue
                base = {"fiscal_year": year, "metric": metric, "unit": "percent",
                        "period_start": self.periods[year][0], "period_end": self.periods[year][1], "value": None}
                if metric == "revenue_growth" and year - 1 not in {**self.support_periods, **self.periods}:
                    results.append({**base, "status": "insufficient_data", "reason": "prior_year_outside_reviewed_scope"})
                    continue
                revenue = operand(select(year, "revenue"))
                if metric == "operating_margin":
                    other = operand(select(year, "operating_income"))
                elif metric == "gross_margin":
                    other = operand(select(year, "gross_profit"))
                else:
                    other = operand(select(year - 1, "revenue"))
                inputs = [revenue, other]
                base["inputs"] = inputs
                if any(f["status"] != "ok" for f in inputs):
                    results.append({**base, "status": "insufficient_data", "reason": "operand_unavailable"})
                    continue
                basis_warnings = []
                if revenue["accn"] != other["accn"]:
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


def snapshot_ticker(data_dir=DEFAULT_DATA):
    """The issuer a snapshot directory's root belongs to, without loading its facts."""
    try:
        cik = str(json.loads((Path(data_dir) / "submissions.json").read_text())["cik"]).zfill(10)
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return PROFILES[cik]["ticker"] if cik in PROFILES else None


class AnalystService:
    """Route the tools to reviewed issuer snapshots: the root issuer plus any reviewed issuer subdirectories."""

    def __init__(self, data_dir=DEFAULT_DATA, treasury_snapshot=None):
        from .treasury import DEFAULT_SNAPSHOT, TreasuryService
        self.treasury = TreasuryService(treasury_snapshot or DEFAULT_SNAPSHOT)
        root = Path(data_dir)
        primary = Analyst(root)
        self.issuers = {primary.cik: primary}
        # Other issuers load on first use, so a one-issuer query parses one companyfacts file.
        # The bundled data must contain every issuer; a missing one fails loudly instead of disappearing.
        bundled = root.resolve() == DEFAULT_DATA.resolve()
        self.pending = {cik: root / profile["directory"] for cik, profile in PROFILES.items()
                        if cik != primary.cik and profile["directory"] != "."
                        and (bundled or (root / profile["directory"] / "manifest.json").is_file())}

    def _load(self, cik):
        if cik in self.pending:
            # Load before forgetting the path, so a failed load fails the same way every time.
            self.issuers[cik] = Analyst(self.pending[cik])
            del self.pending[cik]
        return self.issuers[cik]

    def reviewed_profiles(self):
        return {**{cik: PROFILES[cik] for cik in self.pending}, **{cik: a.profile for cik, a in self.issuers.items()}}

    def resolve_company(self, ticker):
        if not isinstance(ticker, str):
            raise Refusal("invalid_ticker", "Ticker must be a string.")
        profiles = self.reviewed_profiles()
        matches = [cik for cik, profile in profiles.items() if profile["ticker"] == ticker.upper()]
        if len(matches) != 1:
            raise Refusal("unsupported_company", "Reviewed companies are " + ", ".join(sorted(p["ticker"] for p in profiles.values())) + "; custom snapshots contain only their own issuer.")
        return self._load(matches[0]).resolve_company(ticker)

    def issuer(self, cik):
        if not isinstance(cik, str) or (cik not in self.issuers and cik not in self.pending):
            raise Refusal("unsupported_company", "CIK is not in the loaded reviewed snapshots.")
        return self._load(cik)

    def get_annual_facts(self, cik, fiscal_years, metrics, as_of):
        return self.issuer(cik).get_annual_facts(cik, fiscal_years, metrics, as_of)

    def calculate_metrics(self, cik, fiscal_years, metrics, as_of):
        return self.issuer(cik).calculate_metrics(cik, fiscal_years, metrics, as_of)

    def get_quarterly_facts(self, cik, fiscal_year, quarter, metrics, as_of):
        return self.issuer(cik).get_quarterly_facts(cik, fiscal_year, quarter, metrics, as_of)
