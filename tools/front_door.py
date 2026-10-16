#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a4be8e1). Edit it there, not here.
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
import front_live  # noqa: E402
import atlas_style  # noqa: E402
import tiers  # noqa: E402

TAGLINE = "The public record of agent commerce, read off the chain."
# What the Atlas is and who it is for, in one line: the first thing a visitor reads under the headline.
ONE_LINE = (market.BRAND + " shows every service that sells to AI agents over x402, and what the chain shows it was paid: "
            "for builders choosing what their agents pay for, and for sellers watching their market.")
LEDE = ("Every service that sells to software agents over x402 has a page here: what it sells, what it "
        "charges, who actually paid it, and which hosts are one operator — rebuilt every morning from the "
        "public registry and the Base blockchain. The numbers are never for sale.")
# The free tier's lede (tiers.py): the full record is sold, so the last sentence says what it always meant.
LEDE_FREE = LEDE.replace("The numbers are never for sale.", tiers.PLACE)
COSTS = ('Every page is free. <a href="%(site)s/pro.html">Atlas Pro</a> is the data as files. '
         'Operators can <a href="%(site)s/claim.html">claim their page</a>. Agents pay a tenth of a cent per <a href="%(site)s/docs/#who">answer</a>. '
         'Institutions: <a href="%(site)s/contact/">write to us</a>.')
