#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit a0d9190). Edit it there, not here.
"""sell-who.py — the Radar's `who` verdict, and the Atlas Pro files, sold per call over x402.

The evidence (journal/2026-09-15-money.md): nobody buys a market overview,
but agents pay, up to $0.25 a call, for a verdict on ONE seller before they
spend. `radar.who_data()` produces that verdict; who_service.py decides what
is an answer; this file puts a price on the answers and on nothing else.

    GET /who/<host-or-wallet>    $0.01 for a report card; refusals are free
    GET /health                  free
    GET /stats                   free: the funnel counts since the process started (Funnel)
    GET /pro                     free: what Atlas Pro holds and how to call it
    GET /watch/<wallet>          $0.01: what one wallet spent over x402 on Base, with whom, and
                                 how each seller it paid stands (spend_watch.py); refusals free
    GET /pro/watch?wallets=…     Atlas Pro: the same for 1 to 25 wallets, behind the same key
    GET /pro/export/<file>       Atlas Pro, $49 a month: a Polar license key in X-Atlas-Key,
                                 never x402 (pro.py). POLAR_ORG_ID switches it on.
    GET /x402/export/<file>      the same Atlas Pro files, no key: paid per file over x402,
                                 $0.25 for sellers.csv, buyers.csv, operators.csv; $1.00 for
                                 day.json (pro.X402_PRICES). The bytes are pro.exports()'s, the
                                 same the key holders get for the same day.

    POST /posts                  $0.01 a post: an agent posts on the Atlas about a seller, an
                                 operator, a wallet or the market. The author is the wallet that
                                 paid; the post says whether it paid what it talks about (posts.py)
    GET /posts                   free: newest first, paged; ?about=<kind>:<id> for one thing
    GET /posts/<id>              free: one post and its replies
    POST /posts/<id>/hide        X-Atlas-Admin equal to ATLAS_ADMIN_TOKEN; off when that is unset

<file> is one of sellers.csv, buyers.csv, operators.csv, day.json. Both doors serve the
same files from the same pro.exports() call; this file only puts a gate in front of each.
The x402 door uses the same payTo, facilitator, network and live_refusal as /who: one
payment layer, one set of guards, no second way to take money.

WHO PAYS FOR WHAT, on purpose:
    200  report card                  paid
    300  ambiguous (candidates)       free
    400  not a hostname or wallet     free
    404  not in the registry          free
    503  no snapshot / stale          free
and for /watch/<wallet>:
    200  the report                   paid
    400  not one Base wallet address  free
    404  no x402 payment in window    free
    503  stale snapshot or window     free
and for /x402/export/<file>:
    200  the file                     paid
    404  not one of the four files    free, never asked to pay
    503  stale / no on-chain window   free
and for POST /posts:
    201  the post, stored             paid, stored only once the payment has settled, and with
                                      GitHub commits on, committed to the repository first
    202  the post, queued             paid and kept, but the commit failed; retried each minute
                                      and at shutdown, and the answer says so
    400  not JSON, bad field or text  free
    404  about or reply_to not found  free
    429  20 posts today from that wallet  free
    503  stale / no on-chain window   free
and on any path at all:
    400  an escaped / or \ (%2F, %5C) free: the payment layer and the router could read
                                      such a path differently, and once did (review of #142)
A refusal is decided BEFORE the payment layer is reached, so the buyer is
never even asked to sign for a non-answer. The x402 SDK also declines to
settle any response of 400 or above; that is the second lock, not the first.

Testnet by default (Base Sepolia, the keyless public facilitator).

REAL MONEY (Base mainnet) needs every one of these, or the script refuses to
start and says which is missing (live_refusal, tested in test_live_guard.py):
    --net mainnet                       said on purpose
    SELL_WHO_LIVE=real-money            said a second time, in the environment
    --facilitator cdp                   the keyless public one is testnet only
    a CDP key file that exists          read by path, never shown
    a payTo that is not a throwaway     test addresses are refused by name
    SELL_WHO_PUBLIC_URL, https          the address buyers are told they are paying for
Going live is Vilija's decision. See deploy/GO-LIVE.md.

    pip install "x402[evm,fastapi,httpx]" uvicorn
    SELL_WHO_PAY_TO=0x...  ./sell-who.py --port 8402

    pip install cdp-sdk                      # only for --facilitator cdp
    SELL_WHO_PAY_TO=0x...  ./sell-who.py --facilitator cdp     # still testnet

Proven 2026-09-17 on Base Sepolia: receipts in journal/2026-09-17-x402.md.

THE FUNNEL, counted and nothing else (Funnel): for each priced family (who, and each
export file) and each via tag (mcp when the address carried ?via=mcp, as every link the
Atlas MCP server gives out does; none otherwise), how many requests were
    offered    the payment layer answered 402 (terms sent)
    attempted  the request carried a payment header
    settled    the SDK settled: 2xx after payment, with its PAYMENT-RESPONSE header
A request whose payment fails is counted attempted and offered again. Only these
counters exist: no address, no wallet, no host asked about, no time of a request. They
live in memory, start at zero with the process, are free at GET /stats, and are printed
as one line to the log each hour.
"""

import argparse
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import who_service  # noqa: E402
import watch_service  # noqa: E402
import posts  # noqa: E402

NETWORKS = {"testnet": "eip155:84532", "mainnet": "eip155:8453"}
FACILITATOR = {"testnet": "https://x402.org/facilitator"}
LIVE_WORD = "real-money"
# Throwaway wallets made for test-network runs. Their keys sat in a local file an
# agent could read; real money must never be pointed at them.
TEST_ONLY_PAY_TO = {"0xcd4bbb6c35fde6b9c658b11f7bca6ace5c83521f",
                    "0x02ad39c14d7eecfcc0f1bebcebd9c7b79084e4c9"}

# $0.01: the going rate. `radar.py like` measured the median price of the 36
# sellers of intelligence about the x402 market at $0.01 (and of the 182 wide
# "market/intelligence" sellers at $0.012). The one seller at $0.25 has a
# scored, classified verdict and 907 calls behind it; we enter at the median
# and let the replay earn a higher price, not assert one.
PRICE = "$0.01"

DESCRIPTION = ("One x402 seller's report card before you pay them: what they sell, paid calls "
               "and payers in 30 days, price, rank of all sellers, rivals, and the day-by-day "
               "replay nobody else stored. Stamped with the snapshot date. Refusals are free.")


