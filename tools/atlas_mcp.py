#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 3e428c1). Edit it there, not here.
"""atlas_mcp.py — the x402 Atlas as an MCP server, so an agent can ask the
public record from inside its own tools.

The site is for people. An agent does not browse it; it calls a tool. This
server answers the questions the pages answer, from the same published files
the pages are built from, and nothing else:

  market_today      how big the market was yesterday, on the chain, and who led it
  search            which sellers do this job — by name, by words, or by intent
  seller            one seller's card: what it sells, what it charges, who paid it
  operator          which hosts are one operator, and how much they took together
  agents_at_work    the buyer wallets whose x402 payments reached three or more sellers
  compare           two to five hosts side by side, each row with its data date

Data comes from the rolling windows the Atlas publishes each morning — the
registry snapshots under radar/ and the on-chain pulls under flows/ — fetched
once per process into a local store and checksummed on the way in, exactly as
the paid `who` seller fetches them. They are read first from the Atlas
repository's `data` branch on raw.githubusercontent.com (https, no redirect,
whatever happens to the site's address; ATLAS_DATA), then from the site
(ATLAS_SITE). Both fetchers refuse redirects on purpose: a manifest fetched
through one vouches for nothing. Point ATLAS_STORE at a folder that already
holds market-<date>.json and whales-<date>.json files and no network is used.
Links to pages in answers are always the site's.

Every free answer that is an answer (not a refusal) names, in one field
`paid_next`, the paid thing that follows from it, as a plain fact: for one
seller, the `who` report card at a cent a call; for the market or a list, the
Atlas Pro files over x402. Every link this server gives out to the Atlas or its
seller carries ?via=mcp, so the seller can count, in aggregate, how many
offers began here. Explorer links to basescan.org are third-party and carry
nothing.

No dependencies. Standard library only, JSON-RPC 2.0 over stdio.

    uvx --from git+https://github.com/ausrine-labs/x402-atlas x402-atlas-mcp
    python3 atlas_mcp.py                       # or straight from a checkout

Claude Desktop, Cursor, or any MCP client:

    {"mcpServers": {"x402-atlas": {"command": "uvx",
        "args": ["--from", "git+https://github.com/ausrine-labs/x402-atlas", "x402-atlas-mcp"]}}}

The numbers are never for sale; this server is free and reads only what the
site publishes. MIT. Made by an AI agent, openly and by design.
"""

import json
import os
import re
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "x402"))       # the lab keeps snapshot_handoff.py there; the Atlas beside us
import market  # noqa: E402
import radar  # noqa: E402
import flows_handoff  # noqa: E402
import snapshot_handoff  # noqa: E402
from operator_pages import group_name, group_slug, slug  # noqa: E402

VERSION = "0.2.0"
PROTOCOL = "2024-11-05"
SITE = (os.environ.get("ATLAS_SITE") or "https://ausrine-labs.github.io/x402-atlas").rstrip("/")
# The same radar/ and flows/ folders, kept on the Atlas repository's data branch: read first.
DATA = (os.environ.get("ATLAS_DATA") or "https://raw.githubusercontent.com/ausrine-labs/x402-atlas/data").rstrip("/")
OFFLINE = bool(os.environ.get("ATLAS_STORE"))
STORE = os.environ.get("ATLAS_STORE") or os.environ.get("ATLAS_CACHE") \
    or os.path.join(tempfile.gettempdir(), "x402-atlas-mcp")
SELLER = (os.environ.get("ATLAS_SELLER") or "https://ausrine-who.onrender.com").rstrip("/")
VIA = "mcp"
PAY = "x402, USDC on Base"
WHO_PRICE = "$0.01"
FILE_PRICES = {"sellers.csv": "$0.25", "buyers.csv": "$0.25", "operators.csv": "$0.25", "day.json": "$1.00"}

NOTE_WALLET = "A wallet is not an agent, and one operator can appear as many wallets."
NOTE_X402 = ("x402 payments are USDC transfers on Base that a facilitator settled on a signed authorization; "
             "USDC that reached the same wallet by other means is shown apart and is not a call.")
NOTE_CONC = ("Concentration is a fact about a seller's payers, never a verdict on the seller: 'one payer' means "
             "every x402 payment in the window came from one wallet.")
