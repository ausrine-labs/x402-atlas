#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f04f064). Edit it there, not here.
"""leaders.py — /leaders/: facilitators, new sellers, new buyer wallets, and the chain split.

    facilitators   who settled the day's x402 payments. An x402 'exact' payment is settled
                   by a facilitator calling USDC's transferWithAuthorization; USDC logs
                   AuthorizationUsed in that transaction. The facilitator is the
                   transaction's sender. Only settlements paid to a seller wallet the Atlas
                   knows are counted, the same rule chain_flows.py uses for "x402-settled".
                   An address is named only from FACILITATORS below, and only where the
                   facilitator publishes it in its own documentation; otherwise the page
                   shows the address.
    new sellers    hosts first seen in the registry snapshots in the last 7 days, ranked
                   by x402 USDC in the rollup. A host in the oldest stored snapshot is never
                   new: the store cannot say when it arrived.
    new buyers     wallets that made x402 payments and were first seen in the stored flow
                   days within the last 7 days, never on the oldest stored day, ranked by
                   how many sellers they paid.
    chains         the rollup split by chain, when it covers more than one.

The chain pull for facilitators (one day, Base):

    leaders.py pull --day 2026-09-24 --snapshot market-2026-09-24.json --out settlements-2026-09-24.json

and the page:

    leaders.py --whales whales-2026-09-24.json --store radar-store --flows flows-*.json \
               [--settlements settlements-2026-09-24.json] --out _site

leaders_body(data) is the fragment; write(out, data) wraps it. Standard library only.
"""

import argparse
import collections
import glob
import json
import os
import sys
import urllib.request
from datetime import date, timedelta

import buyer_pages
import chain_flows
import coverage_page as cp
import tiers

WINDOW_DAYS = 7
TOP = 25
BATCH = 50

# Facilitator settlement addresses, named ONLY where the facilitator publishes the address in
# its own documentation. Each entry: address (lowercase) -> {"name", "source": the https page
# that lists it}. An entry without a source is not allowed (tested). Empty until someone
# reads the docs and adds one; until then the page shows addresses, which are the facts.
FACILITATORS = {}


def name_of(address, known=None):
    known = FACILITATORS if known is None else known
    k = known.get((address or "").lower())
    return k["name"] if k and k.get("source", "").startswith("https://") else None


# ── the chain pull ───────────────────────────────────────────────────────────

def rpc_batch(calls, url=chain_flows.RPC):
    """One JSON-RPC batch; answers in the order asked."""
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "ausrine-infoharmoni/1.0"})
    ans = json.load(urllib.request.urlopen(req, timeout=90))
    by = {a.get("id"): a for a in ans}
    out = []
    for i in range(len(calls)):
        a = by.get(i) or {}
        if "error" in a or "result" not in a:
            raise RuntimeError((a.get("error") or {}).get("message", "no answer for call %d" % i))
        out.append(a["result"])
    return out


def authorized_txs(since, until, get_logs):
    """The transactions in [since, until], both ends included, in which USDC logged
    AuthorizationUsed. chain_flows.authorized_txs does the same but stops before `until`
    when a chunk ends exactly one block short of it; this one never skips the last block."""
    txs, b, step = set(), since, chain_flows.CHUNK_BLOCKS
    while b <= until:
        e = min(b + step, until)
        try:
            logs = get_logs(b, e, [chain_flows.AUTHORIZATION_USED])
        except Exception:
            if step <= 125:
                raise
            step //= 2
            continue
        txs.update(l["transactionHash"] for l in logs)
        b = e + 1
    return txs


