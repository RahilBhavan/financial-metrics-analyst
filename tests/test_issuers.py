"""Coverage across all ten reviewed issuers: filing-transcribed cards, refusals and stale-value guards.

Expected values come from each issuer's ground-truth.json, which scripts/review_filings.py transcribes
from the filing documents without reading companyfacts. Synthetic mutations run only here, never in the
committed evaluation, and are labeled synthetic.
"""
import contextlib
import copy
import json
import unittest
from datetime import date, timedelta

from financial_metrics.domain import AnalystService, DEFAULT_DATA
from financial_metrics.policy import PROFILES, TAGS, Refusal
from financial_metrics.questions import COMPANIES, parse_question, validate_proposal
from financial_metrics.tools import TOOLS, call_tool

SERVICE = AnalystService()
CARDS = {cik: json.loads((DEFAULT_DATA / profile["directory"] / "ground-truth.json").read_text()) for cik, profile in PROFILES.items()}
NEW = ("COIN", "MSTR", "HOOD", "XYZ", "PYPL", "V", "TSLA")
NEW_CIKS = [cik for cik, profile in PROFILES.items() if profile["ticker"] in NEW]


def accession_of(card, year):
    values = card["years"][str(year)]
    return values.get("accession") or card.get("accession") or card["filing_accession"]


def annual_rows(analyst, metric, start, end, accn):
    tag = analyst.profile.get("tags", TAGS)[metric]
    return [r for r in analyst.facts["facts"]["us-gaap"][tag]["units"]["USD"]
            if r.get("start") == start and r["end"] == end and r["accn"] == accn]


@contextlib.contextmanager
def appended(analyst, metric, row):
    rows = analyst.facts["facts"]["us-gaap"][analyst.profile.get("tags", TAGS)[metric]]["units"]["USD"]
    rows.append(row)
    try:
        yield
    finally:
        rows.remove(row)


@contextlib.contextmanager
def changed(rows, **fields):
    saved = [{key: row[key] for key in fields} for row in rows]
    for row in rows:
        row.update(fields)
    try:
        yield
    finally:
        for row, original in zip(rows, saved):
            row.update(original)


class CoverageTests(unittest.TestCase):
    def test_twelve_issuers_with_six_reviewed_quarters_each(self):
        self.assertEqual(len(SERVICE.issuers) + len(SERVICE.pending), 12)
        self.assertEqual(sorted(p["ticker"] for p in PROFILES.values()),
                         sorted(["AAPL", "MSFT", "NVDA", "COIN", "MSTR", "HOOD", "XYZ", "PYPL", "V", "TSLA", "AMD", "INTC"]))
        for cik, profile in PROFILES.items():
            with self.subTest(ticker=profile["ticker"]):
                self.assertGreaterEqual(len(profile["quarters"]), 6)
                self.assertEqual(len(CARDS[cik]["reviewed_quarters"]), len(profile["quarters"]))
                self.assertEqual(SERVICE.resolve_company(profile["ticker"].lower())["cik"], cik)

    def test_every_card_year_matches_server(self):
        for cik, profile in PROFILES.items():
            card = CARDS[cik]
            captured = SERVICE.issuer(cik).captured_date.isoformat()
            result = SERVICE.get_annual_facts(cik, sorted(profile["periods"]), list(TAGS), captured)
            for row in result["results"]:
                expected = card["years"][str(row["fiscal_year"])][row["metric"]]
                with self.subTest(ticker=profile["ticker"], year=row["fiscal_year"], metric=row["metric"]):
                    self.assertEqual(row["value"], expected)
                    if expected is None:
                        self.assertEqual(row["status"], "insufficient_data")
                        self.assertEqual(row["reason"], "standard_tag_absent")

    def test_every_reviewed_quarter_matches_server_at_its_filing_date(self):
        for cik, profile in PROFILES.items():
            for quarter in CARDS[cik]["reviewed_quarters"]:
                result = SERVICE.get_quarterly_facts(cik, quarter["fiscal_year"], quarter["quarter"], list(TAGS), quarter["filed"])
                for row in result["results"]:
                    with self.subTest(ticker=profile["ticker"], quarter=quarter["quarter"], fy=quarter["fiscal_year"], metric=row["metric"]):
                        self.assertEqual(row["value"], quarter[row["metric"]])
                        if row["value"] is not None:
                            self.assertEqual((row["accn"], row["period_start"], row["period_end"]),
                                             (quarter["filing_accession"], quarter["start"], quarter["end"]))

    def test_unreported_metric_is_unavailable_never_zero(self):
        by_ticker = {p["ticker"]: cik for cik, p in PROFILES.items()}
        for ticker, metric in [("COIN", "gross_profit"), ("HOOD", "operating_income"), ("PYPL", "gross_profit"), ("V", "gross_profit")]:
            cik = by_ticker[ticker]
            captured = SERVICE.issuer(cik).captured_date.isoformat()
            ratio = "gross_margin" if metric == "gross_profit" else "operating_margin"
            row = SERVICE.calculate_metrics(cik, [2025], [ratio], captured)["results"][0]
            with self.subTest(ticker=ticker):
                self.assertEqual((row["status"], row["reason"], row["value"]), ("insufficient_data", "operand_unavailable", None))

    def test_hood_amendment_is_selected_and_original_kept(self):
        cik = next(c for c, p in PROFILES.items() if p["ticker"] == "HOOD")
        card = CARDS[cik]["years"]["2025"]
        row = SERVICE.get_annual_facts(cik, [2025], ["revenue"], "2026-10-25")["results"][0]
        self.assertEqual((row["accn"], row["form"]), (card["accession"], "10-K/A"))
        self.assertEqual(row["original"]["accn"], card["original_accession"])
        self.assertFalse(row["revision_candidate"])

    def test_growth_year_over_year_uses_card_arithmetic_for_new_issuers(self):
        from fractions import Fraction
        for cik in NEW_CIKS:
            card = CARDS[cik]
            captured = SERVICE.issuer(cik).captured_date.isoformat()
            for year in (2023, 2024, 2025):
                prior = card["supporting_revenue"]["value"] if year == 2023 else card["years"][str(year - 1)]["revenue"]
                current = card["years"][str(year)]["revenue"]
                row = SERVICE.calculate_metrics(cik, [year], ["revenue_growth"], captured)["results"][0]
                with self.subTest(ticker=PROFILES[cik]["ticker"], year=year):
                    self.assertEqual(Fraction(int(row["exact_fraction"]["numerator"]), int(row["exact_fraction"]["denominator"])),
                                     Fraction((int(current) - int(prior)) * 100, int(prior)))


