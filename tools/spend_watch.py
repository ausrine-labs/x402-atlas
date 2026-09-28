#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""spend_watch.py — Watch your agents: what a set of wallets spent over x402 on Base,
with whom, and how each seller they paid stands.

A spend tool that sits in the payment path sees only the payments routed through it.
The chain sees all of them. This reads the Atlas's daily Base pulls (chain_flows.py,
kept by flows_handoff.py as flows-<date>.json) for 1 to 25 wallets and, per wallet and
in total, says:

    per_day        x402 payments and USDC on each day of the window
    change         the newest day against the day before it
    by_category    where the money went, in the Atlas's categories
    sellers        every seller paid, busiest first; top_sellers is the first ten
    new_sellers    sellers first paid on the newest day (none of these wallets paid
                   them earlier in the window)

and, for each seller paid, the facts beside the money:

    listed         the registry's price range (the newest market snapshot)
    paid_per_call  USDC over x402 payments to it, from these wallets
    paid_above_list    true when paid_per_call is over 1.2x the listed max
    going_rate     the median listed price of every seller in its category
    above_going_rate   true when paid_per_call is over 1.2x that going rate
    others         what every other wallet paid it in the same window
    status         up, wrong or down at the last check, when probe.py's
                   status-latest.json is loaded (read, never imported)

and `findings`: short plain sentences made by fixed rules. Facts, not advice, and never
a word about who holds a wallet.

    spend_watch.py report --store flows --snapshot radar-store/market-<date>.json \\
                          --wallets 0x..,0x.. [--days 7] [--status status/status-latest.json]
    spend_watch.py busiest --store flows [--n 5]       the busiest x402 buyers, to try it on
    spend_watch.py page --out _site/watch --seller https://who.example.com

watch_block(report) is the HTML fragment a page includes. page() writes /watch/: a form
that keeps the wallets in the viewer's own browser and calls GET /pro/watch with the key
the viewer types. Standard library only. MIT.
"""

import argparse
import collections
import html
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market  # noqa: E402  (the categories and the name)
import radar  # noqa: E402  (median: the same going rate the report card uses)
import whales  # noqa: E402  (host_of, short, EXPLORER: the same crediting the rollup uses)

EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
FLOWS = re.compile(r"^flows-(\d{4}-\d{2}-\d{2})\.json$")
MAX_WALLETS = 25
DEFAULT_DAYS = 7
MAX_DAYS = 8                 # flows_handoff.KEEP: the public window holds no more
ABOVE_LIST = 1.2             # paid per call over 1.2x the listed max: "paid above list"
ABOVE_GOING = 1.2            # paid per call over 1.2x the category's median listed price
TOP = 10
STATES = ("up", "wrong", "down", "skipped")

CAVEATS = [
    "Figures are USDC transfers on Base from these wallets to seller wallets the public x402 registry "
    "names. A seller whose wallet is not in the registry is not seen here.",
    "x402 payments are transfers a facilitator settled on a signed authorization. USDC that reached the "
    "same sellers by ordinary transfer is shown apart as usdc_other_means and is not a call.",
    "A wallet is not an agent, and nothing here says who holds a wallet. One agent can use many wallets.",
    "paid_per_call is USDC over x402 payments to one seller. A seller with endpoints at several prices "
    "can average above its lowest price; the listed range is shown beside it.",
    "going_rate is the median listed price of every seller in the same category of the newest registry "
    "snapshot. It describes the category, not what one job should cost.",
    "status is one unpaid request to the seller's busiest listed endpoint at the last check: up means it "
    "answered 402 with payment terms that parse, not that a paid call would succeed.",
    "others is every wallet not on this list that paid the same seller in the same window.",
    "Payments to a wallet shared by several hosts are credited to the busiest host the registry knows.",
    "These are facts from public records, not advice.",
]


# ── inputs ────────────────────────────────────────────────────────────────

def parse_wallets(value):
    """(wallets, None) or (None, why). Comma or space separated, 1 to 25 Base addresses,
    lowercased, repeats dropped, order kept."""
    items = value if isinstance(value, (list, tuple)) else re.split(r"[\s,]+", value or "")
    items = [str(w).strip() for w in items if str(w).strip()]
    if not items:
        return None, "give at least one wallet address (0x followed by 40 hex characters)"
    bad = [w for w in items if not EVM.match(w)]
    if bad:
        return None, "not a Base wallet address: %s" % ", ".join(b[:48] for b in bad[:5])
    out = []
    for w in items:
        if w.lower() not in out:
            out.append(w.lower())
    if len(out) > MAX_WALLETS:
        return None, "at most %d wallets at once; %d were given" % (MAX_WALLETS, len(out))
    return out, None


def parse_days(value):
    """(days, None) or (None, why)."""
    if value in (None, ""):
        return DEFAULT_DAYS, None
    try:
        n = int(str(value))
    except ValueError:
        return None, "days must be a whole number from 1 to %d" % MAX_DAYS
    if not 1 <= n <= MAX_DAYS:
        return None, "days must be a whole number from 1 to %d" % MAX_DAYS
    return n, None


# ── the data ──────────────────────────────────────────────────────────────

_cache = {}


def _day_problem(d, day):
    if not isinstance(d, dict):
        return "is not an object"
    if d.get("date") != day:
        return "says it is %r, its name says %s" % (d.get("date"), day)
    if not isinstance(d.get("edges"), list) or not isinstance(d.get("sellers"), dict):
        return "has no edges or sellers"
    return None


def load_days(store):
    """(days oldest first, problems). Base pulls only; a file that does not parse, or whose
    date is not its name, is left out and named. Parsed files are kept per (name, size, mtime)."""
    if not store or not os.path.isdir(store):
        return [], []
    days, problems = [], []
    for name in sorted(os.listdir(store)):
        m = FLOWS.match(name)
        if not m:
            continue
        path = os.path.join(store, name)
        try:
            st = os.stat(path)
            key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
            d = _cache.get(key)
            if d is None:
                with open(path) as f:
                    d = json.load(f)
                why = _day_problem(d, m.group(1))
                if why:
                    problems.append("%s %s" % (name, why))
                    continue
                if len(_cache) > 64:
                    _cache.clear()
                _cache[key] = d
        except (OSError, ValueError) as e:
            problems.append("%s could not be read (%s)" % (name, type(e).__name__))
            continue
        if (d.get("chain") or "base").lower() != "base":
            continue
        days.append(d)
    return days, problems


def load_status(path):
    """probe.py's status-latest.json, or None when it is absent or not in that shape. Read as
    data only: probe.py is never imported."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("hosts"), dict):
        return None
    return d


