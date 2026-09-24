#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 079001a). Edit it there, not here.
"""network.py — the agent ecosystem tonight, as a movable 3D network.

Infoharmoni's real subject was never a hub with a crowd around it; it was
the interactions inside an ecosystem — who speaks to whom, communities at the
moment of their birth. This is that picture for the agent economy on X:

    node    one account that spoke, or was spoken to, in the three rooms tonight
    size    reach — log of followers
    line    an @mention tonight, from the speaker to the named; thicker when repeated
    pink    self-described agent or bot
    gold    an agent with a wallet — the four we are selling to
    white   this shop, @ausrine_ai
    grey    a human
    dust    voices that spoke tonight but named nobody, and were named by nobody

Reads the JSON that tools/x_read.py writes, plus the day's verified replies
from this shop, and emits network-<date>.json and an interactive 3D page
(three.js from cdnjs; drag to turn, wheel or pinch to zoom, tap a node).
Standard library only. MIT.

    python3 network.py --data data --out network-2026-09-09
"""

import argparse
import collections
import glob
import json
import os
import re
from datetime import date

import mandala  # same folder: kind(), BUYERS, US, ROOMS

# Replies this shop posted tonight, verified on X in the session that made
# this picture (ids are the reply tweets). They are the shop's own edges.
OUR_REPLIES = {
    "teneo_protocol": "2097816097365913897",
    "korprotocol": "2097816347493167250",
    "polsia": "2097816349514846575",
    "bankrbot": "2097816352127848804",
}


def build(data_dir):
    users = {}
    voices = mandala.load(data_dir)
    posts = []
    room_of_post = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        room = os.path.splitext(os.path.basename(path))[0]
        d = json.load(open(path))
        for a in d.get("authors", []):
            users[a["id"]] = a["username"].lower()
        for p in d.get("posts", []):
            posts.append(p)
            room_of_post[p["id"]] = room if room in mandala.ROOMS else None

    edges = collections.Counter()
    edge_room = {}
    edge_text = {}
    for p in posts:
        src = users.get(p["author_id"])
        if not src:
            continue
        for m in sorted(set(x.lower() for x in re.findall(r"@(\w{1,15})", p["text"]))):
            if m == src:
                continue
            edges[(src, m)] += 1
            edge_room.setdefault((src, m), room_of_post.get(p["id"]))
            edge_text.setdefault((src, m), p["text"][:200])
    for who, tid in OUR_REPLIES.items():
        edges[(mandala.US, who)] += 1
        edge_room[(mandala.US, who)] = "agent_economy"
        edge_text[(mandala.US, who)] = "reply " + tid

    names = set(voices) | {b for a, b in edges} | {a for a, b in edges}
    degree = collections.Counter()
    for (a, b), n in edges.items():
        degree[a] += n
        degree[b] += n

    nodes = []
    for u in sorted(names):
        v = voices.get(u)
        if v is None:
            v = {"username": u, "name": "", "followers": 0, "bio": "", "sample": "",
                 "rooms": set(), "engagement": 0}
            if u in mandala.BUYERS or u == mandala.US:
                pass
        nodes.append({
            "u": u, "n": v.get("name", ""), "f": v.get("followers", 0),
            "k": mandala.kind(v), "b": (v.get("bio") or "")[:160],
            "s": (v.get("sample") or "")[:200], "r": sorted(v.get("rooms", ())),
            "d": degree[u], "known": u in voices,
        })
    links = [{"a": a, "b": b, "w": n, "r": edge_room.get((a, b)), "t": edge_text.get((a, b), "")}
             for (a, b), n in sorted(edges.items())]
    communities = find_communities(nodes, links, posts, users)
    return nodes, links, communities


STOP = set("""the a an and or of to in on for with is are be this that it its as at by from
we you your our i my me they their them he she his her not no so if but can will just
how what who when where why all any more most new now one out up via than then there
here also about into over get got has have had do does did was were been being am
rt amp http https t co like very really much many some such only own same too s""".split())


def top_terms(texts, k=3, handles=()):
    c = collections.Counter()
    for t in texts:
        t = re.sub(r"@\w+", " ", t.lower())
        for w in re.findall(r"[#$]?[a-z][a-z0-9_]{2,}", t):
            if w.lstrip("#$") not in STOP and w.lstrip("#$") not in handles:
                c[w] += 1
    return [w for w, _ in c.most_common(k)]


def find_communities(nodes, links, posts, users, skip=()):
    """Connected circles of the mention graph; the big ones split by label
    propagation. Each is named by its hub and what its members were saying."""
    adj = collections.defaultdict(set)
    weight = collections.Counter()
    for l in links:
        if l["a"] in skip or l["b"] in skip:
            continue   # a hub that touches everything is the sun, not a member
        adj[l["a"]].add(l["b"]); adj[l["b"]].add(l["a"])
        weight[l["a"]] += l["w"]; weight[l["b"]] += l["w"]
    by_u = {n["u"]: n for n in nodes}
    seen, comps = set(), []
    for n in nodes:
        u = n["u"]
        if u in seen or u not in adj:
            continue
        st, c = [u], []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x); c.append(x); st.extend(adj[x] - seen)
        comps.append(c)
    groups = []
    for c in comps:
        if len(c) <= 15:
            groups.append(c); continue
        lab = {u: u for u in c}
        for _ in range(30):
            changed = False
            for u in sorted(c, key=lambda x: -weight[x]):
                cnt = collections.Counter(lab[v] for v in adj[u])
                best = max(cnt.items(), key=lambda kv: (kv[1], weight[kv[0]]))[0]
                if lab[u] != best:
                    lab[u] = best; changed = True
            if not changed:
                break
        sub = collections.defaultdict(list)
        for u in c:
            sub[lab[u]].append(u)
        groups.extend(sub.values())
    texts_by_u = collections.defaultdict(list)
    for pp in posts:
        u = users.get(pp["author_id"])
        if u:
            texts_by_u[u].append(pp["text"])
    out = []
    for g in sorted(groups, key=len, reverse=True):
        if len(g) < 3:
            continue
        hub = max(g, key=lambda u: (weight[u], by_u[u]["f"]))
        texts = [t for u in g for t in texts_by_u.get(u, [])]
        rooms = collections.Counter(r for u in g for r in by_u[u]["r"])
        room = rooms.most_common(1)[0][0] if rooms else None
        ai = sum(1 for u in g if by_u[u]["k"] != "human")
        cid = len(out)
        for u in g:
            by_u[u]["c"] = cid
        out.append({"id": cid, "hub": hub, "size": len(g), "ai": ai, "room": room,
                    "terms": top_terms(texts, handles=set(by_u)), "members": sorted(g, key=lambda u: -weight[u])})
    for n in nodes:
        n.setdefault("c", -1)
    return out


