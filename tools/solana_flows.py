#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 400e511). Edit it there, not here.
"""solana_flows.py — who paid whom on Solana: every x402 payment a known payment
processor settled, read in six-hour windows and assembled into UTC days.

Base reads cleanly off one USDC contract's Transfer logs. Solana has no such index,
and walking every listed seller's token account (the September prototype) missed
every payee the registry does not list. The processors are the index instead: an
x402 payment on Solana is a transaction the facilitator pays the fee for — account
0 — carrying one spl-token transferChecked from the buyer's stablecoin account to
the seller's, plus a memo. x402scan's MIT package `facilitators` names the fee-payer
wallets (solana_facilitators.json: 27 addresses, 17 processors, on 2026-10-09).

    processor  a known fee-payer wallet; a payment is counted whoever the payee is
    payment    account 0 is a processor, and the stablecoin balances moved exactly
               once down (the buyer's owner) and once up (the seller's owner), with
               different owners. USDC and USDT both count; the asset is kept.
    other      anything else a processor paid the fee for: counted in other_shape,
               never as a payment
    mention    getSignaturesForAddress lists every transaction that so much as
               names the address (testdata/solana/failed_tx.json is listed under a
               Coinbase processor though another key paid its fee), so the account-0
               check is what makes a payment the processor's, not the listing

Why windows and not days (measured 2026-10-09): the free fast RPC, publicnode,
keeps about 19 hours — signature paging stops there and getTransaction answers
null for anything older — while api.mainnet-beta.solana.com has the whole history
but sustains about 0.7 getTransaction a second with backoff, six hours for one
day. So a day cannot be read after it ends. Instead:

    read      one half-open window [since, until), by blockTime
    catchup   every missing complete six-hour UTC window (00, 06, 12, 18) whose end
              is between ten minutes and ten hours ago, each written atomically
              to D/sol-YYYY-MM-DDTHH.json; one over 1% unread is not written
    assemble  the four windows of a day into flows-sol-YYYY-MM-DD.json (hours 24),
              only when all four exist; otherwise exit non-zero naming the missing

Signatures are paged on publicnode first and on mainnet-beta when publicnode's
history ends before the window does. Transactions are read on publicnode; a null
answer is asked once more on mainnet-beta and counted unread if still null.
Transactions come in version 1 now, and mainnet-beta refuses
maxSupportedTransactionVersion 0 for those (error -32015), so version 1 is asked.

Every file has the shape chain_flows.py writes, so whales.py merges the two chains:
{"chain":"solana","date","day","hours","edges":[{from,to,n,usdc,n_x402,usdc_x402}],
"sellers":{wallet:[hosts]}}, plus "processors":{id:{payments,usdc}},
"assets":{symbol:{mint,payments,usdc}}, "other_shape" and "unread". Every edge is
x402 by construction (n == n_x402); "usdc" is stablecoin dollars, USDC and USDT
together. Base58 is case-sensitive and no address is ever lowercased here.

    python3 solana_flows.py catchup --dir flows/sol-windows --snapshot radar/market-2026-10-08.json
    python3 solana_flows.py assemble --day 2026-10-08 --dir flows/sol-windows --out flows/flows-sol-2026-10-08.json
    python3 solana_flows.py read --since 2026-10-08T06:00 --until 2026-10-08T12:00 --out sol-2026-10-08T06.json
    python3 solana_flows.py show <signature>        # one transaction, trimmed like the fixtures

Public RPCs, no key. Standard library only. MIT.
"""

import argparse
import collections
import concurrent.futures
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FACILITATORS = os.path.join(HERE, "solana_facilitators.json")

