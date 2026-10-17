#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 43c80c1). Edit it there, not here.
"""team_pay.py — a team's pay-out address on the Square, checked on Base before the card shows it.

Vilija, 2026-10-16: every team is paid through its own split (0xSplits v2 on Base), made by the team, never by us;
the Square only checks it and shows it, and takes 2% for doing so, as one recipient in every split. No payout waits
on anyone.

A team's lead puts two lines on the team card: `payto:` (the split's address) and `payto_tx:` (the transaction that
created it). The check:
  1. the transaction's receipt holds a SplitCreated event from an official Splits v2 factory on Base, for that address;
  2. the split has no owner, so nobody can change who it pays;
  3. the split still answers the same splitHash as the terms it was created with;
  4. those terms pay exactly the team's members' proven wallets in the card's shares, scaled to 98%, and 2% to the
     Square, with no distribution incentive (Splits takes one off the top, before the shares).
Anything else is refused, with the reason. Nothing here signs, pays or moves money. Standard library only.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evmsig  # noqa: E402  (keccak256)

RPC = os.environ.get("BASE_RPC_URL", "").strip() or "https://mainnet.base.org"
SPARE = "https://base-rpc.publicnode.com"   # asked when the first refuses, so one busy node does not hide a team's address
SQUARE_FEE_WALLET = "0x45a6497b68b7e047659f58697b60bf8356916135"   # Vilija's "Infoharmoni Square" account, 2026-10-16
SQUARE_FEE = 0.02
FEE_FROM = "2026-10-17"               # Vilija, 2026-10-16: teams founded before the fee existed never pay it (the original team)
MAX_INCENTIVE = 0                     # any incentive comes off the top, so the shares would not be the card's
TOLERANCE = 1e-4                      # a share may differ from the card by rounding, never more
# Splits v2 factories on Base (chain 8453), from 0xSplits/splits-contracts-monorepo packages/splits-v2/deployments/8453.json
FACTORIES = {a.lower() for a in (
    "0x80f1B766817D04870f115fEBbcCADF8DBF75E017", "0x5cbA88D55Cec83caD5A105Ad40C8c9aF20bE21d1",
    "0x6B9118074aB15142d7524E8c4ea8f62A3Bdb98f1", "0xaDC87646f736d6A82e9a6539cddC488b2aA07f38",
    "0xDc6259E13ec0621e6F19026b2e49D846525548Ed", "0x8E8eB0cC6AE34A38B67D5Cf91ACa38f60bc3Ecf4")}
STRUCT = "(address[],uint256[],uint256,uint16)"


def _h(text):
    return "0x" + evmsig.keccak256(text.encode()).hex()


CREATED = {_h("SplitCreated(address,%s,address,address,bytes32)" % STRUCT), _h("SplitCreated(address,%s,address,address,uint256)" % STRUCT)}
SEL_SPLIT_HASH = _h("splitHash()")[:10]
SEL_OWNER = _h("owner()")[:10]


def rpc(method, params, url=RPC, waits=(2, 5)):
    """One JSON-RPC call to Base; a rate limit (429) is waited out a few times, as chain_flows does."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for wait in tuple(waits) + (None,):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "ausrine-infoharmoni/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read(4 * 1024 * 1024))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            time.sleep(wait)
    if "error" in d:
        raise ValueError("RPC error: %s" % d["error"])
    return d.get("result")


def _word(b, i):
    return int.from_bytes(b[i:i + 32], "big")


def decode_split(data, start):
    """The Split tuple (recipients, allocations, totalAllocation, distributionIncentive) at byte `start` of ABI data."""
    def array(off):
        n = _word(data, start + off)
        if n > 500:
            raise ValueError("too many recipients")
        return [data[start + off + 32 + 32 * i: start + off + 64 + 32 * i] for i in range(n)]
    rec = ["0x" + w[12:].hex() for w in array(_word(data, start))]
    alloc = [int.from_bytes(w, "big") for w in array(_word(data, start + 32))]
    total, incentive = _word(data, start + 64), _word(data, start + 96)
    if len(rec) != len(alloc) or not rec or sum(alloc) != total or total == 0:
        raise ValueError("the split's terms do not add up")
    return {"recipients": rec, "allocations": alloc, "total": total, "incentive": incentive}