NOTE_OPERATOR = ("Hosts paid into the same wallet are grouped as one operator: usually one operator, sometimes a "
                 "platform collecting for several.")

TOOLS = [
    {"name": "market_today",
     "description": "The x402 market on Base as of the newest published day: payments settled, USDC moved, "
                    "buyer wallets, sellers paid, operators, agents at work, and the busiest sellers by real payments.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "search",
     "description": "Find sellers that do a job. Matches names and descriptions word by word, and reads intent "
                    "(e.g. 'weather', 'enrich a person', 'llm inference') into the Atlas categories. Ranked by "
                    "x402 payments on the newest day, then by self-reported paid calls. Also names matching operators.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "words, a host, or the job you need done"},
                                                      "limit": {"type": "integer", "description": "sellers to return, default 10, max 25"}},
                     "required": ["query"]}},
    {"name": "seller",
     "description": "One seller's card: what it sells, its price range and how that sits against rivals, "
                    "self-reported paid calls, rank in the registry, the last days of its history, and what the chain "
                    "says — x402 payments, USDC, payer wallets, concentration, and which other hosts share its wallet.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "a host (api.example.com) or a wallet address"}},
                     "required": ["name"]}},
    {"name": "operator",
     "description": "The hosts one operator runs — the hosts the registry lists under the same wallet — with their "
                    "combined x402 payments and USDC on the newest day. Give any host in the group or the group's name.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "a host, or the operator's domain"}},
                     "required": ["name"]}},
    {"name": "agents_at_work",
     "description": "Buyer wallets whose x402-settled payments reached three or more sellers on the newest day: "
                    "the honest signal of an agent at work. Payments, USDC, categories bought, and the sellers paid.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "wallets to return, default 12, max 50"}}}},
    {"name": "compare",
     "description": "Two to five seller hosts side by side: what each sells, its price range, x402 payments and "
                    "USDC on the newest chain day, payer wallets, concentration, self-reported 30-day paid calls, "
                    "and its operator group. Every row names the dates its figures come from. A host the "
                    "registry does not list is reported as unknown, never guessed at.",
     "inputSchema": {"type": "object", "properties": {"hosts": {"type": "array", "items": {"type": "string"},
                                                                "minItems": 2, "maxItems": 5,
                                                                "description": "two to five hosts, e.g. api.example.com"}},
                     "required": ["hosts"]}},
]


# ---------------------------------------------------------------- data

_DATA = {}


def _refresh():
    """Bring the store in line with the published window, once: each folder from
    the data branch first, the site second. Never raises: an offline store still
    answers from what it has, and says how old it is. Returns (problems, sources):
    what failed everywhere, and where each folder came from."""
    problems, sources = [], {}
    for part, fetch in (("radar", snapshot_handoff.fetch), ("flows", flows_handoff.fetch)):
        tried = []
        for base in (DATA, SITE):
            try:
                report = fetch("%s/%s/" % (base, part), STORE) or {}
                # a readable manifest whose every file was rejected is no source at all: try the next
                usable = [x for k in ("kept", "had", "fetched") for x in (report.get(k) or [])]
                if not usable:
                    tried.append("%s/%s/: no usable file (%d rejected)" % (base, part, len(report.get("rejected") or [])))
                    continue
                sources[part] = "%s/%s/" % (base, part)
                break
            except Exception as e:  # noqa: BLE001 - surface in the answer, never hide
                tried.append("%s/%s/: %s" % (base, part, str(e) or type(e).__name__))
        else:
            problems.append("%s: %s" % (part, "; ".join(tried)))
    return problems, sources


def chain_day(d, name):
    """The day a rollup covers: the last of its dates. Its file is named for the day it was
    built, which from the daily build on is the day after; the name answers only when a
    rollup carries no dates."""
    dates = d.get("dates")
    if isinstance(dates, list) and dates and isinstance(dates[-1], str) and re.match(r"^\d{4}-\d{2}-\d{2}$", dates[-1]):
        return dates[-1]
    return name[len("whales-"):-len(".json")]


def newest_chain(store):
    names = sorted(f for f in os.listdir(store) if re.match(r"^whales-\d{4}-\d{2}-\d{2}\.json$", f))
    for name in reversed(names):
        try:
            with open(os.path.join(store, name)) as f:
                d = json.load(f)
            if d.get("classified") and isinstance(d.get("sellers"), list):
                d["_file"] = name
                d["_day"] = chain_day(d, name)
                return d
        except (OSError, ValueError):
            continue
    return None


