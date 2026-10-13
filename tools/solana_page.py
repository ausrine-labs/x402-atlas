#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 83713b3). Edit it there, not here.
"""solana_page.py — /solana/: one day of x402 payments on Solana, in numbers.

The map at /map/solana/ draws the day; this page counts it. It reads the newest
whole flows-sol-<day>.json (solana_flows.py assemble) and writes /solana/index.html
in the Atlas look: the day's totals, the ten payees taking the most dollars and the
ten paid most often, each processor's share, how many transactions were left unread,
and the file's own two sentences on what it counts.

Before any total it names the largest single line (one payer to one payee), and says
so when that line is more than half the day's dollars: a total one pair makes is a
fact about that pair, not about the market. The same for a single payee.

A payee is shown as its host when the file names one for its wallet (map_page.payee_host),
otherwise as its shortened wallet. A host links to its /s/ page only when that page
exists; a wallet links to /b/ only when that page exists, else to the public explorer.
Nothing here says who holds a wallet. Standard library only.

    solana_page.py --flows flows-sol-2026-10-10.json --store radar-store --out _site
"""

import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import atlas_style  # noqa: E402
import buyer_pages  # noqa: E402
import map_page  # noqa: E402
import market  # noqa: E402
import whales as whales_mod  # noqa: E402

NAME = re.compile(r"^flows-sol-(\d{4}-\d{2}-\d{2})\.json$")
TOP = 10


esc = atlas_style.esc


def text(x):
    """Words the file or the registry wrote, as the page shows them: escaped, and without the
    banned word. Addresses and links go through esc() alone; they are not words."""
    return esc(map_page.scrub(str(x if x is not None else "")))


def whole(fl):
    """A whole Solana day: 24 hours, and, where the file lists them, all four windows."""
    try:
        hours = float(fl.get("hours") or 0)
    except (TypeError, ValueError):
        return False
    win = fl.get("windows")
    return (fl.get("chain") == "solana" and hours >= 24 and isinstance(fl.get("edges"), list)
            and ("windows" not in fl or (isinstance(win, list) and len(win) >= 4)))


def newest(dirs):
    """(path, flows) for the newest whole flows-sol-<day>.json in any of dirs, or (None, None).
    A file that will not load, or covers less than a day, is passed over for the one before."""
    found = {}
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            m = NAME.match(name)
            if m:
                found.setdefault(m.group(1), []).append(os.path.join(d, name))
    for day in sorted(found, reverse=True):
        for path in found[day]:            # the same day in more than one folder: any whole copy will do
            try:
                with open(path) as f:
                    fl = json.load(f)
            except (OSError, ValueError) as e:
                print("solana: %s would not load (%s); trying the next" % (path, type(e).__name__))
                continue
            if isinstance(fl, dict) and whole(fl):
                return path, fl
            print("solana: %s is not a whole day; trying the next" % path)
    return None, None


def money(x):
    return "$%s" % "{:,.2f}".format(x)


def pct(part, total):
    if not total:
        return "—"
    p = 100.0 * part / total
    if 0 < p < 0.05:
        return "<0.1%"
    return "%.1f%%" % p if p < 10 else "%.0f%%" % p


def summary(fl, A):
    """The day in numbers, from the x402 edges alone (on Solana that is every edge)."""
    E = [e for e in fl.get("edges") or [] if (e.get("n_x402") or 0) > 0]
    sellers = fl.get("sellers") or {}
    pay = collections.defaultdict(lambda: {"usd": 0.0, "n": 0, "payers": set()})
    for e in E:
        p = pay[e["to"]]
        p["usd"] += e.get("usdc_x402") or 0.0
        p["n"] += e["n_x402"]
        p["payers"].add(e["from"])
    usd = sum(e.get("usdc_x402") or 0.0 for e in E)
    rows = []
    for w, p in pay.items():
        hosts = sellers.get(w) or []
        host = map_page.payee_host(hosts, A)
        rows.append({"wallet": w, "host": host, "page": host if host in A else None, "usd": round(p["usd"], 6),
                     "n": p["n"], "payers": len(p["payers"])})
    largest = max(E, key=lambda e: (e.get("usdc_x402") or 0.0, e["n_x402"], e["from"], e["to"])) if E else None
    return {"day": fl.get("date") or fl.get("day") or "", "payments": sum(e["n_x402"] for e in E), "usd": round(usd, 6),
            "payees": len(pay), "payers": len({e["from"] for e in E}), "edges": len(E), "rows": rows,
            "by_usd": sorted(rows, key=lambda r: (-r["usd"], -r["n"], r["wallet"]))[:TOP],
            "by_n": sorted(rows, key=lambda r: (-r["n"], -r["usd"], r["wallet"]))[:TOP],
            "largest": largest, "largest_share": ((largest.get("usdc_x402") or 0.0) / usd) if largest and usd else 0.0}


