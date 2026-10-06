#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f04f064). Edit it there, not here.
"""pro.py — Atlas Pro: the Atlas's record as working data, for a license key.

The Atlas is a public record: every seller's basic card is free, and the full record,
every buyer wallet and every operator, is paid (tiers.py, since 2026-10-05). Pro sells
that record as data a program can use: the newest window, whole, in four files.

    GET /pro                       free: what Pro holds and how to call it
    GET /pro/export/sellers.csv    every seller in the newest snapshot, with the chain beside it
    GET /pro/export/buyers.csv     every wallet that made an x402 payment in the window
    GET /pro/export/operators.csv  every wallet group: hosts paid into one wallet
    GET /pro/export/day.json       all three and the window's totals, in one file

The exports are built from exactly what the `who` answers are built from: the snapshot
set who_service.capture() checks (the same freshness rule, the same refusals), and the
newest classified rollup in who_service.CHAIN_STORE. Nothing here reads anything else.

Two doors to the same four files, the same bytes for the same day:

    GET /pro/export/<file>         a Polar license key in X-Atlas-Key, $49 a month, every file
    GET /x402/export/<file>        no key, no account: paid per file over x402 when fetched,
                                   $0.25 a CSV, $1.00 day.json (X402_PRICES; sell-who.py prices it)

The first gate is a Polar license key in the header X-Atlas-Key, checked against Polar's
public validation endpoint, which needs no access token: only the key and the
organization id, from POLAR_ORG_ID. A good answer is kept ten minutes. The key is
never logged, never echoed, never stored: the caches hold its sha256.

One gate, two doors (Gate.check(key, door)). A key opens a door when its Polar benefit is
one that door accepts:

    door "pro"      the Pro exports and /pro/watch   POLAR_BENEFIT_ID (Atlas Pro) only
    door "sellers"  the seller reports               POLAR_BENEFIT_ID or POLAR_SELLERS_BENEFIT_ID

so an Atlas for Sellers key never opens a Pro file, and a Pro key opens both. A door with
no benefit configured answers 503 (pro_not_configured, sellers_not_configured), never billed.

No web framework here: sell-who.py puts this behind routes. Standard library only.
"""

import collections
import csv
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import who_service  # noqa: E402  (also puts the mandala folder on the path)
import market  # noqa: E402  (the category of a seller, the same words the Atlas uses)
import operator_pages  # noqa: E402  (a group's page address and name, the same as the Atlas's /o/)
import buyer_pages  # noqa: E402  (what a wallet bought, counted as the buyer pages count it)

PRICE = "$49 a month"
HEADER = "X-Atlas-Key"
POLAR_VALIDATE = "https://api.polar.sh/v1/customer-portal/license-keys/validate"
GOOD_FOR = 600              # seconds a good answer from Polar is trusted
PER_HOUR = 60               # export calls one key may make in an hour
POLAR_PER_MINUTE = 30       # validations this host asks Polar for in a minute, all keys together
ATLAS = (os.environ.get("ATLAS_URL") or "http://atlas.infoharmoni.com").rstrip("/")

SELLER_COLUMNS = [
    "host", "category", "sells", "price_min", "price_max", "endpoints", "chains",
    "calls_30d_self_reported", "payers_30d_self_reported",
    "x402_payments", "x402_usdc", "usdc_other_means", "payer_wallets", "top3_share_pct",
    "concentration", "top_payer_wallets", "operator_group", "operator_hosts"]
BUYER_COLUMNS = [
    "wallet", "chain", "x402_payments", "x402_usdc", "usdc_other_means", "sellers_paid_x402",
    "agent", "categories", "top_sellers"]
OPERATOR_COLUMNS = [
    "group", "name", "hosts", "host_list", "wallets", "paid_hosts", "x402_payments", "x402_usdc",
    "usdc_other_means", "calls_30d_self_reported", "top_payer_wallets"]