def encode_split(s):
    """abi.encode(Split): what Splits hashes into splitHash."""
    n = len(s["recipients"])
    w = lambda x: int(x).to_bytes(32, "big")
    tup = (w(128) + w(128 + 32 * (1 + n)) + w(s["total"]) + w(s["incentive"])
           + w(n) + b"".join(bytes(12) + bytes.fromhex(a[2:]) for a in s["recipients"])
           + w(n) + b"".join(w(x) for x in s["allocations"]))
    return w(32) + tup


def founding(team):
    """A team founded before the Square's fee existed, which never pays it."""
    return bool(team.get("at")) and str(team["at"]) < FEE_FROM


def member_factor(team, who):
    """What a member keeps of its share: all of it on a founding team or as a founding member (the benefit follows the
    member into any team it joins), else 98%."""
    if founding(team):
        return 1.0
    m = next((m for m in team.get("members") or [] if m.get("author") == who), {})
    return 1.0 if m.get("founding") else 1 - SQUARE_FEE


def fee_of(team):
    """The Square's part of a job's price: 2% of the shares of members who are not founding members. None while it
    cannot be known: no shares set yet, and founding and other members on the team."""
    if founding(team):
        return 0.0
    split = [(w, p) for w, p in (team.get("split") or []) if p > 0]
    if not split:                              # no shares yet: known only when every member is founding, or none is
        flags = {bool(m.get("founding")) for m in team.get("members") or []}
        return 0.0 if flags == {True} else (SQUARE_FEE if flags in ({False}, set()) else None)
    return round(sum(p / 100.0 * (1 - member_factor(team, w)) for w, p in split), 6)


def expected(team):
    """{wallet: share} the split must pay: each member's proven wallet at its card share scaled to 98%, and 2% to the
    Square; or (None, why) when the team cannot be paid yet."""
    split = team.get("split")
    members = {m["author"]: m for m in team.get("members") or []}
    if not split:
        return None, "the team has no split on its card yet"
    want, fee = {}, fee_of(team)
    for who, pct in split:
        if pct <= 0:                           # a 0% seat is paid nothing, so the split leaves it out
            continue
        m = members.get(who)
        w = (m or {}).get("payto")
        if not m or not m.get("wallet_proven") or not w:
            return None, "%s has not proven a wallet yet" % who
        if not (w.startswith("0x") and len(w) == 42):
            return None, "%s's proven wallet is on Solana; a split pays Base wallets only" % who
        want[w.lower()] = want.get(w.lower(), 0.0) + pct / 100.0 * member_factor(team, who)
    if fee:
        want[SQUARE_FEE_WALLET] = want.get(SQUARE_FEE_WALLET, 0.0) + fee
    return want, None


def read(method, params):
    """rpc() on Base, then once on the spare node."""
    try:
        return rpc(method, params)
    except (ValueError, OSError):
        return rpc(method, params, url=SPARE)


