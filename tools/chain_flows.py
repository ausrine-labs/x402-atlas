#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 19e73aa). Edit it there, not here.
"""chain_flows.py — who paid whom: x402 payments read straight off Base.

The registry says how many calls a seller got. The chain says who paid.
Every x402 'exact' payment is a USDC Transfer on Base from the buyer's
wallet to the seller's payTo wallet, so the interactions of the agent
market are public: this reads them from the free public RPC.

    edge    buyer wallet → seller wallet, count of payments and USDC total
    window  the last --hours (2000-block chunks; the public RPC caps payloads)

Not every transfer to a seller's wallet is an x402 payment: bitrefill's
payTo is also its ordinary gift-card checkout, and 71 of its last 80
incoming transfers on 2026-09-23 were plain `transfer` calls from people.
An x402 'exact' payment is settled by a facilitator with EIP-3009
transferWithAuthorization, and USDC logs AuthorizationUsed in the same
transaction. So each edge also carries n_x402 / usdc_x402: the transfers
whose transaction used an authorization — a facilitator settled them.
The rest is money that reached the same wallet some other way.

Emits flows-<date>.json: {"since_block","head","edges":[{from,to,n,usdc,
n_x402,usdc_x402}],"sellers":{wallet:[hosts]}}. Standard library only. MIT.

    python3 chain_flows.py --hours 24 --out data-action/flows-2026-09-10.json
"""

import argparse
import collections
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

RPC = "https://mainnet.base.org"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
AUTHORIZATION_USED = "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"   # EIP-3009, read off a real settlement
CHUNK_BLOCKS = 2000          # ~1.1 h of Base
CHUNK_WALLETS = 60


def rpc(method, params, tries=4):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json", "User-Agent": "ausrine-infoharmoni/1.0"})
            d = json.load(urllib.request.urlopen(req, timeout=90))
            if "error" in d:
                raise RuntimeError(d["error"].get("message", "rpc error"))
            return d["result"]
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def topic_addr(w):
    return "0x" + "0" * 24 + w[2:].lower()


def wallets_from_items(items):
    """{base wallet: {hosts}} from the raw registry: only endpoints that name Base."""
    hosts_of = collections.defaultdict(set)
    for it in items:
        host = urllib.parse.urlparse(it.get("resource", "")).netloc.replace("www.", "")
        for acc in it.get("accepts", []):
            if acc.get("network") == "eip155:8453" and acc.get("payTo"):
                hosts_of[acc["payTo"].lower()].add(host)
    return hosts_of


def wallets_from_snapshot(snap):
    """{base wallet: {hosts}} from a radar snapshot (market-<date>.json), which keeps
    every payTo per seller but not the chain of each. An EVM address is taken as
    Base: the USDC contract filter makes a wallet that never took Base payments
    cost one empty answer, nothing more."""
    hosts_of = collections.defaultdict(set)
    for host, s in snap["sellers"].items():
        for w in s.get("wallets", []):
            if isinstance(w, str) and len(w) == 42 and w.startswith("0x"):
                hosts_of[w.lower()].add(host)
    return hosts_of


def authorized_txs(since, head, get_logs=None):
    """The transactions in [since, head] in which USDC used an EIP-3009 authorization:
    a facilitator settled a signed payment. Chunks halve when the RPC refuses a payload."""
    get_logs = get_logs or (lambda b, e, topics: rpc("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e),
                                                                       "address": USDC, "topics": topics}]))
    txs, b, step = set(), since, CHUNK_BLOCKS
    while b < head:
        e = min(b + step, head)
        try:
            logs = get_logs(b, e, [AUTHORIZATION_USED])
        except Exception:
            if step <= 125:
                raise
            step //= 2
            continue
        txs.update(l["transactionHash"] for l in logs)
        b = e + 1
    return txs


def tally(logs, authorized, seen, edges, usdc, n_x402, usdc_x402):
    """Fold Transfer logs into the edge counters, once per (tx, log), splitting out the
    transfers whose transaction used an authorization."""
    for l in logs:
        key = (l["transactionHash"], l["logIndex"])
        if key in seen:
            continue
        seen.add(key)
        frm = "0x" + l["topics"][1][26:]
        to = "0x" + l["topics"][2][26:]
        amount = int(l["data"], 16) / 1e6
        edges[(frm, to)] += 1
        usdc[(frm, to)] += amount
        if l["transactionHash"] in authorized:
            n_x402[(frm, to)] += 1
            usdc_x402[(frm, to)] += amount


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sellers", default="data-action/x402-sellers.json", help="the raw registry (items)")
    ap.add_argument("--snapshot", help="a radar snapshot instead: market-<date>.json, wallets read from it")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--out", default="data-action/flows-" + date.today().isoformat() + ".json")
    a = ap.parse_args()

    if a.snapshot:
        hosts_of = wallets_from_snapshot(json.load(open(a.snapshot)))
    else:
        hosts_of = wallets_from_items(json.load(open(a.sellers)))
    wallets = sorted(hosts_of)
    head = int(rpc("eth_blockNumber", []), 16)
    span = int(a.hours * 3600 / 2)
    since = head - span
    print("Base head %d · %d seller wallets · %d blocks (%.0f h)" % (head, len(wallets), span, a.hours), file=sys.stderr)

    authorized = authorized_txs(since, head)
    print("  %d transactions settled a signed authorization in the window" % len(authorized), file=sys.stderr)

    edges, usdc, n_x402, usdc_x402 = (collections.Counter() for _ in range(4))
    seen_tx = set()
    n_calls = 0
    for wi in range(0, len(wallets), CHUNK_WALLETS):
        group = wallets[wi:wi + CHUNK_WALLETS]
        topics = [TRANSFER, None, [topic_addr(w) for w in group]]
        b = since
        while b < head:
            e = min(b + CHUNK_BLOCKS, head)
            logs = rpc("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e), "address": USDC, "topics": topics}])
            n_calls += 1
            tally(logs, authorized, seen_tx, edges, usdc, n_x402, usdc_x402)
            b = e + 1
        print("  wallets %d-%d done · %d payments so far · %d rpc calls" % (wi, wi + len(group), sum(edges.values()), n_calls), file=sys.stderr)

    out = {"date": date.today().isoformat(), "hours": a.hours, "since_block": since, "head": head,
           "x402_means": "the transfer's transaction used an EIP-3009 authorization: a facilitator settled a signed payment",
           "edges": [{"from": f, "to": t, "n": n, "usdc": round(usdc[(f, t)], 4),
                      "n_x402": n_x402[(f, t)], "usdc_x402": round(usdc_x402[(f, t)], 4)}
                     for (f, t), n in sorted(edges.items(), key=lambda kv: -kv[1])],
           "sellers": {w: sorted(h) for w, h in hosts_of.items()}}
    json.dump(out, open(a.out, "w"), indent=1)
    payers = {f for f, _ in edges}
    print("payments %d · usdc %.2f · buyer wallets %d · seller wallets paid %d · x402-settled: %d payments, usdc %.2f" % (
        sum(edges.values()), sum(usdc.values()), len(payers), len({t for _, t in edges}),
        sum(n_x402.values()), sum(usdc_x402.values())))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
