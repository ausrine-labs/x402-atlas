#!/usr/bin/env python3
"""solana_flows.py — who paid whom on Solana, the x402 market's second chain.

Base is 56% of the market's paid calls; Solana is 26%. Base's payments read
cleanly off one USDC contract's Transfer logs; Solana has no such index, so
this walks each seller's USDC token account backwards through its signatures
and reads the payer out of each transfer.

Emits the same shape chain_flows.py does — {"edges":[{from,to,n,usdc}],
"sellers":{wallet:[hosts]}} — so flows_graph.py can merge the two chains.

    python3 solana_flows.py --hours 24 --out data-action/flows-sol-2026-09-11.json

Public RPC, no key. Slow and polite by design: one seller at a time.
"""

import argparse
import collections
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

RPC = "https://api.mainnet-beta.solana.com"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def rpc(method, params, tries=4):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body, headers={
                "Content-Type": "application/json", "User-Agent": "ausrine-infoharmoni/1.0"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            if "error" in d:
                raise RuntimeError(str(d["error"])[:120])
            return d["result"]
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def usdc_account(owner):
    r = rpc("getTokenAccountsByOwner", [owner, {"mint": USDC}, {"encoding": "jsonParsed"}])
    vals = (r or {}).get("value", [])
    return vals[0]["pubkey"] if vals else None


def payments_into(account, owner, since_ts, cap=400):
    """USDC amounts credited to this account, by payer, since a unix time."""
    got = collections.Counter()
    usd = collections.Counter()
    before = None
    while True:
        sigs = rpc("getSignaturesForAddress", [account, {"limit": 100, **({"before": before} if before else {})}])
        if not sigs:
            return got, usd
        for s in sigs:
            if s.get("err"):
                continue
            if (s.get("blockTime") or 0) < since_ts:
                return got, usd
            tx = rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                         "maxSupportedTransactionVersion": 0}])
            if not tx:
                continue
            meta = tx.get("meta") or {}
            pre = {b["accountIndex"]: b for b in meta.get("preTokenBalances", []) if b.get("mint") == USDC}
            post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", []) if b.get("mint") == USDC}
            payer, amount = None, 0.0
            for idx, b in post.items():
                before_amt = float((pre.get(idx) or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                after_amt = float(b.get("uiTokenAmount", {}).get("uiAmount") or 0)
                delta = after_amt - before_amt
                if b.get("owner") == owner and delta > 0:
                    amount = delta
                elif delta < 0:
                    payer = b.get("owner")
            if payer and amount > 0:
                got[payer] += 1
                usd[payer] += amount
            cap -= 1
            if cap <= 0:
                return got, usd
        before = sigs[-1]["signature"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sellers", default="data-action/x402-sellers.json")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--top", type=int, default=40, help="busiest Solana sellers to walk")
    ap.add_argument("--out", default="data-action/flows-sol-" + date.today().isoformat() + ".json")
    a = ap.parse_args()

    items = json.load(open(a.sellers))
    hosts_of = collections.defaultdict(set)
    calls_of = collections.Counter()
    for it in items:
        host = urllib.parse.urlparse(it.get("resource", "")).netloc.replace("www.", "")
        c = (it.get("quality") or {}).get("l30DaysTotalCalls", 0) or 0
        for acc in it.get("accepts", []):
            if str(acc.get("network", "")).startswith("solana") and acc.get("payTo"):
                hosts_of[acc["payTo"]].add(host)
                calls_of[acc["payTo"]] += c
    wallets = [w for w, _ in calls_of.most_common(a.top)]
    since_ts = int(datetime.now(timezone.utc).timestamp() - a.hours * 3600)
    print("Solana: %d seller wallets known, walking the busiest %d over %g h"
          % (len(hosts_of), len(wallets), a.hours), file=sys.stderr)

    edges, usdc = collections.Counter(), collections.Counter()
    for i, w in enumerate(wallets, 1):
        try:
            acct = usdc_account(w)
            if not acct:
                continue
            got, usd = payments_into(acct, w, since_ts)
            for payer, n in got.items():
                edges[(payer, w)] += n
                usdc[(payer, w)] += usd[payer]
        except Exception as e:
            print("  %s… skipped: %s" % (w[:8], str(e)[:60]), file=sys.stderr)
            continue
        print("  %2d/%d %s… %d payments so far" % (i, len(wallets), w[:8], sum(edges.values())), file=sys.stderr)

    out = {"date": date.today().isoformat(), "hours": a.hours, "chain": "solana",
           "edges": [{"from": f, "to": t, "n": n, "usdc": round(usdc[(f, t)], 4)}
                     for (f, t), n in sorted(edges.items(), key=lambda kv: -kv[1])],
           "sellers": {w: sorted(h) for w, h in hosts_of.items()}}
    json.dump(out, open(a.out, "w"), indent=1)
    print("payments %d · usdc %.2f · buyer wallets %d · sellers paid %d" % (
        sum(edges.values()), sum(usdc.values()), len({f for f, _ in edges}), len({t for _, t in edges})))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
