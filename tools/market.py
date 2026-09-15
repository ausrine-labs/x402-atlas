#!/usr/bin/env python3
"""market.py — the x402 market: agents with wallets, what they sell, who buys.

The facilitator's public registry lists every endpoint that takes x402
payment: its URL, what it does, its price, the wallet it pays to, and —
the part that makes it a picture of ACTION, not a directory — how many
paid calls and unique payers it saw in the last 30 days.

Flat, still, hover. One circle per seller (the host that serves the
endpoints), sized by paid calls in 30 days, grouped by what it sells,
colour by category. Hover: wallet, prices, buyers, the best-selling
endpoint. A ranked list beside it by real USDC paid in 24 h, read off the chain.

    python3 market.py --in data-action/x402-sellers.json --out market-2026-09-10
"""

import argparse
import collections
import html
import json
import math
import re
import urllib.parse
from datetime import date

CATS = [
    ("money & payments", "#ffd166", r"\binvoice|\bbank (account|transfer)|\bach\b|prepaid|gift card|remit|send (dollars|money)|off-?ramp|on-?ramp|\bpayout|pay (a|an|your) |bill pay|top[- ]up"),
    ("AI inference", "#ff4fa3", r"\bllm\b|inference|chat completion|openai-compatible|\bgpt|claude|gemini|\bflash\b|embedding|image gen|generate (an )?(ai )?image|transcri|\btts\b|text[- ]to[- ]speech|vision model|run (a|the) model|nanobanana"),
    ("trust & agent infra", "#7bffb0", r"\btrust|\bproof\b|verif|reputation|agent-readiness|bazaar|get (your|listed)|registry|identity|audit|guard|attest|precheck|demand record"),
    ("people & company data", "#ff8c42", r"enrich|\bperson\b|\bpeople\b|contact|\bemail|linkedin|company (search|lookup|data)|\blei\b|procurement|tender|sec filing|edgar|xbrl|\bkyb\b|\bkyc\b|whitepages"),
    ("search & web", "#5ad1ff", r"\bsearch\b|\bserp\b|scrape|crawl|web ?page|extract|markdown|fetch url|metadata|\bnews\b|headline|tweet|twitter|reddit|read a web"),
    ("crypto & markets", "#b98cff", r"\btoken|crypto|onchain|on-chain|\bdex\b|defi|liquidat|\bperp|trading|\bprice|market|whale|smart ?money|chainlink|\bgas\b|\bnft\b|balance|\btx\b|\bblock\b|wallet|swap|bridge|stablecoin"),
    ("world data", "#8ab4ff", r"weather|earthquake|flight|travel|award|\bseat|\bgeo|\bmap\b|current (server )?time|\btime\b|countr(y|ies)|\btax|\blaw\b|rules|calendar|sports|\bscore"),
]


def cat(text):
    t = text.lower()
    for name, col, rx in CATS:
        if re.search(rx, t):
            return name, col
    return "other", "#7f8fa6"


def chain_usd(flow_paths, sellers):
    """Real USDC paid to each seller host, read off the chain (chain_flows.py /
    solana_flows.py output). A wallet's money goes to its busiest host."""
    import collections
    calls = {s["host"].replace("www.", ""): s["calls"] for s in sellers}
    usd = collections.Counter()
    hours = None
    for fp in flow_paths:
        fl = json.load(open(fp))
        hours = fl.get("hours", hours)
        for e in fl["edges"]:
            hs = sorted(fl["sellers"].get(e["to"], []), key=lambda h: -calls.get(h, 0))
            if hs:
                usd[hs[0]] += e["usdc"]
    return usd, hours