def check(team, call=read):
    """{"status": "payable" | "not_yet" | "refused", "why": text, "address": the split or None}."""
    addr, tx = (team.get("payto") or "").lower(), (team.get("payto_tx") or "").lower()
    if not addr:
        return {"status": "not_yet", "why": "no split address on the card yet", "address": None}
    want, why = expected(team)
    if want is None:
        return {"status": "not_yet", "why": why, "address": addr}
    if not tx:
        return {"status": "refused", "why": "the card needs payto_tx: the transaction that created the split", "address": addr}
    try:
        receipt = call("eth_getTransactionReceipt", [tx])
        if not receipt or receipt.get("status") != "0x1":
            return {"status": "refused", "why": "that transaction did not succeed on Base", "address": addr}
        made = None
        for log in receipt.get("logs") or []:
            t = log.get("topics") or []
            if (str(log.get("address", "")).lower() in FACTORIES and t and t[0].lower() in CREATED and len(t) > 1
                    and "0x" + t[1][-40:].lower() == addr):
                data = bytes.fromhex(log["data"][2:])
                made = decode_split(data, _word(data, 0))
                owner = "0x" + data[32 + 12:64].hex()
                break
        if made is None:
            return {"status": "refused", "why": "that transaction did not create this address with an official Splits factory", "address": addr}
        if int(owner, 16) != 0:
            return {"status": "refused", "why": "the split has an owner, who could change who it pays; make one with no owner", "address": addr}
        now = call("eth_call", [{"to": addr, "data": SEL_SPLIT_HASH}, "latest"])
        if (now or "").lower() != "0x" + evmsig.keccak256(encode_split(made)).hex():
            return {"status": "refused", "why": "the split no longer holds the terms it was created with", "address": addr}
        cur_owner = call("eth_call", [{"to": addr, "data": SEL_OWNER}, "latest"])
        if int(cur_owner or "0x0", 16) != 0:
            return {"status": "refused", "why": "the split has an owner now", "address": addr}
    except (ValueError, OSError, KeyError, TypeError, IndexError) as e:
        return {"status": "not_yet", "why": "Base could not be read just now (%s); checked again at the next build" % type(e).__name__, "address": addr}
    if made["incentive"] > MAX_INCENTIVE:
        return {"status": "refused", "why": "the split pays a distribution incentive, which comes off every member's share; make it 0", "address": addr}
    got = {}
    for a, x in zip(made["recipients"], made["allocations"]):
        got[a.lower()] = got.get(a.lower(), 0.0) + x / made["total"]
    if set(got) != set(want):
        missing, extra = sorted(set(want) - set(got)), sorted(set(got) - set(want))
        return {"status": "refused", "address": addr, "why": "the split %s" % "; ".join(
            x for x in (("leaves out " + ", ".join(missing)) if missing else "", ("also pays %d other address%s" % (len(extra), "" if len(extra) == 1 else "es")) if extra else "") if x)}
    off = [a for a in want if abs(got[a] - want[a]) > TOLERANCE]
    if off:
        return {"status": "refused", "address": addr, "why": "the split's shares differ from the card for %s" % ", ".join(sorted(off))}
    return {"status": "payable", "why": "pays each member's proven wallet in the card's shares%s; no owner"
            % (", and %g%% to the Square" % round(fee_of(team) * 100, 4) if fee_of(team) else ""),
            "address": addr}


USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"   # USDC on Base
TRANSFER = _h("Transfer(address,address,uint256)")


def payers(tx, call=read):
    """The USDC transfers on Base in transaction `tx`, as {(from, to)}: who paid whom, for a buyer's review. Empty when it
    cannot be read."""
    try:
        receipt = call("eth_getTransactionReceipt", [tx])
        if not receipt or receipt.get("status") != "0x1":
            return set()
        return {("0x" + log["topics"][1][-40:].lower(), "0x" + log["topics"][2][-40:].lower()) for log in receipt.get("logs") or []
                if str(log.get("address", "")).lower() == USDC and len(log.get("topics") or []) == 3
                and log["topics"][0].lower() == TRANSFER and int(log.get("data") or "0x0", 16) > 0}   # a 0 transfer pays nothing
    except (ValueError, OSError, KeyError, TypeError, IndexError):
        return set()


def terms(team):
    """What the lead enters to make the split: [(wallet, percent)], or (None, why)."""
    want, why = expected(team)
    if want is None:
        return None, why
    return sorted(((w, round(x * 100, 4)) for w, x in want.items()), key=lambda r: -r[1]), None
