"""Deterministic paraphrases and explicit clarification, with no model call."""

import re

from .contracts import obj, validate_schema
from .policy import Clarification, Refusal

ALIASES = {
    "revenue": "revenue", "sales": "revenue", "net sales": "revenue", "total revenue": "revenue",
    "operating income": "operating_income", "operating profit": "operating_income",
    "net income": "net_income", "net profit": "net_income",
    "gross profit": "gross_profit", "gross margin": "gross_margin",
    "operating margin": "operating_margin", "operating profit margin": "operating_margin",
    "revenue growth": "revenue_growth", "yoy revenue growth": "revenue_growth",
    "year-over-year revenue growth": "revenue_growth",
}
COMPANIES = {"apple": "AAPL", "aapl": "AAPL", "microsoft": "MSFT", "msft": "MSFT",
             "nvidia": "NVDA", "nvda": "NVDA"}
FORBIDDEN = r"\b(forecast\w*|predict\w*|projected|ebitda|fcf|cash flow|valuation|adjusted|quarter\w*|q[1-4]|ttm|calendar|net margin|execute|shell|ignore|delete|send|email)\b"
FILLER = {"what", "was", "were", "is", "the", "for", "in", "from", "to", "through", "and", "please", "show",
          "me", "give", "tell", "about", "of", "between", "fiscal", "years", "year", "fy", "how", "did", "change", "over"}


def parse_question(question):
    if not isinstance(question, str) or not 1 <= len(question) <= 500:
        raise Refusal("unsupported_question", "Use a question of 1 to 500 characters.")
    text = question.lower().replace("’", "'").strip()
    text = re.sub(r"^(?:can|could|would) you\s+", "", text)
    if re.search(FORBIDDEN, text) or re.search(r"[;`{}<>]|https?://", text):
        raise Refusal("unsupported_question", "Only historical annual revenue, income, operating margin, and revenue growth are supported.")
    matches = list(re.finditer(r"\bas\s+of\s+(\d{4}-\d{2}-\d{2})\b", text))
    if len(matches) > 1:
        raise Clarification("ambiguous_as_of", "Which filing cutoff date should be used?", [m.group(1) for m in matches])
    as_of = matches[0].group(1) if matches else None
    if matches:
        text = text[:matches[0].start()] + " " + text[matches[0].end():]
    entities = {COMPANIES[m.group()] for m in re.finditer(r"\b(?:apple|aapl|microsoft|msft|nvidia|nvda)\b", text)}
    if len(entities) > 1:
        raise Refusal("unsupported_comparison", "Ask for one issuer at a time; cross-company comparisons are not supported.")
    if not entities:
        raise Clarification("company_required", "Which reviewed company should I use?", ["Apple (AAPL)", "Microsoft (MSFT)", "NVIDIA (NVDA)"])
    ticker = entities.pop()
    text = re.sub(r"\b(?:apple|aapl|microsoft|msft|nvidia|nvda)(?:'s)?\b", " ", text)
    range_match = re.search(r"\b(?:fy\s*)?(\d{4})\s*(?:through|to|-)\s*(?:fy\s*)?(\d{4})\b", text)
    if range_match:
        start, end = map(int, range_match.groups())
        if end < start or end - start > 2:
            raise Refusal("unsupported_years", "Use an ascending range of at most three reviewed fiscal years.")
        years = list(range(start, end + 1))
        text = text[:range_match.start()] + " " + text[range_match.end():]
        if re.search(r"\b\d{4}\b", text):
            raise Clarification("ambiguous_years", "Use one year range or one explicit year list.", ["2023 through 2025", "2024, 2025"])
    else:
        years = [int(y) for y in re.findall(r"\b(?:fy\s*)?(\d{4})\b", text)]
        text = re.sub(r"\b(?:fy\s*)?\d{4}\b", " ", text)
    if not years:
        raise Clarification("years_required", "Which fiscal years? Coverage depends on the issuer and extends through FY2026.", ["2023 through 2025", "2026"])
    if len(years) > 3 or len(years) != len(set(years)) or any(y not in (2023, 2024, 2025, 2026) for y in years):
        raise Refusal("unsupported_years", "Public queries support up to three distinct reviewed years from 2023 through 2026, subject to issuer coverage.")
    metrics = []
    pattern = r"\b(?:" + "|".join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True)) + r")\b"
    def collect(match):
        metrics.append(ALIASES[match.group()])
        return " "
    text = re.sub(pattern, collect, text)
    if re.search(r"\bmargin\b", text):
        raise Clarification("ambiguous_margin", "Do you mean operating margin? Other margin definitions are not supported.", ["Operating margin"])
    if re.search(r"\bprofit\b", text):
        raise Clarification("ambiguous_profit", "Do you mean operating income or net income?", ["Operating income", "Net income"])
    if "revenue" in metrics and re.search(r"\bchange\b", text) and "revenue_growth" not in metrics:
        raise Clarification("ambiguous_change", "Do you want annual revenue amounts or year-over-year revenue growth?", ["Revenue", "Revenue growth"])
    if not metrics:
        raise Clarification("metric_required", "Which metric should I show?", ["Revenue", "Operating margin", "Net income", "Revenue growth"])
    residual = re.sub(r"[,?.!&]", " ", text).split()
    if any(word not in FILLER for word in residual):
        raise Refusal("unsupported_question", "Some requested wording could not be interpreted safely. Specify one issuer, supported metrics, and explicit fiscal years.")
    return ticker, sorted(years), list(dict.fromkeys(metrics)), as_of


PROPOSAL_SCHEMA = obj({"ticker": {"type": "string", "enum": ["AAPL", "MSFT", "NVDA"]},
                       "fiscal_years": {"type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True,
                                        "items": {"type": "integer", "minimum": 2023, "maximum": 2026}},
                       "metrics": {"type": "array", "minItems": 1, "maxItems": 7, "uniqueItems": True,
                                   "items": {"type": "string", "enum": sorted(set(ALIASES.values()))}},
                       "as_of": {"type": "string", "format": "date", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}})


def validate_proposal(proposal):
    """An optional model can propose arguments, never a number or an action."""
    validate_schema(proposal, PROPOSAL_SCHEMA, "proposal")
    return proposal["ticker"], proposal["fiscal_years"], proposal["metrics"], proposal["as_of"]
