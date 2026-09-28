#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""prices.py — /prices/: what a call costs in each kind of x402 service.

Per category (market.py's categories, sorted the way whales.py sorts a seller):

    the 25th percentile, median and 75th percentile listed price per call, across
    sellers — each seller counted once, at its own median listed price, so a host
    listing ninety endpoints does not outvote ninety hosts listing one;
    how many sellers list below the category median;
    the cheapest and the dearest seller that was actually paid on chain in the rollup's
    days, with what an average payment to it came to.

Listed prices are dated by the registry snapshot, paid figures by the rollup's days.
A listed price is what the seller asks, not what anyone paid.

    prices.py --snapshot market-2026-09-24.json --whales whales-2026-09-24.json --out _site

prices_body(data) is the fragment; write(out, data) wraps it. Standard library only.
"""

import argparse
import collections
import json
import sys

import coverage_page as cp
import market


def category(host, row):
    return market.cat((row.get("sells") or "") + " " + host)[0]


def prices_data(sellers, rollup=None, listed_on="", as_of="", site=""):
    """sellers: the snapshot's {host: row}. Returns the rows /prices/ shows, busiest category first.
    A seller counts as paid by its own chain's rule: x402-settled where that pull told it apart."""
    classified = cp.classified_chains(rollup)
    paid = {}
    for s in (rollup or {}).get("sellers") or []:
        usdc, n = cp.paid(s, classified)
        if n:
            paid[s["host"]] = (usdc, n)
    by = collections.defaultdict(list)
    for host, row in sellers.items():
        p = row.get("price_med") or 0
        if p and p > 0:
            by[category(host, row)].append((host, float(p)))
    out = []
    for cat, xs in by.items():
        prices = [p for _, p in xs]
        med = cp.percentile(prices, 50)
        paid_here = [(h, p) for h, p in xs if h in paid]
        pick = lambda hp: {"host": hp[0], "listed": hp[1], "usdc": round(paid[hp[0]][0], 2), "payments": paid[hp[0]][1],
                           "avg_paid": round(paid[hp[0]][0] / paid[hp[0]][1], 6)}
        out.append({"category": cat, "sellers": len(xs), "p25": cp.percentile(prices, 25), "median": med,
                    "p75": cp.percentile(prices, 75), "undercut": sum(1 for p in prices if p < med),
                    "paid_sellers": len(paid_here),
                    "cheapest_paid": pick(min(paid_here, key=lambda hp: (hp[1], hp[0]))) if paid_here else None,
                    "dearest_paid": pick(max(paid_here, key=lambda hp: (hp[1], hp[0]))) if paid_here else None})
    out.sort(key=lambda r: (-r["sellers"], r["category"]))
    return {"as_of": as_of or listed_on, "listed_on": listed_on, "days": ", ".join((rollup or {}).get("dates") or []),
            "site": cp.site_path(site), "classified": sorted(classified), "chains_covered": cp.chains_of(rollup),
            "categories": out, "sellers_priced": sum(r["sellers"] for r in out)}


def price_text(x):
    if x is None:
        return "—"
    if x == 0:
        return "$0"
    if x >= 1:
        return "$%s" % "{:,.2f}".format(x)
    return "$%s" % ("%.6f" % x if x < 0.0001 else "%.4f" % x).rstrip("0").rstrip(".")


def paid_cell(p, site=""):
    if not p:
        return '<span class="muted">none paid</span>'
    return "%s<br><span class=\"muted\">lists %s · %s · average %s</span>" % (
        cp.seller_html(p["host"], site), cp.esc(price_text(p["listed"])), cp.num(p["payments"], "payment"), cp.esc(price_text(p["avg_paid"])))


def prices_body(data):
    x402 = cp.basis(set(data["classified"]), data["chains_covered"])
    site = data.get("site", "")
    p = ['<section class="prices">', "<h1>Price benchmarks</h1>",
         '<p class="muted">Listed prices per call from the registry of <span class="dated">%s</span>; paid on chain means %s on '
         '<span class="dated">%s</span>. Built <span class="dated">%s</span>.</p>'
         % (cp.esc(data["listed_on"]), cp.esc(x402), cp.esc(data["days"] or "—"), cp.esc(data["as_of"])),
         '<div class="wrap"><table><thead><tr><th>category</th><th class="num">sellers</th><th class="num">25th</th>'
         '<th class="num">median</th><th class="num">75th</th><th class="num">below median</th>'
         "<th>cheapest paid on chain</th><th>dearest paid on chain</th></tr></thead><tbody>"]
    for r in data["categories"]:
        p.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td>%s</td><td>%s</td></tr>' % (
                     cp.esc(r["category"]), "{:,}".format(r["sellers"]), cp.esc(price_text(r["p25"])),
                     cp.esc(price_text(r["median"])), cp.esc(price_text(r["p75"])), "{:,}".format(r["undercut"]),
                     paid_cell(r["cheapest_paid"], site), paid_cell(r["dearest_paid"], site)))
    p.append("</tbody></table></div>")
    p.append('<p class="muted">Each seller counts once, at the median of the prices it lists. Percentiles interpolate between '
             "neighbouring sellers. \"Below median\" counts sellers listing less than their category's median. A category "
             "comes from what the seller says it sells, sorted by fixed rules; a seller can fit more than one and is put "
             "in the first. The average paid is USDC received over payments counted, and can differ from the listed "
             "price where a price varies per call.</p>")
    p.append("</section>")
    return "".join(p)


def write(out, data):
    return cp.write(out, "prices", cp.page("Price benchmarks", prices_body(data), data["as_of"],
                                           "Listed x402 prices per call by category, and what was paid on chain.",
                                           room="prices", root=data.get("site", "")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--whales")
    ap.add_argument("--site", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    snap = json.load(open(a.snapshot))
    rollup = json.load(open(a.whales)) if a.whales else None
    d = prices_data(snap["sellers"], rollup, snap.get("date", ""), (rollup or {}).get("as_of") or snap.get("date", ""), a.site)
    print("prices: %d categories, %d sellers priced -> %s" % (len(d["categories"]), d["sellers_priced"], write(a.out, d)))


if __name__ == "__main__":
    sys.exit(main())