# The second door: one file, paid once, over x402. No key, no account, no subscription.
X402_PATH = "/x402/export/"
X402_PRICES = {"sellers.csv": "$0.25", "buyers.csv": "$0.25", "operators.csv": "$0.25", "day.json": "$1.00"}

EXPORTS = {
    "sellers.csv": ("every seller in the newest registry snapshot; the on-chain columns are the window's "
                    "x402 payments on Base, blank when the window is not loaded", SELLER_COLUMNS),
    "buyers.csv": ("every wallet that made an x402 payment to a seller in the window; agent is yes when "
                   "its x402 payments reached three or more sellers", BUYER_COLUMNS),
    "operators.csv": ("every group of hosts paid into one wallet: usually one operator, sometimes a "
                      "platform collecting for several", OPERATOR_COLUMNS),
    "day.json": ("all three as JSON, with the window's totals, dates and caveats", None),
}

CAVEATS = who_service.CAVEATS + [
    "the self-reported columns (calls_30d_self_reported, payers_30d_self_reported) are the registry's own "
    "counts; the x402 columns are read off Base. The two are never blended",
    "lists inside a CSV cell are separated by ';'; a wallet with its count is written wallet:count",
]


# --- the window ---------------------------------------------------------------------------

def newest_rollup(now, max_age_days):
    """(name, rollup) for the newest classified rollup in CHAIN_STORE that is fresh by the
    same rule as the snapshots, or (None, None). The whole rollup: buyers and groups too."""
    store = who_service.CHAIN_STORE
    if not store or not os.path.isdir(store):
        return None, None
    names = sorted(f for f in os.listdir(store) if re.match(r"^whales-\d{4}-\d{2}-\d{2}\.json$", f))
    for name in reversed(names):
        try:
            path = os.path.join(store, name)
            before = os.stat(path)
            with open(path) as f:
                d = json.load(f)
            after = os.stat(path)
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                return None, None               # replaced while read: nothing from a half-known file
            d["_fid"] = (after.st_size, after.st_mtime_ns, after.st_ino)   # the identity of the bytes read
            if not (d.get("classified") and isinstance(d.get("sellers"), list) and isinstance(d.get("buyers"), list)):
                continue
            as_of = date.fromisoformat(d.get("as_of") or name[7:17])
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        age = (now - as_of).days
        if 0 <= age <= max_age_days:
            return name, d
        return None, None               # the newest good rollup is stale or future-dated: none is sold
    return None, None


def _cell(v):
    """One CSV cell. Text a stranger wrote can start with = + - @ and become a formula in a
    spreadsheet; such a cell is given a leading apostrophe. Numbers pass as they are."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def to_csv(columns, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in columns])
    return buf.getvalue()


def _wallets(top):
    return ";".join("%s:%d" % (t["wallet"], t["payments"]) for t in (top or []) if t.get("wallet"))


def operator_groups(rollup, with_group=False):
    """[(slug, hosts)] for every group of two or more hosts in a rollup, slugged by the same
    rule as the /o/ pages. with_group adds the rollup's group dict as a third item."""
    out, seen = [], set()
    for g in (rollup or {}).get("groups") or []:
        hosts = [h for h in g.get("hosts") or [] if isinstance(h, str)]
        if len(hosts) < 2:
            continue
        base = operator_pages.group_slug(hosts)
        sl = base if base not in seen else "%s-%s" % (base, g.get("id"))   # the same rule as the /o/ pages
        seen.add(sl)
        out.append((sl, hosts, g) if with_group else (sl, hosts))
    return out


