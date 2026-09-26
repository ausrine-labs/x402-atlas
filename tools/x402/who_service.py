#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 116e747). Edit it there, not here.
"""who_service.py — what the paid `who` endpoint answers, and what it refuses.

No web framework, no payment library, no network: this is the part that
decides, and it is the part the tests hold. `sell-who.py` puts it behind x402.

Four refusals, and none of them is ever billed (see sell-who.py for how):

    400  the target is not a hostname or a wallet address
    503  there is no snapshot, or the newest one is older than the limit
    404  the seller is not in the registry snapshot
    300  the name matches several sellers; the candidates are listed

Only a 200 — a real report card, stamped with the snapshot date — is sold.
"""

import json
import os
import re
import sys
import threading
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import radar  # noqa: E402  (the engine; who_data() is the single source of the report card)

# A target reaches the engine only if it looks like what the registry holds.
# Checked against every host and wallet in a real snapshot: none is rejected.
# A leading "-" can never pass, so the target can never be read as an option.
HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?"
                  r"(\.[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?)*(:\d{1,5})?$")
EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

MAX_AGE_DAYS = 2   # the daily scan may miss one morning; two and the answer is rotten

CAVEATS = [
    "a wallet is not an agent: one wallet may serve many agents, one agent many wallets",
    "payers are endpoint counts summed: a wallet paying two endpoints counts twice",
    "money is calls times list price, an estimate, not settled revenue",
    "movement is the change in a rolling 30-day window between stored days, not a daily count",
    "the source is one registry (x402 discovery); absence from it is not absence from the market",
    "on_chain is read off Base: x402 payments are transfers a facilitator settled on a buyer's signature; "
    "money that reached the same wallet by ordinary transfer is counted apart and is not a call",
    "concentration is a fact about a seller's payers, never a verdict on the seller: 'one payer' means "
    "every x402 payment in the window came from one wallet; 'concentrated' means ten or more payments "
    "with the busiest three wallets sending 80% or more",
    "hosts paid into one wallet are grouped: usually one operator, sometimes a platform collecting for several",
]

CHAIN_STORE = None      # a folder of whales-<date>.json (flows_handoff.fetch keeps it); None = not available
ON_CHAIN_MEANS = ("x402_payments were settled by a facilitator on a signed authorization, on Base, over the "
                  "window's hours; usdc_by_other_means reached the same wallets some other way and is not a call")


def newest_chain():
    """The newest classified whale rollup in CHAIN_STORE, keyed for answers, or (None, None)."""
    if not CHAIN_STORE or not os.path.isdir(CHAIN_STORE):
        return None, None
    names = sorted(f for f in os.listdir(CHAIN_STORE) if re.match(r"^whales-\d{4}-\d{2}-\d{2}\.json$", f))
    for name in reversed(names):
        try:
            with open(os.path.join(CHAIN_STORE, name)) as f:
                d = json.load(f)
            if d.get("classified") and isinstance(d.get("sellers"), list):
                return name, {"as_of": d.get("as_of"), "hours": d.get("hours"), "dates": d.get("dates") or [],
                              "sellers": {s["host"]: s for s in d["sellers"]}, "operators": d.get("operators") or {}}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None, None


def on_chain(host, chain):
    """What the chain says about one seller, for the paid answer. Never raises; never
    blocks an answer: when the window is not loaded it says so."""
    if not chain:
        return {"available": False, "say": "the on-chain window is not loaded on this host yet; the report card above stands"}
    op = chain["operators"].get(host)
    out = {"available": True, "as_of": chain["as_of"], "hours": chain["hours"], "dates": chain["dates"], "chain": "Base",
           "operator_hosts": op["hosts"] if op else 1, "operator_other_hosts": (op["others"] if op else [])[:12],
           "means": ON_CHAIN_MEANS}
    s = chain["sellers"].get(host)
    if not s or not s.get("on_chain_payments_x402"):
        out.update({"x402_payments": 0, "x402_usdc": 0.0,
                    "usdc_by_other_means": round((s or {}).get("on_chain_usdc", 0.0), 2),
                    "say": "no x402 payment reached this seller's wallets on Base in the window"})
        return out
    # a rollup from before the pull learned concentration lacks these fields; say so, sell the rest
    out.update({"x402_payments": s["on_chain_payments_x402"], "x402_usdc": s.get("on_chain_usdc_x402", 0.0),
                "payer_wallets": s.get("x402_payer_wallets"), "top3_share_pct": s.get("x402_top3_share"),
                "concentration": s.get("concentration"), "top_payers": s.get("x402_top_payers"),
                "usdc_by_other_means": round(s.get("on_chain_usdc", 0.0) - s.get("on_chain_usdc_x402", 0.0), 2)})
    if out["payer_wallets"] is None:
        out["say"] = "this rollup predates concentration; payer wallets and the busiest three are not known for it"
    return out