class StaleValueGuardTests(unittest.TestCase):
    """Synthetic mutations of real snapshots, run for each of the ten issuers."""

    @staticmethod
    def newest(cik):
        analyst = SERVICE.issuer(cik)
        year = max(analyst.periods)
        card = CARDS[cik]["years"][str(year)]
        return analyst, year, card

    def test_synthetic_conflicting_values_on_one_filing_date_are_ambiguous(self):
        for cik in PROFILES:
            analyst, year, card = self.newest(cik)
            rows = annual_rows(analyst, "revenue", card["start"], card["end"], accession_of(CARDS[cik], year))
            clash = copy.deepcopy(rows[0])
            clash["val"] += 1
            with appended(analyst, "revenue", clash), self.subTest(ticker=PROFILES[cik]["ticker"]):
                row = analyst.get_annual_facts(cik, [year], ["revenue"], analyst.captured_date.isoformat())["results"][0]
                self.assertEqual((row["status"], row["reason"], row["value"]), ("ambiguous", "conflicting_values_on_same_filing_date", None))

    def test_synthetic_revision_in_newest_filing_keeps_the_older_original(self):
        for cik in NEW_CIKS:
            analyst, year, card = self.newest(cik)
            older = CARDS[cik]["point_in_time"]
            start, end = older["years"][str(year - 1)]["start"], older["years"][str(year - 1)]["end"]
            newest_rows = annual_rows(analyst, "revenue", start, end, card["accession"])
            expected = older["years"][str(year - 1)]["revenue"]
            with self.subTest(ticker=PROFILES[cik]["ticker"]):
                with changed(newest_rows, val=int(expected) + 1):
                    row = analyst.get_annual_facts(cik, [year - 1], ["revenue"], analyst.captured_date.isoformat())["results"][0]
                    self.assertTrue(row["revision_candidate"])
                    self.assertEqual((row["original"]["accn"], row["original"]["value"]), (older["accession"], expected))
                    self.assertEqual(row["value"], str(int(expected) + 1))
                    before = analyst.get_annual_facts(cik, [year - 1], ["revenue"], older["as_of"])["results"][0]
                    self.assertEqual((before["value"], before["accn"], before["revision_candidate"]), (expected, older["accession"], False))

    def test_synthetic_invalid_newest_annual_value_never_falls_back_to_older_filing(self):
        for cik in NEW_CIKS:
            analyst, year, card = self.newest(cik)
            older = CARDS[cik]["point_in_time"]
            period = older["years"][str(year - 1)]
            newest_rows = annual_rows(analyst, "revenue", period["start"], period["end"], card["accession"])
            with self.subTest(ticker=PROFILES[cik]["ticker"]), changed(newest_rows, val="NaN"):
                blocked = analyst.get_annual_facts(cik, [year - 1], ["revenue"], analyst.captured_date.isoformat())["results"][0]
                self.assertEqual(blocked["reason"], "newer_or_same_date_candidate_invalid")
                self.assertIsNone(blocked["value"])
                earlier = analyst.get_annual_facts(cik, [year - 1], ["revenue"], older["as_of"])["results"][0]
                self.assertEqual((earlier["status"], earlier["value"]), ("ok", period["revenue"]))

    def test_synthetic_conflicting_quarter_values_are_ambiguous(self):
        for cik in PROFILES:
            analyst = SERVICE.issuer(cik)
            quarter = CARDS[cik]["reviewed_quarters"][-1]
            tag = analyst.profile.get("tags", TAGS)["revenue"]
            rows = [r for r in analyst.facts["facts"]["us-gaap"][tag]["units"]["USD"]
                    if r.get("start") == quarter["start"] and r["end"] == quarter["end"] and r["accn"] == quarter["filing_accession"]]
            clash = copy.deepcopy(rows[0])
            clash["val"] += 1
            with appended(analyst, "revenue", clash), self.subTest(ticker=PROFILES[cik]["ticker"]):
                row = analyst.get_quarterly_facts(cik, quarter["fiscal_year"], quarter["quarter"], ["revenue"], quarter["filed"])["results"][0]
                self.assertEqual((row["status"], row["value"]), ("ambiguous", None))

    def test_synthetic_invalid_newer_quarter_amendment_never_falls_back(self):
        for cik in PROFILES:
            analyst = SERVICE.issuer(cik)
            quarter = CARDS[cik]["reviewed_quarters"][-1]
            tag = analyst.profile.get("tags", TAGS)["revenue"]
            original = next(r for r in analyst.facts["facts"]["us-gaap"][tag]["units"]["USD"]
                            if r.get("start") == quarter["start"] and r["end"] == quarter["end"] and r["accn"] == quarter["filing_accession"])
            amendment_date = (date.fromisoformat(quarter["filed"]) + timedelta(days=3)).isoformat()
            amendment = dict(copy.deepcopy(original), accn="0000000000-26-000001", form="10-Q/A", filed=amendment_date, val="NaN")
            analyst.filings[amendment["accn"]] = {**analyst.filings[quarter["filing_accession"]], "accessionNumber": amendment["accn"],
                                                  "form": "10-Q/A", "filingDate": amendment_date}
            try:
                with appended(analyst, "revenue", amendment), self.subTest(ticker=PROFILES[cik]["ticker"]):
                    args = (cik, quarter["fiscal_year"], quarter["quarter"], ["revenue"])
                    blocked = analyst.get_quarterly_facts(*args, amendment_date)["results"][0]
                    self.assertEqual(blocked["reason"], "newer_or_same_date_candidate_invalid")
                    self.assertIsNone(blocked["value"])
                    served = analyst.get_quarterly_facts(*args, quarter["filed"])["results"][0]
                    self.assertEqual((served["status"], served["value"]), ("ok", quarter["revenue"]))
            finally:
                del analyst.filings[amendment["accn"]]

    def test_later_ten_q_comparative_is_a_revision_candidate_not_a_mismatch(self):
        checked = 0
        for cik in PROFILES:
            analyst = SERVICE.issuer(cik)
            for quarter in CARDS[cik]["reviewed_quarters"]:
                tag = analyst.profile.get("tags", TAGS)["revenue"]
                rows = [r for r in analyst.facts["facts"]["us-gaap"][tag]["units"]["USD"]
                        if r.get("start") == quarter["start"] and r["end"] == quarter["end"] and r["accn"] != quarter["filing_accession"]
                        and r["form"] == "10-Q" and r["filed"] > quarter["filed"] and r["fp"] == quarter["quarter"]]
                if not rows:
                    continue
                checked += 1
                with self.subTest(ticker=PROFILES[cik]["ticker"], quarter=quarter["quarter"], fy=quarter["fiscal_year"]):
                    captured = analyst.captured_date.isoformat()
                    unchanged = analyst.get_quarterly_facts(cik, quarter["fiscal_year"], quarter["quarter"], ["revenue"], captured)["results"][0]
                    self.assertEqual((unchanged["status"], unchanged["value"], unchanged["revision_candidate"]), ("ok", quarter["revenue"], False))
                    self.assertEqual(unchanged["original"]["accn"], quarter["filing_accession"])
                    with changed(rows, val=int(quarter["revenue"]) + 1):
                        revised = analyst.get_quarterly_facts(cik, quarter["fiscal_year"], quarter["quarter"], ["revenue"], captured)["results"][0]
                        self.assertTrue(revised["revision_candidate"])
                        self.assertEqual((revised["original"]["value"], revised["value"]), (quarter["revenue"], str(int(quarter["revenue"]) + 1)))
                        at_filing = analyst.get_quarterly_facts(cik, quarter["fiscal_year"], quarter["quarter"], ["revenue"], quarter["filed"])["results"][0]
                        self.assertEqual((at_filing["value"], at_filing["revision_candidate"]), (quarter["revenue"], False))
        self.assertGreaterEqual(checked, 10)

    def test_quarter_is_invisible_before_its_ten_q_is_filed(self):
        for cik in PROFILES:
            for quarter in CARDS[cik]["reviewed_quarters"]:
                day_before = (date.fromisoformat(quarter["filed"]) - timedelta(days=1)).isoformat()
                row = SERVICE.get_quarterly_facts(cik, quarter["fiscal_year"], quarter["quarter"], ["revenue"], day_before)["results"][0]
                with self.subTest(ticker=PROFILES[cik]["ticker"], quarter=quarter["quarter"], fy=quarter["fiscal_year"]):
                    self.assertEqual((row["status"], row["value"]), ("insufficient_data", None))

    def test_real_newer_relabelled_record_blocks_paypal_q2_2025_net_income(self):
        cik = next(c for c, p in PROFILES.items() if p["ticker"] == "PYPL")
        row = SERVICE.get_quarterly_facts(cik, 2025, "Q2", ["net_income"], "2026-10-25")["results"][0]
        self.assertEqual(row["reason"], "newer_or_same_date_candidate_invalid")
        self.assertEqual(row["blocking_candidates"][0]["accn"], "0001633917-25-000196")
        card = next(q for q in CARDS[cik]["reviewed_quarters"] if (q["fiscal_year"], q["quarter"]) == (2025, "Q2"))
        served = SERVICE.get_quarterly_facts(cik, 2025, "Q2", ["net_income"], "2025-10-27")["results"][0]
        self.assertEqual((served["value"], served["accn"]), (card["net_income"], card["filing_accession"]))