def tables(A, rollup):
    """(sellers, buyers, operators) as lists of dicts, from one snapshot's sellers A and
    one rollup (or None). Pure."""
    S = {s["host"]: s for s in (rollup or {}).get("sellers") or [] if isinstance(s, dict) and s.get("host")}
    group_of = {}
    operators = []
    for sl, hosts, g in operator_groups(rollup, with_group=True):
        for h in hosts:
            group_of[h] = (sl, len(hosts))
        facts = operator_pages.group_facts({"hosts": hosts, "wallets": g.get("wallets")}, {"sellers": S}, A)
        operators.append({
            "group": sl, "name": operator_pages.group_name(hosts, {"sellers": S}), "hosts": len(hosts),
            "host_list": ";".join(sorted(hosts)), "wallets": g.get("wallets"), "paid_hosts": facts["paid_hosts"],
            "x402_payments": facts["x402"], "x402_usdc": round(facts["usdc"], 2),
            "usdc_other_means": round(facts["other"], 2), "calls_30d_self_reported": facts["calls30"],
            "top_payer_wallets": ";".join("%s:%d" % (w, n) for w, n in facts["top_payers"])})
    operators.sort(key=lambda r: (-r["x402_payments"], -r["hosts"], r["group"]))

    sellers = []
    for host, me in A.items():
        s = S.get(host)
        on = rollup is not None
        x = (s or {}).get("on_chain_payments_x402") or 0
        g = group_of.get(host)
        sellers.append({
            "host": host, "category": market.cat((me.get("sells") or "") + " " + host)[0], "sells": me.get("sells"),
            "price_min": me.get("price_min"), "price_max": me.get("price_max"), "endpoints": me.get("endpoints"),
            "chains": ";".join(me.get("chains") or []),
            "calls_30d_self_reported": me.get("calls"), "payers_30d_self_reported": me.get("payers"),
            "x402_payments": x if on else None,
            "x402_usdc": round((s or {}).get("on_chain_usdc_x402") or 0.0, 2) if on else None,
            "usdc_other_means": round(max(((s or {}).get("on_chain_usdc") or 0.0) - ((s or {}).get("on_chain_usdc_x402") or 0.0), 0.0), 2)
            if on else None,
            "payer_wallets": ((s or {}).get("x402_payer_wallets") or 0) if on else None,
            "top3_share_pct": (s or {}).get("x402_top3_share") if x else None,
            "concentration": (s or {}).get("concentration") if x else None,
            "top_payer_wallets": _wallets((s or {}).get("x402_top_payers")) if x else None,
            "operator_group": g[0] if g else None, "operator_hosts": g[1] if g else (1 if on else None)})
    sellers.sort(key=lambda r: (-(r["x402_payments"] or 0), -(r["calls_30d_self_reported"] or 0), r["host"]))

    buyers = []
    agents = {b.get("wallet") for b in (rollup or {}).get("agents") or [] if isinstance(b, dict)}
    for b in (rollup or {}).get("buyers") or []:
        if not isinstance(b, dict) or not b.get("payments_x402"):
            continue
        cats = buyer_pages.bought(b.get("sellers") or [], b)      # x402 purchases only, as the buyer pages say
        paid = sorted((s for s in b.get("sellers") or [] if (s.get("payments_x402") or 0) > 0),
                      key=lambda s: (-(s.get("payments_x402") or 0), s.get("host") or ""))
        buyers.append({
            "wallet": b.get("wallet"), "chain": b.get("chain") or "Base", "x402_payments": b["payments_x402"],
            "x402_usdc": round(b.get("usdc_x402") or 0.0, 2),
            "usdc_other_means": round(max((b.get("usdc") or 0.0) - (b.get("usdc_x402") or 0.0), 0.0), 2),
            "sellers_paid_x402": b.get("sellers_paid_x402") or 0,
            "agent": b.get("wallet") in agents or (b.get("sellers_paid_x402") or 0) >= 3,
            "categories": ";".join(cats), "top_sellers": ";".join("%s:%d" % (s["host"], s["payments_x402"]) for s in paid if s.get("host"))})
    buyers.sort(key=lambda r: (not r["agent"], -r["x402_payments"], -r["x402_usdc"], r["wallet"] or ""))
    return sellers, buyers, operators


_lock = threading.Lock()
_built = {}          # (set key, rollup name) -> {export name: bytes}; one version at a time


