#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 83713b3). Edit it there, not here.
"""map_page.py — the Atlas map, rebuilt each morning from the day's real flows.

The map at /map/ was a copy of a page drawn once, on 2026-09-11. Every other
page is rebuilt from the newest on-chain rollup; this makes the map the same.
seller_pages.py calls build() when the store holds a flows file for the same
day as the rollup, and it writes:

    /map/index.html   the 3D network (network.py's renderer) under the Atlas header
    /map/graph.json   every x402-settled line of the day, open for anyone to read
    /map/embed.html   the same picture, bare, for the frame on the home page

Only x402-settled edges are drawn (n_x402 > 0): agent commerce, not gift cards
or treasury moves. The busiest CAP edges by x402 payments are drawn so the page
stays usable, and the page says how many edges, wallets and sellers were left
out. A seller node is its host and links to /s/<host>/; a buyer node is its
shortened wallet and links to /b/<wallet>/. Nothing names who holds a wallet.
Standard library only.

The same page draws a Solana day (chain="Solana") at /map/solana/, from the newest
whole flows-sol-<day>.json, with no embed. Every Solana edge is x402 already: a
known processor settled it. A payee is named by its host when the file's "sellers"
gives its wallet one, otherwise by its shortened wallet; a host links to /s/ only
when that page exists, a wallet to /b/ only when that page exists, and anything
else to the public explorer. When both are built, each map carries a small
"Base | Solana" switch to the other.

    map_page.py --flows flows-2026-09-24.json --whales whales-2026-09-24.json --store store --out _site
"""

import argparse
import html
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import buyer_pages  # noqa: E402
import flows_graph  # noqa: E402
import market  # noqa: E402
import network  # noqa: E402
import atlas_style  # noqa: E402
import whales as whales_mod  # noqa: E402

CAP = 400
# drawn on white, in the Atlas palette: sellers emerald, the wallets that paid amber
PALETTE = {"seller": [atlas_style.PALETTE["seller"], "green"], "buyer": [atlas_style.PALETTE["buyer"], "amber"]}
LABELS = {"page": 12, "embed": 8}          # only the largest sellers carry a name; the rest on hover or tap
# which of whales.py's notes belong under the map: what a line is, and what a dot is not
NOTE_STARTS = ("On-chain figures", "x402-settled means", "A wallet is not an agent",
               "Hosts paid into the same wallet", "Payments to a wallet shared")
# The Atlas never uses this word, in any form, and a map quotes strangers: a description
# that uses it is left off, and a host that contains it is shown by its shortened wallet.
BANNED = re.compile(r"verif", re.I)
LEGEND = ('<p class="legend"><span><i style="background:%s"></i>a seller</span><span><i style="background:%s"></i>a wallet that paid</span>'
          '<span><s></s>a payment</span></p>' % (PALETTE["seller"][0], PALETTE["buyer"][0]))
NO_NAMES = "A seller is shown as its host and a buyer as its shortened wallet. The map names no one."
# The two maps, side by side: where each lives and what its green dot is called. On Solana a
# processor settles payments to any wallet, listed or not, so a green dot is a payee.
MAPS = {"Base": "/map/", "Solana": "/map/solana/"}
PAYEE = {"Base": "seller", "Solana": "payee"}
SOL_NO_NAMES = ("A payee is shown as its host when the file names one for its wallet, and otherwise as its "
                "shortened wallet; a wallet that paid is shown as its shortened wallet. The map names no one.")
SOL_NOTES = ["A wallet is not an agent, and not a person. One operator can appear as many wallets; a wallet "
             "paying several payees is the honest signal of an agent at work.",
             "Dollars are USDC and USDT together, one for one, as the file counts them.",
             "Payments to a wallet named by several hosts are credited to the busiest host the registry knows.",
             "Base and Solana are counted differently: read their figures side by side, never added together."]
TWICE = ("A wallet that both paid and was paid is drawn twice: green as a payee, amber as a wallet that "
         "paid. Its green dot carries the longer form of its address.")

