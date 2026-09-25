#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 9aa52cb). Edit it there, not here.
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
import network  # noqa: E402
import whales as whales_mod  # noqa: E402

CAP = 400
# drawn on white: a deep ochre gold and a muted rose, far apart in hue and both dark enough to read
PALETTE = {"seller": ["#a8780a", "gold"], "buyer": ["#c0457c", "pink"]}
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

# The renderer's own style is the dark field of the older pages; this lays the paper over it.
PAPER = """:root{--bg:#fdfcf9;--ink:#16161a;--muted:#6b6b73;--line:#e3e0d8;--pink:#c0457c;--gold:#a8780a;--grey:#8a8a92}
#key{background:#ffffffee;border:1px solid var(--line);border-radius:4px;box-shadow:0 1px 3px #0000000d;backdrop-filter:none;color:#3d3d45}
#key .t,#side .t{font:600 13px "Source Sans 3",sans-serif;letter-spacing:0;text-transform:none;color:var(--ink)}
#key .kr{color:#3d3d45}#key .kr b{color:var(--ink)}#key #sizeBy{border-top-color:var(--line)}
#key #sizeBy label:has(input:checked){color:var(--ink)}#key #sizeBy label:has(input:checked)::before{color:#1d4f91}
#tip{background:#fff;border:1px solid var(--line);border-radius:4px;box-shadow:0 4px 16px #0000001a;color:var(--ink)}
#tip .kd{letter-spacing:0;text-transform:none;font-size:12.5px}#tip a{color:#1d4f91}#tip .q{color:var(--muted)}
#bar{background:#fffffff2;border-top:1px solid var(--line);color:var(--muted)}
#bar label,#mode label,#qsort label{border-color:var(--line);color:var(--muted)}
#bar label:has(input:checked),#mode label:has(input:checked),#qsort label:has(input:checked){color:var(--ink);border-color:#9a968c;background:#f3f1ea}
#side{background:#fffffff5;border:1px solid var(--line);border-radius:4px;backdrop-filter:none;color:var(--ink)}
#side a,#side .row{border-top-color:var(--line)}#side .row a,#side a{color:var(--ink)}#side .row a:hover,#side a:hover{color:#1d4f91}
#side .row .m{color:var(--muted)}#side input#q{background:#fff;border:1px solid #cfcbc0;color:var(--ink);border-radius:3px;margin:4px 0}
#comms .c{border-top-color:var(--line)}#comms .c:hover,#comms .c.on{color:#1d4f91}
.btn{background:#fff;border:1px solid #cfcbc0;color:var(--ink);border-radius:3px;backdrop-filter:none;font:14px "Source Sans 3",sans-serif}
.btn:hover{border-color:var(--ink);background:#fff}
.legend{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;font-size:14px;color:#3d3d45;margin:10px 0 0;max-width:none}
.legend i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.legend s{display:inline-block;width:24px;height:0;border-top:1.5px solid #b5b3ad;margin-right:6px;vertical-align:4px;text-decoration:none}
"""

CSS = PAPER + """html,body{height:auto;overflow:auto;background:var(--bg)}
.maphead h1{margin:34px 0 10px}.maphead .sells{margin:0 0 8px}.maphead p.muted{margin:0}
#stage{position:relative;height:calc(100vh - 20px);min-height:520px;max-height:860px;margin-top:18px;overflow:hidden;background:#fff;
  border-top:1px solid var(--ink);border-bottom:1px solid var(--line)}
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


def dress(g, A, buyer_slugs, site, day):
    """Hosts and shortened wallets as labels, Atlas pages as links, the map's own words."""
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
    g["source"] = "Base · x402-settled USDC payments · %s" % day
    g["key"] = ("Every dot is a wallet on Base. Gold is a seller, pink a wallet that paid; "
                "a line is money, x402-settled, on %s." % day)
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