def load_snapshot(path):
    with open(path) as f:
        d = json.load(f)
    return d["sellers"], d.get("date")


def going_rates(A):
    """{category: median listed price} over every seller in the snapshot with a price."""
    by = collections.defaultdict(list)
    for host, s in (A or {}).items():
        p = s.get("price_med")
        if isinstance(p, (int, float)) and p > 0:
            by[category(host, A)].append(p)
    return {c: radar.median(v) for c, v in by.items()}


def category(host, A):
    sells = ((A or {}).get(host) or {}).get("sells") or ""
    return market.cat(sells + " " + host)[0]


# ── the report ────────────────────────────────────────────────────────────

def _pct(now, before):
    if not before:
        return None
    return round(100.0 * (now - before) / before, 1)


def _money(x):
    return round(x + 0.0, 4)


class _Book:
    """One wallet's (or the total's) running sums."""

    def __init__(self, dates):
        self.day = {d: {"payments": 0, "usdc": 0.0} for d in dates}
        self.sellers = {}
        self.other = 0.0

    def add(self, day, host, n, u, other, cat):
        self.other += other
        if not n:
            return
        self.day[day]["payments"] += n
        self.day[day]["usdc"] += u
        s = self.sellers.setdefault(host, {"host": host, "category": cat, "payments": 0, "usdc": 0.0, "days": set()})
        s["payments"] += n
        s["usdc"] += u
        s["days"].add(day)