def largest_line(s):
    """The largest single line, in words, for the build's log."""
    e = s["largest"]
    if not e:
        return "no lines"
    return "%s -> %s: %s over %s, %s of the day's dollars" % (
        e["from"], e["to"], money(e.get("usdc_x402") or 0.0), map_page.num(e["n_x402"], "payment"),
        pct(e.get("usdc_x402") or 0.0, s["usd"]))


def payee_cell(r, site):
    """A payee as the page shows it: its host, linked to /s/ when that page exists; else its
    shortened wallet, linked to its public page on Solana."""
    if r["host"]:
        label = text(r["host"])
        return '<a href="%s/s/%s/">%s</a>' % (esc(site), esc(buyer_pages.slug(r["page"])), label) if r["page"] else label
    return '<a rel="nofollow noopener" href="%s"><code>%s</code></a>' % (esc(whales_mod.explorer(r["wallet"])),
                                                                      esc(whales_mod.short(r["wallet"])))


def payer_cell(w, site, buyer_slugs):
    code = "<code>%s</code>" % esc(whales_mod.short(w))
    if buyer_pages.slug(w) in buyer_slugs:
        return '<a href="%s">%s</a>' % (esc(buyer_pages.link(w, site)), code)
    return '<a rel="nofollow noopener" href="%s">%s</a>' % (esc(whales_mod.explorer(w)), code)


def table(rows, s, site, by):
    head = ('<tr><th class="n">#</th><th>Payee</th><th class="n">Dollars</th><th class="n">% of dollars</th>'
            '<th class="n">Payments</th><th class="n">% of payments</th><th class="n">Wallets that paid</th></tr>')
    body = "".join('<tr><td class="n">%d</td><td class="h">%s</td><td class="n">%s</td><td class="n">%s</td>'
                   '<td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
                   % (i + 1, payee_cell(r, site), money(r["usd"]), pct(r["usd"], s["usd"]), "{:,}".format(r["n"]),
                      pct(r["n"], s["payments"]), "{:,}".format(r["payers"])) for i, r in enumerate(rows))
    return '<div class="tw"><table aria-label="Payees by %s">%s%s</table></div>' % (by, head, body)


