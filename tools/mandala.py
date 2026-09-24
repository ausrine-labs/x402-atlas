#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 079001a). Edit it there, not here.
"""mandala.py — the agent internet tonight, drawn as an Infoharmoni mandala.

The inheritance: Infoharmoni (2009) drew the live social web as a mandala —
dark field, the subject at centre, the crowd clustered around it, venues as
named stars at the rim pulling their people along coloured rays. "Data is the
interface." What mattered was not who was big but how attention DEVELOPED.

This is the same picture with the new swarm in it: not topics, not repo
counts — the individual voices talking about the agent economy on X right
now, each one a dot, sized by reach, placed by which room it is in and how
hot its post ran tonight. Agents are marked apart from humans. The four
agents with wallets we are selling to are gold.

    voice   one account that posted in one of the rooms tonight
    size    reach — log of followers
    ring    heat — engagement on its post tonight; hotter is nearer the centre
    ray     the room it spoke in; a voice in two rooms sits between them
    pink    self-described agent or bot (bio says so)
    gold    an agent with a wallet — the buyers
    white   this shop, @ausrine_ai, in its own swarm

Reads the JSON that tools/x_read.py writes (one file per room), emits an SVG
for posting and an interactive HTML (hover a dot: who, reach, what they said;
click: their profile). Standard library only. MIT.

    python3 mandala.py --data data --out mandala-2026-09-09
"""

import argparse
import glob
import hashlib
import html
import json
import math
import os
import re
from datetime import date

W = H = 1200
CX = CY = 600.0
R_INNER = 90.0       # the subject's own disc
R_OUTER = 470.0      # where the room stars sit
BUYERS = {"teneo_protocol", "bankrbot", "korprotocol", "polsia"}
US = "ausrine_ai"
# accounts that are AI agents but whose bio does not say so
KNOWN_AGENTS = {"grok"}

ROOMS = {
    "agent_economy": ("agentic commerce", "#ff8c42"),
    "mcp": ("MCP servers", "#5ad1ff"),
    "agents": ("autonomous agents", "#b98cff"),
}

AGENT_BIO = re.compile(
    r"\b(agent|bot|autonomous|automated|i am an ai|ai that|ai-native|"
    r"onchain ai|llm|not a human|operated by)\b", re.I)


def load(data_dir):
    """Every voice, with the set of rooms it spoke in and its hottest post."""
    voices = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        room = os.path.splitext(os.path.basename(path))[0]
        d = json.load(open(path))
        for a in d.get("authors", []):
            key = a["username"].lower()
            v = voices.setdefault(key, dict(a, rooms=set(), engagement=0))
            if room in ROOMS:
                v["rooms"].add(room)
            v["engagement"] = max(v["engagement"], a.get("engagement", 0))
            v["followers"] = max(v["followers"], a.get("followers", 0))
            if a.get("sample") and not v.get("sample"):
                v["sample"] = a["sample"]
                v["top_post_id"] = a.get("top_post_id", "")
    return voices


def kind(v):
    u = v["username"].lower()
    if u == US:
        return "us"
    if u in BUYERS:
        return "buyer"
    if u in KNOWN_AGENTS or AGENT_BIO.search(v.get("bio", "") or "") or u.endswith("bot"):
        return "agent"
    return "human"


def jitter(seed, lo, hi):
    h = int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return lo + h * (hi - lo)


def place(v, angles):
    """Angle from the rooms a voice spoke in; radius from tonight's heat."""
    rooms = sorted(v["rooms"]) or [None]
    if rooms == [None]:
        ang = jitter(v["username"] + "a", 0, 2 * math.pi)
    else:
        x = sum(math.cos(angles[r]) for r in rooms)
        y = sum(math.sin(angles[r]) for r in rooms)
        ang = math.atan2(y, x)
        spread = 0.42 if len(rooms) == 1 else 0.12
        ang += jitter(v["username"] + "a", -spread, spread)
    heat = math.log1p(v["engagement"])
    heat_n = min(heat / math.log1p(300), 1.0)
    r = R_INNER + 40 + (1.0 - heat_n) * (R_OUTER - R_INNER - 90)
    r += jitter(v["username"] + "r", -22, 22)
    if v["username"].lower() == US:
        r = R_INNER + 26
    return CX + r * math.cos(ang), CY + r * math.sin(ang), ang


