#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit defb6e9). Edit it there, not here.
"""seller_report.py — "Your buyers": a report for one x402 seller about its own customers,
read from the x402 payments we observe on Base. What Atlas for Sellers sells.

    GET /sellers                      free: what the report holds, the price, a real sample with
                                      its numbers blurred to ranges, and how to subscribe
    GET /sellers/report/<host>        Atlas for Sellers, $29 a month: a Polar license key in
    GET /sellers/report/<host>.html   X-Atlas-Key (an Atlas Pro key opens it too); JSON, or one
                                      printable page in the Atlas look
    GET /x402/report/<host>           no key, no account: the same JSON, paid per call over x402,
                                      $0.50 (X402_PRICES; sell-who.py prices it)

The report is built from exactly what the paid `who` answer is built from: the snapshot set
who_service.fresh_capture() checks (the same freshness refusals), and the flows window in
who_service.CHAIN_STORE, read through who_service.relationships_window() (the same cache, and
the ledger relationships.window() keeps). For one seller host, per payTo wallet the window's
sellers map names for it:

    summary           buyers, payments and USDC over the window
    by_day            buyers, new buyers (first seen in the window that day), payments, USDC
    came_back         buyers who paid on 2 or more days, the rate, and the loyal buyers (top 20)
    lost              buyers who paid only in the first half, and where each went (left_for, top 20)
    arrived           buyers who paid only in the second half, and where they came from (top 20)
    bought_alongside  the sellers sharing the most buyers with it (top 20), with the share
    early_buyers      when they exist: the wallets that paid it on the window's first two days
    rivals            the 5 sellers sharing the most buyers, side by side with it
    what_changed      a short list made by fixed rules (RULES): deterministic, no model calls

Refusals, and none is billed: 400 not a hostname; 503 no snapshot, a stale one, no on-chain
window, a stale or changing one; 404 not in the registry, not in the window's sellers map, or
no x402 payment to its wallets in the window. Only a 200 is sold.

Wallets are shown in full: this is a seller's own customer list, read from a public chain. A
wallet is not an agent, and nothing here says who holds or runs one. No score and no single
number for a seller: every figure is a count with its dates. Standard library only.

    seller_report.py --store radar-store --flows-dir flows enrichx402.com [--html out.html]
"""

import argparse
import collections
import json
import os
import re
import sys
import threading
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import who_service  # noqa: E402  (also puts the mandala folder on the path)
import pro  # noqa: E402  (the key header, the Atlas address, the public address of this service)
import relationships  # noqa: E402
import atlas_style  # noqa: E402
import market  # noqa: E402

NAME = "Your buyers"
PRODUCT = market.PRODUCT + " for Sellers"
PRICE = "$29 a month"
KEY_PATH = "/sellers/report/"
X402_PATH = "/x402/report/"
X402_PRICES = {"report": "$0.50"}     # one report, one host, paid when fetched
EMAIL = atlas_style.EMAIL
TOP = 20              # the long lists: loyal, lost, left for, came from, bought alongside, early buyers
RIVALS = 5            # the sellers side by side with it
WENT_TO = 5           # sellers named for each lost buyer; went_to_total says how many there are
MASK = "0x····…····"  # a buyer wallet in the public sample

# What changed: fixed rules, applied in this order. Each item says the numbers and dates it read.
CHANGE_PCT = 20.0                     # buyers, payments, USDC between halves: a change of 20% or more...
CHANGE_MIN = {"buyers": 3, "payments": 10, "usdc": 1.0}   # ...and at least this much
BACK_MIN_BUYERS = 10                  # came-back rate between halves: each half needs this many buyers...
BACK_POINTS = 5.0                     # ...and a move of this many percentage points
MOVED_MIN = 3                         # buyers lost and arrived: said when either is at least this many
TOOK_MIN = 2                          # a seller named for taking (or sending) at least this many buyers
TOOK_MAX = 3                          # at most this many such sellers each way
RULES = [
    {"rule": "buyers_between_halves", "when": "distinct buyers in the second half against the first moved by %g%% or "
     "more and by at least %d" % (CHANGE_PCT, CHANGE_MIN["buyers"])},
    {"rule": "payments_between_halves", "when": "payments in the second half against the first moved by %g%% or more "
     "and by at least %d" % (CHANGE_PCT, CHANGE_MIN["payments"])},
    {"rule": "usdc_between_halves", "when": "USDC in the second half against the first moved by %g%% or more and by "
     "at least $%g" % (CHANGE_PCT, CHANGE_MIN["usdc"])},
    {"rule": "came_back_between_halves", "when": "the share of a half's buyers that paid on 2 or more of that half's "
     "days moved by %g points or more, each half with at least %d buyers" % (BACK_POINTS, BACK_MIN_BUYERS)},
    {"rule": "lost_and_arrived", "when": "buyers who paid only in the first half, against buyers who paid only in the "
     "second: said when either is at least %d" % MOVED_MIN},
    {"rule": "a_seller_took_lost_buyers", "when": "a seller that at least %d of its lost buyers started paying in the "
     "second half; at most %d, most first" % (TOOK_MIN, TOOK_MAX)},
    {"rule": "new_buyers_came_from", "when": "a seller at least %d of its arriving buyers had paid only in the first "
     "half; at most %d, most first" % (TOOK_MIN, TOOK_MAX)},
    {"rule": "early_buyers", "when": "its buyers on the window's last day are at least %d and at least %d times the "
     "first day's" % (relationships.EARLY_LAST_MIN, relationships.EARLY_TIMES)},
]

MEANS = {
    "buyer": "a wallet that paid this payTo wallet over x402 in the window",
    "came_back": "a buyer that paid on 2 or more distinct days of the window",
    "loyal": "the buyers that came back: most days paid, then most payments",
    "new_buyer": "first seen in the window on that day; on the window's first day every buyer is new to it, since "
                 "the window holds nothing before",
    "lost": "a buyer that paid only on days in the first half of the window, and not after",
    "left_for": "a lost buyer that started paying the other seller only in the second half",
    "arrived": "a buyer that paid only on days in the second half of the window",
    "came_from": "an arriving buyer that had paid the other seller only in the first half",
    "bought_alongside": "buyers this wallet shares with another seller in the window",
    "early_buyers": "the wallets that paid it on the window's first two days, when its buyers on the last day are at "
                    "least %d and at least %d times the first day's" % (relationships.EARLY_LAST_MIN,
                                                                         relationships.EARLY_TIMES),
    "rivals": "the %d sellers sharing the most buyers with this wallet, side by side with it: a comparison, not a "
              "verdict" % RIVALS,
    "halves": "the window split in two; with an odd number of days the middle day is in neither half",
    "busy": "buyer wallets that paid more than %d sellers in the window are left out of bought alongside, left for "
            "and came from, and each list says how many: a wallet that pays everyone says nothing about what goes "
            "together or who moved" % relationships.BUSY,
}