PAGE = r"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>__HEADX__
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&display=swap">
<style>
:root{--bg:#05060d;--ink:#f2f3f8;--muted:#9aa1b8;--line:#ffffff22;--pink:#ff4fa3;--gold:#ffd166;--grey:#7f8fa6}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font-family:"DM Sans","Helvetica Neue",Helvetica,Arial,sans-serif;overflow:hidden}
#c{position:fixed;inset:0;display:block;touch-action:none;cursor:grab}
#c:active{cursor:grabbing}
#hd{position:fixed;left:22px;top:18px;pointer-events:none}
#hd h1{margin:0;font-family:"Syne","DM Sans","Helvetica Neue",sans-serif;font-size:30px;font-weight:800;letter-spacing:.5px;text-wrap:balance}
#key{position:fixed;left:22px;bottom:46px;width:330px;background:#0b0e1cd9;border:1px solid var(--line);border-radius:12px;padding:11px 13px;font-size:12.5px;line-height:1.45;backdrop-filter:blur(6px);z-index:3}
#key .t{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:7px}
#key .kr{display:flex;gap:9px;align-items:flex-start;margin-bottom:6px;color:#d7dbe6}
#key .kr b{color:#fff;font-weight:600}
#key .sw{width:11px;height:11px;border-radius:50%;flex:0 0 11px;margin-top:3px}
#key svg{flex:0 0 56px;margin-top:1px}
#key #sizeBy{align-items:center;gap:8px;border-top:1px solid #ffffff14;padding-top:7px;margin-bottom:0}
#key #sizeBy label{display:inline-flex;gap:4px;align-items:center;cursor:pointer;color:var(--muted)}
#key #sizeBy label:has(input:checked){color:#fff}
#key #sizeBy input{position:absolute;opacity:0;width:0;height:0}
#key #sizeBy label:has(input:checked)::before{content:'●';color:var(--gold);font-size:9px}
#key #sizeBy label:not(:has(input:checked))::before{content:'○';font-size:9px}
@media (max-width:700px){#key{display:none}}
#ft{position:fixed;left:22px;bottom:14px;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#ffffff66;pointer-events:none;z-index:3}
#ft b{color:#ffffffaa;font-weight:600}
#hd p{margin:4px 0 0;font-size:14px;color:var(--muted)}
#hd p.k{font-size:12px;color:#ffffff88;margin-top:6px}
#tip{position:fixed;background:#0b0e1cf5;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:13px;max-width:320px;display:none;line-height:1.4;z-index:2}
#tip b{font-size:15px}#tip .q{color:var(--muted);margin-top:6px;font-style:italic}
#tip a{display:inline-block;margin-top:8px;color:var(--gold);text-decoration:none;font-weight:600}
#bar{position:fixed;left:0;right:0;bottom:0;display:flex;gap:16px;padding:10px 22px 40px;font-size:13px;color:var(--muted);flex-wrap:wrap;align-items:center;background:linear-gradient(#05060d00,#05060dee)}
#bar label{cursor:pointer;display:flex;gap:6px;align-items:center}
#bar input,#mode input{position:absolute;opacity:0;width:0;height:0;pointer-events:none}
#bar label,#mode label{padding:4px 10px;border:1px solid #ffffff22;border-radius:999px;color:var(--muted);user-select:none}
#bar label:has(input:checked),#mode label:has(input:checked){color:var(--ink);border-color:#ffffff66;background:#ffffff10}
#bar label:not(:has(input)){border-color:transparent;padding-left:0}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
#bar .hint{margin-left:auto;text-align:right}
#side{position:fixed;right:14px;top:16px;width:300px;max-height:calc(100% - 110px);overflow:auto;background:#0b0e1ccc;border:1px solid var(--line);border-radius:12px;padding:10px 12px;font-size:13px;backdrop-filter:blur(6px)}
#side .t{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
#side a{display:flex;justify-content:space-between;gap:8px;color:var(--ink);text-decoration:none;padding:4px 0;border-top:1px solid #ffffff10}
#side a:hover,#side a:focus{color:var(--gold);outline:none}
#side a .m{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
#side a.buyer{color:var(--gold)}#side a.us{color:#fff}
#side .row{display:grid;grid-template-columns:1fr auto;gap:1px 10px;padding:6px 0;border-top:1px solid #ffffff10}
#side .row a{color:var(--ink);text-decoration:none;font-weight:600;overflow-wrap:anywhere}
#side .row a:hover{color:var(--gold)}
#side .row .m{color:var(--gold);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
#side .row .d{grid-column:1/3;color:var(--muted);font-size:12px}
#side input#q{width:100%;box-sizing:border-box;background:#0b0e1c;border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit}
#qsort{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0 2px}
#qsort label{padding:3px 8px;border:1px solid #ffffff22;border-radius:999px;color:var(--muted);cursor:pointer;font-size:12px}
#qsort label:has(input:checked){color:var(--ink);border-color:#ffffff66;background:#ffffff10}
#qsort input{position:absolute;opacity:0;width:0;height:0}
#qres{max-height:300px;overflow:auto}
#qres .row a.sell{color:var(--sell,#ffb340)}#qres .row a.buy{color:var(--buy,#6ea8ff)}
#side .t{margin-top:10px}#side .t:first-child{margin-top:0}
#mode{display:flex;gap:6px;flex-wrap:wrap}#mode label{display:flex;gap:4px;align-items:center;cursor:pointer}
#roomkey{display:none;flex-wrap:wrap;gap:4px 10px;margin-top:6px;font-size:12px;color:var(--muted)}#roomkey i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}
#comms .c{display:block;padding:5px 0;border-top:1px solid #ffffff10;cursor:pointer}
#comms .c b{font-weight:600}#comms .c .m{color:var(--muted);font-size:12px;display:block}
#comms .c:hover,#comms .c.on{color:var(--gold)}
#side.hide{display:none}
.btn{background:#0b0e1ccc;border:1px solid #ffffff33;color:var(--ink);border-radius:999px;padding:6px 12px;font-size:13px;cursor:pointer;backdrop-filter:blur(6px)}
.btn:hover{border-color:#ffffff88}
#tog{position:fixed;right:14px;top:16px;z-index:3}
#ctl{position:fixed;right:14px;bottom:56px;display:flex;flex-direction:column;gap:6px;z-index:3}
#ctl .btn{width:44px;text-align:center;padding:6px 0}
#ctl #pause,#ctl #home{width:auto;padding:6px 10px}
#side{top:56px}
@media (max-width:600px){#bar .hint{flex-basis:100%;margin-left:0;text-align:left}#tip{max-width:80vw}}
__CSS__</style>
__TOP__<div id="stage"><canvas id="c"></canvas>
<div id="hd"><h1>AI Agent Economy</h1><p>__DATE__ · __SOURCE__</p><p class="k">__KEY__</p></div>
<div id="tip"></div>
<div id="key"><div class="t">how to read this</div>
<div class="kr"><span class="sw" id="swS" style="background:#ffb340"></span><b id="kwS">amber = a seller.</b> A service agents pay per call.</div>
<div class="kr"><span class="sw" id="swB" style="background:#6ea8ff"></span><b id="kwB">blue = a buyer.</b> A wallet that paid one.</div>
<div class="kr"><svg width="56" height="18" viewBox="0 0 56 18"><circle cx="6" cy="9" r="2.5" fill="#9aa1b8"/><circle cx="20" cy="9" r="5" fill="#9aa1b8"/><circle cx="40" cy="9" r="8.5" fill="#9aa1b8"/></svg><span id="sizeWhat"><b>size = payments in 24 h</b> — for a seller, payments it received; for a buyer, payments it made.</span></div>
<div class="kr"><svg width="56" height="18" viewBox="0 0 56 18"><line x1="2" y1="6" x2="54" y2="6" stroke="#8fa6c8" stroke-width="1"/><line x1="2" y1="13" x2="54" y2="13" stroke="#8fa6c8" stroke-width="3"/></svg><span><b>a line = money moved</b> between those two wallets; thicker = more payments.</span></div>
<div class="kr" id="sizeBy"><b>size by</b> <label><input type="radio" name="sz" value="pays" checked> payments</label> <label><input type="radio" name="sz" value="usd"> dollars</label></div>
</div>
<div id="ft">powered by <b>Infoharmoni</b></div>
<button id="tog" class="btn">lists</button>
<div id="ctl"><button class="btn" id="home" title="recentre">centre</button><button class="btn" id="pause" title="play">play</button><button class="btn" id="zin">+</button><button class="btn" id="zout">−</button></div>
<div id="side" class="hide">
<div class="t">colour the dots by</div>
<div id="mode"><label><input type="radio" name="mode" value="kind" checked> buyer or seller</label><label><input type="radio" name="mode" value="room"> what it sells</label><label><input type="radio" name="mode" value="comm"> which circle</label></div>
<div id="roomkey"></div>
<div class="t">the circles — a shop and its buyers</div><div id="comms"></div>
<div class="t">find a wallet</div><input id="q" placeholder="name, or what it sells — try trust, search, inference"><div id="qsort"><label><input type="radio" name="qs" value="usd" checked> by dollars</label><label><input type="radio" name="qs" value="pays"> by payments</label><label><input type="radio" name="qs" value="sell"> sellers</label><label><input type="radio" name="qs" value="buy"> buyers</label></div><div id="qres"></div><div id="panels"></div><div class="t" id="listT">AI agents tonight</div><div id="list"></div></div>
<div id="bar">
<label><input type="checkbox" id="fh" checked><span class="dot" style="background:var(--grey)"></span>humans</label>
<label><input type="checkbox" id="fa" checked><span class="dot" id="dotA" style="background:var(--pink)"></span>AI agents</label>
<label><span class="dot" id="dotB" style="background:var(--gold)"></span>AI agents with wallets</label>
<label id="lrepo"><span class="dot" style="background:#8ab4ff"></span>repositories</label>
<label><input type="checkbox" id="fd"><span class="dot" style="background:#3a3f55"></span>show the unconnected</label>
<span class="hint">click any dot for its card · scroll zooms where you point · drag turns · shift-drag pans · double-click or F fits · Esc closes</span>
</div>
</div>__BOTTOM__
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const G=__DATA__;
const PAL=G.palette||(G.panels?{seller:['#ffb340','amber'],buyer:['#6ea8ff','blue']}:null);
const hx=c=>parseInt(c.slice(1),16);
const COL={human:0x7f8fa6,agent:(PAL?hx(PAL.buyer[0]):0xff4fa3),buyer:(PAL?hx(PAL.seller[0]):0xffd166),us:0xffffff,repo:0x8ab4ff};
const ROOMCOL={null:0x9aa1b8}, ROOMNAME={}; Object.entries(G.rooms||{}).forEach(([k,v])=>{ROOMCOL[k]=parseInt(v.color.slice(1),16); ROOMNAME[k]=v.name;});
const CPAL=[0xff8c42,0x5ad1ff,0xb98cff,0x7bffb0,0xffd166,0xff4fa3,0x4fd8ff,0xffa8f0,0xa0ff6e,0xffc58a,0x8ab4ff,0xff7f7f];
const C=G.communities; const commCol=i=>i<0?0x3a3f55:CPAL[i%CPAL.length];
function roomCol(n){if(!n.r.length)return 0x4a5068; if(n.r.length===1)return ROOMCOL[n.r[0]]; const c=new THREE.Color(0); n.r.forEach(r=>c.add(new THREE.Color(ROOMCOL[r]).multiplyScalar(1/n.r.length))); return c.getHex();}
const KIND={human:'human',agent:'AI agent',buyer:'AI agent with a wallet',us:'this shop (AI agent)',repo:'repository'};
const prof=n=>n.url||('https://x.com/'+encodeURIComponent(n.u));
const AT=G.panels?'':'@';
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const N=G.nodes, L=G.links, idx={}; N.forEach((n,i)=>idx[n.u]=i);
const conn=N.map(n=>n.d>0);
// ---- layout: 3D force, run at load, then kept softly alive
const R=120*Math.sqrt(N.length/440); const pos=N.map((n,i)=>{const a=Math.random()*6.283,b=Math.acos(2*Math.random()-1),r=R*(0.4+0.6*Math.cbrt(Math.random()));
  return [r*Math.sin(b)*Math.cos(a),r*Math.sin(b)*Math.sin(a),r*Math.cos(b)];});
const vel=N.map(()=>[0,0,0]);
const LK=L.map(l=>[idx[l.a],idx[l.b],l.w]);
function step(t){
  const n=N.length; const f=pos.map(()=>[0,0,0]);
  for(let i=0;i<n;i++){const pi=pos[i], ci=conn[i];
    for(let j=i+1;j<n;j++){const pj=pos[j];
      let dx=pi[0]-pj[0],dy=pi[1]-pj[1],dz=pi[2]-pj[2]; let d2=dx*dx+dy*dy+dz*dz+0.5;
      const k=(ci&&conn[j])?900:(ci||conn[j]?250:120); const s=k/d2/Math.sqrt(d2);
      const fx=dx*s,fy=dy*s,fz=dz*s; f[i][0]+=fx;f[i][1]+=fy;f[i][2]+=fz;f[j][0]-=fx;f[j][1]-=fy;f[j][2]-=fz;}}
  for(const [a,b,w] of LK){const pa=pos[a],pb=pos[b];
    const dx=pb[0]-pa[0],dy=pb[1]-pa[1],dz=pb[2]-pa[2]; const d=Math.sqrt(dx*dx+dy*dy+dz*dz)+0.01;
    const s=(d-28)*0.02*Math.min(w,3); f[a][0]+=dx/d*s*d;f[a][1]+=dy/d*s*d;f[a][2]+=dz/d*s*d; f[b][0]-=dx/d*s*d;f[b][1]-=dy/d*s*d;f[b][2]-=dz/d*s*d;}
  const cen={}; N.forEach((nd,i)=>{if(nd.c>=0){const c=cen[nd.c]||(cen[nd.c]=[0,0,0,0]); c[0]+=pos[i][0];c[1]+=pos[i][1];c[2]+=pos[i][2];c[3]++;}});
  N.forEach((nd,i)=>{if(nd.c>=0){const c=cen[nd.c]; f[i][0]+=(c[0]/c[3]-pos[i][0])*0.14; f[i][1]+=(c[1]/c[3]-pos[i][1])*0.14; f[i][2]+=(c[2]/c[3]-pos[i][2])*0.14;}});
  const ck=Object.keys(cen); for(let a=0;a<ck.length;a++)for(let b=a+1;b<ck.length;b++){const A=cen[ck[a]],B=cen[ck[b]];
    const dx=A[0]/A[3]-B[0]/B[3],dy=A[1]/A[3]-B[1]/B[3],dz=A[2]/A[3]-B[2]/B[3]; const d2=dx*dx+dy*dy+dz*dz+1; const s=Math.min(6,(A[3]+B[3])*40/d2);
    N.forEach((nd,i)=>{if(nd.c==ck[a]){f[i][0]+=dx*s/Math.sqrt(d2);f[i][1]+=dy*s/Math.sqrt(d2);f[i][2]+=dz*s/Math.sqrt(d2);} else if(nd.c==ck[b]){f[i][0]-=dx*s/Math.sqrt(d2);f[i][1]-=dy*s/Math.sqrt(d2);f[i][2]-=dz*s/Math.sqrt(d2);}});}
  for(let i=0;i<n;i++){const p=pos[i]; const c=conn[i]?0.012:0.006; f[i][0]-=p[0]*c;f[i][1]-=p[1]*c;f[i][2]-=p[2]*c;
    for(let k=0;k<3;k++){vel[i][k]=(vel[i][k]+f[i][k]*t)*0.85; pos[i][k]+=Math.max(-6,Math.min(6,vel[i][k]));}}
}
for(let it=0;it<160;it++) step(0.5*(1-it/180));
// ---- three.js scene
const cv=document.getElementById('c'); const ren=new THREE.WebGLRenderer({canvas:cv,antialias:true,alpha:false});
ren.setPixelRatio(Math.min(devicePixelRatio,2)); ren.setClearColor(0x05060d,1);
const sc=new THREE.Scene(); const cam=new THREE.PerspectiveCamera(50,1,1,4000);
const root=new THREE.Group(); sc.add(root);
sc.add(new THREE.AmbientLight(0xffffff,0.55)); const pl=new THREE.PointLight(0xffffff,0.9); pl.position.set(200,300,400); sc.add(pl);
const geo=new THREE.SphereGeometry(1,14,10);
let sizeBy='pays';
function baseSize(n){const v=sizeBy==='usd'?(n.usd||0)*100:n.f;
  return (n.k==='human'?0.55:(n.k==='agent'&&G.panels?0.7:1))*(1.2+1.6*Math.log10(v+1)+0.25*Math.min(n.d,8));}
const meshes=N.map((n,i)=>{const s=baseSize(n);
  const m=new THREE.Mesh(geo,new THREE.MeshLambertMaterial({color:COL[n.k],emissive:COL[n.k],emissiveIntensity:n.k==='human'?0.1:(n.k==='agent'&&G.panels?0.3:0.6),transparent:true,opacity:n.k==='human'?(n.d?0.6:0.25):(n.k==='agent'&&G.panels?0.55:0.95)}));
  m.scale.setScalar(n.d?s:Math.min(s,2)); m.userData.i=i; m.userData.s=m.scale.x; root.add(m); return m;});
const lgeo=new THREE.BufferGeometry(); const lpos=new Float32Array(LK.length*6); const lcol=new Float32Array(LK.length*6);
L.forEach((l,i)=>{const c=new THREE.Color(G.panels?0x8fa6c8:(ROOMCOL[l.r]||0x9aa1b8)); const b=(G.panels?0.55:0.35)+0.2*Math.min(l.w,3);
  for(let e=0;e<2;e++){lcol[i*6+e*3]=c.r*b;lcol[i*6+e*3+1]=c.g*b;lcol[i*6+e*3+2]=c.b*b;}});
lgeo.setAttribute('position',new THREE.BufferAttribute(lpos,3)); lgeo.setAttribute('color',new THREE.BufferAttribute(lcol,3));
const lines=new THREE.LineSegments(lgeo,new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:0.9})); root.add(lines);
// labels for the ones worth naming: sprites drawn on canvas
function label(txt,color){const c=document.createElement('canvas'); const x=c.getContext('2d'); const F='600 28px "DM Sans", Helvetica Neue, Helvetica, Arial'; x.font=F;
  const w=x.measureText(txt).width+16; c.width=w; c.height=40; x.font=F; x.fillStyle=color; x.textBaseline='middle'; x.fillText(txt,8,20);
  const t=new THREE.CanvasTexture(c); t.minFilter=THREE.LinearFilter; const sp=new THREE.Sprite(new THREE.SpriteMaterial({map:t,transparent:true,depthTest:false}));
  sp.scale.set(w/40*7,7,1); return sp;}
const labels=[]; const LB=G.labels; let labelSet=null;
if(LB){const pool=N.map((n,i)=>[n,i]).filter(([n])=>LB.kinds.includes(n.k)).sort((a,b)=>(b[0].usd||b[0].f)-(a[0].usd||a[0].f)).slice(0,LB.top);
  labelSet=new Set(pool.map(([,i])=>i));}
const big=N.length>600; const buyerCut=big?[...N].filter(n=>n.k==='buyer').map(n=>n.f).sort((a,b)=>b-a)[40]||0:-1;
N.forEach((n,i)=>{ if(labelSet){ if(labelSet.has(i)){const sp=label((n.k==='repo'?'':'')+n.u,'#'+COL[n.k].toString(16).padStart(6,'0')); sp.userData.i=i; root.add(sp); labels.push(sp);} return;}
  if((n.k==='buyer'&&n.f>=buyerCut)||n.k==='us'||(n.k==='agent'&&(n.f>3000||n.d>(big?3:1)))||n.d>=(big?12:4)||(n.k!=='repo'&&n.f>60000)||(n.k==='repo'&&(n.f>(big?8000:2000)||n.d>=(big?15:6)))){
  const sp=label('@'+n.u,'#'+COL[n.k].toString(16).padStart(6,'0')); sp.userData.i=i; root.add(sp); labels.push(sp);} });
const cmax=Math.max(...C.map(c=>c.size));
const clabels=C.map(c=>{const sp=label(c.label||(c.terms.length?c.terms.slice(0,2).join(' · '):'@'+c.hub),'#dfe4f0'); sp.material.opacity=0.95; sp.scale.multiplyScalar(1.1+1.5*Math.sqrt(c.size/cmax)); sp.visible=false; root.add(sp); return sp;});
const hulls=C.map((c,i)=>{const m=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),new THREE.MeshBasicMaterial({color:commCol(i),transparent:true,opacity:0.07,depthWrite:false,side:THREE.BackSide})); root.add(m); return m;});
let mode=(G.mode||'kind'), onComm=-1; document.querySelectorAll('#mode input').forEach(r=>r.checked=(r.value===mode));
function recolour(){meshes.forEach((m,i)=>{const n=N[i]; const col=mode==='kind'?COL[n.k]:(mode==='room'?roomCol(n):commCol(n.c));
  m.material.color.setHex(col); m.material.emissive.setHex(col); m.material.emissiveIntensity=(mode==='kind'&&n.k==='human')?0.1:0.45;
  m.material.opacity=onComm>=0?(n.c===onComm?1:0.06):(n.k==='human'&&mode==='kind'?(n.d?0.6:0.25):(n.k==='agent'&&G.panels&&mode==='kind'?0.55:0.9));});
  clabels.forEach((sp,i)=>{sp.visible=mode==='comm'||onComm===i||C[i].size>=5; sp.material.opacity=(mode==='comm'||onComm===i)?0.95:0.5;});
  hulls.forEach((h,i)=>{h.material.opacity=onComm>=0?(onComm===i?0.18:0.02):(mode==='comm'?0.12:0.06);}); document.getElementById('roomkey').style.display=mode==='room'?'flex':'none';}
document.querySelectorAll('#mode input').forEach(r=>r.onchange=()=>{mode=r.value; recolour();});
document.getElementById('roomkey').innerHTML=Object.entries(G.rooms||{}).map(([k,v])=>'<span><i style="background:'+v.color+'"></i>'+esc(v.name)+'</span>').join('');
const comms=document.getElementById('comms');
C.forEach((c,i)=>{const d=document.createElement('span'); d.className='c';
  d.innerHTML='<b style="color:#'+commCol(i).toString(16).padStart(6,'0')+'">'+esc(c.label||('@'+c.hub+' +'+(c.size-1)))+'</b><span class="m">'+esc(c.note||c.terms.join(' · ')||'')+'</span>';
  d.onclick=()=>{onComm=onComm===i?-1:i; document.querySelectorAll('#comms .c').forEach((e,j)=>e.classList.toggle('on',j===onComm)); recolour();}; comms.appendChild(d);});
function sync(){N.forEach((n,i)=>{const p=pos[i]; meshes[i].position.set(p[0],p[1],p[2]);});
  C.forEach((c,ci)=>{let x=0,y=0,z=0,k=0; c.members.forEach(u=>{const p=pos[idx[u]]; x+=p[0];y+=p[1];z+=p[2];k++;}); x/=k;y/=k;z/=k;
    let r=0; c.members.forEach(u=>{const p=pos[idx[u]]; r=Math.max(r,Math.hypot(p[0]-x,p[1]-y,p[2]-z)+meshes[idx[u]].scale.x);});
    hulls[ci].position.set(x,y,z); hulls[ci].scale.setScalar(r+5); clabels[ci].position.set(x,y+r+9,z);});
  labels.forEach(sp=>{const p=pos[sp.userData.i]; sp.position.set(p[0]+meshes[sp.userData.i].scale.x+1,p[1]+3,p[2]);});
  LK.forEach(([a,b],i)=>{const pa=pos[a],pb=pos[b]; lpos.set([pa[0],pa[1],pa[2],pb[0],pb[1],pb[2]],i*6);}); lgeo.attributes.position.needsUpdate=true;}
// ---- controls: drag turns, wheel/pinch zooms, tap picks
let rx=0.3,ry=0,dist=540*Math.sqrt(N.length/440),drag=null,pinch=0,auto=false,lastMove=0,paused=true;
const target=new THREE.Vector3(); function recentre(){let x=0,y=0,z=0,k=0; N.forEach((n,i)=>{if(n.d>0){x+=pos[i][0];y+=pos[i][1];z+=pos[i][2];k++;}}); if(k){target.set(x/k,y/k,z/k);}}
function fitAll(){recentre(); const rs=[]; N.forEach((n,i)=>{if(n.d>0||fd.checked){rs.push(Math.hypot(pos[i][0]-target.x,pos[i][1]-target.y,pos[i][2]-target.z));}}); rs.sort((a,b)=>a-b); const R=rs[Math.floor(rs.length*0.93)]||rs[rs.length-1]||100; dist=Math.min(1600,Math.max(80,R/Math.tan(cam.fov*Math.PI/360)*1.08+40));}
fitAll(); document.getElementById('home').onclick=()=>{rx=0.3; ry=0; fitAll();};
function pan(dx,dy){const s=dist*0.0016; const right=new THREE.Vector3(Math.cos(ry),0,-Math.sin(ry)); const up=new THREE.Vector3(-Math.sin(ry)*Math.sin(rx),Math.cos(rx),-Math.cos(ry)*Math.sin(rx)); target.addScaledVector(right,-dx*s).addScaledVector(up,dy*s);}
document.getElementById('tog').onclick=()=>{const s=document.getElementById('side'); s.classList.toggle('hide'); tog.textContent=s.classList.contains('hide')?'lists':'hide lists';};
document.getElementById('pause').onclick=()=>{paused=!paused; pause.textContent=paused?'play':'pause';};
document.getElementById('zin').onclick=()=>{dist=Math.max(60,dist*0.8);};
document.getElementById('zout').onclick=()=>{dist=Math.min(1600,dist*1.25);};
function resize(){const w=cv.clientWidth||innerWidth,h=cv.clientHeight||innerHeight; ren.setSize(w,h,false); cam.aspect=w/h; cam.updateProjectionMatrix();} addEventListener('resize',resize); resize();
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,moved:false,pan:e.button===2||e.shiftKey}; cv.setPointerCapture(e.pointerId);});
cv.addEventListener('contextmenu',e=>e.preventDefault());
let hoverT=0;
cv.addEventListener('pointermove',e=>{if(!drag){if(pinned<0)pick(e,false);return;} const dx=e.clientX-drag.x,dy=e.clientY-drag.y; if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;
  if(drag.pan){pan(dx,dy);} else {ry+=dx*0.0042; rx=Math.max(-1.45,Math.min(1.45,rx+dy*0.0042));} drag.x=e.clientX;drag.y=e.clientY; auto=false; lastMove=performance.now();});
