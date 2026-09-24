#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 76e0e62). Edit it there, not here.
"""operator_pages.py — a page for every wallet group: the hosts paid into one wallet.

The registry counts hosts; the chain shows which of them are paid into the same
wallet. seller_pages.py calls build() with the day's rollup and writes one page
per group at /o/<group>/ — the hosts, the group's x402 payments and payers,
concentration, the money that was not a call — with "unclaimed" where a name
would go, and an offer to put one there. A claimed group (operators.json) gets
its name, words, logo and links and a "Claimed by operator" mark, which never
appears without the sentence that says what it does not mean (tested).

Usually a group is one operator; sometimes it is a platform collecting for
several. The page says so and never says more than the wallet shows.
Stranger text is escaped on the way out. Standard library only.
"""

import collections
import html
import json
import os
import re

MARK = "Claimed by operator"
DISCLAIMER = ("“Claimed by operator” means the operator proved control of the hosts the registry lists under "
              "this wallet. It is not an endorsement, a safety check, or a judgement that any of these services "
              "is good or real. The numbers on these pages are never for sale.")
UNCLAIMED = ("Hosts paid into one wallet are usually one operator, sometimes a platform collecting for several. "
             "Nobody has put a name on this group yet.")
PLATFORM_SUFFIXES = ("workers.dev", "vercel.app", "run.app", "onrender.com", "fly.dev", "up.railway.app",
                     "netlify.app", "github.io", "herokuapp.com", "pages.dev", "zeabur.app", "ts.net")


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def slug(x):
    return re.sub(r"[^a-z0-9._-]", "-", x.lower())[:200]