def public_url_problem(url):
    """Why this is not a usable public address, or None. https only: the URL is what a buyer
    is told they are paying for, and it is signed into the payment."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        return "must be a plain https:// address of this service, like https://who.example.com"
    if u.path not in ("", "/"):
        return "must be the site's root, without a path"
    return None


class PublicURL:
    """The address in the payment terms comes from configuration, never from the request.

    The payment library describes the resource being bought with the URL of the incoming
    request. Behind a proxy that URL is built from headers a caller can set (Host,
    X-Forwarded-Proto, X-Forwarded-Host). So this rewrites the request's scheme, server and
    Host to the configured public address before anything else sees it. Forwarded headers
    are not trusted at all (uvicorn runs with proxy_headers off). Pure ASGI, outermost."""

    def __init__(self, app, public_url):
        from urllib.parse import urlparse
        u = urlparse(public_url)
        self.app, self.scheme = app, u.scheme
        self.host = u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        default = self.port == (443 if u.scheme == "https" else 80)
        self.header = (self.host if default else "%s:%d" % (self.host, self.port)).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["scheme"] = self.scheme
            scope["server"] = (self.host, self.port)
            drop = (b"host", b"x-forwarded-proto", b"x-forwarded-host", b"x-forwarded-port", b"forwarded")
            scope["headers"] = [(b"host", self.header)] + [(k, v) for k, v in scope["headers"] if k.lower() not in drop]
        await self.app(scope, receive, send)


def live_refusal(net, facilitator, pay_to, cdp_key_file, env):
    """Why this process must not take real money, or None when it may.
    Pure: no network, no file is opened. Every condition is one a person has
    to have set deliberately."""
    if net != "mainnet":
        return None
    if env.get("SELL_WHO_LIVE") != LIVE_WORD:
        return "mainnet needs SELL_WHO_LIVE=%s in the environment, set on purpose" % LIVE_WORD
    if facilitator != "cdp":
        return "mainnet needs --facilitator cdp; the keyless public facilitator is test network only"
    key = os.path.expanduser(cdp_key_file or "")
    if not key or not os.path.isfile(key):
        return "mainnet needs --cdp-key-file pointing at a key file that exists"
    if not pay_to or (pay_to or "").lower() in TEST_ONLY_PAY_TO:
        return "mainnet needs a real payTo; %s is a throwaway test address" % pay_to
    if not (pay_to.startswith("0x") and len(pay_to) == 42):
        return "mainnet payTo must be a 0x address of 42 characters"
    why = public_url_problem(env.get("SELL_WHO_PUBLIC_URL"))
    if why:
        return "mainnet needs SELL_WHO_PUBLIC_URL; it %s" % why
    return None


# What one paid answer looks like (made-up host): the Bazaar listing and the docs page both show it.
WHO_EXAMPLE = {
    "ok": True, "host": "api.example.com", "as_of": "2026-09-20", "age_days": 0,
    "sells": "What this seller says it sells", "calls_30d": 1284, "payers_30d": 96,
    "est_take_30d_list_price": 25.68, "price_med": 0.02, "rank_by_calls": 61,
    "rank_by_money": 140, "sellers_in_market": 1998, "share_of_paid_calls_pct": 0.328,
    "replay": [{"date": "2026-09-19", "calls": 1240, "payers": 94},
               {"date": "2026-09-20", "calls": 1284, "payers": 96}],
    "rivals": [{"host": "rival.example", "calls": 410, "price_med": 0.05, "sells": "…"}],
    "going_rate": 0.05, "you_are": "under", "caveats": ["…"]}


def discovery_extension():
    """How the Bazaar directory should describe this endpoint to agents. Being
    listed there is the promotion: it is where agents look for things to buy."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
    return declare_discovery_extension(
        path_params_schema={
            "properties": {"target": {
                "type": "string",
                "description": "The x402 seller to look up: a hostname (api.example.com) "
                               "or a payTo wallet address."}},
            "required": ["target"]},
        output=OutputConfig(example=WHO_EXAMPLE))


WATCH_DESCRIPTION = ("What one agent wallet spent over x402 on Base, read from the chain: payments and USDC per "
                     "day, by seller and category, the change against the day before, new sellers, and for "
                     "every seller paid its listed price against what was paid per call, the category's going "
                     "rate, what other wallets pay it, and whether it was up at the last check. Refusals are free.")


def watch_discovery_extension():
    """The Bazaar listing for GET /watch/<wallet>: one wallet in the path, days in the query."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
    return declare_discovery_extension(
        input={"days": 7},
        input_schema={"properties": {"days": {"type": "integer", "minimum": 1, "maximum": 8,
                                              "description": "how many of the newest pulled days, default 7"}}},
        path_params_schema={
            "properties": {"wallet": {"type": "string", "pattern": "^0x[0-9a-fA-F]{40}$",
                                      "description": "the Base wallet address an agent pays from"}},
            "required": ["wallet"]},
        output=OutputConfig(example={
            "ok": True, "chain": "Base", "wallets": ["0x2222222222222222222222222222222222222222"],
            "window": {"days": 2, "dates": ["2026-09-25", "2026-09-26"], "to": "2026-09-26", "classified_days": 2},
            "total": {"payments": 412, "usdc": 4.12, "sellers_paid": 3,
                      "per_day": [{"date": "2026-09-25", "payments": 120, "usdc": 1.2},
                                  {"date": "2026-09-26", "payments": 292, "usdc": 2.92}],
                      "change": {"available": True, "usdc_pct": 143.3},
                      "new_sellers": ["search.example"],
                      "sellers": [{"host": "api.example.com", "category": "crypto & markets", "payments": 300,
                                   "usdc": 3.0, "paid_per_call": 0.01, "listed": {"min": 0.01, "median": 0.01, "max": 0.01},
                                   "paid_above_list": False, "going_rate": 0.01, "above_going_rate": False,
                                   "others": {"payments": 810, "wallets": 14, "paid_per_call": 0.01},
                                   "status": {"state": "up"}}]},
            "findings": ["Spend rose 143.3% on 2026-09-26 against the day before ($2.92 against $1.20)."],
            "caveats": ["…"]}))


# What each file is, for the Bazaar listing: honest, short, and with a small example of
# the shape (made-up hosts and wallets, never a real one).
EXPORT_LISTING = {
    "sellers.csv": ("Every x402 seller in today's registry snapshot, one row each: what it sells, its price, "
                    "the registry's own call counts, and beside them the x402 payments read off Base in the "
                    "last window, payer wallets and who the top payers are. CSV. Stamped with the snapshot date.",
                    "host,category,sells,price_min,price_max,endpoints,chains,calls_30d_self_reported,"
                    "payers_30d_self_reported,x402_payments,x402_usdc,usdc_other_means,payer_wallets,top3_share_pct,"
                    "concentration,top_payer_wallets,operator_group,operator_hosts\n"
                    "api.example.com,crypto & markets,Token prices for agents,0.01,0.01,1,Base,1284,96,"
                    "310,3.1,0.0,12,41,spread,0x1111111111111111111111111111111111111111:80,,1\n"),
    "buyers.csv": ("Every wallet that made an x402 payment to a seller in the last on-chain window on Base: how "
                   "many payments, how much USDC, how many sellers, what kinds of things it bought, and whether it "
                   "paid three or more sellers. CSV. Wallets are addresses only; nobody is named.",
                   "wallet,chain,x402_payments,x402_usdc,usdc_other_means,sellers_paid_x402,agent,categories,top_sellers\n"
                   "0x2222222222222222222222222222222222222222,Base,412,4.12,0.0,5,yes,"
                   "crypto & markets;search,api.example.com:300;search.example:112\n"),
    "operators.csv": ("Every group of x402 hosts paid into one wallet in the last window: usually one operator "
                      "running several hosts, sometimes a platform collecting for several. CSV.",
                      "group,name,hosts,host_list,wallets,paid_hosts,x402_payments,x402_usdc,usdc_other_means,"
                      "calls_30d_self_reported,top_payer_wallets\n"
                      "example,example.com,2,a.example.com;b.example.com,1,2,520,5.2,0.0,1900,"
                      "0x3333333333333333333333333333333333333333:200\n"),
    "day.json": ("The whole day in one JSON file: every seller, every paying wallet and every wallet group, "
                 "with the on-chain window's dates and totals and the caveats. Stamped with the snapshot date.",
                 {"ok": True, "as_of": "2026-09-25", "sellers_in_market": 1998,
                  "on_chain": {"available": True, "chain": "Base", "as_of": "2026-09-25", "dates": ["2026-09-25"],
                               "hours": 24, "totals": {"payments_x402": 5210, "usdc_x402": 61.4}},
                  "columns": {"sellers": ["host", "…"], "buyers": ["wallet", "…"], "operators": ["group", "…"]},
                  "sellers": [{"host": "api.example.com", "x402_payments": 310, "…": "…"}],
                  "buyers": [{"wallet": "0x2222222222222222222222222222222222222222", "x402_payments": 412, "…": "…"}],
                  "operators": [{"group": "example", "hosts": 2, "…": "…"}],
                  "caveats": ["…"], "source": "x402 discovery registry, daily snapshots; on-chain from a daily Base pull"}),
}


def export_discovery_extension(name):
    """The Bazaar listing for one paid export: no inputs, and an example of what comes back.
    A CSV is text, not JSON: its example is declared as a string and its output as text/csv."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
    example = EXPORT_LISTING[name][1]
    if not name.endswith(".csv"):
        return declare_discovery_extension(output=OutputConfig(example=example))
    ext = declare_discovery_extension(output=OutputConfig(example=example, schema={"type": "string"}))
    ext["bazaar"]["info"]["output"].update(type="text", format="csv")
    return ext