def exports(now=None, max_age_days=who_service.MAX_AGE_DAYS):
    """(status, files_or_refusal). 200 carries {name: bytes} for every export; anything else
    is a refusal body, the same refusals the paid `who` answer gives, plus 503
    on_chain_not_loaded for the two exports that are nothing without the chain."""
    now = now or date.today()
    set_key, loaded, newest, refusal = who_service.fresh_capture(now, max_age_days)
    if refusal:
        code, body = refusal
        body = dict(body)
        body.pop("charged", None)
        return code, body
    name, rollup = newest_rollup(now, max_age_days)
    fid = (rollup or {}).get("_fid")
    key = (set_key, name, fid)                # a same-date rollup replaced with new contents is a new key
    with _lock:
        hit = _built.get(key)
    if hit:
        return (200, hit) if _unchanged(set_key) and _file_id(name) == fid else _CHANGED
    A = loaded[-1]["sellers"]
    sellers, buyers, operators = tables(A, rollup)
    window = {"available": rollup is not None, "chain": "Base"}
    if rollup is not None:
        window.update({"as_of": rollup.get("as_of"), "dates": rollup.get("dates") or [], "hours": rollup.get("hours"),
                       "totals": rollup.get("totals") or {}})
    else:
        window["say"] = "no fresh on-chain window is loaded on this host; the x402 columns are blank"
    day = {"ok": True, "as_of": newest.isoformat(), "sellers_in_market": len(A), "on_chain": window,
           "columns": {"sellers": SELLER_COLUMNS, "buyers": BUYER_COLUMNS, "operators": OPERATOR_COLUMNS},
           "sellers": sellers, "buyers": buyers, "operators": operators, "caveats": CAVEATS,
           "source": "x402 discovery registry, daily snapshots; on-chain from the Atlas's daily Base pull"}
    files = {"sellers.csv": to_csv(SELLER_COLUMNS, sellers).encode(),
             "buyers.csv": to_csv(BUYER_COLUMNS, buyers).encode() if rollup is not None else None,
             "operators.csv": to_csv(OPERATOR_COLUMNS, operators).encode() if rollup is not None else None,
             "day.json": json.dumps(day, separators=(",", ":")).encode(),
             "_as_of": newest.isoformat(), "_window": (rollup or {}).get("as_of")}
    if not _unchanged(set_key) or _file_id(name) != fid:   # the store changed under us: nothing from a mixed set
        return _CHANGED
    with _lock:
        _built.clear()
        _built[key] = files
    return 200, files


_CHANGED = (503, {"ok": False, "error": "snapshot_changed",
                  "say": "the market snapshots changed while the export was being prepared; ask again"})


def _file_id(name):
    """(size, mtime_ns) of a rollup in CHAIN_STORE, or None."""
    if not name or not who_service.CHAIN_STORE:
        return None
    try:
        st = os.stat(os.path.join(who_service.CHAIN_STORE, name))
        return (st.st_size, st.st_mtime_ns, st.st_ino)
    except OSError:
        return None


def _unchanged(set_key):
    """True when the store still holds exactly the captured set: checked before every export served."""
    try:
        return who_service._set_keys() == set_key
    except who_service.SetChanged:
        return False