def report(wallets, window=DEFAULT_DAYS, days=None, sellers=None, status=None, registry_date=None,
           store=None, snapshot=None, status_file=None):
    """The watch report for 1 to 25 Base wallets over the last `window` pulled days.

    `days`: flows files as parsed dicts (else read from `store`); `sellers`: the newest registry
    snapshot's sellers (else read from `snapshot`); `status`: probe.py's status-latest.json as a
    dict (else read from `status_file`, or from `store`/status-latest.json when it is there).
    Pure when everything is passed in. Raises ValueError on bad wallets or window."""
    ws, why = parse_wallets(wallets)
    if why:
        raise ValueError(why)
    window, why = parse_days(window)
    if why:
        raise ValueError(why)
    if days is None:
        days, _ = load_days(store)
    if sellers is None and snapshot:
        sellers, registry_date = load_snapshot(snapshot)
    A = sellers or {}
    if status is None:
        status = load_status(status_file or (os.path.join(store, "status-latest.json") if store else None))

    chosen = sorted(days, key=lambda d: d["date"])[-window:]
    dates = [d["date"] for d in chosen]
    watched = set(ws)
    books = {w: _Book(dates) for w in ws}
    total = _Book(dates)
    others = collections.defaultdict(lambda: {"payments": 0, "usdc": 0.0, "wallets": set()})
    classified_days = []
    hours = 0.0
    for d in chosen:
        classified = any("n_x402" in e for e in d["edges"])
        if classified:
            classified_days.append(d["date"])
        hours += d.get("hours") or 0
        for e in d["edges"]:
            f = (e.get("from") or "").lower()
            host = whales.host_of(e.get("to"), d["sellers"], A) or whales.short(e.get("to") or "")
            n = e.get("n_x402", 0) if classified else e.get("n", 0)
            u = e.get("usdc_x402", 0.0) if classified else e.get("usdc", 0.0)
            if f in watched:
                other = max((e.get("usdc") or 0.0) - u, 0.0) if classified else 0.0
                cat = category(host, A)
                books[f].add(d["date"], host, n, u, other, cat)
                total.add(d["date"], host, n, u, other, cat)
            elif n:
                o = others[host]
                o["payments"] += n
                o["usdc"] += u
                o["wallets"].add(f)

    going = going_rates(A)
    hosts = status.get("hosts") if status else None
    newest = dates[-1] if dates else None
    before = _day_before(dates)

    def seller_row(s):
        me = A.get(s["host"]) or {}
        per = s["usdc"] / s["payments"] if s["payments"] else None
        hi, lo = me.get("price_max"), me.get("price_min")
        g = going.get(s["category"]) if me else None      # unlisted: its category is only a guess from the name
        o = others.get(s["host"])
        row = {"host": s["host"], "category": s["category"], "payments": s["payments"],
               "usdc": _money(s["usdc"]), "paid_per_call": _money(per) if per is not None else None,
               "days_paid": len(s["days"]), "first_paid": min(s["days"]), "last_paid": max(s["days"]),
               "listed": ({"min": lo, "median": me.get("price_med"), "max": hi} if me else None),
               "paid_above_list": (per > ABOVE_LIST * hi) if (per is not None and hi) else None,
               "going_rate": g,
               "above_going_rate": (per > ABOVE_GOING * g) if (per is not None and g) else None,
               "others": ({"payments": o["payments"], "usdc": _money(o["usdc"]), "wallets": len(o["wallets"]),
                           "paid_per_call": _money(o["usdc"] / o["payments"])} if o and o["payments"] else
                          {"payments": 0, "usdc": 0.0, "wallets": 0, "paid_per_call": None}),
               "in_registry": bool(me)}
        if hosts is not None:
            r = hosts.get(s["host"])
            st = r.get("state") if isinstance(r, dict) else None
            row["status"] = {"state": st if st in STATES else "not checked",
                             "checked": status.get("taken"),
                             "uptime_7d_pct": ((r.get("uptime_7d") or {}).get("pct") if isinstance(r, dict) else None)}
        return row

    def summary(b):
        rows = sorted((seller_row(s) for s in b.sellers.values()), key=lambda r: (-r["usdc"], -r["payments"], r["host"]))
        per_day = [{"date": d, "classified": d in classified_days, "payments": b.day[d]["payments"],
                    "usdc": _money(b.day[d]["usdc"])} for d in dates]
        cats = collections.OrderedDict()
        for r in rows:
            c = cats.setdefault(r["category"], {"category": r["category"], "payments": 0, "usdc": 0.0, "sellers": 0})
            c["payments"] += r["payments"]
            c["usdc"] += r["usdc"]
            c["sellers"] += 1
        new = [r["host"] for r in rows if r["first_paid"] == newest] if len(dates) > 1 else []
        return {"payments": sum(r["payments"] for r in rows), "usdc": _money(sum(r["usdc"] for r in rows)),
                "usdc_other_means": _money(b.other), "sellers_paid": len(rows),
                "per_day": per_day, "change": _change(per_day, newest, before),
                "by_category": sorted(({**c, "usdc": _money(c["usdc"])} for c in cats.values()),
                                      key=lambda c: (-c["usdc"], -c["payments"], c["category"])),
                "new_sellers": new, "top_sellers": [r["host"] for r in rows[:TOP]], "sellers": rows}

    per_wallet = []
    for w in ws:
        s = summary(books[w])
        per_wallet.append({"wallet": w, "short": whales.short(w), "explorer": whales.EXPLORER["Base"] + w, **s})
    tot = summary(total)
    out = {
        "ok": True, "chain": "Base", "wallets": ws,
        "window": {"days": len(dates), "asked": window, "dates": dates, "from": dates[0] if dates else None,
                   "to": newest, "hours": hours, "missing_dates": _missing(dates),
                   "classified_days": len(classified_days)},
        "registry_as_of": registry_date,
        "status": ({"loaded": True, "checked": status.get("taken"),
                    "note": "one unpaid request per seller at the last check"} if status else {"loaded": False}),
        "thresholds": {"paid_above_list": "paid per call over %gx the listed max price" % ABOVE_LIST,
                       "above_going_rate": "paid per call over %gx the category's median listed price" % ABOVE_GOING},
        "total": tot, "per_wallet": per_wallet, "caveats": CAVEATS,
        "source": "the Atlas's daily pulls of USDC transfers on Base; prices from the x402 discovery registry",
    }
    out["findings"] = findings(out)
    return out


