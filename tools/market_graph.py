#!/usr/bin/env python3
"""market_graph.py — the x402 market as a graph for network.py's 3D page.

    node    one seller (host) with a wallet — gold
    size    paid calls in the last 30 days
    room    what it sells (market.py's categories)
    line    two sellers paid to the same wallet — one operator, several fronts
            (wallets shared by more than 12 hosts are platforms, not lines)

    python3 market_graph.py --in data-action/x402-sellers.json --out data-action/market-graph.json
"""

import argparse
import collections
import json
from datetime import date

import market

NET = {"eip155:8453": "Base", "eip155:137": "Polygon", "eip155:42161": "Arbitrum", "xrpl:0": "XRPL"}


def net_name(n):
    return NET.get(n, "Solana" if str(n).startswith("solana") else str(n))


def build(path, today):
    sellers, items = market.load(path)
    cats = {name: col for name, col, _ in market.CATS}
    cats["other"] = "#7f8fa6"
    key = {n: n.replace(" & ", "-").replace(" ", "-") for n in cats}

    by_wallet = collections.defaultdict(set)
    for s in sellers:
        for w in s["wallets"]:
            if w:
                by_wallet[w].add(s["host"].replace("www.", ""))
    links, seen = [], set()
    for w, hosts in by_wallet.items():
        hosts = sorted(hosts)
        if len(hosts) > 12:
            continue
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                if (hosts[i], hosts[j]) not in seen:
                    seen.add((hosts[i], hosts[j]))
                    links.append({"a": hosts[i], "b": hosts[j], "w": 1, "r": None, "t": "same wallet " + w[:10]})
    deg = collections.Counter()
    for l in links:
        deg[l["a"]] += 1
        deg[l["b"]] += 1

    nodes = []
    for s in sellers:
        u = s["host"].replace("www.", "")
        nets = [net_name(n) for n in sorted(x for x in s["nets"] if x)]
        b = "%s · %d endpoint%s · %s paid calls · %s payers · take ~$%.0f · $%g–$%g per call · %s" % (
            s["cat"], s["n"], "s" if s["n"] > 1 else "", "{:,}".format(s["calls"]), "{:,}".format(s["payers"]),
            s["take"], s["pmin"], s["pmax"], ", ".join(nets))
        nodes.append({"u": u, "n": "", "f": s["calls"], "k": "buyer", "b": b[:240],
                      "s": (s["best"]["desc"] if s["best"] else "")[:200], "r": [key[s["cat"]]], "d": deg[u], "known": True,
                      "url": (s["best"]["url"].split("/")[0] + "//" + s["host"]) if s["best"] else "https://" + s["host"],
                      "wallet": sorted(w for w in s["wallets"] if w)[:1]})
    calls_of = {n["u"]: n["f"] for n in nodes}
    comms = []
    for name in cats:
        members = sorted([n["u"] for n in nodes if n["r"] == [key[name]]], key=lambda u: -calls_of[u])
        if not members:
            continue
        for n in nodes:
            if n["u"] in members:
                n["c"] = len(comms)
        comms.append({"id": len(comms), "hub": members[0], "size": len(members), "ai": len(members),
                      "room": key[name], "terms": [name], "members": members})
    return {"date": today, "source": "x402 registry · paid calls of the last 30 days",
            "key": "sphere = one seller with a wallet · size = paid calls in 30 days · line = two sellers paid to the same wallet · hover for what it sells and charges",
            "rooms": {key[n]: {"name": n, "color": c} for n, c in cats.items()}, "mode": "room",
            "nodes": nodes, "links": links, "communities": comms}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data-action/x402-sellers.json")
    ap.add_argument("--out", default="data-action/market-graph-" + date.today().isoformat() + ".json")
    ap.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()
    g = build(a.inp, a.date)
    json.dump(g, open(a.out, "w"), indent=1)
    print("graph: %d sellers, %d same-operator links, %d categories" % (len(g["nodes"]), len(g["links"]), len(g["communities"])))
    for c in g["communities"]:
        calls = sum(n["f"] for n in g["nodes"] if n["c"] == c["id"])
        print("  %-24s %4d sellers %9s calls  top: %s" % (c["terms"][0], c["size"], "{:,}".format(calls), c["hub"]))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