def size(v):
    return 2.2 + 2.6 * math.log10(max(v["followers"], 1) + 1)


COLORS = {
    "us": "#ffffff",
    "buyer": "#ffd166",
    "agent": "#ff4fa3",
    "human": "#7f8fa6",
}


def esc(s):
    return html.escape(str(s), quote=True)


def draw(voices, today):
    rooms = list(ROOMS)
    angles = {r: -math.pi / 2 + i * 2 * math.pi / len(rooms) for i, r in enumerate(rooms)}
    placed = []
    for v in voices.values():
        x, y, ang = place(v, angles)
        placed.append((v, x, y))
    # big dots under small so nothing is buried
    placed.sort(key=lambda t: -size(t[0]))

    n_agents = sum(1 for v in voices.values() if kind(v) == "agent")
    n_buyers = sum(1 for v in voices.values() if kind(v) == "buyer")

    o = []
    o.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
             'font-family="Helvetica Neue, Helvetica, Arial, sans-serif">' % (W, H, W, H))
    o.append('<defs>'
             '<radialGradient id="field" cx="50%" cy="50%" r="60%">'
             '<stop offset="0" stop-color="#101426"/><stop offset="1" stop-color="#05060d"/>'
             '</radialGradient>'
             '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
             '<feGaussianBlur stdDeviation="4" result="b"/>'
             '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
             '<filter id="soft" x="-50%" y="-50%" width="200%" height="200%">'
             '<feGaussianBlur stdDeviation="1.2"/></filter>'
             '</defs>')
    o.append('<rect width="%d" height="%d" fill="url(#field)"/>' % (W, H))

    # rings: heat bands
    for k in range(1, 5):
        r = R_INNER + 40 + k * (R_OUTER - R_INNER - 90) / 4
        o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="#ffffff" '
                 'stroke-opacity="0.06" stroke-width="1"/>' % (CX, CY, r))

    # rays and room stars
    for r_key in rooms:
        name, col = ROOMS[r_key]
        a = angles[r_key]
        x2, y2 = CX + R_OUTER * math.cos(a), CY + R_OUTER * math.sin(a)
        o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-opacity="0.35" '
                 'stroke-width="1.5"/>' % (CX, CY, x2, y2, col))
        # sector wash
        a0, a1 = a - 0.5, a + 0.5
        o.append('<path d="M%.1f,%.1f L%.1f,%.1f A%.1f,%.1f 0 0 1 %.1f,%.1f Z" fill="%s" fill-opacity="0.045"/>'
                 % (CX, CY, CX + R_OUTER * math.cos(a0), CY + R_OUTER * math.sin(a0),
                    R_OUTER, R_OUTER, CX + R_OUTER * math.cos(a1), CY + R_OUTER * math.sin(a1), col))
        o.append('<circle class="star" cx="%.1f" cy="%.1f" r="9" fill="%s" filter="url(#glow)"/>' % (x2, y2, col))
        n_here = sum(1 for v in voices.values() if r_key in v["rooms"])
        # label sits radially outside the star, centred, kept inside the canvas
        lx = min(max(x2 + 26 * math.cos(a), 150), W - 150)
        ly = y2 + 26 * math.sin(a)
        dy = -12 if math.sin(a) < -0.3 else 24
        o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="22" font-weight="600" fill="%s">%s</text>'
                 % (lx, ly + dy, col, esc(name)))
        o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="14" fill="%s" fill-opacity="0.7">%d voices tonight</text>'
                 % (lx, ly + dy + 20, col, n_here))

    # the crowd
    labelled = 0
    label_after = []
    for v, x, y in placed:
        k = kind(v)
        col = COLORS[k]
        s = size(v)
        op = {"human": 0.55, "agent": 0.92, "buyer": 1.0, "us": 1.0}[k]
        extra = ' filter="url(#glow)"' if k in ("buyer", "us", "agent") and s > 6 else ""
        o.append('<circle class="v" cx="%.1f" cy="%.1f" r="%.1f" fill="%s" fill-opacity="%.2f"%s>'
                 '<title>@%s · %s followers · %s</title></circle>'
                 % (x, y, s, col, op, extra, esc(v["username"]), "{:,}".format(v["followers"]),
                    esc((v.get("bio") or "")[:80])))
        if k in ("buyer", "us") or (k == "agent" and v["followers"] > 3000) or v["followers"] > 60000:
            label_after.append((v, x, y, s, col, k))

    for v, x, y, s, col, k in label_after:
        fs = 15 if k in ("buyer", "us") else 12
        o.append('<text x="%.1f" y="%.1f" font-size="%d" fill="%s" fill-opacity="0.95" '
                 'font-weight="%s">@%s</text>'
                 % (x + s + 4, y + 4, fs, col, "700" if k in ("buyer", "us") else "400", esc(v["username"])))

    # the subject at centre
    o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="#0b0e1c" stroke="#ffffff" stroke-opacity="0.25" stroke-width="1.5"/>'
             % (CX, CY, R_INNER))
    o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="15" fill="#ffffff" fill-opacity="0.9" letter-spacing="2">THE AGENT</text>'
             % (CX, CY - 14))
    o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="15" fill="#ffffff" fill-opacity="0.9" letter-spacing="2">INTERNET</text>'
             % (CX, CY + 6))
    o.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12" fill="#ffffff" fill-opacity="0.55">%s</text>'
             % (CX, CY + 28, today))

    # title + legend
    o.append('<text x="40" y="52" font-size="30" font-weight="700" fill="#ffffff" letter-spacing="1">AI Agent Economy</text>')
    o.append('<text x="40" y="78" font-size="16" fill="#ffffff" fill-opacity="0.7">%s · X, three rooms</text>' % today)
    ly = H - 70
    leg = [("#ff4fa3", "agents talking (%d)" % n_agents), ("#ffd166", "agents with wallets (%d)" % n_buyers),
           ("#7f8fa6", "humans")]
    if US in voices:
        leg.append(("#ffffff", "@ausrine_ai — this shop"))
    lx = 40
    for col, txt in leg:
        o.append('<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (lx, ly, col))
        o.append('<text x="%d" y="%d" font-size="14" fill="#ffffff" fill-opacity="0.8">%s</text>' % (lx + 14, ly + 5, esc(txt)))
        lx += 14 + 8 * len(txt) + 30
    o.append('<text x="%d" y="%d" text-anchor="end" font-size="13" fill="#ffffff" fill-opacity="0.45">'
             'live from X · drawn by @ausrine_ai</text>' % (W - 40, H - 30))
    o.append('</svg>')
    return "\n".join(o)


def html_page(svg, voices, today):
    """Interactive: tap a dot for who/reach/what they said, tap the handle for
    the profile; toggle humans and agents; the swarm breathes."""
    rows = []
    for v in voices.values():
        rows.append({
            "u": v["username"], "n": v.get("name", ""), "f": v["followers"],
            "k": kind(v), "b": (v.get("bio") or "")[:160], "s": (v.get("sample") or "")[:200],
            "r": sorted(v["rooms"]), "e": v["engagement"],
        })
    data = json.dumps(rows)
    svg_i = svg.replace(' width="%d" height="%d"' % (W, H), "", 1)
    return """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Agent Economy</title>
<style>
:root{--bg:#05060d;--ink:#f2f3f8;--muted:#9aa1b8;--line:#ffffff22;--pink:#ff4fa3;--gold:#ffd166;--grey:#7f8fa6}
body{background:var(--bg);color:var(--ink);font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;margin:0}
#wrap{max-width:1100px;margin:0 auto;position:relative}
svg{width:100%%;height:auto;display:block}
circle.v{cursor:pointer;transform-box:fill-box;transform-origin:center;animation:breathe 6s ease-in-out infinite}
circle.v.dim{opacity:.08}
@keyframes breathe{0%%,100%%{transform:scale(1)}50%%{transform:scale(1.18)}}
.star{transform-box:fill-box;transform-origin:center;animation:breathe 4s ease-in-out infinite}
@media (prefers-reduced-motion:reduce){circle.v,.star{animation:none}}
#tip{position:absolute;background:#0b0e1cf5;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:13px;max-width:300px;display:none;line-height:1.4;z-index:2}
#tip b{font-size:15px}#tip .q{color:var(--muted);margin-top:6px;font-style:italic}
#tip a{display:inline-block;margin-top:8px;color:var(--gold);text-decoration:none;font-weight:600}
#bar{display:flex;gap:18px;padding:12px 24px 28px;font-size:14px;color:var(--muted);flex-wrap:wrap;align-items:center;max-width:1100px;margin:0 auto}
#bar label{cursor:pointer;display:flex;gap:6px;align-items:center}
#bar input{accent-color:var(--gold)}
#bar .dot{width:9px;height:9px;border-radius:50%%;display:inline-block}
#bar .hint{flex-basis:100%%;font-size:13px}
@media (max-width:600px){#tip{max-width:80vw}}
</style>
<div id="wrap">%s<div id="tip"></div></div>
<div id="bar">
<label><input type="checkbox" id="fh" checked><span class="dot" style="background:var(--grey)"></span>humans</label>
<label><input type="checkbox" id="fa" checked><span class="dot" style="background:var(--pink)"></span>agents</label>
<span class="hint">Tap a dot: who it is, their reach, what they said tonight. Tap the handle to open their profile. Drawn %s from X recent search across three rooms.</span>
</div>
<script>
const V=%s; const byU={}; V.forEach(v=>byU[v.u.toLowerCase()]=v);
const KIND={human:'human',agent:'agent',buyer:'agent with a wallet',us:'this shop'};
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const tip=document.getElementById('tip'), wrap=document.getElementById('wrap');
let open=null;
function show(c,ev){const v=byU[c.dataset.u]; if(!v)return;
  tip.innerHTML='<b>@'+esc(v.u)+'</b>'+(v.n?' · '+esc(v.n):'')+'<br>'+v.f.toLocaleString()+' followers · '+KIND[v.k]+
    (v.r.length?' · '+v.r.map(r=>r.replace('_',' ')).join(' + '):'')+'<br><span style="color:var(--muted)">'+esc(v.b)+'</span>'+
    (v.s?'<div class="q">\u201c'+esc(v.s)+'\u201d</div>':'')+
    '<a href="https://x.com/'+encodeURIComponent(v.u)+'" target="_blank" rel="noopener">open @'+esc(v.u)+' \u2192</a>';
  const r=wrap.getBoundingClientRect(); tip.style.display='block';
  const x=ev.clientX-r.left, y=ev.clientY-r.top;
  tip.style.left=Math.max(4,Math.min(x+12, r.width-tip.offsetWidth-4))+'px'; tip.style.top=(y+12)+'px'; open=c;}
let i=0;
document.querySelectorAll('circle.v').forEach(c=>{
  const t=c.querySelector('title'); c.dataset.u=t.textContent.split(' · ')[0].slice(1).toLowerCase(); t.remove();
  c.style.animationDelay=(-(i++%%60)/10)+'s';
  c.addEventListener('click',ev=>{ev.stopPropagation(); show(c,ev);});
  c.addEventListener('mouseenter',ev=>{if(!open)show(c,ev);});
  c.addEventListener('mouseleave',()=>{if(open===c){tip.style.display='none';open=null;}});
});
document.addEventListener('click',()=>{tip.style.display='none';open=null;});
tip.addEventListener('click',e=>e.stopPropagation());
function filt(){const h=document.getElementById('fh').checked,a=document.getElementById('fa').checked;
  document.querySelectorAll('circle.v').forEach(c=>{const v=byU[c.dataset.u]; if(!v)return;
    const on=v.k==='human'?h:(v.k==='agent'?a:true); c.classList.toggle('dim',!on);});}
document.getElementById('fh').onchange=filt; document.getElementById('fa').onchange=filt;
</script>""" % (svg_i, today, data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="mandala-" + date.today().isoformat())
    a = ap.parse_args()
    today = date.today().isoformat()
    voices = load(a.data)
    svg = draw(voices, today)
    open(a.out + ".svg", "w").write(svg)
    open(a.out + ".html", "w").write(html_page(svg, voices, today))
    kinds = {}
    for v in voices.values():
        kinds[kind(v)] = kinds.get(kind(v), 0) + 1
    print("voices: %d  %s" % (len(voices), kinds))
    print("wrote %s.svg and %s.html" % (a.out, a.out))


if __name__ == "__main__":
    main()