CAVEATS = [
    "a wallet is not an agent, and nothing here says who holds or runs one: a wallet is listed because it paid this "
    "seller's payTo wallet on a public chain",
    "x402 payments only: transfers a facilitator settled on a buyer's signature, on Base; money that reached the same "
    "wallet by ordinary transfer is not a call and is not counted",
    "the window is the Atlas's daily pulls, up to %d days: a buyer from before the window is not seen, so new means "
    "new to the window" % relationships.MAX_DAYS,
    "each payTo wallet is read on its own, across every host paid into it: a wallet shared by several hosts carries "
    "all of their buyers",
    "no score and no single number for a seller: every figure is a count with its dates, and the rivals are the "
    "sellers that share its buyers, not a judgement of anyone",
]

SOURCE = "the Atlas's daily Base pull (flows window), checked against the x402 discovery registry's daily snapshot"

SECTIONS = [
    ("summary", "buyers, payments and USDC over the window"),
    ("by_day", "buyers, new buyers, payments and USDC, day by day"),
    ("came_back", "how many buyers came back, the rate, and the loyal buyers (top %d)" % TOP),
    ("lost", "buyers who paid only in the first half, and where each went (left for, top %d)" % TOP),
    ("arrived", "buyers who paid only in the second half, and where they came from (top %d)" % TOP),
    ("bought_alongside", "the sellers sharing the most buyers with it (top %d), with the share" % TOP),
    ("early_buyers", "when they exist: the wallets that paid it on the window's first two days"),
    ("rivals", "its %d closest rivals by shared buyers, side by side: buyers, came-back rate, payments" % RIVALS),
    ("what_changed", "a short list made by fixed rules, each with its numbers and dates"),
]


def valid_host(host):
    """A seller host as the registry holds it: never a wallet, never an option, never a path."""
    h = (host or "").lower()
    return bool(who_service.HOST.fullmatch(h)) and not who_service.EVM.fullmatch(h)   # fullmatch: "$" lets a final newline through


# --- the report, from one window ----------------------------------------------------------

def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def _top(counter, n=TOP):
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def _other(win, w, **extra):
    """Another seller wallet, named by its most particular hosts (as relationships.py names it)."""
    hs = win.get("wallet_hosts", {}).get(w, [])
    out = {"wallet": w, "hosts": hs[:relationships.OTHER_HOSTS], "hosts_total": len(hs)}
    out.update(extra)
    return out


def _span(dates):
    return {"from": dates[0], "to": dates[-1], "days": len(dates)} if dates else {"from": None, "to": None, "days": 0}


def wallet(win, s):
    """Everything the report says about one payTo wallet, from the window's ledger. Pure."""
    f = win["sellers"][s]
    dates = win["dates"]
    first, second = win["halves"]["first"], win["halves"]["second"]
    F, L = set(first), set(second)
    led = win["ledger"]
    paid, bought, busy = led["paid"], led["bought"], set(led["busy"])
    mine = paid.get(s, {})
    rows = {b: (sorted(per), sum(v[0] for v in per.values()), sum(v[1] for v in per.values()))
            for b, per in mine.items()}
    span = _span(dates)
    n_buyers = len(rows)

    def days_with(b, t):
        return set(paid.get(t, {}).get(b, ()))

    first_seen = collections.Counter(ds[0] for ds, _, _ in rows.values())
    by_day = []
    for d in dates:
        xs = [per[d] for per in mine.values() if d in per]
        by_day.append({"date": d, "buyers": len(xs), "new_buyers": first_seen.get(d, 0),
                       "payments": sum(x[0] for x in xs), "usdc": round(sum(x[1] for x in xs), 4)})

    back = sorted(((b, r) for b, r in rows.items() if len(r[0]) >= 2), key=lambda x: (-len(x[1][0]), -x[1][1], x[0]))
    came_back = dict(f["came_back"], dates=span, loyal=[
        {"wallet": b, "days": len(ds), "first": ds[0], "last": ds[-1], "payments": n, "usdc": round(u, 4)}
        for b, (ds, n, u) in back[:TOP]])

    def half(H):
        n_b = n_back = pay = 0
        usd = 0.0
        for per in mine.values():
            ds = [d for d in per if d in H]
            if ds:
                n_b += 1
                n_back += len(ds) >= 2
                pay += sum(per[d][0] for d in ds)
                usd += sum(per[d][1] for d in ds)
        return {"dates": sorted(H), "buyers": n_b, "came_back": n_back, "came_back_rate_pct": _pct(n_back, n_b),
                "payments": pay, "usdc": round(usd, 4)}
    halves = {"first": half(F), "second": half(L)} if first else None

    lost_rows, left_for, lost_busy = [], collections.Counter(), 0
    arrived_n, came_from, arrived_busy = 0, collections.Counter(), 0
    if first:
        for b, (ds, n, u) in rows.items():
            mine_days = set(ds)
            if mine_days <= F:
                went = None
                if b in busy:
                    lost_busy += 1
                else:
                    went = sorted(t for t in bought.get(b, ()) if t != s and days_with(b, t) and days_with(b, t) <= L)
                    left_for.update(went)
                lost_rows.append((b, ds, n, u, went))
            elif mine_days <= L:
                arrived_n += 1
                if b in busy:
                    arrived_busy += 1
                else:
                    came_from.update(t for t in bought.get(b, ()) if t != s and days_with(b, t) and days_with(b, t) <= F)
    lost_rows.sort(key=lambda r: (-r[2], -r[3], r[0]))
    halves_dates = {"first_half": first, "second_half": second}
    lost = {"buyers": len(lost_rows), "of": n_buyers, "dates": halves_dates,
            "list": [{"wallet": b, "days": len(ds), "last_paid": ds[-1], "payments": n, "usdc": round(u, 4),
                      "busy": went is None,
                      "went_to": None if went is None else [_other(win, t) for t in went[:WENT_TO]],
                      "went_to_total": None if went is None else len(went)}
                     for b, ds, n, u, went in lost_rows[:TOP]],
            "left_for": [_other(win, t, buyers=c) for t, c in _top(left_for)],
            "busy_buyers_left_out": lost_busy}
    arrived = {"buyers": arrived_n, "of": n_buyers, "dates": halves_dates,
               "came_from": [_other(win, t, buyers=c) for t, c in _top(came_from)],
               "busy_buyers_left_out": arrived_busy}

    along, busy_here = collections.Counter(), 0
    for b in rows:
        if b in busy:
            busy_here += 1
            continue
        along.update(t for t in bought.get(b, ()) if t != s)
    alongside = {"dates": span, "busy_buyers_left_out": busy_here,
                 "sellers": [_other(win, t, shared_buyers=c, share_pct=_pct(c, n_buyers)) for t, c in _top(along)]}

    early = None
    if f["early_buyers"]:
        e = f["early_buyers"]
        ew = sorted(((b, r) for b, r in rows.items() if set(r[0]) & set(e["days"])), key=lambda x: (-x[1][1], x[0]))
        early = dict(e, list=[{"wallet": b, "first": ds[0], "days": len(ds), "payments": n, "usdc": round(u, 4)}
                              for b, (ds, n, u) in ew[:TOP]])

    def side(t, **extra):
        g = win["sellers"][t]
        return _other(win, t, buyers=g["buyers"]["count"], came_back=g["came_back"]["buyers"],
                      came_back_rate_pct=g["came_back"]["rate_pct"], payments=g["buyers"]["payments"],
                      usdc=g["buyers"]["usdc"], days_paid=g["days"]["paid"], **extra)
    rivals = {"dates": span, "rule": "the %d sellers sharing the most buyers with this wallet" % RIVALS,
              "side_by_side": [side(s, this=True, shared_buyers=None)] +
                              [side(t, this=False, shared_buyers=c) for t, c in _top(along, RIVALS)]}

    out = {"wallet": s, "hosts": f["hosts"], "hosts_total": f["hosts_total"],
           "summary": {"buyers": n_buyers, "payments": f["buyers"]["payments"], "usdc": f["buyers"]["usdc"],
                       "days_paid": f["days"]["paid"], "window_days": f["days"]["window"],
                       "paid_on": f["days"]["paid_on"], "from": span["from"], "to": span["to"]},
           "by_day": by_day, "came_back": came_back,
           "new_buyers": {"dates": span, "first_day": by_day[0]["new_buyers"] if by_day else 0,
                          "after_first_day": sum(x["new_buyers"] for x in by_day[1:]),
                          "note": MEANS["new_buyer"]},
           "halves": halves, "lost": lost, "arrived": arrived, "bought_alongside": alongside,
           "early_buyers": early, "rivals": rivals, "notes": list(f["notes"])}
    out["what_changed"] = what_changed(out)
    return out