def build(out, fl, A, site="", as_of="", head=None, foot=None, issues=None, buyer_slugs=(), map_url=None):
    """Write out/solana/index.html from one whole Solana day. A is the registry snapshot's
    sellers, keyed by host (whose /s/ pages exist); buyer_slugs the /b/ pages that exist."""
    if head is None or foot is None or issues is None:
        import seller_pages    # the house header and footer; imported late, it imports us
        head = seller_pages.HEAD if head is None else head
        foot = seller_pages.FOOT if foot is None else foot
        issues = seller_pages.ISSUES if issues is None else issues
    site = (site or "").rstrip("/")
    s = summary(fl, A)
    print("solana: the largest single line: %s" % largest_line(s))       # before any total
    day = atlas_style.long_date(s["day"])
    lede = ("On %s, known payment processors settled %s on Solana: %s from %s to %s."
            % (day, map_page.num(s["payments"], "x402 payment"), money(s["usd"]), map_page.num(s["payers"], "wallet"),
               map_page.num(s["payees"], "payee")))
    title = "x402 on Solana, %s · %s" % (day, market.BRAND)
    big = s["largest"]
    desc = ("The largest single line: %s over %s, %s of the day’s dollars. %s"
            % (money(big.get("usdc_x402") or 0.0), map_page.num(big["n_x402"], "payment"), pct(big.get("usdc_x402") or 0.0, s["usd"]),
               lede)) if big else lede          # here too, the largest line before any total
    p = [head % {"title": text(title), "desc": text(desc), "canon": site + "/solana/", "css": site + "/atlas.css", "root": site}]
    p.append('<main id="main"><p class="eyebrow">Solana · x402 · %s</p><h1>x402 on Solana, one day</h1>' % text(day))

    # the largest line first: a total is read with it in mind
    e = s["largest"]
    if e:
        big = next(r for r in s["rows"] if r["wallet"] == e["to"])
        line = ("The largest single line: %s paid %s %s over %s, %s of the day’s dollars."
                % (payer_cell(e["from"], site, buyer_slugs), payee_cell(big, site), money(e.get("usdc_x402") or 0.0),
                   map_page.num(e["n_x402"], "payment"), pct(e.get("usdc_x402") or 0.0, s["usd"])))
        warn = []
        if s["largest_share"] > 0.5:
            warn.append("<b>One line is more than half of the day’s dollars.</b> The dollar total below is mostly "
                        "that one pair, and says little about the rest.")
        top = s["by_usd"][0]
        if s["usd"] and top["usd"] / s["usd"] > 0.5:
            warn.append("<b>One payee took more than half of the day’s dollars:</b> %s took %s of %s (%s)."
                        % (payee_cell(top, site), money(top["usd"]), money(s["usd"]), pct(top["usd"], s["usd"])))
        p.append('<div class="box"><p style="margin:0">%s</p>%s</div>'
                 % (line, "".join('<p style="margin:8px 0 0">%s</p>' % w for w in warn)))

    p.append('<p class="sells">%s</p>' % text(lede))
    p.append('<div class="tiles">%s</div>' % "".join(
        '<div class="tile"><b>%s</b><span>%s</span></div>' % (v, k) for v, k in (
            ("{:,}".format(s["payments"]), "x402 payments"), (money(s["usd"]), "paid, in USDC and USDT"),
            ("{:,}".format(s["payees"]), "payees: wallets that were paid"),
            ("{:,}".format(s["payers"]), "payers: wallets that paid"))))
    assets = sorted((fl.get("assets") or {}).items(), key=lambda kv: -(kv[1].get("usdc") or 0))
    if assets:
        p.append('<p class="muted">Dollars are USDC and USDT together, one for one, as the file counts them: %s.</p>'
                 % "; ".join("%s %s over %s" % (text(k), money(v.get("usdc") or 0), map_page.num(v.get("payments") or 0, "payment"))
                             for k, v in assets))
    if map_url:
        p.append('<p class="actions"><a class="btn ghost" href="%s">See the day drawn on the map</a></p>' % esc(map_url))

    p.append("<h2>The %d payees taking the most</h2>" % len(s["by_usd"]))
    p.append(table(s["by_usd"], s, site, "dollars"))
    p.append("<h2>The %d payees paid most often</h2>" % len(s["by_n"]))
    p.append(table(s["by_n"], s, site, "payments"))
    p.append('<p class="muted">A payee is shown as its host when the file names one for its wallet, and otherwise as '
             'its shortened wallet. A host links to its page on the Atlas when it has one; a wallet to its public page on Solana.</p>')

    procs = sorted((fl.get("processors") or {}).items(), key=lambda kv: (-(kv[1].get("payments") or 0), kv[0]))
    if procs:
        n_all = sum(v.get("payments") or 0 for _k, v in procs)
        usd_all = sum(v.get("usdc") or 0.0 for _k, v in procs)
        p.append("<h2>Who settled them</h2>"
                 '<p class="muted">Each payment processor’s share of the day: the payments it paid the fee for.</p>'
                 '<div class="tw"><table aria-label="Processors"><tr><th>Processor</th><th class="n">Payments</th>'
                 '<th class="n">Share</th><th class="n">Dollars</th><th class="n">Share</th></tr>%s</table></div>'
                 % "".join('<tr><td class="h">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                           '<td class="n">%s</td></tr>' % (text(k), "{:,}".format(v.get("payments") or 0),
                                                           pct(v.get("payments") or 0, n_all), money(v.get("usdc") or 0.0),
                                                           pct(v.get("usdc") or 0.0, usd_all)) for k, v in procs))

    read = fl.get("signatures") or 0
    unread = fl.get("unread") or 0
    are = "is" if unread == 1 else "are"
    p.append("<h2>What was left unread</h2>")
    if read:
        p.append("<p>Of %s the processors’ addresses listed, %s could not be read (%s) and %s not in the totals."
                 % (map_page.num(read, "transaction"), "{:,}".format(unread), pct(unread, read), are))
    else:
        p.append("<p>%s could not be read and %s not in the totals." % (map_page.num(unread, "transaction"), are))
    p.append(" A six-hour window with more than 1% unread is not written, and a day is whole only when all four are.</p>")
    if fl.get("other_shape"):
        p.append('<p class="muted">%s that a processor paid for were not one payment between two owners, and are '
                 'not counted.</p>' % map_page.num(fl["other_shape"], "other transaction"))

    windows = len(fl.get("windows") or [])
    p.append('<h2>How this was counted</h2><ul class="cav">%s</ul></main>' % "".join(
        "<li>%s</li>" % text(c) for c in map_page.method_notes(fl) + [
            "The day runs from 00:00 to 24:00 UTC%s." % (", read in %s" % map_page.num(windows, "six-hour window")
                                                         if windows else ""),
            map_page.SOL_NOTES[0], map_page.SOL_NOTES[3]]))
    p.append(foot % {"root": site, "issue": esc(issues), "as_of": esc(as_of or s["day"]), "n": "{:,}".format(len(A))})
    sdir = os.path.join(out, "solana")
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "index.html"), "w") as f:
        f.write("".join(p))
    return dict({k: v for k, v in s.items() if k not in ("rows", "by_usd", "by_n")}, out=os.path.join(sdir, "index.html"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--flows", required=True, help="a whole flows-sol-<date>.json (solana_flows.py assemble)")
    ap.add_argument("--store", required=True, help="the registry snapshots (market-<date>.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    import radar
    radar.STORE = a.store
    snap = radar.load_snapshot(radar.snapshots()[-1])
    with open(a.flows) as f:
        fl = json.load(f)
    r = build(a.out, fl, snap["sellers"], a.site, snap["date"])
    print("solana: %d x402 payments, %s, %d payers, %d payees -> %s"
          % (r["payments"], money(r["usd"]), r["payers"], r["payees"], r["out"]))


if __name__ == "__main__":
    main()