def describe():
    """GET /pro: what Pro holds and the two ways to pay for it. Free, no key, no payment."""
    base = who_service_public_url()
    return {
        "ok": True, "name": market.BRAND_SHORT + " Pro", "price": PRICE,
        "what": "The " + market.BRAND + "'s newest window of the x402 market on Base, as working data: every seller, every paying wallet and every "
                "wallet group, with the on-chain facts beside the registry's own counts. Every seller's basic card on the "
                "Atlas is free; Pro is the full record, as files a program can use.",
        "ways_to_pay": [
            "a subscription, %s: a Polar license key in the %s header opens every file at %s<file>"
            % (PRICE, HEADER, "/pro/export/"),
            "per file, over x402: no key and no account, each file is paid for when it is fetched at %s<file>; "
            "%s" % (X402_PATH, ", ".join("%s %s" % (p, n) for n, p in X402_PRICES.items()))],
        "auth": {"header": HEADER, "value": "the license key Polar sends after you subscribe",
                 "refused": "401 when the key is missing, unknown, revoked or expired",
                 "limit": "%d export calls per key per hour; 429 beyond it" % PER_HOUR},
        "x402": {"prices": {X402_PATH + n: p for n, p in X402_PRICES.items()},
                 "how": "GET the file; the 402 answer names the price, the network and the address to pay in USDC; "
                        "sign and send again with the payment header. The same bytes the license key gets for the same day",
                 "refused": "an unknown file is 404, and a stale snapshot or a missing on-chain window is 503, "
                            "before any payment is asked; nothing is charged for a refusal"},
        "exports": {"/pro/export/" + n: {"what": what, "columns": cols, "x402": X402_PATH + n, "x402_price": X402_PRICES[n]}
                    for n, (what, cols) in EXPORTS.items()},
        "example": "curl -H '%s: YOUR-KEY' %s/pro/export/sellers.csv" % (HEADER, base),
        "example_x402": "an x402 client, e.g. GET %s%ssellers.csv, pays %s and receives the file"
                        % (base, X402_PATH, X402_PRICES["sellers.csv"]),
        "fresh": "rebuilt when the daily scan lands; refused (503) when the newest snapshot is more than %d days old"
                 % who_service.MAX_AGE_DAYS,
        "subscribe": ATLAS + "/pro.html",
        "seller_reports": "a Pro key also opens the seller report (Your buyers) at /sellers/report/<host>; GET /sellers",
        "caveats": CAVEATS}


def who_service_public_url():
    return (os.environ.get("SELL_WHO_PUBLIC_URL") or "https://ausrine-who.onrender.com").rstrip("/")


# --- the gate ------------------------------------------------------------------------------

KEY_SHAPE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
PRO, SELLERS = "pro", "sellers"          # the doors a key can open
FOR = {PRO: "Atlas Pro", SELLERS: "seller reports"}


