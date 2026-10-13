#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 83713b3). Edit it there, not here.
"""brief.py — the weekly x402 Market Brief, written from the data: one command, one page
for people and one JSON file for agents, every number computed and dated.

    brief.py --flows-dir flows --from 2026-10-03 --to 2026-10-10 [--out brief]
             [--site https://atlas.infoharmoni.com]

For each day from --from to --to it reads flows-<date>.json (Base) and, when it is there,
flows-sol-<date>.json (Solana): the daily files chain_flows.py and solana_flows.py write
and the Atlas publishes. It writes

    <out>/<from>-to-<to>/index.html   the brief, in the Atlas look
    <out>/<from>-to-<to>/brief.json   the same numbers, named for an agent
    <out>/latest.json                 brief.json again, unless <out> holds a newer brief

Five parts:

    1 where the money went   x402 USDC and payments; the top three sellers' share; for each
                             top seller, the share of its USDC from its largest payer
    2 concentration          sellers with exactly one paying wallet; the median payers a seller
    3 growth                 sellers whose paying wallets grew from the window's first half to
                             its second, from many wallets or from one
    4 Solana                 when its files are there: totals by day and the top payees
    5 what it means          a short list made from the numbers by fixed rules

The rules are the Atlas's own (relationships.py, whales.py). A seller is its payTo wallet,
named by the hosts the registry lists on it. Only x402 payments count (n_x402 > 0: a
facilitator settled a signed authorization), and on Base only those to a wallet in that
day's sellers map. A robot wallet paid 20 or more different sellers in the window. The
halves are relationships.py's: with an odd number of days the middle one is in neither.

Before any total, the largest single edge in it is found (an edge is one wallet paying one
wallet on one day: one row of a daily file). When one edge is more than half of a total,
the page says so beside the total, and brief.json marks it over_half with the total
without it.

USDC is summed in millionths, so totals are exact and the same files give the same bytes.
A wallet is not a person, and nothing here says who holds or runs one. No model calls;
standard library only.
"""

import argparse
import collections
import datetime
import hashlib
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import atlas_style  # noqa: E402
import market  # noqa: E402
import relationships  # noqa: E402
import whales  # noqa: E402

KIND = "x402-market-brief"
VERSION = 1
TITLE = "x402 Market Brief"
SITE = "https://atlas.infoharmoni.com"
ROBOT = 20        # a wallet that paid this many different sellers or more in the window is a robot (a sampler)
TOP = 10          # rows in each list
LEAD = 3          # "the top three sellers"
HOSTS = 12        # hosts named for a wallet in brief.json; hosts_total says how many there are
MAX_DAYS = 31     # a brief covers a week; a month at most
MICRO = 1000000   # USDC has six decimals: sums are kept in whole millionths
BUCKETS = ((1, 1, "1"), (2, 4, "2 to 4"), (5, 19, "5 to 19"), (20, None, "20 or more"))

# The one word the Atlas never says, spelled apart so this file never says it either. A few
# registry hosts hold it; a label shows "…" in its place, and the wallet beside it stays exact.
_UNSAID = re.compile(r"[A-Za-z0-9]*" + "ver" + "if" + r"[A-Za-z0-9]*", re.I)

Edge = collections.namedtuple("Edge", "micro n date payer payee")


def label(text):
    return _UNSAID.sub("…", str(text))


# ── reading the files ────────────────────────────────────────────────────

def day_arg(s):
    try:
        return datetime.date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("%r is not a date like 2026-10-03" % s)