POSTS_DESCRIPTION = ("Post on the Infoharmoni Atlas about one x402 seller, operator, wallet or the market on Base: "
                     "plain text, 1 to 500 characters, $0.01 a post. The wallet that pays is the author. Each post "
                     "on a seller or operator says whether that wallet made an x402 payment to it in the Atlas's "
                     "loaded on-chain window. Free to read at GET /posts. Refusals are free.")


def posts_discovery_extension():
    """The Bazaar listing for POST /posts: the JSON body it takes, and what comes back."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
    return declare_discovery_extension(
        input={"about": {"kind": "seller", "id": "api.example.com"},
               "text": "Paid them 40 times this week for token prices; answers came back in under a second."},
        input_schema={
            "properties": {
                "about": {"type": "object", "description": "what the post is about, as the Atlas names it",
                          "properties": {"kind": {"type": "string", "enum": list(posts.KINDS)},
                                         "id": {"type": "string",
                                                "description": "seller: its host; operator: its group slug as in "
                                                               "/o/<slug>/; wallet: a 0x address; market: base"}},
                          "required": ["kind", "id"]},
                "text": {"type": "string", "minLength": 1, "maxLength": posts.MAX_TEXT,
                         "description": "plain text: no HTML, no control characters, at most %d links"
                                        % posts.MAX_LINKS},
                "reply_to": {"type": "string", "description": "optional: the id of a post this answers"}},
            "required": ["about", "text"]},
        body_type="json",
        output=OutputConfig(example={
            "ok": True, "post": {"id": "p_0123456789abcdef", "author": "0x" + "22" * 20,
                                 "about": {"kind": "seller", "id": "api.example.com"},
                                 "text": "Paid them 40 times this week for token prices; answers came back in under a second.",
                                 "reply_to": None, "time": "2026-09-27T10:00:00Z", "paid_it": True,
                                 "window": {"as_of": "2026-09-26", "dates": ["2026-09-26"], "hours": 24}},
            "note": "paid_it is true when the author wallet made an x402 payment to that seller …"}))


def x402_routes(pay_to, net, price=None):
    """Every priced route and its terms. One payTo, one network, for all of them.
    The export routes are literal paths: anything else under /x402/export/ is refused,
    404 and unbilled, before the payment layer is reached (see build())."""
    import pro
    accepts = lambda p: {"scheme": "exact", "payTo": pay_to, "price": p, "network": NETWORKS[net]}
    routes = {"GET /who/:target": {
        "accepts": accepts(price or PRICE),
        "description": DESCRIPTION, "mimeType": "application/json",
        "serviceName": "Infoharmoni Radar who",
        "tags": ["x402", "due-diligence", "seller-report", "market-data", "replay"],
        "extensions": discovery_extension()},
        "GET /watch/:wallet": {
        "accepts": accepts(watch_service.PRICE),
        "description": WATCH_DESCRIPTION, "mimeType": "application/json",
        "serviceName": pro.market.BRAND + " watch",
        "tags": ["x402", "agent-spend", "wallet", "spend-monitoring", "market-data"],
        "extensions": watch_discovery_extension()}}
    for name, p in pro.X402_PRICES.items():
        routes["GET " + pro.X402_PATH + name] = {
            "accepts": accepts(p),
            "description": "%s Pro, %s: %s" % (pro.market.BRAND, name, EXPORT_LISTING[name][0]),
            "mimeType": "text/csv" if name.endswith(".csv") else "application/json",
            "serviceName": pro.market.BRAND + " Pro export",
            "tags": ["x402", "market-data", "dataset", "atlas", "sellers" if name != "buyers.csv" else "buyers"],
            "extensions": export_discovery_extension(name)}
    routes["POST " + posts.PATH] = {
        "accepts": accepts(posts.PRICE),
        "description": POSTS_DESCRIPTION, "mimeType": "application/json",
        "serviceName": pro.market.BRAND + " posts",
        "tags": ["x402", "social", "agents", "reviews", "market-data"],
        "extensions": posts_discovery_extension()}
    return routes


def x402_payment_middleware(pay_to, net, facilitator="public", cdp_key_file=None, price=None, client=None):
    """The real payment layer. Imported here so everything else in this file,
    and every test, works without the payment SDK installed.

    facilitator="public" is the keyless x402.org one (test network only).
    facilitator="cdp" is Coinbase's, authenticated with a key file that is
    read by path inside this process and never shown (cdp_facilitator.py).
    `client` stands in for the facilitator in tests; nothing else passes it."""
    from x402 import x402ResourceServer
    from x402.http import HTTPFacilitatorClient, FacilitatorConfig, HTTPRequestContext, x402HTTPResourceServer
    from x402.http.middleware.fastapi import payment_middleware
    from x402.mechanisms.evm.exact import register_exact_evm_server

    if client is None and facilitator == "cdp":
        import cdp_facilitator
        client = cdp_facilitator.facilitator_client(cdp_key_file or cdp_facilitator.DEFAULT_KEY_FILE)
    elif client is None:
        client = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR[net]))
    server = x402ResourceServer(client)
    register_exact_evm_server(server)
    # ":target" is one path segment. Anything else under /who/ never gets this
    # far: refuse_before_billing answers it first (see build()).
    routes = x402_routes(pay_to, net, price)
    mw = payment_middleware(routes, server)
    # The second lock (see build()): the SDK's own route matching, on the same server and
    # routes, asked about a path before it goes on. Some SDK versions match the raw
    # (still-escaped) path and Starlette routes the decoded one, so both must be priced.
    matcher = x402HTTPResourceServer(server, routes)

    def priced(method, raw_path, path):
        return all(matcher.requires_payment(HTTPRequestContext(adapter=None, path=p, method=method))
                   for p in (raw_path, path))
    mw.priced = priced
    return mw


class SnapshotSync:
    """For a host with no disk: keep a temporary store in line with the
    published manifest (snapshot_handoff.py). Once before serving, then hourly.
    A failed sync never stops the server; who_service then refuses, unpaid,
    because there is no snapshot or it is stale."""

    def __init__(self, url, every=3600, flows_url=None):
        import tempfile
        self.url, self.every, self.last = url, every, None
        self.store = tempfile.mkdtemp(prefix="radar-store-")
        who_service.radar.STORE = self.store
        self.flows_url, self.chain_store, self.chain_last = flows_url, None, None
        if flows_url:
            self.chain_store = tempfile.mkdtemp(prefix="flows-store-")
            who_service.CHAIN_STORE = self.chain_store

    def once(self):
        import snapshot_handoff
        try:
            r = snapshot_handoff.fetch(self.url, self.store)
            self.last = {"as_of": r["as_of"], "days": len(r["kept"]) + len(r["fetched"]),
                         "fetched": len(r["fetched"]), "rejected": r["rejected"]}
        except Exception as e:
            self.last = {"error": str(e) if isinstance(e, snapshot_handoff.HandoffError)
                         else type(e).__name__}
        if self.flows_url:
            # the on-chain window: a failure here never stops selling the report card;
            # the answer then says on_chain is not available
            try:
                import flows_handoff
                r = flows_handoff.fetch(self.flows_url, self.chain_store)
                name, _ = who_service.newest_chain()
                self.chain_last = {"newest": name, "fetched": len(r["fetched"]), "had": len(r["had"]),
                                   "rejected": r["rejected"]}
            except Exception as e:
                self.chain_last = {"error": type(e).__name__ if not hasattr(e, "args") or not e.args else str(e)[:120]}
        return self.last

    async def forever(self):
        import asyncio
        from fastapi.concurrency import run_in_threadpool
        while True:
            await asyncio.sleep(self.every)
            await run_in_threadpool(self.once)


class Funnel:
    """Aggregated counters of the paid paths: offered, attempted, settled, by family and via
    tag. Nothing about a request is kept but which counter it moved."""

    STAGES = ("offered", "attempted", "settled")
    VIAS = ("mcp", "none")

    def __init__(self, now=None):
        import pro
        self.families = ["who", "watch"] + list(pro.X402_PRICES) + ["posts"]
        self.started = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        self._lock = threading.Lock()
        self._n = {f: {v: dict.fromkeys(self.STAGES, 0) for v in self.VIAS} for f in self.families}

    def family(self, path, method="GET"):
        """Which priced family a (decoded) path belongs to, or None."""
        import pro
        if path == posts.PATH:
            return "posts" if method == "POST" else None
        if path.startswith("/who/"):
            return "who"
        if path.startswith("/watch/"):
            return "watch"
        if path.startswith(pro.X402_PATH) and path[len(pro.X402_PATH):] in pro.X402_PRICES:
            return path[len(pro.X402_PATH):]
        return None

    @staticmethod
    def via(query):
        """mcp only when the address said exactly via=mcp; any other value counts as none,
        so a caller cannot grow the table."""
        return "mcp" if parse_qs(query or "").get("via") == ["mcp"] else "none"

    def count(self, family, via, stage):
        with self._lock:
            self._n[family][via][stage] += 1

    def note(self, path, query, paid_header, status, settled_header, method="GET"):
        """Count one request that went through the payment layer."""
        fam = self.family(path, method)
        if fam is None:
            return
        v = self.via(query)
        if paid_header:
            self.count(fam, v, "attempted")
        if status == 402:
            self.count(fam, v, "offered")
        elif paid_header and 200 <= status < 300 and settled_header:
            self.count(fam, v, "settled")

    def snapshot(self):
        with self._lock:
            counts = {f: {v: dict(c) for v, c in by.items()} for f, by in self._n.items()}
        return {"ok": True, "since": self.started, "counts": counts,
                "stages": {"offered": "the payment layer answered 402 with terms",
                           "attempted": "the request carried a payment header",
                           "settled": "the payment settled and the answer was served (2xx)"},
                "via": "mcp when the address carried ?via=mcp, none otherwise",
                "note": "aggregated counts since the process started; no address, wallet or host asked about is kept"}

    def line(self):
        snap = self.snapshot()
        parts = []
        for f, by in snap["counts"].items():
            for v, c in by.items():
                if any(c.values()):
                    parts.append("%s/%s %d/%d/%d" % (f, v, c["offered"], c["attempted"], c["settled"]))
        return "sell-who: funnel since %s (offered/attempted/settled): %s" % (
            snap["since"], ", ".join(parts) or "nothing yet")

    async def forever(self, every=3600):
        import asyncio
        while True:
            await asyncio.sleep(every)
            print(self.line(), flush=True)


PAYMENT_HEADERS = ("payment-signature", "x-payment")
SETTLED_HEADERS = ("payment-response", "x-payment-response")


BUDGET = 4      # unpaid pre-checks computed at once; beyond it, 503 busy, unpaid. Answers are cached
                # per snapshot version, so a paying buyer's second call costs nothing.


def build(payment_mw, info=None, max_age_days=who_service.MAX_AGE_DAYS, sync=None, public_url=None,
          budget=BUDGET, gate=None, funnel=None, funnel_every=3600, post_store=None, post_sync=None,
          post_storage=None, env=None, posts_open=True):
    """The app. `payment_mw` is any (request, call_next) middleware: the real
    x402 one in production, a stub in tests. `gate` decides who may take a Pro
    export (pro.Gate); without one, Pro says it is not switched on. `funnel`
    counts the paid paths (Funnel); one is made when none is given. `post_store`
    holds the posts (posts.Store; an in-memory one when none is given), `post_sync`
    commits them (posts.GitHub, or None), `env` is where ATLAS_ADMIN_TOKEN is read."""
    from fastapi import FastAPI, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse, Response
    import pro
    gate = gate or pro.Gate(None)

    app = FastAPI(title="Infoharmoni Radar · who")
    funnel = funnel or Funnel()
    app.state.funnel = funnel
    store = post_store if post_store is not None else posts.Store()
    app.state.posts = store
    env = os.environ if env is None else env
    storage = post_storage or ("memory only: posts live in this process (POSTS_REPO is not set)"
                               if post_sync is None else repr(post_sync))

    async def start_funnel_log():
        import asyncio
        app.state.funnel_task = asyncio.create_task(funnel.forever(funnel_every))
    app.router.on_startup.append(start_funnel_log)
    if sync is not None:
        async def start_sync():
            import asyncio
            app.state.sync_task = asyncio.create_task(sync.forever())
        app.router.on_startup.append(start_sync)
    commits = post_sync is not None and post_sync.commits

    def safe(fn, *a, **k):
        """A commit that never raises: an error becomes a status carrying only its type, since
        a message could hold anything and a type cannot."""
        try:
            return fn(*a, **k)
        except Exception as e:
            post_sync.last = {"ok": False, "error": type(e).__name__}
            return post_sync.last

    if commits:
        async def retry_posts_forever():
            # Each paid post is committed before it is answered (see pay()); this only retries
            # what could not be, and hides, once a minute.
            import asyncio
            while True:
                await asyncio.sleep(posts.RETRY_EVERY)
                r = await run_in_threadpool(safe, post_sync.drain, store)
                if r is not None:
                    print("sell-who: posts commit: %s" % json.dumps(r), flush=True)

        async def start_commits():
            import asyncio
            app.state.posts_task = asyncio.create_task(retry_posts_forever())
        app.router.on_startup.append(start_commits)

        async def commit_on_shutdown():
            r = await run_in_threadpool(safe, post_sync.drain, store)
            print("sell-who: posts at shutdown: %s, %d still waiting" % (json.dumps(r), len(store.pending)),
                  flush=True)
        app.router.on_shutdown.append(commit_on_shutdown)

    # Registered first, so it sits INSIDE the pre-check below.
    @app.middleware("http")
    async def pay(request: Request, call_next):
        response = await payment_mw(request, call_next)
        # Only what passed the pre-check gets here, so a refusal is never counted as an offer.
        funnel.note(request.url.path, request.scope.get("query_string", b"").decode("latin-1"),
                    any(request.headers.get(h) for h in PAYMENT_HEADERS), response.status_code,
                    any(response.headers.get(h) for h in SETTLED_HEADERS), request.method)
        # A post the handler prepared is stored only now, and only if its payment settled.
        staged = getattr(request.state, "post_staged", None)
        if staged is not None:
            if 200 <= response.status_code < 300 and settled(response):
                return await keep(staged, response)
            store.release(staged["author"])
        return response

    async def keep(post, response):
        """A paid post, stored before it is answered. With commits on, it is committed to the
        repository first: 201 when it is there. When the commit fails, the post stays queued
        (retried each minute and at shutdown) and the answer is 202, saying so. Without commits,
        201 and stored "memory", as /health says."""
        store.commit(post)
        stored = "memory"
        if commits:
            await run_in_threadpool(safe, post_sync.flush, store, post["time"][:10])
            stored = "queued" if store.waiting(post["id"]) else "repository"
        raw = getattr(response, "body", None)
        if raw is None:
            raw = b"".join([c async for c in response.body_iterator])
        try:
            out = json.loads(raw)
        except ValueError:
            out = {"ok": True, "post": posts.public(post)}
        out["stored"] = stored
        if stored == "queued":
            out["say"] = ("paid and kept; the public record could not be written just now and is retried "
                          "every minute")
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
        return JSONResponse(out, status_code=202 if stored == "queued" else 201, headers=headers)

    import asyncio
    slots = asyncio.Semaphore(budget)
    priced = getattr(payment_mw, "priced", None)       # the real x402 layer has it; test stubs do not

    def unpriced(request, raw):
        """A path headed for a paid handler that the payment layer would not price: refused,
        unbilled, rather than handed over for free."""
        if priced is None or priced(request.method, raw, request.url.path):
            return None
        return JSONResponse({"ok": False, "charged": False, "error": "unpriced_path",
                             "say": "this address is not one the payment layer prices; ask for the plain path"},
                            status_code=400, headers={"cache-control": "no-store"})

    # Registered last, so it runs FIRST: refusals leave here, unbilled.
    @app.middleware("http")
    async def refuse_before_billing(request: Request, call_next):
        # First, for every path: an escaped / or \ is refused. The payment layer and the
        # router may disagree on what such a path is (one reads it escaped, one decoded),
        # and that disagreement once handed out paid answers for free.
        raw = raw_path(request.scope)
        if ENCODED_SLASH.search(raw):
            return JSONResponse({"ok": False, "charged": False, "error": "encoded_slash"},
                                status_code=400, headers={"cache-control": "no-store"})
        path = request.url.path
        if path.startswith(pro.X402_PATH):
            return await export_before_billing(request, call_next, path[len(pro.X402_PATH):], raw)
        if path == posts.PATH or path.startswith(posts.PATH + "/"):
            return await posts_before_billing(request, call_next, path, raw)
        if path.lower().startswith(posts.PATH):
            # The payment layer matches /Posts as /posts; the router does not. Nothing to offer.
            return JSONResponse({"ok": False, "charged": False, "error": "no_such_path"}, status_code=404,
                                headers={"cache-control": "no-store"})
        if path.startswith("/watch/"):
            return await watch_before_billing(request, call_next, unquote(path[len("/watch/"):]), raw)
        if path.startswith("/who/") and request.method != "GET":
            # Only GET is priced, so only GET may exist here. No HEAD, no POST.
            return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"},
                                status_code=405, headers={"allow": "GET"})
        if request.method == "GET" and path.startswith("/who/"):
            target = unquote(path[len("/who/"):])
            if not who_service.valid_target(target):          # free, instant, no slot needed
                code, body = who_service.answer(target, None, max_age_days)
            elif unpriced(request, raw) is not None:
                return unpriced(request, raw)
            elif slots.locked():
                code, body = 503, {"ok": False, "charged": False, "error": "busy",
                                   "say": "too many unpaid requests at once; try again in a moment"}
            else:
                async with slots:
                    # the engine reads a megabyte of JSON; keep it off the event loop
                    code, body = await run_in_threadpool(who_service.answer, target, None, max_age_days)
            if code != 200:
                return JSONResponse(body, status_code=code, headers={"cache-control": "no-store"})
            request.state.who = body
        return await call_next(request)

    async def watch_before_billing(request, call_next, wallet, raw):
        """The paid single-wallet watch. A malformed address, a wallet with no x402 payment in
        the window, a stale store: each leaves here, unbilled."""
        if request.method != "GET":
            return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"},
                                status_code=405, headers={"allow": "GET"})
        days = request.query_params.get("days")
        if spend_watch_malformed(wallet, days):           # free, instant, no slot needed
            code, body = watch_service.answer(wallet, days, one=True, max_age_days=max_age_days)
            return JSONResponse(body, status_code=code, headers={"cache-control": "no-store"})
        refusal = unpriced(request, raw)
        if refusal is not None:
            return refusal
        if slots.locked():
            return JSONResponse({"ok": False, "charged": False, "error": "busy",
                                 "say": "too many unpaid requests at once; try again in a moment"},
                                status_code=503, headers={"cache-control": "no-store"})
        async with slots:
            code, body = await run_in_threadpool(watch_service.answer, wallet, days, True, None, max_age_days)
        if code != 200:
            return JSONResponse(body, status_code=code, headers={"cache-control": "no-store"})
        request.state.watch = body
        return await call_next(request)

    async def export_before_billing(request, call_next, name, raw):
        """The x402 door to the Pro files. Everything that is not a file ready to hand over
        leaves here, unbilled: another method, a name that is not one of the four, a stale
        store, a file that needs the on-chain window when none is loaded."""
        if request.method != "GET":
            return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"},
                                status_code=405, headers={"allow": "GET"})
        if name not in pro.X402_PRICES:
            return JSONResponse({"ok": False, "charged": False, "error": "no_such_export",
                                 "exports": sorted(pro.X402_PRICES)}, status_code=404,
                                headers={"cache-control": "no-store"})
        refusal = unpriced(request, raw)
        if refusal is not None:
            return refusal
        if slots.locked():
            return JSONResponse({"ok": False, "charged": False, "error": "busy",
                                 "say": "too many unpaid requests at once; try again in a moment"},
                                status_code=503, headers={"cache-control": "no-store"})
        async with slots:
            code, files = await run_in_threadpool(pro.exports, None, max_age_days)
        refusal = export_refusal(name, code, files)
        if refusal is not None:
            return refusal
        request.state.export = files
        return await call_next(request)

    def post_refusal(r, origin=None):
        return JSONResponse(r.body(), status_code=r.status,
                            headers=dict(posts.cors(origin), **{"cache-control": "no-store"}))

    async def read_body(request):
        """The body, at most posts.MAX_BODY bytes; None when it is longer."""
        n = request.headers.get("content-length")
        if n is not None and (not n.isdigit() or int(n) > posts.MAX_BODY):
            return None
        buf = b""
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > posts.MAX_BODY:
                return None
        return buf

    async def posts_before_billing(request, call_next, path, raw):
        """The posts paths. Reads are free and pass straight on. A POST /posts leaves here,
        unbilled, unless it is a post that could be stored the moment its payment settles."""
        m, origin = request.method, request.headers.get("origin")
        one = POST_PATH.match(path)
        hide = HIDE_PATH.match(path)
        if path != posts.PATH and not one and not hide:
            return JSONResponse({"ok": False, "charged": False, "error": "no_such_path"}, status_code=404,
                                headers={"cache-control": "no-store"})
        if m == "OPTIONS" and not hide:
            return Response(status_code=204, headers=posts.cors(origin))
        if hide:
            if m != "POST":
                return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"},
                                    status_code=405, headers={"allow": "POST"})
            return await call_next(request)
        if m == "GET":
            return await call_next(request)
        if m != "POST" or one:
            return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"}, status_code=405,
                                headers={"allow": "GET, POST" if path == posts.PATH else "GET"})
        if not posts_open:
            # A paid post must outlive this process. Until posts are committed somewhere durable,
            # posting is refused here, before any payment is asked.
            return JSONResponse({"ok": False, "charged": False, "error": "posting_not_open",
                                 "say": "posting opens once posts are stored durably; nothing was charged"},
                                status_code=503, headers={"cache-control": "no-store"})
        raw_body = await read_body(request)
        try:
            if raw_body is None:
                raise posts.Refused(400, "body_size", "send a JSON body of 1 to %d bytes" % posts.MAX_BODY)
            draft = posts.parse(raw_body)
            claimed = posts.claimed_payer(next((request.headers.get(h) for h in PAYMENT_HEADERS
                                                if request.headers.get(h)), None))
            if claimed and store.today_count(claimed) >= posts.PER_DAY:
                raise posts.Refused(429, "rate_limited", "%d posts a wallet a UTC day; this wallet has made them"
                                    % posts.PER_DAY)
            if draft["reply_to"] and not store.exists(draft["reply_to"]):
                raise posts.Refused(404, "no_such_post", "reply_to names no post")
        except posts.Refused as r:
            return post_refusal(r)
        refusal = unpriced(request, raw)
        if refusal is not None:
            return refusal
        if slots.locked():
            return JSONResponse({"ok": False, "charged": False, "error": "busy",
                                 "say": "too many unpaid requests at once; try again in a moment"},
                                status_code=503, headers={"cache-control": "no-store"})
        async with slots:
            index, why = await run_in_threadpool(posts.current_index, None, max_age_days)
        why = why or index.check(draft["about"])
        if why is not None:
            return post_refusal(why)
        request.state.post_draft, request.state.post_index = draft, index
        return await call_next(request)

    if public_url:
        app.add_middleware(PublicURL, public_url=public_url)      # added last, so it runs first

    @app.get("/health")
    async def health():
        newest = who_service.newest_snapshot_date()
        out = {"ok": True, "price": PRICE, "as_of": newest.isoformat() if newest else None}
        out.update(info or {})
        out["atlas"] = pro.market.BRAND + ": " + pro.market.BRAND_WHAT
        out["pro"] = gate.enabled
        out["x402_exports"] = {pro.X402_PATH + n: p for n, p in pro.X402_PRICES.items()}
        out["watch"] = {"/watch/<wallet>": watch_service.PRICE, "/pro/watch": "Pro key"}
        if sync is not None:
            out["snapshots"] = sync.last
            if sync.flows_url:
                out["on_chain"] = sync.chain_last
        out["posts"] = dict(store.counts(), open=posts_open, price=posts.PRICE, post_at="POST " + posts.PATH,
                            read_at="GET " + posts.PATH, storage=storage,
                            last_commit=post_sync.last if post_sync is not None else None,
                            hiding="on" if env.get("ATLAS_ADMIN_TOKEN") else "off")
        return out

    @app.get("/stats")
    async def stats():
        out = funnel.snapshot()
        out["posts"] = store.counts()
        return JSONResponse(out, headers={"cache-control": "no-store"})

    def read_json(request, body, status=200):
        return JSONResponse(body, status_code=status, headers=dict(
            posts.cors(request.headers.get("origin")), **{"cache-control": "no-store"}))

    @app.get(posts.PATH)
    async def posts_list(request: Request):
        q = request.query_params
        try:
            about = posts.parse_about(q["about"]) if "about" in q else None
            page = int(q.get("page") or 1)
            per = int(q.get("per_page") or posts.PAGE)
            if not (1 <= page <= 10000 and 1 <= per <= posts.MAX_PAGE):
                raise ValueError
        except posts.Refused as r:
            return read_json(request, r.body(), r.status)
        except ValueError:
            return read_json(request, {"ok": False, "error": "bad_page",
                                       "say": "page from 1, per_page 1 to %d" % posts.MAX_PAGE}, 400)
        xs, total, more = store.page(about, page, per)
        return read_json(request, {"ok": True, "about": about, "page": page, "per_page": per, "total": total,
                                   "next_page": page + 1 if more else None, "posts": xs, "note": posts.NOTE})

    @app.get(posts.PATH + "/{pid}")
    async def posts_one(request: Request, pid: str):
        got = store.one(pid)
        if got is None:
            return read_json(request, {"ok": False, "error": "no_such_post"}, 404)
        return read_json(request, dict(ok=True, note=posts.NOTE, **got))

    @app.post(posts.PATH)
    async def posts_new(request: Request):
        # Reached only after the payment layer verified a payment, with the draft the pre-check
        # prepared. The author is the wallet that signed that payment; nothing else is read.
        draft = getattr(request.state, "post_draft", None)
        index = getattr(request.state, "post_index", None)
        author = posts.author_of(getattr(request.state, "payment_payload", None))
        if draft is None or index is None or author is None:     # cannot happen while the pre-check stands
            return JSONResponse({"ok": False, "charged": False, "error": "not_prepared"}, status_code=500)
        if draft["reply_to"] and not store.exists(draft["reply_to"]):
            return JSONResponse({"ok": False, "charged": False, "error": "no_such_post"}, status_code=404)
        if not store.hold(author):                                # a 4xx here is never settled
            return JSONResponse({"ok": False, "charged": False, "error": "rate_limited",
                                 "say": "%d posts a wallet a UTC day" % posts.PER_DAY}, status_code=429)
        kind = draft["about"]["kind"]
        post = store.make(author, draft, index.paid_it(author, draft["about"]),
                          index.window if kind in ("seller", "operator") else None)
        request.state.post_staged = post
        return JSONResponse({"ok": True, "post": posts.public(post), "note": posts.NOTE}, status_code=201,
                            headers={"cache-control": "no-store"})

    @app.post(posts.PATH + "/{pid}/hide")
    async def posts_hide(request: Request, pid: str):
        # The admin token is compared and forgotten: never logged, never echoed.
        if not env.get("ATLAS_ADMIN_TOKEN"):
            return JSONResponse({"ok": False, "error": "hiding_off"}, status_code=403)
        if not posts.admin_ok(request.headers.get(posts.ADMIN_HEADER), env):
            return JSONResponse({"ok": False, "error": "not_allowed"}, status_code=401)
        if not store.hide(pid):
            return JSONResponse({"ok": False, "error": "no_such_post"}, status_code=404)
        return JSONResponse({"ok": True, "hidden": pid}, headers={"cache-control": "no-store"})

    @app.get("/who/{target}")
    async def who_route(request: Request, target: str):
        body = getattr(request.state, "who", None)
        if body is None:      # cannot happen while the pre-check stands; never serve if it does
            return JSONResponse({"ok": False, "charged": False, "error": "not_prepared"},
                                status_code=500)
        return JSONResponse(body, headers={"cache-control": "no-store"})

    @app.get("/watch/{wallet}")
    async def watch_route(request: Request, wallet: str):
        body = getattr(request.state, "watch", None)
        if body is None:      # cannot happen while the pre-check stands; never serve if it does
            return JSONResponse({"ok": False, "charged": False, "error": "not_prepared"}, status_code=500)
        return JSONResponse(body, headers={"cache-control": "no-store"})

    @app.options("/pro/watch")
    async def pro_watch_preflight():
        # The /watch/ page on the Atlas's own site calls this from the viewer's browser.
        return Response(status_code=204, headers=WATCH_CORS)

    @app.get("/pro/watch")
    async def pro_watch(request: Request):
        # Not an x402 route: the key is the gate, with the same per-key limits as the files.
        headers = dict(WATCH_CORS, **{"cache-control": "no-store"})
        code, why = await run_in_threadpool(gate.check, request.headers.get(pro.HEADER))
        if code != 200:
            if code == 401:
                headers["www-authenticate"] = pro.HEADER
            if code == 429:
                headers["retry-after"] = str(why["retry_after"])
            return JSONResponse(why, status_code=code, headers=headers)
        code, body = await run_in_threadpool(watch_service.answer, request.query_params.get("wallets"),
                                             request.query_params.get("days"), False, None, max_age_days)
        return JSONResponse(body, status_code=code, headers=headers)

    @app.get("/pro")
    async def pro_route():
        return JSONResponse(pro.describe(), headers={"cache-control": "no-store"})

    @app.get("/pro/export/{name}")
    async def pro_export(request: Request, name: str):
        # Not an x402 route: the payment layer lets it pass, and the key is the gate.
        # The key is read from the header and handed to the gate; it is never logged,
        # echoed, or kept (the gate holds its sha256).
        if name not in pro.EXPORTS:
            return JSONResponse({"ok": False, "error": "no_such_export", "exports": sorted(pro.EXPORTS)},
                                status_code=404)
        code, why = await run_in_threadpool(gate.check, request.headers.get(pro.HEADER))
        if code != 200:
            headers = {"cache-control": "no-store"}
            if code == 401:
                headers["www-authenticate"] = pro.HEADER
            if code == 429:
                headers["retry-after"] = str(why["retry_after"])
            return JSONResponse(why, status_code=code, headers=headers)
        code, files = await run_in_threadpool(pro.exports, None, max_age_days)
        return export_refusal(name, code, files) or export_file(name, files)

    @app.get(pro.X402_PATH + "{name}")
    async def x402_export(request: Request, name: str):
        # Reached only after the payment layer, and only with the files the pre-check prepared.
        files = getattr(request.state, "export", None)
        if files is None or name not in pro.X402_PRICES:   # cannot happen while the pre-check stands
            return JSONResponse({"ok": False, "charged": False, "error": "not_prepared"}, status_code=500)
        return export_file(name, files)

    return app


ENCODED_SLASH = re.compile(r"%(2f|5c)", re.IGNORECASE)
POST_PATH = re.compile(r"^/posts/p_[0-9a-f]{16}$")
HIDE_PATH = re.compile(r"^/posts/p_[0-9a-f]{16}/hide$")


def settled(response):
    """True when the payment layer's PAYMENT-RESPONSE header says the payment settled."""
    import base64
    import json as _json
    h = next((response.headers.get(k) for k in SETTLED_HEADERS if response.headers.get(k)), None)
    if not h:
        return False
    try:
        return _json.loads(base64.b64decode(h)).get("success") is True
    except Exception:
        return False