# The renderer's own style is the dark field of the older pages; this lays the paper over it.
PAPER = """:root{color-scheme:light;--bg:#FFFFFF;--ink:#102A23;--muted:#66645A;--line:#E7E5DF;--pink:#E0A93B;--gold:#0B7A55;--grey:#A39E8C}
html,body{font-family:"Instrument Sans",system-ui,Arial,sans-serif}
#key{background:#ffffffee;border:1px solid var(--line);border-radius:10px;box-shadow:0 1px 3px #0000000d;backdrop-filter:none;color:#3A4A43}
#key .t,#side .t{font:500 11px "IBM Plex Mono",monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
#key .kr{color:#3A4A43}#key .kr b{color:var(--ink)}#key #sizeBy{border-top-color:var(--line)}
#key #sizeBy label:has(input:checked){color:var(--ink)}#key #sizeBy label:has(input:checked)::before{color:#0B7A55}
#tip{background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 4px 16px #0000001a;color:var(--ink)}
#tip .kd{font-family:"IBM Plex Mono",monospace;letter-spacing:.06em;font-size:11px}#tip a{color:#0B5A40}#tip .q{color:var(--muted)}
#bar{background:#fffffff2;border-top:1px solid var(--line);color:var(--muted)}
#bar label,#mode label,#qsort label{border-color:var(--line);color:var(--muted)}
#bar label:has(input:checked),#mode label:has(input:checked),#qsort label:has(input:checked){color:var(--ink);border-color:#A39E8C;background:#F5F4EF}
#side{background:#fffffff5;border:1px solid var(--line);border-radius:10px;backdrop-filter:none;color:var(--ink)}
#side a,#side .row{border-top-color:var(--line)}#side .row a,#side a{color:var(--ink)}#side .row a:hover,#side a:hover{color:#0B5A40}
#side .row .m{color:var(--muted);font-family:"IBM Plex Mono",monospace}
#side input#q{background:#fff;border:1px solid var(--line);color:var(--ink);border-radius:8px;margin:4px 0;height:auto;padding:7px 10px;font-size:13px}
#comms .c{border-top-color:var(--line)}#comms .c:hover,#comms .c.on{color:#0B5A40}
.btn{background:#fff;border:1px solid var(--line);color:var(--ink);border-radius:8px;backdrop-filter:none;font:14px "Instrument Sans",sans-serif;min-height:0}
.btn:hover{border-color:var(--ink);background:#fff}
.legend{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;font-size:14px;color:#3A4A43;margin:10px 0 0;max-width:none}
.legend i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.legend s{display:inline-block;width:24px;height:0;border-top:1.5px solid #D6D3CA;margin-right:6px;vertical-align:4px;text-decoration:none}
"""

CSS = PAPER + """html,body{height:auto;overflow:auto;background:var(--bg)}
.maphead h1{margin:10px 0 10px}.maphead .sells{margin:0 0 8px}.maphead p.muted{margin:0}
.chainsw{display:flex;gap:8px;align-items:baseline;font:500 13px/1.4 "IBM Plex Mono",monospace;color:var(--muted);margin:0 0 12px}
.chainsw b{color:var(--ink);font-weight:600}.chainsw a{color:var(--muted)}.chainsw a:hover{color:var(--ink)}
#stage{position:relative;height:calc(100vh - 20px);min-height:520px;max-height:860px;margin:18px auto 0;overflow:hidden;background:#fff;
  border:1px solid var(--line);border-radius:12px;width:calc(100% - 2*clamp(16px,4.4vw,64px));max-width:1312px}
#stage #c,#stage #key,#stage #bar,#stage #side,#stage #tog,#stage #ctl{position:absolute}
#stage #c{inset:0;width:100%;height:100%}
#stage #hd,#stage #ft{display:none}
#stage #key{bottom:58px}#stage #bar{padding-bottom:12px}#stage #ctl{bottom:64px}
#stage .btn{margin-top:0;font-weight:400;display:inline-block}
#stage #side{top:56px;max-height:calc(100% - 120px)}
@media (max-width:600px){#stage{height:78vh;min-height:440px}#stage #bar{gap:6px 8px;padding:8px 12px 10px;font-size:12.5px}#stage #ctl{bottom:96px}}
"""

# The frame on the home page: the picture alone, turning slowly, a legend and nothing else.
EMBED_CSS = PAPER + """html,body{background:#fff}
#c{touch-action:pan-y;width:100%;height:100%}
#hd,#ft,#bar,#side,#tog,#key{display:none!important}
#ctl{bottom:12px;right:12px;flex-direction:row}#ctl #pause{display:none}
#lg{position:fixed;left:12px;top:10px;z-index:3;pointer-events:none;margin:0;background:#ffffffd9;padding:3px 8px;border-radius:3px}
#tip{max-width:260px}
"""


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def num(n, one, many=None):
    return "%s %s" % ("{:,}".format(n), one if n == 1 else (many or one + "s"))