def data():
    """Snapshots (oldest to newest), the newest chain rollup, and any fetch problems."""
    if _DATA:
        return _DATA
    problems, sources = ([], {"store": STORE}) if OFFLINE else _refresh()
    os.makedirs(STORE, exist_ok=True)
    snaps = sorted(f for f in os.listdir(STORE) if re.match(r"^market-\d{4}-\d{2}-\d{2}\.json$", f))
    loaded = []
    for name in snaps[-8:]:
        try:
            with open(os.path.join(STORE, name)) as f:
                loaded.append(json.load(f))
        except (OSError, ValueError):
            continue
    chain = newest_chain(STORE)
    if chain:
        chain["_by_host"] = {s["host"]: s for s in chain["sellers"]}
        groups = chain.get("groups") or []
        seen = set()
        for g in groups:
            g["name"] = group_name(g["hosts"], chain)
            base = group_slug(g["hosts"])             # the page's slug, as operator_pages.build makes it
            g["slug"] = base if base not in seen else "%s-%s" % (base, g["id"])
            seen.add(g["slug"])
            xs = [chain["_by_host"].get(h) for h in g["hosts"]]
            g["payments_x402"] = sum((s or {}).get("on_chain_payments_x402", 0) for s in xs)
            g["usdc_x402"] = round(sum((s or {}).get("on_chain_usdc_x402", 0.0) for s in xs), 2)
            g["hosts_paid"] = sum(1 for s in xs if s and s.get("on_chain_payments_x402"))
        chain["_groups"] = groups
    _DATA.update({"loaded": loaded, "chain": chain, "problems": problems, "sources": sources})
    return _DATA


def via(url):
    """Every link this server gives out to the Atlas or its seller says where it came from."""
    return url + ("&" if "?" in url else "?") + "via=" + VIA


def seller_url(host):
    return via("%s/s/%s/" % (SITE, slug(host)))


def operator_url(g):
    return via("%s/o/%s/" % (SITE, g["slug"]))


def who_url(host):
    return via("%s/who/%s" % (SELLER, urllib.parse.quote(host, safe="")))


def paid_one(host):
    """The paid next step when an answer is about one seller."""
    return {"what": "this seller's report card from the Atlas's paid seller, one HTTPS call, stamped with "
                    "the snapshot's age; refusals are free",
            "price": WHO_PRICE, "pay": PAY, "url": who_url(host)}


def paid_files(first):
    """The paid next step when an answer is market-wide or a list: the whole window as files."""
    order = [first] + [n for n in FILE_PRICES if n != first]
    return {"what": "the whole newest window as files, every row rather than the top few; %s fits this "
                    "answer best" % first,
            "pay": PAY,
            "files": {n: {"price": FILE_PRICES[n], "url": via("%s/x402/export/%s" % (SELLER, n))} for n in order}}


def stale_note(loaded, chain):
    parts = []
    if loaded:
        parts.append("registry snapshot as of %s" % loaded[-1]["date"])
    if chain:
        parts.append("chain day %s (%s hours)" % (chain.get("_day"), chain.get("hours")))
    return "; ".join(parts) or "no data in the store"


# ---------------------------------------------------------------- tools

def t_market_today(_args):
    d = data()
    chain, loaded = d["chain"], d["loaded"]
    if not chain:
        return {"available": False, "say": "no classified on-chain day in the store yet", "problems": d["problems"]}
    tot = chain.get("totals") or {}
    top = sorted(chain["sellers"], key=lambda s: -s.get("on_chain_payments_x402", 0))[:10]
    return {
        "day": chain.get("_day"), "dates": chain.get("dates") or [], "chain": "Base", "hours": chain.get("hours"),
        "x402_payments": tot.get("payments_x402"), "x402_usdc": tot.get("usdc_x402"),
        "buyer_wallets_x402": tot.get("buyer_wallets_x402"), "sellers_paid": tot.get("sellers_paid"),
        "sellers_in_registry": len(loaded[-1]["sellers"]) if loaded else tot.get("sellers_known"),
        "operators_known": tot.get("operators_known"), "agents_3plus": tot.get("agents_3plus"),
        "sellers_one_payer": tot.get("sellers_one_payer"), "sellers_concentrated": tot.get("sellers_concentrated"),
        "usdc_by_other_means": round((tot.get("usdc") or 0) - (tot.get("usdc_x402") or 0), 2),
        "busiest_by_x402": [{"host": s["host"], "x402_payments": s.get("on_chain_payments_x402", 0),
                             "x402_usdc": s.get("on_chain_usdc_x402", 0.0), "payer_wallets": s.get("x402_payer_wallets", 0),
                             "concentration": s.get("concentration"), "category": s.get("category"),
                             "page": seller_url(s["host"])} for s in top],
        "site": via(SITE + "/"), "as_of": stale_note(loaded, chain), "data_from": d["sources"],
        "notes": [NOTE_X402, NOTE_WALLET], "paid_next": paid_files("day.json"), "problems": d["problems"],
    }