def _name(x):
    hs = x.get("hosts") or []
    if not hs:
        return x["wallet"]
    more = x.get("hosts_total", len(hs)) - 1
    return hs[0] + (" (and %d more host%s on its wallet)" % (more, "s" if more != 1 else "") if more > 0 else "")


def _ds(ds):
    return ds[0] if len(ds) == 1 else "%s to %s" % (ds[0], ds[-1])


def _num(x, money=False):
    return "$%s" % "{:,.2f}".format(x) if money else "{:,}".format(x)


def what_changed(w):
    """The short list, by RULES and nothing else. Every item carries the numbers and dates it read."""
    out = []
    h = w["halves"]
    if not h:
        return out
    a, b = h["first"], h["second"]
    da, db = a["dates"], b["dates"]
    for key, word in (("buyers", "Distinct buyers"), ("payments", "Payments"), ("usdc", "USDC")):
        x, y = a[key], b[key]
        if x == y or abs(y - x) < CHANGE_MIN[key] or (x and abs(y - x) < CHANGE_PCT / 100.0 * x):
            continue
        m = key == "usdc"
        say = "%s %s from %s (%s) to %s (%s)%s." % (
            word, "rose" if y > x else "fell", _num(x, m), _ds(da), _num(y, m), _ds(db),
            ", %s%g%%" % ("up " if y > x else "down ", round(abs(100.0 * (y - x) / x), 1)) if x else "")
        out.append({"rule": key + "_between_halves", "say": say, "numbers": {"first_half": x, "second_half": y},
                    "dates": {"first_half": da, "second_half": db}})
    if len(da) >= 2 and a["buyers"] >= BACK_MIN_BUYERS and b["buyers"] >= BACK_MIN_BUYERS:
        ra, rb = a["came_back_rate_pct"], b["came_back_rate_pct"]
        if abs(rb - ra) >= BACK_POINTS:
            say = ("The came-back rate %s from %g%% (%s of %s buyers paid on 2 or more days of %s) to %g%% (%s of %s, %s)."
                   % ("rose" if rb > ra else "fell", ra, _num(a["came_back"]), _num(a["buyers"]), _ds(da), rb,
                      _num(b["came_back"]), _num(b["buyers"]), _ds(db)))
            out.append({"rule": "came_back_between_halves", "say": say,
                        "numbers": {"first_half": {"came_back": a["came_back"], "of": a["buyers"], "rate_pct": ra},
                                    "second_half": {"came_back": b["came_back"], "of": b["buyers"], "rate_pct": rb}},
                        "dates": {"first_half": da, "second_half": db}})
    lost, arr = w["lost"]["buyers"], w["arrived"]["buyers"]
    if max(lost, arr) >= MOVED_MIN:
        verdict = ("more arrived than left" if arr > lost else "more left than arrived" if lost > arr
                   else "as many arrived as left")
        out.append({"rule": "lost_and_arrived", "numbers": {"lost": lost, "arrived": arr},
                    "dates": {"first_half": da, "second_half": db},
                    "say": "%s buyer%s paid it only in the first half (%s) and %s only in the second (%s): %s."
                           % (_num(lost), "" if lost == 1 else "s", _ds(da), _num(arr), _ds(db), verdict)})
    rivals = {x["wallet"] for x in w["rivals"]["side_by_side"] if not x["this"]}
    for x in [x for x in w["lost"]["left_for"] if x["buyers"] >= TOOK_MIN][:TOOK_MAX]:
        out.append({"rule": "a_seller_took_lost_buyers", "numbers": {"buyers": x["buyers"], "lost": lost},
                    "seller": {"wallet": x["wallet"], "hosts": x["hosts"], "hosts_total": x["hosts_total"]},
                    "dates": {"first_half": da, "second_half": db},
                    "say": "%s of the buyers it lost (%s) started paying %s in the second half (%s)%s."
                           % (_num(x["buyers"]), _ds(da), _name(x), _ds(db),
                              ", one of its closest rivals" if x["wallet"] in rivals else "")})
    for x in [x for x in w["arrived"]["came_from"] if x["buyers"] >= TOOK_MIN][:TOOK_MAX]:
        out.append({"rule": "new_buyers_came_from", "numbers": {"buyers": x["buyers"], "arrived": arr},
                    "seller": {"wallet": x["wallet"], "hosts": x["hosts"], "hosts_total": x["hosts_total"]},
                    "dates": {"first_half": da, "second_half": db},
                    "say": "%s of the buyers that arrived in the second half (%s) had paid %s only in the first (%s)."
                           % (_num(x["buyers"]), _ds(db), _name(x), _ds(da))})
    e = w["early_buyers"]
    if e:
        dates = w["summary"]
        out.append({"rule": "early_buyers", "numbers": {k: e[k] for k in ("wallets", "first_day_buyers", "last_day_buyers")},
                    "dates": {"early": e["days"], "first_day": dates["from"], "last_day": dates["to"]},
                    "say": "Its daily buyers went from %s on %s to %s on %s; %s wallet%s paid it on %s, the early buyers."
                           % (_num(e["first_day_buyers"]), dates["from"], _num(e["last_day_buyers"]), dates["to"],
                              _num(e["wallets"]), "" if e["wallets"] == 1 else "s", " and ".join(e["days"]))})
    return out


