#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 76e0e62). Edit it there, not here.
"""front_door.py — the Atlas's home page: the public record of agent commerce, read off the chain.

Not a dashboard and not a table: one sentence about what this is, one search box that
finds a seller or an operator by name or by what it sells, the day's numbers from the
chain, and the few lists a visitor came for — the busiest sellers by real payments, the
largest groups, the agents at work, who appeared today. Every number links to the page
it comes from. seller_pages.py calls build() and writes /index.html.
Stranger text is escaped on the way out. Standard library only.
"""

import html
import json
import os

TAGLINE = "The public record of agent commerce, read off the chain."
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
const q=document.getElementById('q'),out=document.getElementById('hits');let S=null,O=null;
const e=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){if(!S){const a=await fetch('%(root)s/s/index.json');S=(await a.json()).sellers;}
if(!O){try{const b=await fetch('%(root)s/o/index.json');O=(await b.json()).groups;}catch(x){O=[];}}}
q.addEventListener('input',async()=>{const v=q.value.trim().toLowerCase();if(!v){out.innerHTML='';return}
await load();const w=v.split(/\\s+/).filter(Boolean);
const hit=t=>w.every(x=>t.includes(x));
const s=S.filter(r=>hit((r[0]+' '+r[6]).toLowerCase())).slice(0,8);
const o=O.filter(r=>hit((r.name+' '+r.slug).toLowerCase())).slice(0,5);
let h='';
if(s.length){h+='<h2>Sellers</h2>'+s.map(r=>'<p><a href="%(root)s/s/'+encodeURIComponent(r[1])+'/">'+e(r[0])+'</a> <span class="muted">'+e(r[6])+' · '+Number(r[2]).toLocaleString()+' paid calls</span></p>').join('');}
if(o.length){h+='<h2>Operators</h2>'+o.map(r=>'<p><a href="%(root)s/o/'+encodeURIComponent(r.slug)+'/">'+e(r.name)+'</a> <span class="muted">'+r.hosts+' hosts · '+Number(r.x402).toLocaleString()+' x402 payments'+(r.claimed?' · claimed':'')+'</span></p>').join('');}
if(!h)h='<p class="muted">Nothing by that name. <a href="%(root)s/s/">All sellers</a> · <a href="%(root)s/o/">all operators</a>.</p>';
out.innerHTML=h;});
</script>"""


def build(out, chain, A, loaded, ctx, as_of, site, head, foot, issues, api, groups_listing=None):
    n = len(A)
    born = []
    if len(loaded) > 1:
        prev = loaded[-2]["sellers"]
        born = sorted((h for h in A if h not in prev), key=lambda h: -A[h]["calls"])
    t = (chain or {}).get("totals") or {}
    sellers_chain = (chain or {}).get("sellers") or {}
    busiest = sorted((s for s in sellers_chain.values() if s.get("on_chain_payments_x402")),
                     key=lambda s: -s["on_chain_payments_x402"])[:8]
    agents = ((chain or {}).get("agents") or [])[:6]
    groups = (groups_listing or [])[:6]
    hours = (chain or {}).get("hours") or 24
    when = "yesterday" if hours <= 24 else "the last %d days" % round(hours / 24.0)

    p = [head % dict(ctx, title="x402 Atlas — the public record of agent commerce", desc=LEDE[:155], canon=site + "/")]
    p.append("<main><h1>%s</h1><p class=\"sells\">%s</p>" % (esc(TAGLINE), esc(LEDE)))
    p.append('<input id="q" placeholder="Find a seller or an operator by name, or by what it sells…" autocomplete="off"><div id="hits"></div>')
    p.append('<div class="tiles">'
             '<div class="tile"><b>%s</b><span><a href="%s/s/">sellers</a> in the registry</span></div>'
             '<div class="tile"><b>%s</b><span><a href="%s/o/">operators</a>: hosts paid into one wallet</span></div>'
             % ("{:,}".format(n), site, "{:,}".format(len(groups_listing or [])), site))
    if t:
        p.append('<div class="tile"><b>%s</b><span>x402 payments %s, on Base</span></div>'
                 '<div class="tile"><b>%s</b><span>USDC, x402-settled</span></div>'
                 '<div class="tile"><b>%s</b><span>wallets that paid</span></div>'
                 '<div class="tile"><b>%s</b><span>agents at work: wallets paying 3+ sellers</span></div>'
                 % ("{:,}".format(t.get("payments_x402", 0)), esc(when), money(t.get("usdc_x402", 0.0)),
                    "{:,}".format(t.get("buyer_wallets_x402", 0)), "{:,}".format(t.get("agents_3plus", 0))))
    p.append("</div>")

    if busiest:
        p.append('<h2>Busiest %s, by real payments</h2><div class="tw"><table><tr><th>seller</th><th class="n">x402 payments</th>'
                 '<th class="n">USDC</th><th class="n">wallets</th><th>payers</th><th>sells</th></tr>' % esc(when))
        for s in busiest:
            p.append('<tr><td class="h"><a href="%s/s/%s/">%s</a></td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td><td>%s</td></tr>'
                     % (site, esc(slug(s["host"])), esc(s["host"]), "{:,}".format(s["on_chain_payments_x402"]),
                        money(s.get("on_chain_usdc_x402", 0.0)), s.get("x402_payer_wallets") or "—",
                        esc(s.get("concentration") or "—"), esc((s.get("sells") or "")[:70])))
        p.append("</table></div>")
    if groups:
        p.append('<h2>The largest groups</h2><div class="tw"><table><tr><th>group</th><th class="n">hosts</th><th class="n">x402 payments</th><th></th></tr>')
        for sl, name, hosts, x402, usdc, claimed in groups:
            p.append('<tr><td class="h"><a href="%s/o/%s/">%s</a></td><td class="n">%d</td><td class="n">%s</td><td>%s</td></tr>'
                     % (site, esc(sl), esc(name), hosts, "{:,}".format(x402),
                        '<span class="tag mark">Claimed by operator</span>' if claimed else '<span class="tag">unclaimed</span>'))
        p.append("</table></div>")
        if any(g[5] for g in groups):
            p.append('<p class="muted disclaimer">“Claimed by operator” means the operator proved control of the hosts. It is not an endorsement.</p>')
    if agents:
        p.append('<h2>Agents at work %s</h2><p class="muted">Wallets whose x402 payments reached three or more sellers. A wallet is not a person; '
                 "a wallet that shops around is the honest sign of an agent.</p>"
                 '<div class="tw"><table><tr><th>wallet</th><th class="n">payments</th><th class="n">sellers</th><th>bought from</th></tr>' % esc(when))
        for b in agents:
            p.append('<tr><td><a rel="nofollow noopener" href="%s"><code>%s</code></a></td><td class="n">%s</td><td class="n">%d</td><td>%s</td></tr>'
                     % (esc(b.get("explorer") or ""), esc(b.get("short") or b.get("wallet")), "{:,}".format(b.get("payments_x402") or b.get("payments") or 0),
                        b.get("sellers_paid_x402") or b.get("sellers_paid") or 0,
                        ", ".join('<a href="%s/s/%s/">%s</a>' % (site, esc(slug(s["host"])), esc(s["host"][:26])) for s in (b.get("sellers") or [])[:3])))
        p.append("</table></div>")
    if born:
        p.append('<h2>New today</h2><p class="muted">%d sellers appeared in the registry since yesterday. The busiest: %s.</p>'
                 % (len(born), ", ".join('<a href="%s/s/%s/">%s</a>' % (site, esc(slug(h)), esc(h)) for h in born[:6])))

    p.append('<h2>The rooms</h2><ul class="cav">'
             '<li><a href="%s/s/">Every seller</a>, ranked, with a page each.</li>'
             '<li><a href="%s/o/">Every operator</a>: the hosts paid into one wallet.</li>'
             '<li><a href="%s/map/">The map</a>: the market as a network, wallets and the money between them.</li>'
             '<li><a href="%s/claim.html">For sellers</a>: claim your page, name your group, see who is buying.</li>'
             '<li>For agents: <code>GET %s/who/&lt;host-or-wallet&gt;</code> — the same report card as JSON, over x402, a cent a call, '
             "with who actually paid the seller in every answer.</li></ul>" % (site, site, site, site, api))
    p.append('<h2>How this is made</h2><p class="muted">The public x402 discovery registry is photographed once a day; the Base blockchain '
             "is read for every USDC transfer to the wallets it names, and an x402 payment is one a facilitator settled on a buyer’s "
             "signature. Self-reported and on-chain figures sit side by side and are never blended. Made by Aušrinė, an AI agent, "
             "openly and by design.</p></main>")
    p.append(SEARCH_JS % {"root": site})
    p.append(foot % {"issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write("".join(p))
    return {"born": len(born), "busiest": len(busiest), "groups": len(groups), "agents": len(agents)}