def _words(text):
    return set(re.findall(r"[a-z0-9]{2,}", text.lower()))


def t_search(args):
    q = (args.get("query") or "").strip()
    if not q:
        return {"error": "say what you are looking for"}
    limit = max(1, min(int(args.get("limit") or 10), 25))
    d = data()
    loaded, chain = d["loaded"], d["chain"]
    if not loaded:
        return {"error": "no registry snapshot in the store", "problems": d["problems"]}
    A = loaded[-1]["sellers"]
    by_host = (chain or {}).get("_by_host") or {}
    ql = q.lower()
    want = _words(q)
    cats = [name for name, _, rx in market.CATS if re.search(rx, ql) or name in ql]

    hits = {}
    for host, s in A.items():
        cat = market.cat((s.get("sells") or "") + " " + host)[0]
        text = (host + " " + (s.get("sells") or "") + " " + cat).lower()
        by_word = all(w in text for w in want)
        by_intent = cat in cats
        if by_word or by_intent:
            x = by_host.get(host) or {}
            hits[host] = {"host": host, "sells": (s.get("sells") or "")[:140], "category": cat,
                          "price": radar.price_label(s), "chains": s.get("chains"),
                          "calls_30d_self_reported": s.get("calls", 0),
                          "x402_payments_newest_day": x.get("on_chain_payments_x402", 0),
                          "x402_usdc_newest_day": x.get("on_chain_usdc_x402", 0.0),
                          "concentration": x.get("concentration"),
                          "matched_by": "words" if by_word else "intent", "page": seller_url(host)}
    ranked = sorted(hits.values(), key=lambda r: (r["matched_by"] != "words",
                                                  -r["x402_payments_newest_day"], -r["calls_30d_self_reported"]))
    ops = []
    for g in (chain or {}).get("_groups") or []:
        if all(w in (g["name"] + " " + " ".join(g["hosts"])).lower() for w in want):
            ops.append({"operator": g["name"], "hosts": len(g["hosts"]), "x402_payments_newest_day": g["payments_x402"],
                        "page": operator_url(g)})
    return {"query": q, "intent": cats, "matched": len(ranked), "sellers": ranked[:limit],
            "operators": ops[:5], "as_of": stale_note(loaded, chain),
            "notes": ["ranked by x402 payments on the newest chain day, then by the registry's own 30-day counts",
                      NOTE_WALLET],
            **({"paid_next": paid_one(ranked[0]["host"]) if len(ranked) == 1 else paid_files("sellers.csv")}
               if ranked else {}),
            "problems": d["problems"]}


def on_chain(host, chain):
    if not chain:
        return {"available": False, "say": "no classified on-chain day in the store"}
    s = chain["_by_host"].get(host)
    op = (chain.get("operators") or {}).get(host)
    out = {"available": True, "day": chain.get("_day"), "hours": chain.get("hours"), "chain": "Base",
           "x402_payments": (s or {}).get("on_chain_payments_x402", 0),
           "x402_usdc": (s or {}).get("on_chain_usdc_x402", 0.0),
           "payer_wallets": (s or {}).get("x402_payer_wallets", 0),
           "concentration": (s or {}).get("concentration"),
           "top_payers": (s or {}).get("x402_top_payers") or [],
           "usdc_by_other_means": round((s or {}).get("on_chain_usdc", 0.0) - (s or {}).get("on_chain_usdc_x402", 0.0), 2),
           "operator_hosts": op["hosts"] if op else 1,
           "operator_other_hosts": (op["others"] if op else [])[:12]}
    if not s:
        out["say"] = "no USDC reached this seller's wallets on this day"
    return out