cv.addEventListener('pointerup',e=>{if(drag&&!drag.moved)pick(e,true); drag=null;});
cv.addEventListener('wheel',e=>{e.preventDefault(); dist=Math.max(60,Math.min(1200,dist*(1+e.deltaY*0.001)));},{passive:false});
let tmid=null;
cv.addEventListener('touchstart',e=>{if(e.touches.length===2){pinch=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY); tmid=[(e.touches[0].clientX+e.touches[1].clientX)/2,(e.touches[0].clientY+e.touches[1].clientY)/2];}},{passive:true});
cv.addEventListener('touchmove',e=>{if(e.touches.length===2&&pinch){const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY); dist=Math.max(60,Math.min(1200,dist*pinch/d)); pinch=d; const m=[(e.touches[0].clientX+e.touches[1].clientX)/2,(e.touches[0].clientY+e.touches[1].clientY)/2]; if(tmid)pan(m[0]-tmid[0],m[1]-tmid[1]); tmid=m; drag=null;}},{passive:true});
const ray=new THREE.Raycaster(); ray.params.Points={threshold:4}; const tip=document.getElementById('tip'); let sel=-1, pinned=-1;
function pick(e,stick){const R=cv.getBoundingClientRect(); const m=new THREE.Vector2(((e.clientX-R.left)/R.width)*2-1,-((e.clientY-R.top)/R.height)*2+1); ray.setFromCamera(m,cam);
  if(stick){const lh=ray.intersectObjects(labels.filter(x=>x.visible))[0]; if(lh){window.open(prof(N[lh.object.userData.i]),'_blank'); return;}}
  let hit=ray.intersectObjects(meshes.filter(x=>x.visible))[0];
  if(!hit){ // nothing exactly under the pointer: take the nearest visible dot within reach
    const px=e.clientX,py=e.clientY; let best=null,bd=stick?34:20;
    const v=new THREE.Vector3();
    meshes.forEach(m=>{if(!m.visible)return; v.copy(m.position).project(cam); if(v.z>1)return;
      const sx=R.left+(v.x*0.5+0.5)*R.width, sy=R.top+(-v.y*0.5+0.5)*R.height; const d=Math.hypot(sx-px,sy-py);
      if(d<bd){bd=d;best=m;}});
    if(best)hit={object:best,point:best.position.clone()};}
  if(!hit){if(stick||pinned<0){tip.style.display='none';sel=-1;pinned=-1;cv.style.cursor='grab';}return;}
  const n=N[hit.object.userData.i]; if(!stick&&sel===hit.object.userData.i)return; sel=hit.object.userData.i; if(stick){pinned=sel; target.copy(hit.object.position); dist=Math.max(60,Math.min(dist,110+hit.object.scale.x*16));} cv.style.cursor='pointer';
  const said=L.filter(l=>l.a===n.u).map(l=>l.b), heard=L.filter(l=>l.b===n.u).map(l=>l.a);
  const onch=/basescan|solscan/.test(n.url||'');
  const what=({human:'a person',agent:onch?'a buyer — the wallet that paid':'an AI agent',buyer:onch?'a seller with a wallet':'an AI agent with a wallet',us:'this shop — an AI agent',repo:'a repository'})[n.k]+(n.chain?' · '+n.chain:'');
  tip.innerHTML='<div style="font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:2px">'+what+'</div><b>'+(n.k==='repo'?'':AT)+esc(n.u)+'</b>'+(n.n?' · '+esc(n.n):'')+'<br>'+(n.known&&!(n.url||'').includes('basescan')?n.f.toLocaleString()+(n.k==='repo'?' stars · ':(n.url&&n.url.includes('github')?' commits · ':' followers · ')):'')+
    (n.r.length?n.r.map(r=>ROOMNAME[r]).join(' + '):'')+(n.c>=0&&C[n.c].label&&!/^shared market/.test(C[n.c].label)?'<br><span style="color:var(--muted)">in: '+esc(C[n.c].label)+'</span>':'')+
    (said.length?'<br>'+(G.panels?'paid':'spoke to')+': '+said.slice(0,6).map(u=>AT+esc(u)).join(', ')+(said.length>6?' +'+(said.length-6):''):'')+
    (heard.length?'<br>'+(G.panels?'paid by':'named by')+': '+heard.slice(0,6).map(u=>AT+esc(u)).join(', ')+(heard.length>6?' +'+(heard.length-6):''):'')+
    (n.b?'<br><span style="color:var(--muted)">'+esc(n.b)+'</span>':'')+(n.wallet&&n.wallet.length?'<br><span style="font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--muted)">'+esc(n.wallet[0])+'</span>':'')+(n.s?'<div class="q">“'+esc(n.s)+'”</div>':'')+
    '<a href="'+esc(prof(n))+'" target="_blank" rel="noopener">open '+(n.k==='repo'?'':AT)+esc(n.u)+' →</a>';
  tip.style.display='block'; tip.style.left=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8)+'px'; tip.style.top=Math.min(e.clientY+12,innerHeight-tip.offsetHeight-60)+'px';}
