#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 14d153d). Edit it there, not here.
"""radar.py — Infoharmoni Radar: how the agent market moved, and how you did in it.

The 2009 thesis, applied to the new swarm: *replay beats snapshot.* Listening
platforms are opinion polls — a picture of the past. What matters is how
attention DEVELOPED. "This is radar. Before radar you had guys with binoculars
saying I think that's an airplane."

Every other view of x402 shows you today. This one keeps yesterday, so it can
tell you what CHANGED — who appeared, who died, who is climbing, what prices
moved — and it can answer the question a seller actually has:

    how am I doing in this market?

Four commands:

    radar.py snapshot                 store today's market (registry + chain)
    radar.py diff                     what changed since the last snapshot
    radar.py who <host|wallet>        one seller's own report card
    radar.py like <words...>          is anyone paid for a service like this?

Snapshots are small (a few hundred KB) and append-only: the value compounds,
and it cannot be back-filled by anyone who did not start storing. Standard
library only, public data only. MIT.
"""

import argparse
import collections
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

DISCOVERY = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
STORE = os.environ.get("RADAR_STORE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "radar-store")
NET = {"eip155:8453": "Base", "eip155:137": "Polygon", "eip155:42161": "Arbitrum",
       "xrpl:0": "XRPL", "eip155:1": "Ethereum", "eip155:10": "Optimism", "eip155:56": "BNB"}


def net_name(n):
    return NET.get(n, "Solana" if str(n).startswith("solana") else str(n or "?"))


def fetch_registry(limit_s=600, tries=4):
    """Page through the registry, saying where it is. A run that hangs silently
    is indistinguishable from one that is working, so every page reports, each
    page retries a bounded number of times, and the whole pull has a deadline."""
    import time
    items, offset, start = [], 0, time.time()
    while True:
        if time.time() - start > limit_s:
            sys.exit("radar: gave up after %ds at offset %d (%d items) — nothing stored"
                     % (limit_s, offset, len(items)))
        url = "%s?limit=100&offset=%d" % (DISCOVERY, offset)
        req = urllib.request.Request(url, headers={"User-Agent": "infoharmoni-radar/1.0"})
        for attempt in range(1, tries + 1):
            try:
                got = json.load(urllib.request.urlopen(req, timeout=30)).get("items", [])
                break
            except Exception as e:
                if attempt == tries:
                    sys.exit("radar: offset %d failed %d times (%s) — nothing stored"
                             % (offset, tries, str(e)[:80]))
                print("  offset %d: %s — retry %d/%d" % (offset, str(e)[:60], attempt, tries - 1),
                      file=sys.stderr)
                time.sleep(2 * attempt)
        items += got
        if offset % 1000 == 0:
            print("  %6d items · %3ds" % (len(items), time.time() - start), file=sys.stderr)
        if len(got) < 100 or offset > 40000:
            return items
        offset += 100


def condense(items):
    """One row per seller host: what it sells, what it charges, how it did."""
    sellers = {}
    for it in items:
        url = it.get("resource", "")
        host = urllib.parse.urlparse(url).netloc.replace("www.", "") or url[:40]
        a = (it.get("accepts") or [{}])[0]
        try:
            price = int(a.get("maxAmountRequired") or a.get("amount") or 0) / 1e6
        except (TypeError, ValueError):
            price = 0.0
        if price > 1e5:
            price = 0.0
        q = it.get("quality") or {}
        s = sellers.setdefault(host, {"host": host, "endpoints": 0, "calls": 0, "payers": 0,
                                      "take": 0.0, "prices": [], "chains": set(), "wallets": set(),
                                      "best": None, "desc": ""})
        s["endpoints"] += 1
        s["calls"] += q.get("l30DaysTotalCalls", 0) or 0
        s["payers"] += q.get("l30DaysUniquePayers", 0) or 0
        s["take"] += (q.get("l30DaysTotalCalls", 0) or 0) * price
        s["prices"].append(price)
        s["chains"].add(net_name(a.get("network")))
        if a.get("payTo"):
            s["wallets"].add(a["payTo"])
        c = q.get("l30DaysTotalCalls", 0) or 0
        if s["best"] is None or c > s["best"][0]:
            s["best"] = (c, (it.get("description") or "")[:140], url)
    out = {}
    for h, s in sellers.items():
        pr = sorted(p for p in s["prices"] if p > 0)
        out[h] = {"endpoints": s["endpoints"], "calls": s["calls"], "payers": s["payers"],
                  "take": round(s["take"], 2), "chains": sorted(s["chains"]),
                  "wallets": sorted(s["wallets"]),        # every one: the chain pull reads these
                  "price_min": pr[0] if pr else 0, "price_med": pr[len(pr) // 2] if pr else 0,
                  "price_max": pr[-1] if pr else 0,
                  "sells": s["best"][1] if s["best"] else "", "url": s["best"][2] if s["best"] else ""}
    return out


def snapshot_path(d):
    return os.path.join(STORE, "market-%s.json" % d)


def snapshots():
    if not os.path.isdir(STORE):
        return []
    return sorted(f for f in os.listdir(STORE) if f.startswith("market-") and f.endswith(".json"))


def load_snapshot(name):
    return json.load(open(os.path.join(STORE, name)))


def cmd_snapshot(a):
    os.makedirs(STORE, exist_ok=True)
    items = fetch_registry()
    sellers = condense(items)
    snap = {"taken": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "date": a.date, "endpoints": len(items), "sellers": sellers}
    path = snapshot_path(a.date)
    json.dump(snap, open(path, "w"), indent=1, sort_keys=True)
    calls = sum(s["calls"] for s in sellers.values())
    print("%s · %d sellers · %d endpoints · %s calls (30 d) · $%s"
          % (a.date, len(sellers), len(items), "{:,}".format(calls),
             "{:,.0f}".format(sum(s["take"] for s in sellers.values()))))
    print("stored", path)


def pct(now, then):
    if not then:
        return "new"
    return "%+.0f%%" % (100.0 * (now - then) / then)


def cmd_diff(a):
    snaps = snapshots()
    if len(snaps) < 2:
        sys.exit("radar: need two snapshots to compare — have %d. Run `radar.py snapshot` daily."
                 % len(snaps))
    new, old = load_snapshot(snaps[-1]), load_snapshot(snaps[-2])
    A, B = new["sellers"], old["sellers"]
    born = [h for h in A if h not in B]
    gone = [h for h in B if h not in A]
    moved = []
    for h in A:
        if h in B and B[h]["calls"] >= 20:
            d = A[h]["calls"] - B[h]["calls"]
            if d:
                moved.append((d, h))
    moved.sort(reverse=True)
    priced = [(h, B[h]["price_med"], A[h]["price_med"]) for h in A
              if h in B and B[h]["price_med"] and A[h]["price_med"] != B[h]["price_med"]]

    print("── INFOHARMONI RADAR · %s vs %s ──" % (new["date"], old["date"]))
    print("   %d sellers (%+d) · %s calls in 30 d (%s)"
          % (len(A), len(A) - len(B),
             "{:,}".format(sum(s["calls"] for s in A.values())),
             pct(sum(s["calls"] for s in A.values()), sum(s["calls"] for s in B.values()))))
    print("\n  NEW SELLERS (%d)" % len(born))
    for h in sorted(born, key=lambda h: -A[h]["calls"])[:10]:
        print("    %-34s %5d calls  $%-7.3f %s" % (h[:34], A[h]["calls"], A[h]["price_med"], A[h]["sells"][:44]))
    print("\n  GONE (%d)" % len(gone))
    for h in sorted(gone, key=lambda h: -B[h]["calls"])[:6]:
        print("    %-34s had %d calls" % (h[:34], B[h]["calls"]))
    print("\n  CLIMBING  (change in the rolling 30-day call count)")
    for d, h in moved[:10]:
        print("    %-34s %+6d calls  %s  %s" % (h[:34], d, pct(A[h]["calls"], B[h]["calls"]), A[h]["sells"][:36]))
    print("\n  FALLING  (change in the rolling 30-day call count)")
    for d, h in moved[-6:][::-1]:
        print("    %-34s %+6d calls  %s" % (h[:34], d, pct(A[h]["calls"], B[h]["calls"])))
    if priced:
        print("\n  PRICE MOVES")
        for h, was, now in priced[:8]:
            print("    %-34s $%.3f → $%.3f" % (h[:34], was, now))


def median(values):
    """The conventional median: the middle value, or the mean of the two middles."""
    v = sorted(values)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def price_label(s):
    """A seller's price as words: one figure, or the range across its endpoints."""
    lo, hi = s["price_min"], s["price_max"]
    if not hi:
        return "unpriced"
    return "$%g" % lo if lo == hi else "$%g–$%g" % (lo, hi)


def price_verdict(s, going):
    """Over, under or at the going rate — but only when that is true of every endpoint
    the seller lists. A seller whose prices straddle the going rate gets "mixed" and no
    single verdict: one blended median called a $0.001 endpoint expensive because a $0.35
    sibling existed (api.anchor-x402.com, 2026-09-23), and did the same to ~380 others."""
    if not going or not s["price_max"]:
        return None
    if s["price_max"] < going:
        return "under"
    if s["price_min"] > going:
        return "over"
    if s["price_min"] == s["price_max"] == going:
        return "at"
    return "mixed"


def who_data(target, loaded=None):
    """One seller's report card as data. Raises LookupError when the name is
    unknown, or Ambiguous when several sellers match. The CLI and the paid
    endpoint both read this, so they can never drift apart.

    `loaded`: an already-parsed list of snapshots, oldest to newest. The paid
    endpoint passes the exact set it validated, so the report sold is built
    from the bytes that were checked and from nothing else."""
    if loaded is None:
        snaps = snapshots()
        if not snaps:
            raise LookupError("no snapshots yet — run `radar.py snapshot` first")
        loaded = [load_snapshot(f) for f in snaps[-8:]]
    new = loaded[-1]
    A = new["sellers"]
    key = target.lower().replace("www.", "")
    host = next((h for h in A if h.lower() == key), None) \
        or next((h for h, s in A.items() if key in [w.lower() for w in s["wallets"]]), None)
    if not host:
        near = sorted((h for h in A if key in h.lower()), key=lambda h: -A[h]["calls"])
        if len(near) == 1:
            host = near[0]
        elif near:
            raise Ambiguous(near[:12])
    if not host:
        raise LookupError("%s is not selling in this market. That is itself an answer." % target)
    me = A[host]
    by_calls = [h for h, _ in sorted(A.items(), key=lambda kv: -kv[1]["calls"])]
    by_take = [h for h, _ in sorted(A.items(), key=lambda kv: -kv[1]["take"])]
    total_calls = sum(s["calls"] for s in A.values())

    hist = []
    for snap in loaded[-8:]:
        s = snap["sellers"].get(host)
        if s:
            hist.append({"date": snap["date"], "calls": s["calls"], "payers": s["payers"]})

    words = set(re.findall(r"[a-z]{4,}", me["sells"].lower()))
    rivals = []
    for h, s in A.items():
        if h == host:
            continue
        overlap = len(words & set(re.findall(r"[a-z]{4,}", s["sells"].lower())))
        if overlap >= 2:
            rivals.append({"host": h, "calls": s["calls"], "price": price_label(s), "price_med": s["price_med"],
                           "sells": s["sells"][:80], "_overlap": overlap})
    rivals.sort(key=lambda r: (-r["_overlap"], -r["calls"]))
    priced = [r["price_med"] for r in rivals if r["price_med"]]       # every matched rival with a listed price
    going = median(priced)
    rivals_matched, rivals_priced = len(rivals), len(priced)
    rivals = [{k: v for k, v in r.items() if k != "_overlap"} for r in rivals[:6]]
    verdict = price_verdict(me, going)
    if verdict == "mixed":
        verdict_note = ("endpoints priced %s and the going rate falls inside that range: no single "
                        "verdict is fair, compare per endpoint" % price_label(me))
    elif verdict:
        verdict_note = "true of every endpoint this seller lists"
    else:
        verdict_note = None
    return {
        "host": host, "as_of": new["date"], "sells": me["sells"],
        "calls_30d": me["calls"], "payers_30d": me["payers"],
        "payers_note": "endpoint counts summed — a wallet paying two endpoints counts twice",
        "est_take_30d_list_price": me["take"],
        "take_note": "calls x list price; it undercounts sellers whose price varies",
        "price": price_label(me),
        "price_min": me["price_min"], "price_med": me["price_med"], "price_max": me["price_max"],
        "price_note": "list prices across this seller's endpoints; price_med is the median endpoint "
                      "price, not what a call costs",
        "chains": me["chains"], "endpoints": me["endpoints"],
        "rank_by_calls": by_calls.index(host) + 1, "rank_by_money": by_take.index(host) + 1,
        "sellers_in_market": len(A), "market_calls_30d": total_calls,
        "share_of_paid_calls_pct": round(100.0 * me["calls"] / max(total_calls, 1), 4),
        "replay": hist, "rivals": rivals, "rivals_matched": rivals_matched,
        "rivals_priced": rivals_priced, "going_rate": going,
        "going_rate_note": "median price of the %d matched rivals with a listed price (of %d matched); "
                           "a rival with several prices counts by its median endpoint price"
                           % (rivals_priced, rivals_matched),
        "you_are": verdict, "you_are_note": verdict_note,
    }


class Ambiguous(LookupError):
    def __init__(self, candidates):
        super().__init__("%d sellers match" % len(candidates))
        self.candidates = candidates


def cmd_who(a):
    """A seller's own report card — the thing an agent wants about itself."""
    try:
        d = who_data(a.target)
    except Ambiguous as e:
        print("radar: %d sellers match %r — say which:" % (len(e.candidates), a.target))
        for h in e.candidates:
            print("   %s" % h)
        sys.exit(2)
    except LookupError as e:
        sys.exit("radar: %s" % e)

    print("── %s ──" % d["host"])
    print("   sells: %s" % d["sells"])
    print("   %s calls in 30 days · %d payers (%s) · about $%s at list price"
          % ("{:,}".format(d["calls_30d"]), d["payers_30d"], d["payers_note"],
             "{:,.2f}".format(d["est_take_30d_list_price"])))
    print("   price $%g–$%g (median $%g) · %s · %d endpoint%s"
          % (d["price_min"], d["price_max"], d["price_med"], ", ".join(d["chains"]),
             d["endpoints"], "s" if d["endpoints"] != 1 else ""))
    print("   rank %d of %d by calls · rank %d by money · %.3f%% of all paid calls"
          % (d["rank_by_calls"], d["sellers_in_market"], d["rank_by_money"],
             d["share_of_paid_calls_pct"]))
    if len(d["replay"]) > 1:
        print("\n   YOUR REPLAY")
        peak = max(h["calls"] for h in d["replay"]) or 1
        for h in d["replay"]:
            print("     %s %6d %s" % (h["date"], h["calls"],
                                      "█" * max(1, int(30 * h["calls"] / peak))))
        print("     %s since %s" % (pct(d["replay"][-1]["calls"], d["replay"][0]["calls"]),
                                    d["replay"][0]["date"]))
    else:
        print("\n   (one snapshot so far — movement appears from tomorrow)")
    if d["rivals"]:
        print("\n   SELLING SOMETHING LIKE YOURS")
        for r in d["rivals"]:
            print("     %-30s %6d calls  %-14s %s"
                  % (r["host"][:30], r["calls"], r["price"], r["sells"][:40]))
        if d["you_are"] == "mixed":
            print("     going rate $%g; your endpoints run %s — no single verdict, compare per endpoint"
                  % (d["going_rate"], d["price"]))
        elif d["you_are"]:
            print("     you charge %s, they charge $%g — you are %s the going rate"
                  % (d["price"], d["going_rate"], d["you_are"]))
    print("\n   market: %d sellers, %s paid calls in 30 days"
          % (d["sellers_in_market"], "{:,}".format(d["market_calls_30d"])))


def cmd_like(a):
    """Demand for a KIND of service: who sells something like the words you
    give, whether anyone pays them, and at what price. The question to ask
    before you build or price an offer — is there a market for this at all?"""
    snaps = snapshots()
    if not snaps:
        sys.exit("radar: no snapshots yet — run `radar.py snapshot` first.")
    new = load_snapshot(snaps[-1])
    A = new["sellers"]
    words = [w.lower() for w in a.words]
    hits = []
    for h, s in A.items():
        text = (h + " " + s["sells"]).lower()
        got = [w for w in words if w in text]
        if got and (a.all is False or len(got) == len(words)):
            hits.append((len(got), s["calls"], h, s))
    if not hits:
        sys.exit("radar: nobody is selling anything like %r. Either the market is not there,\n"
                 "       or nobody has built it yet — the snapshot cannot tell those apart."
                 % " ".join(a.words))
    hits.sort(key=lambda t: -t[1])
    calls = sum(s["calls"] for _n, _c, _h, s in hits)
    payers = sum(s["payers"] for _n, _c, _h, s in hits)
    take = sum(s["take"] for _n, _c, _h, s in hits)
    paid = [s for _n, _c, _h, s in hits if s["calls"] > 0]
    prices = sorted(s["price_med"] for s in paid if s["price_med"]) or \
             sorted(s["price_med"] for _n, _c, _h, s in hits if s["price_med"])
    total_calls = sum(s["calls"] for s in A.values())

    print("── LIKE: %s · %s ──" % (" ".join(a.words), new["date"]))
    print("   %d sellers match (%s of %d) · %d of them have been paid at all"
          % (len(hits), "all words" if a.all else "any word", len(A), len(paid)))
    print("   %s paid calls in 30 d (%.2f%% of the market) · %d payers (endpoint counts summed)"
          " · about $%s at list price"
          % ("{:,}".format(calls), 100.0 * calls / max(total_calls, 1), payers, "{:,.2f}".format(take)))
    if prices:
        print("   going rate: $%g per call (median of %d priced sellers, $%g–$%g; a seller with several "
              "prices counts by its median endpoint price)"
              % (median(prices), len(prices), prices[0], prices[-1]))
    print("\n   %-36s %7s %6s %-14s %s" % ("seller", "calls", "payers", "price", "sells"))
    for _n, c, h, s in hits[:a.top]:
        print("   %-36s %7d %6d  %-14s %s" % (h[:36], c, s["payers"], price_label(s), s["sells"][:48]))
    if len(hits) > a.top:
        print("   … and %d more" % (len(hits) - a.top))

    if len(snaps) > 1:
        rows = []
        for name in snaps[-8:]:
            snap = load_snapshot(name)
            S = snap["sellers"]
            hs = [h for _n, _c, h, _s in hits if h in S]
            rows.append((snap["date"], len(hs), sum(S[h]["calls"] for h in hs)))
        print("\n   THE REPLAY  (these sellers, on each stored day)")
        for d, n, c in rows:
            bar = "█" * max(1, int(30 * c / max(r[2] for r in rows) if max(r[2] for r in rows) else 1))
            print("     %s %3d sellers %7d calls %s" % (d, n, c, bar))
        print("     calls %s since %s" % (pct(rows[-1][2], rows[0][2]), rows[0][0]))
    print("\n   market: %d sellers, %s paid calls in 30 days" % (len(A), "{:,}".format(total_calls)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="store today's market")
    s.add_argument("--date", default=date.today().isoformat())
    s.set_defaults(fn=cmd_snapshot)
    d = sub.add_parser("diff", help="what changed since the last snapshot")
    d.set_defaults(fn=cmd_diff)
    w = sub.add_parser("who", help="one seller's report card")
    w.add_argument("target", help="a host (api.example.com) or a payTo wallet")
    w.set_defaults(fn=cmd_who)
    l = sub.add_parser("like", help="is anyone paid for a service like this, and what does it cost")
    l.add_argument("words", nargs="+", help="words that describe the service, e.g. market intelligence")
    l.add_argument("--all", action="store_true", help="require every word, not any")
    l.add_argument("--top", type=int, default=12, help="rows to show")
    l.set_defaults(fn=cmd_like)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