def flows_beside(whales_path, day):
    """Where the store keeps the flows for the rollup's day: flows-<day>.json beside it."""
    return os.path.join(os.path.dirname(os.path.abspath(whales_path)), "flows-%s.json" % day)


def x402_only(fl):
    """The day's flows with every edge that was not x402-settled dropped, and each kept
    edge's counts set to its x402 part."""
    edges = [{"from": e["from"], "to": e["to"], "n": e["n_x402"], "usdc": round(e.get("usdc_x402") or 0.0, 6),
              "n_x402": e["n_x402"], "usdc_x402": round(e.get("usdc_x402") or 0.0, 6)}
             for e in fl.get("edges", []) if (e.get("n_x402") or 0) > 0]
    edges.sort(key=lambda e: (-e["n_x402"], -e["usdc_x402"], e["from"], e["to"]))
    return dict(fl, edges=edges)


def registry_from(A):
    """flows_graph reads the registry to name a wallet by its busiest host and sort it into
    a category; the snapshot already holds both, so write it in the registry's shape."""
    items = []
    for host, s in A.items():
        wallets = s.get("wallets") or [""]
        for i, w in enumerate(wallets):      # the calls once per host, however many wallets it has
            items.append({"resource": "https://%s/" % host, "description": s.get("sells") or "",
                          "accepts": [{"payTo": w}], "quality": {"l30DaysTotalCalls": (s.get("calls") or 0) if i == 0 else 0}})
    return items


def payee_host(hosts, A):
    """The host a Solana payee is named by: the busiest the registry knows among those the
    file gives its wallet, or None. A host holding the banned word never names a dot."""
    ok = [h for h in hosts or [] if isinstance(h, str) and h and not BANNED.search(h)]
    return min(ok, key=lambda h: (-((A.get(h) or {}).get("calls") or 0), h)) if ok else None


def solana_payees(fl, A):
    """A Solana day in the shape flows_graph names by: each paid wallet's one label, as
    "sellers" {wallet: [label]}, and {label: {"wallet", "host"}} for the links. A label is
    the payee's host, or its shortened wallet; a wallet that also paid (its amber dot
    carries the short form) gets the longer form, so no two dots share a label. "host" is
    the host its /s/ page would be under, kept even when the banned word keeps it off the dot."""
    sellers = fl.get("sellers") or {}
    payers = sorted({e["from"] for e in fl["edges"]})
    taken = {whales_mod.short(b) for b in payers} | set(unique_short(payers).values())
    names, out = {}, {}
    for w in sorted({e["to"] for e in fl["edges"]}):
        hosts = sellers.get(w) or []
        host = payee_host(hosts, A)
        label = host
        if label is None or label in taken:                  # no host, or another wallet already took this host's name
            wants = [whales_mod.short(w), w[:10] + "…" + w[-8:], w]
            if host:
                wants = ["%s (%s)" % (host, x) for x in wants]
            for label in wants:
                if label not in taken:
                    break
        taken.add(label)
        page = host or next((h for h in hosts if isinstance(h, str) and h in A), None)
        names[w] = [label]
        out.setdefault(label, {"wallet": w, "host": page, "longer": label not in (host, whales_mod.short(w))})
    return dict(fl, sellers=names), out


def switch(site, chain):
    """The small "Base | Solana" switch: this map in bold, the other one a link."""
    return ('<nav class="chainsw" aria-label="Chain">%s</nav>'
            % '<span aria-hidden="true">|</span>'.join(
                '<b aria-current="page">%s</b>' % c if c == chain else '<a href="%s%s">%s</a>' % (site, MAPS[c], c)
                for c in MAPS))


def unique_short(wallets):
    """Shortened wallets, one per wallet, lengthened where two would read the same."""
    out, seen = {}, {}
    for w in sorted(wallets):
        s = whales_mod.short(w)
        if s in seen:
            s = w[:10] + "…" + w[-8:]
        seen[s] = w
        out[w] = s
    return out