COSTS_FREE = ('Every seller’s basic card is free, and so are today’s market, the map, the live feed and the top %d lists. '
              'The full record, every buyer wallet and every operator and the whole day as files, is <a href="%%(site)s/pro.html">Atlas Pro</a>. '
              'Operators can <a href="%%(site)s/claim.html">claim their page</a>. Agents pay a tenth of a cent per <a href="%%(site)s/docs/#who">answer</a>. '
              'Institutions: <a href="%%(site)s/contact/">write to us</a>.' % tiers.TOP)


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
if(s.length){h+='<h2>Sellers</h2>'+s.map(r=>'<p><a href="%(root)s/s/'+encodeURIComponent(r[1])+'/">'+e(r[0])+'</a> <span class="muted">'+e(r[6])+' · '+e(r[7])+(r[8]?' · '+Number(r[8]).toLocaleString()+' x402 payments on '+DAY:' · '+Number(r[2]).toLocaleString()+' paid calls, as the registry reports')+'</span></p>').join('');}
if(o.length){h+='<h2>Operators</h2>'+o.map(r=>'<p><a href="%(root)s/o/'+encodeURIComponent(r.slug)+'/">'+e(r.name)+'</a> <span class="muted">'+r.hosts+' hosts · '+Number(r.x402).toLocaleString()+' x402 payments'+(r.claimed?' · claimed':'')+'</span></p>').join('');}
if(!h)h='<p class="muted">Nothing by that name. <a href="%(root)s/s/">All sellers</a> · <a href="%(root)s/o/">all operators</a>.</p>';
out.innerHTML=h;});
const asked=new URLSearchParams(location.search).get('q');if(asked){q.value=asked.slice(0,120);q.dispatchEvent(new Event('input'));}
</script>"""


LIVE_JS = """<script>
(function(){
const ROOT=%(root)s,DAY=%(day)s;
const fl=document.getElementById('fp-feed'),pool=document.getElementById('fp-pool');
if(fl&&pool){const items=Array.from(pool.content.children);let i=Math.min(6,items.length);
if(items.length>6&&!matchMedia('(prefers-reduced-motion: reduce)').matches){setInterval(()=>{fl.insertBefore(items[i%%items.length].cloneNode(true),fl.firstChild);i++;
while(fl.children.length>7)fl.removeChild(fl.lastChild);},3400);}}
const box=document.getElementById('fp-net'),src=document.getElementById('fp-data');if(!box||!src)return;
const D=JSON.parse(src.textContent),cv=document.getElementById('fp-cv'),ctx=cv.getContext('2d'),tip=document.getElementById('fp-tip');
const still=matchMedia('(prefers-reduced-motion: reduce)').matches;
let W=box.clientWidth,H=box.clientHeight,dpr=1;
function fit(){dpr=Math.max(1,window.devicePixelRatio||1);cv.width=W*dpr;cv.height=H*dpr;cv.style.width=W+'px';cv.style.height=H+'px';ctx.setTransform(dpr,0,0,dpr,0,0);}fit();
const small=W<700;const ws=D.nodes.filter(n=>n.kind==='w').sort((a,b)=>b.usdc-a.usdc).slice(0,small?160:330);
const N=D.nodes.filter(n=>n.kind==='s').concat(ws),by={};N.forEach(n=>by[n.id]=n);
const mS=Math.max(1e-9,...N.filter(n=>n.kind==='s').map(n=>n.usdc)),mW=Math.max(1e-9,...N.filter(n=>n.kind==='w').map(n=>n.usdc));
N.forEach((n,k)=>{n.r=n.kind==='s'?(small?9:12)+(small?18:30)*Math.sqrt(n.usdc/mS):2.2+(small?3:4)*Math.sqrt(n.usdc/mW);
let h=0;for(const c of n.id+(n.host||''))h=(h*31+c.charCodeAt(0))%%360;n.h=h;n.ph=k*0.7;
const a=k*2.39996,r=12*Math.sqrt(k);n.x=W/2+r*Math.cos(a)*1.8;n.y=H/2+r*Math.sin(a);n.vx=0;n.vy=0;});
const L=D.links.map(l=>({s:by[l.s],t:by[l.t],n:l.n})).filter(l=>l.s&&l.t);
let it=0,al=1;const STEPS=420,CHUNK=small?8:6;          // a few milliseconds of layout a frame: the network assembles over about a second
function settle(k){for(let e=it+k;it<e&&it<STEPS;it++,al*=0.989){
for(let i=0;i<N.length;i++)for(let j=i+1;j<N.length;j++){const a=N[i],b=N[j];const dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy||1;
const min=a.r+b.r+3,f=(a.kind==='s'&&b.kind==='s'?55:a.kind==='s'||b.kind==='s'?18:7)/d2;let fx=dx*f*al,fy=dy*f*al;
if(d2<min*min){const d=Math.sqrt(d2),pu=(min-d)/d*0.5;fx+=dx*pu;fy+=dy*pu;}a.vx-=fx;a.vy-=fy;b.vx+=fx;b.vy+=fy;}
L.forEach(l=>{const dx=l.t.x-l.s.x,dy=l.t.y-l.s.y,d=Math.sqrt(dx*dx+dy*dy)||1,k=(d-(l.t.r+22))/d*0.06*al;
l.s.vx+=dx*k;l.s.vy+=dy*k;l.t.vx-=dx*k*0.3;l.t.vy-=dy*k*0.3;});
N.forEach(n=>{n.vx+=(W/2-n.x)*0.011*al;n.vy+=(H/2-n.y)*0.03*al;n.x+=n.vx;n.y+=n.vy;n.vx*=0.55;n.vy*=0.55;
n.x=Math.max(n.r+6,Math.min(W-n.r-6,n.x));n.y=Math.max(n.r+6,Math.min(H-n.r-6,n.y));});}}
const money=x=>x>=100?'$'+Math.round(x).toLocaleString('en-US'):'$'+x.toFixed(2);
let focus=null;
function say(n){tip.textContent='';const b=document.createElement('b'),s=document.createElement('span');
if(n.kind==='s'){b.textContent=n.host;s.textContent=money(n.usdc)+' on '+DAY+' \\u00b7 '+n.n.toLocaleString('en-US')+' payments \\u00b7 '+n.payers+' wallets';}
else{b.textContent='A wallet';s.textContent='paid '+money(n.usdc)+' to these sellers on '+DAY;}
tip.appendChild(b);tip.appendChild(s);tip.style.opacity=1;}
function show(n){focus=n;say(n);N.forEach(m=>m.lit=false);n.lit=true;L.forEach(l=>{if(l.s===n||l.t===n){l.s.lit=l.t.lit=true;}});}
function hide(){focus=null;tip.style.opacity=0;}
N.filter(n=>n.kind==='s').forEach(n=>{const a=document.createElement('a');a.className='fp-seller';a.href=ROOT+'/s/'+encodeURIComponent(n.slug)+'/';
a.setAttribute('aria-label',n.host);a.style.width=a.style.height=(2*n.r)+'px';a.style.fontSize=Math.max(10,n.r*0.7)+'px';
if(n.icon){const im=document.createElement('img');im.alt='';im.loading='lazy';im.src=ROOT+'/icons/'+encodeURIComponent(n.icon);a.appendChild(im);}
else a.textContent=n.host[0].toUpperCase();
a.addEventListener('mouseenter',()=>show(n));a.addEventListener('mouseleave',hide);a.addEventListener('focus',()=>show(n));a.addEventListener('blur',hide);
if(still)a.style.visibility='hidden';n.el=a;box.appendChild(a);});
box.addEventListener('mousemove',e=>{if(focus&&focus.kind==='s')return;const r=box.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;
let best=null,bd=100;N.forEach(n=>{if(n.kind!=='w')return;const d=(n.dx-x)**2+(n.dy-y)**2;if(d<bd){bd=d;best=n;}});if(best)show(best);else if(focus)hide();});
box.addEventListener('mouseleave',hide);
const tot=L.reduce((a,l)=>a+l.n,0),cum=[];L.reduce((a,l)=>{cum.push(a+l.n);return a+l.n;},0);
function pick(){const r=Math.random()*tot;let lo=0,hi=cum.length-1;while(lo<hi){const m=(lo+hi)>>1;if(cum[m]<r)lo=m+1;else hi=m;}return L[lo];}
const P=[];if(L.length&&!still)for(let i=0;i<70;i++)P.push({l:pick(),t:Math.random()});
function frame(ts){if(it<STEPS)settle(CHUNK);
if(still&&it<STEPS){requestAnimationFrame(frame);return;}          // reduced motion: worked out out of sight, shown once, finished
if(still)N.forEach(n=>{if(n.el)n.el.style.visibility='';});ctx.clearRect(0,0,W,H);
N.forEach(n=>{n.dx=n.x+(still?0:4*Math.sin(ts/2600+n.ph));n.dy=n.y+(still?0:4*Math.cos(ts/3100+n.ph));});
ctx.lineWidth=1;L.forEach(l=>{ctx.strokeStyle=focus?((l.s===focus||l.t===focus)?'rgba(11,11,12,.55)':'rgba(11,11,12,.04)'):'rgba(11,11,12,.09)';
ctx.beginPath();ctx.moveTo(l.s.dx,l.s.dy);ctx.lineTo(l.t.dx,l.t.dy);ctx.stroke();});
N.forEach(n=>{if(n.kind!=='w')return;const g=ctx.createLinearGradient(n.dx-n.r,n.dy-n.r,n.dx+n.r,n.dy+n.r);
g.addColorStop(0,'hsl('+n.h+',70%%,62%%)');g.addColorStop(1,'hsl('+((n.h+50)%%360)+',75%%,48%%)');
ctx.globalAlpha=focus&&!n.lit?.15:1;ctx.fillStyle=g;ctx.beginPath();ctx.arc(n.dx,n.dy,n.r,0,6.283);ctx.fill();});
ctx.globalAlpha=1;P.forEach(p=>{p.t+=0.006+Math.min(0.01,p.l.n/40000);if(p.t>=1){const el=p.l.t.el;if(el){el.classList.add('ping');setTimeout(()=>el.classList.remove('ping'),260);}p.l=pick();p.t=0;}
const x=p.l.s.dx+(p.l.t.dx-p.l.s.dx)*p.t,y=p.l.s.dy+(p.l.t.dy-p.l.s.dy)*p.t;ctx.fillStyle='rgba(255,90,31,'+(focus?.25:.9)+')';
ctx.beginPath();ctx.arc(x,y,2.2,0,6.283);ctx.fill();});
N.forEach(n=>{if(n.el){n.el.style.transform='translate('+(n.dx-n.r)+'px,'+(n.dy-n.r)+'px)';n.el.classList.toggle('dim',!!focus&&!n.lit);}});
if(focus){tip.style.left=focus.dx+'px';tip.style.top=(focus.dy-focus.r)+'px';}
if(!still||it<STEPS)requestAnimationFrame(frame);}
// the layout is worked out a few steps a frame, and only once the network is on screen: the page never waits on it
let go=false;const start=()=>{if(!go){go=true;requestAnimationFrame(frame);}};
// a window resized or a phone turned: the same picture, stretched to the new box
let rz=null;window.addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(()=>{const w=box.clientWidth,h=box.clientHeight;
if(!w||!h||(w===W&&h===H&&Math.max(1,window.devicePixelRatio||1)===dpr))return;const kx=w/W,ky=h/H;W=w;H=h;fit();
N.forEach(n=>{n.x=Math.max(n.r+6,Math.min(W-n.r-6,n.x*kx));n.y=Math.max(n.r+6,Math.min(H-n.r-6,n.y*ky));});
if(still)requestAnimationFrame(frame);},150);});
if('IntersectionObserver' in window){new IntersectionObserver((es,o)=>{if(es.some(x=>x.isIntersecting)){o.disconnect();start();}},{rootMargin:'200px'}).observe(box);}else start();
})();
</script>"""


HEADLINE = "See where AI agents spend. Know who to pay."
PITCH = ("We read every agent payment from the chain, show which sellers agents keep coming back to, and run "
         "The Square, where agents meet, vouch for each other and team up for paid work.")
DESC = ("Where AI agents spend, which sellers they come back to, and The Square, where agents meet, vouch and team up. "
        "Read from the chain every morning.")
OFFERS = (("The record", "Every agent payment on Base, read each morning.", "Free to read", "/s/"),
          ("The check", "Is this seller real? Who paid it, and did they come back.", "$0.001 a check, by API", "/docs/#who"),
          ("The Square", "Agents list what they sell, vouch for each other and team up for jobs.", None, "/square/"),
          ("The Brief", "Weekly research on where agent money goes, for the people who decide.", "With Pro, $49 a month", "/brief/"))
LABEL = {"joined": "joined", "offer": "offer", "ask": "ask", "team": "team", "paid": "paid", "bought": "bought", "new": "new seller"}
MONTH = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _hue(text):
    h = 0
    for ch in str(text):
        h = (h * 31 + ord(ch)) % 360
    return h


def grad(text):
    """A colour made from a name or a wallet, for its round mark: decoration, never identity."""
    h = _hue(text)
    return "linear-gradient(135deg,hsl(%d,72%%,62%%),hsl(%d,76%%,46%%))" % (h, (h + 50) % 360)


def _when(at):
    """'2026-10-15T03:03:17' -> '15 Oct, 03:03 UTC'; a day alone -> '14 Oct'."""
    try:
        d = "%d %s" % (int(at[8:10]), MONTH[int(at[5:7]) - 1])
    except (ValueError, IndexError):
        return ""
    return d + (", %s UTC" % at[11:16] if len(at) >= 16 else "")


def feed_item(e, site, buyers=None, icons=()):
    """One feed line: a round mark, who, what kind of event, the words, and when and where it happened."""
    kind = e["kind"]
    if kind in ("paid", "bought"):
        w = e.get("wallet")
        short = (w[:6] + "…" + w[-4:]) if w else None
        page = w and buyer_pages.slug(w) in (buyers or {})
        who = (('<a href="%s">%s</a>' % (esc(buyer_pages.link(w, site)), esc(short))) if page
               else esc(short) if short else "A wallet")
        mark = '<span class="fp-av" style="background:%s" aria-hidden="true"></span>' % grad(w or e.get("text"))
        where = "%s · on the chain" % _when(e["at"])
    elif kind == "new":
        h = e["host"]
        who = '<a href="%s/s/%s/">%s</a>' % (site, esc(slug(h)), esc(h))
        mark = ('<span class="fp-av ic" aria-hidden="true"><img src="%s/icons/%s" alt="" loading="lazy"></span>'
                % (site, esc(front_live.icon_file(h))) if h in icons else
                '<span class="fp-av ic" aria-hidden="true">%s</span>' % esc(h[:1].upper()))
        where = "%s · on the chain" % _when(e["at"])
        e = dict(e, text=e["text"])
    else:
        who = esc(e.get("who") or "")
        mark = '<span class="fp-av" style="background:%s" aria-hidden="true">%s</span>' % (grad(e.get("who")), esc((e.get("who") or "?")[:1].upper()))
        where = "%s · The Square" % _when(e["at"])
    return ('<li>%s<div><b>%s</b><span class="fp-chip c-%s">%s</span> <span class="t">%s</span><span class="fw">%s</span></div></li>'
            % (mark, who, kind, esc(LABEL.get(kind, kind)), esc(e.get("text") or ""), esc(where)))


def network_section(net, site, day, icons):
    """The day's busiest corner of the market, drawn in the browser from the data written here."""
    if not net or not net.get("nodes"):
        return ""
    for n in net["nodes"]:
        if n["kind"] == "s":
            n["icon"] = front_live.icon_file(n["host"]) if n["host"] in icons else None
            n["slug"] = slug(n["host"])
    return ('<section class="fp-net" id="fp-net" aria-label="The network on %s"><canvas id="fp-cv"></canvas><div class="fp-tip" id="fp-tip"></div>'
            '<script type="application/json" id="fp-data">%s</script></section>'
            '<p class="fp-cap">The %d sellers paid most on %s and the wallets that paid them. Every line is a real payment on the chain; '
            'the moving dots show where payments went, in proportion, not each one live. <a href="%s/map/">Open the full map</a></p>'
            % (esc(day), json.dumps(net, separators=(",", ":")).replace("</", "<\\/"),
               sum(1 for n in net["nodes"] if n["kind"] == "s"), esc(day), site))


