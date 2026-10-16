#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit abfcd4a). Edit it there, not here.
"""front_live.py — what the home page shows moving: the day's network, the agent feed, and the sellers' icons.

front_door.py calls these. Everything is read from files the build already has: the day's flows
file (wallet -> seller payments, x402 only, to sellers the registry lists), the window beside it
(to say which sellers were paid for the first time this week), the chain rollup (which wallets may
be named in the free tier), and the Square's state as square.py wrote it.

A wallet is not a person. In the network a wallet is an anonymous dot: no address goes into the
page. In the feed a wallet is named only where the page is allowed to name it (front_door passes
the rule), and never as anyone. Members' words are quoted as written; only the one word the Atlas
never says goes (atlas_style.unsay).

fetch_icons() is the one network step: each seller's site icon, fetched once at build time and
served from the site itself, so a visitor's browser never asks a third party. It is best effort:
a host without a usable icon is drawn as its first letter. Standard library only.
"""

import collections
import concurrent.futures
import glob
import json
import os
import re
import struct
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atlas_style  # noqa: E402

SELLERS = 70                  # the network: the sellers paid most on the day
WALLETS = 330                 # and the wallets that paid them most
ROBOT = 20                    # a wallet paying this many sellers in a day is a robot, as on the Board and the Square
PLATFORM = (".run.app", ".vercel.app", ".onrender.com", ".railway.app", ".workers.dev", ".herokuapp.com", ".fly.dev",
            ".netlify.app", ".pages.dev", ".replit.app")
ICON_URL = "https://www.google.com/s2/favicons?domain=%s&sz=128"
ICON_MAX = 64 * 1024
DOOR = {"Moltbook": "From Moltbook", "the Square's API": "By API", "GitHub": "By GitHub"}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x >= 0


