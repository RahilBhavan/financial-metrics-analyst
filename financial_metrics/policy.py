"""Reviewed scope and accounting policy; changes require new source checks."""

CIK = "0000320193"
NAME = "Apple Inc."
TICKER = "AAPL"
PERIODS = {
    2023: ("2022-09-25", "2023-09-30"),
    2024: ("2023-10-01", "2024-09-28"),
    2025: ("2024-09-29", "2025-09-27"),
}
TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "gross_profit": "GrossProfit",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
}
CASH_FLOW_TAGS = {
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "investing_cash_flow": "NetCashProvidedByUsedInInvestingActivities",
    "financing_cash_flow": "NetCashProvidedByUsedInFinancingActivities",
}
ANNUAL_TAGS = {**TAGS, **CASH_FLOW_TAGS}
METRICS = tuple(ANNUAL_TAGS) + ("gross_margin", "operating_margin", "revenue_growth")
LABELS = {"operating_cash_flow": "Operating cash flow", "investing_cash_flow": "Investing cash flow",
          "financing_cash_flow": "Financing cash flow", "revenue": "Revenue", "gross_profit": "Gross profit", "operating_income": "Operating income",
          "net_income": "Net income", "gross_margin": "Gross margin",
          "operating_margin": "Operating margin", "revenue_growth": "Revenue growth"}
# Four years lets the full MSFT FY2023-FY2026 profile fit in one request.
MAX_YEARS = 4
# Large issuers' companyfacts exceed 8 MiB; the cap still bounds memory per file.
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


def calendar_profile(cik, name, ticker, directory, tags=None):
    """Calendar-year filers with reviewed FY2023-FY2025 and one prior revenue year for growth."""
    profile = {"cik": cik, "name": name, "ticker": ticker, "directory": directory, "fye_month": 12,
               "periods": {year: (str(year) + "-01-01", str(year) + "-12-31") for year in (2023, 2024, 2025)},
               "support_periods": {2022: ("2022-01-01", "2022-12-31")}}
    if tags:
        profile["tags"] = {**TAGS, **tags}
    return profile


PROFILES = {
    CIK: {"cik": CIK, "name": NAME, "ticker": TICKER, "periods": PERIODS, "fye_month": 9,
          "support_periods": {2022: ("2021-09-26", "2022-09-24")}, "directory": "."},
    "0000789019": {"cik": "0000789019", "name": "Microsoft Corporation", "ticker": "MSFT", "fye_month": 6,
                  "periods": {year: (str(year - 1) + "-07-01", str(year) + "-06-30") for year in (2023, 2024, 2025, 2026)},
                  "support_periods": {2022: ("2021-07-01", "2022-06-30")}, "directory": "msft"},
    "0001045810": {"cik": "0001045810", "name": "NVIDIA Corporation", "ticker": "NVDA", "fye_month": 1,
                  "periods": {2024: ("2023-01-30", "2024-01-28"), 2025: ("2024-01-29", "2025-01-26"),
                              2026: ("2025-01-27", "2026-01-25")},
                  "support_periods": {2023: ("2022-01-31", "2023-01-29")}, "directory": "nvda",
                  "tags": {**TAGS, "revenue": "Revenues"}},
    "0001679788": calendar_profile("0001679788", "Coinbase Global, Inc.", "COIN", "coin", {"revenue": "Revenues"}),
    "0001050446": calendar_profile("0001050446", "Strategy Inc", "MSTR", "mstr"),
    "0001783879": calendar_profile("0001783879", "Robinhood Markets, Inc.", "HOOD", "hood", {"revenue": "Revenues"}),
    "0001512673": calendar_profile("0001512673", "Block, Inc.", "XYZ", "xyz", {"revenue": "Revenues"}),
    "0001633917": calendar_profile("0001633917", "PayPal Holdings, Inc.", "PYPL", "pypl", {"revenue": "Revenues"}),
    "0001403161": {"cik": "0001403161", "name": "Visa Inc.", "ticker": "V", "directory": "v", "fye_month": 9,
                  "periods": {year: (str(year - 1) + "-10-01", str(year) + "-09-30") for year in (2023, 2024, 2025)},
                  "support_periods": {2022: ("2021-10-01", "2022-09-30")}},
    "0001318605": calendar_profile("0001318605", "Tesla, Inc.", "TSLA", "tsla", {"revenue": "Revenues"}),
}
# Reviewed fiscal quarters: (fiscal year, quarter) -> (start, end). The latest four 10-Q periods in each snapshot that
# the SEC companyfacts API serves; each is transcribed in the issuer's ground-truth.json from the 10-Q income statement.
REVIEWED_QUARTERS = {
    "AAPL": {
        (2025, "Q3"): ("2025-03-30", "2025-06-28"),
        (2026, "Q1"): ("2025-09-28", "2025-12-27"),
        (2026, "Q2"): ("2025-12-28", "2026-03-28"),
        (2026, "Q3"): ("2026-03-29", "2026-06-27"),
    },
    "MSFT": {
        (2025, "Q3"): ("2025-01-01", "2025-03-31"),
        (2026, "Q1"): ("2025-07-01", "2025-09-30"),
        (2026, "Q2"): ("2025-10-01", "2025-12-31"),
        (2026, "Q3"): ("2026-01-01", "2026-03-31"),
    },
    "NVDA": {
        (2026, "Q2"): ("2025-04-28", "2025-07-27"),
        (2026, "Q3"): ("2025-07-28", "2025-10-26"),
        (2027, "Q1"): ("2026-01-26", "2026-04-26"),
        (2027, "Q2"): ("2026-04-27", "2026-07-26"),
    },
    "COIN": {
        (2025, "Q2"): ("2025-04-01", "2025-06-30"),
        (2025, "Q3"): ("2025-07-01", "2025-09-30"),
        (2026, "Q1"): ("2026-01-01", "2026-03-31"),
        (2026, "Q2"): ("2026-04-01", "2026-06-30"),
    },
    "MSTR": {
        (2025, "Q2"): ("2025-04-01", "2025-06-30"),
        (2025, "Q3"): ("2025-07-01", "2025-09-30"),
        (2026, "Q1"): ("2026-01-01", "2026-03-31"),
        (2026, "Q2"): ("2026-04-01", "2026-06-30"),
    },
    "HOOD": {
        (2025, "Q2"): ("2025-04-01", "2025-06-30"),
        (2025, "Q3"): ("2025-07-01", "2025-09-30"),
        (2026, "Q1"): ("2026-01-01", "2026-03-31"),
        (2026, "Q2"): ("2026-04-01", "2026-06-30"),
    },
    "XYZ": {
        (2025, "Q2"): ("2025-04-01", "2025-06-30"),
        (2025, "Q3"): ("2025-07-01", "2025-09-30"),
        (2026, "Q1"): ("2026-01-01", "2026-03-31"),
        (2026, "Q2"): ("2026-04-01", "2026-06-30"),
    },
    "PYPL": {
        (2025, "Q1"): ("2025-01-01", "2025-03-31"),
        (2025, "Q2"): ("2025-04-01", "2025-06-30"),
        (2025, "Q3"): ("2025-07-01", "2025-09-30"),
        (2026, "Q1"): ("2026-01-01", "2026-03-31"),
    },
    "V": {
        (2025, "Q2"): ("2025-01-01", "2025-03-31"),
        (2025, "Q3"): ("2025-04-01", "2025-06-30"),
        (2026, "Q1"): ("2025-10-01", "2025-12-31"),
        (2026, "Q2"): ("2026-01-01", "2026-03-31"),
    },
    "TSLA": {
        (2025, "Q3"): ("2025-07-01", "2025-09-30"),
        (2026, "Q1"): ("2026-01-01", "2026-03-31"),
        (2026, "Q2"): ("2026-04-01", "2026-06-30"),
        (2026, "Q3"): ("2026-07-01", "2026-09-30"),
    },
}
for _profile in PROFILES.values():
    _profile["tags"] = {**ANNUAL_TAGS, **_profile.get("tags", {})}
    _profile["quarters"] = REVIEWED_QUARTERS[_profile["ticker"]]
