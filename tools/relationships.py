#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 400e511). Edit it there, not here.
"""relationships.py — who came back, what is bought alongside, who left for whom:
relationship facts read from the x402 payments we observe on Base.

A seller's standing is never one number here. It is a handful of facts about the
wallets that paid it, each carrying the counts behind it, read from the daily on-chain
window flows_handoff.py keeps (flows-<date>.json, up to eight days). A seller is its
payTo wallet; the day's sellers map names the hosts paid into each. Only x402 edges
count (n_x402 > 0: a facilitator settled a signed authorization), and only to a wallet
in that day's sellers map.

Per seller wallet:

    buyers            distinct wallets that paid it in the window, with payments and USDC
    came_back         buyers who paid it on 2 or more distinct days, and the rate
    days              the days of the window it was paid on
    loyal             the buyers with the most days paid, then payments (top 5)
    bought_alongside  other sellers sharing the most buyers with it (top 5)
    switches          left_for: buyers who paid it only in the first half of the window and
                      started paying another seller only in the second half (top 5);
                      came_from: the reverse (top 5)
    early_buyers      when its buyers on the last day are at least 10 and at least 3 times
                      the first day's: the wallets that paid it in the first two days

Bought alongside and switches leave out busy wallets, the ones that paid more than 30
sellers in the window, and say how many: a wallet that pays everyone says nothing about
what goes together or who moved. A seller paid on fewer than 2 days keeps its facts with
a note that came-back facts need more days.

The window also keeps the ledger the facts were counted from, read-only, for the seller
report (x402/seller_report.py): ledger["paid"][seller][buyer][date] = [payments, usdc],
ledger["bought"][buyer] = the sellers it paid, ledger["busy"] = the busy wallets, all plain
JSON. So a report is read from the same window, computed once, as the facts beside it.

A wallet is not an agent, and nothing here says who holds or runs one. Deterministic,
no model calls, standard library only.

    relationships.py --flows-dir flows [--host api.example.com ...] [--json]
"""

import argparse
import collections
import json
import os
import re
import sys
import time

FLOWS = re.compile(r"^flows-(\d{4}-\d{2}-\d{2})\.json$")
MAX_DAYS = 8          # flows_handoff.KEEP: the public window holds no more
BUSY = 30             # a buyer wallet that paid more than this many sellers is left out of alongside and switches
TOP = 5
EARLY_LAST_MIN = 10   # early buyers: at least this many buyers on the last day...
EARLY_TIMES = 3       # ...and at least this many times the first day's
EARLY_DAYS = 2        # the first two days of the window
OWN_HOSTS = 12        # hosts named for a seller's own wallet; hosts_total says how many there are
OTHER_HOSTS = 5       # hosts named for another seller in a list

MEANS = ("x402 payments on Base, one window of daily pulls: a buyer is a wallet that paid the seller's payTo "
         "wallet; came back means paid on 2 or more distinct days; bought alongside counts buyers two sellers "
         "share; left for means paid this seller only in the first half of the window and started paying the "
         "other only in the second half. A wallet is not an agent, and a relationship is a pattern of payments, "
         "not a claim about who anyone is.")


def files_key(folder):
    """The identity of the window in `folder`: ((name, size, mtime_ns), ...) for the newest
    MAX_DAYS flows files, oldest first; () when there are none. Cheap: one stat per file."""
    if not folder or not os.path.isdir(folder):
        return ()
    names = sorted(f for f in os.listdir(folder) if FLOWS.match(f))[-MAX_DAYS:]
    out = []
    for name in names:
        try:
            st = os.stat(os.path.join(folder, name))
        except OSError:
            continue
        out.append((name, st.st_size, st.st_mtime_ns))
    return tuple(out)


def _day_problem(d, day):
    if not isinstance(d, dict):
        return "is not an object"
    if d.get("date") != day:
        return "says it is %r, its name says %s" % (d.get("date"), day)
    if not isinstance(d.get("edges"), list) or not isinstance(d.get("sellers"), dict):
        return "has no edges or sellers"
    return None


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def load(folder):
    """(days, key, problems): the window's Base days oldest first as (date, flows), the key of
    the files actually read, and what was left out and why. Never raises on a bad file."""
    days, key, problems = [], [], []
    for name, size, mtime in files_key(folder):
        day = FLOWS.match(name).group(1)
        try:
            with open(os.path.join(folder, name)) as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            problems.append("%s could not be read (%s)" % (name, type(e).__name__))
            continue
        why = _day_problem(d, day)
        if why:
            problems.append("%s %s" % (name, why))
            continue
        if str(d.get("chain") or "base").lower() != "base":
            continue
        key.append((name, size, mtime))
        days.append((day, d))
    return days, tuple(key), problems