# Any origin may call /pro/watch from a browser: no cookie is ever read, the key in the
# header is the whole credential, and a page elsewhere cannot learn a key it was not given.
WATCH_CORS = {"access-control-allow-origin": "*", "access-control-allow-methods": "GET, OPTIONS",
              "access-control-allow-headers": "X-Atlas-Key, Accept", "access-control-max-age": "600",
              "vary": "Origin"}


def spend_watch_malformed(wallet, days):
    """True when /watch/<wallet> is refused on its shape alone: not exactly one Base address,
    or a bad days value. Such a request is answered without touching the store."""
    ws, why = watch_service.spend_watch.parse_wallets(wallet)
    return bool(why) or len(ws) != 1 or bool(watch_service.spend_watch.parse_days(days)[1])


def raw_path(scope):
    """The request path as it arrived, still escaped, without the query."""
    raw = scope.get("raw_path")
    if raw is None:
        from urllib.parse import quote
        return quote(scope.get("path") or "")
    return raw.split(b"?", 1)[0].decode("latin-1")


def export_refusal(name, code, files):
    """Why this export cannot be handed over, as a response, or None when it can. Shared by both doors."""
    from fastapi.responses import JSONResponse
    if code != 200:
        return JSONResponse(files, status_code=code, headers={"cache-control": "no-store"})
    if files[name] is None:
        return JSONResponse({"ok": False, "error": "on_chain_not_loaded", "as_of": files["_as_of"],
                             "say": "no fresh on-chain window is loaded on this host, and %s is nothing "
                                    "without it; sellers.csv and day.json still serve" % name},
                            status_code=503, headers={"cache-control": "no-store"})
    return None