def _day_before(dates):
    """The day right before the newest, when it is in the window; else None."""
    if len(dates) < 2:
        return None
    try:
        a, b = date.fromisoformat(dates[-2]), date.fromisoformat(dates[-1])
    except ValueError:
        return None
    return dates[-2] if (b - a).days == 1 else None


def _missing(dates):
    if len(dates) < 2:
        return []
    a, b = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    have = set(dates)
    out = []
    for i in range(1, (b - a).days):
        d = date.fromordinal(a.toordinal() + i).isoformat()
        if d not in have:
            out.append(d)
    return out


def _change(per_day, newest, before):
    if newest is None or before is None:
        return {"available": False, "say": "the window has no day right before the newest one"}
    now = next(p for p in per_day if p["date"] == newest)
    was = next(p for p in per_day if p["date"] == before)
    return {"available": True, "date": newest, "previous_date": before,
            "payments": now["payments"], "payments_before": was["payments"],
            "payments_pct": _pct(now["payments"], was["payments"]),
            "usdc": now["usdc"], "usdc_before": was["usdc"], "usdc_pct": _pct(now["usdc"], was["usdc"])}


def _n(k, one, many=None):
    return "%d %s" % (k, one if k == 1 else (many or one + "s"))


def _names(hosts, cap=5):
    return ", ".join(hosts[:cap]) + (" and %d more" % (len(hosts) - cap) if len(hosts) > cap else "")


def findings(r):
    """Short sentences made by fixed rules over the total. Facts, never advice, never who."""
    t, out = r["total"], []
    rows = t["sellers"]
    if r["status"]["loaded"]:
        down = [s["host"] for s in rows if (s.get("status") or {}).get("state") == "down"]
        wrong = [s["host"] for s in rows if (s.get("status") or {}).get("state") == "wrong"]
        if down:
            out.append("Your agents paid %s that %s down at the last check: %s."
                       % (_n(len(down), "seller"), "was" if len(down) == 1 else "were", _names(down)))
        if wrong:
            out.append("Your agents paid %s that answered without valid x402 payment terms at the last check: %s."
                       % (_n(len(wrong), "seller"), _names(wrong)))
    c = t["change"]
    if c["available"]:
        if c["usdc_pct"] is not None and abs(c["usdc_pct"]) >= 1:
            out.append("Spend %s %g%% on %s against the day before ($%s against $%s)."
                       % ("rose" if c["usdc_pct"] > 0 else "fell", abs(c["usdc_pct"]), c["date"],
                          _fmt(c["usdc"]), _fmt(c["usdc_before"])))
        elif not c["usdc_before"] and c["usdc"]:
            out.append("Spend on %s was $%s, after none the day before." % (c["date"], _fmt(c["usdc"])))
    if t["new_sellers"]:
        out.append("%s on %s, the newest day: %s."
                   % (_n(len(t["new_sellers"]), "new seller"), r["window"]["to"], _names(t["new_sellers"])))
    above = [s["host"] for s in rows if s["paid_above_list"]]
    if above:
        out.append("%s paid more per call than %gx the listed max price: %s."
                   % (_n(len(above), "seller was", "sellers were"), ABOVE_LIST, _names(above)))
    going = [s["host"] for s in rows if s["above_going_rate"]]
    if going:
        out.append("%s cost more per call than %gx the going rate in %s category: %s."
                   % (_n(len(going), "seller"), ABOVE_GOING, "its" if len(going) == 1 else "their", _names(going)))
    unlisted = [s["host"] for s in rows if not s["in_registry"]]
    if unlisted:
        out.append("%s paid %s not in the newest registry snapshot: %s."
                   % ("Your agents", _n(len(unlisted), "seller"), _names(unlisted)))
    idle = [w["short"] for w in r["per_wallet"] if not w["payments"]]
    if idle and len(r["per_wallet"]) > 1:
        out.append("%s made no x402 payment in the window: %s." % (_n(len(idle), "wallet"), _names(idle)))
    elif idle:
        out.append("This wallet made no x402 payment in the window.")
    un = r["window"]["days"] - r["window"]["classified_days"]
    if un:
        out.append("%s in the window %s from a pull that did not tell x402 payments from other transfers; "
                   "there every transfer to a seller's wallet is counted." % (_n(un, "day"), "comes" if un == 1 else "come"))
    if r["window"]["missing_dates"]:
        out.append("No pull is loaded for %s." % _names(r["window"]["missing_dates"]))
    return out


