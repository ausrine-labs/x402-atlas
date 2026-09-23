#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 14d153d). Edit it there, not here.
"""whales.py — the agent whales: which wallets pay a lot, for what, and which
sellers are actually paid on-chain.

The registry says what each seller reports about itself. The chain says who
paid whom (chain_flows.py, solana_flows.py). This rolls those payments up both
ways and puts the on-chain figure next to the self-reported one, labelled.

    whales.py report --flows flows-2026-09-23.json [more days or chains ...]
                     [--snapshot radar-store/market-2026-09-23.json]
                     [--top 15] [--out whales-2026-09-23.json]

    buyers   every paying wallet: USDC, payments, how many sellers, what kinds
    agents   the buyers that paid three or more sellers — a wallet that shops
             around is an agent at work; a wallet that paid one seller once is
             more often a person buying a gift card
    sellers  who actually got paid, next to what the registry says about them

Two windows are compared, never confused: on-chain figures cover the pulled
hours; the registry's counts are its own rolling 30 days. Both are shown per
day so they can sit side by side. Standard library only. MIT.
"""

import argparse
import collections
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market  # noqa: E402

EXPLORER = {"Base": "https://basescan.org/address/", "Solana": "https://solscan.io/account/"}


def short(w):
    return w[:6] + "…" + w[-4:] if len(w) > 14 else w


def load_flows(paths):
    """Merge pulls (days, chains) into one edge list. Windows add up; a wallet
    keeps the chain it was first seen on."""
    edges, sellers, chain_of, hours, dates = [], {}, {}, 0.0, []
    for p in paths:
        fl = json.load(open(p))
        chain = {"solana": "Solana"}.get(fl.get("chain", ""), "Base")
        hours += fl.get("hours", 0) or 0
        dates.append(fl.get("date", "?"))
        for w, hs in fl["sellers"].items():
            sellers.setdefault(w, hs)
            chain_of.setdefault(w, chain)
        for e in fl["edges"]:
            chain_of.setdefault(e["from"], chain)
            edges.append(e)
    return edges, sellers, chain_of, hours, sorted(set(dates))


def load_snapshot(path):
    if not path:
        return {}
    return json.load(open(path))["sellers"]


def host_of(wallet, sellers, snap):
    """A wallet paid several hosts: name it by the busiest one the registry knows."""
    hs = sellers.get(wallet) or []
    if not hs:
        return None
    return max(hs, key=lambda h: snap.get(h, {}).get("calls", 0))


def rollup(edges, sellers, chain_of, hours, snap):
    per_day = (hours / 24.0) if hours else None
    buyers = {}
    sold = {}
    for e in edges:
        f, t = e["from"], e["to"]
        host = host_of(t, sellers, snap) or short(t)
        sells = snap.get(host, {}).get("sells", "")
        category = market.cat(sells + " " + host)[0] if (sells or host) else "other"
        b = buyers.setdefault(f, {"wallet": f, "chain": chain_of.get(f, "Base"), "usdc": 0.0, "payments": 0,
                                  "sellers": {}, "categories": collections.Counter()})
        b["usdc"] += e["usdc"]
        b["payments"] += e["n"]
        s = b["sellers"].setdefault(host, {"host": host, "payments": 0, "usdc": 0.0, "category": category})
        s["payments"] += e["n"]
        s["usdc"] += e["usdc"]
        b["categories"][category] += e["n"]
        r = sold.setdefault(host, {"host": host, "wallets": set(), "chain": chain_of.get(t, "Base"), "usdc": 0.0,
                                   "payments": 0, "buyers": set(), "category": category, "sells": sells[:140]})
        r["wallets"].add(t)
        r["usdc"] += e["usdc"]
        r["payments"] += e["n"]
        r["buyers"].add(f)

    out_buyers = []
    for b in buyers.values():
        ss = sorted(b["sellers"].values(), key=lambda s: (-s["usdc"], -s["payments"]))
        out_buyers.append({
            "wallet": b["wallet"], "short": short(b["wallet"]), "chain": b["chain"],
            "explorer": EXPLORER.get(b["chain"], "") + b["wallet"],
            "usdc": round(b["usdc"], 2), "payments": b["payments"], "sellers_paid": len(ss),
            "avg_payment_usdc": round(b["usdc"] / b["payments"], 4) if b["payments"] else 0,
            "categories": [c for c, _ in b["categories"].most_common()],
            "sellers": [dict(s, usdc=round(s["usdc"], 2)) for s in ss[:8]],
        })
    out_buyers.sort(key=lambda b: (-b["usdc"], -b["payments"]))

    out_sellers = []
    for r in sold.values():
        me = snap.get(r["host"], {})
        calls30 = me.get("calls")
        out_sellers.append({
            "host": r["host"], "chain": r["chain"], "wallets": sorted(r["wallets"]), "category": r["category"],
            "sells": r["sells"],
            "on_chain_usdc": round(r["usdc"], 2), "on_chain_payments": r["payments"],
            "on_chain_buyer_wallets": len(r["buyers"]),
            "on_chain_payments_per_day": round(r["payments"] / per_day, 1) if per_day else None,
            "self_reported_calls_30d": calls30,
            "self_reported_calls_per_day": round(calls30 / 30.0, 1) if calls30 is not None else None,
            "self_reported_payers_30d": me.get("payers"),
        })
    out_sellers.sort(key=lambda s: (-s["on_chain_usdc"], -s["on_chain_payments"]))

    return {
        "hours": hours,
        "totals": {"payments": sum(e["n"] for e in edges), "usdc": round(sum(e["usdc"] for e in edges), 2),
                   "buyer_wallets": len(buyers), "sellers_paid": len(sold), "sellers_known": len(sellers),
                   "agents_3plus": sum(1 for b in out_buyers if b["sellers_paid"] >= 3)},
        "buyers": out_buyers,
        "agents": sorted([b for b in out_buyers if b["sellers_paid"] >= 3],
                         key=lambda b: (-b["payments"], -b["usdc"])),
        "sellers": out_sellers,
        "notes": [
            "On-chain figures are real USDC transfers to seller wallets the public x402 registry names, "
            "over the pulled hours only. A seller whose wallet is not in the registry is invisible here.",
            "Self-reported figures are the registry's own rolling 30-day counts. The two windows differ; "
            "both are shown per day so they can be compared, and neither is adjusted to match the other.",
            "A wallet is not an agent. One operator can appear as many wallets; a wallet paying several "
            "sellers is the honest signal of an agent at work.",
            "Payments to a wallet shared by several hosts are credited to the busiest host the registry knows.",
        ],
    }