def pull_settlements(since, until, wallets, call=chain_flows.rpc, batch=rpc_batch):
    """Every x402 settlement in [since, until] paid to one of `wallets`: the Transfer to the
    seller, in a transaction that also logged AuthorizationUsed, and that transaction's sender."""
    get_logs = lambda b, e, topics: call("eth_getLogs", [{"fromBlock": hex(b), "toBlock": hex(e),
                                                           "address": chain_flows.USDC, "topics": topics}])
    authorized = authorized_txs(since, until, get_logs)
    wallets = sorted({w.lower() for w in wallets})
    found, seen = [], set()
    for wi in range(0, len(wallets), chain_flows.CHUNK_WALLETS):
        topics = [chain_flows.TRANSFER, None, [chain_flows.topic_addr(w) for w in wallets[wi:wi + chain_flows.CHUNK_WALLETS]]]
        b = since
        while b <= until:
            e = min(b + chain_flows.CHUNK_BLOCKS, until)
            for l in get_logs(b, e, topics):
                key = (l["transactionHash"], l["logIndex"])
                if key in seen or l["transactionHash"] not in authorized:
                    continue
                seen.add(key)
                found.append({"tx": l["transactionHash"], "payer": "0x" + l["topics"][1][26:].lower(),
                              "to": "0x" + l["topics"][2][26:].lower(), "usdc": int(l["data"], 16) / 1e6,
                              "block": int(l["blockNumber"], 16)})
            b = e + 1
    txs = sorted({s["tx"] for s in found})
    sender = {}
    for i in range(0, len(txs), BATCH):
        part = txs[i:i + BATCH]
        for tx, t in zip(part, batch([("eth_getTransactionByHash", [h]) for h in part])):
            sender[tx] = (t or {}).get("from", "").lower() or None
    for s in found:
        s["facilitator"] = sender.get(s["tx"])
    found.sort(key=lambda s: (s["block"], s["tx"]))
    return found


# ── the boards ───────────────────────────────────────────────────────────────

def facilitator_board(settlements, known=None, sellers=None):
    """Facilitators by settlements, then USDC: how many sellers and payer wallets each served."""
    rows = {}
    for s in settlements:
        f = s.get("facilitator")
        if not f:
            continue
        r = rows.setdefault(f, {"address": f, "name": name_of(f, known), "settlements": 0, "usdc": 0.0,
                                "sellers": set(), "payers": set()})
        r["settlements"] += 1
        r["usdc"] += s["usdc"]
        r["sellers"].add((sellers or {}).get(s["to"], s["to"]))
        r["payers"].add(s["payer"])
    out = [dict(r, usdc=round(r["usdc"], 6), sellers=len(r["sellers"]), payers=len(r["payers"])) for r in rows.values()]
    out.sort(key=lambda r: (-r["settlements"], -r["usdc"], r["address"]))
    return out


def first_seen(snapshots):
    """{host: the date of the earliest snapshot that lists it}. snapshots: [(date, hosts)]
    in any order. A host that leaves and returns keeps its first date."""
    seen = {}
    for day, hosts in sorted(snapshots, key=lambda x: x[0]):
        for h in hosts:
            seen.setdefault(h, day)
    return seen


def since_day(as_of, days=WINDOW_DAYS):
    """The first day of a `days`-long window ending on as_of."""
    return (date.fromisoformat(as_of) - timedelta(days=days - 1)).isoformat()


def new_sellers(snapshots, rollup, as_of=None, days=WINDOW_DAYS, top=TOP):
    """Hosts first seen within the last `days` days and after the oldest stored snapshot,
    ranked by x402 USDC (then payments, then name). Returns (rows, baseline date)."""
    if not snapshots:
        return [], None
    oldest = min(d for d, _ in snapshots)
    as_of = as_of or max(d for d, _ in snapshots)
    start = since_day(as_of, days)
    classified = cp.classified_chains(rollup)
    paid = {s["host"]: cp.paid(s, classified) for s in (rollup or {}).get("sellers") or []}
    rows = []
    for h, d in first_seen(snapshots).items():
        if d > oldest and start <= d <= as_of:
            usdc, n = paid.get(h, (0.0, 0))
            rows.append({"host": h, "first_seen": d, "usdc": round(usdc, 2), "payments": n})
    rows.sort(key=lambda r: (-r["usdc"], -r["payments"], r["first_seen"], r["host"]))
    return rows[:top], oldest