addEventListener('scroll',()=>{tip.style.display='none'; sel=-1; pinned=-1;},{passive:true});   // the card is pinned to the window, the dots are not
function filt(){const h=fh.checked,a=fa.checked,d=fd.checked;
  meshes.forEach((m,i)=>{const n=N[i]; const on=(n.k==='human'?h:(n.k==='agent'?a:true))&&(n.d>0||d); m.visible=on;});
  labels.forEach(sp=>sp.visible=meshes[sp.userData.i].visible);}
[fh,fa,fd].forEach(el=>el.onchange=filt); filt(); recolour();
document.querySelectorAll('#sizeBy input').forEach(r=>r.onchange=()=>{sizeBy=r.value;
  meshes.forEach((m,i)=>{const s=baseSize(N[i]); m.userData.s=N[i].d?s:Math.min(s,2); m.scale.setScalar(m.userData.s);});
  document.getElementById('sizeWhat').innerHTML=sizeBy==='usd'
    ? '<b>size = USDC in 24 h</b> — for a seller, dollars it earned; for a buyer, dollars it spent.'
    : '<b>size = payments in 24 h</b> — for a seller, payments it received; for a buyer, payments it made.';});
if(location.search.includes('still')){['bar','side','ctl','tog','key'].forEach(id=>{const e=document.getElementById(id); if(e)e.style.display='none';});}
// the legend only names what is actually in this picture
const present=new Set(N.map(n=>n.k));
if(PAL){const a=document.getElementById('dotA'),b=document.getElementById('dotB'); if(a)a.style.background=PAL.buyer[0]; if(b)b.style.background=PAL.seller[0];
  swS.style.background=PAL.seller[0]; swB.style.background=PAL.buyer[0]; kwS.textContent=PAL.seller[1]+' = a seller.'; kwB.textContent=PAL.buyer[1]+' = a buyer.';
  document.documentElement.style.setProperty('--sell',PAL.seller[0]); document.documentElement.style.setProperty('--buy',PAL.buyer[0]);}