def registry_row(row):
    row = row or {}
    return {"sells": row.get("sells"), "price_min": row.get("price_min"), "price_max": row.get("price_max"),
            "endpoints": row.get("endpoints"), "chains": row.get("chains") or [],
            "payto_wallets": len(row.get("wallets") or [])}


def build(win, host, row=None, as_of=None):
    """The whole report for `host` from one window, or None when the window's sellers map does
    not name the host. Pure: the report() wrapper decides what may be sold."""
    view = relationships.for_host(win, host)
    if view is None:
        return None
    dates = win["dates"]
    body = {"ok": True, "report": NAME, "host": view["host"], "as_of": as_of, "registry": registry_row(row),
            "window": {"chain": "Base", "dates": dates, "from": dates[0], "to": dates[-1], "days": len(dates),
                       "halves": win["halves"], "busy": relationships.BUSY},
            "wallets": [wallet(win, f["wallet"]) for f in view["wallets"]], "unpaid_wallets": view["unpaid_wallets"]}
    if win.get("problems"):
        body["incomplete"] = True
        body["problems"] = [str(x)[:200] for x in win["problems"][:10]]
    ws = body["wallets"]
    if len(ws) > 1 or any(w["hosts_total"] > 1 for w in ws):
        body["say"] = ("each wallet's figures are its own, across every host paid into it; this host is paid into "
                       "%d wallet%s that were paid in the window" % (len(ws), "s" if len(ws) != 1 else ""))
    body.update({"means": MEANS, "rules": RULES, "caveats": CAVEATS, "source": SOURCE})
    return body


# --- what may be sold ---------------------------------------------------------------------

_lock = threading.Lock()
_reports = {}        # (set key, window key, host) -> (status, body without age_days)
MAX_CACHED = 500


def _no(code, error, say, **extra):
    body = {"ok": False, "charged": False, "error": error, "say": say}
    body.update(extra)
    return code, body


def _window_now(now, max_age_days):
    """(key, window, None) for a window that may be sold today, or (None, None, refusal)."""
    key, win = who_service.relationships_window()
    if key is None:
        return None, None, _no(503, "on_chain_not_loaded", "the on-chain window is not loaded on this host; "
                                                            "nothing was charged")
    if key == who_service.CHANGING:
        return None, None, _no(503, "window_changing", "the on-chain window's files were changing while they were "
                                                       "read; ask again shortly, nothing was charged")
    if not win.get("dates") or "ledger" not in win:
        return None, None, _no(503, "window_unreadable", "no day of the on-chain window could be read (%s); nothing "
                               "was charged" % "; ".join(str(p) for p in (win.get("problems") or ["no Base day"]))[:300])
    try:
        newest = date.fromisoformat(win["dates"][-1])
    except (TypeError, ValueError):     # a file named for a day that does not exist
        return None, None, _no(503, "window_unreadable", "the on-chain window's newest day is not a real date; "
                                                          "nothing was charged")
    age = (now - newest).days
    if age < 0:
        return None, None, _no(503, "future_window", "the on-chain window is dated in the future; nothing was charged",
                               window_to=newest.isoformat())
    if age > max_age_days + 1:          # the window's newest day is the day before the pull that read it
        return None, None, _no(503, "stale_window", "the on-chain window is too old to sell; nothing was charged",
                               window_to=newest.isoformat(), age_days=age, limit_days=max_age_days + 1)
    return key, win, None


def report(host, today=None, max_age_days=who_service.MAX_AGE_DAYS):
    """(status, body). 200 is the only status that is sold; every refusal says charged: false."""
    # exactly the check the routes make before they skip payment and the key: nothing is stripped or
    # repaired here, so a host a route let through unpaid as invalid can never become a 200
    h = (host or "").lower()
    if not valid_host(h):
        return 400, {"ok": False, "charged": False, "error": "invalid_host",
                     "expected": "a seller's hostname, like api.example.com"}
    now = today or date.today()
    set_key, loaded, newest, refusal = who_service.fresh_capture(now, max_age_days)
    if refusal:
        return refusal
    rel_key, win, refusal = _window_now(now, max_age_days)
    if refusal:
        return refusal
    ckey = (set_key, rel_key, h)
    with _lock:
        hit = _reports.get(ckey)
    if hit:
        return who_service.with_age(hit[0], hit[1], now)
    A = loaded[-1]["sellers"]
    name = next((k for k in A if k.lower() == h), None)
    if name is None and h.startswith("www."):
        name = next((k for k in A if k.lower() == h[4:]), None)
    as_of = newest.isoformat()
    if name is None:
        out = _no(404, "not_in_registry", "not found in the x402 discovery registry as of %s; absence from one "
                  "registry is not absence from the market, and nothing was charged" % as_of, host=h, as_of=as_of)
    else:
        body = build(win, name.lower(), A[name], as_of)
        chains = (A[name].get("chains") or [])
        if body is None:
            out = _no(404, "not_in_window", "this seller's payTo wallets are not in the on-chain window's sellers map%s; "
                      "nothing was charged" % ("" if "Base" in chains else ": it takes payment on %s, and the window "
                                               "reads Base only" % (", ".join(chains) or "another chain")),
                      host=h, as_of=as_of, window={"from": win["dates"][0], "to": win["dates"][-1]})
        elif not body["wallets"]:
            out = _no(404, "no_x402_payments", "no x402 payment reached this seller's wallets on Base from %s to %s, "
                      "so there are no buyers to report; nothing was charged" % (win["dates"][0], win["dates"][-1]),
                      host=h, as_of=as_of, window={"from": win["dates"][0], "to": win["dates"][-1]},
                      unpaid_wallets=body["unpaid_wallets"])
        else:
            out = 200, body
    try:
        unchanged = who_service._set_keys() == set_key and relationships.files_key(who_service.CHAIN_STORE) == rel_key
    except who_service.SetChanged:
        unchanged = False
    if not unchanged:                       # the store changed under us: sell nothing from a mixed set
        return _no(503, "snapshot_changed", "the snapshots or the on-chain window changed while the report was being "
                                            "prepared; ask again, nothing was charged")
    with _lock:
        if len(_reports) >= MAX_CACHED or any(k[:2] != ckey[:2] for k in list(_reports)[:1]):
            _reports.clear()
        _reports[ckey] = out
    return who_service.with_age(out[0], out[1], now)


