"""Closed JSON Schemas plus validation of the subset used by this project."""

import json
import re
from datetime import date, datetime

from .policy import ANNUAL_TAGS, ANNUAL_YEARS, MAX_YEARS, METRICS, POLICY, REVIEWED_TAGS, TAGS, Refusal


def obj(properties, optional=()):
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key not in optional], "additionalProperties": False}


def array(items, minimum=0, maximum=1000):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


TEXT = {"type": "string", "maxLength": 2000}
DATE = {"type": "string", "format": "date", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}
DECIMAL = {"type": "string", "pattern": r"^-?[0-9]+(?:\.[0-9]+)?$", "maxLength": 100}
INTEGER_TEXT = {"type": "string", "pattern": r"^-?[0-9]+$", "maxLength": 100}
COUNT = {"type": "integer", "minimum": 0}
CIK_SCHEMA = {"type": "string", "pattern": r"^[0-9]{10}$"}
ACCN = {"type": "string", "pattern": r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$"}
FILING_URL = {"type": "string", "pattern": r"^https://www\.sec\.gov/Archives/edgar/data/[0-9]+/[0-9]{18}/[A-Za-z0-9_.-]+\.html?$"}
YEAR = {"type": "integer", "minimum": 1900, "maximum": 2100}
REVIEWED_YEAR = {"type": "integer", "minimum": ANNUAL_YEARS[0], "maximum": ANNUAL_YEARS[-1]}
WARNINGS = array(TEXT, maximum=100)
COMPANY = obj({"cik": CIK_SCHEMA, "name": TEXT, "ticker": {"type": "string", "pattern": "^[A-Z]{1,5}$"}})
REJECTION = obj({"accn": {"type": "string", "maxLength": 100}, "start": {"anyOf": [TEXT, {"type": "null"}]},
                 "end": DATE, "unit": TEXT, "filed": {"anyOf": [DATE, {"type": "null"}]}, "reason": TEXT})
AUDIT = {"rejection_counts": {"type": "object", "additionalProperties": COUNT},
         "rejected_candidates": array({"$ref": "#/$defs/rejection"}, maximum=20), "rejected_candidates_truncated": COUNT}
ROW = {"fiscal_year": YEAR, "period_start": DATE, "period_end": DATE}
QUARTER_FPS = ["Q1", "Q2", "Q3"]
RATIO_BASE = {**ROW, "metric": {"enum": ["gross_margin", "operating_margin", "revenue_growth"]}, "unit": {"const": "percent"}}
REFUSAL = obj({"status": {"const": "refused"}, "code": TEXT, "message": TEXT})
CONTEXT = obj({"company": COMPANY, "as_of": DATE,
               "snapshot_captured_at": {"type": "string", "format": "date-time"},
               "evidence_kind": {"const": "sec_api_snapshot"},
               "snapshot_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
               "policy": obj({key: TEXT for key in POLICY}), "warnings": WARNINGS})


def definitions(quarterly):
    """Annual and quarterly results differ only in which forms and fiscal periods are valid."""
    forms, fps = (["10-Q", "10-Q/A"], QUARTER_FPS) if quarterly else (["10-K", "10-K/A"], ["FY"])
    facts = TAGS if quarterly else ANNUAL_TAGS
    core = {"cik": CIK_SCHEMA, "metric": {"enum": list(facts)}, "value": DECIMAL, "unit": {"const": "USD"},
            "fiscal_year": YEAR, "period_start": DATE, "period_end": DATE, "reported_fy": YEAR,
            "fp": {"enum": fps}, "form": {"enum": forms}, "filed": DATE,
            "accn": ACCN, "tag": {"enum": ["us-gaap:" + tag for tag in REVIEWED_TAGS]}, "source_url": FILING_URL}
    provenance = {**core, "status": {"const": "ok"}, "original": {"$ref": "#/$defs/fact_core"},
                  "history": array({"$ref": "#/$defs/fact_core"}, 1), "revision_candidate": {"type": "boolean"}, "warnings": WARNINGS}
    error = obj({**ROW, **AUDIT, "metric": {"enum": list(facts)}, "value": {"type": "null"}, "fp": {"enum": fps},
                 "status": {"enum": ["insufficient_data", "ambiguous"]}, "reason": TEXT,
                 "blocking_candidates": array({"$ref": "#/$defs/rejection"}, 1, 20), "blocking_candidates_total": COUNT},
                optional=("fp", "blocking_candidates", "blocking_candidates_total"))
    ratio_ok = obj({**RATIO_BASE, "status": {"const": "ok"}, "value": DECIMAL, "display_value": DECIMAL,
                    "exact_fraction": obj({"numerator": INTEGER_TEXT, "denominator": {"type": "string", "pattern": "^[1-9][0-9]*$", "maxLength": 100}}),
                    "precision": obj({"significant_digits": {"const": 34}, "rounding": {"const": "ROUND_HALF_EVEN"}, "display_places": {"const": 2}}),
                    "formula": {"enum": ["gross_profit / revenue * 100", "operating_income / revenue * 100", "(current_revenue - prior_revenue) / prior_revenue * 100"]},
                    "inputs": array({"$ref": "#/$defs/operand_ok"}, 2, 2), "warnings": WARNINGS})
    ratio_error = obj({**RATIO_BASE, "status": {"const": "insufficient_data"}, "value": {"type": "null"}, "reason": TEXT,
                       "inputs": array({"oneOf": [{"$ref": "#/$defs/operand_ok"}, {"$ref": "#/$defs/fact_error"}]}, 2, 2)},
                      optional=("inputs",))
    return {"fact_core": obj(core), "rejection": REJECTION, "fact_ok": obj({**provenance, **AUDIT}),
            # Ratio operands keep provenance; the candidate audit stays on the requested fact rows.
            "operand_ok": obj(provenance), "fact_error": error,
            "fact": {"oneOf": [{"$ref": "#/$defs/fact_ok"}, {"$ref": "#/$defs/fact_error"}]},
            "ratio_ok": ratio_ok, "ratio_error": ratio_error,
            "result": {"oneOf": [{"$ref": "#/$defs/" + name} for name in ("fact_ok", "fact_error", "ratio_ok", "ratio_error")]}}


def output_schema(kind):
    quarterly = kind == "get_quarterly_facts"
    if kind == "resolve_company":
        success = obj({**COMPANY["properties"], "status": {"const": "ok"},
                       "lookup_timestamp": {"type": "string", "format": "date-time"}, "lookup_is_cached": {"const": True},
                       "source_url": {"type": "string", "pattern": r"^https://data\.sec\.gov/submissions/CIK[0-9]{10}\.json$"}})
    else:
        limit = len(TAGS) if quarterly else MAX_YEARS * len(METRICS)
        success = obj({"status": {"enum": ["ok", "partial"]}, "context": CONTEXT,
                       "results": array({"$ref": "#/$defs/fact" if kind in ("get_annual_facts", "get_quarterly_facts") else "#/$defs/result"}, 1, limit)})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "$defs": definitions(quarterly),
            "oneOf": [success, REFUSAL]}