def new_buyers(flow_days, as_of=None, days=WINDOW_DAYS, top=TOP, hosts=None):
    """Wallets with x402 payments first seen in the stored flow days within the last `days`
    days, never on the oldest stored day, ranked by sellers paid (x402), then USDC.
    flow_days: [(date, edges)] with chain_flows edges. hosts: {seller wallet: host}, so a
    seller paid into several wallets counts once. Returns (rows, baseline date)."""
    hosts = {k.lower(): v for k, v in (hosts or {}).items()}
    if not flow_days:
        return [], None
    oldest = min(d for d, _ in flow_days)
    as_of = as_of or max(d for d, _ in flow_days)
    start = since_day(as_of, days)
    first, sellers, usdc, pays = {}, collections.defaultdict(set), collections.Counter(), collections.Counter()
    for d, edges in sorted(flow_days, key=lambda x: x[0]):
        for e in edges:
            if not (e.get("n_x402") or 0):
                continue
            w = e["from"].lower()
            first.setdefault(w, d)
            if start <= d <= as_of:
                sellers[w].add(hosts.get(e["to"].lower(), e["to"].lower()))
                usdc[w] += e.get("usdc_x402") or 0.0
                pays[w] += e["n_x402"]
    rows = [{"wallet": w, "first_seen": d, "sellers": len(sellers[w]), "usdc": round(usdc[w], 2), "payments": pays[w]}
            for w, d in first.items() if d > oldest and start <= d <= as_of]
    rows.sort(key=lambda r: (-r["sellers"], -r["usdc"], -r["payments"], r["wallet"]))
    return rows[:top], oldest


def chain_split(rollup):
    """Per chain: sellers paid, buyer wallets, payments and USDC. Each chain counts x402-settled
    payments when its own pull told them apart, and every transfer when it did not."""
    classified = cp.classified_chains(rollup)
    by = collections.defaultdict(lambda: {"sellers": 0, "buyers": 0, "payments": 0, "usdc": 0.0})
    for s in (rollup or {}).get("sellers") or []:
        for chain, (usdc, n) in cp.paid_by_chain(s, classified).items():
            r = by[chain]
            r["sellers"] += 1 if n else 0
            r["payments"] += n
            r["usdc"] += usdc
    for b in (rollup or {}).get("buyers") or []:
        if (b.get("payments_x402") if cp.split(b, classified) else b.get("payments")):
            by[b.get("chain", "Base")]["buyers"] += 1
    return [dict(v, chain=k, usdc=round(v["usdc"], 2), x402=k in classified)
            for k, v in sorted(by.items(), key=lambda kv: -kv[1]["usdc"])]


def leaders_data(rollup, snapshots, flow_days, settlements=None, settlements_day=None, as_of=None, known=None, site="",
                 wallet_hosts=None, free=None):
    """Everything /leaders/ shows. settlements: pull_settlements' list for one day, or None.
    site: where the Atlas is served; links keep only its path (see coverage_page.site_path).
    free: the tier (tiers.py). The free tier counts every row so the body can say how many
    are past the TOP it shows, and links a wallet to its page only where one has a record."""
    rollup = rollup or {}
    free = tiers.free(free)
    cap = None if free else TOP
    as_of = as_of or rollup.get("as_of") or (max(d for d, _ in snapshots) if snapshots else "")
    wallet_host = {}
    for s in rollup.get("sellers") or []:
        for w in s.get("wallets") or []:
            wallet_host.setdefault(w.lower(), s["host"])
    ns, ns_base = new_sellers(snapshots, rollup, top=cap)
    hosts = dict(wallet_hosts or {})
    hosts.update(wallet_host)                  # the rollup's naming wins: the busiest host of a shared wallet
    nb, nb_base = new_buyers(flow_days, hosts=hosts, top=cap)
    split = chain_split(rollup)
    pages = buyer_pages.kept(rollup, tiers.TOP) if free else {b["wallet"].lower() for b in rollup.get("buyers") or [] if b.get("payments_x402")}
    return {"as_of": as_of, "days": ", ".join(rollup.get("dates") or []), "site": cp.site_path(site), "free": free,
            "classified": sorted(cp.classified_chains(rollup)), "chains_covered": cp.chains_of(rollup),
            "facilitators": facilitator_board(settlements, known, wallet_host) if settlements is not None else None,
            "settlements_day": settlements_day,
            "settlements": len(settlements) if settlements is not None else None,
            "settlements_usdc": round(sum(s["usdc"] for s in settlements), 2) if settlements else 0.0,
            "new_sellers": ns, "sellers_baseline": ns_base,
            "sellers_window": [since_day(max(d for d, _ in snapshots)), max(d for d, _ in snapshots)] if snapshots else None,
            "new_buyers": nb, "buyers_baseline": nb_base,
            "buyers_window": [since_day(max(d for d, _ in flow_days)), max(d for d, _ in flow_days)] if flow_days else None,
            "buyer_pages": sorted(pages), "chains": split}