# Everything below derives from PROFILES so adding a reviewed period changes one place.
TICKERS = tuple(profile["ticker"] for profile in PROFILES.values())
PROFILE_BY_TICKER = {profile["ticker"]: profile for profile in PROFILES.values()}
ANNUAL_YEARS = tuple(sorted({year for profile in PROFILES.values() for year in profile["periods"]}))
QUARTERS = tuple(sorted({key for profile in PROFILES.values() for key in profile["quarters"]}))
REVIEWED_TAGS = tuple(sorted({tag for profile in PROFILES.values() for tag in profile.get("tags", TAGS).values()}))
KHC_REFERENCE_PROFILE = {
    "cik": "0001637459", "name": "The Kraft Heinz Company", "ticker": "KHC",
    "periods": {2017: ("2017-01-01", "2017-12-30")}, "support_periods": {},
    "directory": "reference-cases/khc",
}
POLICY = {
    "version": "reviewed-annual-quarterly-v5",
    "scope": "Ten reviewed issuers: AAPL FY2023-FY2025, MSFT FY2023-FY2026, NVDA FY2024-FY2026, and COIN, MSTR, HOOD, XYZ, PYPL, V and TSLA FY2023-FY2025; four reviewed 10-Q quarters each; one prior revenue period supports growth; annual operating, investing and financing cash flow; consolidated USD",
    "selection": "Latest filing date on or before as_of, matching exact reviewed dates. Invalid same-date or newer annual or quarterly candidates block selection; conflicting values on any one filing date are ambiguous. A later 10-Q that repeats a quarter as its prior-year comparative is a revision candidate.",
    "as_of": "Inclusive filing date, end of day; no intraday point-in-time claim; later API corrections to old records cannot be reconstructed.",
    "revision": "Retain earliest eligible value and history; changed values are revision candidates, not proven formal restatements.",
    "net_income": "Net income attributable to the issuer (NetIncomeLoss), not income available to common shareholders and not consolidated net income including noncontrolling interests.",
    "cash_flow": "Annual net cash provided by (positive) or used in (negative) operating, investing and financing activities; signed USD from standard tags. No quarterly YTD subtraction, capital expenditures or free cash flow inference.",
    "growth": "Reported annual growth; prior revenue must be positive; consecutive contiguous periods; unequal fiscal period lengths explicitly flagged, not normalized.",
    "basis": "Ratios use one accession. Growth may use the latest common filing only when its two values match the latest individually selected values; explain the older comparative basis explicitly.",
    "precision": "Exact input decimals and exact rational percentage retained; decimal rendering has 34 significant digits, ROUND_HALF_EVEN; display 2 decimal places.",
}


class Refusal(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def as_dict(self):
        return {"status": "refused", "code": self.code, "message": str(self)}


class Clarification(Refusal):
    def __init__(self, code, message, choices):
        super().__init__(code, message)
        self.choices = choices

    def as_dict(self):
        return {"status": "needs_clarification", "code": self.code, "message": str(self), "choices": self.choices}