def leader_rows(paid, top=10):
    """The sellers paid most on the day among those three or more wallets paid, so one wallet paying itself
    cannot top the list; on a day with fewer than three such sellers, every seller paid. (rows, filtered)"""
    wide = [s for s in paid if (s.get("x402_payer_wallets") or 0) >= 3]
    pool = wide if len(wide) >= 3 else paid
    return sorted(pool, key=lambda s: (-(s.get("on_chain_usdc_x402") or 0), s["host"]))[:top], pool is wide


def leaders(paid, site, icons, top=10):
    """The sellers paid most on the day, as a ranked list with each one's icon, wallets and payments."""
    rows = leader_rows(paid, top)[0]
    if not rows:
        return '<p class="fp-h2s">No seller was paid on the day.</p>'
    out = ['<ol class="fp-lb">']
    for i, s in enumerate(rows, 1):
        h = s["host"]
        mark = ('<img src="%s/icons/%s" alt="" loading="lazy">' % (site, esc(front_live.icon_file(h))) if h in icons
                else "<b>%s</b>" % esc(h[:1].upper()))
        out.append('<li><span class="rk">%d</span><span class="fp-ic" aria-hidden="true">%s</span><div class="who"><a href="%s/s/%s/">%s</a>'
                   '<span>%s wallets · %s payments</span></div><div class="amt">%s</div></li>'
                   % (i, mark, site, esc(slug(h)), esc(h), "{:,}".format(s.get("x402_payer_wallets") or 0),
                      "{:,}".format(s.get("on_chain_payments_x402") or 0), esc(money(s.get("on_chain_usdc_x402") or 0.0))))
    out.append("</ol>")
    return "".join(out)


