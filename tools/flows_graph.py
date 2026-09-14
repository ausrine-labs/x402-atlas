#!/usr/bin/env python3
"""flows_graph.py — agent paying agent: the x402 flows as a graph for network.py.

    gold    a seller (host) — an agent, or a service built for agents, with a wallet
    pink    a buyer wallet — the agent that paid
    line    payments buyer → seller in the window; thicker with more payments
    room    what the seller sells (market.py's categories); a buyer sits among
            the categories it bought from
    size    seller: payments received · buyer: payments made

    python3 flows_graph.py --flows data-action/flows-2026-09-10.json --out data-action/flows-graph-2026-09-10.json
"""

import argparse
import collections
import json
from datetime import date

import market
import network

KNOWN_BUYERS = {}   # wallet -> name, filled in as we learn who is who


def build(flows_path, sellers_path, today, extra_flows=()):
    fl = json.load(open(flows_path))
    chain_of = {}                       # wallet -> which chain paid it
    for w in fl["sellers"]:
        chain_of[w] = "Base"
    for p in extra_flows:               # merge another chain's pull, same shape
        g = json.load(open(p))
        name = {"solana": "Solana"}.get(g.get("chain", ""), g.get("chain", "?"))
        for w, hs in g["sellers"].items():
            fl["sellers"].setdefault(w, hs)
            chain_of.setdefault(w, name)
        fl["edges"] = fl["edges"] + g["edges"]
    sellers, _ = market.load(sellers_path)
    cats = {name: col for name, col, _ in market.CATS}
    cats["other"] = "#7f8fa6"
    key = {n: n.replace(" & ", "-").replace(" ", "-") for n in cats}
    host_info = {s["host"].replace("www.", ""): s for s in sellers}
    wallet_hosts = {w: hs for w, hs in fl["sellers"].items()}

    # a seller node per wallet, named by its busiest host
    def seller_name(w):
        hs = wallet_hosts.get(w, [])
        hs = sorted(hs, key=lambda h: -host_info.get(h, {}).get("calls", 0))
        return hs[0] if hs else w[:10] + "…"

    edges = collections.Counter()
    usdc = collections.Counter()
    for e in fl["edges"]:
        s = seller_name(e["to"])
        edges[(e["from"], s)] += e["n"]
        usdc[(e["from"], s)] += e["usdc"]
    recv = collections.Counter(); paid = collections.Counter(); recv_usd = collections.Counter(); paid_usd = collections.Counter()
    for (b, s), n in edges.items():
        recv[s] += n; paid[b] += n; recv_usd[s] += usdc[(b, s)]; paid_usd[b] += usdc[(b, s)]

    what_of = {}
    for s in sorted(recv):
        info = host_info.get(s, {})
        what_of[s] = ((info.get("best") or {}).get("desc") or "").strip()
    nodes = []
    for s in sorted(recv):
        info = host_info.get(s, {})
        cat = info.get("cat", "other")
        wallet = next((w for w, hs in wallet_hosts.items() if s in hs), "")
        others = [h for h in wallet_hosts.get(wallet, []) if h != s]
        nodes.append({"u": s, "n": "", "f": recv[s], "k": "buyer",
                      "b": "%s · earned %.2f USDC from %d payments by %d buyer wallets in %g h%s" % (
                          cat, recv_usd[s], recv[s], sum(1 for (b, t) in edges if t == s), fl["hours"],
                          (" · same operator also runs " + ", ".join(others[:3])) if others else ""),
                      "s": what_of[s][:200], "r": [key[cat]], "d": recv[s], "known": True, "usd": round(recv_usd[s], 2),
                      "url": (("https://solscan.io/account/" if chain_of.get(wallet) == "Solana" else "https://basescan.org/address/") + wallet) if wallet else "https://" + s,
                      "chain": chain_of.get(wallet, "Base"), "wallet": [wallet] if wallet else []})
    for b in sorted(paid):
        bought = collections.Counter()
        for (bb, s), n in edges.items():
            if bb == b:
                bought[key[host_info.get(s, {}).get("cat", "other")]] += n
        nsell = sum(1 for (bb, s) in edges if bb == b)
        from_ = sorted(((n, s) for (bb, s), n in edges.items() if bb == b), reverse=True)
        basket = ", ".join("%s (%d)" % (s, n) for n, s in from_[:3])
        nodes.append({"u": KNOWN_BUYERS.get(b, b[:6] + "…" + b[-4:]), "n": "", "f": paid[b], "k": "agent",
                      "b": "spent %.2f USDC over %d payments in %g h, to %d seller%s" % (paid_usd[b], paid[b], fl["hours"], nsell, "s" if nsell != 1 else ""),
                      "s": ("buys: " + basket) if basket else "", "r": [r for r, _ in bought.most_common()], "d": paid[b],
                      "known": True, "usd": round(paid_usd[b], 2), "bought": [s for _n, s in from_[:6]],
                      "url": ("https://solscan.io/account/" if len(b) < 60 and not b.startswith("0x") else "https://basescan.org/address/") + b,
                      "chain": ("Solana" if not b.startswith("0x") else "Base"), "wallet": [b]})
    name_of = {b: KNOWN_BUYERS.get(b, b[:6] + "…" + b[-4:]) for b in paid}
    links = [{"a": name_of[b], "b": s, "w": n, "r": key[host_info.get(s, {}).get("cat", "other")], "t": "%d payments · %.2f USDC" % (n, usdc[(b, s)])}
             for (b, s), n in sorted(edges.items(), key=lambda kv: -kv[1])]
    comms = network.find_communities(nodes, links, [], {})
    by_u = {n["u"]: n for n in nodes}
    for c in comms:
        sells = sorted([u for u in c["members"] if by_u[u]["k"] == "buyer"], key=lambda u: -by_u[u]["f"])
        buys = [u for u in c["members"] if by_u[u]["k"] == "agent"]
        pays = sum(by_u[u]["f"] for u in sells)
        cat = (host_info.get(sells[0], {}) or {}).get("cat", "") if sells else ""
        # what_of is built above from each seller's best-selling endpoint
        earned = sum(by_u[u].get("usd", 0) for u in sells)
        if len(sells) == 1:
            # one shop and the agents that pay it
            desc = what_of.get(sells[0], "")
            short = desc.split(".")[0].split(" - ")[0].split(" — ")[0][:60] or cat
            c["label"] = "%s — %s" % (sells[0], short)
            c["note"] = "%d buyers · %s payments · $%s earned in 24 h" % (len(buys), "{:,}".format(pays), "{:,.2f}".format(earned))
        elif sells:
            # buyers here paid several different sellers: a shared market, not one shop
            top = ", ".join(sells[:3])
            c["label"] = "shared market — %d sellers, %d buyers" % (len(sells), len(buys))
            c["note"] = "buyers here pay more than one seller · %s payments · $%s · biggest: %s" % (
                "{:,}".format(pays), "{:,.2f}".format(earned), top)
        else:
            c["label"] = "%d wallets" % len(c["members"])
            c["note"] = ""
        c["terms"] = [c["label"]]
        c["ai"] = len(buys)
    sellers_n = [n for n in nodes if n["k"] == "buyer"]
    buyers_n = [n for n in nodes if n["k"] == "agent"]
    def row(n, metric, sub):
        return {"name": n["u"], "url": n["url"], "metric": metric, "sub": sub}
    cust = collections.Counter()
    for (b, s) in edges:
        cust[s] += 1
    def srow(n):
        return row(n, "$%s" % "{:,.2f}".format(n["usd"]),
                   "SELLS: %s · %d customers, %s payments" % ((n["s"] or "—")[:80], cust[n["u"]], "{:,}".format(n["f"])))
    def brow(n):
        bought = ", ".join(n.get("bought", [])[:3]) or "—"
        return row(n, "$%s" % "{:,.2f}".format(n["usd"]),
                   "BUYS FROM: %s · %s payments" % (bought[:80], "{:,}".format(n["f"])))
    panels = [
        {"title": "sellers making the most money", "rows": [srow(n) for n in sorted(sellers_n, key=lambda n: -n["usd"])[:20]]},
        {"title": "sellers with the most customers", "rows": [srow(n) for n in sorted(sellers_n, key=lambda n: -cust[n["u"]])[:20]]},
        {"title": "buyers spending the most", "rows": [brow(n) for n in sorted(buyers_n, key=lambda n: -n["usd"])[:20]]},
        {"title": "buyers paying most often", "rows": [brow(n) for n in sorted(buyers_n, key=lambda n: -n["f"])[:20]]},
    ]
    return {"date": today, "source": "%s · USDC payments to x402 sellers · last %g h" % (" + ".join(sorted(set(chain_of.values()))), fl["hours"]),
            "key": "Every dot is a wallet on the Base blockchain. AMBER = a seller: a service agents pay per call in USDC over x402. BLUE = a buyer: the wallet that paid it. Every line is real money that moved in the last %g hours." % fl["hours"],
            "panels": panels, "labels": {"kinds": ["buyer"], "top": 22},
            "rooms": {key[n]: {"name": n, "color": c} for n, c in cats.items()}, "mode": "kind",
            "nodes": nodes, "links": links, "communities": comms,
            "totals": {"payments": sum(edges.values()), "usdc": round(sum(usdc.values()), 2), "buyers": len(paid), "sellers": len(recv)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flows", default="data-action/flows-" + date.today().isoformat() + ".json")
    ap.add_argument("--sellers", default="data-action/x402-sellers.json")
    ap.add_argument("--out", default="data-action/flows-graph-" + date.today().isoformat() + ".json")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--also", nargs="*", default=[], help="other chains' flow files to merge")
    a = ap.parse_args()
    g = build(a.flows, a.sellers, a.date, a.also)
    json.dump(g, open(a.out, "w"), indent=1)
    t = g["totals"]
    print("payments %d · %.2f USDC · %d buyer wallets → %d sellers · %d communities" % (t["payments"], t["usdc"], t["buyers"], t["sellers"], len(g["communities"])))
    for n in sorted((n for n in g["nodes"] if n["k"] == "agent"), key=lambda n: -n["f"])[:8]:
        print("  buyer %-16s %5d payments  %s" % (n["u"], n["f"], n["b"][:60]))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