if(!present.has('repo'))document.getElementById('lrepo').remove();
if(!present.has('human'))document.querySelector('#bar label:has(#fh)').remove();
if(!present.has('agent'))document.querySelector('#bar label:has(#fa)').remove();
if(N.every(n=>n.d>0))document.querySelector('#bar label:has(#fd)').remove();
{const onchain=N.some(n=>(n.url||'').includes('basescan'));
 const la=document.querySelector('#bar label:has(#fa)'); if(la&&onchain)la.lastChild.textContent='buyers — the wallets that paid';
 const lb=[...document.querySelectorAll('#bar label')].find(e=>/wallets/.test(e.textContent)); if(lb&&onchain)lb.lastChild.textContent='sellers with a wallet';}
// the list on the right: every AI agent seen tonight, biggest reach first, linked to X
const list=document.getElementById('list');
if(G.panels&&G.panels.length){ document.getElementById('listT').remove(); list.remove();
  // search: every wallet, filterable by name or by what it sells / buys
  const q=document.getElementById('q'), qres=document.getElementById('qres');
  const money=v=>'$'+(v>=1000?(v/1000).toFixed(1)+'k':(v||0).toFixed(2));
  let qs='usd';
  function search(){const f=q.value.trim().toLowerCase();
    let rows=N.filter(n=>!f||n.u.toLowerCase().includes(f)||(n.s||'').toLowerCase().includes(f)||(n.b||'').toLowerCase().includes(f));
    if(qs==='sell')rows=rows.filter(n=>n.k==='buyer'); if(qs==='buy')rows=rows.filter(n=>n.k==='agent');
    rows.sort((a,b)=>qs==='pays'?b.f-a.f:((b.usd||0)-(a.usd||0))||b.f-a.f);
    qres.innerHTML=rows.slice(0,60).map(n=>'<div class="row"><a class="'+(n.k==='buyer'?'sell':'buy')+'" href="'+esc(n.url)+'" target="_blank" rel="noopener" data-u="'+esc(n.u)+'">'+esc(n.u)+'</a><span class="m">'+money(n.usd)+' · '+n.f.toLocaleString()+' pays</span><span class="d">'+esc((n.s||n.b||'').slice(0,100))+'</span></div>').join('')
      +(rows.length>60?'<div class="row"><span class="d">+'+(rows.length-60)+' more — type to narrow</span></div>':'');
    qres.querySelectorAll('a').forEach(a=>{a.addEventListener('mouseenter',()=>{const i=N.findIndex(n=>n.u===a.dataset.u); if(i<0)return; meshes.forEach((m,j)=>m.material.opacity=(j===i?1:0.05)); if(meshes[i])target.copy(meshes[i].position);});
      a.addEventListener('mouseleave',recolour);});}
  q.addEventListener('input',search);
  document.querySelectorAll('#qsort input').forEach(r=>r.onchange=()=>{qs=r.value; search();});
  search();
  document.getElementById('panels').innerHTML=G.panels.map(p=>'<div class="t">'+esc(p.title)+'</div>'+p.rows.map(r=>
    '<div class="row"><a href="'+esc(r.url)+'" target="_blank" rel="noopener">'+esc(r.name)+'</a><span class="m">'+esc(r.metric)+'</span><span class="d">'+esc(r.sub)+'</span></div>').join('')).join('');
  document.querySelectorAll('#panels .row a').forEach(a=>{const u=a.textContent.toLowerCase();
    a.addEventListener('mouseenter',()=>{const i=N.findIndex(n=>n.u.toLowerCase()===u); if(i<0)return; meshes.forEach((m,j)=>m.material.opacity=(j===i?1:0.06)); if(meshes[i])target.copy(meshes[i].position);});
    a.addEventListener('mouseleave',recolour);});
} else N.map((n,i)=>[n,i]).filter(([n])=>n.k!=='human'&&n.k!=='repo').sort((x,y)=>(y[0].f-x[0].f)||(y[0].d-x[0].d)).forEach(([n,i])=>{
  const a=document.createElement('a'); a.href=prof(n); a.target='_blank'; a.rel='noopener'; a.className=n.k;
  a.innerHTML='<span>@'+esc(n.u)+'</span><span class="m">'+[n.known?(n.f>=1000?(n.f/1000).toFixed(n.f>=10000?0:1)+'k':String(n.f)):'',n.d?n.d+' ties':''].filter(Boolean).join(' · ')+'</span>';
  a.addEventListener('mouseenter',()=>{meshes.forEach((m,j)=>m.material.opacity=(j===i?1:(N[j].d?0.25:0.08)));});
  a.addEventListener('mouseleave',recolour);
  list.appendChild(a);});
