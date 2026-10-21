"""Read-only treasury tools over a frozen dat-accretion engine export.

Strategy (MSTR), BitMine (BMNR) and SharpLink (SBET) capital actions measured on Strategy's net
coins per share definition. Every effect is dat-accretion's own exact recompute
(scripts/export_dat_snapshot.py runs dat.engine.attribute); this module only selects, scales and
renders. Each record carries the SEC filing it rests on. Estimated rows (BitMine's unreported
share issuance) say so in `basis` and name the 8-K whose reserve change sized them.

dat-accretion computes in binary floating point. Values render as decimal strings with ten
significant digits; money and prices as cents. No network, model, shell, or write access.
"""

import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

from .domain import iso_date
from .policy import Refusal

DEFAULT_SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "treasury" / "snapshot.json"
FIRMS = ("MSTR", "BMNR", "SBET")
ACTIONS = ("issue_common", "buyback_common", "issue_pref", "retire_pref", "buy_coin", "sell_coin", "carry",
           "est_issuance")
LIQUIDATION_PREFERENCE = Decimal(100)  # STRC stated amount and BMNP liquidation preference (dat method.md)
ROTATION = {
    "MSTR": ("Strategy issues common stock and retires STRC with the proceeds.", "below"),
    "BMNR": ("BitMine issues BMNP preferred and buys back common stock with the proceeds.", "above"),
}
ACCESSION = re.compile(r"/data/[0-9]+/([0-9]{10})([0-9]{2})([0-9]{6})/")


def significant(value, digits=10):
    """Float from the engine -> decimal string with `digits` significant digits, never exponent form."""
    if value is None:
        return None
    exact = Decimal(repr(float(value)))
    if exact == 0:
        return "0"
    step = Decimal(1).scaleb(exact.adjusted() - digits + 1)
    text = format(exact.quantize(step, rounding=ROUND_HALF_EVEN), "f")
    return text[1:] if text.startswith("-") and Decimal(text) == 0 else text


def places(value, digits=2):
    if value is None:
        return None
    text = format(Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_EVEN), "f")
    return text[1:] if text.startswith("-") and Decimal(text) == 0 else text


def provenance(filed, filing_url, price_date=None):
    match = ACCESSION.search(filing_url)
    if not match:
        raise Refusal("invalid_tool_output", "Record lacks an SEC filing URL.")
    out = {"filed": filed, "filing_url": filing_url, "accession": "-".join(match.groups())}
    if price_date is not None:
        out["price_date"] = price_date
    return out