def load(path):
    items = json.load(open(path))
    sellers = {}
    for it in items:
        url = it.get("resource", "")
        host = urllib.parse.urlparse(url).netloc or url[:40]
        a = (it.get("accepts") or [{}])[0]
        try:
            price = int(a.get("maxAmountRequired") or a.get("amount") or 0) / 1e6
        except (TypeError, ValueError):
            price = 0.0
        if price > 1e5:
            price = 0.0
        q = it.get("quality") or {}
        calls = q.get("l30DaysTotalCalls") or 0
        payers = q.get("l30DaysUniquePayers") or 0
        s = sellers.setdefault(host, {"host": host, "n": 0, "calls": 0, "payers": 0, "take": 0.0,
                                      "wallets": set(), "nets": set(), "prices": [], "best": None, "texts": [],
                                      "catcalls": collections.Counter()})
        s["n"] += 1; s["calls"] += calls; s["payers"] += payers; s["take"] += calls * price
        s["wallets"].add(a.get("payTo")); s["nets"].add(a.get("network")); s["prices"].append(price)
        s["texts"].append(it.get("description", ""))
        # each endpoint is sorted on its own; the seller takes the category its calls mostly went to
        s["catcalls"][cat(it.get("description", "") + " " + url)] += calls + 1
        if s["best"] is None or calls > s["best"]["calls"]:
            s["best"] = {"calls": calls, "price": price, "desc": it.get("description", "")[:140], "url": url}
    for s in sellers.values():
        s["cat"], s["col"] = s["catcalls"].most_common(1)[0][0]
        del s["catcalls"]
        s["wallets"].discard(None); s["nets"].discard(None)
        pr = sorted(p for p in s["prices"] if p > 0)
        s["pmin"], s["pmed"], s["pmax"] = (pr[0], pr[len(pr) // 2], pr[-1]) if pr else (0, 0, 0)
    return list(sellers.values()), items


def pack(sellers, W, H):
    """Sellers packed on a spiral inside their category's own disc; discs
    laid out on a ring. Big sellers first so they sit at each centre."""
    by_cat = collections.defaultdict(list)
    for s in sellers:
        by_cat[s["cat"]].append(s)
    cats = sorted(by_cat.items(), key=lambda kv: -sum(x["calls"] for x in kv[1]))
    for s in sellers:
        s["r"] = 2.0 + 4.2 * math.log10(s["calls"] + 1) + 0.6 * math.log10(s["n"] + 1)
    placed = []
    # each category's disc radius from the area its sellers need, then the discs
    # around a ring wide enough that none overlap, scaled to the canvas
    Rs = []
    for name, ss in cats:
        area = sum(math.pi * (s["r"] + 1.2) ** 2 for s in ss) * 1.75
        Rs.append(math.sqrt(area / math.pi) + 14)
    ring = max(sum(2 * R + 26 for R in Rs) / (2 * math.pi), max(Rs) * 1.1)
    span = ring + max(Rs)
    top, bottom, side = 118, 44, 40
    scale = min((H - top - bottom) / (2 * span + 40), (W - 2 * side) / (2 * span))
    cx0, cy0 = W * 0.5, top + (H - top - bottom) * 0.5
    n = len(cats)
    ang = -math.pi / 2
    for i, (name, ss) in enumerate(cats):
        R = Rs[i] * scale
        # advance the angle by this disc's share of the ring so big discs get room
        half = (2 * Rs[i] + 26) / (2 * math.pi * ring) * math.pi
        ang += half
        cx, cy = cx0 + ring * scale * math.cos(ang), cy0 + ring * scale * math.sin(ang)
        ang += half
        for s in ss:
            s["r"] *= scale
        ss.sort(key=lambda s: -s["r"])
        pts = []
        for s in ss:
            t = 0.0
            while True:
                rr = 2.2 * scale * math.sqrt(t)
                x, y = cx + rr * math.cos(t), cy + rr * math.sin(t)
                if all((x - px) ** 2 + (y - py) ** 2 >= (s["r"] + pr + 1.5) ** 2 for px, py, pr in pts):
                    break
                t += 0.35
            pts.append((x, y, s["r"]))
            s["x"], s["y"] = x, y
        maxr = max(math.hypot(s["x"] - cx, s["y"] - cy) + s["r"] for s in ss) + 8 * scale
        placed.append({"name": name, "col": ss[0]["col"], "cx": cx, "cy": cy, "R": maxr,
                       "calls": sum(s["calls"] for s in ss), "sellers": len(ss),
                       "take": sum(s["take"] for s in ss)})
    return placed


def esc(s):
    return html.escape(str(s), quote=True)


def svg(sellers, groups, today, totals):
    W, H = 1200, 1000
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" font-family="DM Sans, Helvetica Neue, Helvetica, Arial, sans-serif">' % (W, H),
         '<rect width="%d" height="%d" fill="#05060d"/>' % (W, H)]
    for g in groups:
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" fill-opacity="0.06" stroke="%s" stroke-opacity="0.25"/>' % (g["cx"], g["cy"], g["R"], g["col"], g["col"]))
        o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="16" font-weight="600" fill="%s">%s</text>' % (g["cx"], g["cy"] - g["R"] - 14, g["col"], esc(g["name"])))
        o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12" fill="%s" fill-opacity="0.8">%d sellers · %s paid calls (30 d) · $%s on chain (24 h)</text>'
                 % (g["cx"], g["cy"] - g["R"] - 0, g["col"], g["sellers"], "{:,}".format(g["calls"]), "{:,.0f}".format(g["take"])))
    for s in sorted(sellers, key=lambda s: -s["r"]):
        o.append('<circle class="s" data-h="%s" cx="%.1f" cy="%.1f" r="%.1f" fill="%s" fill-opacity="0.85" stroke="#05060d" stroke-width="0.8"/>'
                 % (esc(s["host"]), s["x"], s["y"], s["r"], s["col"]))
    for s in sorted(sellers, key=lambda s: -s["calls"])[:22]:
        o.append('<text x="%.1f" y="%.1f" font-size="11" fill="#ffffff" fill-opacity="0.9">%s</text>' % (s["x"] + s["r"] + 3, s["y"] + 4, esc(s["host"].replace("www.", "")[:28])))
    o.append('<text x="40" y="50" font-size="32" font-weight="800" font-family="Syne, DM Sans, Helvetica Neue, sans-serif" fill="#ffffff" letter-spacing="0.5">AI Agent Economy</text>')
    o.append('<text x="40" y="%d" font-size="11" fill="#ffffff" fill-opacity="0.45" letter-spacing="1.5">POWERED BY INFOHARMONI</text>' % (H - 24))
    o.append('<text x="40" y="76" font-size="16" fill="#ffffff" fill-opacity="0.7">the market · %s · x402 on Base and friends</text>' % today)
    o.append('<text x="40" y="98" font-size="12" fill="#ffffff" fill-opacity="0.5">circle = one seller with a wallet · size = paid calls in the last 30 days · hover for what it sells and what it charges</text>')
    o.append('<text x="%d" y="%d" text-anchor="end" font-size="13" fill="#ffffff" fill-opacity="0.55">%s sellers · %s endpoints · %s paid calls · $%s USDC moved to these sellers in 24 h, read off the chain · source: x402 registry + Base/Solana</text>'
             % (W - 40, H - 24, "{:,}".format(totals["sellers"]), "{:,}".format(totals["endpoints"]), "{:,}".format(totals["calls"]), "{:,.0f}".format(totals["take"])))
    o.append('</svg>')
    return "\n".join(o)


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Agent Economy</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&display=swap">
<style>
:root{--bg:#05060d;--ink:#f2f3f8;--muted:#9aa1b8;--line:#ffffff22;--gold:#ffd166}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"DM Sans","Helvetica Neue",Helvetica,Arial,sans-serif}
#lay{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:0;max-width:1560px;margin:0 auto}
#wrap{position:relative}svg{width:100%%;height:auto;display:block}
circle.s{cursor:pointer}circle.s:hover{stroke:#fff;stroke-width:1.5}
#tip{position:absolute;background:#0b0e1cf5;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:13px;max-width:320px;display:none;line-height:1.4;z-index:2;pointer-events:none}
#tip b{font-size:15px}#tip .q{color:var(--muted);margin-top:6px}#tip .w{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--muted);word-break:break-all}
#side{padding:18px 16px;border-left:1px solid var(--line);font-size:13px;max-height:100vh;overflow:auto}
#all .row .m{font-size:12px}
#side .t{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin:14px 0 6px}
#side .row{display:grid;grid-template-columns:1fr auto;gap:2px 10px;padding:6px 0;border-top:1px solid #ffffff10}
#side .row a{color:var(--ink);text-decoration:none;font-weight:600}#side .row a:hover{color:var(--gold)}
#side .row .m{color:var(--muted);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
#side .row .d{grid-column:1/3;color:var(--muted);font-size:12px}
@media (max-width:900px){#lay{grid-template-columns:1fr}#side{border-left:0;border-top:1px solid var(--line);max-height:none}}
</style>
<div id="lay"><div id="wrap">%s<div id="tip"></div></div>
<div id="side">
<div class="t">where the money went · last 24 h, on chain</div>%s
<div class="t">every seller · <span id="cnt"></span></div><input id="q" placeholder="filter by name or what it sells" style="width:100%%;box-sizing:border-box;background:#0b0e1c;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:7px 10px;font-size:13px;margin-bottom:6px"><div id="all"></div>
<div class="t">what this is</div>
<p style="color:var(--muted);margin:0">Every seller here is an agent, or a service built for agents, that takes payment machine-to-machine over x402 — USDC on Base, mostly — with no human in the loop. The counts are the facilitator's own: paid calls and paying wallets per endpoint over 30 days. Dollars are real USDC read off the Base and Solana chains over 24 hours — not list price, which badly undercounts sellers whose price varies (gift cards, model access). Circle size is paid calls over 30 days.</p>
</div></div>
<script>
const S=%s; const byH={}; S.forEach(s=>byH[s.host]=s);
const tip=document.getElementById('tip'),wrap=document.getElementById('wrap');
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const money=v=>v>=1000?'$'+(v/1000).toFixed(1)+'k':'$'+v.toFixed(2);
document.querySelectorAll('circle.s').forEach(c=>{
  c.addEventListener('mousemove',e=>{const s=byH[c.dataset.h]; if(!s)return;
    tip.innerHTML='<b>'+esc(s.host)+'</b><br>'+s.cat+' · '+s.n+' endpoint'+(s.n>1?'s':'')+'<br>'+s.calls.toLocaleString()+' paid calls · '+s.payers.toLocaleString()+' payers · 24 h on chain '+money(s.take)+
      '<br>price '+(s.pmin===s.pmax?'$'+s.pmed:'$'+s.pmin+' – $'+s.pmax)+' per call · '+s.nets.map(n=>({'eip155:8453':'Base','eip155:137':'Polygon','eip155:42161':'Arbitrum','xrpl:0':'XRPL'})[n]||(n.startsWith('solana')?'Solana':n)).join(', ')+
      (s.best?'<div class="q">best seller: '+esc(s.best.desc)+' ('+s.best.calls.toLocaleString()+' calls)</div>':'')+
      '<div class="w">'+s.wallets.slice(0,2).map(esc).join('<br>')+(s.wallets.length>2?'<br>+'+(s.wallets.length-2)+' more wallets':'')+'</div>';
    const r=wrap.getBoundingClientRect(); tip.style.display='block';
    tip.style.left=Math.min(e.clientX-r.left+14,r.width-340)+'px'; tip.style.top=(e.clientY-r.top+14)+'px';});
  c.addEventListener('mouseleave',()=>tip.style.display='none');
  c.addEventListener('click',()=>{const s=byH[c.dataset.h]; if(s&&s.best)window.open(s.best.url.split('/').slice(0,3).join('/'),'_blank');});
});
// the whole market, scrollable and filterable
const all=document.getElementById('all'), q=document.getElementById('q'), cnt=document.getElementById('cnt');
const sorted=[...S].sort((a,b)=>b.calls-a.calls);
function render(){const f=q.value.trim().toLowerCase(); let k=0; all.innerHTML=sorted.filter(s=>!f||s.host.includes(f)||s.cat.includes(f)||(s.best&&s.best.desc.toLowerCase().includes(f))).map(s=>{k++;
  return '<div class="row"><a href="'+esc(s.best?s.best.url.split('/').slice(0,3).join('/'):'https://'+s.host)+'" target="_blank" rel="noopener">'+esc(s.host.replace('www.',''))+'</a><span class="m">'+s.calls.toLocaleString()+' calls · '+money(s.take)+'</span><span class="d">'+esc(s.cat)+' · '+esc(s.best?s.best.desc.slice(0,90):'')+'</span></div>';}).join(''); cnt.textContent=k+' of '+S.length;}
q.addEventListener('input',render); render();
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data-action/x402-sellers.json")
    ap.add_argument("--out", default="market-" + date.today().isoformat())
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--flows", nargs="*", default=[], help="chain flow files; dollars come from these, not list price")
    a = ap.parse_args()
    sellers, items = load(a.inp)
    if a.flows:
        usd, _h = chain_usd(a.flows, sellers)
        for s in sellers:
            s["take"] = round(usd.get(s["host"].replace("www.", ""), 0.0), 2)
    groups = pack(sellers, 1200, 1000)
    totals = {"sellers": len(sellers), "endpoints": len(items), "calls": sum(s["calls"] for s in sellers), "take": sum(s["take"] for s in sellers)}
    s_svg = svg(sellers, groups, a.date, totals)
    open(a.out + ".svg", "w").write(s_svg)

    def row(s, metric):
        return ('<div class="row"><a href="%s" target="_blank" rel="noopener">%s</a><span class="m">%s</span><span class="d">%s</span></div>'
                % (esc(s["best"]["url"].split("/")[0] + "//" + s["host"]), esc(s["host"].replace("www.", "")), metric, esc((s["best"]["desc"] or "")[:90])))
    by_take = "".join(row(s, "$%s" % "{:,.0f}".format(s["take"])) for s in sorted(sellers, key=lambda s: -s["take"])[:15])
    data = [{k: (sorted(v) if isinstance(v, set) else v) for k, v in s.items() if k not in ("texts", "prices", "x", "y", "r", "col")} for s in sellers]
    page = PAGE % (s_svg, by_take, json.dumps(data))
    open(a.out + ".html", "w").write(page)
    print("sellers %d · endpoints %d · calls %s · take ~$%.0f" % (len(sellers), len(items), "{:,}".format(totals["calls"]), totals["take"]))
    for g in groups:
        print("  %-24s %4d sellers %8s calls  ~$%.0f" % (g["name"], g["sellers"], "{:,}".format(g["calls"]), g["take"]))
    print("wrote %s.svg and %s.html" % (a.out, a.out))


if __name__ == "__main__":
    main()