def t_seller(args):
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "give a host or a wallet"}
    d = data()
    loaded, chain = d["loaded"], d["chain"]
    if not loaded:
        return {"error": "no registry snapshot in the store", "problems": d["problems"]}
    try:
        card = radar.who_data(name, loaded)
    except radar.Ambiguous as e:
        return {"ambiguous": True, "say": "%d sellers match %r — say which" % (len(e.candidates), name),
                "candidates": e.candidates}
    except LookupError as e:
        return {"found": False, "say": str(e), "as_of": stale_note(loaded, chain)}
    card["on_chain"] = on_chain(card["host"], chain)
    card["page"] = seller_url(card["host"])
    card["notes"] = [NOTE_X402, NOTE_CONC, NOTE_OPERATOR]
    card["paid_next"] = paid_one(card["host"])
    card["problems"] = d["problems"]
    return card


def t_operator(args):
    name = (args.get("name") or "").strip().lower().replace("www.", "")
    if not name:
        return {"error": "give a host or an operator's domain"}
    d = data()
    loaded, chain = d["loaded"], d["chain"]
    if not chain:
        return {"available": False, "say": "no classified on-chain day in the store", "problems": d["problems"]}
    g = next((g for g in chain["_groups"] if name in (g["name"], g["slug"]) or name in [h.lower() for h in g["hosts"]]), None)
    if not g:
        near = [g for g in chain["_groups"] if name in g["name"] or any(name in h.lower() for h in g["hosts"])]
        if len(near) == 1:
            g = near[0]
        elif near:
            return {"ambiguous": True, "say": "%d operators match %r — say which" % (len(near), name),
                    "candidates": [{"operator": x["name"], "hosts": x["hosts"][:6]} for x in near[:12]]}
    if not g:
        in_registry = loaded and any(h.lower() == name for h in loaded[-1]["sellers"])
        return {"found": False,
                "say": ("%s is in the registry under a wallet no other host shares: a group of one" % name) if in_registry
                else "%s is not a host or operator the record knows" % name,
                "as_of": stale_note(loaded, chain)}
    by = chain["_by_host"]
    hosts = [{"host": h, "x402_payments": by.get(h, {}).get("on_chain_payments_x402", 0),
              "x402_usdc": by.get(h, {}).get("on_chain_usdc_x402", 0.0), "page": seller_url(h)} for h in g["hosts"]]
    hosts.sort(key=lambda h: -h["x402_payments"])
    return {"operator": g["name"], "hosts": len(g["hosts"]), "wallets": g.get("wallets"),
            "hosts_paid_newest_day": g["hosts_paid"], "x402_payments_newest_day": g["payments_x402"],
            "x402_usdc_newest_day": g["usdc_x402"], "day": chain.get("_day"),
            "hosts_list": hosts, "page": operator_url(g),
            "claim": "whether the operator has claimed this group is shown on the page, not here",
            "notes": [NOTE_OPERATOR, NOTE_X402], "paid_next": paid_files("operators.csv"), "problems": d["problems"]}


def t_agents(args):
    limit = max(1, min(int(args.get("limit") or 12), 50))
    d = data()
    chain = d["chain"]
    if not chain:
        return {"available": False, "say": "no classified on-chain day in the store", "problems": d["problems"]}
    out = []
    for b in (chain.get("agents") or [])[:limit]:
        out.append({"wallet": b["wallet"], "explorer": b.get("explorer"),
                    "sellers_paid_x402": b.get("sellers_paid_x402"), "x402_payments": b.get("payments_x402"),
                    "x402_usdc": b.get("usdc_x402"), "categories": b.get("categories"),
                    "sellers": [{"host": s["host"], "x402_payments": s.get("payments_x402", 0),
                                 "x402_usdc": s.get("usdc_x402", 0.0)} for s in (b.get("sellers") or [])[:8]]})
    return {"day": chain.get("_day"), "chain": "Base", "agents_3plus": (chain.get("totals") or {}).get("agents_3plus"),
            "shown": len(out), "agents": out,
            "notes": ["an agent at work is a wallet whose x402-settled payments reached three or more sellers",
                      NOTE_WALLET],
            **({"paid_next": paid_files("buyers.csv")} if out else {}), "problems": d["problems"]}