# --- the public sample --------------------------------------------------------------------

def busiest(win, sellers, full=False):
    """(host, wallet) for the payTo wallet with the most buyers in the window that has a host in
    the registry's `sellers` (any host when sellers is None), or None. With full, the busiest
    whose buyers also paid at least RIVALS other sellers, so every section of its report has
    something in it; the busiest of all when no wallet has that many."""
    names = None if sellers is None else {h.lower() for h in sellers}
    best, best_full = None, None
    for s, f in ((win or {}).get("sellers") or {}).items():
        hs = [h for h in (win.get("wallet_hosts") or {}).get(s, []) if names is None or h in names]
        if not hs:
            continue
        k = (-f["buyers"]["count"], -f["buyers"]["payments"], s)
        if best is None or k < best[0]:
            best = (k, hs[0], s)
        if len(f["bought_alongside"]["sellers"]) >= RIVALS and (best_full is None or k < best_full[0]):
            best_full = (k, hs[0], s)
    pick = (best_full or best) if full else best
    return (pick[1], pick[2]) if pick else None


def _bands(x, edges, fmt):
    if x <= 0:
        return fmt(0)
    for lo, hi in zip(edges, edges[1:]):
        if x < hi:
            return "%s–%s" % (fmt(lo), fmt(hi if isinstance(hi, float) else hi - 1))
    return "%s or more" % fmt(edges[-1])


COUNT_EDGES = [1, 10, 50, 100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000]
USD_EDGES = [0.0001, 1.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0, 10000.0, 50000.0, 100000.0]


def count_band(n):
    return _bands(n, COUNT_EDGES, lambda v: "{:,}".format(int(v)))


def usd_band(x):
    if 0 < x < 1:
        return "under $1"
    return _bands(x, USD_EDGES, lambda v: "$%s" % "{:,}".format(int(v)))


