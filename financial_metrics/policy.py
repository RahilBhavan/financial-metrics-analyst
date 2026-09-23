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
METRICS = tuple(TAGS) + ("gross_margin", "operating_margin", "revenue_growth")
PROFILES = {
    CIK: {"cik": CIK, "name": NAME, "ticker": TICKER, "periods": PERIODS,
          "support_periods": {2022: ("2021-09-26", "2022-09-24")}, "directory": "."},
    "0000789019": {"cik": "0000789019", "name": "Microsoft Corporation", "ticker": "MSFT",
                  "periods": {year: (str(year - 1) + "-07-01", str(year) + "-06-30") for year in (2023, 2024, 2025, 2026)},
                  "support_periods": {2022: ("2021-07-01", "2022-06-30")}, "directory": "msft"},
    "0001045810": {"cik": "0001045810", "name": "NVIDIA Corporation", "ticker": "NVDA",
                  "periods": {2024: ("2023-01-30", "2024-01-28"), 2025: ("2024-01-29", "2025-01-26"),
                              2026: ("2025-01-27", "2026-01-25")},
                  "support_periods": {2023: ("2022-01-31", "2023-01-29")}, "directory": "nvda",
                  "tags": {**TAGS, "revenue": "Revenues"},
                  "quarters": {(2027, "Q2"): ("2026-04-27", "2026-07-26")}},
}
KHC_REFERENCE_PROFILE = {
    "cik": "0001637459", "name": "The Kraft Heinz Company", "ticker": "KHC",
    "periods": {2017: ("2017-01-01", "2017-12-30")}, "support_periods": {},
    "directory": "reference-cases/khc",
}
POLICY = {
    "version": "reviewed-annual-v3",
    "scope": "AAPL FY2023-FY2025, MSFT FY2023-FY2026, and NVDA FY2024-FY2026; one prior revenue period supports growth; consolidated USD; one reviewed NVIDIA quarter",
    "selection": "Latest filing date on or before as_of, matching exact reviewed dates. Invalid same-date or newer annual candidates block selection; conflicting values on any one filing date are ambiguous.",
    "as_of": "Inclusive filing date, end of day; no intraday point-in-time claim; later API corrections to old records cannot be reconstructed.",
    "revision": "Retain earliest eligible value and history; changed values are revision candidates, not proven formal restatements.",
    "net_income": "Consolidated NetIncomeLoss, not income available to common shareholders.",
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
