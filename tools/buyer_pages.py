#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 507dd4a). Edit it there, not here.
"""buyer_pages.py — a page for every buyer wallet: what one wallet paid for, and to whom.

Sellers have pages, wallet groups have pages; the wallets that pay them did not.
seller_pages.py calls build() with the day's rollup (whales.py) and writes one page
per wallet that made at least one x402-settled payment in the window, at
/b/<wallet>/ — its x402 payments and USDC, the money it sent the same sellers some
other way, how many sellers it paid, what kinds of things it bought, and the sellers
themselves, busiest first. A wallet whose x402 payments reached three or more sellers
is said to be an agent at work, and nothing more is said about who holds it.

A wallet, a host and an amount are public facts. A name is not, and none is given.
Host names come from the registry and are escaped on the way out. Standard library only.
"""

import collections
import html
import json
import os
import re

# Kept word for word from whales.py's notes (tested against them), so the standing
# caveats read the same on every page that uses the rollup.
CAVEATS = [
    "On-chain figures are real USDC transfers to seller wallets the public x402 registry names, "
    "over the pulled hours only. A seller whose wallet is not in the registry is invisible here.",
    "x402-settled means the transfer's transaction used an EIP-3009 authorization: a facilitator "
    "settled a payment the buyer signed. A plain transfer to the same wallet is money that arrived "
    "some other way — a person paying a merchant, a treasury move — and is counted, but not as x402.",
    "A wallet is not an agent. One operator can appear as many wallets; a wallet paying several "
    "sellers is the honest signal of an agent at work.",
    "Payments to a wallet shared by several hosts are credited to the busiest host the registry knows.",
]
AGENT = "paid three or more sellers in the window: an agent at work"


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def slug(x):
    return re.sub(r"[^a-z0-9._-]", "-", x.lower())[:200]


def money(x):
    return "$%s" % ("{:,.0f}".format(x) if x >= 100 else "{:,.2f}".format(x))


def span_words(hours):
    return "%.0f h" % hours if hours < 48 else "%d days" % round(hours / 24.0)


def day_words(chain):
    """The day (or days) the rollup covers, as the pull named them."""
    dates = chain.get("dates") or []
    return ", ".join(dates) if dates else (chain.get("as_of") or "")


def link(wallet, site=""):
    """Where a wallet's page lives: /b/<wallet, lowercased>/."""
    return "%s/b/%s/" % (site, slug(wallet))


def bought(sellers, b=None):
    """The categories a wallet bought, most x402 payments first. The rollup counts them over
    every seller (categories_x402) before it cuts the seller list to eight; an older rollup
    without that falls back to the seller rows with an x402 payment. Plain transfers are not
    purchases, so the rollup's all-transfer categories are never used."""
    if b is not None and isinstance(b.get("categories_x402"), list):
        return list(b["categories_x402"])
    n = collections.Counter()
    for s in sellers:
        if (s.get("payments_x402") or 0) > 0:
            n[s.get("category") or "other"] += s["payments_x402"]
    return [c for c, _ in n.most_common()]


