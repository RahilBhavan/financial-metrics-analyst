import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from financial_metrics.client import Client
from financial_metrics.domain import AnalystService
from financial_metrics.tools import TOOLS, call_tool
from financial_metrics.treasury import DEFAULT_SNAPSHOT, TreasuryService, significant

ROOT = Path(__file__).resolve().parent.parent
SEC = re.compile(r"^https://www\.sec\.gov/Archives/edgar/data/")
NUMERIC = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")


def numeric_fields_without_provenance(value, path="result"):
    """Paths of decimal-string numbers whose record has no provenance (directly or in a child record)."""
    missing = []
    if isinstance(value, dict):
        covered = "provenance" in value or any(isinstance(v, dict) and "provenance" in v for v in value.values())
        for key, item in value.items():
            if key in ("source", "stated_weeks", "provenance", "firm"):
                continue
            if isinstance(item, str) and NUMERIC.match(item) and not covered and key != "liquidation_preference_usd":
                missing.append(path + "." + key)
            missing += numeric_fields_without_provenance(item, path + "." + key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            missing += numeric_fields_without_provenance(item, path + "[" + str(i) + "]")
    return missing


class TreasuryToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = AnalystService()
        cls.snapshot = json.loads(DEFAULT_SNAPSHOT.read_text())

    def call(self, name, arguments):
        return call_tool(self.service, name, arguments)

    def test_seven_read_only_tools_with_closed_inputs(self):
        names = [t["name"] for t in TOOLS]
        self.assertEqual(names[4:], ["get_treasury_actions", "get_coins_per_share", "get_break_even"])
        for tool in TOOLS[4:]:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertEqual(tool["annotations"], {"readOnlyHint": True, "openWorldHint": False})

    def test_every_number_has_sec_provenance(self):
        calls = [("get_treasury_actions", {"firm": firm, "limit": 20}) for firm in ("MSTR", "BMNR", "SBET")]
        calls += [("get_coins_per_share", {"firm": "BMNR", "compare_to": "2026-06-07"}),
                  ("get_coins_per_share", {"firm": "SBET", "week_end": "2026-08-03"}),
                  ("get_break_even", {"firm": "MSTR"}), ("get_break_even", {"firm": "BMNR", "week_end": "2026-08-02"})]
        for name, arguments in calls:
            with self.subTest(name=name, arguments=arguments):
                result = self.call(name, arguments)
                self.assertFalse(result["isError"], result["structuredContent"])
                self.assertEqual(numeric_fields_without_provenance(result["structuredContent"]), [])
                text = result["content"][0]["text"]
                for url in re.findall(r'"filing_url":"([^"]+)"', text):
                    self.assertRegex(url, SEC)

    def test_all_actions_serve_through_the_output_contract(self):
        for firm in ("MSTR", "BMNR", "SBET"):
            for action in ("issue_common", "buyback_common", "issue_pref", "retire_pref", "buy_coin", "sell_coin", "carry", "est_issuance"):
                result = self.call("get_treasury_actions", {"firm": firm, "action": action, "limit": 20})
                self.assertIn(result["structuredContent"]["status"], ("ok", "insufficient_data"))

    def test_bitmine_issuance_is_labeled_estimated(self):
        rows = self.call("get_treasury_actions", {"firm": "BMNR", "action": "est_issuance", "limit": 20})["structuredContent"]["actions"]
        self.assertTrue(rows)
        self.assertTrue(all(r["basis"] == "estimated" and r["note"].startswith("release ") for r in rows))
        filed = self.call("get_treasury_actions", {"firm": "BMNR", "action": "buyback_common", "limit": 20})["structuredContent"]["actions"]
        self.assertTrue(all(r["basis"] == "filed" for r in filed))
        self.assertEqual(self.call("get_treasury_actions", {"firm": "BMNR", "action": "issue_common"})["structuredContent"]["status"],
                         "insufficient_data")

    def test_most_recent_first_and_limits(self):
        result = self.call("get_treasury_actions", {"firm": "BMNR", "action": "buyback_common", "limit": 2})["structuredContent"]
        self.assertEqual((result["matched"], result["returned"]), (5, 2))
        self.assertEqual([r["week_end"] for r in result["actions"]], ["2026-08-16", "2026-08-09"])
        window = self.call("get_treasury_actions", {"firm": "MSTR", "week_from": "2026-07-26", "week_to": "2026-07-26", "limit": 20})
        self.assertTrue(all(r["week_end"] == "2026-07-26" for r in window["structuredContent"]["actions"]))

    def test_method_anchor_strc_retirement_value_to_common(self):
        # dat-accretion method.md: the 7/26 STRC 8-K states $25.0M, so (1/q - 1)x = $3.893M to common.
        row = self.call("get_treasury_actions", {"firm": "MSTR", "action": "retire_pref", "week_from": "2026-07-26",
                                                 "week_to": "2026-07-26"})["structuredContent"]["actions"][0]
        self.assertEqual((row["usd"], row["value_to_common_usd"], row["direction"]), ("25000000.00", "3893000.00", "adds"))

    def test_memo_break_even_prices(self):
        # dat-accretion docs/memo.md, week ending 2026-10-11: STRC $119.07 at 1.191, BMNP $99.79 at 0.998.
        strategy = self.call("get_break_even", {"firm": "MSTR"})["structuredContent"]["break_even"]
        bitmine = self.call("get_break_even", {"firm": "BMNR"})["structuredContent"]["break_even"]
        self.assertEqual((strategy["week_end"], strategy["break_even_price_usd"], strategy["preferred_close_usd"]),
                         ("2026-10-11", "119.07", "99.65"))
        self.assertTrue(strategy["adds_at_close"])
        self.assertEqual((bitmine["break_even_price_usd"], bitmine["preferred_close_usd"], bitmine["adds_at_close"]),
                         ("99.79", "99.53", False))

    def test_first_order_formula_matches_engine_rows(self):
        # method.md: k = x/(p*S); issue_common k(1-1/m), buyback k(1/m-1), issue_pref k(1-1/q), retire_pref k(1/q-1).
        formulas = {"issue_common": lambda k, m, q: k * (1 - 1 / m), "est_issuance": lambda k, m, q: k * (1 - 1 / m),
                    "buyback_common": lambda k, m, q: k * (1 / m - 1), "issue_pref": lambda k, m, q: k * (1 - 1 / q),
                    "retire_pref": lambda k, m, q: k * (1 / q - 1)}
        checked = 0
        for a in self.snapshot["actions"]:
            if a["action"] in formulas:
                # The engine evaluates k with the pre-action S, which can differ from week-end S; compare loosely.
                k = a["usd"] / (a["p"] * a["S"])
                expected = formulas[a["action"]](k, a["m"], a["q"])
                self.assertAlmostEqual(a["dn_first_order"], expected, delta=abs(expected) * 0.05 + 1e-15)
                checked += 1
            elif a["action"] in ("buy_coin", "sell_coin"):
                self.assertEqual(a["dn_first_order"], 0.0)
        self.assertGreater(checked, 40)

    def test_coins_per_share_comparison(self):
        result = self.call("get_coins_per_share", {"firm": "BMNR", "week_end": "2026-10-11", "compare_to": "2026-06-07"})["structuredContent"]
        self.assertEqual(result["week"]["coins_per_share"], "0.009687168255")
        self.assertEqual(result["comparison"]["week"]["coins_per_share"], "0.009764363711")
        snapshot = {w["week_end"]: w["n"] for w in self.snapshot["weeks"] if w["firm"] == "BMNR"}
        self.assertEqual(result["comparison"]["change_coins_per_share"], significant(snapshot["2026-10-11"] - snapshot["2026-06-07"]))
        self.assertTrue(result["comparison"]["change_coins_per_share"].startswith("-0.0000771954560"))
        self.assertIsNone(result["week"]["net_sats_per_share"])
        strategy = self.call("get_coins_per_share", {"firm": "MSTR"})["structuredContent"]["week"]
        self.assertEqual(strategy["net_sats_per_share"], "156990.87")

    def test_refusals(self):
        cases = [("get_break_even", {"firm": "SBET"}, "no_preferred"),
                 ("get_coins_per_share", {"firm": "MSTR", "week_end": "2026-07-27"}, "unknown_week"),
                 ("get_coins_per_share", {"firm": "TSLA"}, None),
                 ("get_treasury_actions", {"firm": "BMNR", "limit": 0}, None),
                 ("get_treasury_actions", {"firm": "BMNR", "url": "https://attacker"}, None),
                 ("get_break_even", {"firm": "MSTR", "week_end": "2026-02-30"}, "invalid_date"),
                 ("get_treasury_actions", {}, None)]
        for name, arguments, code in cases:
            with self.subTest(arguments=arguments):
                result = self.call(name, arguments)
                self.assertTrue(result["isError"])
                if code:
                    self.assertEqual(result["structuredContent"]["code"], code)

    def test_snapshot_records_its_inputs(self):
        source = self.snapshot["source"]
        self.assertRegex(source["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(set(source["files"]), {"actions.csv", "attribution.csv", "balances.csv", "stated.csv",
                                                "weekly.csv", "prices.csv", "staking.csv"})
        served = TreasuryService().get_break_even("MSTR")["source"]
        self.assertEqual(served["snapshot_sha256"], hashlib.sha256(DEFAULT_SNAPSHOT.read_bytes()).hexdigest())

    @unittest.skipUnless(os.environ.get("DAT_ACCRETION_REPO"), "set DAT_ACCRETION_REPO to a clean dat-accretion checkout")
    def test_export_reproduces_committed_snapshot(self):
        repo = Path(os.environ["DAT_ACCRETION_REPO"])
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if commit != self.snapshot["source"]["commit"]:
            self.skipTest("checkout is at " + commit[:7] + ", snapshot at " + self.snapshot["source"]["commit"][:7])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "export_dat_snapshot.py"), "--dat-repo", str(repo),
                            "--output", str(output)], check=True, capture_output=True, cwd=directory)
            self.assertEqual(output.read_bytes(), DEFAULT_SNAPSHOT.read_bytes())

    def test_treasury_tools_over_stdio(self):
        with Client() as client:
            names = [t["name"] for t in client.request("tools/list")["result"]["tools"]]
            self.assertIn("get_break_even", names)
            result = client.call("get_treasury_actions", {"firm": "MSTR", "action": "retire_pref", "limit": 1})
            self.assertEqual(result["status"], "ok")
            self.assertRegex(result["actions"][0]["provenance"]["filing_url"], SEC)


if __name__ == "__main__":
    unittest.main()
