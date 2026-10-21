"""Deterministic number tracing: every number in an answer must come from a tool result.

An answer number is traced when some tool-result number equals it at the precision the answer
shows: "$85.9M" matches 85885800.00, "0.85 bps" matches 0.849852, "119.07" matches 119.07.
Signs are compared by magnitude, because prose says "reduced by" for a negative change. Small
integers without a scale suffix must match exactly, so "2 weeks" cannot borrow a 1.998.
Dates, SEC accession numbers and URLs must appear verbatim. Numbers in the question are
allowed. Anything else is untraced, and the agent rejects the answer.
"""

import re
from decimal import Decimal, InvalidOperation

MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
URL = re.compile(r"https?://[^\s)\]>\"'`]+")
ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
NAMED_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b")
ACCESSION = re.compile(r"(?<!\d)(\d{10}-\d{2}-\d{6})(?!\d)")
FISCAL = re.compile(r"\bFY\s?(\d{4})\b")
LABELS = re.compile(r"\b(?:10-K/A|10-Q/A|10-K|10-Q|8-K|424B\d|ex99-\d|ex3-\d|Q[1-4]|H[12]|S-3)\b", re.IGNORECASE)
NUMBER = re.compile(r"""(?<![\w.])(?P<sign>[-−–])?\$?\s?
    (?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?(?:[eE](?P<exp>[-+]?\d+))?
    (?:\s?(?P<suffix>%|bps\b|bp\b|basis\ points?\b|thousand\b|million\b|billion\b|trillion\b|K\b|k\b|M\b|MM\b|mn\b|B\b|bn\b|T\b))?""",
                    re.VERBOSE)
SCALE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mm": 6, "mn": 6, "billion": 9, "b": 9, "bn": 9, "trillion": 12, "t": 12}


def _decimal(text):
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def corpus(results, question=""):
    """(numbers, strings): every number in the tool results (with its path) plus the question's numbers."""
    numbers, strings = [], []

    def walk(value, path):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            numbers.append((Decimal(repr(value)) if isinstance(value, float) else Decimal(value), path))
        elif isinstance(value, str):
            strings.append(value)
            direct = _decimal(value) if re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) else None
            if direct is not None:
                numbers.append((direct, path))
            else:
                numbers.extend((value, path + " (text)") for value in text_numbers(value))
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + "." + key if path else key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, path + "[" + str(i) + "]")

    for i, result in enumerate(results):
        walk(result, "call[" + str(i) + "]")
    strings.append(question)
    numbers.extend((value, "question") for value in text_numbers(question))
    return numbers, strings


def text_numbers(text):
    """Numbers stated in free text. Dates contribute their year only, so 2026-06-28 cannot supply a 6 or a 28."""
    stripped, verbatim = _strip_verbatim(text)
    years = [Decimal(item[:4]) for kind, item in verbatim if kind == "date"]
    return years + [token["value"] for token in tokens(stripped)]


def _strip_verbatim(text):
    """Remove URLs, accessions, dates and form labels; return (rest, [(kind, text that must appear verbatim)])."""
    verbatim = []

    def take(kind, pattern, value):
        def replace(match):
            verbatim.append((kind, value(match)))
            return " "
        return pattern.sub(replace, text)

    text = take("url", URL, lambda m: m.group(0).rstrip(".,;:"))
    text = take("accession", ACCESSION, lambda m: m.group(1))
    text = take("date", ISO_DATE, lambda m: m.group(1))
    text = take("date", NAMED_DATE, lambda m: m.group(3) + "-" + str(MONTHS[m.group(1).lower()]).zfill(2) + "-" + m.group(2).zfill(2))
    text = FISCAL.sub(lambda m: " " + m.group(1) + " ", text)
    return LABELS.sub(" ", text), verbatim


def tokens(text):
    out = []
    for match in NUMBER.finditer(text):
        whole = match.group("int").replace(",", "")
        frac = match.group("frac") or ""
        value = _decimal(whole + ("." + frac if frac else ""))
        if value is None:
            continue
        suffix = (match.group("suffix") or "").lower()
        if suffix.startswith("basis"):
            suffix = "bps"
        exponent = int(match.group("exp") or 0) + SCALE.get(suffix, 0)
        unit = Decimal(1).scaleb(exponent - len(frac))
        value = value.scaleb(exponent)
        exact = not frac and not match.group("exp") and suffix not in SCALE and abs(value) < 100
        out.append({"text": match.group(0).strip(), "value": value, "unit": unit, "exact": exact})
    return out


def trace_numbers(answer, results, question=""):
    """-> list of {text, traced, source, tool_value}. results: structured tool results, in call order."""
    numbers, strings = corpus(results, question)
    joined = "\n".join(strings)
    stripped, verbatim = _strip_verbatim(answer)
    traces = []
    for kind, text in verbatim:
        found = text in joined
        traces.append({"text": text, "kind": kind, "traced": found, "source": "verbatim" if found else None, "tool_value": None})
    for token in tokens(stripped):
        tolerance = Decimal(0) if token["exact"] else token["unit"] / 2
        match = next(((value, path) for value, path in numbers if abs(abs(value) - abs(token["value"])) <= tolerance), None)
        traces.append({"text": token["text"], "kind": "number", "traced": match is not None,
                       "source": match[1] if match else None, "tool_value": str(match[0]) if match else None})
    return traces


def quotes(answer, value):
    """True if the answer states `value` (a tool decimal string) at the precision shown."""
    target = abs(Decimal(value))
    stripped, _ = _strip_verbatim(answer)
    return any(abs(abs(t["value"]) - target) <= (Decimal(0) if t["exact"] else t["unit"] / 2) for t in tokens(stripped))
