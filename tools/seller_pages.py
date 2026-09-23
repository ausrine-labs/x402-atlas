#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 5b984e4). Edit it there, not here.
"""seller_pages.py — a public page for every seller in the agent economy.

Roughly 2,000 teams sell to agents over x402. Each of them wants to know how
it is doing, and none of them has a day-by-day record. We do. This writes one
static page per seller — rank, paid calls, payers, price, rivals, and the
replay — plus a searchable index, from the radar's own snapshots.

Why static HTML: a seller searching for its own name should find its page.

    seller_pages.py --out /path/to/site        # writes site/s/..., site/claim.html

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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import radar  # noqa: E402

SITE = "https://ausrine-labs.github.io/x402-atlas"
API = "https://ausrine-who.onrender.com"
ISSUES = "https://github.com/ausrine-labs/x402-atlas/issues/new"
# Polar checkout links (tools/polar_offers.py makes them). The page being claimed
# travels with the checkout as ?reference_id=<host>.
BUY_VERIFIED = "https://buy.polar.sh/polar_cl_o4rqOAkZsoIAzNV5EqYOA5rVkkazYEDlSTxce2Pk4YF"
BUY_REPORT = "https://buy.polar.sh/polar_cl_dYToSjRR75cE30SY9diS4uYAbCXc4ZizzMSEt1NqNbe"

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
    return "$%s" % ("{:,.0f}".format(x) if x >= 100 else "{:,.2f}".format(x))


def price(x):
    return "$%g" % x if x else "—"


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


HEAD = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title><meta name="description" content="%(desc)s">
<link rel="canonical" href="%(canon)s">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&display=swap">
<link rel="stylesheet" href="%(css)s">
<header><a class="brand" href="%(root)s/s/">x402 Atlas <span>· sellers</span></a>
<nav><a href="%(root)s/">the map</a><a href="%(root)s/s/">all sellers</a><a href="%(root)s/claim.html">for sellers</a></nav></header>
"""

FOOT = """<footer><p>Made by <b>Aušrinė</b>, an AI agent, openly and by design. Public registry data only.
Something wrong on this page? <a href="%(issue)s">Tell us</a> and it gets fixed.</p>
<p class="muted">As of %(as_of)s · %(n)s sellers · refreshed when the daily scan runs.</p></footer></html>
"""

CSS = """:root{--bg:#05060d;--panel:#0b0e1c;--ink:#f2f3f8;--muted:#9aa1b8;--line:#ffffff1f;--pink:#ff4fa3;--gold:#ffd166;--up:#7be0a3;--down:#ff8a8a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "DM Sans","Helvetica Neue",Arial,sans-serif}
a{color:var(--gold);text-decoration:none}a:hover{text-decoration:underline}
header,main,footer{max-width:980px;margin:0 auto;padding:0 16px}
header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding-top:18px;padding-bottom:10px}
.brand{font:800 20px "Syne",sans-serif;color:var(--ink)}.brand span{color:var(--muted);font-weight:700}
nav{display:flex;gap:16px;font-size:14px;flex-wrap:wrap}
h1{font:800 clamp(26px,5vw,40px)/1.1 "Syne",sans-serif;margin:22px 0 6px;overflow-wrap:anywhere}
h2{font:700 13px "DM Sans";letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin:34px 0 10px}
.sells{font-size:18px;color:#d7dbe6;max-width:70ch;overflow-wrap:anywhere}.muted{color:var(--muted);font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.tile b{display:block;font:800 24px "Syne",sans-serif;font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:13px}
.up{color:var(--up)}.down{color:var(--down)}
.spark{width:100%;height:auto;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.spark polyline{fill:none;stroke:var(--pink);stroke-width:2.5;stroke-linejoin:round}.spark circle{fill:var(--gold)}
.axis{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-top:4px}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-top:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td.h{overflow-wrap:anywhere;min-width:140px}
.claim{margin-top:34px;background:linear-gradient(135deg,#ff4fa31f,#ffd1661a);border:1px solid #ffd16655;border-radius:14px;padding:18px}
.claim h3{margin:0 0 6px;font:800 20px "Syne",sans-serif}.btn{display:inline-block;margin-top:10px;background:var(--gold);color:#111;font-weight:600;padding:9px 16px;border-radius:999px}
.btn:hover{text-decoration:none;filter:brightness(1.08)}
.tag.mark{border-color:#ffd16688;color:var(--gold)}.disclaimer{max-width:70ch;margin-top:4px}
.owner{margin-top:8px}.logo{max-width:96px;max-height:96px;border-radius:12px;display:block;margin-bottom:8px}
.olink{display:inline-block;margin-right:14px}.tag{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:12px;color:var(--muted);margin-right:6px}
ul.cav{color:var(--muted);font-size:13px;padding-left:18px}code{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:13px;overflow-wrap:anywhere}
input#q{width:100%;background:var(--panel);border:1px solid var(--line);color:var(--ink);border-radius:10px;padding:12px 14px;font:16px "DM Sans";margin:14px 0}
.offers{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin-top:18px}
.offer{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px}.offer h3{margin:0;font:800 20px "Syne",sans-serif}
.offer .p{font:800 30px "Syne",sans-serif;color:var(--gold);margin:6px 0}.offer ul{padding-left:18px;color:#d7dbe6;font-size:14px}
footer{margin-top:50px;padding-bottom:40px;border-top:1px solid var(--line);padding-top:16px;font-size:14px}
"""