# Agents act on refusal codes, so a failed field maps to the code its domain check would give.
FIELD_CODES = (("metrics", "unsupported_metric"), ("fiscal_year", "unsupported_years"),
               ("ticker", "unsupported_company"), ("firm", "unsupported_company"), ("quarter", "unsupported_quarter"))
RFC3339 = r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})"


def field_code(path):
    field = path.split(".")[-1].rstrip("[]")
    return next((code for name, code in FIELD_CODES if field.startswith(name)), "invalid_arguments")


def validate_schema(value, schema, path="arguments", root=None):
    """No remote refs or dependency; every emitted schema keyword is enforced."""
    root = schema if root is None else root
    if "$ref" in schema:
        if not schema["$ref"].startswith("#/$defs/"):
            raise Refusal("invalid_contract", "Only local schema definitions are supported.")
        return validate_schema(value, root["$defs"][schema["$ref"].split("/")[-1]], path, root)
    for key in ("oneOf", "anyOf"):
        if key in schema:
            matches = 0
            for branch in schema[key]:
                try:
                    validate_schema(value, branch, path, root)
                    matches += 1
                except Refusal:
                    pass
            if matches < 1 or (key == "oneOf" and matches != 1):
                raise Refusal("invalid_arguments", path + " does not match its allowed shape")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise Refusal("invalid_arguments", path + " has an invalid constant")
    if "enum" in schema and value not in schema["enum"]:
        raise Refusal(field_code(path), path + " must be one of " + ", ".join(map(str, schema["enum"])))
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    if kind and type(value) is not types[kind]:
        raise Refusal("invalid_arguments", path + " must be " + kind)
    if kind == "object":
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise Refusal("invalid_arguments", path + " is missing required fields")
        extras = set(value) - set(properties)
        if schema.get("additionalProperties") is False and extras:
            raise Refusal("invalid_arguments", path + " contains unknown fields")
        for name in value.keys() & properties.keys():
            validate_schema(value[name], properties[name], path + "." + name, root)
        if isinstance(schema.get("additionalProperties"), dict):
            for name in extras:
                validate_schema(value[name], schema["additionalProperties"], path + "." + name, root)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1000):
            raise Refusal("invalid_arguments", path + " must contain " + str(schema.get("minItems", 0)) + " to " + str(schema.get("maxItems", 1000)) + " items")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise Refusal("invalid_arguments", path + " must contain unique values")
        for item in value:
            validate_schema(item, schema["items"], path + "[]", root)
    elif kind == "string":
        if len(value) > schema.get("maxLength", 2000) or ("pattern" in schema and re.fullmatch(schema["pattern"], value) is None):
            raise Refusal("invalid_arguments", path + " has an invalid format")
        try:
            if schema.get("format") == "date":
                date.fromisoformat(value)
            if schema.get("format") == "date-time":
                if not re.fullmatch(RFC3339, value):
                    raise ValueError()
                # Fractions are dropped because Python 3.9 parses only 3- or 6-digit fractions.
                datetime.fromisoformat(value[:10] + "T" + re.sub(r"\.[0-9]+", "", value[11:]).upper().replace("Z", "+00:00"))
        except ValueError:
            raise Refusal("invalid_date", path + " has an invalid date")
    elif kind == "integer":
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise Refusal(field_code(path), path + " is outside the allowed range")


