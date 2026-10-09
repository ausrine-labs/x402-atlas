#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 400e511). Edit it there, not here.
"""seller_pages.py — a public page for every seller in the agent economy.

Roughly 2,000 teams sell to agents over x402. Each of them wants to know how
it is doing, and none of them has a day-by-day record. We do. This writes one
static page per seller — rank, paid calls, payers, price, rivals, the replay,
and, given the on-chain window (--flows-dir), its relationships with its buyers —
plus a searchable index, from the radar's own snapshots.

Why static HTML: a seller searching for its own name should find its page.

    seller_pages.py --out /path/to/site        # writes site/s/..., site/claim.html
    seller_pages.py --out site --whales flows/whales-<date>.json --flows-dir flows
    seller_pages.py --out site ... --full      # the whole record public, as before tiers.py

Since 2026-10-05 the site is built in the free tier (tiers.FREE_TIER_ONLY): the basic
card is free, the full record is paid, and what a page does not show it does not carry.
--full builds the old, everything-public site, byte for byte.

Every word that comes from the registry was written by a stranger. It is
escaped on the way out, always (see esc()). Numbers carry their caveats.
Standard library only. Made by an AI agent, openly and by design.
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import date
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import radar  # noqa: E402
import market  # noqa: E402
import operator_pages  # noqa: E402
import buyer_pages  # noqa: E402
import front_door  # noqa: E402
import map_page  # noqa: E402
import atlas_style  # noqa: E402
import site_pages  # noqa: E402
import relationships  # noqa: E402
import tiers  # noqa: E402
import whales  # noqa: E402  (explorer: a wallet's public page on its own chain)

SITE = "https://ausrine-labs.github.io/x402-atlas"
API = "https://ausrine-who.onrender.com"
ISSUES = atlas_style.ISSUES
CORRECT = ISSUES + "?template=correct.yml"            # the form: page, what is wrong, what is right
# Polar checkout links (tools/polar_offers.py makes them). The page being claimed
# travels with the checkout as ?reference_id=<host>.
BUY_VERIFIED = "https://buy.polar.sh/polar_cl_o4rqOAkZsoIAzNV5EqYOA5rVkkazYEDlSTxce2Pk4YF"
BUY_REPORT = "https://buy.polar.sh/polar_cl_dYToSjRR75cE30SY9diS4uYAbCXc4ZizzMSEt1NqNbe"
BUY_BUYERS = "https://buy.polar.sh/polar_cl_ENl6aFmH7kBGSBRzQzM7E6FPGvP5xJKdMTgmf4eATNJ"
BUY_OPERATOR = "https://buy.polar.sh/polar_cl_nabc7zipli1BLgwDkLh4tyEEPyrSE3rTIEzxh1BaWDG"
# Atlas Pro, $49 a month: the Polar checkout for the product whose license key opens /pro.
# Set it to "" and /pro.html says the subscription opens soon and shows no button (tested).
BUY_PRO = "https://buy.polar.sh/polar_cl_lJhAOVU7EHynszEyW3pSoPuEuMkbPKORYjVqJ1d7MBP"   # Atlas Pro, $49/mo; its key opens /pro (2026-09-30)
# Atlas for Sellers, $29 a month: the Polar checkout for "Your buyers", whose key opens the seller report.
BUY_SELLERS = "https://buy.polar.sh/polar_cl_tKCkIdfx92wCN3i0rrY5cTCTzk3giBZADbkHk04KET8"


def checkout_id(url):
    """polar_cl_… from a Polar checkout address: the claim page carries only the id."""
    return url[len(atlas_style.POLAR):] if url.startswith(atlas_style.POLAR) else url

CAVEATS = [
    "Source: the public x402 discovery registry, photographed once a day. A seller missing from "
    "that registry is missing here; that is not the same as not selling.",
    "“Payers” are endpoint counts summed: a wallet paying two endpoints counts twice. A wallet is "
    "not an agent.",
    "“Money” is paid calls times list price. It is an estimate, not settled revenue, and it "
    "misleads for sellers whose price varies per call.",
    "Where a seller lists several prices, the page shows the range. A single over/under verdict "
    "against the going rate is given only when it holds for every endpoint the seller lists.",
    "Movement is the change in a rolling 30-day total between stored days, not a daily count.",
    "Self-dealing is not filtered. A seller can pay its own endpoint, and those calls count here like any "
    "others. A high rank is a count of paid calls, not a judgement that a service is good, safe or real.",
    "“Who actually paid” is read straight off Base: x402 payments are the transfers a facilitator settled on "
    "a buyer’s signature, in the last day only. A wallet is not a person, and one operator can hold many. "
    "“One payer” means every x402 payment came from one wallet; “concentrated” means ten or more payments "
    "with the busiest three wallets sending 80% or more. Both are facts about the payers, not verdicts on "
    "the seller. Hosts paid into one wallet are grouped: usually one operator, sometimes a platform "
    "collecting for several.",
]


MARK = "Claimed by owner"
# This sentence travels WITH the mark, on the seller's own page. A reader lands there,
# not on claim.html. The mark may never be shown without it (tested).
DISCLAIMER = ("“Claimed by owner” means the owner proved control of this host. It is not an endorsement, "
              "a safety check, or a judgement that the service is good or real.")


def load_claims(path):
    """{host: {"description", "logo", "links": [{"label","url"}], "claimed_on"}} or {}.
    Everything in it was typed by a stranger with a credit card. Text is escaped like any
    other; a URL is kept only if it is plain https."""
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        raw = json.load(f)
    out = {}
    for host, c in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(c, dict):
            continue
        ok = lambda u: isinstance(u, str) and re.match(r"^https://[^\s\"'<>]{3,300}$", u) is not None
        links = [{"label": str(l.get("label", ""))[:40], "url": l["url"]}
                 for l in (c.get("links") or [])[:3] if isinstance(l, dict) and ok(l.get("url"))]
        out[host.lower()] = {"description": str(c.get("description", ""))[:300],
                             "logo": c["logo"] if ok(c.get("logo")) else None,
                             "links": links, "claimed_on": str(c.get("claimed_on", ""))[:10]}
    return out


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def slug(host):
    return re.sub(r"[^a-z0-9._-]", "-", host.lower())[:200]


def money(x):
    if 0 < x < 0.01:                  # a sub-cent total is not $0.00
        return "$%s" % ("{:.6f}".format(x).rstrip("0"))
    return "$%s" % ("{:,.0f}".format(x) if x >= 100 else "{:,.2f}".format(x))


def price(x):
    return "$%g" % x if x else "—"


def span(hours):
    """The pulled window as words: "24 h" for a day, "8 days" for the rolling window."""
    return "%.0f h" % hours if hours < 48 else "%d days" % round(hours / 24.0)


STOP = set("""with from your this that have will into over more than when what which their them they then
also each every other only some such very most many much make made does done using used use uses user users
data agent agents api apis service services endpoint endpoints request requests response responses return
returns returned result results provide provides provided get gets give gives given based real time live
full fast simple easy free paid price prices priced pay pays call calls json http https x402 usdc base chain
support supports supported including include includes available access information info details detail
query queries search searches list lists format formats any all one two for and the via per new best""".split())


def rival_scores(words):
    """For each host, the hosts selling something like it. Shared words are weighed by
    rarity (IDF): two sellers sharing "liquidation" are rivals, two sharing "data" are not."""
    import math
    n = len(words)
    df = {}
    for ws in words.values():
        for w in ws:
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log(n / c) for w, c in df.items()}
    by_word = {}
    for h, ws in words.items():
        for w in ws:
            if idf[w] >= 2.5:                      # words in more than ~8% of sellers say nothing
                by_word.setdefault(w, []).append(h)
    out = {}
    for h, ws in words.items():
        score, shared = {}, {}
        for w in ws:
            for h2 in by_word.get(w, ()):
                if h2 != h:
                    score[h2] = score.get(h2, 0.0) + idf[w]
                    shared[h2] = shared.get(h2, 0) + 1
        out[h] = [(sc, h2) for h2, sc in score.items() if shared[h2] >= 2 and sc >= 9.0]
    return out


def spark(points, w=520, h=120):
    """The replay as an inline SVG line. points: [(date, calls)]"""
    if len(points) < 2:
        return '<p class="muted">One stored day so far. Movement appears from the second.</p>'
    ys = [p[1] for p in points]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1
    pad = 10
    xs = [pad + i * (w - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    pts = ["%.1f,%.1f" % (x, h - pad - (y - lo) * (h - 2 * pad) / span) for x, y in zip(xs, ys)]
    dots = "".join('<circle cx="%s" cy="%s" r="3"><title>%s: %s paid calls (30 d)</title></circle>'
                   % (p.split(",")[0], p.split(",")[1], esc(d), "{:,}".format(c))
                   for p, (d, c) in zip(pts, points))
    return ('<svg class="spark" viewBox="0 0 %d %d" role="img" aria-label="Paid calls, rolling 30 days, '
            'by stored day"><polyline points="%s"/>%s</svg><div class="axis"><span>%s</span><span>%s</span></div>'
            % (w, h, " ".join(pts), dots, esc(points[0][0]), esc(points[-1][0])))


# The house look lives in atlas_style.py, written once; these names stay for every caller.
HEAD, FOOT, CSS = atlas_style.HEAD, atlas_style.FOOT, atlas_style.CSS


def load_chain(path):
    """The day's whale rollup (whales.py --out), keyed by host, or None. What the chain says
    about who actually paid each seller; every number in it is read straight off Base."""
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    if not d.get("classified"):
        return None
    return {"hours": d.get("hours") or 24, "as_of": d.get("as_of") or "", "sellers": {s["host"]: s for s in d["sellers"]},
            "operators": d.get("operators") or {}, "groups": d.get("groups") or [],
            "totals": d.get("totals") or {}, "agents": d.get("agents") or [], "buyers": d.get("buyers") or [],
            "dates": d.get("dates") or [],
            # the chains the rollup's pulls covered: Base alone before 2026-10-09. whales.py says so
            # itself ("chains", read from the files, a quiet chain included); an older rollup has
            # only the chains that took a payment
            "chains": d.get("chains") or sorted((d.get("totals") or {}).get("by_chain") or {}) or ["Base"]}


def operator_line(host, chain, free=False):
    op = chain["operators"].get(host)
    if not op:
        return ""
    g = chain.get("by_host", {}).get(host)
    link = ('<a href="%s/o/%s/">%s</a>' % (SITE, esc(g["slug"]), esc(g["name"]))) if g else "the group"
    if g and g["claimed"]:
        return ('<p class="muted">Payments to <b>%d hosts</b> land in this same wallet. The group is claimed by its operator, '
                "%s (that mark means the operator proved control of the hosts; it is not an endorsement).</p>" % (op["hosts"], link))
    if free:        # the other hosts are the group's record: on its page, in the full record
        return ('<p class="muted">Payments to <b>%d hosts</b> land in this same wallet — usually one operator, sometimes a '
                "platform collecting for several. The group’s page: %s.</p>" % (op["hosts"], link))
    return ('<p class="muted">Payments to <b>%d hosts</b> land in this same wallet — usually one operator, sometimes a '
            "platform collecting for several: %s%s. The group’s page: %s.</p>"
            % (op["hosts"], ", ".join(esc(h) for h in op["others"][:6]),
               " and %d more" % (op["hosts"] - 1 - 6) if op["hosts"] - 1 > 6 else "", link))


def payer_link(w, chain):
    """A named payer wallet: to its buyer page when one was written, else to the explorer."""
    b = buyer_pages.slug(w["wallet"])
    if b in (chain.get("buyer_pages") or {}):
        return '<a href="%s"><code>%s</code></a> %s' % (esc(buyer_pages.link(w["wallet"], SITE)), esc(w["short"]), "{:,}".format(w["payments"]))
    return ('<a rel="nofollow noopener" href="%s"><code>%s</code></a> %s'
            % (esc(whales.explorer(w["wallet"])), esc(w["short"]), "{:,}".format(w["payments"])))


PAID_LOCKED = "the wallets that paid it, each with its payments, and the share the busiest three sent"


def paid_section(host, me, chain, free=False):
    """'Who actually paid': the seller's x402 payments in the window, from how many wallets,
    how concentrated, the wallets named — and the operator its wallet belongs to. Facts with
    their evidence; the word for concentration is defined on the page. In the free tier
    (tiers.py) one summary line stays: the payments, the payer wallets, the concentration
    label; the wallets and their shares are in the full record, and the page says where."""
    if chain is None:
        return ""
    s = chain["sellers"].get(host)
    hours = chain["hours"]
    pulled = chain.get("chains") or ["Base"]
    # the chain this seller was paid on, else the pulled chain it lists: the one the words name
    on = (s or {}).get("chain") or next((c for c in pulled if c in me["chains"]), pulled[0])
    if len((s or {}).get("by_chain") or {}) > 1:
        # paid on both chains: the figures below are the two together, and the words say so
        on = " and ".join(sorted(s["by_chain"]))
    p = ['<h2>Who actually paid</h2><p class="dateline">x402 payments on %s · %s</p>' % (esc(on), esc(atlas_style.chain_day(chain)))]
    if not any(c in me["chains"] for c in pulled):
        p.append('<p class="muted">This seller takes payment on %s. The daily pull reads %s only, so the chain '
                 "has nothing to say here yet.</p>" % (esc(", ".join(me["chains"]) or "another chain"), esc(" and ".join(pulled))))
        p.append(operator_line(host, chain, free))
        return "".join(p)
    if not s or not s["on_chain_payments_x402"]:
        other = s["on_chain_usdc"] if s else 0
        p.append('<p class="muted">In the last %s on %s, no x402 payment reached this seller’s wallet%s.%s</p>'
                 % (span(hours), esc(on), "s" if len(me["wallets"]) != 1 else "",
                    (" %s reached it by ordinary transfer, which is not a call being bought." % money(other)) if other else ""))
        p.append(operator_line(host, chain, free))
        return "".join(p)
    n, m, top3 = s["on_chain_payments_x402"], s["x402_payer_wallets"], s["x402_top3_share"]
    word = s["concentration"]
    tag = '<span class="tag">%s</span> ' % esc(word) if word in ("one payer", "concentrated") else ""
    if m == 1:
        spread = "all of them from one wallet"
    elif free:
        spread = "from %s wallets" % "{:,}".format(m)
    else:
        spread = "from %s wallets; the busiest three sent %d%%" % ("{:,}".format(m), top3)
    p.append("<p>%sIn the last %s on %s, <b>%s x402 payments</b> (%s) reached this seller’s wallet%s, %s.%s</p>"
             % (tag, span(hours), esc(on), "{:,}".format(n), money(s["on_chain_usdc_x402"]), "s" if len(s["wallets"]) != 1 else "", spread,
                (" Another %s reached the same wallet%s by ordinary transfer, which is not a call being bought."
                 % (money(s["on_chain_usdc"] - s["on_chain_usdc_x402"]), "s" if len(s["wallets"]) != 1 else ""))
                if s["on_chain_usdc"] - s["on_chain_usdc_x402"] >= 1 else ""))
    if free:
        p.append(tiers.locked_html(PAID_LOCKED, SITE))
    else:
        p.append('<p class="muted">The busiest wallets that paid it:</p><ul class="payers">%s</ul>'
                 % "".join("<li>%s payments</li>" % payer_link(w, chain) for w in s["x402_top_payers"]))
    p.append(operator_line(host, chain, free))
    return "".join(p)


REL_NOTE = ("Relationships are patterns in the x402 payments we observe on Base over the window: a buyer is a wallet "
            "that paid this seller’s payTo wallet, and came back means it paid on two or more different days. A wallet "
            "is not an agent, and a relationship is a pattern of payments, not a claim about who anyone is or who runs "
            "a wallet. Bought alongside and the switches leave out wallets that paid more than %d sellers in the window: "
            "a wallet that pays everyone says nothing about what goes together." % relationships.BUSY)
# The free tier shows one line of the facts; the note keeps only what that line needs defined.
REL_NOTE_FREE = REL_NOTE[:REL_NOTE.index(" Bought alongside")]
REL_LOCKED = ("its most loyal buyers, what is bought alongside it, who left it for whom, who came to it from where, "
              "and its early buyers, each with the counts behind it")


def _n(x):
    return "{:,}".format(x)


def _s(n, word, plural=None):
    return "%s %s" % (_n(n), word if n == 1 else (plural or word + "s"))


def wallet_link(w, chain):
    """A buyer wallet: to its buyer page when one was written, else to the explorer."""
    short = w[:6] + "…" + w[-4:]
    if buyer_pages.slug(w) in ((chain or {}).get("buyer_pages") or {}):
        return '<a href="%s"><code>%s</code></a>' % (esc(buyer_pages.link(w, SITE)), esc(short))
    return '<a rel="nofollow noopener" href="%s"><code>%s</code></a>' % (esc(whales.explorer(w)), esc(short))


def seller_link(wallet, rel, known, here):
    """Another seller, linked to the page of one of its wallet's hosts: the most particular (a host
    listed on many wallets names none of them well), then the busiest, and not this page's own host
    when there is another. Plain text when none of its hosts has a page here."""
    hs = rel["wallet_hosts"].get(wallet) or []
    paged = [h for h in hs if h in known and h != here] or [h for h in hs if h in known]
    if paged:
        h = min(paged, key=lambda x: (len(rel["hosts"].get(x, ())), -known[x], x))
        out = '<a href="%s/s/%s/">%s</a>' % (SITE, esc(slug(h)), esc(h))
    else:
        out = esc(hs[0] if hs else wallet[:6] + "…" + wallet[-4:])
    if len(hs) > 1:
        out += " and %s on its wallet" % _s(len(hs) - 1, "more host")
    return out


def _days(ds):
    ds = [atlas_style.short_date(d) for d in ds]
    return ds[0] if len(ds) == 1 else "%s – %s" % (ds[0], ds[-1]) if ds else "—"


def wallet_facts(f, rel, known, chain, it, here):
    """One payTo wallet's relationship facts as plain sentences, the numbers behind each shown."""
    b, cb = f["buyers"], f["came_back"]
    p = ["<p><b>%s</b> paid %s over x402 on %d of the window’s %s: %s, %s.</p>"
         % (_s(b["count"], "buyer"), it, f["days"]["paid"], _s(f["days"]["window"], "day"),
            _s(b["payments"], "payment"), money(b["usdc"]))]
    for note in f["notes"]:
        p.append('<p class="muted">%s.</p>' % esc(note[:1].upper() + note[1:]))
    p.append("<p><b>%s of %s came back</b> on another day (%.0f%%).</p>"
             % (_n(cb["buyers"]), _s(cb["of"], "buyer"), cb["rate_pct"]))
    if f["loyal"]:
        p.append('<p class="muted">The buyers that paid on the most days, then the most times:</p><ul class="cav">%s</ul>'
                 % "".join("<li>%s paid on %s (%s)</li>" % (wallet_link(x["wallet"], chain), _s(x["days"], "day"),
                                                             _s(x["payments"], "payment")) for x in f["loyal"]))
    along, busy = f["bought_alongside"]["sellers"], f["bought_alongside"]["busy_buyers_left_out"]
    if along:
        p.append('<ul class="cav">%s</ul>' % "".join(
            "<li>Bought alongside: %s (%s, %.0f%% of %s’s buyers)</li>"
            % (seller_link(x["wallet"], rel, known, here), _s(x["shared_buyers"], "shared buyer"), x["share_pct"], it) for x in along))
    else:
        p.append('<p class="muted">Bought alongside: no other seller shares a buyer with %s in the window%s.</p>'
                 % (it, ", busy wallets left out" if busy else ""))
    sw = f["switches"]
    if sw["left_for"] or sw["came_from"]:
        p.append('<ul class="cav">%s%s</ul>' % (
            "".join("<li>%s left for %s</li>" % (_s(x["buyers"], "buyer"), seller_link(x["wallet"], rel, known, here)) for x in sw["left_for"]),
            "".join("<li>%s came from %s</li>" % (_s(x["buyers"], "buyer"), seller_link(x["wallet"], rel, known, here)) for x in sw["came_from"])))
    if rel["halves"]["first"] and f["days"]["paid"] >= 2:
        p.append('<p class="muted">Left for: buyers who paid %s only on %s and started paying the other only on %s. '
                 "Came from: the reverse.%s%s</p>"
                 % (it, esc(_days(rel["halves"]["first"])), esc(_days(rel["halves"]["second"])),
                    "" if sw["left_for"] or sw["came_from"] else " No buyer did either in this window.",
                    (" %s of its buyers paid more than %d sellers and %s left out of bought alongside and the switches."
                     % (_n(busy), relationships.BUSY, "is" if busy == 1 else "are")) if busy else ""))
    e = f["early_buyers"]
    if e:
        p.append("<p><b>Early buyers:</b> %s paid it on %s, before its daily buyers went from %s on the first day of the "
                 "window to %s on the last.</p>"
                 % (_s(e["wallets"], "wallet"), esc(" and ".join(atlas_style.short_date(d) for d in e["days"])),
                    _n(e["first_day_buyers"]), _n(e["last_day_buyers"])))
    return "".join(p)