// ---- render loop: the swarm keeps breathing
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
function frame(t){ if(!reduced&&!paused){  if((t|0)%3===0) step(0.03); }
  sync(); cam.position.set(target.x+dist*Math.sin(ry)*Math.cos(rx),target.y+dist*Math.sin(rx),target.z+dist*Math.cos(ry)*Math.cos(rx)); cam.lookAt(target);
  const pulse=paused?1:1+0.06*Math.sin(t/900); if(!paused)meshes.forEach((m,i)=>{if(N[i].k!=='human')m.scale.setScalar(m.userData.s*pulse);});
  ren.render(sc,cam); requestAnimationFrame(frame);} requestAnimationFrame(frame);
</script>
"""


GRAPH_KEYS = ("rooms", "source", "key", "mode", "panels", "labels", "totals", "palette")


def render(g, today, title="AI Agent Economy", head="", css="", top="", bottom=""):
    """The page for one graph: g has nodes, links and communities, and may carry the
    keys in GRAPH_KEYS. head goes into <head>; css is appended to the page's own; top
    and bottom are markup placed above and below the stage (canvas and its controls).
    With neither, the stage fills the window as it always has."""
    data = {"nodes": g["nodes"], "links": g["links"], "communities": g["communities"]}
    data.update({k: g[k] for k in GRAPH_KEYS if k in g})
    blob = json.dumps(data).replace("</", "<\\/")      # a stranger's host name cannot close the script
    page = (PAGE.replace("__TITLE__", title).replace("__HEADX__", head).replace("__CSS__", css)
            .replace("__TOP__", top).replace("__BOTTOM__", bottom)
            .replace("__DATE__", today).replace("__SOURCE__", g.get("source", ""))
            .replace("__KEY__", g.get("key", "sphere = one account · size = reach (followers) · line = an @mention tonight")))
    return page.replace("__DATA__", blob)       # last, so nothing inside the data is ever substituted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="network-" + date.today().isoformat())
    ap.add_argument("--date", default=date.today().isoformat(), help="the night the data was pulled")
    ap.add_argument("--graph", help="render a prebuilt graph JSON (nodes, links, communities, rooms) instead of X data")
    a = ap.parse_args()
    extra = {}
    if a.graph:
        g = json.load(open(a.graph))
        nodes, links, communities = g["nodes"], g["links"], g["communities"]
        extra = {k: g[k] for k in GRAPH_KEYS if k in g}
        a.date = g.get("date", a.date)
    else:
        nodes, links, communities = build(a.data)
        extra = {"rooms": {k: {"name": v[0], "color": v[1]} for k, v in mandala.ROOMS.items()}, "source": "X · three rooms, recent search"}
    today = a.date
    json.dump({"date": today, "nodes": nodes, "links": links, "communities": communities}, open(a.out + ".json", "w"), indent=1)
    page = render({"nodes": nodes, "links": links, "communities": communities, **extra}, today)
    open(a.out + ".html", "w").write(page)
    connected = sum(1 for n in nodes if n["d"] > 0)
    print("nodes: %d (%d connected) · links: %d · communities: %d" % (len(nodes), connected, len(links), len(communities)))
    for c in communities[:8]:
        print("  %2d  @%-18s %3d members (%d AI)  %-16s %s" % (c["id"], c["hub"], c["size"], c["ai"], c["room"] or "-", " ".join(c["terms"])))
    print("wrote %s.json and %s.html" % (a.out, a.out))


if __name__ == "__main__":
    main()