def pct_band(p):
    """A share in ten-point bands (100% is the top one); a change above 100% in wide ones."""
    if p is None:
        return None
    if p <= 0:
        return "0%"
    if p <= 100:
        lo = min(int(p // 10) * 10, 90)
        return "%d–%d%%" % (lo, lo + 10)
    for lo, hi in ((100, 200), (200, 500)):
        if p < hi:
            return "%d–%d%%" % (lo, hi)
    return "500% or more"


NUMBER = re.compile(r"(?<![\w.$-])(\$?)(\d[\d,]*(?:\.\d+)?)(%?)(?![\w-]|\.\d| more hosts? on its wallet)")


def blur_text(text):
    """A sentence with its numbers turned to ranges; ISO dates (2026-09-25) and names are kept."""
    def one(m):
        v = float(m.group(2).replace(",", ""))
        if m.group(1):
            return usd_band(v)
        if m.group(3):
            return pct_band(v)
        return count_band(v)
    return NUMBER.sub(one, text)


KEEP_EXACT = {"days", "days_paid", "window_days", "hosts_total", "went_to_total"}


def _blur(k, v):
    if isinstance(v, dict):
        return {kk: _blur(kk, vv) for kk, vv in v.items()}
    if isinstance(v, list):
        return [_blur(k, x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        if k in KEEP_EXACT:
            return v
        if k.endswith("_pct"):
            return pct_band(v)
        if k == "usdc":
            return usd_band(v)
        return count_band(v)
    if isinstance(v, str) and k == "say":
        return blur_text(v)
    return v


BUYER_LISTS = (("came_back", "loyal"), ("lost", "list"), ("early_buyers", "list"))
SELLER_LISTS = (("lost", "left_for"), ("arrived", "came_from"), ("bought_alongside", "sellers"))


def blur(w, keep=3):
    """One wallet's report as the public sample shows it: every number a range, every buyer
    wallet masked, each long list cut to `keep` rows with how many more there are (a range too).
    The report given is never changed."""
    w = json.loads(json.dumps(w))
    for sec, key in BUYER_LISTS + SELLER_LISTS:
        part = w.get(sec)
        if isinstance(part, dict) and isinstance(part.get(key), list):
            more = len(part[key]) - keep
            part[key] = part[key][:keep]
            part[key + "_more"] = max(more, 0)
    for sec, key in BUYER_LISTS:
        for x in (w.get(sec) or {}).get(key) or []:
            x["wallet"] = MASK
    out = _blur(None, w)
    out["blurred"] = True
    return out


def sample(today=None, max_age_days=who_service.MAX_AGE_DAYS):
    """The public sample, now: the busiest seller's wallet in the window, blurred. Built through
    report(), so it is refused for the same reasons, and read from the same cache."""
    now = today or date.today()
    set_key, loaded, newest, refusal = who_service.fresh_capture(now, max_age_days)
    if refusal:
        return {"available": False, "say": "no sample right now: " + str(refusal[1].get("say") or refusal[1]["error"])}
    _key, win, refusal = _window_now(now, max_age_days)
    if refusal:
        return {"available": False, "say": "no sample right now: " + refusal[1]["say"]}
    pick = busiest(win, loaded[-1]["sellers"], full=True)
    if pick is None:
        return {"available": False, "say": "no sample right now: no seller in the registry was paid in the window"}
    host, s = pick
    code, body = report(host, now, max_age_days)
    if code != 200:
        return {"available": False, "say": "no sample right now: " + str(body.get("say") or body.get("error"))}
    return sample_from(body, s)


def sample_from(body, s):
    w = next((x for x in body["wallets"] if x["wallet"] == s), None)
    if w is None:                       # the window was replaced between choosing and reporting
        return {"available": False, "say": "no sample right now: the on-chain window changed; ask again shortly"}
    return {"available": True, "host": body["host"], "as_of": body["as_of"],
            "window": {k: body["window"][k] for k in ("chain", "from", "to", "days")},
            "about": "the busiest seller in the window, by buyers, among those whose buyers also paid at least %d "
                     "other sellers (so every section has something in it): one of its payTo wallets, every number "
                     "blurred to a range, every buyer wallet masked, each long list cut to three rows. The report "
                     "itself carries the exact figures and every wallet in full" % RIVALS,
            "wallet": blur(w)}


def describe(env=None, today=None, max_age_days=who_service.MAX_AGE_DAYS):
    """GET /sellers: what the report holds, the price, a real blurred sample, how to subscribe."""
    env = os.environ if env is None else env
    base = pro.who_service_public_url()
    checkout = (env.get("SELLERS_CHECKOUT_URL") or "").strip()
    subscribe = ({"open": True, "checkout": checkout} if checkout else
                 {"open": False, "say": "subscriptions open soon; to be told when, write to %s" % EMAIL, "email": EMAIL})
    return {
        "ok": True, "name": PRODUCT, "report": NAME, "price": PRICE,
        "what": "A report for an x402 seller about its own customers, read from its x402 payments on Base: who paid "
                "it and when, who came back, who left and for whom, where new buyers came from, what is bought "
                "alongside, and its closest rivals side by side. Per payTo wallet, every figure with its numbers and "
                "dates, every buyer wallet in full, and nothing said about who holds one.",
        "holds": dict(SECTIONS),
        "ways_to_pay": [
            "a subscription, %s: a Polar license key in the %s header opens %s<host> (JSON) and %s<host>.html (one "
            "printable page); an Atlas Pro key opens them too" % (PRICE, pro.HEADER, KEY_PATH, KEY_PATH),
            "per report, over x402: no key and no account, %s at %s<host>, JSON" % (X402_PRICES["report"], X402_PATH)],
        "auth": {"header": pro.HEADER, "value": "the license key Polar sends after you subscribe",
                 "refused": "401 when the key is missing, unknown, revoked, expired or for another product",
                 "limit": "%d calls per key per hour; 429 beyond it" % pro.PER_HOUR},
        "x402": {"price": X402_PRICES["report"], "path": X402_PATH + "<host>",
                 "refused": "400 not a hostname; 404 not in the registry, not in the window, or no x402 payment to it "
                            "in the window; 503 a stale snapshot or window. All before any payment is asked; nothing "
                            "is charged for a refusal"},
        "example": "curl -H '%s: YOUR-KEY' %s%sapi.example.com.html -o your-buyers.html" % (pro.HEADER, base, KEY_PATH),
        "example_x402": "an x402 client, e.g. GET %s%sapi.example.com, pays %s and receives the report as JSON"
                        % (base, X402_PATH, X402_PRICES["report"]),
        "subscribe": subscribe, "page": pro.ATLAS + "/sellers/",
        "sample": sample(today, max_age_days), "means": MEANS, "rules": RULES, "caveats": CAVEATS}


# --- one printable page -------------------------------------------------------------------

def esc(x):
    return atlas_style.esc(x)


def said(x):
    """Stranger text (a host, what a seller says it sells), as a page shows it."""
    return esc(atlas_style.unsay(x))


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def n_(x):
    return "{:,}".format(x) if _is_num(x) else ("—" if x is None else esc(x))


def usd_(x):
    if not _is_num(x):
        return "—" if x is None else esc(x)
    return "$%s" % ("{:,.2f}".format(x) if x >= 0.01 or x == 0 else "{:,.4f}".format(x))


def pct_(x):
    return ("%g%%" % x) if _is_num(x) else ("—" if x is None else esc(x))


def d_(iso):
    return esc(atlas_style.short_date(iso))


def days_(ds):
    return esc(" – ".join(atlas_style.short_date(d) for d in ([ds[0], ds[-1]] if len(ds) > 1 else ds))) if ds else "—"


def seller_(x):
    hs = x.get("hosts") or []
    if not hs:
        return "<code>%s</code>" % esc(x["wallet"])
    more = (x.get("hosts_total") or len(hs)) - 1
    return said(hs[0]) + (' <span class="muted">and %d more on its wallet</span>' % more if more > 0 else "")


def _more(part, key):
    m = part.get(key + "_more")
    if not m or m == "0":
        return ""
    return '<p class="muted">…and %s more in the report.</p>' % n_(m)


def bars(by_day):
    """Buyers a day as bars, new buyers in amber at the foot of each. Real numbers only: the
    blurred sample has none to draw."""
    if not by_day:
        return ""
    W, H, top, foot = 720, 150, 22, 24
    slot = W / len(by_day)
    bw = min(56.0, slot * 0.6)
    peak = max(x["buyers"] for x in by_day) or 1
    out = ['<svg class="bars" viewBox="0 0 %d %d" role="img" aria-label="Buyers a day; new buyers in amber">' % (W, H)]
    for i, x in enumerate(by_day):
        h = (H - top - foot) * x["buyers"] / peak
        hn = (H - top - foot) * x["new_buyers"] / peak
        mid, base = slot * i + slot / 2, H - foot
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>' % (mid - bw / 2, base - h, bw, h))
        if hn:
            out.append('<rect class="new" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>' % (mid - bw / 2, base - hn, bw, hn))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (mid, base - h - 6, n_(x["buyers"])))
        out.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>'
                   % (mid, H - 7, esc(atlas_style.short_date(x["date"])[:-5])))
    out.append("</svg>")
    return "".join(out)


def wallet_html(w, level=2):
    """One wallet's section: the report's body, real or blurred (the sample's ranges are strings)."""
    blurred = bool(w.get("blurred"))
    H, K = "h%d" % level, "h%d" % (level + 1)
    s, cb = w["summary"], w["came_back"]
    span = days_([s["from"], s["to"]])
    p = ['<section class="rpt-wallet" id="w-%s" aria-label="Wallet %s">' % (esc(w["wallet"]), esc(w["wallet"]))]
    p.append('<%s>Wallet <code>%s</code></%s>' % (H, esc(w["wallet"]), H))
    hosts = w.get("hosts") or []
    if w.get("hosts_total", 1) > 1:
        p.append('<p class="muted">Paid for %s%s. The figures are this wallet’s, across every host paid into it.</p>'
                 % (", ".join(said(h) for h in hosts),
                    " and %d more hosts" % (w["hosts_total"] - len(hosts)) if w["hosts_total"] > len(hosts) else ""))
    p.append('<p class="dateline">x402 payments on Base · %s · paid on %s of %s days</p>'
             % (span, n_(s["days_paid"]), n_(s["window_days"])))
    lost, arr = w["lost"], w["arrived"]
    p.append('<div class="tiles">'
             '<div class="tile"><b>%s</b><span>buyers</span></div>'
             '<div class="tile"><b>%s</b><span>payments</span></div>'
             '<div class="tile"><b>%s</b><span>USDC</span></div>'
             '<div class="tile"><b>%s</b><span>came back: %s of %s buyers</span></div>'
             '<div class="tile"><b>%s</b><span>new after the first day</span></div>'
             '<div class="tile"><b>%s · %s</b><span>lost · arrived, between halves</span></div></div>'
             % (n_(s["buyers"]), n_(s["payments"]), usd_(s["usdc"]), pct_(cb["rate_pct"]), n_(cb["buyers"]), n_(cb["of"]),
                n_(w["new_buyers"]["after_first_day"]), n_(lost["buyers"]), n_(arr["buyers"])))
    for note in w.get("notes") or []:
        p.append('<p class="muted">%s.</p>' % esc(note[:1].upper() + note[1:]))

    p.append("<%s>What changed</%s>" % (K, K))
    if w["what_changed"]:
        p.append('<ul class="cav changes">%s</ul>' % "".join("<li>%s</li>" % said(x["say"]) for x in w["what_changed"]))
    else:
        p.append('<p class="muted">Nothing crossed the rules in this window. The rules are listed at the end.</p>')

    p.append("<%s>Day by day</%s>" % (K, K))
    if not blurred:
        p.append(bars(w["by_day"]))
    p.append('<div class="tw"><table><tr><th>day</th><th class="n">buyers</th><th class="n">new buyers</th>'
             '<th class="n">payments</th><th class="n">USDC</th></tr>%s</table></div>'
             % "".join('<tr><td class="mono">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                       '<td class="n">%s</td></tr>' % (d_(x["date"]), n_(x["buyers"]), n_(x["new_buyers"]),
                                                       n_(x["payments"]), usd_(x["usdc"])) for x in w["by_day"]))
    p.append('<p class="muted">New buyers: first seen in the window that day. Every buyer on the first day is new to '
             "the window, since it holds nothing before.</p>")

    p.append("<%s>Came back</%s>" % (K, K))
    p.append("<p><b>%s of %s buyers</b> paid on 2 or more days of %s (%s).</p>"
             % (n_(cb["buyers"]), n_(cb["of"]), span, pct_(cb["rate_pct"])))
    if cb["loyal"]:
        p.append('<div class="tw"><table><tr><th>buyer wallet</th><th class="n">days</th><th>first</th><th>last</th>'
                 '<th class="n">payments</th><th class="n">USDC</th></tr>%s</table></div>'
                 % "".join('<tr><td class="w">%s</td><td class="n">%s</td><td class="mono">%s</td><td class="mono">%s</td>'
                           '<td class="n">%s</td><td class="n">%s</td></tr>'
                           % (esc(x["wallet"]), n_(x["days"]), d_(x["first"]), d_(x["last"]), n_(x["payments"]),
                              usd_(x["usdc"])) for x in cb["loyal"]))
        p.append(_more(cb, "loyal"))

    halves = lost["dates"]
    if halves["first_half"]:
        p.append("<%s>Buyers lost, and where they went</%s>" % (K, K))
        p.append("<p><b>%s of %s buyers</b> paid only in the first half (%s) and not in the second (%s).</p>"
                 % (n_(lost["buyers"]), n_(lost["of"]), days_(halves["first_half"]), days_(halves["second_half"])))
        if lost["left_for"]:
            p.append('<div class="tw"><table><tr><th>left for</th><th class="n">buyers</th></tr>%s</table></div>'
                     % "".join('<tr><td class="h">%s</td><td class="n">%s</td></tr>' % (seller_(x), n_(x["buyers"]))
                               for x in lost["left_for"]))
            p.append(_more(lost, "left_for"))
        if lost["list"]:
            p.append('<div class="tw"><table><tr><th>lost buyer</th><th class="n">payments</th><th class="n">USDC</th>'
                     '<th>last paid</th><th>went to</th></tr>%s</table></div>' % "".join(
                         '<tr><td class="w">%s</td><td class="n">%s</td><td class="n">%s</td><td class="mono">%s</td>'
                         "<td>%s</td></tr>"
                         % (esc(x["wallet"]), n_(x["payments"]), usd_(x["usdc"]), d_(x["last_paid"]),
                            '<span class="muted">a busy wallet: left out</span>' if x["busy"] else
                            (", ".join(seller_(t) for t in x["went_to"]) +
                             (" and %d more" % (x["went_to_total"] - len(x["went_to"]))
                              if x["went_to_total"] > len(x["went_to"]) else "")) or '<span class="muted">no new seller</span>')
                         for x in lost["list"]))
            p.append(_more(lost, "list"))

        p.append("<%s>Where new buyers came from</%s>" % (K, K))
        p.append("<p><b>%s of %s buyers</b> paid only in the second half (%s).</p>"
                 % (n_(arr["buyers"]), n_(arr["of"]), days_(halves["second_half"])))
        if arr["came_from"]:
            p.append('<div class="tw"><table><tr><th>came from</th><th class="n">buyers</th></tr>%s</table></div>'
                     % "".join('<tr><td class="h">%s</td><td class="n">%s</td></tr>' % (seller_(x), n_(x["buyers"]))
                               for x in arr["came_from"]))
            p.append(_more(arr, "came_from"))
        else:
            p.append('<p class="muted">None of them had paid another seller only in the first half.</p>')
        busy = lost["busy_buyers_left_out"], arr["busy_buyers_left_out"]
        if any(b not in (0, "0") for b in busy):
            p.append('<p class="muted">Busy wallets (each paid more than %d sellers) are counted but not followed: %s '
                     "lost, %s arrived.</p>" % (relationships.BUSY, n_(busy[0]), n_(busy[1])))

    al = w["bought_alongside"]
    p.append("<%s>Bought alongside</%s>" % (K, K))
    if al["sellers"]:
        p.append('<div class="tw"><table><tr><th>seller</th><th class="n">shared buyers</th><th class="n">share of its '
                 'buyers</th></tr>%s</table></div>'
                 % "".join('<tr><td class="h">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
                           % (seller_(x), n_(x["shared_buyers"]), pct_(x["share_pct"])) for x in al["sellers"]))
        p.append(_more(al, "sellers"))
    else:
        p.append('<p class="muted">No other seller shares a buyer with this wallet in the window.</p>')

    e = w["early_buyers"]
    if e:
        p.append("<%s>Early buyers</%s>" % (K, K))
        p.append("<p><b>%s wallets</b> paid it on %s, before its daily buyers went from %s on the first day to %s on "
                 "the last.</p>" % (n_(e["wallets"]), esc(" and ".join(atlas_style.short_date(d) for d in e["days"])),
                                    n_(e["first_day_buyers"]), n_(e["last_day_buyers"])))
        p.append('<div class="tw"><table><tr><th>early buyer</th><th>first</th><th class="n">days</th>'
                 '<th class="n">payments</th><th class="n">USDC</th></tr>%s</table></div>'
                 % "".join('<tr><td class="w">%s</td><td class="mono">%s</td><td class="n">%s</td><td class="n">%s</td>'
                           '<td class="n">%s</td></tr>' % (esc(x["wallet"]), d_(x["first"]), n_(x["days"]),
                                                           n_(x["payments"]), usd_(x["usdc"])) for x in e["list"]))
        p.append(_more(e, "list"))

    rv = w["rivals"]["side_by_side"]
    p.append("<%s>Closest rivals, side by side</%s>" % (K, K))
    if len(rv) > 1:
        p.append('<p class="muted">The %d sellers sharing the most buyers with this wallet, %s.</p>' % (len(rv) - 1, span))
        p.append('<div class="tw"><table><tr><th>seller</th><th class="n">shared buyers</th><th class="n">buyers</th>'
                 '<th class="n">came back</th><th class="n">payments</th><th class="n">USDC</th><th class="n">days paid</th>'
                 "</tr>%s</table></div>"
                 % "".join('<tr%s><td class="h">%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td>'
                           '<td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
                           % (' class="this"' if x["this"] else "", "this wallet" if x["this"] else seller_(x),
                              "—" if x["this"] else n_(x["shared_buyers"]), n_(x["buyers"]),
                              pct_(x["came_back_rate_pct"]), n_(x["payments"]), usd_(x["usdc"]), n_(x["days_paid"]))
                           for x in rv))
    else:
        p.append('<p class="muted">No other seller shares a buyer with this wallet in the window.</p>')
    p.append("</section>")
    return "".join(q for q in p if q)


PAGE_HEAD = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title><meta name="robots" content="noindex">
<meta name="color-scheme" content="light">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="%(fonts)s">
<style>%(css)s</style>
<header class="site"><div class="hbar"><span class="brand">%(logo)s%(lockup)s</span>
<span class="netchips"><span class="chip-sm">x402</span><span class="chip-sm">Base</span></span>
<span class="chip-sm">%(product)s · %(name)s</span></div></header>
"""


def html(body):
    """The whole report as one printable page, in the Atlas look (atlas_style.CSS, inlined)."""
    win, reg = body["window"], body["registry"]
    ws = body["wallets"]
    p = [PAGE_HEAD % {"title": esc("%s · %s · %s to %s · %s" % (NAME, atlas_style.unsay(body["host"]), win["from"],
                                                               win["to"], market.BRAND)),
                      "fonts": atlas_style.FONTS.replace("&", "&amp;"), "css": atlas_style.CSS, "logo": atlas_style.LOGO,
                      "lockup": atlas_style.LOCKUP, "product": esc(PRODUCT), "name": esc(NAME)}]
    p.append('<main id="main" class="rpt"><p class="eyebrow">%s · x402 payments on Base</p><h1>%s</h1>'
             % (esc(NAME), said(body["host"])))
    if reg.get("sells"):
        p.append('<p class="sells">%s</p>' % said(reg["sells"]))
    p.append('<p class="dateline">Window %s – %s · %s days · registry as of %s</p>'
             % (esc(atlas_style.long_date(win["from"])), esc(atlas_style.long_date(win["to"])), n_(win["days"]),
                esc(atlas_style.long_date(body["as_of"]))))
    p.append("<p>This host is paid into <b>%s</b> that %s paid over x402 in the window%s. %s Buyer wallets are shown in "
             "full: this is your own customer list, read from a public chain. A wallet is not an agent, and nothing here "
             "says who holds or runs one.</p>"
             % ("%d wallet%s" % (len(ws), "s" if len(ws) != 1 else ""), "was" if len(ws) == 1 else "were",
                " (and %d more that were not)" % len(body["unpaid_wallets"]) if body["unpaid_wallets"] else "",
                "Each is read on its own below." if len(ws) > 1 else "It is read below."))
    if body.get("incomplete"):
        p.append('<p class="muted">Part of the window could not be read, so these figures may be short: %s.</p>'
                 % esc("; ".join(body.get("problems") or [])[:300]))
    if len(ws) > 1:
        p.append('<nav class="box" aria-label="Wallets"><p style="margin:0">%s</p></nav>' % " · ".join(
            '<a href="#w-%s"><code>%s</code></a> %s buyers' % (esc(w["wallet"]), esc(w["wallet"][:6] + "…" + w["wallet"][-4:]),
                                                               n_(w["summary"]["buyers"])) for w in ws))
    for w in ws:
        p.append(wallet_html(w))
    p.append("<h2>How to read this report</h2><dl class=\"kv\">%s</dl>"
             % "".join("<dt>%s</dt><dd>%s</dd>" % (esc(k.replace("_", " ")), esc(v)) for k, v in body["means"].items()))
    p.append('<h3 style="margin-top:28px">What changed: the rules</h3><ul class="cav">%s</ul>'
             % "".join("<li>%s</li>" % esc(r["when"][:1].upper() + r["when"][1:]) for r in body["rules"]))
    p.append('<h3 style="margin-top:28px">What the numbers are, and are not</h3><ul class="cav">%s</ul>'
             % "".join("<li>%s.</li>" % esc(c[:1].upper() + c[1:]) for c in body["caveats"]))
    p.append("</main>")
    p.append('<footer class="site"><div class="small"><p>%s · %s. %s is an %s product, made by Aušrinė, an AI agent, '
             "openly and by design. Public registry and chain data only. Questions: %s · %s</p></div></footer></html>\n"
             % (esc(NAME), esc(body["source"][:1].upper() + body["source"][1:]), esc(market.PRODUCT), esc(market.COMPANY),
                esc(EMAIL), esc(pro.ATLAS + "/sellers/")))
    return "".join(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("host")
    ap.add_argument("--store", required=True, help="a folder of market-<date>.json snapshots (radar/)")
    ap.add_argument("--flows-dir", required=True, help="a folder of flows-<date>.json (flows/)")
    ap.add_argument("--today", default=None, help="the day to sell on, YYYY-MM-DD (default: today)")
    ap.add_argument("--html", default=None, help="write the one-page report here")
    ap.add_argument("--json", default=None, help="write the JSON report here")
    a = ap.parse_args()
    who_service.radar.STORE = a.store
    who_service.CHAIN_STORE = a.flows_dir
    t0 = time.perf_counter()
    code, body = report(a.host, date.fromisoformat(a.today) if a.today else None)
    took = time.perf_counter() - t0
    if code != 200:
        print(json.dumps(body, indent=1))
        sys.exit(1)
    t1 = time.perf_counter()
    page = html(body)
    took_html = time.perf_counter() - t1
    if a.html:
        with open(a.html, "w") as f:
            f.write(page)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(body, f, indent=1)
    w = body["window"]
    print("%s: window %s to %s (%d days), as of %s · report in %.3f s, page in %.3f s"
          % (body["host"], w["from"], w["to"], w["days"], body["as_of"], took, took_html))
    for x in body["wallets"]:
        s, cb = x["summary"], x["came_back"]
        print("-- %s (%s): %s buyers, %s payments, $%.2f; came back %s of %s (%g%%); lost %d, arrived %d"
              % (x["wallet"], ", ".join(x["hosts"][:3]), "{:,}".format(s["buyers"]), "{:,}".format(s["payments"]),
                 s["usdc"], cb["buyers"], cb["of"], cb["rate_pct"], x["lost"]["buyers"], x["arrived"]["buyers"]))
        for c in x["what_changed"]:
            print("   · " + c["say"])


if __name__ == "__main__":
    main()
