"""Freeze dat-accretion's engine output into data/treasury/snapshot.json.

Runs the dat-accretion engine itself (dat.engine.states, week_rows, attribute) from a local
checkout, so every per-action effect served by the treasury tools is the engine's own exact
recompute. The MCP server then reads only this frozen file: standard library, no network,
no dat-accretion import at serve time. Rerun after a dat-accretion refresh merges:

    python3 -B scripts/export_dat_snapshot.py --dat-repo ../dat-accretion

The export refuses to write if the rebuilt attribution differs from the checkout's committed
data/attribution.csv or if a rebuilt n differs from data/weekly.csv.
"""

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "treasury" / "snapshot.json"
INPUTS = ("actions.csv", "attribution.csv", "balances.csv", "stated.csv", "weekly.csv", "prices.csv", "staking.csv")
FIRMS = {
    "MSTR": {"name": "Strategy", "cik": "0001050446", "coin": "BTC", "preferred": "STRC"},
    "BMNR": {"name": "BitMine Immersion Technologies", "cik": "0001829311", "coin": "ETH", "preferred": "BMNP"},
    "SBET": {"name": "SharpLink Gaming", "cik": "0001981535", "coin": "ETH", "preferred": None},
}
SKIP = ("price", "itm_flip", "residual")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(dat_repo, output=OUTPUT):
    dat_repo = Path(dat_repo).resolve()
    sys.path.insert(0, str(dat_repo))
    from dat.balances import read
    from dat.engine import attribute, state_net, states, week_rows
    from dat.balances import bmnr_s_bias

    data = dat_repo / "data"
    rows = {name: read(str(data / name)) for name in ("actions.csv", "attribution.csv", "balances.csv",
                                                      "stated.csv", "weekly.csv")}
    commit = subprocess.run(["git", "-C", str(dat_repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(dat_repo), "status", "--porcelain", "data", "dat"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise SystemExit("dat-accretion checkout has uncommitted data/ or dat/ changes; export from a clean commit")
    committed = {}
    for r in rows["attribution.csv"]:
        committed.setdefault((r["firm"], r["week_end"]), []).append(r)
    weeks_out, actions_out = [], []
    for firm in FIRMS:
        pick = lambda table: [r for r in rows[table] if r["firm"] == firm]
        bal = sorted(pick("balances.csv"), key=lambda b: b["date"])
        weekly = {r["week_end"]: {**r, "p": float(r["p"]), "s": float(r["s"])} for r in pick("weekly.csv")}
        stated = {r["week_end"]: r for r in pick("stated.csv")}
        actions = pick("actions.csv")
        sts = states(firm, bal, weekly, sorted(pick("stated.csv"), key=lambda r: r["week_end"]), actions)
        notes = {b["date"]: b["source"] for b in bal}
        order = [b["date"] for b in bal]
        for w in order:
            net = state_net(sts[w])
            if abs(net["n"] / float(weekly[w]["n"]) - 1) > 1e-9:
                raise SystemExit("rebuilt n differs from weekly.csv for " + firm + " " + w)
            weeks_out.append({"firm": firm, "week_end": w, "price_date": weekly[w]["price_date"],
                              "n": net["n"], "m": float(weekly[w]["m"]),
                              "q": float(weekly[w]["q"]) if weekly[w]["q"] else None,
                              "p": weekly[w]["p"], "s": weekly[w]["s"], "S": net["S"], "coins": sts[w]["C"],
                              "filed": stated[w]["filed"], "filing_url": stated[w]["filing_url"],
                              "state_note": notes[w]})
        for prev_w, w in zip(order, order[1:]):
            prev, cur = sts[prev_w], sts[w]
            out, _ = attribute(prev, cur, week_rows(firm, prev_w, w, prev, cur, actions))
            applied = [a for a in week_rows(firm, prev_w, w, prev, cur, actions)]
            effects = [r for r in out if r["action"] not in SKIP]
            mine = [r for r in committed.get((firm, w), []) if r["action"] not in SKIP]
            if len(effects) != len(applied) or len(effects) != len(mine):
                raise SystemExit("attribution row count mismatch for " + firm + " " + w)
            for source, effect, check in zip(applied, effects, mine):
                if check["action"] != effect["action"] or not math.isclose(float(check["dn_exact"]), effect["dn_exact"],
                                                                          rel_tol=1e-9, abs_tol=1e-18):
                    raise SystemExit("engine rebuild differs from committed attribution.csv for " + firm + " " + w)
                estimated = effect["action"] == "est_issuance"
                actions_out.append({
                    "firm": firm, "week_end": w, "prior_week_end": prev_w, "action": effect["action"],
                    "ticker": source["ticker"], "usd": float(source["usd"]),
                    "units": float(source["units"]) if source.get("units") not in (None, "") else None,
                    "avg_price": float(source["avg_price"]) if source.get("avg_price") not in (None, "") else None,
                    "filed": stated[w]["filed"] if estimated else source["filed"],
                    "filing_url": stated[w]["filing_url"] if estimated else source["filing_url"],
                    "estimated": estimated, "note": notes[w] if estimated else source.get("note", ""),
                    "m": effect.get("m"), "q": effect.get("q"), "dn_first_order": effect.get("dn_first_order"),
                    "dn_exact": effect["dn_exact"], "dn_per_dollar": effect.get("dn_per_dollar"),
                    "n_before": state_net(prev)["n"], "S": state_net(cur)["S"], "p": cur["p"]})
    bias, bias_week = bmnr_s_bias(str(data))
    snapshot = {
        "source": {"repository": "https://github.com/RahilBhavan/dat-accretion", "commit": commit,
                   "files": {name: sha256(data / name) for name in INPUTS},
                   "exporter": "scripts/export_dat_snapshot.py",
                   "engine": "dat.engine.attribute (exact recompute through dat.balances.net)",
                   "market_data": "CoinGecko daily closes (BTC, ETH); Yahoo daily closes (common and preferred shares)"},
        "firms": FIRMS,
        "bmnr_s_bias": {"bias": bias, "week_end": bias_week},
        "weeks": weeks_out,
        "actions": actions_out,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
    return {"weeks": len(weeks_out), "actions": len(actions_out), "commit": commit}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dat-repo", required=True, help="Path to a clean dat-accretion checkout")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    print(json.dumps(export(args.dat_repo, args.output)))


if __name__ == "__main__":
    main()