# Ordered: publicnode answered 1,000 getTransaction calls at six workers without a refusal
# but keeps ~19 h; mainnet-beta keeps everything and refuses most of a burst (HTTP 429).
RPCS = ["https://solana-rpc.publicnode.com", "https://api.mainnet-beta.solana.com"]
# How far back each endpoint's history reaches, in seconds; None is the whole history. When
# an endpoint's signature list runs out, the list is whole only if the window starts inside
# that reach: publicnode answered back to ~19.3 h on 2026-10-09, so 17 h is taken. An
# endpoint not named here is taken to keep everything.
DEPTH = {"https://solana-rpc.publicnode.com": 17 * 3600, "https://api.mainnet-beta.solana.com": None}

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
STABLE = {USDC: "USDC", USDT: "USDT"}
# The programs an x402 'exact' payment on Solana is made of, read off the live chain on
# 2026-10-09: the fee settings, one token transferChecked, and, from most processors, a memo
# (openfacilitator sends none); a first payment to a seller may also create its token account.
COMPUTE = "ComputeBudget111111111111111111111111111111"
TOKEN_PROGRAMS = {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}
ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
MEMOS = {"MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr", "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo"}
# Lighthouse: an assertion program some wallets add to what they sign. It checks an account
# and moves nothing; 22 of Coinbase's payments in one window carried it (2026-10-09).
ASSERTIONS = {"L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"}
# Not counted, and said so: PayAI also settles through a channel program
# (CHNLxYvVA28MJP9PrFuDXccuoGXAx7jBacfLEkahyGsX, about $10 a window on 2026-10-08). That is
# a settlement of a payment channel, not one exact payment, and stays in other_shape.
PAGE = 1000                      # getSignaturesForAddress's largest page
WORKERS = 6
MAX_UNREAD = 0.01                # more than this share unread: write nothing
WINDOW_HOURS = 6                 # the catchup windows: 00, 06, 12, 18 UTC
TX_VERSION = 1                   # maxSupportedTransactionVersion
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
TX_OPTS = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": TX_VERSION}


class RpcRefused(Exception):
    """The RPC answered but not with the result: a 429, a 5xx, a timeout, a cut connection.
    Asking again, a little later or elsewhere, can help."""


