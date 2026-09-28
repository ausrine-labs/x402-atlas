#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""watch_service.py — what the two watch doors answer, and what they refuse, before any money.

    GET /watch/<wallet>          one wallet, $0.01 over x402 (sell-who.py prices it)
    GET /pro/watch?wallets=…     1 to 25 wallets, behind the Pro key (X-Atlas-Key)

Both are spend_watch.report() over the on-chain window this host already keeps
(who_service.CHAIN_STORE, filled by flows_handoff.fetch) and the registry snapshot set
who_service.fresh_capture() checks, so prices, freshness and refusals are the ones the
`who` answer and the Pro files use. probe.py's status-latest.json is read when this
host has one (STATUS_FILE, else beside the flows files); it is never imported.

Refusals, none of them billed:
    400  a malformed wallet, more than one on /watch/, more than 25, a bad days value
    503  no snapshot or a stale one; no on-chain window or a stale one
    404  /watch/<wallet> only: no x402 payment from that wallet in the window

No web framework, no network. Standard library only.
"""

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import who_service  # noqa: E402  (also puts the mandala folder on the path)
import spend_watch  # noqa: E402

PRICE = "$0.01"
STATUS_FILE = os.environ.get("STATUS_FILE") or None


def status_path():
    if STATUS_FILE:
        return STATUS_FILE
    if who_service.CHAIN_STORE:
        return os.path.join(who_service.CHAIN_STORE, "status-latest.json")
    return None


def answer(wallets, days=None, one=False, today=None, max_age_days=who_service.MAX_AGE_DAYS):
    """(status, body). `one`: the paid single-wallet door, where exactly one wallet is allowed
    and a wallet with no x402 payment in the window is a free 404."""
    ws, why = spend_watch.parse_wallets(wallets)
    if why:
        return 400, {"ok": False, "charged": False, "error": "invalid_wallet", "say": why}
    if one and len(ws) != 1:
        return 400, {"ok": False, "charged": False, "error": "invalid_wallet",
                     "say": "one wallet per call here; GET /pro/watch takes up to %d" % spend_watch.MAX_WALLETS}
    n, why = spend_watch.parse_days(days)
    if why:
        return 400, {"ok": False, "charged": False, "error": "invalid_days", "say": why}
    now = today or date.today()
    _, loaded, newest, refusal = who_service.fresh_capture(now, max_age_days)
    if refusal:
        return refusal
    flows, problems = spend_watch.load_days(who_service.CHAIN_STORE)
    return spend_watch.answer(ws, n, flows, loaded[-1]["sellers"], registry_date=newest.isoformat(),
                              status=spend_watch.load_status(status_path()), today=now,
                              max_age_days=max_age_days, need_payments=one, problems=problems)