def wallet_line(f, it):
    """The one line the free tier keeps of a wallet's relationship facts: buyers in the window,
    how many came back, with the numbers behind each."""
    b, cb = f["buyers"], f["came_back"]
    p = ["<p><b>%s</b> paid %s over x402 on %d of the window’s %s: %s, %s. <b>%s of %s came back</b> on another day (%.0f%%).</p>"
         % (_s(b["count"], "buyer"), it, f["days"]["paid"], _s(f["days"]["window"], "day"),
            _s(b["payments"], "payment"), money(b["usdc"]), _n(cb["buyers"]), _s(cb["of"], "buyer"), cb["rate_pct"])]
    for note in f["notes"]:
        p.append('<p class="muted">%s.</p>' % esc(note[:1].upper() + note[1:]))
    return "".join(p)


def relationships_section(host, me, rel, known, chain, free=False):
    """'Relationships': who came back, what was bought alongside, who left for whom, the early
    buyers. Read from the flows window, per payTo wallet; every number shown. In the free
    tier (tiers.py) one line stays, buyers and who came back; the lists are in the full
    record, and the page says where."""
    p = ["<h2>Relationships</h2>"]
    if rel is None:
        p.append('<p class="muted">The on-chain window was not loaded for this build, so the relationships between this '
                 "seller and its buyers are not shown.</p>")
        return "".join(p)
    if not rel["dates"]:
        p.append('<p class="muted">The on-chain window was loaded but held no day that could be read, so the relationships '
                 "between this seller and its buyers are not shown.</p>")
        return "".join(p)
    p.append('<p class="dateline">x402 payments on Base · %s · %s</p>'
             % (esc(atlas_style.chain_day({"dates": rel["dates"]})), _s(len(rel["dates"]), "day")))
    if rel.get("problems"):
        p.append('<p class="muted">Part of the window could not be read, so these facts may be short: %s.</p>'
                 % esc("; ".join(str(x) for x in rel["problems"][:3])))
    view = relationships.for_host(rel, host)
    if view is None:
        if "Base" not in me["chains"]:
            p.append('<p class="muted">This seller takes payment on %s. The window reads Base only, so it has no '
                     "relationships to show here yet.</p>" % esc(", ".join(me["chains"]) or "another chain"))
        else:
            p.append('<p class="muted">This seller’s wallet is not in the window’s sellers map, so no payment to it was read.</p>')
        return "".join(p)
    if not view["wallets"]:
        p.append('<p class="muted">No x402 payment reached this seller’s wallet%s on Base in the window, so it has no '
                 "buyers to read relationships from.</p>" % ("s" if len(view["unpaid_wallets"]) != 1 else ""))
        p.append('<p class="muted">%s</p>' % esc(REL_NOTE))
        return "".join(p)
    ws = view["wallets"]
    if free:
        if len(ws) > 1:
            p.append('<p class="muted">This host is paid into %s that were paid in the window; the line below is its '
                     "busiest wallet’s, across every host paid into it.</p>" % _s(len(ws), "wallet"))
        p.append(wallet_line(ws[0], "this wallet" if ws[0]["hosts_total"] > 1 or len(ws) > 1 else "this seller"))
        p.append(tiers.locked_html(REL_LOCKED, SITE))
        p.append('<p class="muted">%s</p>' % esc(REL_NOTE_FREE))
        return "".join(p)
    if len(ws) > 1:
        p.append('<p class="muted">This host is paid into %s that were paid in the window. Each wallet is read on its own, '
                 "across every host paid into it%s.</p>"
                 % (_s(len(ws), "wallet"), "; the three with the most buyers are shown here, and the paid answer carries all %d"
                    % len(ws) if len(ws) > 3 else ""))
    for f in ws[:3]:
        shared = f["hosts_total"] > 1
        if len(ws) > 1:
            p.append('<h3 style="margin-top:22px">Wallet <code>%s</code></h3>' % esc(f["wallet"][:6] + "…" + f["wallet"][-4:]))
        if shared:
            others = [h for h in rel["wallet_hosts"].get(f["wallet"], []) if h != host.lower()]
            p.append('<p class="muted">This wallet also takes payment for %s%s; the facts below are the wallet’s, across %s.</p>'
                     % (", ".join(esc(h) for h in others[:6]), " and %d more" % (len(others) - 6) if len(others) > 6 else "",
                        "both hosts" if f["hosts_total"] == 2 else "all %d hosts" % f["hosts_total"]))
        p.append(wallet_facts(f, rel, known, chain, "this wallet" if shared or len(ws) > 1 else "this seller", host.lower()))
    p.append('<p class="muted">%s</p>' % esc(REL_NOTE))
    return "".join(p)