def valid_target(target):
    t = target or ""
    return bool(HOST.match(t.lower()) or EVM.match(t) or BASE58.match(t))


def newest_snapshot_date():
    """For /health only: the date in the newest snapshot's file name, or None. The serving
    path never uses a file name for a date; it uses the captured set (see answer())."""
    snaps = radar.snapshots()
    if not snaps:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", snaps[-1])
    return snapshot_handoff.parse_day(m.group(1)) if m else None


sys.path.insert(0, HERE)
import snapshot_handoff  # noqa: E402

_lock = threading.Lock()
_validated = {}      # file key -> reason or None
_parsed = {}         # file key -> parsed snapshot
_answers = {}        # (set key, target) -> (status, body without age_days)
MAX_CACHED = 2000
FLOOR = snapshot_handoff.FLOOR      # sellers a snapshot must hold; tests lower it
REPLAY = 8                          # files that contribute to one answer


class SetChanged(Exception):
    """A file that was listed is gone, or changed, before it could be captured."""


def _file_key(name):
    try:
        st = os.stat(os.path.join(radar.STORE, name))
    except OSError:
        raise SetChanged(name)
    return (radar.STORE, name, st.st_size, st.st_mtime_ns)


def _set_keys():
    """The identity of everything that would go into an answer right now."""
    return tuple(_file_key(n) for n in radar.snapshots()[-REPLAY:])


def capture(today=None):
    """Load and validate, as ONE set, every snapshot that contributes to an answer.
    Returns (set_key, loaded_snapshots_oldest_first, problem). A problem in any
    file, replay days included, means nothing is sold: the report sold must be
    built from exactly the bytes that were checked (Map Room, 2026-09-22)."""
    keys, loaded = [], []
    for name in radar.snapshots()[-REPLAY:]:
        key = _file_key(name)                      # SetChanged if it vanished since listing
        with _lock:
            why, parsed = _validated.get(key, "?"), _parsed.get(key)
        if why == "?" or parsed is None:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
            try:
                with open(os.path.join(radar.STORE, name), "rb") as f:
                    raw = f.read()
            except OSError:
                raise SetChanged(name)
            why = snapshot_handoff.check_snapshot(raw, m.group(1) if m else "", FLOOR, today)
            parsed = None if why else json.loads(raw)
            with _lock:
                if len(_validated) > 4 * REPLAY:
                    _validated.clear(); _parsed.clear()
                _validated[key] = why
                if parsed is not None:
                    _parsed[key] = parsed
        if why:
            return tuple(keys), None, "%s %s" % (name, why)
        keys.append(key); loaded.append(parsed)
    return tuple(keys), loaded, None


def with_age(status, body, today):
    """Every response carries age_days computed now from its own as_of. The cached
    body is never mutated; the caller gets a copy."""
    if status != 200:
        return status, body
    out = dict(body)
    out["age_days"] = (today - date.fromisoformat(out["as_of"])).days
    return status, out