def build(out, flows_path, whales, A, site="", as_of="", head=None, foot=None, issues=None, cap=CAP):
    """Write out/map/index.html and out/map/graph.json from one day's flows. whales is the
    day's rollup (a path or the loaded dict): its buyers say which /b/ pages exist, its
    notes are the caveats. A is the registry snapshot's sellers, keyed by host."""
    if head is None or foot is None or issues is None:
        import seller_pages    # the house header and footer; imported late, it imports us
        head = seller_pages.HEAD if head is None else head
        foot = seller_pages.FOOT if foot is None else foot
        issues = seller_pages.ISSUES if issues is None else issues
    site = (site or "").rstrip("/")
    with open(flows_path) as f:
        fl = x402_only(json.load(f))
    rollup = whales
    if isinstance(whales, str):
        with open(whales) as f:
            rollup = json.load(f)
    day = fl.get("date") or as_of
    as_of = as_of or day
    buyer_slugs = {buyer_pages.slug(b["wallet"]) for b in (rollup or {}).get("buyers") or []
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
        full = scrub(dress(flows_graph.build(full_p, reg, day), A, buyer_slugs, site, day))
        drawn = scrub(dress(flows_graph.build(drawn_p, reg, day), A, buyer_slugs, site, day))

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

    mdir = os.path.join(out, "map")
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "graph.json"), "w") as f:
        json.dump(full, f, separators=(",", ":"))

    lede = ("Yesterday on Base: %s between %s and %s. Gold is a seller, pink a wallet that paid; a line is money."
            % (num(t["payments"], "x402 payment"), num(t["buyers"], "wallet"), num(t["sellers"], "seller")))
    if left["edges"]:
        drawn_line = ("Drawn: the %s busiest lines of %s, by x402 payments. Left out of the picture: %s, %s and %s, "
                      "counted in the numbers above and all in <a href=\"graph.json\">graph.json</a>."
                      % ("{:,}".format(cut["drawn"]), "{:,}".format(cut["edges"]), num(left["edges"], "line"),
                         num(left["wallets"], "wallet"), num(left["sellers"], "seller")))
    else:
        drawn_line = ("Every line is drawn: %s. The data is in <a href=\"graph.json\">graph.json</a>."
                      % num(cut["edges"], "line"))
    ctx = {"title": "", "desc": esc(lede), "canon": site + "/map/", "css": site + "/s/radar.css", "root": site}
    h = head % ctx
    head_extra = h[h.index("</title>") + len("</title>"):h.index("<header")]
    header = h[h.index("<header"):]
    top = (header + '<main class="maphead"><h1>The map</h1><p class="sells">%s</p>'
           '<p class="muted">x402-settled payments on Base, %s. Tap a dot for its card; its page is one tap more. %s</p>%s</main>'
           % (esc(lede), esc(day), drawn_line, LEGEND))
    bottom = ('<main><h2>Read it with care</h2><ul class="cav">%s</ul></main>'
              % "".join("<li>%s</li>" % esc(c) for c in notes_of(rollup)))
    bottom += foot % {"issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(len(A))}
    page = network.render(dict(drawn, labels=dict(drawn.get("labels") or {"kinds": ["buyer"]}, top=LABELS["page"])), day,
                          title=esc("The map — who paid whom on Base, %s · x402 Atlas" % day),
                          head=head_extra, css=CSS, top=top, bottom=bottom)
    with open(os.path.join(mdir, "index.html"), "w") as f:
        f.write(page)
    embed = network.render(dict(drawn, embed=True, labels=dict(drawn.get("labels") or {"kinds": ["buyer"]}, top=LABELS["embed"])),
                           day, title=esc("The map, %s · x402 Atlas" % day),
                           head='<meta name="robots" content="noindex">', css=EMBED_CSS, top=LEGEND.replace("<p ", '<p id="lg" ', 1))
    with open(os.path.join(mdir, "embed.html"), "w") as f:
        f.write(embed)
    return {"payments": t["payments"], "wallets": t["buyers"], "sellers": t["sellers"], **cut, "lede": lede,
            "out": os.path.join(mdir, "index.html"), "embed": os.path.join(mdir, "embed.html")}


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