def endpoints_section(me):
    """What is actually bought, at what price: the seller's busiest endpoints, from the
    registry's own per-endpoint counts. Absent for snapshots made before this was kept."""
    eps = me.get("top_endpoints") or []
    if not eps:
        return ""
    p = ['<h2>Endpoints</h2><p class="muted">The busiest of this seller’s %d endpoint%s in the registry, by paid calls '
         "over 30 days; price and chain per endpoint.</p>" % (me["endpoints"], "s" if me["endpoints"] != 1 else "")]
    p.append('<div class="tw"><table><tr><th>endpoint</th><th class="n">paid calls</th><th class="n">payers</th>'
             '<th class="n">price</th><th>chain</th></tr>')
    for e in eps:
        p.append('<tr><td class="h"><code>%s</code></td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                 % (esc(e["path"]), "{:,}".format(e["calls"]), "{:,}".format(e["payers"]), price(e["price"]), esc(e["network"])))
    p.append("</table></div>")
    if me["endpoints"] > len(eps):
        p.append('<p class="muted">%d more endpoints not shown.</p>' % (me["endpoints"] - len(eps)))
    return "".join(p)


def build(out, store=None, site=None, claims=None, whales=None, operators=None, flows=None, flows_dir=None, free=None):
    """Write the whole site. free: None for the switch (tiers.FREE_TIER_ONLY), True for the free
    tier, False for the whole record public, as the site was built before 2026-10-05."""
    global SITE
    if site:
        SITE = site.rstrip("/")      # a local address, for looking at the pages before they are public
    if store:
        radar.STORE = store
    free = tiers.free(free)
    tier = tiers if free else None          # the page builders read the switch through this, and import no tiers
    if free:
        # A free build writes only what the free tier shows, so it must not land on pages an
        # earlier build left: a seller, wallet or group missing from today's data would keep
        # its whole record at a public address. The Atlas builds into a fresh _site every day.
        old = [d for d in ("s", "b", "o") if os.path.isdir(os.path.join(out, d))]
        if old:
            raise SystemExit("seller_pages: the free tier builds into a fresh folder; %s already holds %s/ from an "
                             "earlier build" % (out, "/, ".join(old)))
    foot = atlas_style.foot(free)
    chain = load_chain(whales)
    rel = relationships.window(flows_dir) if flows_dir else None     # the flows window, read once for every page
    claimed_ops = operator_pages.load_operators(operators if operators is not None else os.path.join(HERE, "operators.json"))
    snaps = radar.snapshots()
    if not snaps:
        sys.exit("seller-pages: no snapshots")
    loaded = [radar.load_snapshot(f) for f in snaps[-30:]]
    new = loaded[-1]
    A = new["sellers"]
    as_of = new["date"]
    n = len(A)
    by_calls = [h for h, _ in sorted(A.items(), key=lambda kv: -kv[1]["calls"])]
    by_take = [h for h, _ in sorted(A.items(), key=lambda kv: -kv[1]["take"])]
    rank_c = {h: i + 1 for i, h in enumerate(by_calls)}
    rank_t = {h: i + 1 for i, h in enumerate(by_take)}
    total = sum(s["calls"] for s in A.values()) or 1
    words = {h: set(re.findall(r"[a-z]{4,}", s["sells"].lower())) - STOP for h, s in A.items()}
    rivals_of = rival_scores(words)
    known = {h.lower(): s["calls"] for h, s in A.items()}               # hosts with a page here, for the relationships' links

    claimed = load_claims(claims if claims is not None else os.path.join(HERE, "claims.json"))
    sdir = os.path.join(out, "s")
    os.makedirs(sdir, exist_ok=True)
    atlas_style.write_assets(out, free)
    with open(os.path.join(sdir, "radar.css"), "w") as f:     # the old address, for pages cached before atlas.css
        f.write('@import url("../atlas.css");\n')
    ctx = {"root": SITE, "css": SITE + "/atlas.css"}
    index = []
    group_slugs, groups_listing = [], []
    if chain is not None:
        # buyers first, so the operator pages link a wallet to its page only when it exists
        chain["buyer_pages"], _buyers_listing = buyer_pages.build(out, chain, A, ctx, as_of, n, site=SITE, head=HEAD, foot=foot,
                                                                   issues=ISSUES, tier=tier)
        chain["by_host"], groups_listing = operator_pages.build(out, chain, A, ctx, as_of, n, operators=claimed_ops, site=SITE,
                                                                 head=HEAD, foot=foot, issues=ISSUES, buy_url=BUY_OPERATOR,
                                                                 buyers=chain["buyer_pages"], tier=tier)
        group_slugs = operator_pages.built_slugs(groups_listing, tiers.TOP if free else None)   # the sitemap names the pages with a record on them
    drew_map = build_map(out, whales, chain, flows, A, as_of, foot)

    for host, me in A.items():
        sl = slug(host)
        hist = [(s["date"], s["sellers"][host]["calls"]) for s in loaded if host in s["sellers"]]
        change = None
        if len(hist) > 1 and hist[0][1]:
            change = 100.0 * (hist[-1][1] - hist[0][1]) / hist[0][1]
        riv_all = sorted(((sc, A[h2]["calls"], h2) for sc, h2 in rivals_of[host]), reverse=True)
        riv = riv_all[:8]
        priced = [A[h2]["price_med"] for _o, _c, h2 in riv_all if A[h2]["price_med"]]
        going = radar.median(priced)

        title = "%s — how this x402 seller is doing · %s" % (host, market.BRAND)
        desc = "%s: rank %d of %d x402 sellers by paid calls, %s paid calls in 30 days. As of %s." % (
            host, rank_c[host], n, "{:,}".format(me["calls"]), as_of)
        p = [HEAD % dict(ctx, title=esc(title), desc=esc(desc), canon=esc("%s/s/%s/" % (SITE, sl)))]
        sells = me["sells"] + ("…" if len(me["sells"]) >= 140 else "")     # the snapshot keeps 140 characters
        category = market.cat(me["sells"] + " " + host)[0]
        s_chain = ((chain or {}).get("sellers") or {}).get(host) or {}
        op = ((chain or {}).get("operators") or {}).get(host)
        p.append('<main id="main"><p class="crumbs"><a href="%s/s/">Sellers</a> / %s / %s</p>'
                 '<div class="ident"><span class="avatar seller" aria-hidden="true">%s</span><div><h1>%s</h1>'
                 '<p class="sells">%s</p></div></div>'
                 % (SITE, esc(category), esc(host), esc(re.sub(r"[^a-z0-9]", "", host.lower())[:2] or "·"),
                    esc(host), esc(atlas_style.unsay(sells)) or "—"))
        mine = claimed.get(host.lower())
        state = '<span class="tag mark">%s</span>' % esc(MARK) if mine else '<span class="tag">unclaimed page</span>'
        p.append('<p>%s%s<span class="tag">%d endpoint%s</span>%s<span class="tag">as of %s</span></p>'
                 % (state, "".join('<span class="tag">%s</span>' % esc(c) for c in me["chains"][:4]),
                    me["endpoints"], "s" if me["endpoints"] != 1 else "",
                    ('<span class="tag">one of %d hosts paid into one wallet</span>' % op["hosts"]) if op else "",
                    esc(atlas_style.long_date(as_of))))
        if mine:
            p.append('<p class="muted disclaimer">%s</p>' % esc(DISCLAIMER))
            p.append('<div class="owner"><h2>In the owner’s words</h2>%s<p class="sells">%s</p>%s</div>' % (
                '<img class="logo-owner" src="%s" alt="%s logo, as the owner supplied it" loading="lazy" referrerpolicy="no-referrer">'
                % (esc(mine["logo"]), esc(host)) if mine["logo"] else "",
                esc(atlas_style.unsay(mine["description"])) or "—",
                "".join('<a class="olink" rel="nofollow ugc noopener" href="%s">%s</a>'
                        % (esc(l["url"]), esc(l["label"] or l["url"])) for l in mine["links"])))
        # The Atlas Score lands here later. Until it does, the slot stays empty and hidden.
        p.append('<aside id="atlas-score" aria-label="Atlas Score" hidden></aside>')
        chg = ""
        if change is not None:
            chg = '<div class="tile"><b class="%s">%+.0f%%</b><span>paid calls since %s</span></div>' % (
                "up" if change >= 0 else "down", change, esc(atlas_style.short_date(hist[0][0])))
        onchain = ""
        if s_chain.get("on_chain_payments_x402"):
            day = atlas_style.chain_day(chain)
            onchain = ('<div class="tile"><b>%s</b><span>x402 payments on Base, %s</span></div>'
                       '<div class="tile"><b>%s</b><span>USDC, x402-settled, %s</span></div>'
                       % ("{:,}".format(s_chain["on_chain_payments_x402"]), esc(day),
                          money(s_chain.get("on_chain_usdc_x402") or 0.0), esc(day)))
        p.append('<section aria-label="The numbers"><div class="tiles">'
                 '<div class="tile"><b>#%d</b><span>of %s sellers, by paid calls</span></div>'
                 '<div class="tile"><b>%s</b><span>paid calls in 30 days, self-reported</span></div>'
                 '%s'
                 '<div class="tile"><b>%s</b><span>payers in 30 days, self-reported (see notes)</span></div>'
                 '<div class="tile"><b>%s</b><span>%s</span></div>'
                 '<div class="tile"><b>%s</b><span>est. money at list price · rank #%d</span></div>%s</div></section>'
                 % (rank_c[host], "{:,}".format(n), "{:,}".format(me["calls"]), onchain, "{:,}".format(me["payers"]),
                    esc(radar.price_label(me)) if me["price_max"] else "—",
                    "price per call" if me["price_min"] == me["price_max"]
                    else "price per call, across %d endpoints" % me["endpoints"],
                    money(me["take"]), rank_t[host], chg))
        p.append('<div class="cols"><div>')
        p.append(paid_section(host, me, chain, free))
        p.append(relationships_section(host, me, rel, known, chain, free))
        # every seller page points its owner at the buyers report; a claimed page already has its owner
        p.append('<p class="box">%s <a href="%s/sellers/?host=%s">See who your buyers are</a>: every wallet that paid '
                 "you, day by day, and where the ones that left went, in one report.</p>"
                 % ("For the owner:" if claimed.get(host.lower()) else "Is this your service?", SITE,
                    esc(quote(host.lower(), safe=""))))
        p.append(endpoints_section(me))
        p.append('<h2>The replay</h2><p class="dateline">Paid calls, rolling 30 days · %s</p>%s'
                 % (esc(" to ".join(atlas_style.long_date(d) for d in sorted({hist[0][0], hist[-1][0]}))), spark(hist)))
        if riv:
            p.append('<h2>Selling something like this</h2><p class="muted">Matched automatically from each '
                     "seller’s own short description. It will sometimes be wrong; tell us and we fix it.</p>"
                     '<div class="tw"><table><tr><th>seller</th>'
                     '<th class="n">paid calls</th><th class="n">price</th><th>sells</th></tr>')
            for _o, c, h2 in riv:
                p.append('<tr><td class="h"><a href="%s/s/%s/">%s</a></td><td class="n">%s</td><td class="n">%s</td>'
                         "<td>%s</td></tr>" % (SITE, esc(slug(h2)), esc(h2), "{:,}".format(c),
                                               esc(radar.price_label(A[h2])) if A[h2]["price_max"] else "—",
                                               esc(atlas_style.unsay(A[h2]["sells"][:110]))))
            p.append("</table></div>")
            v = radar.price_verdict(me, going)
            if v == "mixed":
                p.append('<p class="muted">Going rate, the median of the %d matched sellers with a listed price '
                         "(of %d matched): %s a call. This seller’s endpoints run %s, and the going rate falls "
                         "inside that range — so no single over/under verdict is fair. Compare per endpoint.</p>"
                         % (len(priced), len(riv_all), price(going), esc(radar.price_label(me))))
            elif v:
                p.append('<p class="muted">Going rate, the median of the %d matched sellers with a listed price '
                         "(of %d matched): %s a call. This seller charges %s, which is <b>%s</b> it%s.</p>"
                         % (len(priced), len(riv_all), price(going), esc(radar.price_label(me)), v,
                            "" if me["price_min"] == me["price_max"] else " on every endpoint"))
        p.append('</div><aside aria-label="For the seller and for agents">')
        if not mine:
            group = (chain or {}).get("operators", {}).get(host)
            p.append('<div class="claim"><h3>Is this your service?</h3><p>Claim this page: add your own words, '
                     "your logo and links, a “claimed by owner” mark, and get the full competitive report — you "
                     "against every rival, day by day. Or see <b>who is buying in your category</b>: the "
                     "wallets paying sellers like you, read off the chain, yours beside your rivals’.%s</p>"
                     '<a class="btn" href="%s/claim.html?host=%s">Claim this page</a></div>'
                     % ((" Your wallet is paid through <b>%d hosts</b>: put one name on the group as a "
                         "<b>claimed operator</b>." % group["hosts"]) if group else "",
                        SITE, esc(host)))
        p.append('<div class="box"><p class="eyebrow" style="margin:0">For AI agents</p><h3 style="margin-top:6px">This page, as an '
                 'answer your agent can pay for</h3><p class="muted">The same report card as JSON — rivals, the full replay, who '
                 "actually paid this seller, and its relationships — over x402 on Base: <code>GET %s/who/%s</code>, a cent a call, paid in USDC "
                 "by the agent itself. A refusal is never charged.</p>"
                 '<pre class="code"><span class="c">$</span> curl %s/who/%s\n<span class="p">402</span> Payment Required '
                 '<span class="c">→ the agent pays $0.01 in USDC on Base</span>\n<span class="k">200</span> '
                 '{"host": "%s", "rank_by_calls": %d, …}</pre><p class="muted"><a href="%s/docs/#who">How the paid API works</a></p></div>'
                 % (API, esc(host), API, esc(host), esc(host), rank_c[host], SITE))
        p.append('</aside></div>')
        p.append('<h2>How to read these numbers</h2><ul class="cav">%s</ul></main>'
                 % "".join("<li>%s</li>" % esc(c) for c in CAVEATS))
        p.append(foot % {"root": SITE, "issue": esc("%s&title=%s" % (CORRECT, "Correction:+" + host)), "as_of": esc(as_of),
                         "n": "{:,}".format(n)})
        d = os.path.join(sdir, sl)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write("".join(p))
        index.append([host, sl, me["calls"], me["payers"], round(me["take"], 2), me["price_med"],
                      me["sells"][:90], market.cat(me["sells"] + " " + host)[0],
                      ((chain or {}).get("sellers", {}).get(host) or {}).get("on_chain_payments_x402") or 0])

    index.sort(key=lambda r: -r[2])
    with open(os.path.join(sdir, "index.json"), "w") as f:
        json.dump({"as_of": as_of, "sellers": index}, f, separators=(",", ":"))
    rows = "".join('<tr><td class="n">%d</td><td class="h"><a href="%s/s/%s/">%s</a></td><td class="n">%s</td>'
                   '<td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                   % (i + 1, SITE, esc(r[1]), esc(r[0]), "{:,}".format(r[2]), price(r[5]), money(r[4]), esc(atlas_style.unsay(r[6])))
                   for i, r in enumerate(index[:300]))
    page = [HEAD % dict(ctx, title="Every x402 seller, ranked · " + market.BRAND,
                        desc="All %d sellers in the x402 agent economy, ranked by paid calls, with a page each. As of %s."
                        % (n, as_of), canon=SITE + "/s/")]
    page.append('<main id="main"><p class="eyebrow">Sellers · as of %s</p><h1>Every seller in the agent economy</h1><p class="sells">' % esc(atlas_style.long_date(as_of)) + '%s services sell to software '
                "agents over x402. %s paid calls in the last 30 days. Each one has a page here, rebuilt from a "
                'daily photograph of the public registry.</p><label class="vh" for="q">Find a seller</label><input id="q" type="search" placeholder="Find a seller by name or by '
                'what it sells…" autocomplete="off"><div class="tw"><table id="t"><thead><tr><th class="n">#</th>'
                '<th>seller</th><th class="n">paid calls</th><th class="n">price</th><th class="n">est. money</th>'
                "<th>sells</th></tr></thead><tbody>%s</tbody></table></div>"
                '<p class="muted">Showing the top 300. Search finds all %s.</p></main>'
                % ("{:,}".format(n), "{:,}".format(total), rows, "{:,}".format(n)))
    page.append("""<script>
const q=document.getElementById('q'),tb=document.querySelector('#t tbody'),first=tb.innerHTML;let D=null;
const e=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pr=x=>x?'$'+(+x):'—',mo=x=>'$'+(x>=100?Math.round(x).toLocaleString():(+x).toFixed(2));
q.addEventListener('input',async()=>{const v=q.value.trim().toLowerCase();if(!v){tb.innerHTML=first;return}
if(!D)D=(await (await fetch('index.json')).json()).sellers;
tb.innerHTML=D.map((r,i)=>[r,i]).filter(([r])=>(r[0]+' '+r[6]).toLowerCase().includes(v)).slice(0,200)
.map(([r,i])=>`<tr><td class="n">${i+1}</td><td class="h"><a href="${e(r[1])}/">${e(r[0])}</a></td><td class="n">${r[2].toLocaleString()}</td><td class="n">${pr(r[5])}</td><td class="n">${mo(r[4])}</td><td>${e(r[6])}</td></tr>`).join('')
||'<tr><td colspan="6">No seller matches that.</td></tr>'});
</script>""")
    page.append(foot % {"root": SITE, "issue": esc(ISSUES), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(sdir, "index.html"), "w") as f:
        f.write("".join(page))

    claim = [HEAD % dict(ctx, title="For sellers: claim your page · " + market.BRAND,
                         desc="Claim your x402 service's page on the Atlas, or get a competitive report on it.",
                         canon=SITE + "/claim.html")]
    claim.append("""<main id="main"><p class="eyebrow">For sellers</p><h1 id="h">Your service already has a page here.</h1>
<p class="sells">Every seller in the x402 registry does: rank, paid calls, payers, price, rivals, and the day-by-day
replay. %(numbers)s They come from the public registry and are the same for everyone.
What you can buy is your own voice on your page, %(deeper)s.</p>
<p class="muted" id="which"></p>
<form class="form" id="hostform" style="margin-top:18px"><div><label for="host">Your service’s host</label>
<input id="host" type="text" inputmode="url" autocomplete="off" placeholder="api.example.com"></div>
<p class="muted" id="hostnote" role="status" aria-live="polite" style="margin:0">Every checkout below carries the host it is for,
so we know which page you are claiming. Type it here first.</p></form>
<div class="offers">
<div class="offer"><h3>Claimed page</h3><div class="p">$29<span class="muted"> / month</span></div><ul>
<li>The “unclaimed” label becomes <b>Claimed by owner</b></li><li>Your own description, logo and links</li>
<li>A competitive report every month</li><li>Corrections handled first</li><li>Cancel any time</li></ul>
<a class="btn buy" href="#host" data-checkout="%s">Claim my page</a></div>
<div class="offer"><h3>Competitive report</h3><div class="p">$49<span class="muted"> once</span></div><ul>
<li>You against every rival, day by day</li><li>Where your price sits against the going rate</li>
<li>Who entered and who left your corner</li><li>The caveats, stated plainly</li>
<li>A private page and PDF, within 5 business days</li></ul>
<a class="btn buy" href="#host" data-checkout="%s">Get my report</a></div>
<div class="offer"><h3>Who is buying in your category</h3><div class="p">$149<span class="muted"> once</span></div><ul>
<li>Every wallet paying sellers like you, read straight off Base</li><li>Payments, USDC, whom else they pay</li>
<li>Agents at work set apart from one-off buyers</li><li>Your buyers beside your rivals’</li>
<li>A private page and CSV, within 5 business days</li></ul>
<a class="btn buy" href="#host" data-checkout="%s">See who is buying</a></div>
<div class="offer"><h3>Claimed operator</h3><div class="p">$49<span class="muted"> / month</span></div><ul>
<li>One name across every host paid into your wallet</li><li>An operator page, with the wallet evidence</li>
<li>A <b>Claimed by operator</b> mark on each host’s page</li><li>Your hosts’ buyers, concentration and money read together, every day</li>
<li>A monthly note on what changed across your group</li><li>Corrections handled first</li><li>Cancel any time</li></ul>
<a class="btn buy" href="#host" data-checkout="%s">Name my group</a></div></div>
<h2>What “claimed by owner” and “claimed by operator” mean, and do not</h2><p class="muted">They mean the owner
proved control of the service’s host, or of the hosts the registry lists under one wallet. <b>Either mark is
not an endorsement, a safety check, or a judgement that a service is good or real.</b> We do not sell rank, and we do
not vouch for anyone. The buyers report is business analytics about your own market: x402 payments a facilitator
settled, Base only, over the window; a wallet is not a person.</p>
<h2>How claiming works</h2><p class="muted">After checkout we send you one line of text. Put it in a file at
<code>/.well-known/x402-atlas.txt</code> on your service’s host. That proves the service is yours. A person does
this by hand for now: allow up to 5 business days. If you have paid and heard nothing in 2 business days,
<a href="%s?title=I+paid+and+heard+nothing">tell us here</a> and you go to the front. Refunds on request.
This is business analytics about your own service, not financial advice.</p>
<h2>Not a seller?</h2><p class="muted">Everyone can <a href="%(site)s/s/">browse %(browse)s</a> for free. An agent
gets the same report card, with who actually paid, over x402 at <code>%(api)s/who/&lt;host&gt;</code> — a cent a call on
Base, paid by the agent itself.</p></main>
<script>const h=(new URLSearchParams(location.search).get('host')||'').toLowerCase().replace(/[^a-z0-9._:-]/g,'').slice(0,253);
if(h){document.getElementById('h').textContent=h+' already has a page here.';
document.getElementById('which').innerHTML='Claiming: <a href="s/'+encodeURIComponent(h.replace(/:/g,'-'))+'/">'+h+'</a>';
}
// A checkout never leaves without the host it is for: Polar gets it as ?reference_id=<host>.
const clean=v=>(v||'').toLowerCase().trim().replace(/^https?:\/\//,'').replace(/\/.*$/,'').replace(/[^a-z0-9._:-]/g,'').slice(0,253);
const hi=document.getElementById('host'),note=document.getElementById('hostnote');
// The page holds only each checkout's id: the address is put together on a click, never on load,
// so a robot that opens this page at ?host= does not find live checkout links (2026-10-08).
function arm(v){const x=clean(v);return /^[a-z0-9-]+(\.[a-z0-9-]+)+(:\d+)?$/.test(x)?x:'';}
hi.value=h;
document.getElementById('hostform').addEventListener('submit',e=>e.preventDefault());
document.querySelectorAll('a.buy').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();const x=arm(hi.value);
if(!x){hi.focus();note.textContent='Type your service’s host first, like api.example.com: the checkout needs it to know which page is yours.';return;}
location.href='https://buy.'+'polar.sh/'+a.dataset.checkout+'?reference_id='+encodeURIComponent(x);}));
</script>""".replace("%(numbers)s", tiers.PLACE if free else "The numbers are never for sale.")
                 .replace("%(deeper)s", "a deeper look at your corner of the market, and the full record" if free
                          else "and a deeper look at your corner of the market")
                 .replace("%(browse)s", "every seller’s basic card" if free else "all sellers")
                 .replace("%(site)s", SITE).replace("%(api)s", API)
                 % (esc(checkout_id(BUY_VERIFIED)), esc(checkout_id(BUY_REPORT)), esc(checkout_id(BUY_BUYERS)),
                    esc(checkout_id(BUY_OPERATOR)), esc(ISSUES)))
    claim.append(foot % {"root": SITE, "issue": esc(ISSUES), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(out, "claim.html"), "w") as f:
        f.write("".join(claim))

    pro_page(out, ctx, as_of, n, foot=foot, free=free)
    site_pages.build(out, ctx, as_of, n, site=SITE, api=API, head=HEAD, foot=foot, issues=ISSUES, buy_pro=BUY_PRO,
                     sample=sellers_sample(rel, A, as_of), buy_sellers=BUY_SELLERS, free=free)

    door = front_door.build(out, chain, A, loaded, ctx, as_of, SITE, HEAD, foot, ISSUES, API, groups_listing,
                            buyers=(chain or {}).get("buyer_pages"), map_=drew_map, free=free)

    with open(os.path.join(out, "sitemap-sellers.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write("<url><loc>%s/</loc><lastmod>%s</lastmod></url>\n" % (SITE, as_of))
        f.write("<url><loc>%s/s/</loc><lastmod>%s</lastmod></url>\n" % (SITE, as_of))
        for r in index:
            f.write("<url><loc>%s/s/%s/</loc><lastmod>%s</lastmod></url>\n" % (SITE, esc(r[1]), as_of))
        if group_slugs:
            f.write("<url><loc>%s/o/</loc><lastmod>%s</lastmod></url>\n" % (SITE, as_of))
        for sl in group_slugs:
            f.write("<url><loc>%s/o/%s/</loc><lastmod>%s</lastmod></url>\n" % (SITE, esc(sl), as_of))
        if drew_map:
            f.write("<url><loc>%s/map/</loc><lastmod>%s</lastmod></url>\n" % (SITE, as_of))
        f.write("</urlset>\n")
    return {"as_of": as_of, "sellers": n, "groups": len(groups_listing), "door": door, "out": out, "map": drew_map,
            "free": free, "groups_built": len(group_slugs)}


def sellers_sample(rel, A, as_of):
    """The /sellers/ page's sample: the busiest seller's wallet in the build's own window, blurred
    by the report's own rule (x402/seller_report.py). None without a window."""
    if not rel or not rel.get("dates") or "ledger" not in rel:
        return None
    sys.path.insert(0, os.path.join(HERE, "x402"))
    import seller_report
    pick = seller_report.busiest(rel, A, full=True)
    if pick is None:
        return None
    row = next((v for k, v in A.items() if k.lower() == pick[0]), None)
    body = seller_report.build(rel, pick[0], row, as_of)
    return seller_report.sample_from(body, pick[1]) if body and body["wallets"] else None


# The Free and Pro table on /pro.html, for the whole record public and for the free tier.
PRO_TABLE = [("Every seller, operator and buyer page", "yes", "yes"),
             ("Search, the map, the day’s numbers", "yes", "yes"),
             ("The whole day as CSV and JSON", "—", "yes"),
             ("Every payer wallet and operator group in one file", "—", "yes")]
PRO_TABLE_FREE = [("Every seller’s basic card", "yes", "yes"),
                  ("Search, the map, the live feed, the day’s numbers, the top %d lists" % tiers.TOP, "yes", "yes"),
                  ("Every buyer wallet and every operator", "—", "yes"),
                  ("The wallets that paid each seller, and its relationships, in full", "—", "yes"),
                  ("The whole day as CSV and JSON", "—", "yes")]


def pro_page(out, ctx, as_of, n, foot=None, free=None):
    """/pro.html: Atlas Pro, the same record as working data. The columns come from the
    service that serves them (x402/pro.py), so the page cannot promise a column the
    export does not have."""
    sys.path.insert(0, os.path.join(HERE, "x402"))
    import pro
    free = tiers.free(free)
    foot = foot if foot is not None else atlas_style.foot(free)
    p = [HEAD % dict(ctx, title="Atlas Pro: the record as data · " + market.BRAND,
                     desc="Atlas Pro: every x402 seller, buyer wallet and wallet group as CSV and JSON, refreshed "
                          "every morning. $49 a month.", canon=SITE + "/pro.html")]
    buy = (atlas_style.checkout(BUY_PRO, "Subscribe") if BUY_PRO else
           '<p class="muted"><b>The subscription opens soon.</b> The exports are built and served; the '
           'checkout is the last piece.</p>')
    p.append("""<main id="main"><div class="hero"><div><p class="eyebrow">Atlas Pro</p>
<h1>The whole record, as data, every morning.</h1>
<p class="sells">The same record the Atlas shows, as working data: every seller, every wallet that paid over x402,
and every group of hosts paid into one wallet, in files a spreadsheet or a program can read. %(free_line)s</p></div>
<div class="tier feature"><div class="p">$49 <small>a month</small></div><p class="muted" style="margin:0">One license key. Cancel any time.</p>
%s<p class="muted" style="margin:0">Need a licence for a team or a feed? <a href="%s/contact/">Contact us</a>. All plans: <a href="%s/pricing/">pricing</a>.</p></div></div>
<div class="cards">
<div class="card"><p class="eyebrow" style="margin:0 0 6px">01 · Daily</p><h3>Four exports, every morning</h3><p>%s, rebuilt when the daily scan lands.</p></div>
<div class="card"><p class="eyebrow" style="margin:0 0 6px">02 · Honest</p><h3>Two sources, never blended</h3><p>What sellers report to the registry, beside what the chain shows they were paid.</p></div>
<div class="card"><p class="eyebrow" style="margin:0 0 6px">03 · Simple</p><h3>One key, one header</h3><p>Polar issues the key when you subscribe. %d calls an hour per key, for scripts, agents and notebooks.</p></div>
</div>""".replace("%(free_line)s", "Every seller’s basic card is free, as it was. Pro is the full record: every buyer wallet "
                                 "and every operator, and the whole day at once, every morning, without scraping it."
                                 if free else "Every page of the Atlas\nstays free. Pro is for when you want the whole day "
                                 "at once, every morning, without scraping it.")
             % (buy, SITE, SITE, esc(", ".join(pro.EXPORTS)), pro.PER_HOUR))
    import watch_service                        # the watch doors' own price
    p.append('<div class="box" id="watch"><p class="eyebrow" style="margin:0">With your Pro key</p>'
             '<h3 style="margin-top:6px"><a href="%s/watch/">Watch your agents</a></h3>'
             '<p class="muted" style="margin:0">What 1 to %d wallets spent over x402 on Base, with whom, and whether the sellers '
             'they paid are up, read from the chain, not from a payment tool. The wallets and your key stay in your browser. '
             'One wallet at a time without a key: %s over x402.</p></div>'
             % (SITE, watch_service.spend_watch.MAX_WALLETS, esc(watch_service.PRICE)))
    p.append('<h2 id="exports">The four exports</h2>')
    for name, (what, cols) in pro.EXPORTS.items():
        p.append('<div class="card" style="margin-top:12px"><h3><code>/pro/export/%s</code></h3><p>%s.</p>' % (esc(name), esc(what[:1].upper() + what[1:])))
        if cols:
            p.append('<p class="chips">%s</p>' % " ".join("<code>%s</code>" % esc(c) for c in cols))
        p.append("</div>")
    p.append("""<h2>How to call it</h2><p class="muted">After checkout, Polar sends you a license key. Send it in the
<code>%s</code> header:</p>
<pre class="code"><span class="c">$</span> curl -H "%s: YOUR-KEY" %s/pro/export/sellers.csv -o sellers.csv</pre>
<p class="muted">Without a key, or with one that is unknown, revoked or expired, the answer is a 401 and a plain sentence
saying which. <code>GET %s/pro</code> describes all of this as JSON, no key needed. When the newest market snapshot is
more than %d days old the exports are refused rather than sold stale. The full reference is in the <a href="%s/docs/#exports">docs</a>.</p>
<h2>Who it is for</h2><ul class="cav"><li>Funds and analysts sizing agent commerce.</li><li>Sellers watching their rivals and their buyers.</li>
<li>Builders whose agents choose which services to pay.</li><li>Institutions, platforms and facilitators: a data licence or feed, <a href="%s/contact/">talk to us</a>.</li></ul>
<h2>Free and Pro</h2><div class="tw"><table><tr><th>What you get</th><th>Free</th><th>Pro</th></tr>
%s</table></div>
<h2>What the numbers are, and are not</h2><ul class="cav">%s</ul></main>"""
             % (esc(pro.HEADER), esc(pro.HEADER), API, API, pro.who_service.MAX_AGE_DAYS, SITE, SITE,
                "\n".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in (PRO_TABLE_FREE if free else PRO_TABLE)),
                "".join("<li>%s</li>" % esc(c) for c in CAVEATS + [c[:1].upper() + c[1:] + "." for c in pro.CAVEATS[-2:]])))
    p.append(foot % {"root": SITE, "issue": esc(ISSUES), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(out, "pro.html"), "w") as f:
        f.write("".join(p))


def build_map(out, whales, chain, flows, A, as_of, foot=FOOT):
    """/map/ from the day's flows: the flows file for the rollup's own day, found beside the
    rollup in the store (or given as --flows). Without one the map is left as it was."""
    if chain is None:
        if flows:
            print("map: no rollup to go with %s; /map/ not rebuilt" % flows)
        return None
    # the rollup is named for the build day (as_of) and covers the day before (dates):
    # the flows file it was made from is named for the covered day
    day = ((chain.get("dates") or [""])[-1]) or chain.get("as_of")
    path = flows or map_page.flows_beside(whales, day)
    if not os.path.exists(path):
        print("map: no flows-%s.json beside the rollup; /map/ not rebuilt" % day)
        return None
    try:
        r = map_page.build(out, path, whales, A, SITE, as_of, head=HEAD, foot=foot, issues=ISSUES)
    except (OSError, ValueError, KeyError, TypeError) as e:     # a bad day of flows costs the map, not the Atlas
        print("map: %s would not draw (%s: %s); /map/ not rebuilt" % (path, type(e).__name__, e))
        return None
    print("map: %d x402 payments between %d wallets and %d sellers; drew %d of %d lines"
          % (r["payments"], r["wallets"], r["sellers"], r["drawn"], r["edges"]))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", required=True)
    ap.add_argument("--store", default=None)
    ap.add_argument("--site", default=None, help="base address the pages will be served from")
    ap.add_argument("--claims", default=None, help="claims.json (default: beside this file, if it exists)")
    ap.add_argument("--whales", default=None, help="the day's whales.py rollup, for 'Who actually paid' and the operator pages")
    ap.add_argument("--operators", default=None, help="operators.json (default: beside this file, if it exists)")
    ap.add_argument("--flows", default=None, help="the day's flows-<date>.json, for the map (default: beside the rollup)")
    ap.add_argument("--flows-dir", default=None, help="the on-chain window, a folder of flows-<date>.json "
                    "(flows_handoff.py fetch keeps one), for each seller's Relationships")
    tiers.add_flags(ap)
    a = ap.parse_args()
    r = build(a.out, a.store, a.site, a.claims, a.whales, a.operators, a.flows, a.flows_dir, free=tiers.from_args(a))
    print("wrote %d seller pages and %d operator pages (%d with a record on them), as of %s, into %s%s"
          % (r["sellers"], r["groups"], r["groups_built"], r["as_of"], r["out"], ": the free tier" if r["free"] else ": the whole record"))


if __name__ == "__main__":
    main()