def _key(w):
    """A wallet as a dictionary key: a 0x address lowercased (EVM spelling varies), any other
    address as written — base58 is case-sensitive."""
    return w.lower() if w.startswith("0x") else w


def _hosts(ws, cap):
    return {"hosts": ws[:cap], "hosts_total": len(ws)}


def window(folder):
    """Load the window in `folder` once and compute every seller wallet's facts.

    Returns {"dates", "files", "key", "problems", "totals", "busy_buyers", "halves",
    "sellers": {wallet: facts}, "hosts": {host: [wallets]}, "wallet_hosts": {wallet: [hosts]}}.
    Only wallets paid over x402 in the window have facts; for_host() reads it by host."""
    days, key, problems = load(folder)
    dates = [d for d, _ in days]
    wallet_hosts = collections.defaultdict(set)
    pair = {}                                               # (buyer, seller) -> [days, payments, usdc]
    paid = {}                                               # seller -> buyer -> date -> [payments, usdc]
    daily = collections.defaultdict(lambda: collections.defaultdict(set))   # seller -> date -> buyers
    skipped = 0
    for day, d in days:
        today = set()
        for w, hs in d["sellers"].items():
            if not isinstance(w, str):
                continue
            w = _key(w)
            today.add(w)
            wallet_hosts[w].update(str(h).lower() for h in (hs if isinstance(hs, list) else []) if h)
        for e in d["edges"]:
            if not isinstance(e, dict):
                skipped += 1
                continue
            b, s, n, usdc = e.get("from"), e.get("to"), e.get("n_x402"), e.get("usdc_x402", 0)
            if not (isinstance(b, str) and isinstance(s, str) and _num(n) and _num(usdc)):
                skipped += 1
                continue
            b, s = _key(b), _key(s)
            if n <= 0 or s not in today:
                continue
            p = pair.get((b, s))
            if p is None:
                p = pair[(b, s)] = [set(), 0, 0.0]
            p[0].add(day)
            p[1] += n
            p[2] += usdc
            daily[s][day].add(b)
            per = paid.setdefault(s, {}).setdefault(b, {})
            if day in per:
                per[day][0] += n
                per[day][1] += usdc
            else:
                per[day] = [n, usdc]
    if skipped:
        problems.append("%d edges were not in the shape chain_flows writes and were left out" % skipped)

    buyers_of, sellers_of = collections.defaultdict(set), collections.defaultdict(set)
    for b, s in pair:
        buyers_of[s].add(b)
        sellers_of[b].add(s)
    busy = {b for b, ss in sellers_of.items() if len(ss) > BUSY}

    # bought alongside: buyers two sellers share, busy wallets left out
    alongside = collections.defaultdict(collections.Counter)
    for b, ss in sellers_of.items():
        if b in busy or len(ss) < 2:
            continue
        for s in ss:
            for t in ss:
                if t != s:
                    alongside[s][t] += 1

    # switches: the window split in halves; with an odd number of days the middle one is in neither,
    # and a payment on it means the buyer did not pay only in one half
    h = len(dates) // 2
    first, second = set(dates[:h]), set(dates[len(dates) - h:])
    left_for = collections.defaultdict(collections.Counter)
    came_from = collections.defaultdict(collections.Counter)
    switched = 0
    if h:
        for b, ss in sellers_of.items():
            if b in busy:
                continue
            gone = [s for s in ss if pair[(b, s)][0] <= first]
            new = [t for t in ss if pair[(b, t)][0] <= second]
            if gone and new:
                switched += 1
            for s in gone:
                for t in new:
                    left_for[s][t] += 1
                    came_from[t][s] += 1

    # a wallet is named by its most particular hosts first: a host the registry lists on many
    # wallets names none of them well
    hosts = collections.defaultdict(list)
    for w, hs in wallet_hosts.items():
        for host in hs:
            hosts[host].append(w)
    named = {w: sorted(hs, key=lambda x: (len(hosts[x]), x)) for w, hs in wallet_hosts.items()}

    def other(w, **extra):
        out = {"wallet": w}
        out.update(_hosts(named.get(w, []), OTHER_HOSTS))
        out.update(extra)
        return out

    def top(counter, field):
        return [other(t, **{field: c}) for t, c in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]]

    sellers = {}
    for s, bs in buyers_of.items():
        rows = [(b, pair[(b, s)]) for b in bs]
        paid_on = sorted({day for _, p in rows for day in p[0]})
        n_buyers = len(bs)
        back = sum(1 for _, p in rows if len(p[0]) >= 2)
        loyal = sorted(rows, key=lambda r: (-len(r[1][0]), -r[1][1], r[0]))[:TOP]
        busy_here = len(bs & busy)
        f = {"wallet": s,
             "days": {"window": len(dates), "paid": len(paid_on), "paid_on": paid_on},
             "buyers": {"count": n_buyers, "payments": sum(p[1] for _, p in rows),
                        "usdc": round(sum(p[2] for _, p in rows), 4)},
             "came_back": {"buyers": back, "of": n_buyers, "rate_pct": round(100.0 * back / n_buyers, 1)},
             "loyal": [{"wallet": b, "days": len(p[0]), "payments": p[1], "usdc": round(p[2], 4)} for b, p in loyal],
             "bought_alongside": {"sellers": [dict(x, share_pct=round(100.0 * x["shared_buyers"] / n_buyers, 1))
                                              for x in top(alongside[s], "shared_buyers")],
                                  "busy_buyers_left_out": busy_here},
             "switches": {"left_for": top(left_for[s], "buyers"), "came_from": top(came_from[s], "buyers"),
                          "busy_buyers_left_out": busy_here},
             "early_buyers": None, "notes": []}
        f.update(_hosts(named.get(s, []), OWN_HOSTS))
        first_n = len(daily[s].get(dates[0], ())) if dates else 0
        last_n = len(daily[s].get(dates[-1], ())) if dates else 0
        if len(dates) > EARLY_DAYS and last_n >= EARLY_LAST_MIN and last_n >= EARLY_TIMES * first_n:
            early = set().union(*(daily[s].get(d, set()) for d in dates[:EARLY_DAYS]))
            f["early_buyers"] = {"wallets": len(early), "days": dates[:EARLY_DAYS],
                                 "first_day_buyers": first_n, "last_day_buyers": last_n}
        if len(paid_on) < 2:
            f["notes"].append("paid on %d day of the window: came-back facts need 2 or more days"
                              % len(paid_on))
        sellers[s] = f

    return {"dates": dates, "files": [k[0] for k in key], "key": key, "problems": problems,
            "halves": {"first": sorted(first), "second": sorted(second)},
            "busy": BUSY, "busy_buyers": len(busy),
            "totals": {"buyers": len(sellers_of), "sellers_paid": len(buyers_of), "pairs": len(pair),
                       "pairs_3_or_more_days": sum(1 for p in pair.values() if len(p[0]) >= 3),
                       "switched_buyers": switched},
            "sellers": sellers, "hosts": {k: sorted(v) for k, v in hosts.items()},
            "wallet_hosts": named,
            "ledger": {"paid": paid, "bought": {b: sorted(ss) for b, ss in sellers_of.items()},
                       "busy": sorted(busy)}}