def dress(g, A, buyer_slugs, site, day, chain="Base", payees=None):
    """Hosts and shortened wallets as labels, Atlas pages as links, the map's own words.
    payees: solana_payees' labels, for a Solana day; their dots are already named."""
    buyers = [n for n in g["nodes"] if n["k"] == "agent"]
    short = unique_short([n["wallet"][0] for n in buyers])
    rename = {}
    for n in g["nodes"]:
        if n["k"] == "agent":
            rename[n["u"]] = short[n["wallet"][0]]
        elif BANNED.search(n["u"]):
            rename[n["u"]] = whales_mod.short(n["wallet"][0]) if n["wallet"] else "a seller"
    hosts = sorted((u for u in rename if BANNED.search(u)), key=len, reverse=True)

    def words(t):
        for h in hosts:
            t = t.replace(h, rename[h])
        return t

    for n in g["nodes"]:
        w = n["wallet"][0] if n["wallet"] else ""
        if n["k"] == "agent":
            if buyer_pages.slug(w) in buyer_slugs:
                n["url"] = buyer_pages.link(w, site)
        elif payees is not None:            # its host's page when there is one, else its wallet on the explorer
            host = (payees.get(n["u"]) or {}).get("host")
            n["url"] = "%s/s/%s/" % (site, buyer_pages.slug(host)) if host in A else whales_mod.explorer(w) if w else ""
            n["chain"] = chain
        elif n["u"] in A:
            n["url"] = "%s/s/%s/" % (site, buyer_pages.slug(n["u"]))    # the same rule as seller_pages.slug
        n["u"] = rename.get(n["u"], n["u"])
        n["b"], n["s"] = words(n["b"]), words(n["s"])
        if BANNED.search(n["s"]):
            n["s"] = ""
        if BANNED.search(n["b"]):                   # a co-host of the same wallet, not on the map itself
            n["b"] = n["b"].split(" · same operator")[0]
        if "bought" in n:
            n["bought"] = [rename.get(h, h) for h in n["bought"]]
    for l in g["links"]:
        l["a"], l["b"] = rename.get(l["a"], l["a"]), rename.get(l["b"], l["b"])
    for c in g["communities"]:
        c["members"] = [rename.get(u, u) for u in c["members"]]
        c["hub"] = rename.get(c["hub"], c["hub"])
        c["label"], c["note"] = words(c["label"]), words(c["note"])
        if BANNED.search(c["label"]):
            c["label"] = c["label"].split(" — ")[0]
        c["terms"] = [c["label"]]
    url = {n["u"]: n["url"] for n in g["nodes"]}
    for p in g.get("panels", []):
        for r in p["rows"]:
            r["name"] = rename.get(r["name"], r["name"])
            r["url"] = url.get(r["name"], r["url"])
            r["sub"] = words(r["sub"])
            if BANNED.search(r["sub"]):
                r["sub"] = re.sub(r"^SELLS: .*? · (\d+ customers)", r"SELLS: — · \1", r["sub"])
    g["palette"] = PALETTE
    g["theme"] = "paper"
    if chain == "Solana":
        for p in g.get("panels", []):
            p["title"] = p["title"].replace("sellers", "payees").replace("buyers", "wallets")
        g["source"] = "Solana · x402 payments a known processor settled · %s" % day
        g["key"] = ("Every dot is a wallet on Solana. Green is a payee, amber a wallet that paid; "
                    "a line is money a known x402 processor settled on %s." % atlas_style.long_date(day))
        return g
    g["source"] = "Base · x402-settled USDC payments · %s" % day
    g["key"] = ("Every dot is a wallet on Base. Green is a seller, amber a wallet that paid; "
                "a line is money, x402-settled, on %s." % atlas_style.long_date(day))
    return g


def scrub(x, key=""):
    """The last word on the banned word: whatever dress() did not reword, a token that holds
    it becomes an ellipsis. Links and wallets are addresses, not text, and are left alone."""
    if isinstance(x, dict):
        return {k: scrub(v, k) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v, key) for v in x]
    if isinstance(x, str) and key not in ("url", "wallet") and BANNED.search(x):
        return re.sub(r"\S*%s\S*" % BANNED.pattern, "…", x, flags=re.I)
    return x