class TreasuryService:
    def __init__(self, snapshot=DEFAULT_SNAPSHOT):
        raw = Path(snapshot).read_bytes()
        self.snapshot = json.loads(raw)
        self.snapshot_sha256 = hashlib.sha256(raw).hexdigest()
        self.weeks = {}
        for week in self.snapshot["weeks"]:
            self.weeks.setdefault(week["firm"], []).append(week)
        for firm in self.weeks:
            self.weeks[firm].sort(key=lambda w: w["week_end"])

    def _source(self):
        source = self.snapshot["source"]
        return {"repository": source["repository"], "commit": source["commit"], "engine": source["engine"],
                "market_data": source["market_data"], "snapshot_sha256": self.snapshot_sha256}

    def _firm(self, firm):
        if firm not in FIRMS:
            raise Refusal("unsupported_company", "Treasury coverage is MSTR (Strategy), BMNR (BitMine), and SBET (SharpLink).")
        info = self.snapshot["firms"][firm]
        return {"ticker": firm, "name": info["name"], "cik": info["cik"], "coin": info["coin"]}

    def _warnings(self, firm):
        warnings = []
        if firm == "BMNR":
            bias = self.snapshot["bmnr_s_bias"]
            warnings.append("BitMine diluted shares (S) are estimated between 10-Q filings; counting staked ETH as bought "
                            "biases S upward by up to " + places(bias["bias"] * 100) + "% at " + bias["week_end"] + ".")
        if firm == "SBET":
            warnings.append("SharpLink is measured only on dates its filings state ETH holdings; nothing is carried forward.")
        warnings.append("Per-share effects are measured, not judged; no forecast or investment view.")
        return warnings

    def _week(self, firm, week_end):
        weeks = self.weeks[firm]
        if week_end is None:
            return weeks[-1]
        iso_date(week_end)
        found = [w for w in weeks if w["week_end"] == week_end]
        if not found:
            raise Refusal("unknown_week", firm + " stated weeks are " + ", ".join(w["week_end"] for w in weeks) + ".")
        return found[0]

    def _week_record(self, week):
        coin = self.snapshot["firms"][week["firm"]]["coin"]
        return {"week_end": week["week_end"], "coin": coin, "coins_per_share": significant(week["n"]),
                "coins_per_share_unit": coin + " per diluted share",
                "net_sats_per_share": places(week["n"] * 1e8) if coin == "BTC" else None, "net_mnav": significant(week["m"], 7),
                "coin_price_usd": places(week["p"]), "share_price_usd": places(week["s"]),
                "diluted_shares": places(week["S"], 0), "coin_holdings": places(week["coins"], 0),
                "preferred_close_usd": places(LIQUIDATION_PREFERENCE * Decimal(repr(week["q"]))) if week["q"] is not None else None,
                "provenance": provenance(week["filed"], week["filing_url"], week["price_date"])}

    def get_treasury_actions(self, firm, action=None, week_from=None, week_to=None, limit=5):
        company = self._firm(firm)
        for value in (week_from, week_to):
            if value is not None:
                iso_date(value)
        rows = [(i, a) for i, a in enumerate(self.snapshot["actions"]) if a["firm"] == firm
                and (action is None or a["action"] == action)
                and (week_from is None or a["week_end"] >= week_from) and (week_to is None or a["week_end"] <= week_to)]
        rows.sort(key=lambda item: (item[1]["week_end"], item[0]), reverse=True)
        if not rows:
            return {"status": "insufficient_data", "firm": company,
                    "reason": "No " + (action or "action") + " rows for " + firm + " in the requested weeks. Stated weeks run "
                              + self.weeks[firm][0]["week_end"] + " to " + self.weeks[firm][-1]["week_end"]
                              + "; the first stated week is an anchor with no measured effects.",
                    "source": self._source()}
        actions = [self._action_record(a) for _, a in rows[:limit]]
        return {"status": "ok", "firm": company, "matched": len(rows), "returned": len(actions), "actions": actions,
                "source": self._source(), "warnings": self._warnings(firm)}

    def _action_record(self, a):
        coin = self.snapshot["firms"][a["firm"]]["coin"]
        dn = a["dn_exact"]
        return {"week_end": a["week_end"], "prior_week_end": a["prior_week_end"], "action": a["action"], "ticker": a["ticker"],
                "basis": "estimated" if a["estimated"] else "filed", "note": a["note"],
                "usd": places(a["usd"]), "units": places(a["units"], 0) if a["units"] is not None else None,
                "avg_price_usd": significant(a["avg_price"]) if a["avg_price"] is not None else None,
                "m_at_action": significant(a["m"], 7) if a["m"] is not None else None,
                "q_at_action": significant(a["q"], 7) if a["q"] is not None else None,
                "coin": coin, "coins_per_share_before": significant(a["n_before"]),
                "coins_per_share_change": significant(dn),
                "coins_per_share_change_first_order": significant(a["dn_first_order"]) if a["dn_first_order"] is not None else None,
                "effect_bps_of_coins_per_share": significant(dn / a["n_before"] * 1e4, 6),
                "value_to_common_usd": places(dn * a["S"] * a["p"]),
                "direction": "adds" if dn > 0 else "reduces" if dn < 0 else "neutral",
                "provenance": provenance(a["filed"], a["filing_url"])}

    def get_coins_per_share(self, firm, week_end=None, compare_to=None):
        company = self._firm(firm)
        week = self._week(firm, week_end)
        result = {"status": "ok", "firm": company, "week": self._week_record(week), "comparison": None,
                  "stated_weeks": {"first": self.weeks[firm][0]["week_end"], "last": self.weeks[firm][-1]["week_end"],
                                   "count": len(self.weeks[firm])},
                  "source": self._source(), "warnings": self._warnings(firm)}
        if compare_to is not None:
            other = self._week(firm, compare_to)
            change = week["n"] - other["n"]
            result["comparison"] = {"week": self._week_record(other), "change_coins_per_share": significant(change),
                                    "change_percent": significant(change / other["n"] * 100, 6)}
        return result

    def get_break_even(self, firm, week_end=None):
        company = self._firm(firm)
        if firm not in ROTATION:
            raise Refusal("no_preferred", "SharpLink has no preferred stock, so no rotation break-even exists; its common issuance adds coins per share only while net mNAV m is above 1.")
        week = self._week(firm, week_end)
        m = Decimal(repr(week["m"]))
        close = LIQUIDATION_PREFERENCE * Decimal(repr(week["q"]))
        break_even = LIQUIDATION_PREFERENCE * m
        rotation, side = ROTATION[firm]
        preferred = self.snapshot["firms"][firm]["preferred"]
        adds = close < break_even if side == "below" else close > break_even
        return {"status": "ok", "firm": company, "break_even": {
            "week_end": week["week_end"], "preferred": preferred, "liquidation_preference_usd": "100",
            "net_mnav": significant(week["m"], 7), "break_even_price_usd": places(break_even),
            "preferred_close_usd": places(close), "gap_usd": places(close - break_even),
            "rotation": rotation, "adds_while": preferred + " trades " + side + " the break-even price (liquidation preference x net mNAV)",
            "adds_at_close": adds, "provenance": provenance(week["filed"], week["filing_url"], week["price_date"])},
            "source": self._source(), "warnings": self._warnings(firm)}
