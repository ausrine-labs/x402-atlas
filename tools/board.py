#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 5c193d9). Edit it there, not here.
"""board.py — The Board: every x402 seller on Base ranked by the payer wallets that come back, not by money.

A directory that ranks by payments rewards loops and single payers: one wallet paying
itself through a seller, or one big payer, puts a seller on top. The Board answers the
buyer's question instead: who do other buyers actually come back to, for this job?

    board.py --flows-dir flows [--store radar-store] [--out site] [--site https://...]

It reads the newest 7 days of flows-<date>.json (Base, the daily files chain_flows.py
writes and the Atlas publishes) and the newest registry snapshot (radar.py), and writes

    <out>/board/index.html    the Board, in the Atlas look
    <out>/board/board.json    the same numbers, for agents

The rules are the Atlas's own (relationships.py, brief.py). A seller is its payTo wallet,
named by the hosts the registry lists on it. Only x402 payments count (n_x402 > 0), and only
to a wallet in that day's sellers map. A robot wallet paid 20 or more different sellers in
the window: it is left out of customer counts, and its money still counts.

Per seller wallet, over the 7 days:

    customers        distinct payer wallets, robots left out
    returning        customers that paid it on 2 or more days
    top payer share  the share of its x402 USDC from its largest payer wallet
    daily            its x402 USDC on each of the 7 days
    shape            flat:       every day within 10% of the median, and the median above $1
                     spike:      one day over half the total
                     gone quiet: the last two days each under 5% of the busiest day,
                                 and an earlier day was $20 or more
                     ramping:    each of the last 3 days higher than the day before
                     uneven:     anything else
                     (the first that fits, in that order; none when a day's file is missing)

Ranked by returning customers, then customers. A seller whose top payer is over half its
money is shown, marked "one payer is most of it", and ranked after every seller that is
not. A seller with no customer (only robots paid it) is left off. Grouped by market.py's
category of what the registry says it sells.

A wallet is not a person, and nothing here says who holds or runs one. No model calls;
standard library only.
"""

import argparse
import collections
import datetime
import json
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import atlas_style  # noqa: E402
import brief  # noqa: E402
import market  # noqa: E402
import radar  # noqa: E402
import relationships  # noqa: E402
import tiers  # noqa: E402

KIND = "x402-board"
VERSION = 1
TITLE = "The Board"
SITE = "https://atlas.infoharmoni.com"
DAYS = 7
ROBOT = brief.ROBOT          # 20: a wallet that paid this many different sellers or more is a robot
TOP = 50                     # rows in the overall list
TOP_CAT = 10                 # rows in each category
MICRO = brief.MICRO
ONE_PAYER = "one payer is most of it"

MEANS = ("x402 payments on Base, the newest %d daily pulls. A customer is a wallet that paid the seller's "
         "payTo wallet; a robot wallet (one that paid %d or more different sellers in the window) is left out of "
         "customer counts, and its money still counts. Returning means paid on 2 or more days. Ranked by returning "
         "customers, then customers; a seller whose largest payer sent over half its money is ranked after every "
         "seller that is not. A wallet is not a person, and nothing here says who holds or runs one." % (DAYS, ROBOT))


# ── counting ─────────────────────────────────────────────────────────────

