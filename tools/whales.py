#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 19e73aa). Edit it there, not here.
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
        nx, ux = e.get("n_x402", 0), e.get("usdc_x402", 0.0)
        b = buyers.setdefault(f, {"wallet": f, "chain": chain_of.get(f, "Base"), "usdc": 0.0, "payments": 0,
                                  "usdc_x402": 0.0, "payments_x402": 0, "sellers": {}, "sellers_x402": set(),
                                  "categories": collections.Counter()})
        b["usdc"] += e["usdc"]
        b["payments"] += e["n"]
        b["usdc_x402"] += ux
        b["payments_x402"] += nx
        if nx:
            b["sellers_x402"].add(host)
        s = b["sellers"].setdefault(host, {"host": host, "payments": 0, "usdc": 0.0, "payments_x402": 0,
                                           "usdc_x402": 0.0, "category": category})
        s["payments"] += e["n"]
        s["usdc"] += e["usdc"]
        s["payments_x402"] += nx
        s["usdc_x402"] += ux
        b["categories"][category] += e["n"]
        r = sold.setdefault(host, {"host": host, "wallets": set(), "chain": chain_of.get(t, "Base"), "usdc": 0.0,
                                   "payments": 0, "usdc_x402": 0.0, "payments_x402": 0, "buyers": set(),
                                   "category": category, "sells": sells[:140]})
        r["wallets"].add(t)
        r["usdc"] += e["usdc"]
        r["payments"] += e["n"]
        r["usdc_x402"] += ux
        r["payments_x402"] += nx
        r["buyers"].add(f)
    classified = any("n_x402" in e for e in edges)

    out_buyers = []
    for b in buyers.values():
        ss = sorted(b["sellers"].values(), key=lambda s: (-s["usdc"], -s["payments"]))
        out_buyers.append({
            "wallet": b["wallet"], "short": short(b["wallet"]), "chain": b["chain"],
            "explorer": EXPLORER.get(b["chain"], "") + b["wallet"],
            "usdc": round(b["usdc"], 2), "payments": b["payments"], "sellers_paid": len(ss),
            "usdc_x402": round(b["usdc_x402"], 2), "payments_x402": b["payments_x402"],
            "sellers_paid_x402": len(b["sellers_x402"]),
            "avg_payment_usdc": round(b["usdc"] / b["payments"], 4) if b["payments"] else 0,
            "categories": [c for c, _ in b["categories"].most_common()],
            "sellers": [dict(s, usdc=round(s["usdc"], 2), usdc_x402=round(s["usdc_x402"], 2)) for s in ss[:8]],
        })
    out_buyers.sort(key=lambda b: (-b["usdc"], -b["payments"]))
    # an agent at work is a wallet whose x402-settled payments reached three or more sellers;
    # before the pull learned to tell them apart, any three sellers counted
    agent_sellers = (lambda b: b["sellers_paid_x402"]) if classified else (lambda b: b["sellers_paid"])

    out_sellers = []
    for r in sold.values():
        me = snap.get(r["host"], {})
        calls30 = me.get("calls")
        out_sellers.append({
            "host": r["host"], "chain": r["chain"], "wallets": sorted(r["wallets"]), "category": r["category"],
            "sells": r["sells"],
            "on_chain_usdc": round(r["usdc"], 2), "on_chain_payments": r["payments"],
            "on_chain_usdc_x402": round(r["usdc_x402"], 2), "on_chain_payments_x402": r["payments_x402"],
            "on_chain_buyer_wallets": len(r["buyers"]),
            "on_chain_payments_per_day": round(r["payments"] / per_day, 1) if per_day else None,
            "self_reported_calls_30d": calls30,
            "self_reported_calls_per_day": round(calls30 / 30.0, 1) if calls30 is not None else None,
            "self_reported_payers_30d": me.get("payers"),
        })
    out_sellers.sort(key=lambda s: (-s["on_chain_usdc"], -s["on_chain_payments"]))

    return {
        "hours": hours,
        "classified": classified,
        "totals": {"payments": sum(e["n"] for e in edges), "usdc": round(sum(e["usdc"] for e in edges), 2),
                   "payments_x402": sum(e.get("n_x402", 0) for e in edges),
                   "usdc_x402": round(sum(e.get("usdc_x402", 0.0) for e in edges), 2),
                   "buyer_wallets": len(buyers),
                   "buyer_wallets_x402": sum(1 for b in out_buyers if b["payments_x402"]),
                   "sellers_paid": len(sold), "sellers_known": len(sellers),
                   "agents_3plus": sum(1 for b in out_buyers if agent_sellers(b) >= 3)},
        "buyers": out_buyers,
        "agents": sorted([b for b in out_buyers if agent_sellers(b) >= 3],
                         key=lambda b: (-b["payments_x402"], -b["payments"], -b["usdc"])),
        "sellers": out_sellers,
        "notes": [
            "On-chain figures are real USDC transfers to seller wallets the public x402 registry names, "
            "over the pulled hours only. A seller whose wallet is not in the registry is invisible here.",
            "x402-settled means the transfer's transaction used an EIP-3009 authorization: a facilitator "
            "settled a payment the buyer signed. A plain transfer to the same wallet is money that arrived "
            "some other way — a person paying a merchant, a treasury move — and is counted, but not as x402."
            if classified else
            "This pull did not yet tell x402-settled payments from other transfers to the same wallets.",
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
    print("   %s payments · $%s USDC reached %d sellers' wallets from %d buyer wallets (of %d sellers with a known wallet)"
          % ("{:,}".format(t["payments"]), "{:,.2f}".format(t["usdc"]), t["sellers_paid"], t["buyer_wallets"],
             t["sellers_known"]))
    if d.get("classified"):
        print("   x402-settled: %s payments · $%s · %d buyer wallets. The rest reached the same wallets some other way."
              % ("{:,}".format(t["payments_x402"]), "{:,.2f}".format(t["usdc_x402"]), t["buyer_wallets_x402"]))
    print("   %d wallets paid three or more sellers%s" % (t["agents_3plus"], " over x402" if d.get("classified") else ""))

    print("\n  AGENTS AT WORK  (paid 3+ sellers, by x402 payments)")
    for b in d["agents"][:top]:
        print("    %-13s %6d payments  $%9.2f  %2d sellers  %s"
              % (b["short"], b["payments_x402"] or b["payments"], b["usdc_x402"] or b["usdc"],
                 b["sellers_paid_x402"] or b["sellers_paid"], ", ".join(s["host"][:22] for s in b["sellers"][:3])))
        print("    %-13s %s" % ("", " · ".join(b["categories"][:3])))

    print("\n  BIGGEST SPENDERS  (by USDC that reached a seller's wallet; x402 share beside it)")
    for b in d["buyers"][:top]:
        print("    %-13s $%9.2f  x402 $%8.2f  %5d payments  %2d sellers  → %s"
              % (b["short"], b["usdc"], b["usdc_x402"], b["payments"], b["sellers_paid"],
                 ", ".join(s["host"][:24] for s in b["sellers"][:2])))

    print("\n  SELLERS, PAID ON-CHAIN  (per day: on-chain over the pulled hours vs self-reported over 30 days)")
    print("    %-30s %10s %10s %7s %6s   %9s %9s  %s" % ("seller", "usdc", "x402 usdc", "pays", "buyers", "chain/day", "self/day", "sells"))
    for s in d["sellers"][:top]:
        print("    %-30s %10.2f %10.2f %7d %6d   %9s %9s  %s"
              % (s["host"][:30], s["on_chain_usdc"], s["on_chain_usdc_x402"], s["on_chain_payments"], s["on_chain_buyer_wallets"],
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