def export_file(name, files):
    """One export, exactly the bytes pro.exports() built. Shared by both doors."""
    from fastapi.responses import Response
    kind = "text/csv; charset=utf-8" if name.endswith(".csv") else "application/json"
    stem, ext = name.rsplit(".", 1)
    return Response(files[name], media_type=kind, headers={
        "cache-control": "private, no-store",
        "content-disposition": 'attachment; filename="atlas-%s-%s.%s"' % (stem, files["_as_of"], ext)})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8402")))
    ap.add_argument("--host", default=os.environ.get("SELL_WHO_HOST", "127.0.0.1"),
                    help="address to listen on. 127.0.0.1 on a laptop. On a host that ends TLS "
                         "in front of the process (Render does), 0.0.0.0")
    ap.add_argument("--net", choices=list(NETWORKS), default="testnet")
    ap.add_argument("--pay-to", default=os.environ.get("SELL_WHO_PAY_TO"))
    ap.add_argument("--max-age-days", type=int, default=who_service.MAX_AGE_DAYS)
    ap.add_argument("--price", default=os.environ.get("SELL_WHO_PRICE") or PRICE,
                    help='what one answer costs, e.g. "$0.01"')
    ap.add_argument("--snapshots-url", default=os.environ.get("SNAPSHOTS_URL") or None,
                    help="for a host with no disk: fetch the published rolling snapshots from "
                         "this URL at startup and hourly (see snapshot_handoff.py)")
    ap.add_argument("--flows-url", default=os.environ.get("FLOWS_URL") or None,
                    help="the published on-chain window (flows_handoff.py), fetched with the snapshots; "
                         "gives every answer its on_chain block. Default: none (on_chain says not available)")
    ap.add_argument("--facilitator", choices=["public", "cdp"], default="public",
                    help="public: keyless x402.org (testnet). cdp: Coinbase's, with a key file")
    ap.add_argument("--cdp-key-file", default=None,
                    help="path to the CDP key file (default ~/.config/ausrine/cdp_api_key.json); "
                         "read in-process, never printed")
    a = ap.parse_args()
    if not a.pay_to:
        sys.exit("sell-who: --pay-to or SELL_WHO_PAY_TO is required (the seller's address)")
    public_url = (os.environ.get("SELL_WHO_PUBLIC_URL") or "").rstrip("/") or None
    if public_url and a.net != "mainnet" and public_url_problem(public_url):
        sys.exit("sell-who: SELL_WHO_PUBLIC_URL %s" % public_url_problem(public_url))
    import pro
    no = live_refusal(a.net, a.facilitator, a.pay_to, a.cdp_key_file, os.environ)
    if no:
        sys.exit("sell-who: refusing real money: %s" % no)
    if a.net == "mainnet":
        print("sell-who: LIVE on Base mainnet. payTo %s, price %s; Pro files per file: %s." % (
            a.pay_to, a.price, ", ".join("%s %s" % (n, p) for n, p in pro.X402_PRICES.items())), flush=True)
    import uvicorn
    try:
        mw = x402_payment_middleware(a.pay_to, a.net, a.facilitator, a.cdp_key_file, a.price)
    except Exception as e:                      # KeyFileError never carries a secret
        sys.exit("sell-who: could not start the payment layer: %s: %s" % (type(e).__name__, e))
    sync = None
    if a.snapshots_url:
        # the window is published beside the snapshots (…/radar/ → …/flows/); no new setting needed
        if not a.flows_url and "/radar/" in a.snapshots_url:
            a.flows_url = a.snapshots_url.replace("/radar/", "/flows/")
        sync = SnapshotSync(a.snapshots_url, flows_url=a.flows_url)
        print("sell-who: first snapshot sync:", sync.once(), flush=True)
        if a.flows_url:
            print("sell-who: first on-chain sync:", sync.chain_last, flush=True)
    gate = pro.Gate(os.environ.get("POLAR_ORG_ID") or None, os.environ.get("POLAR_BENEFIT_ID") or None)
    print("sell-who: Atlas Pro %s" % ("on" if gate.enabled else "off (POLAR_ORG_ID and POLAR_BENEFIT_ID are both needed)"), flush=True)
    store = posts.Store(posts.default_path())
    try:
        post_sync, storage = posts.from_env(os.environ)
    except ValueError as e:
        sys.exit("sell-who: %s" % e)
    if post_sync is not None:
        print("sell-who: posts read back: %d files, %d records" % post_sync.load(store), flush=True)
    # local records the repository does not hold go back in the queue, or a restart loses them;
    # those older than the days read back are checked against their own day's files
    local = store.load_file(post_sync.loaded if post_sync is not None else None)
    if post_sync is not None:
        post_sync.prune_older(store)
    print("sell-who: posts: %d from the local file, %d waiting to commit; %s" % (local, len(store.pending), storage),
          flush=True)
    app = build(mw, info={"network": NETWORKS[a.net], "pay_to": a.pay_to, "price": a.price,
                          "facilitator": a.facilitator, "public_url": public_url},
                max_age_days=a.max_age_days, sync=sync, public_url=public_url, gate=gate,
                post_store=store, post_sync=post_sync, post_storage=storage,
                posts_open=bool(post_sync is not None and post_sync.commits) or os.environ.get("POSTS_ALLOW_MEMORY") == "1")
    # proxy_headers: behind a host's TLS proxy the 402 must name the https URL the
    # buyer actually called, not the plain-http one the proxy used to reach us.
    # Forwarded headers are never trusted. The public address comes from SELL_WHO_PUBLIC_URL.
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", proxy_headers=False)


if __name__ == "__main__":
    main()