def _host(text):
    """A host as the registry writes it: lower case, no scheme, path or www. Nothing fuzzier."""
    h = (text or "").strip().lower()
    h = re.sub(r"^[a-z][a-z0-9+.-]*://", "", h).split("/", 1)[0].split("?", 1)[0]
    return h[4:] if h.startswith("www.") else h


def operator_of(host, chain):
    if not chain:
        return None
    g = next((g for g in chain["_groups"] if host in g["hosts"]), None)
    if not g:
        return {"operator": None, "hosts": 1, "say": "no other host in the registry is paid into its wallet"}
    return {"operator": g["name"], "hosts": len(g["hosts"]), "x402_payments_newest_day": g["payments_x402"],
            "page": operator_url(g)}


def t_compare(args):
    asked = args.get("hosts")
    if isinstance(asked, str):
        asked = re.split(r"[,\s]+", asked)
    if not isinstance(asked, list):
        return {"error": "give hosts: a list of two to five"}
    hosts = []
    for x in asked:
        h = _host(x if isinstance(x, str) else "")
        if h and h not in hosts:
            hosts.append(h)
    if not 2 <= len(hosts) <= 5:
        return {"error": "give two to five different hosts; got %d" % len(hosts)}
    d = data()
    loaded, chain = d["loaded"], d["chain"]
    if not loaded:
        return {"error": "no registry snapshot in the store", "problems": d["problems"]}
    snap = loaded[-1]
    A = {k.lower(): (k, v) for k, v in snap["sellers"].items()}
    by_host = (chain or {}).get("_by_host") or {}
    rows, unknown = [], []
    for h in hosts:
        if h not in A:
            unknown.append({"host": h, "say": "not in the registry snapshot of %s; nothing is guessed for it"
                                              % snap["date"]})
            continue
        host, s = A[h]
        x = by_host.get(host)
        row = {"host": host, "sells": (s.get("sells") or "")[:140],
               "category": market.cat((s.get("sells") or "") + " " + host)[0],
               "price": radar.price_label(s), "price_min": s.get("price_min"), "price_max": s.get("price_max"),
               "calls_30d_self_reported": s.get("calls", 0),
               "registry_date": snap["date"], "chain_day": chain.get("_day") if chain else None,
               "page": seller_url(host)}
        if chain:
            row.update({"x402_payments": (x or {}).get("on_chain_payments_x402", 0),
                        "x402_usdc": (x or {}).get("on_chain_usdc_x402", 0.0),
                        "payer_wallets": (x or {}).get("x402_payer_wallets", 0),
                        "concentration": (x or {}).get("concentration")})
            if not x:
                row["say"] = "no USDC reached this seller's wallets on the chain day"
        else:
            row["on_chain"] = "no classified on-chain day in the store"
        row["operator"] = operator_of(host, chain)
        rows.append(row)
    out = {"compared": len(rows), "sellers": rows, "unknown": unknown, "as_of": stale_note(loaded, chain),
           "notes": ["x402 payments and USDC are read off Base for the chain day; calls_30d_self_reported is the "
                     "registry's own count. The two are never blended", NOTE_X402, NOTE_CONC],
           "problems": d["problems"]}
    if rows:
        out["paid_next"] = paid_files("sellers.csv")
    return out


HANDLERS = {"market_today": t_market_today, "search": t_search, "seller": t_seller,
            "operator": t_operator, "agents_at_work": t_agents, "compare": t_compare}


def call_tool(name, args):
    fn = HANDLERS.get(name)
    if not fn:
        return "unknown tool: %s" % name
    return json.dumps(fn(args or {}), indent=1, ensure_ascii=False)


# ---------------------------------------------------------------- wire

def respond(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            respond(rid, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "x402-atlas", "version": VERSION}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            respond(rid, {"tools": TOOLS})
        elif method == "tools/call":
            params = req.get("params") or {}
            try:
                text = call_tool(params.get("name"), params.get("arguments") or {})
                respond(rid, {"content": [{"type": "text", "text": text}]})
            except Exception as e:  # noqa: BLE001 - surface, never hide
                respond(rid, {"content": [{"type": "text", "text": "atlas failed: %s" % e}], "isError": True})
        elif rid is not None:
            respond(rid, error={"code": -32601, "message": "unknown method: %s" % method})


if __name__ == "__main__":
    main()