def fresh_capture(now, max_age_days=MAX_AGE_DAYS):
    """(set_key, loaded, newest_date, None) for a set that may be sold today, or
    (None, None, None, (status, body)) with the refusal. Shared by the paid answer and
    the Pro exports, so both refuse the same sets for the same reasons."""
    def no(body):
        return None, None, None, (503, body)
    # The set is captured and validated BEFORE any freshness decision, and the newest
    # date, as_of and age are derived from that captured set and from nothing else.
    # A file name read before capture can belong to a file that is gone by the time
    # the set is read (Map Room's third pass, 2026-09-22): then the age was computed
    # from a file that was not in the set being sold.
    try:
        set_key, loaded, why = capture(now)
    except SetChanged:
        return no({"ok": False, "charged": False, "error": "snapshot_changed",
                   "say": "the market snapshots changed while the answer was being prepared; "
                          "ask again, nothing was charged"})
    if why:
        return no({"ok": False, "charged": False, "error": "invalid_snapshot",
                   "say": "a snapshot in the set failed validation (%s); nothing is sold from it and "
                          "nothing was charged" % why})
    if not loaded:
        return no({"ok": False, "charged": False, "error": "no_snapshot"})
    newest = snapshot_handoff.parse_day(loaded[-1].get("date"))
    if newest is None:
        return no({"ok": False, "charged": False, "error": "invalid_snapshot",
                   "say": "the newest captured snapshot has no usable date; nothing was charged"})
    age = (now - newest).days
    if age < 0:
        return no({"ok": False, "charged": False, "error": "future_snapshot",
                   "as_of": newest.isoformat(), "say": "the newest snapshot is dated in the future; "
                   "it will not be sold and nothing was charged"})
    if age > max_age_days:
        return no({"ok": False, "charged": False, "error": "stale_snapshot",
                   "as_of": newest.isoformat(), "age_days": age, "limit_days": max_age_days,
                   "say": "the newest market snapshot is too old to sell; nothing was charged"})
    return set_key, loaded, newest, None


def answer(target, today=None, max_age_days=MAX_AGE_DAYS):
    """(status, body). 200 is the only status that is sold."""
    if not valid_target(target):
        return 400, {"ok": False, "charged": False, "error": "invalid_target",
                     "expected": "a hostname (api.example.com) or a payTo wallet address"}
    now = today or date.today()
    set_key, loaded, newest, refusal = fresh_capture(now, max_age_days)
    if refusal:
        return refusal
    chain_name, chain = newest_chain()
    ckey = (set_key, chain_name, target.lower())
    with _lock:
        hit = _answers.get(ckey)
    if hit:
        return with_age(hit[0], hit[1], now)
    try:
        card = radar.who_data(target, loaded)
    except radar.Ambiguous as e:
        out = 300, {"ok": False, "charged": False, "ambiguous": target,
                    "candidates": e.candidates, "as_of": newest.isoformat(),
                    "say": "several sellers match; ask again with one of these, nothing was charged"}
    except (KeyError, TypeError, ValueError, AttributeError) as e:      # a broken row, not an absent seller
        return 503, {"ok": False, "charged": False, "error": "invalid_snapshot", "as_of": newest.isoformat(),
                     "say": "the snapshot could not be read for this seller (%s); nothing was charged"
                            % type(e).__name__}
    except LookupError:
        out = 404, {"ok": False, "charged": False, "target": target, "as_of": newest.isoformat(),
                    "say": "not found in the x402 discovery registry as of %s; absence from one "
                           "registry is not absence from the market" % newest.isoformat()}
    else:
        body = {"ok": True}
        body.update(card)
        body["on_chain"] = on_chain(card["host"], chain)
        body["caveats"] = CAVEATS
        body["source"] = "x402 discovery registry, daily snapshots; on_chain from the Atlas's daily Base pull"
        out = 200, body
    try:
        unchanged = _set_keys() == set_key
    except SetChanged:
        unchanged = False
    if not unchanged:                     # the store changed under us: sell nothing from a mixed set
        return 503, {"ok": False, "charged": False, "error": "snapshot_changed",
                     "say": "the market snapshots changed while the answer was being prepared; "
                            "ask again, nothing was charged"}
    with _lock:
        if len(_answers) >= MAX_CACHED or any(k[0] != set_key for k in list(_answers)[:1]):
            _answers.clear()
        _answers[ckey] = out
    return with_age(out[0], out[1], now)