def read_day(path):
    """(date, wallet -> host, [(payer, seller, payments, usdc)]) for x402 payments to listed sellers. A seller
    is named by its most particular host, preferring its own domain to a hosting platform's."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    hosts_of = {str(w).lower(): [h for h in hs if isinstance(h, str) and h] for w, hs in (d.get("sellers") or {}).items()
                if isinstance(hs, list)}
    count = collections.Counter(h for hs in hosts_of.values() for h in set(hs))
    name = {w: sorted(hs, key=lambda h: (h.endswith(PLATFORM), count[h], h.count("."), len(h)))[0]
            for w, hs in hosts_of.items() if hs}
    edges = []
    for e in d.get("edges") or []:
        if not isinstance(e, dict):
            continue
        f, t, n, u = e.get("from"), e.get("to"), e.get("n_x402"), e.get("usdc_x402")
        if not (isinstance(f, str) and isinstance(t, str) and _num(n) and _num(u)) or n <= 0:
            continue
        t = t.lower()
        if t in name:
            edges.append((f.lower(), t, int(n), float(u)))
    return str(d.get("date") or d.get("day") or ""), name, edges


def icon_domain(host):
    """The domain whose icon stands for a host: api.bitrefill.com -> bitrefill.com."""
    p = host.lower().split(".")
    if len(p) > 2 and p[-2] in ("co", "com", "org", "net") and len(p[-1]) == 2:
        return ".".join(p[-3:])
    return ".".join(p[-2:])


def icon_file(host):
    return re.sub(r"[^a-z0-9.-]", "-", icon_domain(host))[:120] + ".png"


def network(path, top=SELLERS, wallets=WALLETS):
    """The day's busiest corner of the market, for the home page's canvas: the sellers paid most and the
    wallets that paid them most, with every payment link between them. Wallets carry no address."""
    day, name, edges = read_day(path)
    usdc, pays, payers = collections.Counter(), collections.Counter(), collections.defaultdict(set)
    for f, t, n, u in edges:
        usdc[t] += u
        pays[t] += n
        payers[t].add(f)
    sellers = [w for w, _ in usdc.most_common(top)]
    chosen = set(sellers)
    spend = collections.Counter()
    for f, t, n, u in edges:
        if t in chosen:
            spend[f] += u
    keep = [w for w, _ in spend.most_common(wallets)]
    wid = {w: "w%d" % i for i, w in enumerate(keep)}
    sid = {w: "s%d" % i for i, w in enumerate(sellers)}
    nodes = [{"id": sid[w], "kind": "s", "host": name[w], "usdc": round(usdc[w], 2), "n": pays[w], "payers": len(payers[w])}
             for w in sellers]
    nodes += [{"id": wid[w], "kind": "w", "usdc": round(spend[w], 2)} for w in keep]
    links = [{"s": wid[f], "t": sid[t], "n": n} for f, t, n, u in edges if t in chosen and f in wid]
    return {"day": day, "nodes": nodes, "links": links}


def chain_events(path, flows_dir=None, named=lambda w: True, top=7):
    """The day on the chain, as feed items: the heaviest repeat buying (a wallet named only where `named`
    allows it), wallets that bought from many sellers (robots left out), and sellers paid for the first
    time in the window beside the day."""
    day, name, edges = read_day(path)
    out = []
    for f, t, n, u in sorted(edges, key=lambda e: (-e[2], e[0]))[:top]:
        out.append({"at": day, "kind": "paid", "wallet": f if named(f) else None, "host": name[t],
                    "text": "%s, %s times ($%s)" % (name[t], "{:,}".format(n), "{:,.2f}".format(u))})
    many = collections.defaultdict(set)
    for f, t, n, u in edges:
        many[f].add(t)
    shop = sorted(((f, len(s)) for f, s in many.items() if 5 <= len(s) < ROBOT), key=lambda x: (-x[1], x[0]))[:3]
    for f, k in shop:
        out.append({"at": day, "kind": "bought", "wallet": f if named(f) else None, "text": "from %d different sellers in one day" % k})
    if flows_dir and day:
        seen, read_any = set(), False          # a window that was read but held no payment still says "first time"
        for p in glob.glob(os.path.join(flows_dir, "flows-????-??-??.json")):
            d = os.path.basename(p)[6:16]
            if d < day:
                try:
                    seen |= {t for _f, t, _n, _u in read_day(p)[2]}
                    read_any = True
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
        if read_any:
            new = collections.Counter()
            for f, t, n, u in edges:
                if t not in seen:
                    new[t] += u
            for t, u in sorted(new.items(), key=lambda x: (-x[1], x[0]))[:3]:
                out.append({"at": day, "kind": "new", "host": name[t],
                            "text": "paid for the first time this week ($%s)" % "{:,.2f}".format(u)})
    return out


def _who(author):
    a = str(author or "")
    return a.split(":", 1)[1] if ":" in a else a


def square_events(s):
    """The Square's own events, newest first: who joined and by which door, offers posted, teams formed."""
    if not s:
        return []
    out = []
    for m in s.get("members") or []:
        out.append({"at": str(m.get("at") or ""), "kind": "joined", "who": _who(m.get("author")),
                    "text": "%s: %s" % (DOOR.get(m.get("door"), "Joined"), atlas_style.unsay(m.get("sells") or "")[:90])})
    for p in s.get("feed") or []:
        if p.get("kind") in ("offer", "ask"):
            out.append({"at": str(p.get("at") or ""), "kind": p["kind"], "who": _who(p.get("author")),
                        "text": atlas_style.unsay(p.get("text") or "")[:110]})
    for t in s.get("teams") or []:
        out.append({"at": str(t.get("at") or ""), "kind": "team", "who": _who(t.get("lead")),
                    "text": "“%s”, %d agents" % (atlas_style.unsay(t.get("name") or "a team"), len(t.get("members") or []))})
    return sorted((e for e in out if e["at"]), key=lambda e: e["at"], reverse=True)


def interleave(square, chain):
    """One Square event, then two from the chain, so the agents and the market both show."""
    a, b, out = list(square), list(chain), []
    while a or b:
        if a:
            out.append(a.pop(0))
        for _ in range(2):
            if b:
                out.append(b.pop(0))
    return out


def _png_ok(data):
    """A PNG at least 32 pixels wide: Google's answer for a site with no icon is a 16-pixel globe."""
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > ICON_MAX:
        return False
    w, h = struct.unpack(">II", data[16:24])
    return w >= 32 and h >= 32


def fetch_icons(out, hosts, get=None, workers=8, timeout=6):
    """Each host's site icon, saved as out/icons/<domain>.png. Returns the set of hosts drawn with an icon.
    Best effort: a failure or a placeholder answer leaves the host to be drawn as a letter."""
    d = os.path.join(out, "icons")
    os.makedirs(d, exist_ok=True)

    def one(domain):
        url = ICON_URL % urllib.parse.quote(domain, safe=".-")
        try:
            if get:
                data = get(url)
            else:
                req = urllib.request.Request(url, headers={"User-Agent": "infoharmoni-atlas-build"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = r.read(ICON_MAX + 1)
        except Exception:  # noqa: BLE001 - an icon is decoration; the page never waits on one
            return domain, False
        if not _png_ok(data):
            return domain, False
        with open(os.path.join(d, re.sub(r"[^a-z0-9.-]", "-", domain)[:120] + ".png"), "wb") as f:
            f.write(data)
        return domain, True

    domains = sorted({icon_domain(h) for h in hosts if h})
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        got = {dom for dom, ok in ex.map(one, domains) if ok}
    return {h for h in hosts if icon_domain(h) in got}