class RefusalAndIntentTests(unittest.TestCase):
    def test_new_issuers_refuse_unreviewed_scope(self):
        for cik in NEW_CIKS:
            analyst = SERVICE.issuer(cik)
            captured = analyst.captured_date.isoformat()
            ticker = PROFILES[cik]["ticker"]
            with self.subTest(ticker=ticker):
                for args in [(cik, [2026], ["revenue"], captured), (cik, [2025], ["ebitda"], captured),
                             (cik, [2025], ["revenue"], (analyst.captured_date + timedelta(days=1)).isoformat()),
                             (cik, [2022], ["revenue"], captured)]:
                    with self.assertRaises(Refusal):
                        SERVICE.get_annual_facts(*args)
                with self.assertRaises(Refusal):
                    SERVICE.get_quarterly_facts(cik, 2024, "Q1", ["revenue"], captured)

    def test_quarter_tool_schema_rejects_q4_and_out_of_range_years(self):
        cik = next(iter(NEW_CIKS))
        for args in [{"fiscal_year": 2026, "quarter": "Q4"}, {"fiscal_year": 2019, "quarter": "Q1"}]:
            result = call_tool(SERVICE, "get_quarterly_facts", {"cik": cik, "metrics": ["revenue"], "as_of": "2026-10-25", **args})
            self.assertTrue(result["isError"])
            self.assertEqual(result["structuredContent"]["status"], "refused")

    def test_tool_descriptions_name_every_reviewed_ticker(self):
        description = next(t for t in TOOLS if t["name"] == "calculate_metrics")["description"]
        for profile in PROFILES.values():
            self.assertIn(profile["ticker"], description)

    def test_question_parser_knows_new_issuers_and_ignores_bare_v(self):
        self.assertEqual(parse_question("Visa revenue 2025")[0], "V")
        self.assertEqual(parse_question("Strategy revenue 2024 and 2025")[0], "MSTR")
        self.assertEqual(parse_question("XYZ net income 2025")[0], "XYZ")
        self.assertNotIn("v", COMPANIES)
        with self.assertRaises(Refusal) as caught:
            parse_question("v revenue 2025")
        self.assertEqual(caught.exception.code, "company_required")
        with self.assertRaises(Refusal) as caught:
            parse_question("Compare Visa and PayPal revenue 2025")
        self.assertEqual(caught.exception.code, "unsupported_comparison")

    def test_proposal_accepts_every_reviewed_ticker(self):
        for profile in PROFILES.values():
            proposal = dict(ticker=profile["ticker"], fiscal_years=[2025], metrics=["revenue"], as_of="2026-09-21")
            self.assertEqual(validate_proposal(proposal)[0], profile["ticker"])
        with self.assertRaises(Refusal):
            validate_proposal(dict(ticker="JPM", fiscal_years=[2025], metrics=["revenue"], as_of="2026-09-21"))


if __name__ == "__main__":
    unittest.main()