def leaders_body(data):
    pages = set(data.get("buyer_pages") or [])
    site = data.get("site", "")
    free = bool(data.get("free"))
    top = tiers.TOP if free else TOP
    x402 = cp.basis(set(data["classified"]), data["chains_covered"])
    p = ['<section class="leaders">', "<h1>Leaderboards</h1>",
         '<p class="muted">Built <span class="dated">%s</span>. Rollup of <span class="dated">%s</span>. '
         "Every figure is read off the chain or the public registry; none is a judgement of anyone.</p>"
         % (cp.esc(data["as_of"]), cp.esc(data["days"] or data["as_of"]))]

    p.append("<h2>Facilitators</h2>")
    if data["facilitators"] is None:
        p.append('<p class="notice">No settlement pull for this build, so no facilitator board. It needs one day of '
                 "Base read with each settlement's transaction sender (leaders.py pull).</p>")
    else:
        p.append('<p class="muted">Who settled the x402 payments to sellers the Atlas knows on <span class="dated">%s</span>: '
                 "%s, %s. The facilitator is the sender of the transaction in which USDC logged AuthorizationUsed. A "
                 "name is shown only where the facilitator publishes that address in its own documentation.</p>"
                 % (cp.esc(data["settlements_day"] or ""), cp.num(data["settlements"], "settlement"),
                    cp.esc(cp.money(data["settlements_usdc"]))))
        p.append('<div class="wrap"><table><thead><tr><th>#</th><th>facilitator</th><th class="num">settlements</th>'
                 '<th class="num">USDC</th><th class="num">sellers</th><th class="num">payer wallets</th></tr></thead><tbody>')
        for i, r in enumerate(data["facilitators"][:top], 1):
            who = (cp.esc(r["name"]) + " " if r["name"] else "") + '<span class="addr" title="%s">%s</span>' % (
                cp.esc(r["address"]), cp.esc(r["address"] if not r["name"] else cp.short(r["address"])))
            p.append('<tr><td class="num">%d</td><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num">%s</td><td class="num">%s</td></tr>' % (
                         i, who, "{:,}".format(r["settlements"]), cp.esc(cp.money(r["usdc"])),
                         "{:,}".format(r["sellers"]), "{:,}".format(r["payers"])))
        p.append("</tbody></table></div>")
        if free:        # no daily file holds the board, so a cut says only what it is
            p.append(cp.shown_line(min(top, len(data["facilitators"])), len(data["facilitators"]), "busiest facilitators"))

    p.append("<h2>New sellers</h2>")
    w = data["sellers_window"]
    if not w:
        p.append('<p class="notice">No registry snapshots in the store.</p>')
    else:
        p.append('<p class="muted">Hosts first seen in the registry between <span class="dated">%s</span> and '
                 '<span class="dated">%s</span>, ranked by %s. The store\'s oldest snapshot is <span class="dated">%s</span>; '
                 "a host already in it is never counted as new.</p>" % (cp.esc(w[0]), cp.esc(w[1]), cp.esc(x402),
                                                                        cp.esc(data["sellers_baseline"])))
        if data["new_sellers"]:
            rows, total = cp.cut(data["new_sellers"], data)
            p.append('<div class="wrap"><table><thead><tr><th>#</th><th>seller</th><th>first seen</th>'
                     '<th class="num">USDC</th><th class="num">payments</th></tr></thead><tbody>')
            for i, r in enumerate(rows, 1):
                p.append('<tr><td class="num">%d</td><td>%s</td><td class="dated">%s</td><td class="num">%s</td>'
                         '<td class="num">%s</td></tr>' % (i, cp.seller_html(r["host"], site), cp.esc(r["first_seen"]),
                                                           cp.esc(cp.money(r["usdc"])), "{:,}".format(r["payments"])))
            p.append("</tbody></table></div>")
            p.append(cp.shown_line(len(rows), total, "busiest"))
            if free:
                p.append(tiers.more_line(len(rows), total, "sellers first seen in the window, each with its day and what it was paid",
                                         site, ("who", "pro")))
        else:
            p.append("<p>None in the window.</p>")

    p.append("<h2>New buyer wallets</h2>")
    w = data["buyers_window"]
    if not w:
        p.append('<p class="notice">No stored days of chain flows.</p>')
    else:
        p.append('<p class="muted">Wallets that made x402 payments and were first seen between <span class="dated">%s</span> '
                 'and <span class="dated">%s</span>, ranked by sellers paid. The oldest stored day is <span class="dated">%s'
                 "</span>; a wallet already paying then is never counted as new. A wallet is an address; the Atlas "
                 "does not say who holds it.</p>" % (cp.esc(w[0]), cp.esc(w[1]), cp.esc(data["buyers_baseline"])))
        if data["new_buyers"]:
            rows, total = cp.cut(data["new_buyers"], data)
            p.append('<div class="wrap"><table><thead><tr><th>#</th><th>wallet</th><th>first seen</th>'
                     '<th class="num">sellers paid</th><th class="num">x402 USDC</th><th class="num">payments</th></tr></thead><tbody>')
            for i, r in enumerate(rows, 1):
                p.append('<tr><td class="num">%d</td><td>%s</td><td class="dated">%s</td><td class="num">%s</td>'
                         '<td class="num">%s</td><td class="num">%s</td></tr>' % (
                             i, cp.wallet_html(r["wallet"], site, has_page=r["wallet"] in pages), cp.esc(r["first_seen"]),
                             "{:,}".format(r["sellers"]), cp.esc(cp.money(r["usdc"])), "{:,}".format(r["payments"])))
            p.append("</tbody></table></div>")
            p.append(cp.shown_line(len(rows), total, "busiest"))
            if free:
                p.append(tiers.more_line(len(rows), total, "wallets first seen in the window, each with its day, the sellers it "
                                         "paid and what it spent", site, tiers.BUYER_WAYS))
        else:
            p.append("<p>None in the window%s.</p>" % (
                " (the store holds one day, so every wallet in it is the baseline)" if w and data["buyers_baseline"] == w[1] else ""))

    if len(data["chains"]) > 1:
        p.append('<h2>By chain</h2><p class="muted">Over the rollup\'s days, <span class="dated">%s</span>. Each chain '
                 "counts what its own pull could tell apart.</p>" % cp.esc(data["days"]))
        p.append('<div class="wrap"><table><thead><tr><th>chain</th><th>counts</th><th class="num">sellers paid</th>'
                 '<th class="num">buyer wallets</th><th class="num">payments</th><th class="num">USDC</th></tr></thead><tbody>')
        for r in data["chains"]:
            p.append('<tr><td>%s</td><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                     '<td class="num">%s</td></tr>'
                     % (cp.esc(r["chain"]), "x402-settled payments" if r["x402"] else "all transfers (not split)",
                        "{:,}".format(r["sellers"]), "{:,}".format(r["buyers"]),
                        "{:,}".format(r["payments"]), cp.esc(cp.money(r["usdc"]))))
        p.append("</tbody></table></div>")
    p.append("</section>")
    return "".join(p)