def polar_validate(key, org_id, benefit_id=None, timeout=10):
    """(http status, parsed body or None) from Polar's public license key validation. No
    access token: the endpoint takes the key and the organization id. The key travels in
    the body over https, never in a URL, and no error message here can carry it."""
    body = {"key": key, "organization_id": org_id}   # the benefit is checked in Polar's answer, not sent
    req = urllib.request.Request(POLAR_VALIDATE, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": "ausrine-atlas-pro/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read(64 * 1024) or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


class Gate:
    """Who may take an export or a seller report. check(key, door) -> (status, message): 200 lets
    the request through; 401 missing/unknown/revoked/expired, or a key for another door; 429 over
    the per-key limit; 503 when this host cannot ask Polar (the door not configured, Polar
    unreachable, too many new keys at once). Only a key's sha256 is ever held, with the benefit
    Polar named for it."""

    def __init__(self, org_id, benefit_id=None, validate=polar_validate, clock=time.time,
                 good_for=GOOD_FOR, per_hour=PER_HOUR, polar_per_minute=POLAR_PER_MINUTE, sellers_benefit_id=None):
        self.org_id, self.benefit_id, self.validate, self.clock = org_id, benefit_id, validate, clock
        self.sellers_benefit_id = sellers_benefit_id
        self.good_for, self.per_hour, self.polar_per_minute = good_for, per_hour, polar_per_minute
        self.lock = threading.Lock()
        self.good = {}                                  # sha256 -> (trusted until, benefit id)
        self.used = {}                                  # sha256 -> deque of call times, last hour
        self.asked = collections.deque()                # times this host asked Polar, last minute

    @property
    def enabled(self):
        return bool(self.org_id and self.benefit_id)

    @property
    def sellers_enabled(self):
        return bool(self.org_id and (self.benefit_id or self.sellers_benefit_id))

    def opens(self, door):
        """The benefits whose keys open this door."""
        return {b for b in ((self.benefit_id, self.sellers_benefit_id) if door == SELLERS else (self.benefit_id,)) if b}

    def _refused(self, why, door=PRO):
        return 401, {"ok": False, "error": "key_refused", "say": why,
                     "subscribe": ATLAS + ("/sellers/" if door == SELLERS else "/pro.html"), "header": HEADER}

    def check(self, key, door=PRO):
        if not key:
            return self._refused("no license key: send it in the %s header" % HEADER, door)
        if not KEY_SHAPE.match(key):
            return self._refused("this license key is not one we know", door)
        if door == SELLERS and not self.sellers_enabled:
            return 503, {"ok": False, "error": "sellers_not_configured",
                         "say": "seller reports by subscription are not switched on on this host yet; the same report "
                                "is sold per call over x402"}
        if door != SELLERS and not self.enabled:      # both ids, or a key for another product could open Pro
            return 503, {"ok": False, "error": "pro_not_configured",
                         "say": "Atlas Pro is not switched on on this host yet"}
        h = hashlib.sha256(key.encode()).hexdigest()
        now = self.clock()
        with self.lock:
            until, benefit = self.good.get(h, (0, None))
            trusted = until > now
            if not trusted:
                while self.asked and self.asked[0] <= now - 60:
                    self.asked.popleft()
                if len(self.asked) >= self.polar_per_minute:
                    return 503, {"ok": False, "error": "busy", "say": "too many new keys at once; try again in a minute"}
                self.asked.append(now)
        if not trusted:
            status, body = self.validate(key, self.org_id, self.benefit_id)
            verdict = self._verdict(status, body, now, door)
            if verdict is not None:
                return verdict
            benefit = body.get("benefit_id")
            until = now + self.good_for
            exp = _when((body or {}).get("expires_at"))
            if exp is not None:
                until = min(until, exp)
            with self.lock:
                if len(self.good) > 10000:
                    self.good = {k: v for k, v in self.good.items() if v[0] > now}
                self.good[h] = (until, benefit)
        if benefit not in self.opens(door):             # a good key, for the other door
            return self._refused("this license key is not for %s" % FOR[door], door)
        with self.lock:
            q = self.used.setdefault(h, collections.deque())
            while q and q[0] <= now - 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                return 429, {"ok": False, "error": "rate_limited", "retry_after": int(q[0] + 3600 - now) + 1,
                             "say": "%d %s calls an hour per key; this key has used them"
                                    % (self.per_hour, "report" if door == SELLERS else "export")}
            q.append(now)
            if len(self.used) > 10000:
                self.used = {k: v for k, v in self.used.items() if v and v[-1] > now - 3600}
        return 200, None

    def _verdict(self, status, body, now, door=PRO):
        """None when Polar's answer lets the key in (for one of this host's benefits), else the refusal."""
        if status is None or (status >= 500 or status == 429):
            return 503, {"ok": False, "error": "license_check_unavailable",
                         "say": "the license service could not be reached; try again in a minute"}
        if status != 200 or not isinstance(body, dict):
            return self._refused("this license key is not one we know", door)
        if body.get("organization_id") != self.org_id:
            return self._refused("this license key is not one we know", door)
        if body.get("benefit_id") not in self.opens(SELLERS):     # a benefit this host sells nothing for
            return self._refused("this license key is not for %s" % FOR[door], door)
        st = body.get("status")
        if st in ("revoked", "disabled"):
            return self._refused("this license key has been revoked", door)
        if st != "granted":
            return self._refused("this license key is not one we know", door)
        exp = _when(body.get("expires_at"))
        if exp is not None and exp <= now:
            return self._refused("this license key has expired", door)
        return None


def _when(s):
    """An ISO timestamp from Polar as epoch seconds, or None."""
    if not s or not isinstance(s, str):
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp()