def build(out, chain, A, ctx, as_of, n_sellers, site="", head="", foot="", issues=""):
    """Write /b/<wallet>/index.html for every wallet with an x402 payment, /b/ for the list
    and /b/index.json for search. Returns ({wallet_slug: {"agent": bool}}, listing) so the
    seller pages and the front door link only to pages that exist."""
    buyers = [b for b in (chain.get("buyers") or []) if b.get("payments_x402")]
    agents = {slug(b["wallet"]) for b in (chain.get("agents") or [])}
    hours = chain.get("hours") or 24
    window, day = span_words(hours), day_words(chain)
    bdir = os.path.join(out, "b")
    os.makedirs(bdir, exist_ok=True)
    pages, listing = {}, []
    for b in buyers:
        sl = slug(b["wallet"])
        agent = sl in agents
        other = max((b.get("usdc") or 0.0) - (b.get("usdc_x402") or 0.0), 0.0)
        sellers = sorted(b.get("sellers") or [], key=lambda s: (-(s.get("payments_x402") or 0), -(s.get("payments") or 0),
                                                                  -(s.get("usdc") or 0.0), s.get("host") or ""))
        title = "%s — a buyer wallet on %s · x402 Atlas" % (b["short"], b.get("chain") or "Base")
        desc = "Wallet %s: %s x402 payments, %s, to %d seller%s in the last %s. As of %s." % (
            b["short"], "{:,}".format(b["payments_x402"]), money(b.get("usdc_x402") or 0.0), b.get("sellers_paid_x402") or 0,
            "s" if (b.get("sellers_paid_x402") or 0) != 1 else "", window, as_of)
        p = [head % dict(ctx, title=esc(title), desc=esc(desc), canon=esc(link(b["wallet"], site)))]
        p.append("<main><h1><code>%s</code></h1>" % esc(b["short"]))
        p.append('<p class="muted">Wallet <a rel="nofollow noopener" href="%s"><code>%s</code></a> on %s.</p>'
                 % (esc(b.get("explorer") or ""), esc(b["wallet"]), esc(b.get("chain") or "Base")))
        p.append('<p>%s<span class="tag">%s · %s on-chain</span><span class="tag">as of %s</span></p>'
                 % ('<span class="tag">agent at work</span>' if agent else "", esc(day), esc(window), esc(as_of)))
        if agent:
            p.append('<p class="sells">This wallet %s.</p>' % esc(AGENT))
        else:
            p.append('<p class="sells">This wallet’s x402 payments reached %d seller%s in the window.</p>'
                     % (b.get("sellers_paid_x402") or 0, "s" if (b.get("sellers_paid_x402") or 0) != 1 else ""))
        p.append('<div class="tiles">'
                 '<div class="tile"><b>%s</b><span>x402 payments, last %s</span></div>'
                 '<div class="tile"><b>%s</b><span>USDC, x402-settled</span></div>'
                 '<div class="tile"><b>%s</b><span>USDC that reached sellers by other means, not x402</span></div>'
                 '<div class="tile"><b>%d</b><span>sellers paid over x402%s</span></div></div>'
                 % ("{:,}".format(b["payments_x402"]), esc(window), money(b.get("usdc_x402") or 0.0), money(other),
                    b.get("sellers_paid_x402") or 0,
                    (" (%d by any means)" % b["sellers_paid"]) if b.get("sellers_paid", 0) != b.get("sellers_paid_x402") else ""))
        cats = bought(sellers, b)
        p.append('<h2>What it bought</h2><p class="muted">By category, most payments first: %s.</p>'
                 % (esc(", ".join(cats)) if cats else "—"))
        p.append('<h2>The sellers it paid</h2><div class="tw"><table><tr><th>seller</th><th class="n">x402 payments</th>'
                 '<th class="n">USDC, x402</th><th class="n">USDC, other means</th><th>category</th></tr>')
        for s in sellers:
            host = s.get("host") or ""
            name = ('<a href="%s/s/%s/">%s</a>' % (site, esc(slug(host)), esc(host))) if host in A else esc(host)
            p.append('<tr><td class="h">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                     % (name, "{:,}".format(s.get("payments_x402") or 0), money(s.get("usdc_x402") or 0.0),
                        money(max((s.get("usdc") or 0.0) - (s.get("usdc_x402") or 0.0), 0.0)), esc(s.get("category") or "")))
        p.append("</table></div>")
        if (b.get("sellers_paid") or 0) > len(sellers):
            p.append('<p class="muted">%d more sellers not shown: the rollup keeps the eight this wallet sent the most USDC.</p>'
                     % (b["sellers_paid"] - len(sellers)))
        p.append('<h2>How to read this</h2><ul class="cav">%s</ul></main>' % "".join("<li>%s</li>" % esc(c) for c in CAVEATS))
        p.append(foot % {"issue": esc("%s?template=correct.yml&title=%s" % (issues, "Correction:+buyer+" + sl)), "as_of": esc(as_of),
                         "n": "{:,}".format(n_sellers)})
        d = os.path.join(bdir, sl)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write("".join(p))
        pages[sl] = {"agent": agent}
        listing.append({"wallet": sl, "short": b["short"], "x402": b["payments_x402"], "usdc_x402": round(b.get("usdc_x402") or 0.0, 2),
                        "sellers": b.get("sellers_paid_x402") or 0, "agent": agent})

    listing.sort(key=lambda r: (not r["agent"], -r["x402"], -r["usdc_x402"], r["wallet"]))
    at_work = [r for r in listing if r["agent"]]
    rest = [r for r in listing if not r["agent"]]
    page = [head % dict(ctx, title="Buyers: the wallets that paid over x402 · x402 Atlas",
                        desc="%d wallets paid x402 sellers in the last %s, %d of them three or more sellers. As of %s."
                        % (len(listing), window, len(at_work), as_of), canon=site + "/b/")]
    page.append('<main><h1>Buyers</h1><p class="sells">Every wallet that made an x402 payment to a seller in the last %s '
                "(%s): %s wallets. %s of them paid three or more sellers — agents at work. A wallet is not a person, and "
                "nothing here says who holds one.</p>" % (esc(window), esc(day), "{:,}".format(len(listing)), "{:,}".format(len(at_work))))

    def table(rows):
        t = ['<div class="tw"><table><tr><th>wallet</th><th class="n">x402 payments</th><th class="n">USDC, x402</th>'
             '<th class="n">sellers</th></tr>']
        for r in rows:
            t.append('<tr><td><a href="%s"><code>%s</code></a></td><td class="n">%s</td><td class="n">%s</td><td class="n">%d</td></tr>'
                     % (esc(link(r["wallet"], site)), esc(r["short"]), "{:,}".format(r["x402"]), money(r["usdc_x402"]), r["sellers"]))
        t.append("</table></div>")
        return "".join(t)

    page.append("<h2>Agents at work · %s</h2>" % "{:,}".format(len(at_work)))
    page.append(table(at_work) if at_work else '<p class="muted">No wallet’s x402 payments reached three or more sellers in the window.</p>')
    page.append("<h2>Every other buyer · %s</h2>" % "{:,}".format(len(rest)))
    page.append(table(rest) if rest else '<p class="muted">None.</p>')
    page.append('<h2>How to read this</h2><ul class="cav">%s</ul></main>' % "".join("<li>%s</li>" % esc(c) for c in CAVEATS))
    page.append(foot % {"issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(n_sellers)})
    with open(os.path.join(bdir, "index.html"), "w") as fh:
        fh.write("".join(page))
    with open(os.path.join(bdir, "index.json"), "w") as fh:        # the front door's search will read this
        json.dump({"as_of": as_of, "buyers": [{"wallet": r["wallet"], "x402": r["x402"], "usdc_x402": r["usdc_x402"],
                                               "sellers": r["sellers"], "agent": r["agent"]} for r in listing]},
                  fh, separators=(",", ":"))
    return pages, listing