def window_days(folder, days=DAYS):
    """The calendar days the Board covers, oldest first: the `days` days ending on the newest
    flows file's date. [] when there is none."""
    names = sorted(f for f in os.listdir(folder) if relationships.FLOWS.match(f)) if folder and os.path.isdir(folder) else []
    if not names:
        return []
    last = datetime.date.fromisoformat(relationships.FLOWS.match(names[-1]).group(1))
    return [(last - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def load(folder, days=DAYS):
    """(dates, base, problems): the window's calendar days, the Base days read as (date, flows),
    and what was missing or left out. Never raises on a bad file."""
    dates = window_days(folder, days)
    if not dates:
        return [], [], []
    base, _sol, _files, problems = brief.load(folder, dates[0], dates[-1])
    got = {d for d, _ in base}
    problems = problems + ["no flows file for %s" % d for d in dates if d not in got]
    return dates, base, problems


def shape(daily):
    """A plain word for how a seller's daily money moved. None when a day is missing."""
    if not daily or any(x is None for x in daily):
        return None
    total = sum(daily)
    if not total:
        return None
    med = statistics.median(daily)
    if med > 1 and all(abs(x - med) <= 0.1 * med for x in daily):
        return "flat"
    if max(daily) > total / 2:
        return "spike"
    top = max(daily)
    if len(daily) >= 3 and all(x < 0.05 * top for x in daily[-2:]) and max(daily[:-2]) >= 20:
        return "gone quiet"
    if len(daily) >= 4 and all(daily[i] > daily[i - 1] for i in range(len(daily) - 3, len(daily))):
        return "ramping"
    return "uneven"


def ceil10(p):
    """The next multiple of 10 at or above p; p is the exact share, never a rounded one, so a
    true 40.04%% is "over 40" (adversarial review 2026-10-13)."""
    return min(100, int(math.ceil(p / 10.0)) * 10) if p is not None else None


def reason(r, raw_share=None):
    """One line on why a row stands where it does, every number from the row. `raw_share` is the
    top payer's exact share in percent; without it the row's rounded share is used."""
    ret = "%d returning customer%s" % (r["returning"], "" if r["returning"] == 1 else "s")
    ret += " of %d" % r["customers"]
    p = r["top_payer_share_pct"]
    if r["one_payer_most"]:
        return "%s; one payer sent %g%% of its money" % (ret, p)
    if p is not None and p < 100:
        return "%s, no single payer over %d%%" % (ret, max(ceil10(p if raw_share is None else raw_share), 10))
    return ret


def compute(folder, snapshot, days=DAYS):
    """The Board as a dict (board.json is this). `snapshot` is a radar snapshot's "sellers"
    ({host: record}), or {} without one. None when the folder holds no flows file."""
    dates, base, problems = load(folder, days)
    if not base:
        return None
    snapshot = snapshot or {}
    known = {h.lower(): h for h in snapshot}
    names = brief.host_names(base)
    rows = []
    for day, d in base:
        r, _off, bad = brief.edges_of(d, day, True)
        rows += r
        if bad:
            problems.append("%d edges on %s were not in the shape chain_flows writes and were left out" % (bad, day))
    sellers_of = collections.defaultdict(set)
    for e in rows:
        sellers_of[e.payer].add(e.payee)
    robots = {w for w, ss in sellers_of.items() if len(ss) >= ROBOT}
    pos = {d: i for i, d in enumerate(dates)}
    present = {d for d, _ in base}

    by = collections.defaultdict(lambda: {"micro": 0, "payments": 0, "daily": [0] * len(dates),
                                          "payer_micro": collections.Counter(), "days_of": collections.defaultdict(set)})
    for e in rows:
        s = by[e.payee]
        s["micro"] += e.micro
        s["payments"] += e.n
        s["daily"][pos[e.date]] += e.micro
        s["payer_micro"][e.payer] += e.micro
        if e.payer not in robots:
            s["days_of"][e.payer].add(e.date)

    out = []
    for w, s in by.items():
        customers = len(s["days_of"])
        if not customers:
            continue
        returning = sum(1 for ds in s["days_of"].values() if len(ds) >= 2)
        top_micro = max(s["payer_micro"].values()) if s["payer_micro"] else 0
        share = brief.pct(top_micro, s["micro"]) if s["micro"] else None
        hosts = names.get(w, [])
        listed = [h for h in hosts if h in known]
        host = (listed or hosts or [w])[0]
        rec = snapshot.get(known.get(host, host)) or {}
        sells = rec.get("sells") or ""
        category = market.cat(sells + " " + (rec.get("url") or host))[0]
        daily = [round(s["daily"][i] / MICRO, 2) if d in present else None for i, d in enumerate(dates)]
        label = brief.label(host)
        r = {"host": label, "page": None if label != host or host == w else "/s/%s/" % slug(host),
             "hosts_total": len(hosts), "wallet": w, "category": category,
             "sells": brief.label(sells), "in_registry": bool(rec),
             "price": radar.price_label(rec) if rec else None,
             "price_min": rec.get("price_min") if rec else None, "price_max": rec.get("price_max") if rec else None,
             "customers": customers, "returning": returning,
             "robot_payers": len(set(s["payer_micro"]) & robots),
             "usdc": round(s["micro"] / MICRO, 2), "payments": s["payments"],
             "top_payer_share_pct": share, "one_payer_most": bool(s["micro"]) and 2 * top_micro > s["micro"],
             "daily_usdc": daily, "shape": shape(daily)}
        r["reason"] = reason(r, 100.0 * top_micro / s["micro"] if s["micro"] else None)
        out.append(r)
    out.sort(key=lambda r: (r["one_payer_most"], -r["returning"], -r["customers"], r["host"], r["wallet"]))
    cat_n = collections.Counter()
    for i, r in enumerate(out, 1):
        r["rank"] = i
        cat_n[r["category"]] += 1
        r["category_rank"] = cat_n[r["category"]]
    cats = sorted(cat_n, key=lambda c: (-sum(r["returning"] for r in out if r["category"] == c), c))
    return {"kind": KIND, "version": VERSION, "title": TITLE,
            "window": {"from": dates[0], "to": dates[-1], "days": len(dates), "dates": dates,
                       "files": len(base)},
            "registry": {"sellers": len(snapshot)},
            "robots": {"rule": "paid %d or more different sellers in the window" % ROBOT, "wallets": len(robots)},
            "sellers_ranked": len(out), "one_payer_most": sum(1 for r in out if r["one_payer_most"]),
            "categories": cats, "means": MEANS, "problems": problems, "sellers": out}


def slug(host):
    return re.sub(r"[^a-z0-9._-]", "-", host.lower())[:200]      # seller_pages.slug, so the link finds the page


# ── the page ─────────────────────────────────────────────────────────────

esc = atlas_style.esc


def _usd(x):
    if x is None:
        return "—"
    return "{:,.0f}".format(x) if x >= 100 else "{:,.2f}".format(x)


def _row(r, site):
    host = esc(r["host"])
    cell = '<a href="%s%s">%s</a>' % (esc(site), esc(r["page"]), host) if r["page"] else host
    if r["hosts_total"] > 1:
        cell += ' <span class="mono">+%d</span>' % (r["hosts_total"] - 1)
    if r["one_payer_most"]:
        cell += '<br><span class="pill one-payer">%s</span>' % ONE_PAYER
    share = "—" if r["top_payer_share_pct"] is None else "%g%%" % r["top_payer_share_pct"]
    return ('<tr><td class="n">%d</td><td class="h">%s</td><td class="sells">%s</td><td>%s</td><td class="n">%s</td>'
            '<td class="n">%s</td><td class="n">%s</td><td class="days">%s</td><td class="shape">%s</td></tr>'
            % (r["rank"], cell, esc(atlas_style.unsay(r["sells"])) or "—", esc(r["price"] or "—"),
               "{:,}".format(r["customers"]), "{:,}".format(r["returning"]), share,
               " ".join(_usd(x) for x in r["daily_usdc"]), esc(r["shape"] or "—")))


def _table(rows, site):
    return ('<div class="tw"><table class="board"><thead><tr><th class="n">#</th><th>Seller</th><th>What it sells</th>'
            '<th>Price</th><th class="n">Payer wallets</th><th class="n">Came back</th><th class="n">Top payer</th>'
            '<th>USDC a day, oldest first</th><th>Shape</th></tr></thead><tbody>'
            + "".join(_row(r, site) for r in rows) + "</tbody></table></div>")


def page(b, site=SITE, as_of=None, foot=None, n=None):
    """The Board as a page. `foot`, when given, is the site's footer template (atlas_style.FOOT
    or FOOT_FREE); without it the footer carries the day only."""
    site = site.rstrip("/")
    w = b["window"]
    as_of = as_of or w["to"]
    rng = "%s to %s" % (atlas_style.long_date(w["from"]), atlas_style.long_date(w["to"]))
    lede = "Every x402 seller on Base, ranked by payer wallets that come back on another day, not by money. %s." % rng
    ctx = {"root": esc(site), "css": esc(site) + "/atlas.css", "canon": esc(site) + "/board/",
           "title": esc("%s: x402 sellers ranked by returning payer wallets · %s" % (TITLE, market.BRAND)), "desc": esc(lede)}
    p = [atlas_style.HEAD % ctx, '<main id="main">',
         '<span class="eyebrow">%s · %s · Base · x402 only</span>' % (esc(TITLE), esc(rng)),
         "<h1>Who buyers come back to</h1>",
         '<p class="oneline">%s</p>' % esc(lede),
         "<p>Money can be made by one payer, or by a wallet paying a seller again and again. So this list counts payer "
         "wallets that come back on another day, not dollars. A wallet is not a customer you can see: one operator can "
         "run many wallets, and this list cannot tell. Read it as a lead, not a verdict.</p>",
         '<ul class="cav"><li><b>Payer wallets</b>: wallets that paid the seller this week. A wallet that paid %d or more '
         "different sellers is a robot and is not counted (%s this week); its money still counts.</li>"
         "<li><b>Came back</b>: payer wallets that paid on 2 or more days.</li>"
         "<li><b>Top payer</b>: the share of the seller's USDC from its largest payer. Over half, and the row is marked "
         '<span class="pill one-payer">%s</span> and placed after every seller that is not.</li>'
         "<li><b>Shape</b> of the money a day: <b>flat</b> every day within 10%% of the middle day; <b>spike</b> one day "
         "over half the week; <b>gone quiet</b> the last two days near nothing after a $20 day; <b>ramping</b> up on each "
         "of the last 3 days; <b>uneven</b> anything else.</li>"
         "<li>A wallet is not a person, and nothing here says who holds or runs one.</li></ul>"
         % (ROBOT, "{:,}".format(b["robots"]["wallets"]), ONE_PAYER),
         '<p class="muted">For agents: <a href="%s/board/board.json">board.json</a> holds the same numbers for every '
         "ranked seller, with its category and what it sells.</p>" % esc(site)]
    rows = b["sellers"]
    p.append('<h2 id="top">Top %d of %s</h2>' % (min(TOP, len(rows)), "{:,}".format(b.get("ranked_total", len(rows)))))
    p.append(_table(rows[:TOP], site))
    for c in b["categories"]:
        rs = [r for r in rows if r["category"] == c]
        p.append('<h2 id="%s">%s: top %d of %s</h2>' % (esc(slug(c)), esc(c[:1].upper() + c[1:]), min(TOP_CAT, len(rs)),
                                                       "{:,}".format(len(rs))))
        p.append(_table(rs[:TOP_CAT], site))
    if b.get("ranked_total", len(rows)) > len(rows):
        p.append(tiers.more_line(len(rows), b["ranked_total"], "ranked sellers", site))
    if b["problems"]:
        p.append('<p class="muted mono">Left out: %s.</p>' % esc("; ".join(b["problems"])))
    p.append("</main>")
    d = {"root": esc(site), "issue": atlas_style.ISSUES, "as_of": as_of, "n": n}
    p.append(foot % d if foot is not None else atlas_style.footer(esc(site), atlas_style.ISSUES, as_of, n=n))
    return "\n".join(p)


def placeholder(out, site=SITE, as_of=None, foot=None, n=None):
    """A plain /board/ page for a build that could not rank the week, so the site's Board link
    never breaks. An existing Board is left as it is. True when the placeholder was written."""
    path = os.path.join(out, "board", "index.html")
    if os.path.exists(path):
        return False
    site = site.rstrip("/")
    lede = "Every x402 seller on Base, ranked by payer wallets that come back on another day, not by money."
    ctx = {"root": esc(site), "css": esc(site) + "/atlas.css", "canon": esc(site) + "/board/",
           "title": esc("%s: x402 sellers ranked by returning payer wallets · %s" % (TITLE, market.BRAND)), "desc": esc(lede)}
    d = {"root": esc(site), "issue": atlas_style.ISSUES, "as_of": as_of, "n": n}
    p = [atlas_style.HEAD % ctx, '<main id="main">', "<h1>Who buyers come back to</h1>",
         '<p class="oneline">%s</p>' % esc(lede),
         "<p>This build had no week of payments to rank, so the Board is not shown. It is rebuilt with the next day's files.</p>",
         "</main>", foot % d if foot is not None else atlas_style.footer(esc(site), atlas_style.ISSUES, as_of, n=n)]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(p))
    return True


def dumps(b):
    return json.dumps(b, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def build(out, folder, snapshot, site=SITE, as_of=None, foot=None, n=None, top=None):
    """Write <out>/board/index.html and board.json. Returns the Board, or None (and writes
    nothing) when the folder holds no flows file. With `top` (the free tier's tiers.TOP),
    both files carry only the first `top` ranked sellers and say how many more the full
    record holds: what the page does not show, the JSON does not carry either."""
    b = compute(folder, snapshot)
    if b is None:
        return None
    site = site.rstrip("/")
    b["ranked_total"] = len(b["sellers"])
    if top is not None and len(b["sellers"]) > top:
        b["sellers"] = b["sellers"][:top]
        b["categories"] = [c for c in b["categories"] if any(r["category"] == c for r in b["sellers"])]
        b["locked"] = tiers.locked_json("%s more ranked sellers, past the %d shown"
                                        % ("{:,}".format(b["ranked_total"] - top), top), site, tiers.LIST_WAYS)
    html_page = page(b, site, as_of, foot, n)          # its links are written against the site
    b["page"] = site + "/board/"
    b["json"] = site + "/board/board.json"
    for r in b["sellers"]:
        if r["page"]:
            r["page"] = site + r["page"]
    d = os.path.join(out, "board")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "board.json"), "w") as f:
        f.write(dumps(b))
    with open(os.path.join(d, "index.html"), "w") as f:
        f.write(html_page)
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--flows-dir", required=True)
    ap.add_argument("--store", default=None, help="the radar snapshot folder (default: radar.py's)")
    ap.add_argument("--out", default="site")
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--top", type=int, default=10, help="rows to print")
    a = ap.parse_args()
    if a.store:
        radar.STORE = a.store
    snaps = radar.snapshots()
    snap = radar.load_snapshot(snaps[-1]) if snaps else {"sellers": {}}
    b = build(a.out, a.flows_dir, snap["sellers"], a.site, snap.get("date"), n=len(snap["sellers"]) or None)
    if b is None:
        sys.exit("board: no flows-<date>.json in %s" % a.flows_dir)
    print("board %s to %s · %d sellers ranked · %d robots left out · %d marked %r"
          % (b["window"]["from"], b["window"]["to"], b["sellers_ranked"], b["robots"]["wallets"], b["one_payer_most"], ONE_PAYER))
    for r in b["sellers"][:a.top]:
        print("%3d  %-34s %-22s customers %4d  returning %4d  top payer %5s%%  %s  %s"
              % (r["rank"], r["host"][:34], r["category"], r["customers"], r["returning"], r["top_payer_share_pct"],
                 r["shape"], "[%s]" % ONE_PAYER if r["one_payer_most"] else ""))
    for p in b["problems"]:
        print("  left out: %s" % p, file=sys.stderr)


if __name__ == "__main__":
    main()