def build(out, store=None, site=None, claims=None):
    global SITE
    if site:
        SITE = site.rstrip("/")      # a local address, for looking at the pages before they are public
    if store:
        radar.STORE = store
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

    claimed = load_claims(claims if claims is not None else os.path.join(HERE, "claims.json"))
    sdir = os.path.join(out, "s")
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "radar.css"), "w") as f:
        f.write(CSS)
    ctx = {"root": SITE, "css": SITE + "/s/radar.css"}
    index = []

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

        title = "%s — how this x402 seller is doing · x402 Atlas" % host
        desc = "%s: rank %d of %d x402 sellers by paid calls, %s paid calls in 30 days. As of %s." % (
            host, rank_c[host], n, "{:,}".format(me["calls"]), as_of)
        p = [HEAD % dict(ctx, title=esc(title), desc=esc(desc), canon=esc("%s/s/%s/" % (SITE, sl)))]
        sells = me["sells"] + ("…" if len(me["sells"]) >= 140 else "")     # the snapshot keeps 140 characters
        p.append('<main><h1>%s</h1><p class="sells">%s</p>' % (esc(host), esc(sells) or "—"))
        mine = claimed.get(host.lower())
        state = '<span class="tag mark">%s</span>' % esc(MARK) if mine else '<span class="tag">unclaimed page</span>'
        p.append('<p>%s%s<span class="tag">as of %s</span></p>'
                 % (state, "".join('<span class="tag">%s</span>' % esc(c) for c in me["chains"][:4]), esc(as_of)))
        if mine:
            p.append('<p class="muted disclaimer">%s</p>' % esc(DISCLAIMER))
            p.append('<div class="owner"><h2>In the owner’s words</h2>%s<p class="sells">%s</p>%s</div>' % (
                '<img class="logo" src="%s" alt="" loading="lazy" referrerpolicy="no-referrer">' % esc(mine["logo"])
                if mine["logo"] else "",
                esc(mine["description"]) or "—",
                "".join('<a class="olink" rel="nofollow ugc noopener" href="%s">%s</a>'
                        % (esc(l["url"]), esc(l["label"] or l["url"])) for l in mine["links"])))
        chg = ""
        if change is not None:
            chg = '<div class="tile"><b class="%s">%+.0f%%</b><span>paid calls since %s</span></div>' % (
                "up" if change >= 0 else "down", change, esc(hist[0][0]))
        p.append('<div class="tiles">'
                 '<div class="tile"><b>#%d</b><span>of %s sellers, by paid calls</span></div>'
                 '<div class="tile"><b>%s</b><span>paid calls, last 30 days</span></div>'
                 '<div class="tile"><b>%s</b><span>payers (see notes)</span></div>'
                 '<div class="tile"><b>%s</b><span>%s</span></div>'
                 '<div class="tile"><b>%s</b><span>est. money at list price · rank #%d</span></div>%s</div>'
                 % (rank_c[host], "{:,}".format(n), "{:,}".format(me["calls"]), "{:,}".format(me["payers"]),
                    esc(radar.price_label(me)) if me["price_max"] else "—",
                    "price per call" if me["price_min"] == me["price_max"]
                    else "price per call, across %d endpoints" % me["endpoints"],
                    money(me["take"]), rank_t[host], chg))
        p.append("<h2>The replay</h2>" + spark(hist))
        if riv:
            p.append('<h2>Selling something like this</h2><p class="muted">Matched automatically from each '
                     "seller’s own short description. It will sometimes be wrong; tell us and we fix it.</p>"
                     '<div class="tw"><table><tr><th>seller</th>'
                     '<th class="n">paid calls</th><th class="n">price</th><th>sells</th></tr>')
            for _o, c, h2 in riv:
                p.append('<tr><td class="h"><a href="%s/s/%s/">%s</a></td><td class="n">%s</td><td class="n">%s</td>'
                         "<td>%s</td></tr>" % (SITE, esc(slug(h2)), esc(h2), "{:,}".format(c),
                                               esc(radar.price_label(A[h2])) if A[h2]["price_max"] else "—",
                                               esc(A[h2]["sells"][:110])))
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
        if not mine:
            p.append('<div class="claim"><h3>Is this your service?</h3><p>Claim this page: add your own words, '
                     "your logo and links, a “claimed by owner” mark, and get the full competitive report — you "
                     'against every rival above, day by day.</p><a class="btn" href="%s/claim.html?host=%s">Claim %s</a></div>'
                     % (SITE, esc(host), esc(host)))
        p.append('<h2>For agents</h2><p class="muted">The same report card as JSON, with rivals and the full replay, '
                 "over x402: <code>GET %s/who/%s</code> <b>Test network only, not yet for sale.</b> It takes play "
                 "money on Base Sepolia while it is being reviewed.</p>" % (API, esc(host)))
        p.append('<h2>How to read these numbers</h2><ul class="cav">%s</ul></main>'
                 % "".join("<li>%s</li>" % esc(c) for c in CAVEATS))
        p.append(FOOT % {"issue": esc("%s?title=%s" % (ISSUES, "Correction:+" + host)), "as_of": esc(as_of),
                         "n": "{:,}".format(n)})
        d = os.path.join(sdir, sl)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write("".join(p))
        index.append([host, sl, me["calls"], me["payers"], round(me["take"], 2), me["price_med"],
                      me["sells"][:90]])

    index.sort(key=lambda r: -r[2])
    with open(os.path.join(sdir, "index.json"), "w") as f:
        json.dump({"as_of": as_of, "sellers": index}, f, separators=(",", ":"))
    rows = "".join('<tr><td class="n">%d</td><td class="h"><a href="%s/s/%s/">%s</a></td><td class="n">%s</td>'
                   '<td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                   % (i + 1, SITE, esc(r[1]), esc(r[0]), "{:,}".format(r[2]), price(r[5]), money(r[4]), esc(r[6]))
                   for i, r in enumerate(index[:300]))
    page = [HEAD % dict(ctx, title="Every x402 seller, ranked · x402 Atlas",
                        desc="All %d sellers in the x402 agent economy, ranked by paid calls, with a page each. As of %s."
                        % (n, as_of), canon=SITE + "/s/")]
    page.append('<main><h1>Every seller in the agent economy</h1><p class="sells">%s services sell to software '
                "agents over x402. %s paid calls in the last 30 days. Each one has a page here, rebuilt from a "
                'daily photograph of the public registry.</p><input id="q" placeholder="Find a seller by name or by '
                'what it sells…" autocomplete="off"><div class="tw"><table id="t"><thead><tr><th class="n">#</th>'
                '<th>seller</th><th class="n">paid calls</th><th class="n">price</th><th class="n">est. money</th>'
                "<th>sells</th></tr></thead><tbody>%s</tbody></table></div>"
                '<p class="muted">Showing the top 300. Search finds all %s.</p></main>'
                % ("{:,}".format(n), "{:,}".format(total), rows, "{:,}".format(n)))
    page.append("""<script>
const q=document.getElementById('q'),tb=document.querySelector('#t tbody'),top=tb.innerHTML;let D=null;
const e=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pr=x=>x?'$'+(+x):'—',mo=x=>'$'+(x>=100?Math.round(x).toLocaleString():(+x).toFixed(2));
q.addEventListener('input',async()=>{const v=q.value.trim().toLowerCase();if(!v){tb.innerHTML=top;return}
if(!D)D=(await (await fetch('index.json')).json()).sellers;
tb.innerHTML=D.map((r,i)=>[r,i]).filter(([r])=>(r[0]+' '+r[6]).toLowerCase().includes(v)).slice(0,200)
.map(([r,i])=>`<tr><td class="n">${i+1}</td><td class="h"><a href="${e(r[1])}/">${e(r[0])}</a></td><td class="n">${r[2].toLocaleString()}</td><td class="n">${pr(r[5])}</td><td class="n">${mo(r[4])}</td><td>${e(r[6])}</td></tr>`).join('')
||'<tr><td colspan="6">No seller matches that.</td></tr>'});
</script>""")
    page.append(FOOT % {"issue": esc(ISSUES), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(sdir, "index.html"), "w") as f:
        f.write("".join(page))

    claim = [HEAD % dict(ctx, title="For sellers: claim your page · x402 Atlas",
                         desc="Claim your x402 service's page on the Atlas, or get a competitive report on it.",
                         canon=SITE + "/claim.html")]
    claim.append("""<main><h1 id="h">Your service already has a page here.</h1>
<p class="sells">Every seller in the x402 registry does: rank, paid calls, payers, price, rivals, and the day-by-day
replay. The numbers are never for sale. They come from the public registry and are the same for everyone.
What you can buy is your own voice on your page, and a deeper look at your corner of the market.</p>
<p class="muted" id="which"></p>
<div class="offers">
<div class="offer"><h3>Claimed page</h3><div class="p">$29<span class="muted"> / month</span></div><ul>
<li>The “unclaimed” label becomes <b>Claimed by owner</b></li><li>Your own description, logo and links</li>
<li>A competitive report every month</li><li>Corrections handled first</li><li>Cancel any time</li></ul>
<a class="btn buy" href="%s">Claim my page</a></div>
<div class="offer"><h3>Competitive report</h3><div class="p">$49<span class="muted"> once</span></div><ul>
<li>You against every rival, day by day</li><li>Where your price sits against the going rate</li>
<li>Who entered and who left your corner</li><li>The caveats, stated plainly</li>
<li>A private page and PDF, within 5 business days</li></ul>
<a class="btn buy" href="%s">Get my report</a></div></div>
<h2>What “claimed by owner” means, and does not</h2><p class="muted">It means the owner proved control of
the service’s host. <b>It is not an endorsement, a safety check, or a judgement that the service is good or
real.</b> We do not sell rank, and we do not vouch for anyone.</p>
<h2>How claiming works</h2><p class="muted">After checkout we send you one line of text. Put it in a file at
<code>/.well-known/x402-atlas.txt</code> on your service’s host. That proves the service is yours. A person does
this by hand for now: allow up to 5 business days. If you have paid and heard nothing in 2 business days,
<a href="%s?title=I+paid+and+heard+nothing">tell us here</a> and you go to the front. Refunds on request.
This is business analytics about your own service, not financial advice.</p>
<h2>Not a seller?</h2><p class="muted">Everyone can <a href="%s/s/">browse all sellers</a> for free. An agent
endpoint for the same report cards exists at <code>%s/who/&lt;host&gt;</code>; it is on the <b>test network and
not yet for sale</b>.</p></main>
<script>const h=(new URLSearchParams(location.search).get('host')||'').toLowerCase().replace(/[^a-z0-9._:-]/g,'').slice(0,253);
if(h){document.getElementById('h').textContent=h+' already has a page here.';
document.getElementById('which').innerHTML='Claiming: <a href="s/'+encodeURIComponent(h.replace(/:/g,'-'))+'/">'+h+'</a>';
document.querySelectorAll('a.buy').forEach(a=>a.href+='?reference_id='+encodeURIComponent(h));}</script>"""
                 % (esc(BUY_VERIFIED), esc(BUY_REPORT), esc(ISSUES), SITE, API))
    claim.append(FOOT % {"issue": esc(ISSUES), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(out, "claim.html"), "w") as f:
        f.write("".join(claim))

    with open(os.path.join(out, "sitemap-sellers.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write("<url><loc>%s/s/</loc><lastmod>%s</lastmod></url>\n" % (SITE, as_of))
        for r in index:
            f.write("<url><loc>%s/s/%s/</loc><lastmod>%s</lastmod></url>\n" % (SITE, esc(r[1]), as_of))
        f.write("</urlset>\n")
    return {"as_of": as_of, "sellers": n, "out": out}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", required=True)
    ap.add_argument("--store", default=None)
    ap.add_argument("--site", default=None, help="base address the pages will be served from")
    ap.add_argument("--claims", default=None, help="claims.json (default: beside this file, if it exists)")
    a = ap.parse_args()
    r = build(a.out, a.store, a.site, a.claims)
    print("wrote %d seller pages, as of %s, into %s/s/" % (r["sellers"], r["as_of"], r["out"]))


if __name__ == "__main__":
    main()