def report(d, dates, top):
    t = d["totals"]
    print("── AGENT WHALES · %s · %.0f h on-chain ──" % (", ".join(dates), d["hours"]))
    print("   %s payments · $%s USDC · %d buyer wallets · %d sellers paid (of %d with a known wallet)"
          % ("{:,}".format(t["payments"]), "{:,.2f}".format(t["usdc"]), t["buyer_wallets"],
             t["sellers_paid"], t["sellers_known"]))
    print("   %d wallets paid three or more sellers" % t["agents_3plus"])

    print("\n  AGENTS AT WORK  (paid 3+ sellers, by payments)")
    for b in d["agents"][:top]:
        print("    %-13s %6d payments  $%9.2f  %2d sellers  %s"
              % (b["short"], b["payments"], b["usdc"], b["sellers_paid"],
                 ", ".join(s["host"][:22] for s in b["sellers"][:3])))
        print("    %-13s %s" % ("", " · ".join(b["categories"][:3])))

    print("\n  BIGGEST SPENDERS  (by USDC)")
    for b in d["buyers"][:top]:
        print("    %-13s $%9.2f  %5d payments  %2d sellers  → %s"
              % (b["short"], b["usdc"], b["payments"], b["sellers_paid"],
                 ", ".join(s["host"][:24] for s in b["sellers"][:2])))

    print("\n  SELLERS, PAID ON-CHAIN  (per day: on-chain over the pulled hours vs self-reported over 30 days)")
    print("    %-30s %10s %7s %6s   %9s %9s  %s" % ("seller", "usdc", "pays", "buyers", "chain/day", "self/day", "sells"))
    for s in d["sellers"][:top]:
        print("    %-30s %10.2f %7d %6d   %9s %9s  %s"
              % (s["host"][:30], s["on_chain_usdc"], s["on_chain_payments"], s["on_chain_buyer_wallets"],
                 "%.1f" % s["on_chain_payments_per_day"] if s["on_chain_payments_per_day"] is not None else "—",
                 "%.1f" % s["self_reported_calls_per_day"] if s["self_reported_calls_per_day"] is not None else "—",
                 s["sells"][:36]))
    for n in d["notes"]:
        print("\n   " + n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="roll the pulled payments up by buyer and by seller")
    r.add_argument("--flows", nargs="+", required=True, help="chain_flows.py / solana_flows.py output, any number")
    r.add_argument("--snapshot", help="radar-store/market-<date>.json, for names, categories and self-reported counts")
    r.add_argument("--top", type=int, default=15)
    r.add_argument("--out", help="write the full rollup as JSON")
    a = ap.parse_args()

    edges, sellers, chain_of, hours, dates = load_flows(a.flows)
    snap = load_snapshot(a.snapshot)
    d = rollup(edges, sellers, chain_of, hours, snap)
    d["dates"] = dates
    d["as_of"] = date.today().isoformat()
    report(d, dates, a.top)
    if a.out:
        json.dump(d, open(a.out, "w"), indent=1)
        print("\nwrote", a.out)


if __name__ == "__main__":
    main()