def write(out, data):
    return cp.write(out, "leaders", cp.page("Leaderboards", leaders_body(data), data["as_of"],
                                            "x402 facilitators, new sellers and new buyer wallets, ranked.",
                                            room="leaders", root=data.get("site", ""), free=data.get("free")))


# ── loading ──────────────────────────────────────────────────────────────────

def load_snapshots(store):
    out = []
    for p in sorted(glob.glob(os.path.join(store, "market-*.json"))):
        with open(p) as f:
            s = json.load(f)
        out.append((s.get("date") or os.path.basename(p)[7:17], set(s.get("sellers") or {})))
    return out


def load_flow_days(paths):
    """[(date, edges)], one entry per day; a Solana file keeps its own day beside Base's."""
    by = collections.defaultdict(list)
    for p in paths:
        with open(p) as f:
            fl = json.load(f)
        by[fl.get("date") or os.path.basename(p)[6:16]].extend(fl.get("edges") or [])
    return sorted(by.items())


def load_wallet_hosts(paths):
    """{seller wallet: host} from the flows files' own seller lists (first host named)."""
    out = {}
    for p in paths:
        with open(p) as f:
            for w, hs in (json.load(f).get("sellers") or {}).items():
                if hs:
                    out.setdefault(w.lower(), sorted(hs)[0])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd")
    pl = sub.add_parser("pull", help="one UTC day of Base settlements with their facilitators")
    pl.add_argument("--day", required=True)
    pl.add_argument("--snapshot", required=True, help="market-<date>.json: the seller wallets")
    pl.add_argument("--out", required=True)
    ap.add_argument("--whales")
    ap.add_argument("--store", help="the registry snapshots, market-<date>.json")
    ap.add_argument("--flows", nargs="*", default=[])
    ap.add_argument("--settlements")
    ap.add_argument("--site", default="")
    ap.add_argument("--out")
    tiers.add_flags(ap)
    a = ap.parse_args()
    if a.cmd == "pull":
        wallets = chain_flows.wallets_from_snapshot(json.load(open(a.snapshot)))
        head = int(chain_flows.rpc("eth_blockNumber", []), 16)
        start, end = chain_flows.day_bounds(a.day)
        since, until = chain_flows.block_at(start, head), chain_flows.block_at(end, head) - 1
        if until >= head:
            sys.exit("leaders: %s is not over yet on Base" % a.day)
        s = pull_settlements(since, until, wallets)
        json.dump({"date": a.day, "chain": "base", "since_block": since, "head": until, "settlements": s},
                  open(a.out, "w"), indent=1)
        print("settlements %d · facilitators %d -> %s" % (len(s), len({x["facilitator"] for x in s}), a.out))
        return
    if not a.out:
        ap.error("--out is needed")
    rollup = json.load(open(a.whales)) if a.whales else {}
    st = json.load(open(a.settlements)) if a.settlements else None
    d = leaders_data(rollup, load_snapshots(a.store) if a.store else [], load_flow_days(a.flows),
                     st["settlements"] if st else None, st["date"] if st else None, site=a.site,
                     wallet_hosts=load_wallet_hosts(a.flows), free=tiers.from_args(a))
    print("leaders: %s facilitators, %d new sellers, %d new buyer wallets, %d chains -> %s" % (
        "no" if d["facilitators"] is None else len(d["facilitators"]), len(d["new_sellers"]), len(d["new_buyers"]),
        len(d["chains"]), write(a.out, d)))


if __name__ == "__main__":
    sys.exit(main())
