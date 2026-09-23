"""Closed JSON Schemas plus validation of the subset used by this project."""

import json
import re
from datetime import date, datetime

from .policy import METRICS, POLICY, TAGS, Refusal


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
WARNINGS = array(TEXT, maximum=100)
COMPANY = obj({"cik": CIK_SCHEMA, "name": TEXT, "ticker": {"type": "string", "pattern": "^[A-Z]{1,5}$"}})
CORE_PROPERTIES = {
    "cik": CIK_SCHEMA, "metric": {"enum": list(TAGS)}, "value": DECIMAL, "unit": {"const": "USD"},
    "fiscal_year": YEAR, "period_start": DATE, "period_end": DATE, "reported_fy": YEAR,
    "fp": {"enum": ["FY", "Q1", "Q2", "Q3"]}, "form": {"enum": ["10-K", "10-K/A", "10-Q", "10-Q/A"]}, "filed": DATE,
    "accn": ACCN, "tag": {"enum": ["us-gaap:" + tag for tag in set(TAGS.values()) | {"Revenues"}]}, "source_url": FILING_URL,
}
REJECTION = obj({"accn": {"type": "string", "maxLength": 100}, "start": {"anyOf": [TEXT, {"type": "null"}]},
                 "end": DATE, "unit": TEXT, "filed": {"anyOf": [DATE, {"type": "null"}]}, "reason": TEXT})
AUDIT = {"rejection_counts": {"type": "object", "additionalProperties": COUNT},
         "rejected_candidates": array({"$ref": "#/$defs/rejection"}, maximum=20), "rejected_candidates_truncated": COUNT}
FACT_OK = obj({**CORE_PROPERTIES, **AUDIT, "status": {"const": "ok"},
               "original": {"$ref": "#/$defs/fact_core"}, "history": array({"$ref": "#/$defs/fact_core"}, 1),
               "revision_candidate": {"type": "boolean"}, "warnings": WARNINGS})
ROW = {"fiscal_year": YEAR, "period_start": DATE, "period_end": DATE}
FACT_ERROR = obj({**ROW, **AUDIT, "metric": {"enum": list(TAGS)}, "value": {"type": "null"},
                  "status": {"enum": ["insufficient_data", "ambiguous"]}, "reason": TEXT,
                  "blocking_candidates": array({"$ref": "#/$defs/rejection"}, 1, 20), "blocking_candidates_total": COUNT},
                 optional=("blocking_candidates", "blocking_candidates_total"))
RATIO_BASE = {**ROW, "metric": {"enum": ["gross_margin", "operating_margin", "revenue_growth"]}, "unit": {"const": "percent"}}
RATIO_OK = obj({**RATIO_BASE, "status": {"const": "ok"}, "value": DECIMAL, "display_value": DECIMAL,
                "exact_fraction": obj({"numerator": INTEGER_TEXT, "denominator": {"type": "string", "pattern": "^[1-9][0-9]*$", "maxLength": 100}}),
                "precision": obj({"significant_digits": {"const": 34}, "rounding": {"const": "ROUND_HALF_EVEN"}, "display_places": {"const": 2}}),
                "formula": {"enum": ["gross_profit / revenue * 100", "operating_income / revenue * 100", "(current_revenue - prior_revenue) / prior_revenue * 100"]},
                "inputs": array({"$ref": "#/$defs/fact_ok"}, 2, 2), "warnings": WARNINGS})
RATIO_ERROR = obj({**RATIO_BASE, "status": {"const": "insufficient_data"}, "value": {"type": "null"}, "reason": TEXT,
                   "inputs": array({"$ref": "#/$defs/fact"}, 2, 2)}, optional=("inputs",))
REFUSAL = obj({"status": {"const": "refused"}, "code": TEXT, "message": TEXT})
CONTEXT = obj({"company": COMPANY, "as_of": DATE,
               "snapshot_captured_at": {"type": "string", "format": "date-time"},
               "evidence_kind": {"const": "sec_api_snapshot"},
               "snapshot_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
               "policy": obj({key: TEXT for key in POLICY}), "warnings": WARNINGS})
DEFS = {"fact_core": obj(CORE_PROPERTIES), "rejection": REJECTION, "fact_ok": FACT_OK,
        "fact_error": FACT_ERROR, "fact": {"oneOf": [{"$ref": "#/$defs/fact_ok"}, {"$ref": "#/$defs/fact_error"}]},
        "ratio_ok": RATIO_OK, "ratio_error": RATIO_ERROR,
        "result": {"oneOf": [{"$ref": "#/$defs/" + name} for name in ("fact_ok", "fact_error", "ratio_ok", "ratio_error")]}}


def output_schema(kind):
    if kind == "resolve_company":
        success = obj({**COMPANY["properties"], "status": {"const": "ok"},
                       "lookup_timestamp": {"type": "string", "format": "date-time"}, "lookup_is_cached": {"const": True},
                       "source_url": {"type": "string", "pattern": r"^https://data\.sec\.gov/submissions/CIK[0-9]{10}\.json$"}})
    else:
        success = obj({"status": {"enum": ["ok", "partial"]}, "context": CONTEXT,
                       "results": array({"$ref": "#/$defs/fact" if kind in ("get_annual_facts", "get_quarterly_facts") else "#/$defs/result"}, 1, 21)})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "$defs": DEFS,
            "oneOf": [success, REFUSAL]}


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
        raise Refusal("unsupported_metric", path + " must be one of " + ", ".join(map(str, schema["enum"])))
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
            raise Refusal("invalid_arguments", path + " has an invalid length")
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
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError()
        except ValueError:
            raise Refusal("invalid_arguments", path + " has an invalid date")
    elif kind == "integer":
        if not schema.get("minimum", value) <= value <= schema.get("maximum", value):
            raise Refusal("unsupported_years", path + " is outside the allowed range")