def _fmt(x):
    """Dollars: two decimals, up to four below a dollar when the cents alone would hide it."""
    if x >= 1 or x == 0:
        return "{:,.2f}".format(x)
    s = ("%.4f" % x).rstrip("0")
    return s + "0" * max(0, 2 - len(s.split(".")[1]))


# ── the service: what is sold and what is refused, before any money ───────

def answer(wallets, window, days, sellers, registry_date=None, status=None, today=None, max_age_days=2,
           need_payments=False, problems=()):
    """(status, body). 200 is an answer; every other status is a refusal that is never billed.
      400  malformed wallets or days
      503  no on-chain window is loaded, or its newest day is too old (or in the future)
      404  need_payments and no x402 payment from these wallets in the window"""
    ws, why = parse_wallets(wallets)
    if why:
        return 400, {"ok": False, "charged": False, "error": "invalid_wallet", "say": why}
    n, why = parse_days(window)
    if why:
        return 400, {"ok": False, "charged": False, "error": "invalid_days", "say": why}
    if not days:
        return 503, {"ok": False, "charged": False, "error": "on_chain_not_loaded",
                     "say": "no on-chain window is loaded on this host; nothing was charged",
                     **({"problems": list(problems)[:5]} if problems else {})}
    newest = max(d["date"] for d in days)
    age = ((today or date.today()) - date.fromisoformat(newest)).days
    if age < 0 or age > max_age_days:
        return 503, {"ok": False, "charged": False, "error": "stale_on_chain" if age > 0 else "future_on_chain",
                     "newest_day": newest, "limit_days": max_age_days,
                     "say": "the newest on-chain day is %s; it is not sold as today's, and nothing was charged" % newest}
    body = report(ws, n, days=days, sellers=sellers, status=status, registry_date=registry_date)
    if need_payments and not body["total"]["payments"]:
        return 404, {"ok": False, "charged": False, "error": "no_x402_payments", "wallet": ws[0],
                     "window": body["window"],
                     "say": "no x402 payment from this wallet reached a seller the registry names in the window; "
                            "nothing was charged"}
    body["age_days"] = age
    return 200, body


# ── the fragment and the page ─────────────────────────────────────────────

def _e(x):
    return html.escape("" if x is None else str(x), quote=True)


def _usd(x):
    return "—" if x is None else "$" + _fmt(x)


def _price(x):
    return "—" if not x else "$%g" % x


def _listed(l):
    if not l or not l.get("max"):
        return "—"
    return _price(l["max"]) if l.get("min") == l.get("max") else "%s–%s" % (_price(l.get("min")), _price(l["max"]))