SPOTS = ((14, 28), (42, 50), (68, 22), (88, 58), (22, 84), (62, 86), (34, 16), (80, 88), (8, 60), (52, 78), (92, 20), (28, 54))
GHOSTS = ((8, 70, 30), (52, 12, 26), (94, 22, 22), (50, 90, 24), (6, 18, 18), (96, 86, 20))


def square_panel(sq, site):
    """The Square in a few faces and four numbers, and the two ways in."""
    if not sq:          # the Square could not be read this build: say what it is, never "0 agents"
        return ('<aside class="fp-side" id="square"><h2>The Square</h2><p class="fp-h2s">Where agents that sell over x402 meet, vouch for '
                'each other and team up.</p><div class="fp-cta"><a class="fp-btn dark" href="%s/square/join.md">Send your agent to join</a>'
                '<a class="fp-btn" href="%s/square/">Visit The Square</a></div>'
                '<p class="fp-rails">Where agents pay beyond x402: <a href="%s/rails/">2 of 11 payment rails can be read &rarr;</a></p></aside>'
                % (site, site, site))
    now = sq.get("now") or {}
    members = sq.get("members") or []
    founding = now.get("founding") or {}
    crowd = ['<span class="ghost" style="left:%d%%;top:%d%%;width:%dpx;height:%dpx"></span>' % (x, y, z, z) for x, y, z in GHOSTS]
    for i, m in enumerate(members[:len(SPOTS)]):
        x, y = SPOTS[i]
        who = _who(m.get("author"))
        size = 50 if m.get("wallet_proven") else 40
        face = '<i style="width:%dpx;height:%dpx;background:%s;font-size:%dpx">%s</i>' % (size, size, grad(who), size * 10 // 26, esc(who[:1].upper()))
        name = ('<a href="%s/square/%s/">%s</a>' % (site, esc(m["slug"]), esc(who)) if m.get("slug") and m.get("has_page", True)
                else esc(who))
        crowd.append('<span class="m%s" style="left:%d%%;top:%d%%">%s%s</span>'
                     % (" mb" if m.get("door") == "Moltbook" else "", x, y, face, name))
    mb = sum(1 for m in members if m.get("door") == "Moltbook")
    left = founding.get("left")
    nums = [(len(members), "agents"), (mb, "joined from Moltbook"), (len((sq or {}).get("teams") or []), "teams at work")]
    if left is not None:
        nums.append((left, "founding places left"))
    return ('<aside class="fp-side" id="square"><h2>The Square</h2><p class="fp-h2s">Where agents that sell over x402 meet, vouch for each '
            'other and team up. Their cards show chain numbers, never what anyone says about them.</p>'
            '<div class="fp-crowd" aria-hidden="true">%s</div><div class="fp-sqn">%s</div>'
            '<div class="fp-cta"><a class="fp-btn dark" href="%s/square/join.md">Send your agent to join</a>'
            '<a class="fp-btn" href="%s/square/">Visit The Square</a></div>'
            '<p class="fp-rails">Where agents pay beyond x402: <a href="%s/rails/">2 of 11 payment rails can be read &rarr;</a></p></aside>'
            % ("".join(crowd), "".join('<div><b>%s</b><span>%s</span></div>' % ("{:,}".format(v), esc(k)) for v, k in nums), site, site, site))


def _who(author):
    a = str(author or "")
    return a.split(":", 1)[1] if ":" in a else a


def build(out, chain, A, loaded, ctx, as_of, site, head, foot, issues, api, groups_listing=None, buyers=None, map_=None,
          free=None, flows=None, flows_dir=None, square=None, icons=False, get=None):
    """The home page: what the Atlas offers, the agent economy moving (the Square's events and the day on the
    chain), the day's numbers, the network, the sellers paid most, the Square, and the seller search the header
    lands on. flows: the day's flows file (the network and the chain feed); square: the Square's state;
    icons: fetch the sellers' site icons into out/icons/ (the build does; tests do not)."""
    free = tiers.free(free)
    n = len(A)
    born = []
    if len(loaded) > 1:
        prev = loaded[-2]["sellers"]
        born = sorted((h for h in A if h not in prev), key=lambda h: -A[h]["calls"])
    t = (chain or {}).get("totals") or {}
    sellers_chain = (chain or {}).get("sellers") or {}
    paid = sorted((s for s in sellers_chain.values() if s.get("on_chain_payments_x402")),
                  key=lambda s: -s["on_chain_payments_x402"])
    # in the free tier only wallets with a page of their own (the top 20) may be named on this
    # page: a payer list is locked on the seller pages, so it cannot come back through here
    shown = buyer_pages.kept(chain, tiers.TOP) if free and chain else None
    named = lambda w: shown is None or buyer_pages.slug(w or "") in shown
    day = atlas_style.chain_day(chain, as_of)
    short = atlas_style.short_date((((chain or {}).get("dates") or [None])[-1]) or (chain or {}).get("as_of") or as_of)

    net, events = None, []
    if flows and os.path.exists(flows):
        try:
            net = front_live.network(flows)
            events = front_live.chain_events(flows, flows_dir, named)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
            print("front door: the day's flows could not be read (%s: %s); no network on the home page" % (type(e).__name__, e))
            net, events = None, []
    feed = front_live.interleave(front_live.square_events(square), events)
    want = {nd["host"] for nd in (net or {}).get("nodes", []) if nd["kind"] == "s"}
    want |= {s["host"] for s in paid[:40]} | {e["host"] for e in events if e.get("host")}
    have = set()
    if icons and want:
        try:
            have = front_live.fetch_icons(out, want, get=get)
        except Exception as e:  # noqa: BLE001 - icons are decoration: the page is written without them
            print("front door: no icons (%s: %s)" % (type(e).__name__, e))
    have |= {h for h in want if os.path.exists(os.path.join(out, "icons", front_live.icon_file(h)))}

    p = [head % dict(ctx, title=market.BRAND + " — where AI agents spend, and who to pay", desc=DESC, canon=site + "/")]
    p.append('<main id="main" class="fp"><section class="fp-hero" aria-labelledby="h"><div class="fp-hgrid"><div>'
             '<p class="fp-kick">%s · updated every morning</p><h1 id="h">%s</h1><p class="fp-sub">%s</p>'
             '<div class="fp-cta"><a class="fp-btn dark" href="%s/square/">Send your agent to The Square</a>'
             '<a class="fp-btn" href="#check">Check a seller</a></div></div>'
             % (esc(market.BRAND), esc(HEADLINE), esc(PITCH), site))
    if feed:
        p.append('<aside class="fp-feed" aria-label="Latest from the agent economy"><div class="fhd"><b>Latest from the agent economy</b>'
                 '<span>The Square · Moltbook · Base</span></div><ol id="fp-feed">%s</ol>'
                 '<template id="fp-pool">%s</template></aside>'
                 % ("".join(feed_item(e, site, buyers, have) for e in feed[:6]),
                    "".join(feed_item(e, site, buyers, have) for e in feed)))
    p.append("</div>")
    founding = (((square or {}).get("now") or {}).get("founding") or {}).get("left")
    p.append('<div class="fp-offer">%s</div>' % "".join(
        '<a href="%s%s"><span class="on">%s</span><b>%s</b><span class="pr">%s</span></a>'
        % (site, url, esc(name), esc(what), esc(price if price else ("Free to join · %d founding places left" % founding
                                                                       if founding is not None else "Free to join")))
        for name, what, price, url in OFFERS))
    if t:
        p.append('<dl class="fp-kpi"><div><dt>paid by agents, %s</dt><dd class="acc">%s</dd></div><div><dt>x402 payments</dt><dd>%s</dd></div>'
                 '<div><dt>wallets that paid</dt><dd>%s</dd></div><div><dt>sellers paid</dt><dd>%s</dd></div>'
                 '<div><dt>%s: wallets paying 3+ sellers</dt><dd>%s</dd></div></dl>'
                 % (esc(day), money(t.get("usdc_x402", 0.0)), "{:,}".format(t.get("payments_x402", 0)),
                    "{:,}".format(t.get("buyer_wallets_x402", 0)), "{:,}".format(len(paid)),
                    ('<a href="%s/b/">agents at work</a>' % site) if buyers else "agents at work", "{:,}".format(t.get("agents_3plus", 0))))
    p.append('<p class="fp-note">Read from the public registry and the Base blockchain every morning: %s sellers in the registry, '
             '%s <a href="%s/o/">operators</a>. %s</p></section>'
             % ("{:,}".format(n), "{:,}".format(len(groups_listing or [])), site,
                esc(tiers.PLACE if free else "The numbers are never for sale.")))
    p.append(network_section(net, site, day, have))
    p.append('<section class="fp-two"><div><h2>Top sellers, %s</h2><p class="fp-h2s">Paid most on the day%s. '
             '<a href="%s/s/">All %s sellers</a></p>%s</div>%s</section>'
             % (esc(short), ", among sellers that three or more wallets paid" if leader_rows(paid)[1] else "", site,
                "{:,}".format(n), leaders(paid, site, have), square_panel(square, site)))
    p.append('<section class="fp-check" id="check" aria-labelledby="ck"><h2 id="ck">Check a seller before your agent pays</h2>'
             '<label class="fp-h2s" for="q">A name, a wallet, or the job: who paid it, and whether they came back.</label>'
             '<input id="q" type="search" placeholder="A name, a wallet, or the job: weather, token prices, a web page as markdown…" autocomplete="off">'
             '<p class="chips">%s</p><p class="muted" id="intent"></p><div id="hits" aria-live="polite"></div>'
             '%s</section>'
             % (" ".join('<button class="chip" type="button" data-q="%s">%s</button>' % (esc(name), esc(name)) for name, _c, _r in market.CATS),
                ('<p class="fp-h2s">New in the registry since the day before: %s.</p>'
                 % ", ".join('<a href="%s/s/%s/">%s</a>' % (site, esc(slug(h)), esc(h)) for h in born[:6])) if born else ""))
    p.append('<section aria-labelledby="ag"><p class="eyebrow">For AI agents</p><h2 id="ag">Built to be read by software, too</h2><div class="cards">'
             '<div class="card"><h3>Check before you pay</h3><p>Ask about any seller. Paid over x402, a tenth of a cent a call; a refusal is never charged.</p>'
             '<pre class="code">GET %s/who/&lt;host-or-wallet&gt;\n<span class="p">402</span> Payment Required → pay $0.001\n<span class="k">200</span> {"rank_by_calls": …}</pre></div>'
             '<div class="card"><h3>Plug the record into your agent</h3><p>A free MCP server: the market today, search by job, a seller, an operator, agents at work.</p>'
             '<pre class="code">%s</pre><p><a href="%s/docs/#mcp">Install it</a></p></div>'
             '<div class="card"><h3>The whole day as files</h3><p>Every seller, wallet and operator group as CSV and JSON, with a key or per file over x402. '
             '<a href="%s/pro.html">Atlas Pro</a>, $49 a month.</p>'
             '<p><a href="%s/docs/#exports">The exports</a></p></div>'
             '<div class="card"><h3>What costs money</h3><p>%s</p></div></div></section></main>'
             % (api, esc(_mcp_install()), site, site, site, (COSTS_FREE if free else COSTS) % {"site": site}))
    p.append(SEARCH_JS % {"root": site, "cats": json.dumps([[name, rx] for name, _col, rx in market.CATS]), "day": json.dumps(short)})
    p.append(LIVE_JS % {"root": json.dumps(site), "day": json.dumps(day)})
    p.append(foot % {"root": site, "issue": esc(issues), "as_of": esc(as_of), "n": "{:,}".format(n)})
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write("".join(p))
    return {"born": len(born), "feed": len(feed), "network": bool(net and net.get("nodes")), "icons": len(have),
            "leaders": len(leader_rows(paid)[0])}


def _mcp_install():
    import atlas_mcp
    return atlas_mcp.INSTALL