def registrable(host):
    """The part of a host that names its owner: the last two labels, or three under
    a hosting platform's domain, and any port dropped."""
    h = host.split(":")[0].lower()
    parts = h.split(".")
    for suf in PLATFORM_SUFFIXES:
        if h.endswith("." + suf):
            n = suf.count(".") + 2
            return ".".join(parts[-n:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def group_name(hosts):
    """A group is named by the domain most of its hosts share; a tie goes to the first."""
    c = collections.Counter(registrable(h) for h in hosts)
    return c.most_common(1)[0][0]


def load_operators(path):
    """{name: {"hosts": [...], "description", "logo", "links", "claimed_on"}} or {}.
    Typed by a stranger with a credit card: escaped on the way out, and a URL is kept
    only if it is plain https."""
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        raw = json.load(f)
    out = {}
    ok = lambda u: isinstance(u, str) and re.match(r"^https://[^\s\"'<>]{3,300}$", u) is not None
    for name, c in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(c, dict) or not isinstance(c.get("hosts"), list):
            continue
        links = [{"label": str(l.get("label", ""))[:40], "url": l["url"]}
                 for l in (c.get("links") or [])[:3] if isinstance(l, dict) and ok(l.get("url"))]
        out[str(name)[:80]] = {"hosts": [str(h).lower() for h in c["hosts"] if isinstance(h, str)],
                               "description": str(c.get("description", ""))[:300],
                               "logo": c["logo"] if ok(c.get("logo")) else None,
                               "links": links, "claimed_on": str(c.get("claimed_on", ""))[:10]}
    return out


def money(x):
    return "$%s" % ("{:,.0f}".format(x) if x >= 100 else "{:,.2f}".format(x))


def group_facts(g, chain, A):
    """What the window says about a group, summed over its hosts."""
    S = chain["sellers"]
    hosts = g["hosts"]
    rows, payers = [], collections.Counter()
    x402 = usdc = other = 0.0
    payer_wallets = 0
    calls30 = sum(A.get(h, {}).get("calls", 0) for h in hosts)
    for h in hosts:
        s = S.get(h)
        n = (s or {}).get("on_chain_payments_x402") or 0
        if s:
            x402 += n
            usdc += s.get("on_chain_usdc_x402", 0.0) or 0.0
            other += (s.get("on_chain_usdc", 0.0) or 0.0) - (s.get("on_chain_usdc_x402", 0.0) or 0.0)
            payer_wallets += s.get("x402_payer_wallets") or 0
            for t in s.get("x402_top_payers") or []:
                payers[t["wallet"]] += t["payments"]
        rows.append({"host": h, "x402": n, "calls30": A.get(h, {}).get("calls", 0),
                     "word": (s or {}).get("concentration"), "sells": A.get(h, {}).get("sells", "")[:90]})
    rows.sort(key=lambda r: (-r["x402"], -r["calls30"], r["host"]))
    return {"hosts": len(hosts), "wallets": g["wallets"], "x402": int(x402), "usdc": usdc, "other": max(other, 0.0),
            "payer_wallets_summed": payer_wallets, "paid_hosts": sum(1 for r in rows if r["x402"]),
            "calls30": calls30, "top_payers": payers.most_common(5), "rows": rows}


def build(out, chain, A, ctx, as_of, n_sellers, operators=None, site="", head="", foot="", issues="", buy_url=""):
    """Write /o/<group>/index.html for every group and /o/ for the list. Returns
    {host: {"slug", "name", "claimed"}} for the seller pages to link to."""
    operators = operators or {}
    groups = chain.get("groups") or []
    odir = os.path.join(out, "o")
    os.makedirs(odir, exist_ok=True)
    by_host, listing, seen = {}, [], {}
    for g in groups:
        base = slug(group_name(g["hosts"]))
        sl = base if base not in seen else "%s-%d" % (base, g["id"])
        seen[sl] = True
        mine = next(((nm, o) for nm, o in operators.items() if any(h in g["hosts"] for h in o["hosts"])), None)
        name = mine[0] if mine else group_name(g["hosts"])
        f = group_facts(g, chain, A)
        for h in g["hosts"]:
            by_host[h] = {"slug": sl, "name": name, "claimed": bool(mine)}
        title = "%s — %d hosts paid into one wallet · x402 Atlas" % (name, f["hosts"])
        desc = "%d x402 hosts paid into one wallet: %s x402 payments in the window, %s. As of %s." % (
            f["hosts"], "{:,}".format(f["x402"]), money(f["usdc"]), as_of)
        p = [head % dict(ctx, title=esc(title), desc=esc(desc), canon=esc("%s/o/%s/" % (site, sl)))]
        p.append("<main><h1>%s</h1>" % esc(name))
        if mine:
            p.append('<p><span class="tag mark">%s</span><span class="tag">%d hosts · %d wallet%s</span><span class="tag">as of %s</span></p>'
                     % (esc(MARK), f["hosts"], f["wallets"], "s" if f["wallets"] != 1 else "", esc(as_of)))
            p.append('<p class="muted disclaimer">%s</p>' % esc(DISCLAIMER))
            o = mine[1]
            p.append('<div class="owner"><h2>In the operator’s words</h2>%s<p class="sells">%s</p>%s</div>' % (
                '<img class="logo" src="%s" alt="" loading="lazy" referrerpolicy="no-referrer">' % esc(o["logo"]) if o["logo"] else "",
                esc(o["description"]) or "—",
                "".join('<a class="olink" rel="nofollow ugc noopener" href="%s">%s</a>' % (esc(l["url"]), esc(l["label"] or l["url"]))
                        for l in o["links"])))
        else:
            p.append('<p><span class="tag">unclaimed group</span><span class="tag">%d hosts · %d wallet%s</span><span class="tag">as of %s</span></p>'
                     % (f["hosts"], f["wallets"], "s" if f["wallets"] != 1 else "", esc(as_of)))
            p.append('<p class="sells">%s</p>' % esc(UNCLAIMED))
        p.append('<div class="tiles">'
                 '<div class="tile"><b>%d</b><span>hosts paid into this wallet</span></div>'
                 '<div class="tile"><b>%s</b><span>x402 payments, last %s</span></div>'
                 '<div class="tile"><b>%s</b><span>USDC, x402-settled</span></div>'
                 '<div class="tile"><b>%d</b><span>hosts that took an x402 payment</span></div>'
                 '<div class="tile"><b>%s</b><span>self-reported calls, 30 days</span></div>'
                 '%s</div>'
                 % (f["hosts"], "{:,}".format(f["x402"]), esc(span_words(chain["hours"])), money(f["usdc"]) if f["usdc"] else "$0",
                    f["paid_hosts"], "{:,}".format(f["calls30"]),
                    ('<div class="tile"><b>%s</b><span>reached the wallet by ordinary transfer, not a call</span></div>' % money(f["other"]))
                    if f["other"] >= 1 else ""))
        p.append("<h2>Who actually paid the group</h2>")
        if f["x402"]:
            p.append('<p class="muted">Across the group, %s x402 payments in the last %s; payer wallets summed per host: %d. '
                     "The busiest wallets, among each host’s busiest three: %s.</p>"
                     % ("{:,}".format(f["x402"]), esc(span_words(chain["hours"])), f["payer_wallets_summed"],
                        ", ".join('<a rel="nofollow noopener" href="https://basescan.org/address/%s"><code>%s…%s</code></a> %s'
                                  % (esc(w), esc(w[:6]), esc(w[-4:]), "{:,}".format(c)) for w, c in f["top_payers"]) or "—"))
        else:
            p.append('<p class="muted">No x402 payment reached any host of this group on Base in the last %s.</p>' % esc(span_words(chain["hours"])))
        p.append('<h2>The hosts</h2><div class="tw"><table><tr><th>host</th><th class="n">x402 payments</th>'
                 '<th class="n">self-reported calls, 30 d</th><th>payers</th><th>sells</th></tr>')
        for r in f["rows"]:
            p.append('<tr><td class="h"><a href="%s/s/%s/">%s</a></td><td class="n">%s</td><td class="n">%s</td><td>%s</td><td>%s</td></tr>'
                     % (site, esc(slug(r["host"])), esc(r["host"]), "{:,}".format(r["x402"]), "{:,}".format(r["calls30"]),
                        esc(r["word"] or ("—" if not r["x402"] else "")), esc(r["sells"])))
        p.append("</table></div>")
        if not mine:
            p.append('<div class="claim"><h3>Is this your group?</h3><p>Put one name on it: this page with your description, '
                     "logo and links; a “claimed by operator” mark on each of the %d host pages; your hosts’ buyers, concentration "
                     "and money read together, updated daily; a monthly note on what changed. $49 a month, cancel any time. "
                     "The numbers never change for money.</p>"
                     '<a class="btn" href="%s?reference_id=%s">Name this group</a></div>'
                     % (f["hosts"], esc(buy_url), esc("o:" + sl)))
        p.append('<h2>How to read this</h2><ul class="cav"><li>%s</li><li>%s</li><li>%s</li></ul></main>' % (
            esc("Hosts are grouped because the registry lists the same payTo wallet for them. That is what the wallet shows, and nothing more: "
                "usually one operator, sometimes a platform collecting for several."),
            esc("x402 payments are transfers a facilitator settled on a buyer’s signature, on Base, over the window. Money that reached "
                "the same wallet by ordinary transfer is shown apart and is not a call."),
            esc("Payer wallets are summed per host: a wallet paying two hosts counts twice. A wallet is not a person.")))
        p.append(foot % {"issue": esc("%s?title=%s" % (issues, "Correction:+group+" + sl)), "as_of": esc(as_of),
                         "n": "{:,}".format(n_sellers)})
        d = os.path.join(odir, sl)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write("".join(p))
        listing.append((sl, name, f["hosts"], f["x402"], f["usdc"], bool(mine)))

    listing.sort(key=lambda r: (-r[2], -r[3]))
    page = [head % dict(ctx, title="Operators: the hosts paid into one wallet · x402 Atlas",
                        desc="%d groups of x402 hosts paid into one wallet, with a page each. As of %s." % (len(listing), as_of),
                        canon=site + "/o/")]
    page.append('<main><h1>Operators</h1><p class="sells">The registry counts hosts. The chain shows which hosts are paid into '
                "the same wallet — usually one operator, sometimes a platform collecting for several. %d groups hold %d of the "
                "hosts with a known wallet.</p>" % (len(listing), sum(r[2] for r in listing)))
    page.append('<div class="tw"><table><tr><th>group</th><th class="n">hosts</th><th class="n">x402 payments</th><th class="n">USDC</th><th></th></tr>')
    for sl, name, hosts, x402, usdc, claimed in listing:
        page.append('<tr><td class="h"><a href="%s/o/%s/">%s</a></td><td class="n">%d</td><td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                    % (site, esc(sl), esc(name), hosts, "{:,}".format(x402), money(usdc) if usdc else "—",
                       '<span class="tag mark">%s</span>' % esc(MARK) if claimed else '<span class="tag">unclaimed</span>'))
    page.append("</table></div>")
    if any(r[5] for r in listing):
        page.append('<p class="muted disclaimer">%s</p>' % esc(DISCLAIMER))
    page.append("</main>" + foot % {"issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(n_sellers)})
    with open(os.path.join(odir, "index.html"), "w") as fh:
        fh.write("".join(page))
    with open(os.path.join(odir, "index.json"), "w") as fh:        # the front door's search reads this
        json.dump({"as_of": as_of, "groups": [{"slug": r[0], "name": r[1], "hosts": r[2], "x402": r[3], "claimed": r[5]}
                                              for r in listing]}, fh, separators=(",", ":"))
    return by_host, listing


def span_words(hours):
    return "%.0f h" % hours if hours < 48 else "%d days" % round(hours / 24.0)