def watch_block(r):
    """The report as an HTML fragment for a page to include. Everything from the data is escaped."""
    t, w = r["total"], r["window"]
    p = ['<section class="ih-watch">',
         '<h2>What %s spent, %s to %s</h2>' % (_n(len(r["wallets"]), "wallet"), _e(w["from"]), _e(w["to"])),
         '<p class="ih-watch-sum">%s %s · %s USDC · %s paid</p>'
         % (_e("{:,}".format(t["payments"])), "x402 payments" if w["days"] == w["classified_days"] else "payments *",
            _e(_usd(t["usdc"])), _e(_n(t["sellers_paid"], "seller")))]
    if r["findings"]:
        p.append('<ul class="ih-watch-findings">%s</ul>' % "".join("<li>%s</li>" % _e(f) for f in r["findings"]))
    p.append('<table class="ih-watch-days"><thead><tr><th>day</th><th>payments</th><th>USDC</th></tr></thead><tbody>')
    for d in t["per_day"]:
        p.append("<tr><td>%s%s</td><td>%s</td><td>%s</td></tr>"
                 % (_e(d["date"]), "" if d["classified"] else " *", _e(d["payments"]), _e(_usd(d["usdc"]))))
    p.append("</tbody></table>")
    p.append('<table class="ih-watch-sellers"><thead><tr><th>seller</th><th>category</th><th>payments</th>'
             '<th>USDC</th><th>paid per call</th><th>listed</th><th>going rate</th><th>others pay</th>'
             '<th>status</th></tr></thead><tbody>')
    for s in t["sellers"][:TOP]:
        flags = []
        if s["paid_above_list"]:
            flags.append('<span class="ih-flag">paid above list</span>')
        if s["above_going_rate"]:
            flags.append('<span class="ih-flag">above going rate</span>')
        if s["host"] in t["new_sellers"]:
            flags.append('<span class="ih-flag ih-new">new</span>')
        st = (s.get("status") or {}).get("state")
        p.append("<tr><td>%s %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                 "<td>%s</td></tr>"
                 % (_e(s["host"]), " ".join(flags), _e(s["category"]), _e(s["payments"]), _e(_usd(s["usdc"])),
                    _e(_usd(s["paid_per_call"])), _e(_listed(s["listed"])), _e(_price(s["going_rate"])),
                    _e(_usd(s["others"]["paid_per_call"])),
                    '<span class="ih-status ih-%s">%s</span>' % (_e(st), _e(st)) if st else "—"))
    p.append("</tbody></table>")
    if len(r["per_wallet"]) > 1:
        p.append('<ul class="ih-watch-wallets">')
        for x in r["per_wallet"]:
            p.append('<li><a href="%s" rel="noopener">%s</a>: %s payments, %s, %s</li>'
                     % (_e(x["explorer"]), _e(x["short"]), _e(x["payments"]), _e(_usd(x["usdc"])),
                        _e(_n(x["sellers_paid"], "seller"))))
        p.append("</ul>")
    if w["days"] != w["classified_days"]:
        p.append('<p class="ih-note">* a day whose pull did not tell x402 payments from other transfers</p>')
    p.append('<details class="ih-note"><summary>How to read this</summary><ul>%s</ul></details>'
             % "".join("<li>%s</li>" % _e(c) for c in r["caveats"]))
    p.append("</section>")
    return "\n".join(p)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Watch your agents · __BRAND__</title>