class Rpc:
    """An ordered list of JSON-RPC endpoints with backoff. call_at() asks one endpoint up to
    `tries` times, sleeping longer after each refusal; call() does that for each endpoint in
    turn. Thread-safe: it keeps no state between calls but the refusal counts. `post` and
    `sleep` are arguments so a test can stand in for the network and the clock."""

    def __init__(self, urls=None, tries=5, post=None, sleep=time.sleep, timeout=60, depth=None):
        self.urls = list(urls or RPCS)
        self.depth = dict(DEPTH if depth is None else depth)
        self.tries = tries
        self.post = post or self._post
        self.sleep = sleep
        self.timeout = timeout
        self.refusals = collections.Counter()      # per endpoint, for the summary

    def _post(self, url, body):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "User-Agent": "ausrine-infoharmoni/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                raise RpcRefused("HTTP %d" % e.code)
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise RpcRefused(str(e)[:80])

    def call_at(self, url, method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        last = None
        for i in range(self.tries):
            try:
                d = self.post(url, body)
            except RpcRefused as e:
                last = e
                self.refusals[url] += 1
                # 0.5, 1, 2, 4 s ... with a little jitter so six workers do not knock together
                self.sleep(0.5 * 2 ** i + random.random() * 0.25)
                continue
            if "error" in d:
                err = d["error"] or {}
                code = err.get("code", 0)
                # a node that is behind or rate-limiting inside the body: try again like a 429
                if code in (429, -32005, -32004, -32009, -32014, -32016):
                    last = RpcRefused(str(err.get("message", code))[:80])
                    self.refusals[url] += 1
                    self.sleep(0.5 * 2 ** i)
                    continue
                raise RuntimeError("%s: %s" % (method, str(err.get("message", err))[:120]))
            return d.get("result")
        raise RpcRefused("%s at %s: refused %d times (%s)" % (method, url.split("//")[-1], self.tries, last))

    def call(self, method, params):
        last = None
        for url in self.urls:
            try:
                return self.call_at(url, method, params)
            except RpcRefused as e:
                last = e
        raise RpcRefused("%s: every endpoint refused (%s)" % (method, last))


# ── time ─────────────────────────────────────────────────────────────────────────────────

def parse_iso(s):
    """Unix seconds of an ISO time taken as UTC: 2026-10-08, 2026-10-08T06:00, ...T06:00:00Z."""
    s = s.strip().replace("Z", "")
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_bounds(day):
    """Unix seconds at the start of `day` (UTC) and of the day after."""
    d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(d0.timestamp()), int((d0 + timedelta(days=1)).timestamp())


def window_name(since):
    """sol-YYYY-MM-DDTHH, the window's file stem, from its start."""
    return datetime.fromtimestamp(since, timezone.utc).strftime("sol-%Y-%m-%dT%H")


def day_windows(day):
    """The four [since, until) windows of a UTC day, oldest first."""
    start, _ = day_bounds(day)
    step = WINDOW_HOURS * 3600
    return [(start + i * step, start + (i + 1) * step) for i in range(24 // WINDOW_HOURS)]


def due_windows(now, min_age=600, max_age=10 * 3600):
    """The complete six-hour windows whose end is between `min_age` and `max_age` seconds
    before `now`, oldest first: what catchup should have on disk. Ten minutes lets the chain
    finalize and the RPCs index. Ten hours keeps a window's start within 16 h, inside
    publicnode's reach (DEPTH, 17 h; ~19 h measured) with time to read it; an hourly run gets
    about ten tries at each window."""
    step = WINDOW_HOURS * 3600
    end = (now - min_age) // step * step             # the newest boundary at least min_age ago
    out = []
    while end >= now - max_age:
        out.append((end - step, end))
        end -= step
    return sorted(out)


# ── the processors and the sellers ───────────────────────────────────────────────────────

def load_processors(path=FACILITATORS, snap=None):
    """{fee-payer address: processor id} from solana_facilitators.json, live and deprecated
    alike (PayAI's deprecated CjNFTjvB… still settled ~630 a day in October 2026), plus any
    the registry pull names (see processors_from_snapshot)."""
    with open(path) as f:
        rows = json.load(f)["facilitators"]
    out = {}
    for r in rows:
        if not BASE58.match(r["address"]):
            raise ValueError("not a base58 address in %s: %r" % (path, r["address"]))
        out[r["address"]] = r["id"]
    for addr, pid in processors_from_snapshot(snap).items():
        out.setdefault(addr, pid)
    return out


def processors_from_snapshot(snap):
    """Fee payers the registry itself names, when the snapshot keeps them: a Solana listing's
    `accepts[].extra.feePayer` is the processor that will settle for that seller.

    TODO: radar.py keeps only each seller's payTo wallets (`wallets`) and chain names, not
    `extra`, so today this finds nothing and the list comes from solana_facilitators.json
    alone. When radar.py keeps feePayer per Solana listing (a separate change; radar.py is
    not widened here), it should land in each seller row as `fee_payers`, and this function
    already reads that key, with id "registry:<host>". Nothing is lowercased."""
    out = {}
    for host, s in ((snap or {}).get("sellers") or {}).items():
        for fp in s.get("fee_payers") or []:
            if isinstance(fp, str) and BASE58.match(fp):
                out.setdefault(fp, "registry:" + host)
    return out


def sellers_from_snapshot(snap):
    """{solana wallet: [hosts]} from a radar snapshot (market-<date>.json): the payTo wallets
    that are base58, case kept. A payee not among them is still counted; whales.py shows it
    as its short wallet."""
    hosts_of = collections.defaultdict(set)
    for host, s in (snap or {}).get("sellers", {}).items():
        for w in s.get("wallets", []):
            if isinstance(w, str) and not w.startswith("0x") and BASE58.match(w):
                hosts_of[w].add(host)
    return {w: sorted(h) for w, h in hosts_of.items()}


# ── reading the chain ────────────────────────────────────────────────────────────────────

def page_signatures(rpc, url, address, since, until, page=PAGE, now=None):
    """One endpoint's signatures under `address` with since <= blockTime < until, paged newest
    first with `before`. Returns ([(signature, blockTime)], reached): `reached` is True when the
    whole window is in the list: a row older than `since` was seen, or the list ran out on an
    endpoint whose history reaches back past `since` (DEPTH; a quiet processor has nothing
    older to show). False when the list ran out where the endpoint's history may end first
    (publicnode keeps ~19 h). Failed signatures (err) are skipped. Raises RpcRefused if a page
    cannot be read: a window with a page missing is not a window."""
    now = time.time() if now is None else now
    depth = rpc.depth.get(url)
    whole_if_run_out = depth is None or since >= now - depth
    out, before = [], None
    while True:
        params = [address, {"limit": page, **({"before": before} if before else {})}]
        sigs = rpc.call_at(url, "getSignaturesForAddress", params) or []
        for s in sigs:
            bt = s.get("blockTime")
            if bt is None:
                # the RPC may leave the time out (Codex): kept, and placed by its transaction's
                # own time when read; if that cannot be read either, it counts as unread
                out.append((s["signature"], None))
                continue
            if bt < since:
                return out, True                      # older than the window: everything after is too
            if bt < until:
                # a failed one is kept: classify() counts it as failed, never as a payment
                out.append((s["signature"], bt))
        if len(sigs) < page:
            return out, whole_if_run_out
        before = sigs[-1]["signature"]               # the oldest of this page, whatever its state


def signatures_in_window(rpc, address, since, until, page=PAGE, now=None):
    """The window's signatures under `address`, from the first endpoint whose list is whole
    (page_signatures' `reached`). An endpoint that refuses, or whose history may end inside the
    window, is passed over. When none gives the whole window, RpcRefused: a shorter list would
    count a part of the window as all of it."""
    last = None
    for url in rpc.urls:
        try:
            sigs, reached = page_signatures(rpc, url, address, since, until, page, now)
        except RpcRefused as e:
            last = e
            continue
        if reached:
            return sigs
        last = "history at %s may end inside the window" % url.split("//")[-1]
    raise RpcRefused("getSignaturesForAddress %s…: no endpoint gave the whole window (%s)" % (address[:8], last))


def fetch_tx(rpc, sig):
    """One transaction, jsonParsed, version 1 allowed. Asked on each endpoint in turn: a null
    (publicnode past its ~19 h) or a refusal moves to the next. None when every endpoint
    answered null or refused: the caller counts it unread."""
    for url in rpc.urls:
        try:
            tx = rpc.call_at(url, "getTransaction", [sig, TX_OPTS])
        except (RpcRefused, RuntimeError):
            # RuntimeError: an answer that is an error, not a refusal (a pruned slot, an
            # unsupported version). One odd transaction must not stop the window: the next
            # endpoint is asked, and if none can say, it is unread and the 1% rule decides.
            continue
        if tx is not None:
            return tx
    return None


def stable_deltas(tx):
    """Each stablecoin balance change in a transaction, from meta's pre/post token balances:
    [(mint, owner, delta in whole tokens)], nonzero only. Integer math on the raw amount."""
    meta = tx.get("meta") or {}
    pre = {b["accountIndex"]: b for b in meta.get("preTokenBalances") or [] if b.get("mint") in STABLE}
    post = {b["accountIndex"]: b for b in meta.get("postTokenBalances") or [] if b.get("mint") in STABLE}
    out = []
    for idx in sorted(set(pre) | set(post)):
        b = post.get(idx) or pre.get(idx)
        raw_pre = int(((pre.get(idx) or {}).get("uiTokenAmount") or {}).get("amount") or 0)
        raw_post = int(((post.get(idx) or {}).get("uiTokenAmount") or {}).get("amount") or 0)
        decimals = int((b.get("uiTokenAmount") or {}).get("decimals") or 6)
        if raw_post != raw_pre:
            out.append((b["mint"], b.get("owner"), (raw_post - raw_pre) / 10 ** decimals))
    return out


def fee_payer(tx):
    """Account 0 of the message: the wallet that paid the transaction fee. The same in a
    version 0 and a version 1 transaction (the looked-up addresses come after)."""
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    if not keys:
        return None
    k = keys[0]
    return k.get("pubkey") if isinstance(k, dict) else k


def payment_transfer(tx, payer):
    """The one stablecoin transferChecked of an x402 payment, or None when the transaction is
    not made like one: only fee settings, at most a token-account creation, one transferChecked
    of USDC or USDT, and memos. Its authority (the buyer, who signed) must not be the fee payer:
    a processor moving its own money, a refund or a treasury sweep from its wallet, has the
    same balance shape as a payment and is not one (Codex, 2026-10-09)."""
    transfers = []
    for ins in ((tx.get("transaction") or {}).get("message") or {}).get("instructions") or []:
        prog = ins.get("programId")
        if prog == COMPUTE or prog in MEMOS or prog in ASSERTIONS:
            continue
        parsed = ins.get("parsed") if isinstance(ins.get("parsed"), dict) else {}
        if prog == ATA and parsed.get("type") in ("create", "createIdempotent"):
            continue
        if prog in TOKEN_PROGRAMS and parsed.get("type") == "transferChecked":
            transfers.append(parsed.get("info") or {})
            continue
        return None                                   # any other program: not the shape of a payment
    if len(transfers) != 1:
        return None
    info = transfers[0]
    if info.get("mint") not in STABLE:
        return None
    if (info.get("authority") or info.get("multisigAuthority")) in (None, payer):
        return None
    return info


def classify(tx, processors):
    """What one transaction is. ("payment", {buyer, seller, mint, amount, processor}) when it
    is an x402 payment a known processor settled; ("failed", None) when it failed on-chain;
    ("not_processor", None) when someone else paid the fee — the signature list of a
    processor includes transactions that merely mention it; ("other_shape", None) when a
    processor paid the fee but the stablecoins did not move as one payment; ("unread", None)
    when there is no transaction to read."""
    if tx is None:
        return "unread", None
    if (tx.get("meta") or {}).get("err") is not None:
        return "failed", None
    payer = fee_payer(tx)
    if payer not in processors:
        return "not_processor", None
    if payment_transfer(tx, payer) is None:
        return "other_shape", None
    deltas = stable_deltas(tx)
    debits = [d for d in deltas if d[2] < 0]
    credits = [d for d in deltas if d[2] > 0]
    if len(debits) != 1 or len(credits) != 1:
        return "other_shape", None
    (mint_d, buyer, down), (mint_c, seller, up) = debits[0], credits[0]
    if mint_d != mint_c or not buyer or not seller or buyer == seller or abs(up + down) > 1e-9:
        return "other_shape", None
    return "payment", {"buyer": buyer, "seller": seller, "mint": mint_c, "amount": up, "processor": processors[payer]}


class Tally:
    """The counters of one window or one day, folded one transaction at a time, or merged
    from files (assemble)."""

    def __init__(self, signatures=0):
        self.signatures = signatures
        self.edges = collections.Counter()           # (buyer, seller) -> payments
        self.usd = collections.Counter()             # (buyer, seller) -> stablecoin dollars
        self.processors = collections.defaultdict(lambda: {"payments": 0, "usdc": 0.0})
        self.assets = collections.defaultdict(lambda: {"payments": 0, "usdc": 0.0})
        self.other_shape = self.unread = self.failed = self.not_processor = 0
        self.payments = 0

    def add(self, kind, p):
        if kind == "payment":
            self.payments += 1
            self.edges[(p["buyer"], p["seller"])] += 1
            self.usd[(p["buyer"], p["seller"])] += p["amount"]
            self.processors[p["processor"]]["payments"] += 1
            self.processors[p["processor"]]["usdc"] += p["amount"]
            self.assets[p["mint"]]["payments"] += 1
            self.assets[p["mint"]]["usdc"] += p["amount"]
        elif kind == "unread":
            self.unread += 1
        elif kind == "failed":
            self.failed += 1
        elif kind == "not_processor":
            self.not_processor += 1
        else:
            self.other_shape += 1

    def merge(self, f):
        """Fold one written window file in."""
        self.signatures += f.get("signatures", 0)
        self.unread += f.get("unread", 0)
        self.other_shape += f.get("other_shape", 0)
        self.failed += f.get("failed", 0)
        self.not_processor += f.get("not_processor", 0)
        for e in f["edges"]:
            self.payments += e["n"]
            self.edges[(e["from"], e["to"])] += e["n"]
            self.usd[(e["from"], e["to"])] += e["usdc"]
        for pid, v in f.get("processors", {}).items():
            self.processors[pid]["payments"] += v["payments"]
            self.processors[pid]["usdc"] += v["usdc"]
        for sym, v in f.get("assets", {}).items():
            self.assets[v.get("mint", sym)]["payments"] += v["payments"]
            self.assets[v.get("mint", sym)]["usdc"] += v["usdc"]

    def unread_share(self):
        return self.unread / self.signatures if self.signatures else 0.0

    def output(self, since, until, sellers, rpcs, extra=None):
        day = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d")
        out = {
            "chain": "solana", "date": day, "day": day, "hours": round((until - since) / 3600.0, 4),
            "since": iso(since), "until": iso(until),
            "x402_means": "a known payment processor (solana_facilitators.json) paid the fee, and the stablecoin "
                          "balances moved exactly once down and once up between two owners: that processor settled it",
            "counts": "every payment a known processor settled, whoever the payee is; a payee the registry does not "
                      "list is still counted and shows as its wallet",
            "signatures": self.signatures, "unread": self.unread, "other_shape": self.other_shape,
            "failed": self.failed, "not_processor": self.not_processor, "rpc": rpcs,
            "edges": [{"from": f, "to": t, "n": n, "usdc": round(self.usd[(f, t)], 6),
                       "n_x402": n, "usdc_x402": round(self.usd[(f, t)], 6)}
                      for (f, t), n in sorted(self.edges.items(), key=lambda kv: (-kv[1], kv[0]))],
            "processors": {k: {"payments": v["payments"], "usdc": round(v["usdc"], 6)}
                           for k, v in sorted(self.processors.items(), key=lambda kv: -kv[1]["payments"])},
            "assets": {STABLE.get(m, m): {"mint": m, "payments": v["payments"], "usdc": round(v["usdc"], 6)}
                       for m, v in sorted(self.assets.items(), key=lambda kv: -kv[1]["payments"])},
            "sellers": sellers,
        }
        out.update(extra or {})
        return out


def read_window(rpc, processors, since, until, workers=WORKERS, log=None):
    """Every transaction under every processor in [since, until), read once however many
    processors listed it, classified into a Tally. A signature whose transaction cannot be
    read on any endpoint counts as unread; the caller decides what that means."""
    log = log or (lambda s: None)
    found = {}                                       # signature -> blockTime (None: not given), deduped across addresses
    for addr in sorted(processors):
        sigs = signatures_in_window(rpc, addr, since, until)
        for sig, bt in sigs:
            if found.get(sig) is None:
                found[sig] = bt
        if sigs:
            log("  %s %-22s %6d signatures · %d distinct so far" % (addr[:8] + "…", processors[addr], len(sigs), len(found)))
    if not found:
        # Every processor quiet for six hours has not happened (about 3,600 a window in October
        # 2026); an endpoint answering empty pages has. Not written: the next run asks again.
        raise RpcRefused("no signature under any of %d processor addresses in the window: an empty answer "
                         "is not taken for a quiet market" % len(processors))
    tally = Tally(len(found))
    lock = threading.Lock()
    done = [0]

    def read(sig):
        tx = fetch_tx(rpc, sig)
        if found[sig] is None and tx is not None:
            bt = tx.get("blockTime")
            if bt is None:
                tx = None                            # no time anywhere: it cannot be placed, so it is unread
            elif not since <= bt < until:
                with lock:
                    tally.signatures -= 1            # listed without a time, and not this window's after all
                return
        kind, p = classify(tx, processors)
        with lock:
            tally.add(kind, p)
            done[0] += 1
            if done[0] % 1000 == 0:
                log("  %d/%d read · %d payments · %d unread" % (done[0], len(found), tally.payments, tally.unread))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(read, sorted(found, key=lambda s: found[s] or 0)))
    return tally


def summary(tally, sellers):
    """The lines a run prints: payments, dollars, per processor, buyers, payees, listed payees."""
    payees = {t for _, t in tally.edges}
    buyers = {f for f, _ in tally.edges}
    lines = ["payments %d · stablecoin $%.2f (%s) · buyer wallets %d · payees %d, of them %d listed sellers"
             % (tally.payments, sum(tally.usd.values()),
                ", ".join("%s %d" % (STABLE.get(m, m[:6]), v["payments"]) for m, v in tally.assets.items()) or "none",
                len(buyers), len(payees), sum(1 for t in payees if t in sellers)),
             "other shape %d · failed %d · not a processor %d · unread %d of %d signatures (%.2f%%)"
             % (tally.other_shape, tally.failed, tally.not_processor, tally.unread, tally.signatures, 100 * tally.unread_share())]
    for pid, v in sorted(tally.processors.items(), key=lambda kv: -kv[1]["payments"]):
        lines.append("  %-24s %6d payments  $%10.2f" % (pid, v["payments"], v["usdc"]))
    return "\n".join(lines)


def write_atomic(path, obj):
    """Write the JSON beside its destination and move it into place: a reader never sees half
    a file, and a crash leaves no partial window behind."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def trimmed(tx):
    """A getTransaction answer cut to what classify() reads, for a fixture: account keys, the
    instructions' programs, err, fee, the token balances, blockTime, version."""
    msg = ((tx or {}).get("transaction") or {}).get("message") or {}
    meta = (tx or {}).get("meta") or {}
    return {"slot": tx.get("slot"), "blockTime": tx.get("blockTime"), "version": tx.get("version"),
            "transaction": {"signatures": (tx.get("transaction") or {}).get("signatures"),
                            "message": {"accountKeys": msg.get("accountKeys"),
                                        "instructions": [{k: v for k, v in i.items() if k in ("program", "programId", "parsed")}
                                                         for i in msg.get("instructions") or []]}},
            "meta": {k: meta.get(k) for k in ("err", "fee", "preTokenBalances", "postTokenBalances")}}


# ── the commands ─────────────────────────────────────────────────────────────────────────

def cmd_read(rpc, processors, sellers, since, until, out_path, workers, log, now=None):
    """One window [since, until) to `out_path`. Exits non-zero, writing nothing, when the
    window is not over, a signature page could not be read, or over 1% is unread."""
    now = time.time() if now is None else now
    if until > now:
        sys.exit("solana-flows: the window to %s is not over yet" % iso(until))
    if since >= until:
        sys.exit("solana-flows: --since must be before --until")
    log("Solana · %s → %s · %d processor addresses · %d listed seller wallets · %d workers"
        % (iso(since), iso(until), len(processors), len(sellers), workers))
    try:
        tally = read_window(rpc, processors, since, until, workers, log)
    except RpcRefused as e:
        sys.exit("solana-flows: %s · nothing written, a window with a page missing is not a window" % e)
    print(summary(tally, sellers))
    if rpc.refusals:
        log("  refusals: " + ", ".join("%s %d" % (u.split("//")[-1], n) for u, n in rpc.refusals.items()))
    if tally.unread_share() > MAX_UNREAD:
        sys.exit("solana-flows: %d of %d signatures unread (%.2f%% > %.0f%%): nothing written, a partial window is not a window"
                 % (tally.unread, tally.signatures, 100 * tally.unread_share(), 100 * MAX_UNREAD))
    write_atomic(out_path, tally.output(since, until, sellers, rpc.urls, {"window": window_name(since)}))
    print("wrote", out_path)


def cmd_catchup(rpc, processors, sellers, folder, workers, log, now=None):
    """Every due window (due_windows) not yet in `folder`, read and written one by one, the
    oldest first. A window over 1% unread or with a page missing is reported and left for
    the next run. Returns the names written and the names refused."""
    now = time.time() if now is None else now
    os.makedirs(folder, exist_ok=True)
    written, refused = [], []
    for since, until in due_windows(int(now)):
        name = window_name(since)
        path = os.path.join(folder, name + ".json")
        if os.path.exists(path):
            continue
        log("catchup · %s · %s → %s" % (name, iso(since), iso(until)))
        try:
            tally = read_window(rpc, processors, since, until, workers, log)
        except RpcRefused as e:
            log("  %s: %s · not written" % (name, e))
            refused.append(name)
            continue
        print(name)
        print(summary(tally, sellers))
        if tally.unread_share() > MAX_UNREAD:
            log("  %s: %d of %d unread (%.2f%%) · not written" % (name, tally.unread, tally.signatures, 100 * tally.unread_share()))
            refused.append(name)
            continue
        write_atomic(path, tally.output(since, until, sellers, rpc.urls, {"window": name}))
        print("wrote", path)
        written.append(name)
    if rpc.refusals:
        log("  refusals: " + ", ".join("%s %d" % (u.split("//")[-1], n) for u, n in rpc.refusals.items()))
    print("catchup: %d written, %d not written%s" % (len(written), len(refused), (": " + ", ".join(refused)) if refused else ""))
    return written, refused


def cmd_assemble(day, folder, out_path, snap=None):
    """The day file from its four windows, only when all four are on disk. The sellers are
    the union of the windows' lists, or the snapshot's when one is given."""
    paths = [os.path.join(folder, window_name(s) + ".json") for s, _ in day_windows(day)]
    missing = [os.path.basename(p)[:-5] for p in paths if not os.path.exists(p)]
    if missing:
        sys.exit("solana-flows: %s is not whole: missing %s" % (day, ", ".join(missing)))
    tally = Tally()
    sellers, rpcs = {}, []
    for p, (since, until) in zip(paths, day_windows(day)):
        with open(p) as f:
            w = json.load(f)
        # a file is this window only if it says so: the name alone could be a stale or moved file (Codex)
        if (w.get("chain"), w.get("since"), w.get("until")) != ("solana", iso(since), iso(until)):
            sys.exit("solana-flows: %s is not the Solana window %s → %s (it says %s, %s → %s); nothing written"
                     % (os.path.basename(p), iso(since), iso(until), w.get("chain"), w.get("since"), w.get("until")))
        tally.merge(w)
        for wallet, hosts in w.get("sellers", {}).items():
            sellers[wallet] = sorted(set(sellers.get(wallet, [])) | set(hosts))
        for u in w.get("rpc") or []:
            if u not in rpcs:
                rpcs.append(u)
    if snap:
        sellers = sellers_from_snapshot(snap)
    start, end = day_bounds(day)
    out = tally.output(start, end, sellers, rpcs, {"windows": [os.path.basename(p)[:-5] for p in paths]})
    write_atomic(out_path, out)
    print(summary(tally, sellers))
    print("wrote", out_path)
    return out


def main(argv=None, rpc=None, now=None):
    """The command line. `argv`, `rpc` and `now` are arguments so a test can run every
    command against a fake endpoint and a fixed clock; the command line passes none."""
    # The shared options are taken before or after the command (Codex: the documented
    # "catchup --dir ... --snapshot ..." failed); --rpc takes one URL per use, so it can never
    # swallow the command's name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--facilitators", default=argparse.SUPPRESS, help="the processors' fee-payer addresses")
    common.add_argument("--rpc", action="append", default=argparse.SUPPRESS,
                        help="a JSON-RPC endpoint; repeat for more, in order (default: %s)" % ", ".join(RPCS))
    common.add_argument("--workers", type=int, default=argparse.SUPPRESS, help="getTransaction calls in flight at once")
    common.add_argument("--snapshot", default=argparse.SUPPRESS, help="radar snapshot market-<date>.json: the listed sellers' wallets and names")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", parents=[common], help="one half-open window [since, until)")
    r.add_argument("--since", required=True, help="ISO time, UTC: 2026-10-08T06:00")
    r.add_argument("--until", required=True)
    r.add_argument("--out", required=True)
    c = sub.add_parser("catchup", parents=[common], help="every missing complete six-hour window ended 10 min to 10 h ago")
    c.add_argument("--dir", required=True, help="where the windows live: D/sol-YYYY-MM-DDTHH.json")
    s = sub.add_parser("assemble", parents=[common], help="the day file from its four windows")
    s.add_argument("--day", required=True, help="YYYY-MM-DD, UTC")
    s.add_argument("--dir", required=True)
    s.add_argument("--out", required=True)
    w = sub.add_parser("show", parents=[common], help="print one transaction, trimmed to what the reader uses")
    w.add_argument("signature")
    a = ap.parse_args(argv)
    a.facilitators = getattr(a, "facilitators", FACILITATORS)
    a.rpc = getattr(a, "rpc", None)
    a.workers = getattr(a, "workers", WORKERS)
    a.snapshot = getattr(a, "snapshot", None)

    rpc = rpc or Rpc(a.rpc)
    log = lambda s: print(s, file=sys.stderr)
    snap = None
    if a.snapshot:
        with open(a.snapshot) as f:
            snap = json.load(f)
    if a.cmd == "show":
        json.dump(trimmed(fetch_tx(rpc, a.signature)), sys.stdout, indent=1)
        print()
        return
    if a.cmd == "assemble":
        cmd_assemble(a.day, a.dir, a.out, snap)
        return
    processors = load_processors(a.facilitators, snap)
    sellers = sellers_from_snapshot(snap)
    if a.cmd == "read":
        cmd_read(rpc, processors, sellers, parse_iso(a.since), parse_iso(a.until), a.out, a.workers, log, now)
    elif a.cmd == "catchup":
        _, refused = cmd_catchup(rpc, processors, sellers, a.dir, a.workers, log, now)
        if refused:
            sys.exit(1)


if __name__ == "__main__":
    main()