def span(start, end):
    a, b = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    return [(a + datetime.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def read_day(path, day, chain):
    """(flows, sha256, problem) for one daily file; flows is None when it was left out."""
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        d = json.loads(raw)
    except (OSError, ValueError) as e:
        return None, None, "%s could not be read (%s)" % (name, type(e).__name__)
    why = relationships._day_problem(d, day)
    if why:
        return None, None, "%s %s" % (name, why)
    said = str(d.get("chain") or "base").lower()
    if said != chain:
        return None, None, "%s says its chain is %s, its name says %s" % (name, said, chain)
    return d, hashlib.sha256(raw).hexdigest(), None


def load(folder, start, end):
    """(base, sol, files, problems): the days from start to end whose files are there and
    sound, each as (date, flows), oldest first; the files read with their sha256; and what
    was left out and why. Never raises on a bad file."""
    base, sol, files, problems = [], [], [], []
    for day in span(start, end):
        for chain, name, into in (("base", "flows-%s.json" % day, base), ("solana", "flows-sol-%s.json" % day, sol)):
            path = os.path.join(folder, name)
            if not os.path.exists(path):
                continue
            d, sha, why = read_day(path, day, chain)
            if why:
                problems.append(why)
                continue
            into.append((day, d))
            files.append({"name": name, "chain": "Base" if chain == "base" else "Solana", "date": day, "sha256": sha})
    return base, sol, files, problems


def edges_of(d, day, listed_only):
    """One day's x402 edges as Edge rows, and how many rows were left out: (rows, off_map, bad).
    On Base (listed_only) an edge counts only to a wallet in that day's sellers map."""
    listed = {relationships._key(w) for w in d["sellers"] if isinstance(w, str)}
    rows, off, bad = [], 0, 0
    for e in d["edges"]:
        if not isinstance(e, dict):
            bad += 1
            continue
        b, s, n, u = e.get("from"), e.get("to"), e.get("n_x402"), e.get("usdc_x402", 0)
        if not (isinstance(b, str) and isinstance(s, str) and relationships._num(n) and relationships._num(u)):
            bad += 1
            continue
        if n <= 0:
            continue
        b, s = relationships._key(b), relationships._key(s)
        if listed_only and s not in listed:
            off += 1
            continue
        rows.append(Edge(int(round(u * MICRO)), int(n), day, b, s))
    return rows, off, bad


def host_names(days):
    """wallet -> its hosts, the most particular first: a host the registry lists on many
    wallets names none of them well (relationships.py does the same)."""
    of = collections.defaultdict(set)
    for _day, d in days:
        for w, hs in d["sellers"].items():
            if isinstance(w, str) and isinstance(hs, list):
                of[relationships._key(w)].update(str(h).lower() for h in hs if h)
    wallets_on = collections.Counter(h for hs in of.values() for h in hs)
    return {w: sorted(hs, key=lambda h: (wallets_on[h], h)) for w, hs in of.items()}


# ── counting ─────────────────────────────────────────────────────────────

def usd(micro):
    return micro / MICRO


def pct(part, whole):
    """part of whole in percent, one decimal. A part short of the whole never reads as 100, and a
    part above nothing never reads as 0: under 0.05% it keeps two significant digits."""
    if not whole:
        return None
    raw = 100.0 * part / whole
    p = round(raw, 1)
    if p >= 100.0 and part < whole:
        p = 99.9
    if p == 0 and part > 0:
        p = float("%.2g" % raw)
    return p


def change(a, b):
    """b against a, in percent, one decimal; None when a is nothing."""
    return round(100.0 * (b - a) / a, 1) if a else None


def num(x):
    return int(x) if x == int(x) else round(x, 1)


def dated(days):
    return {"from": days[0], "to": days[-1], "days": len(days)} if days else None


def edge_key(e):
    return (e.micro, e.n, e.date, e.payer, e.payee)


def largest(rows, micro):
    """The largest single edge in a total, and whether it is more than half of it."""
    if not rows:
        return None
    e = max(rows, key=edge_key)
    return {"date": e.date, "from": e.payer, "to": e.payee, "usdc": usd(e.micro), "payments": e.n,
            "share_pct": pct(e.micro, micro), "over_half": 2 * e.micro > micro,
            "usdc_without_it": usd(micro - e.micro)}


def top_payer(rows, micro, robots=None):
    per = collections.defaultdict(lambda: [0, 0])
    for e in rows:
        per[e.payer][0] += e.micro
        per[e.payer][1] += e.n
    if not per:
        return None
    w, (m, n) = min(per.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
    out = {"wallet": w, "usdc": usd(m), "payments": n, "share_pct": pct(m, micro), "over_half": 2 * m > micro}
    if robots is not None:                        # robots are counted on Base only
        out["robot"] = w in robots
    return out


class Totals:
    """Every total the brief shows goes through here, so none is shown without its largest edge."""

    def __init__(self):
        self.over_half = []

    def __call__(self, rows, where, what):
        micro = sum(e.micro for e in rows)
        out = {"usdc": usd(micro), "payments": sum(e.n for e in rows), "largest_edge": largest(rows, micro)}
        le = out["largest_edge"]
        if le and le["over_half"]:
            self.over_half.append(dict({"where": where, "what": what}, **le))
        return out


def build(folder, start, end, site=SITE):
    """The brief as a dict: the numbers, the method and the caveats. brief.json is this."""
    base, sol, files, problems = load(folder, start, end)
    dates = [d for d, _ in base]
    tot = Totals()
    names = host_names(base)

    def who(w, hosts=names):
        hs = hosts.get(w, [])
        return {"wallet": w, "hosts": [label(h) for h in hs[:HOSTS]], "hosts_total": len(hs)}

    rows, off_map, bad = [], 0, 0
    for day, d in base:
        r, o, b = edges_of(d, day, True)
        rows += r
        off_map += o
        bad += b
    by_seller = collections.defaultdict(list)
    sellers_of = collections.defaultdict(set)
    for e in rows:
        by_seller[e.payee].append(e)
        sellers_of[e.payer].add(e.payee)
    robots = {w for w, ss in sellers_of.items() if len(ss) >= ROBOT}
    micro = {s: sum(e.micro for e in rs) for s, rs in by_seller.items()}
    payers = {s: {e.payer for e in rs} for s, rs in by_seller.items()}
    all_micro = sum(micro.values())
    when = dated(dates)

    # 1 where the money went
    ranked = sorted(by_seller, key=lambda s: (-micro[s], s))
    top = []
    for i, s in enumerate(ranked[:TOP], 1):
        rs = by_seller[s]
        top.append(dict(who(s), rank=i, share_pct=pct(micro[s], all_micro), payers=len(payers[s]),
                        days_paid=len({e.date for e in rs}),
                        **tot(rs, "money.top_sellers[%d]" % (i - 1), "the money to seller %d" % i),
                        largest_payer=top_payer(rs, micro[s], robots)))
    lead_rows = [e for s in ranked[:LEAD] for e in by_seller[s]]
    lead = dict(sellers=min(LEAD, len(ranked)), share_pct=pct(sum(micro[s] for s in ranked[:LEAD]), all_micro),
                **tot(lead_rows, "money.lead", "the money to the top %d sellers" % LEAD))
    money = {"dates": when,
             "total": dict(tot(rows, "money.total", "all x402 money on Base"), sellers_paid=len(by_seller),
                           payer_wallets=len(sellers_of)),
             "lead": lead, "top_sellers": top,
             "top_sellers_over_half_one_payer": sum(1 for x in top if x["largest_payer"]["over_half"])}

    # 2 concentration, over the window and on its last day
    def spread(rs_by_seller):
        counts = {s: len({e.payer for e in rs}) for s, rs in rs_by_seller.items()}
        one = [s for s, c in counts.items() if c == 1]
        return {"sellers_paid": len(counts), "one_payer": len(one), "one_payer_pct": pct(len(one), len(counts)),
                "one_payer_is_robot": sum(1 for s in one if rs_by_seller[s][0].payer in robots),
                "median_payers": num(statistics.median(counts.values())) if counts else None,
                "payers_buckets": [{"payers": name, "sellers": sum(1 for c in counts.values() if c >= lo and (hi is None or c <= hi))}
                                   for lo, hi, name in BUCKETS]}

    last = collections.defaultdict(list)
    for e in rows:
        if dates and e.date == dates[-1]:
            last[e.payee].append(e)
    concentration = dict({"dates": when}, **spread(by_seller))
    concentration["last_day"] = dict({"date": dates[-1] if dates else None}, **spread(last))

    # robot wallets
    robot_rows = [e for e in rows if e.payer in robots]
    reached = {e.payee for e in robot_rows}
    robot = dict({"dates": when, "min_sellers": ROBOT, "wallets": len(robots)},
                 **tot(robot_rows, "robots", "the money from robot wallets"))
    robot.update(share_pct=pct(sum(e.micro for e in robot_rows), all_micro), sellers_reached=len(reached),
                 sellers_reached_pct=pct(len(reached), len(by_seller)),
                 top=[{"wallet": w, "sellers_paid": len(sellers_of[w]),
                       "usdc": usd(sum(e.micro for e in robot_rows if e.payer == w)),
                       "payments": sum(e.n for e in robot_rows if e.payer == w)}
                      for w in sorted(robots, key=lambda w: (-len(sellers_of[w]), w))[:5]])

    growth = grow(dates, rows, robots, who, tot)
    solana = sol_part(sol, tot) if sol else None

    missing = [d for d in span(start, end) if d not in dates]
    b = {"kind": KIND, "version": VERSION, "title": TITLE,
         "window": {"from": start, "to": end, "days": dates, "days_missing": missing,
                    "solana_days": [d for d, _ in sol]},
         "chains": ["Base"] + (["Solana"] if sol else []),
         "page": "%s/brief/%s/" % (site.rstrip("/"), slug(start, end)),
         "json": "%s/brief/%s/brief.json" % (site.rstrip("/"), slug(start, end)),
         "money": money, "concentration": concentration, "robots": robot, "growth": growth, "solana": solana,
         "over_half_totals": tot.over_half}
    b["what_it_means"] = meanings(b)
    b["method"] = method(files, off_map, bad)
    b["caveats"] = caveats(b)
    b["problems"] = problems
    return b


def grow(dates, rows, robots, who, tot):
    """Sellers whose paying wallets grew from the first half to the second, robots left out:
    from many wallets (two or more more) or from one. A seller that grew only when robot
    wallets are counted is a robot wave, counted apart."""
    h = len(dates) // 2
    if not h:
        return {"available": False, "why": "the window needs 2 or more days to have halves", "halves": None}
    first, second = dates[:h], dates[len(dates) - h:]
    F, S = set(first), set(second)
    rf = [e for e in rows if e.date in F]
    rs = [e for e in rows if e.date in S]
    pace = {}
    for key, half, part in (("first", first, rf), ("second", second, rs)):
        t = tot(part, "growth.market.%s" % key, "the money in the %s half" % key)
        pace[key] = dict({"dates": dated(half)}, **t)
        pace[key]["usdc_per_day"] = usd(round(sum(e.micro for e in part) / h))
        pace[key]["payments_per_day"] = num(t["payments"] / h)
    pace["usdc_per_day_change_pct"] = change(pace["first"]["usdc_per_day"], pace["second"]["usdc_per_day"])
    pace["payments_per_day_change_pct"] = change(pace["first"]["payments_per_day"], pace["second"]["payments_per_day"])

    halves = {"first": collections.defaultdict(list), "second": collections.defaultdict(list)}
    for e in rf:
        halves["first"][e.payee].append(e)
    for e in rs:
        halves["second"][e.payee].append(e)
    many, one, wave = [], [], 0
    for s in sorted(set(halves["first"]) | set(halves["second"])):
        a_all = {e.payer for e in halves["first"].get(s, [])}
        b_all = {e.payer for e in halves["second"].get(s, [])}
        a, b = len(a_all - robots), len(b_all - robots)
        if b > a:
            (many if b - a >= 2 else one).append((s, a_all, b_all, a, b))
        elif len(b_all) > len(a_all):
            wave += 1

    def row(s, a_all, b_all, a, b, where):
        f_rows, s_rows = halves["first"].get(s, []), halves["second"].get(s, [])
        s_micro = sum(e.micro for e in s_rows)
        return dict(who(s), gain=b - a, new_wallets=len((b_all - a_all) - robots),
                    first=dict({"payers": a}, **tot(f_rows, where + ".first", "a growing seller's first half")),
                    second=dict({"payers": b}, **tot(s_rows, where + ".second", "a growing seller's second half"),
                                largest_payer=top_payer(s_rows, s_micro, robots)))

    def s_micro(x):
        return sum(e.micro for e in halves["second"].get(x[0], []))
    many.sort(key=lambda x: (-(x[4] - x[3]), -s_micro(x), x[0]))
    one.sort(key=lambda x: (-s_micro(x), x[0]))
    many_rows = [row(*x, where="growth.many_wallets[%d]" % i) for i, x in enumerate(many[:TOP])]
    one_rows = [row(*x, where="growth.one_wallet[%d]" % i) for i, x in enumerate(one[:TOP])]
    return {"available": True, "halves": {"first": first, "second": second}, "robots_left_out": len(robots),
            "market": pace, "grew": len(many) + len(one), "many_wallets_count": len(many), "one_wallet_count": len(one),
            "robot_wave_count": wave,
            "many_wallets_money_mostly_one_wallet": sum(1 for x in many_rows if x["second"]["largest_payer"]["over_half"]),
            "many_wallets": many_rows, "one_wallet": one_rows}


def sol_part(sol, tot):
    """Solana: every payment a known processor settled, listed payee or not, by day and in all."""
    names = host_names(sol)
    rows, bad = [], 0
    for day, d in sol:
        r, _off, b = edges_of(d, day, False)
        rows += r
        bad += b
    days = []
    for day, _d in sol:
        part = [e for e in rows if e.date == day]
        days.append(dict({"date": day}, **tot(part, "solana.days[%s]" % day, "Solana money on %s" % atlas_style.short_date(day)),
                         payers=len({e.payer for e in part}), payees=len({e.payee for e in part})))
    by = collections.defaultdict(list)
    for e in rows:
        by[e.payee].append(e)
    m = {w: sum(e.micro for e in rs) for w, rs in by.items()}
    all_micro = sum(m.values())
    top = []
    for i, w in enumerate(sorted(by, key=lambda w: (-m[w], w))[:TOP]):
        hs = names.get(w, [])
        top.append(dict({"wallet": w, "listed": w in names, "hosts": [label(h) for h in hs[:HOSTS]], "hosts_total": len(hs),
                         "share_pct": pct(m[w], all_micro), "payers": len({e.payer for e in by[w]}),
                         "days_paid": len({e.date for e in by[w]})},
                        **tot(by[w], "solana.top_payees[%d]" % i, "the money to Solana payee %d" % (i + 1)),
                        largest_payer=top_payer(by[w], m[w])))
    sd = [d for d, _ in sol]
    return {"dates": dated(sd), "days": days,
            "total": dict(tot(rows, "solana.total", "all Solana money"), payers=len({e.payer for e in rows}),
                          payees=len(by)),
            "top_payees": top, "left_out_rows": bad}


# ── what it means: fixed rules over the numbers ──────────────────────────

def money(x, whole=False):
    if x is None:
        return "—"
    if 0 < x < 0.005:
        return "under $0.01"
    return ("${:,.0f}" if whole else "${:,.2f}").format(x)


def pct_words(p):
    if p is None:
        return "—"
    if 0 < p < 0.1:
        return "under 0.1%"
    return ("%d%%" % p) if p == int(p) else ("%.1f%%" % p)


def signed(p):
    if p is None:
        return "—"
    return ("+" if p > 0 else "−" if p < 0 else "") + pct_words(abs(p))


def range_words(a, b):
    if not a or not b:
        return "—"
    if a == b:
        return atlas_style.long_date(a)
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, _db = (int(x) for x in b.split("-"))
    if (ya, ma) == (yb, mb):
        return "%d to %s" % (da, atlas_style.long_date(b))
    if ya == yb:
        return "%d %s to %s" % (da, atlas_style.MONTHS[ma - 1], atlas_style.long_date(b))
    return "%s to %s" % (atlas_style.long_date(a), atlas_style.long_date(b))


def short_range(a, b):
    """'2026-10-03', '2026-10-06' -> '3–6 Oct 2026': the short form, for a sentence that names two ranges."""
    if a == b:
        return atlas_style.short_date(a)
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, db = (int(x) for x in b.split("-"))
    mon = lambda m: atlas_style.MONTHS[m - 1][:3]
    if (ya, ma) == (yb, mb):
        return "%d–%d %s %d" % (da, db, mon(mb), yb)
    if ya == yb:
        return "%d %s–%d %s %d" % (da, mon(ma), db, mon(mb), yb)
    return "%s–%s" % (atlas_style.short_date(a), atlas_style.short_date(b))


# the totals a reader meets first; the rest sit in the rows of a table
HEADLINE = ("money.total", "money.lead", "robots", "growth.market.", "solana.total")   # a Solana day has its own line


def seller_words(x):
    return x["hosts"][0] if x.get("hosts") else whales.short(x["wallet"])


def solana_rules(s, say):
    """The Solana rules, which hold whether or not Base was quiet."""
    if s:
        for d in s["days"]:
            le = d["largest_edge"]
            if le and le["over_half"]:
                say("solana_one_edge", "On Solana, one edge (%s in %s) was %s of %s's %s. Without it, %s."
                    % (money(le["usdc"]), payments_words(le["payments"]), pct_words(le["share_pct"]),
                       atlas_style.short_date(d["date"]), money(d["usdc"]), money(le["usdc_without_it"])),
                    date=d["date"], usdc=d["usdc"], edge_usdc=le["usdc"], usdc_without_it=le["usdc_without_it"])
        t = s["total"]
        say("solana_total", "On Solana, %s payments and %s from %s, to %s payees."
            % ("{:,}".format(t["payments"]), money(t["usdc"]), range_words(s["dates"]["from"], s["dates"]["to"]),
               "{:,}".format(t["payees"])),
            payments=t["payments"], usdc=t["usdc"], payees=t["payees"])


COUNT_WORDS = {1: "one", 2: "two", 3: "three"}


def top_words(m):
    """"three" when three sellers led, "two" or "one" in a window with that few paid sellers."""
    return COUNT_WORDS.get(m["lead"]["sellers"], str(m["lead"]["sellers"]))


def meanings(b):
    """A short list, each item made by one fixed rule from the numbers, with the numbers it used."""
    out = []

    def say(rule, text, **numbers):
        out.append({"rule": rule, "says": text, "numbers": numbers})

    m, c, g, r, s = b["money"], b["concentration"], b["growth"], b["robots"], b["solana"]
    if not m["total"]["payments"]:
        say("quiet", "No x402 payment reached a listed seller on Base in these days.")
        solana_rules(s, say)
        return out
    p = m["lead"]["share_pct"]
    if p > 50:
        say("money_in_few_hands", "%s took %s of the money. Most of any total here is theirs."
            % (top_words(m).capitalize() + (" seller" if m["lead"]["sellers"] == 1 else " sellers"), pct_words(p)),
            lead_share_pct=p)
    else:
        say("money_in_few_hands", "The top %s took %s of the money; the rest is spread wider."
            % (top_words(m) + (" seller" if m["lead"]["sellers"] == 1 else " sellers"), pct_words(p)),
            lead_share_pct=p)
    t = m["top_sellers"][0]
    lp = t["largest_payer"]
    k, n = m["top_sellers_over_half_one_payer"], len(m["top_sellers"])
    if lp["over_half"]:
        text = ("The biggest seller, %s, took %s of its %s from one wallet. Its income rests on one payer."
                % (seller_words(t), pct_words(lp["share_pct"]), money(t["usdc"])))
    else:
        text = ("The biggest seller, %s, took %s of its %s from its largest payer: no one wallet carries it."
                % (seller_words(t), pct_words(lp["share_pct"]), money(t["usdc"])))
    say("top_seller_payer", text + " %d of the top %d sellers took more than half their money from one wallet." % (k, n),
        usdc=t["usdc"], largest_payer_share_pct=lp["share_pct"], top_sellers_over_half_one_payer=k, top_sellers=n)
    ld = c["last_day"]
    if ld["sellers_paid"]:
        lead_in = "Most sellers have one paying wallet: on" if 2 * ld["one_payer"] > ld["sellers_paid"] else "On"
        say("one_payer_sellers", "%s %s, %s of the %s sellers paid had just one."
            % (lead_in, atlas_style.short_date(ld["date"]), "{:,}".format(ld["one_payer"]), "{:,}".format(ld["sellers_paid"])),
            date=ld["date"], one_payer=ld["one_payer"], sellers_paid=ld["sellers_paid"])
    if g["available"]:
        h1, h2 = g["halves"]["first"], g["halves"]["second"]
        text = ("From %s to %s, %s seller%s gained two or more paying wallets and %s gained exactly one; %s more grew only "
                "by robot wallets. Count the wallets behind a growth line before you trust it."
                % (short_range(h1[0], h1[-1]), short_range(h2[0], h2[-1]), "{:,}".format(g["many_wallets_count"]),
                   "s" if g["many_wallets_count"] != 1 else "",
                   "{:,}".format(g["one_wallet_count"]), "{:,}".format(g["robot_wave_count"])))
        if g["many_wallets_money_mostly_one_wallet"]:
            text += (" In %d of the %d shown that gained many, one wallet still sent more than half the second half's money."
                     % (g["many_wallets_money_mostly_one_wallet"], len(g["many_wallets"])))
        say("growth_wallets", text, many_wallets=g["many_wallets_count"], one_wallet=g["one_wallet_count"],
            robot_wave=g["robot_wave_count"], many_shown_money_mostly_one_wallet=g["many_wallets_money_mostly_one_wallet"])
        mk = g["market"]
        ch = mk["usdc_per_day_change_pct"]
        say("pace", "Money a day on Base went from %s (%s) to %s (%s): %s."
            % (money(mk["first"]["usdc_per_day"]), short_range(h1[0], h1[-1]), money(mk["second"]["usdc_per_day"]),
               short_range(h2[0], h2[-1]), signed(ch)),
            usdc_per_day_first=mk["first"]["usdc_per_day"], usdc_per_day_second=mk["second"]["usdc_per_day"],
            change_pct=ch)
    if r["wallets"]:
        text = ("%d robot wallet%s (each paid %d or more sellers) sent %s of the money and paid %s of the %s sellers."
                % (r["wallets"], "s" if r["wallets"] != 1 else "", ROBOT, pct_words(r["share_pct"]),
                   "{:,}".format(r["sellers_reached"]), "{:,}".format(m["total"]["sellers_paid"])))
        if (r["share_pct"] or 0) < (r["sellers_reached_pct"] or 0):
            text += " They make the market look more connected than its money is."
        say("robots", text, wallets=r["wallets"], share_pct=r["share_pct"], sellers_reached=r["sellers_reached"])
    if b["over_half_totals"]:
        head = [x for x in b["over_half_totals"] if x["where"].startswith(HEADLINE)]
        rows = sum(1 for x in b["over_half_totals"] if "[" in x["where"] and not x["where"].startswith("solana.days["))
        parts = []
        if head:
            whats = [x["what"] for x in head]
            parts.append("One edge is more than half of %s." % (whats[0] if len(whats) == 1 else
                                                                 ", ".join(whats[:-1]) + " and " + whats[-1]))
        if rows:
            parts.append("The same holds for %d seller total%s in the tables." % (rows, "s" if rows != 1 else ""))
        if parts:
            say("one_edge_totals", " ".join(parts) + " Each is marked beside the total, with the total without it.",
                headline=[x["where"] for x in head], in_tables=rows)
    solana_rules(s, say)
    return out


def payments_words(n):
    return "%s payment%s" % ("{:,}".format(n), "s" if n != 1 else "")


def method(files, off_map, bad):
    return {
        "source": "the daily flow files the Atlas publishes, read from the chain: flows-<date>.json for Base, "
                  "flows-sol-<date>.json for Solana",
        "files": files,
        "x402_only": "a payment counts when n_x402 > 0: a facilitator settled a signed authorization; USDC that "
                     "reached a wallet some other way is left out",
        "seller": "a seller is its payTo wallet; on Base only payments to a wallet in that day's sellers map count, "
                  "and it is named by the hosts the registry lists on it, the most particular first",
        "base_left_out": {"edges_to_unlisted_wallets": off_map, "edges_not_in_shape": bad},
        "solana_payees": "every payment a known processor settled, whoever the payee is; a payee the registry "
                         "does not list is still counted and shown as its wallet",
        "robot": "a wallet that paid %d or more different sellers on Base in the window" % ROBOT,
        "halves": "the window's days split in two; with an odd number of days the middle one is in neither",
        "growth": "a seller grew when its paying wallets, robots left out, were more in the second half than in the "
                  "first: from many wallets when two or more more, from one wallet when exactly one more. A seller "
                  "that grew only when robot wallets are counted is a robot wave",
        "largest_edge": "an edge is one wallet paying one wallet on one day, one row of a daily file. Every total "
                        "carries its largest edge; over_half marks one that is more than half of the total",
        "money": "USDC summed in millionths, so totals are exact; a share short of the whole never reads as 100%",
        "ties": "rows with equal money are ordered by wallet, so the same files give the same brief",
        "model_calls": 0,
    }


def caveats(b):
    out = ["A wallet is not a person. Nothing here says who holds or runs a wallet.",
           "x402 only: USDC that reached the same wallets some other way is not counted.",
           "Base unless marked Solana. The two chains are counted differently: Base counts payments to sellers the "
           "public registry lists; Solana counts every payment a known processor settled.",
           "Hosts are labels the public registry lists on a wallet. A few show \"…\" in place of one word; the "
           "wallet is exact and is the key."]
    if b["window"]["days_missing"]:
        out.append("No Base file for %s: those days are not in any number here." % ", ".join(b["window"]["days_missing"]))
    return out


# ── the page ─────────────────────────────────────────────────────────────

esc = atlas_style.esc


def wallet_html(w):
    return '<a href="%s" rel="nofollow"><code title="%s">%s</code></a>' % (esc(whales.explorer(w)), esc(w), esc(whales.short(w)))


def seller_html(x):
    hs = x.get("hosts") or []
    if not hs:
        return wallet_html(x["wallet"])
    more = x.get("hosts_total", len(hs)) - 1
    return '%s%s<br>%s' % (esc(hs[0]), ' <span class="muted">+%d host%s</span>' % (more, "s" if more != 1 else "") if more > 0 else "",
                           wallet_html(x["wallet"]))


def edge_note(t, what="this total"):
    """Beside a total: when one edge is more than half of it, say so, and what is left without it."""
    le = (t or {}).get("largest_edge")
    if not le or not le["over_half"]:
        return ""
    return ('<span class="edge"><span class="pill concentrated" style="display:inline-block">one edge</span> %s of %s: %s paid %s %s in %s on %s. '
            'Without it, %s.</span>'
            % (pct_words(le["share_pct"]), esc(what), wallet_html(le["from"]), wallet_html(le["to"]), money(le["usdc"]),
               payments_words(le["payments"]), esc(atlas_style.short_date(le["date"])), money(le["usdc_without_it"])))


def tile(big, small, note=""):
    return '<div class="tile"><b>%s</b><span>%s</span>%s</div>' % (big, small, note and "<span>%s</span>" % note)


def table(head, rows, ncols_num=(), narrow=False):
    th = "".join('<th%s>%s</th>' % (' class="n"' if i in ncols_num else "", esc(h)) for i, h in enumerate(head))
    return ('<div class="tw"%s><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % (' style="max-width:560px"' if narrow else "", th, "".join(rows)))


def note_row(note, cols):
    return '<tr><td colspan="%d" class="muted">%s</td></tr>' % (cols, note) if note else ""


def page(b, site=SITE):
    w, m, c, r, g, s = b["window"], b["money"], b["concentration"], b["robots"], b["growth"], b["solana"]
    days = w["days"]
    rng = range_words(days[0], days[-1]) if days else range_words(w["from"], w["to"])
    t = m["total"]
    chains = " and ".join(b["chains"])
    title = "%s · %s · %s" % (TITLE, rng, market.BRAND)
    if not t["payments"]:
        lede = "No x402 payment reached a listed seller on Base from %s." % rng
    elif m["lead"]["sellers"] >= t["sellers_paid"]:
        lede = ("%s in x402 payments reached %s seller%s on Base from %s."
                % (money(t["usdc"], whole=True), "{:,}".format(t["sellers_paid"]), "" if t["sellers_paid"] == 1 else "s", rng))
    else:
        lede = ("%s in x402 payments reached %s sellers on Base from %s. %s of them took %s."
                % (money(t["usdc"], whole=True), "{:,}".format(t["sellers_paid"]), rng, top_words(m).capitalize(),
                   pct_words(m["lead"]["share_pct"])))
    ctx = {"title": esc(title), "desc": esc(lede), "canon": esc(b["page"]), "css": esc(site) + "/atlas.css", "root": esc(site)}
    p = [atlas_style.HEAD % ctx, '<main id="main">',
         '<p class="crumbs"><a href="%s/brief/">Brief</a> / %s</p>' % (esc(site), esc(rng)),
         '<span class="eyebrow">%s · %s · %s</span>' % (esc(TITLE), esc(rng), esc(chains)),
         "<h1>Where the money in x402 payments went</h1>",
         '<p class="oneline">%s</p>' % esc(lede),
         '<p class="muted">Every number below is computed from the daily files of %s, read from the chain. For agents: '
         '<a href="brief.json">brief.json</a> holds the same numbers with field names, the method and the caveats.</p>'
         % esc(rng)]
    ld = c["last_day"]
    tiles = [tile(money(t["usdc"], whole=True), "x402 USDC to %s sellers on Base, %s" % ("{:,}".format(t["sellers_paid"]), esc(rng)),
                  edge_note(t, "this total")),
             tile(pct_words(m["lead"]["share_pct"]), "to the top %s seller%s, %s" % (top_words(m), "" if m["lead"]["sellers"] == 1 else "s", esc(rng)), edge_note(m["lead"], "their total")),
             tile("%s of %s" % ("{:,}".format(ld["one_payer"]), "{:,}".format(ld["sellers_paid"])),
                  "sellers paid on %s had one paying wallet" % esc(atlas_style.short_date(ld["date"])))]
    if g["available"]:
        mk = g["market"]
        tiles.append(tile(signed(mk["usdc_per_day_change_pct"]), "money a day, %s (%s) against %s (%s)"
                          % (esc(short_range(g["halves"]["second"][0], g["halves"]["second"][-1])),
                             money(mk["second"]["usdc_per_day"], whole=True),
                             esc(short_range(g["halves"]["first"][0], g["halves"]["first"][-1])),
                             money(mk["first"]["usdc_per_day"], whole=True)), edge_note(mk["second"], "the second half")))
    p.append('<div class="tiles">%s</div>' % "".join(tiles))

    # 1
    p.append("<h2>1. Where the money went</h2>")
    p.append('<p class="dateline">%s · Base · x402 only</p>' % esc(rng))
    p.append("<p>%s in %s reached %s sellers from %s paying wallets. %s</p>"
             % (money(t["usdc"]), payments_words(t["payments"]), "{:,}".format(t["sellers_paid"]),
                "{:,}".format(t["payer_wallets"]), edge_note(t, "this total")))
    p.append("<p>The top %s took %s (%s). %s</p>" % (top_words(m), pct_words(m["lead"]["share_pct"]), money(m["lead"]["usdc"]),
                                                         edge_note(m["lead"], "their total")))
    rows = []
    for x in m["top_sellers"]:
        lp = x["largest_payer"]
        rows.append('<tr><td class="n">%d</td><td class="h">%s</td><td class="n">%s</td><td class="n">%s</td>'
                    '<td class="n">%s</td><td class="n">%s</td><td>%s from %s%s</td></tr>'
                    % (x["rank"], seller_html(x), money(x["usdc"]), pct_words(x["share_pct"]), "{:,}".format(x["payments"]),
                       "{:,}".format(x["payers"]), pct_words(lp["share_pct"]), wallet_html(lp["wallet"]),
                       ' <span class="pill concentrated">over half</span>' if lp["over_half"] else ""))
        rows.append(note_row(edge_note(x, "its total"), 7))
    p.append(table(["#", "Seller", "USDC", "Share", "Payments", "Payers", "Largest payer's share"], rows, (0, 2, 3, 4, 5)))
    p.append('<p class="muted">Share: of all x402 money on Base, %s. Largest payer: the one wallet that sent the seller the most '
             'in the window, and its share of the seller\'s money.</p>' % esc(rng))

    # 2
    p.append("<h2>2. Concentration</h2>")
    p.append('<p class="dateline">%s · Base</p>' % esc(rng))
    p.append("<p>%s of the %s sellers paid had exactly one paying wallet (%s); %s of those were paid only by a robot wallet. "
             "The median seller had %s paying wallet%s.</p>"
             % ("{:,}".format(c["one_payer"]), "{:,}".format(c["sellers_paid"]), pct_words(c["one_payer_pct"]),
                "{:,}".format(c["one_payer_is_robot"]), "—" if c["median_payers"] is None else c["median_payers"],
                "s" if c["median_payers"] != 1 else ""))
    p.append("<p>On %s alone: %s of the %s sellers paid had one paying wallet; the median seller had %s.</p>"
             % (esc(atlas_style.long_date(ld["date"])), "{:,}".format(ld["one_payer"]), "{:,}".format(ld["sellers_paid"]),
                "—" if ld["median_payers"] is None else ld["median_payers"]))
    p.append(table(["Paying wallets", "Sellers, %s" % rng], ['<tr><td>%s</td><td class="n">%s</td></tr>'
                                                             % (esc(x["payers"]), "{:,}".format(x["sellers"])) for x in c["payers_buckets"]],
                   (1,), narrow=True))
    p.append("<h3 style=\"margin-top:28px\">Robot wallets</h3>")
    p.append("<p>%d wallet%s paid %d or more different sellers %s. Together they sent %s (%s of the money) and paid %s of the "
             "%s sellers (%s). %s</p>"
             % (r["wallets"], "s" if r["wallets"] != 1 else "", ROBOT, esc(rng), money(r["usdc"]), pct_words(r["share_pct"]),
                "{:,}".format(r["sellers_reached"]), "{:,}".format(t["sellers_paid"]), pct_words(r["sellers_reached_pct"]),
                edge_note(r, "their total")))

    # 3
    p.append("<h2>3. Growth</h2>")
    if not g["available"]:
        p.append("<p>%s.</p>" % esc(g["why"].capitalize()))
    else:
        h1, h2 = g["halves"]["first"], g["halves"]["second"]
        w1, w2 = range_words(h1[0], h1[-1]), range_words(h2[0], h2[-1])
        mk = g["market"]
        p.append('<p class="dateline">%s against %s · Base</p>' % (esc(w2), esc(w1)))
        p.append("<p>Money a day: %s from %s, %s from %s (%s). Payments a day: %s, then %s. %s %s</p>"
                 % (money(mk["first"]["usdc_per_day"]), esc(w1), money(mk["second"]["usdc_per_day"]), esc(w2),
                    signed(mk["usdc_per_day_change_pct"]), "{:,}".format(mk["first"]["payments_per_day"]),
                    "{:,}".format(mk["second"]["payments_per_day"]), edge_note(mk["first"], "the first half's money"),
                    edge_note(mk["second"], "the second half's money")))
        p.append("<p>%s sellers had more paying wallets in the second half than in the first, robot wallets left out: %s from "
                 "many wallets (two or more more) and %s from one wallet (exactly one more). %s more grew only by robot wallets.</p>"
                 % ("{:,}".format(g["grew"]), "{:,}".format(g["many_wallets_count"]), "{:,}".format(g["one_wallet_count"]),
                    "{:,}".format(g["robot_wave_count"])))
        for key, head in (("many_wallets", "From many wallets"), ("one_wallet", "From one wallet")):
            p.append('<h3 style="margin-top:28px">%s</h3>' % head)
            rows = []
            for x in g[key]:
                lp = x["second"]["largest_payer"]
                rows.append('<tr><td class="h">%s</td><td class="n">%s → %s</td><td class="n">%s</td><td class="n">%s</td>'
                            '<td>%s from %s%s</td></tr>'
                            % (seller_html(x), x["first"]["payers"], x["second"]["payers"], money(x["first"]["usdc"]),
                               money(x["second"]["usdc"]), pct_words(lp["share_pct"]), wallet_html(lp["wallet"]),
                               ' <span class="pill concentrated">over half</span>' if lp["over_half"] else ""))
                rows.append(note_row(" ".join(n for n in (edge_note(x["first"], "its first half"),
                                                           edge_note(x["second"], "its second half")) if n), 5))
            if rows:
                p.append(table(["Seller", "Payers", "USDC, %s" % w1, "USDC, %s" % w2, "Largest payer, %s" % w2], rows, (1, 2, 3)))
            else:
                p.append('<p class="muted">None.</p>')

    # 4
    p.append("<h2>4. Solana</h2>")
    if not s:
        p.append("<p class=\"muted\">No Solana file for these days.</p>")
    else:
        sr = range_words(s["dates"]["from"], s["dates"]["to"])
        st = s["total"]
        p.append('<p class="dateline">%s · Solana</p>' % esc(sr))
        p.append("<p>Every payment a known processor settled, whoever the payee is (on Base, listed sellers only): %s and %s "
                 "from %s paying wallets to %s payees. %s</p>"
                 % (payments_words(st["payments"]), money(st["usdc"]), "{:,}".format(st["payers"]), "{:,}".format(st["payees"]),
                    edge_note(st, "this total")))
        rows = []
        for d in s["days"]:
            rows.append('<tr><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
                        % (esc(atlas_style.short_date(d["date"])), money(d["usdc"]), "{:,}".format(d["payments"]),
                           "{:,}".format(d["payers"]), "{:,}".format(d["payees"])))
            rows.append(note_row(edge_note(d, "the day's total"), 5))
        p.append(table(["Day", "USDC", "Payments", "Paying wallets", "Payees"], rows, (1, 2, 3, 4)))
        rows = []
        for x in s["top_payees"]:
            lp = x["largest_payer"]
            rows.append('<tr><td class="h">%s%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                        '<td class="n">%s</td><td>%s from %s</td></tr>'
                        % (seller_html(x), "" if x["listed"] else ' <span class="muted">not listed</span>', money(x["usdc"]),
                           pct_words(x["share_pct"]), "{:,}".format(x["payments"]), "{:,}".format(x["payers"]),
                           pct_words(lp["share_pct"]), wallet_html(lp["wallet"])))
            rows.append(note_row(edge_note(x, "its total"), 6))
        p.append('<h3 style="margin-top:28px">Top payees</h3>')
        p.append(table(["Payee", "USDC", "Share", "Payments", "Payers", "Largest payer's share"], rows, (1, 2, 3, 4)))

    # 5
    p.append("<h2>5. What it means</h2>")
    p.append('<p class="muted">Each line is made by one fixed rule from the numbers above; brief.json names the rule.</p>')
    p.append('<ul class="changes">%s</ul>' % "".join("<li>%s</li>" % esc(x["says"]) for x in b["what_it_means"]))

    p.append("<h2>Method</h2>")
    me = b["method"]
    p.append('<ul class="cav">%s</ul>' % "".join("<li>%s</li>" % esc(me[k][0].upper() + me[k][1:] + ".")
                                                 for k in ("source", "x402_only", "seller", "solana_payees", "robot",
                                                           "halves", "growth", "largest_edge", "money")))
    p.append('<p class="muted">Files read: %s.</p>' % esc(", ".join(f["name"] for f in me["files"])))
    p.append("<h2>Caveats</h2>")
    p.append('<ul class="cav">%s</ul>' % "".join("<li>%s</li>" % esc(x) for x in b["caveats"]))
    p.append("</main>")
    stamp = '<p class="mono">Built from the daily files of %s · no number in it is written by hand.</p>' % esc(rng)
    p.append(atlas_style.footer(esc(site), esc(atlas_style.ISSUES), esc(w["to"]), free=True, stamp=stamp))
    return "\n".join(p)


# ── writing ──────────────────────────────────────────────────────────────

def slug(start, end):
    return "%s-to-%s" % (start, end)


def dumps(b):
    return json.dumps(b, indent=1, ensure_ascii=False) + "\n"


def write(b, html, out):
    """Write the brief's folder, and latest.json unless out already holds a newer brief.
    Returns (folder, latest_written)."""
    w = b["window"]
    folder = os.path.join(out, slug(w["from"], w["to"]))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(os.path.join(folder, "brief.json"), "w", encoding="utf-8") as f:
        f.write(dumps(b))
    latest = os.path.join(out, "latest.json")
    try:
        with open(latest, encoding="utf-8") as f:
            cur = json.load(f)["window"]
        newer = (cur["to"], cur["from"]) > (w["to"], w["from"])
    except (OSError, ValueError, KeyError, TypeError):
        newer = False
    if not newer:
        with open(latest, "w", encoding="utf-8") as f:
            f.write(dumps(b))
    return folder, not newer


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flows-dir", required=True, help="a folder of flows-<date>.json and flows-sol-<date>.json")
    ap.add_argument("--from", dest="start", required=True, type=day_arg, help="the first day, e.g. 2026-10-03")
    ap.add_argument("--to", dest="end", required=True, type=day_arg, help="the last day, e.g. 2026-10-10")
    ap.add_argument("--out", default="brief", help="where brief/<from>-to-<to>/ is written (default: brief)")
    ap.add_argument("--site", default=SITE, help="where the Atlas is served, for links (default: %s)" % SITE)
    a = ap.parse_args(argv)
    if a.end < a.start:
        ap.error("--to is before --from")
    if len(span(a.start, a.end)) > MAX_DAYS:
        ap.error("a brief covers %d days at most" % MAX_DAYS)
    b = build(a.flows_dir, a.start, a.end, a.site)
    if not b["window"]["days"]:
        sys.exit("brief: no Base flows-<date>.json in %s from %s to %s%s" % (
            a.flows_dir, a.start, a.end, "; " + "; ".join(b["problems"]) if b["problems"] else ""))
    folder, latest = write(b, page(b, a.site), a.out)
    t = b["money"]["total"]
    print("brief %s to %s: %s to %s sellers, top three %s, %d Base day%s%s" % (
        a.start, a.end, money(t["usdc"]), "{:,}".format(t["sellers_paid"]), pct_words(b["money"]["lead"]["share_pct"]),
        len(b["window"]["days"]), "s" if len(b["window"]["days"]) != 1 else "",
        ", %d Solana" % len(b["window"]["solana_days"]) if b["window"]["solana_days"] else ""))
    for x in b["what_it_means"]:
        print("  - " + x["says"])
    for x in b["problems"]:
        print("  left out: " + x, file=sys.stderr)
    print("wrote %s/index.html and brief.json%s" % (folder, "; and latest.json" if latest else ""))


if __name__ == "__main__":
    main()