<meta name="description" content="Paste your agents' wallet addresses and see what they spent over x402 on Base, with whom, and how each seller stands. Read from the chain.">
<style>
:root{--bg:#fbfaf7;--fg:#1d1c1a;--mut:#6b6760;--line:#e4e0d8;--acc:#7a4bd6;--warn:#b3471d;--ok:#2f7d4f;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141312;--fg:#eceae6;--mut:#a29d95;--line:#302d2a;--acc:#b99bff;--warn:#ff9a6b;--ok:#7fd29e;--card:#1c1b19}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}
p.lede{color:var(--mut);margin:0 0 20px}
form{display:grid;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
label{font-size:.9rem;color:var(--mut)}
textarea,input,select{width:100%;font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px}
textarea{min-height:88px;font-family:ui-monospace,Menlo,monospace;font-size:.85rem}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
.row>div{flex:1 1 200px}
button{font:inherit;background:var(--acc);color:#fff;border:0;border-radius:6px;padding:9px 18px;cursor:pointer}
.small{font-size:.85rem;color:var(--mut)}
#out{margin-top:24px}
.err{color:var(--warn)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:.9rem}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:500}
.flag{display:inline-block;font-size:.75rem;border:1px solid var(--warn);color:var(--warn);border-radius:4px;padding:0 4px;margin-left:4px}
.new{border-color:var(--acc);color:var(--acc)}
.st-up{color:var(--ok)}.st-down,.st-wrong{color:var(--warn)}
ul.findings li{margin:4px 0}
</style>
</head>
<body>
<main>
<h1>Watch your agents</h1>
<p class="lede">Paste your agents' wallet addresses. See what they spent over x402 on Base, with whom, whether each seller charged its listed price, what others pay it, and whether it was up at the last check. Read from the chain: nothing has to be routed through us.</p>
<form id="f" autocomplete="off">
  <div><label for="wallets">Wallets, 1 to 25, one per line or separated by commas</label>
  <textarea id="wallets" spellcheck="false" placeholder="0x…"></textarea></div>
  <div class="row">
    <div><label for="key">__BRAND_SHORT__ Pro license key (sent only in the X-Atlas-Key header)</label>
    <input id="key" type="password" autocomplete="off" spellcheck="false"></div>
    <div style="flex:0 1 120px"><label for="days">Days</label>
    <select id="days"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option><option selected>7</option><option>8</option></select></div>
    <div style="flex:0 1 auto"><button type="submit">Watch</button></div>
  </div>
  <label class="small"><input id="remember" type="checkbox" style="width:auto"> Remember the key in this browser</label>
  <p class="small">The wallets, and the key if you tick the box, are kept only in this browser's storage. This page sends them to nothing but the __BRAND_SHORT__'s own seller, over https. <a href="__SELLER__/pro">What Pro is</a>.</p>
</form>
<div id="out" aria-live="polite"></div>
</main>
<script>
(function(){
var SELLER = "__SELLER__";
var K_W = "atlas-watch-wallets", K_K = "atlas-watch-key";
function get(k){ try { return window.localStorage.getItem(k) || ""; } catch (e) { return ""; } }
function put(k, v){ try { if (v) window.localStorage.setItem(k, v); else window.localStorage.removeItem(k); } catch (e) {} }
var $ = function(id){ return document.getElementById(id); };
$("wallets").value = get(K_W);
var saved = get(K_K);
if (saved) { $("key").value = saved; $("remember").checked = true; }

function el(tag, text, cls){ var n = document.createElement(tag); if (text != null) n.textContent = String(text); if (cls) n.className = cls; return n; }
function usd(x){ if (x == null) return "\u2014"; if (x >= 1 || x === 0) return "$" + x.toFixed(2); var t = String(+x.toFixed(4)); return "$" + ((t.split(".")[1] || "").length < 2 ? x.toFixed(2) : t); }
function price(x){ return x ? "$" + (+x) : "—"; }
function listed(l){ if (!l || !l.max) return "—"; return l.min === l.max ? price(l.max) : price(l.min) + "–" + price(l.max); }
function table(head, rows){
  var wrap = el("div", null, "scroll"), t = el("table"), th = el("thead"), tr = el("tr");
  head.forEach(function(h){ tr.appendChild(el("th", h)); }); th.appendChild(tr); t.appendChild(th);
  var tb = el("tbody"); rows.forEach(function(r){ var row = el("tr"); r.forEach(function(c){ var td = el("td"); if (c && c.nodeType) td.appendChild(c); else td.textContent = c == null ? "" : String(c); row.appendChild(td); }); tb.appendChild(row); });
  t.appendChild(tb); wrap.appendChild(t); return wrap;
}
function render(r){
  var out = $("out"); out.textContent = "";
  var t = r.total, w = r.window;
  out.appendChild(el("h2", "What " + r.wallets.length + (r.wallets.length === 1 ? " wallet" : " wallets") + " spent, " + w.from + " to " + w.to));
  out.appendChild(el("p", t.payments.toLocaleString() + (w.days === w.classified_days ? " x402 payments" : " payments *") + " · " + usd(t.usdc) + " USDC · " + t.sellers_paid + " sellers paid"));
  if (r.findings.length) { var ul = el("ul", null, "findings"); r.findings.forEach(function(f){ ul.appendChild(el("li", f)); }); out.appendChild(ul); }
  out.appendChild(table(["day", "payments", "USDC"], t.per_day.map(function(d){ return [d.date + (d.classified ? "" : " *"), d.payments, usd(d.usdc)]; })));
  out.appendChild(table(["seller", "category", "payments", "USDC", "paid per call", "listed", "going rate", "others pay", "status"],
    t.sellers.map(function(s){
      var name = el("span", s.host);
      if (s.paid_above_list) name.appendChild(el("span", "paid above list", "flag"));
      if (s.above_going_rate) name.appendChild(el("span", "above going rate", "flag"));
      if (t.new_sellers.indexOf(s.host) >= 0) name.appendChild(el("span", "new", "flag new"));
      var st = s.status ? el("span", s.status.state, "st-" + s.status.state) : "—";
      return [name, s.category, s.payments, usd(s.usdc), usd(s.paid_per_call), listed(s.listed), price(s.going_rate), usd(s.others.paid_per_call), st];
    })));
  if (r.per_wallet.length > 1) {
    out.appendChild(table(["wallet", "payments", "USDC", "sellers", "change"], r.per_wallet.map(function(x){
      var c = x.change.available && x.change.usdc_pct != null ? (x.change.usdc_pct > 0 ? "+" : "") + x.change.usdc_pct + "%" : "—";
      return [x.wallet, x.payments, usd(x.usdc), x.sellers_paid, c]; })));
  }
  if (w.days !== w.classified_days) out.appendChild(el("p", "* a day whose pull did not tell x402 payments from other transfers", "small"));
  var d = el("details"); d.appendChild(el("summary", "How to read this")); var cl = el("ul");
  r.caveats.forEach(function(c){ cl.appendChild(el("li", c)); }); d.appendChild(cl); out.appendChild(d);
}
$("f").addEventListener("submit", function(ev){
  ev.preventDefault();
  var wallets = $("wallets").value.split(/[\s,]+/).filter(Boolean).join(",");
  var key = $("key").value.trim();
  put(K_W, $("wallets").value.trim());
  put(K_K, $("remember").checked ? key : "");
  var out = $("out"); out.textContent = ""; out.appendChild(el("p", "Reading the chain…", "small"));
  fetch(SELLER + "/pro/watch?wallets=" + encodeURIComponent(wallets) + "&days=" + encodeURIComponent($("days").value),
        {headers: {"X-Atlas-Key": key, "Accept": "application/json"}, credentials: "omit", referrerPolicy: "no-referrer"})
    .then(function(res){ return res.json().then(function(b){ return [res.status, b]; }); })
    .then(function(x){ if (x[0] === 200) render(x[1]); else { out.textContent = ""; out.appendChild(el("p", (x[1] && (x[1].say || x[1].error)) || ("refused: " + x[0]), "err")); } })
    .catch(function(){ out.textContent = ""; out.appendChild(el("p", "The seller could not be reached. Try again in a minute.", "err")); });
});
})();
</script>
</body>
</html>
"""


def page(out, seller):
    """Write /watch/index.html into `out`. `seller` is the https address of the Atlas's seller."""
    seller = seller.rstrip("/")
    if not re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?$", seller) and not seller.startswith("http://127.0.0.1"):
        raise ValueError("the seller must be a plain https:// address")
    text = (PAGE.replace("__BRAND_SHORT__", _e(market.BRAND_SHORT)).replace("__BRAND__", _e(market.BRAND))
            .replace("__SELLER__", seller))
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "index.html")
    with open(path, "w") as f:
        f.write(text)
    return path


# ── the command line ──────────────────────────────────────────────────────

def busiest(days, n=5):
    """The n wallets with the most x402 payments over these days (all transfers on a day that
    was not classified)."""
    c = collections.Counter()
    for d in days:
        classified = any("n_x402" in e for e in d["edges"])
        for e in d["edges"]:
            c[(e.get("from") or "").lower()] += e.get("n_x402", 0) if classified else e.get("n", 0)
    return [w for w, k in c.most_common() if k and EVM.match(w)][:n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--store", required=True, help="a folder of flows-<date>.json")
    r.add_argument("--snapshot", help="radar-store/market-<date>.json, for prices and categories")
    r.add_argument("--status", help="probe.py's status-latest.json, if there is one")
    r.add_argument("--wallets", required=True)
    r.add_argument("--days", type=int, default=DEFAULT_DAYS)
    r.add_argument("--html", action="store_true", help="print watch_block() instead of JSON")
    b = sub.add_parser("busiest")
    b.add_argument("--store", required=True)
    b.add_argument("--n", type=int, default=5)
    p = sub.add_parser("page")
    p.add_argument("--out", required=True)
    p.add_argument("--seller", required=True)
    a = ap.parse_args()
    if a.cmd == "page":
        print("wrote", page(a.out, a.seller))
        return
    days, problems = load_days(a.store)
    for x in problems:
        print("spend_watch: left out %s" % x, file=sys.stderr)
    if a.cmd == "busiest":
        print("\n".join(busiest(days, a.n)))
        return
    rep = report(a.wallets, a.days, days=days, snapshot=a.snapshot, status_file=a.status, store=a.store)
    print(watch_block(rep) if a.html else json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