def for_host(win, host):
    """The facts for each wallet `host` is paid into, most buyers first, as
    {"host", "wallets": [facts], "unpaid_wallets": [wallet]}; None when the window's
    sellers map does not name the host."""
    ws = (win or {}).get("hosts", {}).get(str(host or "").lower())
    if ws is None:
        return None
    paid = sorted((win["sellers"][w] for w in ws if w in win["sellers"]),
                  key=lambda f: (-f["buyers"]["count"], f["wallet"]))
    return {"host": str(host).lower(), "wallets": paid, "unpaid_wallets": [w for w in ws if w not in win["sellers"]]}


# ── plain words, for the command line ────────────────────────────────────

def _name(x):
    hs = x.get("hosts") or [x["wallet"]]
    more = x.get("hosts_total", len(hs)) - 1
    return hs[0] + (" (+%d host%s on its wallet)" % (more, "s" if more != 1 else "") if more > 0 else "")


def sentences(f):
    """One wallet's facts as plain sentences, every number shown."""
    out = []
    b, cb = f["buyers"], f["came_back"]
    out.append("%s buyers paid it on %d of the window's %d days (%s payments, $%s)."
               % ("{:,}".format(b["count"]), f["days"]["paid"], f["days"]["window"], "{:,}".format(b["payments"]),
                  "{:,.2f}".format(b["usdc"])))
    out.append("%s of %s buyers came back on another day (%g%%)."
               % ("{:,}".format(cb["buyers"]), "{:,}".format(cb["of"]), cb["rate_pct"]))
    for x in f["loyal"]:
        out.append("  loyal: %s paid on %d day%s, %s payment%s" % (x["wallet"], x["days"], "s" if x["days"] != 1 else "",
                                                                 "{:,}".format(x["payments"]), "s" if x["payments"] != 1 else ""))
    for x in f["bought_alongside"]["sellers"]:
        out.append("  bought alongside: %s (%d shared buyer%s, %g%% of its buyers)"
                   % (_name(x), x["shared_buyers"], "s" if x["shared_buyers"] != 1 else "", x["share_pct"]))
    for x in f["switches"]["left_for"]:
        out.append("  %d buyer%s left for %s" % (x["buyers"], "s" if x["buyers"] != 1 else "", _name(x)))
    for x in f["switches"]["came_from"]:
        out.append("  %d buyer%s came from %s" % (x["buyers"], "s" if x["buyers"] != 1 else "", _name(x)))
    if f["bought_alongside"]["busy_buyers_left_out"]:
        out.append("  (left out of bought alongside and switches: %d of its buyers, each of which paid more than %d sellers)"
                   % (f["bought_alongside"]["busy_buyers_left_out"], BUSY))
    e = f["early_buyers"]
    if e:
        out.append("Early buyers: %d wallets paid it on %s, before its daily buyers went from %d on the first day to %d on the last."
                   % (e["wallets"], " and ".join(e["days"]), e["first_day_buyers"], e["last_day_buyers"]))
    out.extend("Note: %s." % n for n in f["notes"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--flows-dir", required=True, help="a folder of flows-<date>.json (flows_handoff.py fetch keeps one)")
    ap.add_argument("--host", action="append", default=[], help="print this host's facts (repeatable)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of sentences")
    a = ap.parse_args()
    t0 = time.perf_counter()
    win = window(a.flows_dir)
    took = time.perf_counter() - t0
    if not win["dates"]:
        sys.exit("relationships: no flows-<date>.json in %s%s" % (a.flows_dir, "; " + "; ".join(win["problems"]) if win["problems"] else ""))
    t = win["totals"]
    print("window %s to %s (%d days) · %s buyer wallets · %s sellers paid · %s buyer-seller pairs, %s on 3 or more days · "
          "%d busy wallets (> %d sellers) · %d buyers switched · computed in %.2f s"
          % (win["dates"][0], win["dates"][-1], len(win["dates"]), "{:,}".format(t["buyers"]), "{:,}".format(t["sellers_paid"]),
             "{:,}".format(t["pairs"]), "{:,}".format(t["pairs_3_or_more_days"]), win["busy_buyers"], BUSY,
             t["switched_buyers"], took), file=sys.stderr)
    for p in win["problems"]:
        print("  left out: %s" % p, file=sys.stderr)
    views = {h: for_host(win, h) for h in a.host}
    if a.json:
        json.dump(views if a.host else {"dates": win["dates"], "totals": t, "sellers": win["sellers"]}, sys.stdout, indent=1)
        print()
        return
    for h, v in views.items():
        print("\n== %s" % h)
        if v is None:
            print("not in the window's sellers map")
            continue
        if not v["wallets"]:
            print("no x402 payment reached its wallet%s in the window" % ("s" if len(v["unpaid_wallets"]) != 1 else ""))
        for f in v["wallets"]:
            print("-- wallet %s (hosts: %s%s)" % (f["wallet"], ", ".join(f["hosts"]),
                                                 ", +%d more" % (f["hosts_total"] - len(f["hosts"])) if f["hosts_total"] > len(f["hosts"]) else ""))
            for line in sentences(f):
                print(line)
        if v["unpaid_wallets"]:
            print("(%d more of its wallets were not paid over x402 in the window)" % len(v["unpaid_wallets"]))


if __name__ == "__main__":
    main()
