#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""front_door.py — the Atlas's home page: the public record of agent commerce, read off the chain.

Not a dashboard and not a table: one sentence about what this is, one search box that
finds a seller or an operator by name or by what it sells (and a buyer by its wallet), the day's numbers from the
chain, and the few lists a visitor came for — the busiest sellers by real payments, the
largest groups, the agents at work, who appeared today. Every number links to the page
it comes from. seller_pages.py calls build() and writes /index.html.
Stranger text is escaped on the way out. Standard library only.
"""

import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market  # noqa: E402
import buyer_pages  # noqa: E402
import atlas_style  # noqa: E402

TAGLINE = "The public record of agent commerce, read off the chain."
# What the Atlas is and who it is for, in one line: the first thing a visitor reads under the headline.
ONE_LINE = (market.BRAND + " shows every service that sells to AI agents over x402, and what the chain shows it was paid: "
            "for builders choosing what their agents pay for, and for sellers watching their market.")
LEDE = ("Every service that sells to software agents over x402 has a page here: what it sells, what it "
        "charges, who actually paid it, and which hosts are one operator — rebuilt every morning from the "
        "public registry and the Base blockchain. The numbers are never for sale.")


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def money(x):
    return "$%s" % ("{:,.0f}".format(x) if x >= 100 else "{:,.2f}".format(x))


def slug(host):
    import re
    return re.sub(r"[^a-z0-9._-]", "-", host.lower())[:200]


SEARCH_JS = """<script>
const q=document.getElementById('q'),out=document.getElementById('hits');let S=null,O=null,B=null;
const WALLET=/^0x[0-9a-f]{6,40}$/;
const CATS=%(cats)s;const DAY=%(day)s;
document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{q.value=c.dataset.q;q.dispatchEvent(new Event('input'));q.focus();}));
const e=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){if(!S){const a=await fetch('%(root)s/s/index.json');S=(await a.json()).sellers;}
if(!O){try{const b=await fetch('%(root)s/o/index.json');O=(await b.json()).groups;}catch(x){O=[];}}}
async function loadB(){if(!B){try{const c=await fetch('%(root)s/b/index.json');B=(await c.json()).buyers;}catch(x){B=[];}}}
q.addEventListener('input',async()=>{const v=q.value.trim().toLowerCase();if(!v){out.innerHTML='';return}
await load();const w=v.split(/\\s+/).filter(Boolean);
const hit=t=>w.every(x=>t.includes(x));
const cats=CATS.filter(c=>new RegExp(c[1],'i').test(v)||c[0].includes(v)).map(c=>c[0]);
const byIntent=cats.length?S.filter(r=>cats.includes(r[7])):[];
const byWord=S.filter(r=>hit((r[0]+' '+r[6]+' '+r[7]).toLowerCase()));
const seen=new Set();const s=byWord.concat(byIntent).filter(r=>!seen.has(r[0])&&seen.add(r[0])).sort((a,b)=>(b[8]||0)-(a[8]||0)||b[2]-a[2]).slice(0,10);
document.getElementById('intent').textContent=cats.length?'Sellers in: '+cats.join(', ')+' — by real payments on '+DAY:'';
const o=O.filter(r=>hit((r.name+' '+r.slug).toLowerCase())).slice(0,5);
let b=[];if(WALLET.test(v)){await loadB();b=B.filter(r=>String(r.wallet).toLowerCase().startsWith(v)).sort((x,y)=>y.x402-x.x402).slice(0,10);}
let h='';
if(b.length){h+='<h2>Buyers</h2>'+b.map(r=>'<p><a href="%(root)s/b/'+encodeURIComponent(String(r.wallet).toLowerCase())+'/"><code>'+e(r.wallet)+'</code></a> <span class="muted">'+Number(r.x402).toLocaleString()+' x402 payments · '+Number(r.sellers).toLocaleString()+(r.sellers==1?' seller paid':' sellers paid')+(r.agent?' · agent at work':'')+'</span></p>').join('');}
if(s.length){h+='<h2>Sellers</h2>'+s.map(r=>'<p><a href="%(root)s/s/'+encodeURIComponent(r[1])+'/">'+e(r[0])+'</a> <span class="muted">'+e(r[6])+' · '+e(r[7])+(r[8]?' · '+Number(r[8]).toLocaleString()+' x402 payments on '+DAY:' · '+Number(r[2]).toLocaleString()+' paid calls, self-reported')+'</span></p>').join('');}
if(o.length){h+='<h2>Operators</h2>'+o.map(r=>'<p><a href="%(root)s/o/'+encodeURIComponent(r.slug)+'/">'+e(r.name)+'</a> <span class="muted">'+r.hosts+' hosts · '+Number(r.x402).toLocaleString()+' x402 payments'+(r.claimed?' · claimed':'')+'</span></p>').join('');}
if(!h)h='<p class="muted">Nothing by that name. <a href="%(root)s/s/">All sellers</a> · <a href="%(root)s/o/">all operators</a>.</p>';
out.innerHTML=h;});
const asked=new URLSearchParams(location.search).get('q');if(asked){q.value=asked.slice(0,120);q.dispatchEvent(new Event('input'));}
</script>"""


def hero(map_, site, day):
    """The day's network in a frame: map_page's embed of the same day, under a dated header
    and a legend. A day with no map drawn shows no frame at all."""
    if not map_ or not map_.get("embed") or not os.path.exists(map_["embed"]):
        return ""
    return ('<figure class="net" aria-labelledby="net-t"><div class="fh"><span class="t" id="net-t">Network · %s · %s</span>'
            '<a href="%s/map/"><b>Open the full map</b></a></div>'
            '<div class="frame"><iframe src="%s/map/embed.html" title="The network on %s: who paid whom on Base" loading="lazy"></iframe></div>'
            '<figcaption>%s</figcaption></figure>'
            % (esc(day), esc("%s busiest links" % "{:,}".format(map_["drawn"]) if map_.get("drawn") else "x402 on Base"),
               site, site, esc(day), esc(map_.get("lede") or "")))


def build(out, chain, A, loaded, ctx, as_of, site, head, foot, issues, api, groups_listing=None, buyers=None, map_=None):
    n = len(A)
    born = []
    if len(loaded) > 1:
        prev = loaded[-2]["sellers"]
        born = sorted((h for h in A if h not in prev), key=lambda h: -A[h]["calls"])
    t = (chain or {}).get("totals") or {}
    sellers_chain = (chain or {}).get("sellers") or {}
    paid = sorted((s for s in sellers_chain.values() if s.get("on_chain_payments_x402")),
                  key=lambda s: -s["on_chain_payments_x402"])
    busiest = paid[:8]
    agents = ((chain or {}).get("agents") or [])[:6]
    groups = (groups_listing or [])[:6]
    day = atlas_style.chain_day(chain, as_of)
    short = atlas_style.short_date((((chain or {}).get("dates") or [None])[-1]) or (chain or {}).get("as_of") or as_of)
    category = lambda h: market.cat((A.get(h) or {}).get("sells", "") + " " + h)[0]

    p = [head % dict(ctx, title=market.BRAND + " — the public record of agent commerce on x402", desc=LEDE[:155], canon=site + "/")]
    if busiest:        # the ledger: the day's busiest wallet-to-seller links, as the chain shows them
        links = sorted(((w["payments"], w.get("short") or w["wallet"], s["host"]) for s in paid for w in (s.get("x402_top_payers") or [])),
                       key=lambda r: -r[0])[:7]
        if links:
            p.append('<div class="ledger" aria-label="Busiest payment links, %s"><span class="lh">Ledger · %s · Base</span>%s</div>'
                     % (esc(day), esc(short), "".join(
                         '<span class="l"><span class="w">%s</span> <span class="a">→</span> %s <span class="w">%s pays</span></span>'
                         % (esc(w), esc(h), "{:,}".format(c)) for c, w, h in links)))
    p.append('<main id="main"><section class="hero" aria-labelledby="h"><div><p class="eyebrow">%s</p>'
             '<h1 id="h">Every agent payment, on the record.</h1><p class="oneline">%s</p></div>'
             '<div><p class="muted" style="margin:0">%s</p>'
             '<div class="actions"><a class="btn" href="%s/s/">Explore the market</a><a class="btn ghost" href="%s/pricing/">See pricing</a></div>'
             '</div></section>' % (esc(TAGLINE), esc(ONE_LINE), esc(LEDE), site, site))
    p.append('<label class="big" for="q">What does your agent need?</label>'
             '<input id="q" type="search" placeholder="A name, a wallet, or the job: weather, token prices, a web page as markdown…" autocomplete="off">'
             '<p class="chips">%s</p><p class="muted" id="intent"></p><div id="hits" aria-live="polite"></div>'
             % " ".join('<button class="chip" type="button" data-q="%s">%s</button>' % (esc(name), esc(name)) for name, _c, _r in market.CATS))
    p.append(hero(map_, site, day))
    p.append('<p class="dateline">%s · Base%s</p><section aria-label="%s in numbers"><div class="tiles">'
             % (esc(day), " · x402" if t else "", esc(day)))
    if t:
        p.append('<div class="tile"><b>%s</b><span>x402 payments on %s, on Base</span></div>'
                 '<div class="tile"><b>%s</b><span>USDC, x402-settled</span></div>'
                 '<div class="tile"><b>%s</b><span>wallets that paid</span></div>'
                 '<div class="tile"><b>%s</b><span>sellers paid</span></div>'
                 '<div class="tile"><b>%s</b><span>%s: wallets paying 3+ sellers</span></div>'
                 % ("{:,}".format(t.get("payments_x402", 0)), esc(day), money(t.get("usdc_x402", 0.0)),
                    "{:,}".format(t.get("buyer_wallets_x402", 0)), "{:,}".format(len(paid)), "{:,}".format(t.get("agents_3plus", 0)),
                    ('<a href="%s/b/">agents at work</a>' % site) if buyers else "agents at work"))
    p.append('<div class="tile"><b>%s</b><span><a href="%s/s/">sellers</a> in the registry</span></div>'
             '<div class="tile"><b>%s</b><span><a href="%s/o/">operators</a>: hosts paid into one wallet</span></div>'
             "</div></section>" % ("{:,}".format(n), site, "{:,}".format(len(groups_listing or [])), site))

    if paid:           # the market map: what agents bought, by category, from the chain
        cats = {}
        for s in paid:
            cats.setdefault(category(s["host"]), []).append(s)
        order = sorted(cats.items(), key=lambda kv: -sum(x["on_chain_payments_x402"] for x in kv[1]))
        p.append('<section aria-labelledby="mm"><p class="eyebrow">Market map</p><div class="section-head"><h2 id="mm">What agents bought, %s</h2>'
                 '<a href="%s/s/">All sellers</a></div><div class="cards">' % (esc(day), site))
        for c, ss in order:
            p.append('<div class="card"><div class="section-head"><h3>%s</h3><span class="mono muted">%s</span></div><div class="rows">%s</div></div>'
                     % (esc(c), "{:,}".format(sum(x["on_chain_payments_x402"] for x in ss)), "".join(
                         '<div><a href="%s/s/%s/">%s</a><span class="v">%s</span></div>'
                         % (site, esc(slug(x["host"])), esc(x["host"]), "{:,}".format(x["on_chain_payments_x402"])) for x in ss[:4])))
        p.append('</div><p class="muted">x402 payments on Base, %s. Categories are read from what each seller says it sells.</p></section>' % esc(day))

    if busiest:
        p.append('<section aria-labelledby="lb"><p class="eyebrow">Leaderboard</p><div class="section-head"><h2 id="lb">Busiest on %s, by real payments</h2>'
                 '<a href="%s/s/">All %s sellers</a></div><div class="tw"><table><tr><th class="n">rank</th><th>seller</th><th>category</th>'
                 '<th class="n">x402 payments</th><th class="n">USDC</th><th class="n">wallets</th><th>payers</th></tr>'
                 % (esc(day), site, "{:,}".format(n)))
        for i, s in enumerate(busiest):
            p.append('<tr><td class="n">%02d</td><td class="h"><a href="%s/s/%s/">%s</a></td><td>%s</td><td class="n">%s</td>'
                     '<td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                     % (i + 1, site, esc(slug(s["host"])), esc(s["host"]), esc(category(s["host"])),
                        "{:,}".format(s["on_chain_payments_x402"]), money(s.get("on_chain_usdc_x402", 0.0)),
                        s.get("x402_payer_wallets") or "—", atlas_style.pill(s.get("concentration"))))
        p.append('</table></div><p class="muted">“One payer” and “concentrated” are facts about who paid, not verdicts on the seller: '
                 'one payer means every x402 payment came from one wallet.</p></section>')
        wide = sorted((s for s in paid if s.get("x402_payer_wallets")), key=lambda s: -s["x402_payer_wallets"])[:5]
        solo = [s for s in paid if s.get("concentration") == "one payer"][:5]
        lists = []
        if wide:
            lists.append(('Sellers with the widest buyers', "by distinct paying wallets, %s" % short,
                          [(s["host"], s["x402_payer_wallets"]) for s in wide]))
        if solo:
            lists.append(('One payer', "every x402 payment from a single wallet, %s" % short,
                          [(s["host"], s["on_chain_payments_x402"]) for s in solo]))
        if lists:
            p.append('<section aria-labelledby="ls"><p class="eyebrow">Lists</p><h2 id="ls">Read off the chain, %s</h2><div class="cards">' % esc(day))
            for title, sub, rows in lists:
                p.append('<div class="card"><h3>%s</h3><p class="muted" style="font-size:13px">%s</p><div class="rows">%s</div></div>'
                         % (esc(title), esc(sub), "".join('<div><a href="%s/s/%s/">%s</a><span class="v">%s</span></div>'
                                                         % (site, esc(slug(h)), esc(h), "{:,}".format(v)) for h, v in rows)))
            p.append("</div></section>")
    if groups:
        p.append('<section aria-labelledby="gr"><p class="eyebrow">Operators</p><div class="section-head"><h2 id="gr">The largest groups</h2>'
                 '<a href="%s/o/">All operators</a></div><div class="tw"><table><tr><th>group</th><th class="n">hosts</th>'
                 '<th class="n">x402 payments</th><th></th></tr>' % site)
        for sl, name, hosts, x402, usdc, claimed in groups:
            p.append('<tr><td class="h"><a href="%s/o/%s/">%s</a></td><td class="n">%d</td><td class="n">%s</td><td>%s</td></tr>'
                     % (site, esc(sl), esc(name), hosts, "{:,}".format(x402),
                        '<span class="tag mark">Claimed by operator</span>' if claimed else '<span class="tag">unclaimed</span>'))
        p.append("</table></div>")
        if any(g[5] for g in groups):
            p.append('<p class="muted disclaimer">“Claimed by operator” means the operator proved control of the hosts. It is not an endorsement.</p>')
        p.append("</section>")
    if agents:
        p.append('<section aria-labelledby="aw"><p class="eyebrow">Agents at work</p><div class="section-head"><h2 id="aw">Wallets that shopped around, %s</h2>'
                 '%s</div><p class="muted">Wallets whose x402 payments reached three or more sellers. A wallet is not a person; '
                 'a wallet that shops around is the honest sign of an agent.</p><div class="cards">'
                 % (esc(day), ('<a href="%s/b/">All buyers</a>' % site) if buyers else ""))
        for b in agents:
            page = buyer_pages.slug(b.get("wallet") or "") in (buyers or {})
            name = esc(b.get("short") or b.get("wallet"))
            p.append('<div class="card"><h3><span class="dot buyer" aria-hidden="true"></span>%s</h3>'
                     '<p class="mono" style="font-size:13px">%s pays · %d sellers</p><p style="font-size:14px">Bought from %s</p>'
                     '<p style="font-size:13px"><a rel="nofollow noopener" href="%s">explorer</a></p></div>'
                     % (('<a href="%s"><code>%s</code></a>' % (esc(buyer_pages.link(b["wallet"], site)), name)) if page else "<code>%s</code>" % name,
                        "{:,}".format(b.get("payments_x402") or b.get("payments") or 0),
                        b.get("sellers_paid_x402") or b.get("sellers_paid") or 0,
                        ", ".join('<a href="%s/s/%s/">%s</a>' % (site, esc(slug(s["host"])), esc(s["host"][:26])) for s in (b.get("sellers") or [])[:3]),
                        esc(b.get("explorer") or "")))
        p.append("</div></section>")
    if born:
        p.append('<h2>New today</h2><p class="muted">%d sellers appeared in the registry since the day before. The busiest: %s.</p>'
                 % (len(born), ", ".join('<a href="%s/s/%s/">%s</a>' % (site, esc(slug(h)), esc(h)) for h in born[:6])))

    p.append('<section aria-labelledby="ab"><p class="eyebrow">About</p><h2 id="ab">A public record of agent commerce, written by the chain</h2><div class="cards">'
             '<div class="card"><h3>What it is</h3><p>A page for every service that sells to AI agents over x402, every operator behind them, '
             'and every wallet that pays. Ranked, dated and searchable.</p></div>'
             '<div class="card"><h3>Why it exists</h3><p>When software pays software, anyone can claim traffic. Payments on a public chain '
             'cannot be typed in. We read them so an agent can check a seller before it pays.</p></div>'
             '<div class="card"><h3>How this is made</h3><p>The public x402 discovery registry is photographed once a day; the Base blockchain '
             "is read for every USDC transfer to the wallets it names, and an x402 payment is one a facilitator settled on a buyer’s "
             "signature. Self-reported and on-chain figures sit side by side and are never blended.</p></div>"
             '<div class="card"><h3>What costs money</h3><p>Every page is free. <a href="%s/pro.html">Atlas Pro</a> is the data as files. '
             'Operators can <a href="%s/claim.html">claim their page</a>. Agents pay a cent per <a href="%s/docs/#who">answer</a>. '
             'Institutions: <a href="%s/contact/">write to us</a>.</p></div></div></section>' % (site, site, site, site))
    p.append('<section aria-labelledby="ag"><p class="eyebrow">For AI agents</p><h2 id="ag">Built to be read by software, too</h2><div class="cards">'
             '<div class="card"><h3>Check before you pay</h3><p>Ask about any seller. Paid over x402, a cent a call; a refusal is never charged.</p>'
             '<pre class="code">GET %s/who/&lt;host-or-wallet&gt;\n<span class="p">402</span> Payment Required → pay $0.01\n<span class="k">200</span> {"rank_by_calls": …}</pre></div>'
             '<div class="card"><h3>Plug the record into your agent</h3><p>A free MCP server: the market today, search by job, a seller, an operator, agents at work.</p>'
             '<pre class="code">%s</pre><p><a href="%s/docs/#mcp">Install it</a></p></div>'
             '<div class="card"><h3>The whole day as files</h3><p>Every seller, wallet and operator group as CSV and JSON, with a key or per file over x402.</p>'
             '<p><a href="%s/docs/#exports">The exports</a></p></div></div></section>'
             % (api, esc(_mcp_install()), site, site))
    p.append('<section class="band" aria-labelledby="pb"><div><p class="eyebrow" style="margin:0">Atlas Pro</p><h2 id="pb">The whole record, as data, every morning.</h2>'
             '<p class="muted" style="margin:0">sellers.csv, buyers.csv, operators.csv and day.json, rebuilt when the daily scan lands.</p></div>'
             '<div><p class="price">$49 <small>/ month</small></p><div class="actions" style="margin-top:10px"><a class="btn" href="%s/pro.html">See Atlas Pro</a>'
             '<a class="btn ghost" href="%s/pricing/">All plans</a></div></div></section></main>' % (site, site))
    p.append(SEARCH_JS % {"root": site, "cats": json.dumps([[name, rx] for name, _col, rx in market.CATS]), "day": json.dumps(short)})
    p.append(foot % {"root": site, "issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write("".join(p))
    return {"born": len(born), "busiest": len(busiest), "groups": len(groups), "agents": len(agents)}


def _mcp_install():
    import atlas_mcp
    return atlas_mcp.INSTALL