# Treasury tools (dat-accretion export). Numbers are decimal strings; every record carries its SEC filing.
NULLABLE_DECIMAL = {"anyOf": [DECIMAL, {"type": "null"}]}
SEC_URL = {"type": "string", "pattern": r"^https://www\.sec\.gov/Archives/edgar/data/[0-9]+/[0-9]{18}/[A-Za-z0-9_.-]+\.html?$"}
TREASURY_FIRM = obj({"ticker": {"enum": ["MSTR", "BMNR", "SBET"]}, "name": TEXT, "cik": CIK_SCHEMA, "coin": {"enum": ["BTC", "ETH"]}})
TREASURY_PROVENANCE = obj({"filed": DATE, "filing_url": SEC_URL, "accession": ACCN, "price_date": DATE}, optional=("price_date",))
TREASURY_SOURCE = obj({"repository": {"const": "https://github.com/RahilBhavan/dat-accretion"},
                       "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"}, "engine": TEXT, "market_data": TEXT,
                       "snapshot_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}})
TREASURY_WEEK = obj({"week_end": DATE, "coin": {"enum": ["BTC", "ETH"]}, "coins_per_share": DECIMAL, "coins_per_share_unit": TEXT,
                     "net_sats_per_share": NULLABLE_DECIMAL, "net_mnav": DECIMAL, "coin_price_usd": DECIMAL, "share_price_usd": DECIMAL, "diluted_shares": DECIMAL,
                     "coin_holdings": DECIMAL, "preferred_close_usd": NULLABLE_DECIMAL, "provenance": TREASURY_PROVENANCE})
TREASURY_ACTION = obj({
    "week_end": DATE, "prior_week_end": DATE, "action": {"enum": ["issue_common", "buyback_common", "issue_pref", "retire_pref",
                                                                  "buy_coin", "sell_coin", "carry", "est_issuance"]},
    "ticker": {"type": "string", "pattern": "^[A-Z_]{1,12}$"}, "basis": {"enum": ["filed", "estimated"]}, "note": TEXT,
    "usd": DECIMAL, "units": NULLABLE_DECIMAL, "avg_price_usd": NULLABLE_DECIMAL, "m_at_action": NULLABLE_DECIMAL,
    "q_at_action": NULLABLE_DECIMAL, "coin": {"enum": ["BTC", "ETH"]}, "coins_per_share_before": DECIMAL,
    "coins_per_share_change": DECIMAL, "coins_per_share_change_first_order": NULLABLE_DECIMAL,
    "effect_bps_of_coins_per_share": DECIMAL, "value_to_common_usd": DECIMAL,
    "direction": {"enum": ["adds", "reduces", "neutral"]}, "provenance": TREASURY_PROVENANCE})
TREASURY_SUCCESS = {
    "get_treasury_actions": obj({"status": {"const": "ok"}, "firm": TREASURY_FIRM, "matched": COUNT, "returned": COUNT,
                                 "actions": array(TREASURY_ACTION, 1, 20), "source": TREASURY_SOURCE, "warnings": WARNINGS}),
    "get_coins_per_share": obj({"status": {"const": "ok"}, "firm": TREASURY_FIRM, "week": TREASURY_WEEK,
                                "comparison": {"anyOf": [{"type": "null"}, obj({"week": TREASURY_WEEK, "change_coins_per_share": DECIMAL,
                                                                                   "change_percent": DECIMAL})]},
                                "stated_weeks": obj({"first": DATE, "last": DATE, "count": COUNT}),
                                "source": TREASURY_SOURCE, "warnings": WARNINGS}),
    "get_break_even": obj({"status": {"const": "ok"}, "firm": TREASURY_FIRM, "break_even": obj({
        "week_end": DATE, "preferred": {"enum": ["STRC", "BMNP"]}, "liquidation_preference_usd": {"const": "100"},
        "net_mnav": DECIMAL, "break_even_price_usd": DECIMAL, "preferred_close_usd": DECIMAL, "gap_usd": DECIMAL,
        "rotation": TEXT, "adds_while": TEXT, "adds_at_close": {"type": "boolean"}, "provenance": TREASURY_PROVENANCE}),
        "source": TREASURY_SOURCE, "warnings": WARNINGS}),
}
TREASURY_EMPTY = obj({"status": {"const": "insufficient_data"}, "firm": TREASURY_FIRM, "reason": TEXT, "source": TREASURY_SOURCE})


def treasury_output_schema(kind):
    branches = [TREASURY_SUCCESS[kind], REFUSAL] + ([TREASURY_EMPTY] if kind == "get_treasury_actions" else [])
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "oneOf": branches}