def notes_of(rollup):
    notes = [n for n in (rollup or {}).get("notes") or [] if n.startswith(NOTE_STARTS)]
    return (notes or list(buyer_pages.CAVEATS)) + [NO_NAMES]


def method_notes(fl):
    """A Solana file's own two sentences on what it counts, as a page says them."""
    out = []
    for lead, k in (("What counts as an x402 payment", "x402_means"), ("What is counted", "counts")):
        t = str(fl.get(k) or "").strip().rstrip(".")
        if t:
            out.append(scrub("%s: %s." % (lead, t)))
    return out


def sol_notes(fl, twice=False):
    return method_notes(fl) + SOL_NOTES + ([TWICE] if twice else []) + [SOL_NO_NAMES]


def build(out, flows_path, whales, A, site="", as_of="", head=None, foot=None, issues=None, cap=CAP,
          chain="Base", other=False, buyer_slugs=None, numbers=None):
    """Write out/map/index.html and out/map/graph.json from one day's flows. whales is the
    day's rollup (a path or the loaded dict): its buyers say which /b/ pages exist, its
    notes are the caveats. A is the registry snapshot's sellers, keyed by host.
    chain="Solana" draws a flows-sol file into out/map/solana/ instead, without an embed;
    buyer_slugs then says which /b/ pages exist (none, if not given). other: the other
    chain's map was built too, so the page carries the switch. numbers: the address of
    the day's page in numbers, linked from the Solana map."""
    if head is None or foot is None or issues is None:
        import seller_pages    # the house header and footer; imported late, it imports us
        head = seller_pages.HEAD if head is None else head
        foot = seller_pages.FOOT if foot is None else foot
        issues = seller_pages.ISSUES if issues is None else issues
    site = (site or "").rstrip("/")
    sol = chain == "Solana"
    with open(flows_path) as f:
        fl = x402_only(json.load(f))
    payees = None
    if sol:
        fl, payees = solana_payees(fl, A)
    rollup = whales
    if isinstance(whales, str):
        with open(whales) as f:
            rollup = json.load(f)
    day = fl.get("date") or as_of
    as_of = as_of or day
    if buyer_slugs is None:
        buyer_slugs = set() if sol else {buyer_pages.slug(b["wallet"]) for b in (rollup or {}).get("buyers") or []
                                         if b.get("payments_x402")}

    with tempfile.TemporaryDirectory() as tmp:
        reg = os.path.join(tmp, "registry.json")
        with open(reg, "w") as f:
            json.dump(registry_from(A), f)
        full_p, drawn_p = os.path.join(tmp, "full.json"), os.path.join(tmp, "drawn.json")
        with open(full_p, "w") as f:
            json.dump(fl, f)
        with open(drawn_p, "w") as f:
            json.dump(dict(fl, edges=fl["edges"][:cap]), f)
        full = scrub(dress(flows_graph.build(full_p, reg, day), A, buyer_slugs, site, day, chain, payees))
        drawn = scrub(dress(flows_graph.build(drawn_p, reg, day), A, buyer_slugs, site, day, chain, payees))

    # a dot drawn with fewer lines still tells its whole day
    whole = {n["u"]: n for n in full["nodes"]}
    for n in drawn["nodes"]:
        for k in ("f", "d", "b", "s", "usd", "bought"):
            if k in whole.get(n["u"], {}):
                n[k] = whole[n["u"]][k]
    drawn["panels"] = full["panels"]

    t = full["totals"]
    kinds = lambda g, k: {n["u"] for n in g["nodes"] if n["k"] == k}
    left = {"edges": len(fl["edges"]) - min(cap, len(fl["edges"])),
            "wallets": len(kinds(full, "agent") - kinds(drawn, "agent")),
            "sellers": len(kinds(full, "buyer") - kinds(drawn, "buyer"))}
    cut = {"cap": cap, "edges": len(fl["edges"]), "drawn": len(fl["edges"]) - left["edges"], "left_out": left}
    full["drawn"] = cut

    mdir = os.path.join(out, "map", "solana") if sol else os.path.join(out, "map")
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "graph.json"), "w") as f:
        json.dump(full, f, separators=(",", ":"))

    payee = PAYEE[chain]
    lede = ("On %s on %s: %s between %s and %s. Green is a %s, amber a wallet that paid; a line is money."
            % (atlas_style.long_date(day), chain, num(t["payments"], "x402 payment"), num(t["buyers"], "wallet"),
               num(t["sellers"], payee), payee))
    if left["edges"]:
        drawn_line = ("Drawn: the %s busiest lines of %s, by x402 payments. Left out of the picture: %s, %s and %s, "
                      "counted in the numbers above and all in <a href=\"graph.json\">graph.json</a>."
                      % ("{:,}".format(cut["drawn"]), "{:,}".format(cut["edges"]), num(left["edges"], "line"),
                         num(left["wallets"], "wallet"), num(left["sellers"], payee)))
    else:
        drawn_line = ("Every line is drawn: %s. The data is in <a href=\"graph.json\">graph.json</a>."
                      % num(cut["edges"], "line"))
    if sol and numbers:
        drawn_line += ' The day in numbers: <a href="%s">%s</a>.' % (esc(numbers), "x402 on Solana")
    what = ("x402 payments on Solana that a known processor settled, %s." if sol else "x402-settled payments on Base, %s.")
    legend = LEGEND.replace("a seller", "a " + payee)
    title = esc("The map — who paid whom on %s, %s · %s" % (chain, atlas_style.long_date(day), market.BRAND))
    ctx = {"title": title, "desc": esc(lede), "canon": site + MAPS[chain], "css": site + "/atlas.css", "root": site}
    h = head % ctx
    head_extra = h[h.index("</title>") + len("</title>"):h.index("<header")]
    header = h[h.index("<header"):]
    top = (header + '<main class="maphead" id="main"><p class="eyebrow">The network · %s · %s · x402</p><h1>Who paid whom</h1>%s'
           '<p class="sells">%s</p>'
           '<p class="muted">%s Tap a dot for its card; its page is one tap more. %s</p>%s</main>'
           % (esc(atlas_style.long_date(day)), chain, switch(site, chain) if other else "", esc(lede),
              esc(what % atlas_style.long_date(day)), drawn_line, legend))
    notes = sol_notes(fl, any(p["longer"] for p in payees.values())) if sol else notes_of(rollup)
    bottom = ('<main><h2>Read it with care</h2><ul class="cav">%s</ul></main>'
              % "".join("<li>%s</li>" % esc(c) for c in notes))
    bottom += foot % {"root": site, "issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(len(A))}
    page = network.render(dict(drawn, labels=dict(drawn.get("labels") or {"kinds": ["buyer"]}, top=LABELS["page"])), day,
                          title=title,
                          head=head_extra, css=CSS, top=top, bottom=bottom)
    with open(os.path.join(mdir, "index.html"), "w") as f:
        f.write(page)
    r = {"chain": chain, "payments": t["payments"], "usdc": t["usdc"], "wallets": t["buyers"], "sellers": t["sellers"],
         **cut, "lede": lede, "out": os.path.join(mdir, "index.html"), "embed": None}
    if sol:
        return r
    embed = network.render(dict(drawn, embed=True, labels=dict(drawn.get("labels") or {"kinds": ["buyer"]}, top=LABELS["embed"])),
                           day, title=esc("The map, %s · %s" % (atlas_style.long_date(day), market.BRAND)),
                           head='<meta name="robots" content="noindex"><link rel="stylesheet" href="%s">' % atlas_style.FONTS.replace("&", "&amp;"), css=EMBED_CSS, top=LEGEND.replace("<p ", '<p id="lg" ', 1).replace("</p>", "<span>%s</span></p>" % esc(atlas_style.long_date(day)), 1))
    with open(os.path.join(mdir, "embed.html"), "w") as f:
        f.write(embed)
    r["embed"] = os.path.join(mdir, "embed.html")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--flows", required=True, help="the day's flows-<date>.json (chain_flows.py)")
    ap.add_argument("--whales", required=True, help="the day's whales-<date>.json rollup")
    ap.add_argument("--store", required=True, help="the registry snapshots (market-<date>.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    import radar
    radar.STORE = a.store
    snap = radar.load_snapshot(radar.snapshots()[-1])
    r = build(a.out, a.flows, a.whales, snap["sellers"], a.site, snap["date"])
    print("map: %d x402 payments, %d wallets, %d sellers; drew %d of %d lines -> %s"
          % (r["payments"], r["wallets"], r["sellers"], r["drawn"], r["edges"], r["out"]))


if __name__ == "__main__":
    main()
