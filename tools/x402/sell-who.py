#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 0a16b98). Edit it there, not here.
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

    GET /sellers                 free: what the seller report ("Your buyers") holds, its price, a
                                 real sample blurred to ranges, and how to subscribe
    GET /sellers/report/<host>   Atlas for Sellers, $29 a month: a Polar license key in X-Atlas-Key
                                 (POLAR_SELLERS_BENEFIT_ID; an Atlas Pro key opens it too), never
                                 x402; <host>.html is the same report as one printable page
    GET /x402/report/<host>      the same report as JSON, no key: paid per call over x402, $0.50
                                 (seller_report.X402_PRICES)

    POST /posts                  $0.01 a post: an agent posts on the Atlas about a seller, an
                                 operator, a wallet or the market. The author is the wallet that
                                 paid; the post says whether it paid what it talks about (posts.py)
    GET /posts                   free: newest first, paged; ?about=<kind>:<id> for one thing
    GET /posts/<id>              free: one post and its replies
    POST /posts/<id>/hide        X-Atlas-Admin equal to ATLAS_ADMIN_TOKEN; off when that is unset

    GET /read?url=<url>          $0.001 a page: a web page or a PDF as clean text, title and all
                                 (page_reader.py). Refusals are free; a failed read is not settled

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
and for /x402/report/<host>:
    200  the report                   paid
    400  not a hostname               free
    404  not in the registry, not in the window, or nobody paid it there   free
    503  stale snapshot or window     free
and for POST /posts:
    201  the post, stored             paid, stored only once the payment has settled, and with
                                      GitHub commits on, committed to the repository first
    202  the post, queued             paid and kept, but the commit failed; retried each minute
                                      and at shutdown, and the answer says so
    400  not JSON, bad field or text  free
    404  about or reply_to not found  free
    429  20 posts today from that wallet  free
    503  stale / no on-chain window   free
and for GET /read?url=<url>:
    200  the page's text          paid
    400  no URL, not http(s), a port other than 80 or 443, a login in the URL, a host
         with no address or one that resolves to a private address        free
    502/504/415/422 after payment  unreachable, timeout, over 5 MB, too many redirects,
         unsupported type, no text, a scanned PDF: all non-2xx, so the SDK never settles
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

THE FUNNEL, counted and nothing else (Funnel): for each priced family (who, watch, each
export file, report, posts, read) and each via tag (mcp when the address carried ?via=mcp, as every link the
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
import seller_report  # noqa: E402
import page_reader  # noqa: E402

NETWORKS = {"testnet": "eip155:84532", "mainnet": "eip155:8453"}
# Solana mainnet (the chain's genesis hash, CAIP-2). Every priced route can also be paid there, in USDC,
# to SELL_WHO_SOL_PAY_TO: a public receiving address; no Solana key lives on this server (the
# facilitator pays the fee and submits the buyer's signed transfer). Mainnet only.
SOLANA_MAINNET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
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


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def sol_pay_to_ok(address):
    """A Solana address as a receiving address: base58 that decodes to exactly 32 bytes (a public
    key), never a 0x one. The alphabet and length alone let through strings that are not keys, and
    a payTo that is not a key advertises a way to pay that cannot work."""
    if not isinstance(address, str) or address.startswith("0x") or not BASE58.match(address):
        return False
    n = 0
    for ch in address:
        n = n * 58 + B58.index(ch)
    pad = len(address) - len(address.lstrip("1"))                # each leading "1" is one zero byte
    raw = b"\x00" * pad + (n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b"")
    return len(raw) == 32


_UNSET = object()


def live_refusal(net, facilitator, pay_to, cdp_key_file, env, sol_pay_to=_UNSET):
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
    # the Solana address in effect (the command line wins over the environment); an old caller that
    # passes none is judged on the environment's
    sol = env.get("SELL_WHO_SOL_PAY_TO") if sol_pay_to is _UNSET else sol_pay_to
    if sol and not sol_pay_to_ok(sol):
        return "the Solana payTo must be a Solana address: base58 that decodes to a 32-byte public key"
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


REPORT_DESCRIPTION = ("Your buyers: one x402 seller's own customers, read from its x402 payments on Base over "
                      "the Atlas's window. Per payTo wallet: buyers, payments and USDC day by day, who came back "
                      "and the loyal buyers, new buyers per day, buyers lost and where each went, where new "
                      "buyers came from, what is bought alongside, early buyers, its 5 closest rivals side by "
                      "side, and what changed by fixed rules. Every figure with its dates. Refusals are free.")

# What one paid report looks like (made-up hosts and wallets, never a real one).
REPORT_EXAMPLE = {
    "ok": True, "report": "Your buyers", "host": "api.example.com", "as_of": "2026-09-30", "age_days": 0,
    "window": {"chain": "Base", "from": "2026-09-25", "to": "2026-09-29", "days": 5},
    "wallets": [{
        "wallet": "0x" + "11" * 20, "hosts": ["api.example.com"], "hosts_total": 1,
        "summary": {"buyers": 96, "payments": 6982, "usdc": 152.35, "days_paid": 5, "window_days": 5},
        "by_day": [{"date": "2026-09-25", "buyers": 35, "new_buyers": 35, "payments": 3152, "usdc": 60.78},
                   {"date": "2026-09-26", "buyers": 24, "new_buyers": 10, "payments": 808, "usdc": 12.88}],
        "came_back": {"buyers": 37, "of": 96, "rate_pct": 38.5,
                      "loyal": [{"wallet": "0x" + "22" * 20, "days": 5, "first": "2026-09-25", "last": "2026-09-29",
                                 "payments": 2753, "usdc": 37.36}]},
        "lost": {"buyers": 22, "of": 96,
                 "left_for": [{"wallet": "0x" + "33" * 20, "hosts": ["rival.example"], "hosts_total": 1, "buyers": 4}],
                 "list": [{"wallet": "0x" + "55" * 20, "days": 1, "last_paid": "2026-09-26", "payments": 30,
                           "usdc": 0.29, "busy": False, "went_to_total": 1,
                           "went_to": [{"wallet": "0x" + "33" * 20, "hosts": ["rival.example"], "hosts_total": 1}]}]},
        "arrived": {"buyers": 40, "of": 96,
                    "came_from": [{"wallet": "0x" + "44" * 20, "hosts": ["other.example"], "hosts_total": 1, "buyers": 5}]},
        "bought_alongside": {"sellers": [{"wallet": "0x" + "33" * 20, "hosts": ["rival.example"], "hosts_total": 1,
                                          "shared_buyers": 13, "share_pct": 13.5}]},
        "early_buyers": None,
        "rivals": {"side_by_side": [{"wallet": "0x" + "11" * 20, "this": True, "buyers": 96, "came_back_rate_pct": 38.5,
                                     "payments": 6982},
                                    {"wallet": "0x" + "33" * 20, "this": False, "shared_buyers": 13, "buyers": 21,
                                     "came_back_rate_pct": 23.8, "payments": 320}]},
        "what_changed": [{"rule": "buyers_between_halves",
                          "say": "Distinct buyers rose from 45 (2026-09-25 to 2026-09-26) to 66 (2026-09-28 to "
                                 "2026-09-29), up 46.7%."}]}],
    "caveats": ["a wallet is not an agent, and nothing here says who holds or runs one"]}


def report_discovery_extension():
    """The Bazaar listing for GET /x402/report/<host>: one host in the path, the report back."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
    return declare_discovery_extension(
        path_params_schema={
            "properties": {"host": {"type": "string",
                                    "description": "the x402 seller's hostname, as the registry lists it "
                                                   "(api.example.com)"}},
            "required": ["host"]},
        output=OutputConfig(example=REPORT_EXAMPLE))


READ_DESCRIPTION = ("Read a web page or a PDF as clean text: give a URL, get its title and readable text "
                    "(markdown). %s a page over x402, no API key. Charged only when text comes back." % page_reader.PRICE)

# What one paid read looks like (the page at example.com, as it reads today).
READ_EXAMPLE_URL = "https://example.com/"
READ_EXAMPLE = {
    "ok": True, "url": "https://example.com/", "final_url": "https://example.com/", "status": 200,
    "content_type": "text/html", "title": "Example Domain", "description": None, "language": None,
    "text": "# Example Domain\n\nThis domain is for use in illustrative examples in documents. You may use "
            "this domain in literature without prior coordination or asking for permission.\n\nMore information...",
    "words": 29, "chars": 190, "pages": None, "truncated": False, "fetched_at": "2026-10-09T06:00:00Z"}


def read_discovery_extension():
    """The Bazaar listing for GET /read: one query parameter, the URL, and what comes back."""
    from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
    return declare_discovery_extension(
        input={"url": READ_EXAMPLE_URL},
        input_schema={"type": "object",
                      "properties": {"url": {"type": "string", "format": "uri",
                                             "description": "the page to read: http or https, port 80 or 443, "
                                                            "an HTML page, a text or markdown file, or a PDF"}},
                      "required": ["url"]},
        output=OutputConfig(example=READ_EXAMPLE))


def x402_routes(pay_to, net, price=None, sol_pay_to=None):
    """Every priced route and its terms. One payTo and one network for all of them, plus, when
    `sol_pay_to` is given (mainnet only), the same price paid on Solana to that address: each route
    then offers two ways to pay, and the buyer's client picks the one it can sign.
    The export routes are literal paths: anything else under /x402/export/ is refused,
    404 and unbilled, before the payment layer is reached (see build())."""
    import pro
    if sol_pay_to and net != "mainnet":
        raise ValueError("Solana is taken on mainnet only")
    if sol_pay_to and not sol_pay_to_ok(sol_pay_to):
        raise ValueError("the Solana payTo is not a Solana address")
    base = lambda p: {"scheme": "exact", "payTo": pay_to, "price": p, "network": NETWORKS[net]}
    accepts = (lambda p: [base(p), {"scheme": "exact", "payTo": sol_pay_to, "price": p, "network": SOLANA_MAINNET}]) \
        if sol_pay_to else base
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
    routes["GET " + seller_report.X402_PATH + ":host"] = {
        "accepts": accepts(seller_report.X402_PRICES["report"]),
        "description": REPORT_DESCRIPTION, "mimeType": "application/json",
        "serviceName": pro.market.BRAND + " seller report",
        "tags": ["x402", "seller-analytics", "customers", "retention", "market-data"],
        "extensions": report_discovery_extension()}
    routes["POST " + posts.PATH] = {
        "accepts": accepts(posts.PRICE),
        "description": POSTS_DESCRIPTION, "mimeType": "application/json",
        "serviceName": pro.market.BRAND + " posts",
        "tags": ["x402", "social", "agents", "reviews", "market-data"],
        "extensions": posts_discovery_extension()}
    routes["GET " + page_reader.PATH] = {
        "accepts": accepts(page_reader.PRICE),
        "description": READ_DESCRIPTION, "mimeType": "application/json",
        "serviceName": "Infoharmoni page reader",
        "tags": ["x402", "web", "scraping", "pdf", "text-extraction", "markdown"],
        "extensions": read_discovery_extension()}
    return routes


def facilitator_supports(client, network):
    """True only when the facilitator lists scheme `exact` (v2) on `network`. Asked before a route
    names a network: the payment SDK ends the whole process (os._exit) when a route's network is not
    one its facilitator lists, so the answer must be known first. A failure to ask is False."""
    try:
        kinds = getattr(client.get_supported(), "kinds", None) or []
    except Exception:
        return False
    return any(getattr(k, "scheme", None) == "exact" and str(getattr(k, "network", "")) == network
               and getattr(k, "x402_version", 2) == 2 for k in kinds)


def x402_payment_middleware(pay_to, net, facilitator="public", cdp_key_file=None, price=None, client=None,
                            sol_pay_to=None):
    """The real payment layer. Imported here so everything else in this file,
    and every test, works without the payment SDK installed.

    facilitator="public" is the keyless x402.org one (test network only).
    facilitator="cdp" is Coinbase's, authenticated with a key file that is
    read by path inside this process and never shown (cdp_facilitator.py).
    `client` stands in for the facilitator in tests; nothing else passes it.

    sol_pay_to adds Solana as a second way to pay, but only when the facilitator lists it: if it does
    not (or cannot be asked), the layer is Base alone and says so (mw.solana is False), instead of a
    server that will not start. The caller prints which it got."""
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
    if sol_pay_to and not facilitator_supports(client, SOLANA_MAINNET):
        sol_pay_to = None
    if sol_pay_to:
        try:
            from x402.mechanisms.svm.exact import register_exact_svm_server
            register_exact_svm_server(server)      # the Solana scheme: prices in USDC, the facilitator's fee payer
        except ImportError:
            sol_pay_to = None                      # the Solana libraries are not installed: Base alone
    # ":target" is one path segment. Anything else under /who/ never gets this
    # far: refuse_before_billing answers it first (see build()).
    routes = x402_routes(pay_to, net, price, sol_pay_to)
    mw = payment_middleware(routes, server)
    # The second lock (see build()): the SDK's own route matching, on the same server and
    # routes, asked about a path before it goes on. Some SDK versions match the raw
    # (still-escaped) path and Starlette routes the decoded one, so both must be priced.
    matcher = x402HTTPResourceServer(server, routes)

    def priced(method, raw_path, path):
        return all(matcher.requires_payment(HTTPRequestContext(adapter=None, path=p, method=method))
                   for p in (raw_path, path))
    mw.priced = priced
    mw.solana = bool(sol_pay_to)
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
        self.families = ["who", "watch"] + list(pro.X402_PRICES) + ["posts"] + list(seller_report.X402_PRICES) + ["read"]
        self.started = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        self._lock = threading.Lock()
        self._n = {f: {v: dict.fromkeys(self.STAGES, 0) for v in self.VIAS} for f in self.families}
        self._failed = {}      # why a payment that was tried did not settle: {reason: count}
        self._clients = {}     # who asked a priced path, by kind of client: {kind: count}

    def family(self, path, method="GET"):
        """Which priced family a (decoded) path belongs to, or None."""
        import pro
        if path == posts.PATH:
            return "posts" if method == "POST" else None
        if path == page_reader.PATH:
            return "read" if method == "GET" else None
        if path.startswith("/who/"):
            return "who"
        if path.startswith("/watch/"):
            return "watch"
        if path.startswith(seller_report.X402_PATH):
            return "report"
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

    def note(self, path, query, paid_header, status, settled_header, method="GET", why=None, client=None):
        """Count one request that went through the payment layer. why: the reason a payment
        that was tried did not settle (a short word, never a wallet); client: the kind of
        client that asked (client_kind()), never its own words."""
        fam = self.family(path, method)
        if fam is None:
            return
        v = self.via(query)
        if client:
            self._bump(self._clients, client)
        if paid_header:
            self.count(fam, v, "attempted")
        if status == 402:
            self.count(fam, v, "offered")
        elif paid_header and 200 <= status < 300 and settled_header:
            self.count(fam, v, "settled")
            return
        if paid_header:
            reason = "%s: %s" % (fam, why or "status %d" % int(status))
            if self._bump(self._failed, reason) == 1:      # once per reason; the hourly line has the counts
                print("sell-who: a payment was tried and did not settle: %s" % reason, flush=True)

    MAX_KEYS = 40      # no caller can grow the tables: past this, every new key counts as "other"

    def _bump(self, table, key):
        with self._lock:
            if key not in table and len(table) >= self.MAX_KEYS:
                key = "other"
            table[key] = table.get(key, 0) + 1
            return table[key]

    def snapshot(self):
        with self._lock:
            counts = {f: {v: dict(c) for v, c in by.items()} for f, by in self._n.items()}
        with self._lock:
            failed, clients = dict(self._failed), dict(self._clients)
        return {"ok": True, "since": self.started, "counts": counts, "failed_payments": failed, "clients": clients,
                "stages": {"offered": "the payment layer answered 402 with terms",
                           "attempted": "the request carried a payment header",
                           "settled": "the payment settled and the answer was served (2xx)"},
                "via": "mcp when the address carried ?via=mcp, none otherwise",
                "failed_payments_means": "why a request that carried a payment did not settle, by family: the "
                                         "payment layer's own reason, or the answer's status",
                "clients_means": "who asked a priced path, by kind of client read from its User-Agent; the "
                                 "User-Agent itself is not kept",
                "note": "aggregated counts since the process started; no address, wallet or host asked about is kept"}

    def line(self):
        snap = self.snapshot()
        parts = []
        for f, by in snap["counts"].items():
            for v, c in by.items():
                if any(c.values()):
                    parts.append("%s/%s %d/%d/%d" % (f, v, c["offered"], c["attempted"], c["settled"]))
        out = "sell-who: funnel since %s (offered/attempted/settled): %s" % (snap["since"], ", ".join(parts) or "nothing yet")
        if snap["clients"]:
            out += " | clients: " + ", ".join("%s %d" % kv for kv in sorted(snap["clients"].items(), key=lambda kv: -kv[1]))
        if snap["failed_payments"]:
            out += " | not settled: " + ", ".join("%s %d" % kv for kv in sorted(snap["failed_payments"].items()))
        return out

    async def forever(self, every=3600):
        import asyncio
        while True:
            await asyncio.sleep(every)
            print(self.line(), flush=True)


PAYMENT_HEADERS = ("payment-signature", "x-payment")
SETTLED_HEADERS = ("payment-response", "x-payment-response")

CLIENT_KINDS = [  # (kind, pattern on the lower-cased User-Agent); first match wins, the text itself is never kept
    ("x402scan", r"x402scan"), ("coinbase / bazaar", r"coinbase|\bcdp\b|bazaar"),
    ("x402 client library", r"x402"), ("claude / anthropic", r"claude|anthropic"),
    ("openai / chatgpt", r"openai|chatgpt|gptbot"), ("search crawler", r"googlebot|bingbot|duckduckbot|applebot|yandex|baiduspider"),
    ("other bot or crawler", r"bot\b|crawler|spider|scan|monitor|uptime|check"),
    ("python", r"python|httpx|aiohttp|urllib|requests"), ("node", r"node|undici|axios|got\b|fetch"),
    ("curl / wget", r"curl|wget"), ("go", r"go-http-client"), ("browser", r"mozilla"),
]


def client_kind(user_agent):
    """The kind of client from its User-Agent, as one of a fixed list of words."""
    ua = (user_agent or "").lower()
    if not ua:
        return "no user-agent"
    for kind, rx in CLIENT_KINDS:
        if re.search(rx, ua):
            return kind
    return "other"


PAYMENT_REASONS = [  # (what we keep, words in the payment layer's reason); its own text is never kept
    ("not enough funds", r"insufficient|balance|funds"), ("authorization already used", r"nonce|already used|replay"),
    ("authorization expired or not yet valid", r"expire|valid_?before|valid_?after|too early|too late|deadline"),
    ("bad signature", r"signature"), ("wrong amount", r"amount|value"),
    ("wrong recipient", r"recipient|pay_?to|receiver"), ("wrong network", r"network|chain"),
    ("wrong token", r"asset|token|usdc"), ("wrong scheme or version", r"scheme|version"),
    ("settlement failed", r"settle"), ("payment checker unavailable", r"facilitator|timeout|unavailable|connect"),
    ("invalid payment", r"invalid|verify|malformed|decode|parse"),
]


def payment_error(response):
    """Why the payment layer refused a payment, as one of a fixed list of plain reasons read
    from the terms it answered with; None when it gave none. Its own words are never kept: a
    facilitator's message could carry an address or a host."""
    raw = response.headers.get("payment-required")
    if not raw:
        return None
    try:
        import base64
        err = json.loads(base64.b64decode(raw)).get("error")
    except Exception:
        return None
    if not isinstance(err, str) or not err:
        return None
    low = err.lower()
    for reason, rx in PAYMENT_REASONS:
        if re.search(rx, low):
            return reason
    return "other reason"


BUDGET = 4      # unpaid pre-checks computed at once; beyond it, 503 busy, unpaid. Answers are cached
                # per snapshot version, so a paying buyer's second call costs nothing.


def build(payment_mw, info=None, max_age_days=who_service.MAX_AGE_DAYS, sync=None, public_url=None,
          budget=BUDGET, gate=None, funnel=None, funnel_every=3600, post_store=None, post_sync=None,
          post_storage=None, env=None, posts_open=True, reader=None):
    """The app. `payment_mw` is any (request, call_next) middleware: the real
    x402 one in production, a stub in tests. `gate` decides who may take a Pro
    export (pro.Gate); without one, Pro says it is not switched on. `funnel`
    counts the paid paths (Funnel); one is made when none is given. `post_store`
    holds the posts (posts.Store; an in-memory one when none is given), `post_sync`
    commits them (posts.GitHub, or None), `env` is where ATLAS_ADMIN_TOKEN is read. `reader`
    reads pages for /read (page_reader.Reader; one on the real network when none is given)."""
    from fastapi import FastAPI, Query, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse, Response
    import pro
    gate = gate or pro.Gate(None)
    reader = reader or page_reader.Reader()

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
        tried = any(request.headers.get(h) for h in PAYMENT_HEADERS)
        funnel.note(request.url.path, request.scope.get("query_string", b"").decode("latin-1"),
                    tried, response.status_code,
                    any(response.headers.get(h) for h in SETTLED_HEADERS), request.method,
                    why=payment_error(response) if tried else None,
                    client=client_kind(request.headers.get("user-agent")))
        response = terms_in_body(response)
        # A post the handler prepared is stored only now, and only if its payment settled.
        staged = getattr(request.state, "post_staged", None)
        if staged is not None:
            if 200 <= response.status_code < 300 and settled(response):
                return await keep(staged, response)
            store.release(staged["author"])
        return response

    def terms_in_body(response):
        """The terms are in the payment-required header (x402 version 2). A client that reads the
        answer's body finds them there too, instead of an empty {}."""
        if response.status_code != 402 or not response.headers.get("payment-required"):
            return response
        if response.headers.get("content-length") not in ("0", "2"):
            return response
        try:
            import base64
            body = base64.b64decode(response.headers["payment-required"])
            json.loads(body)
        except Exception:
            return response
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(body, status_code=402, headers=headers, media_type="application/json")

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

    async def directory_probe(request, call_next, path):
        """Directories (x402scan) learn our prices by probing: HEAD requests, and GETs on the
        OpenAPI template itself (/who/{target}) or the catalog's pattern (/who/:target). An unpaid probe gets the payment terms, never an
        answer: a template is swapped for the document's own example, HEAD is asked as GET and
        answered without a body. Anything carrying a payment header takes the normal path, and
        nothing is settled without one."""
        if request.method not in ("GET", "HEAD") or any(request.headers.get(h) for h in PAYMENT_HEADERS):
            return None
        if path == page_reader.PATH:
            # The template's own placeholder, or a HEAD: the terms for the example page. A probe
            # never reads anything: without a payment the payment layer answers, and that is all.
            # A plain GET with no url is not a probe but bad input, refused below, unbilled.
            url = query_url(request)
            template = url in ("{url}", ":url")
            if not template and request.method != "HEAD":
                return None
            if template or not url:
                from urllib.parse import urlencode
                request.scope["query_string"] = urlencode({"url": READ_EXAMPLE_URL}).encode()
            head = request.method == "HEAD"
            request.scope["method"] = "GET"
            response = await call_next(request)
            if response.status_code != 402:
                return JSONResponse({"ok": False, "charged": False, "error": "probe_unanswered"}, status_code=404,
                                    headers={"cache-control": "no-store"})
            if head:
                headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
                return Response(b"", status_code=402, headers=headers)
            return response
        prefix = next((p for p in ("/who/", "/watch/", pro.X402_PATH, seller_report.X402_PATH) if path.startswith(p)),
                      None)
        if prefix is None:
            return None
        value = unquote(path[len(prefix):])
        # Coinbase's catalog lists our routes by their pattern (/who/:target), so an agent that
        # copies the listed address asks for ":target" itself; it gets the terms, never a 400.
        listed = {"/who/": ":target", "/watch/": ":wallet", pro.X402_PATH: ":name", seller_report.X402_PATH: ":host"}
        template = "{" in value or "}" in value or value == listed[prefix]
        if not template and request.method != "HEAD":
            return None
        if template:
            target, wallet = discovery_examples()
            example = {"/who/": target, "/watch/": wallet, pro.X402_PATH: next(iter(pro.X402_PRICES)),
                       seller_report.X402_PATH: report_example()}[prefix]
            new_path = prefix + example
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode()
        head = request.method == "HEAD"
        request.scope["method"] = "GET"
        response = await call_next(request)
        if response.status_code != 402:
            return JSONResponse({"ok": False, "charged": False, "error": "probe_unanswered"}, status_code=404,
                                headers={"cache-control": "no-store"})
        if head:
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            return Response(b"", status_code=402, headers=headers)
        return response

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
        probe = await directory_probe(request, call_next, path)
        if probe is not None:
            return probe
        if path.startswith(pro.X402_PATH):
            return await export_before_billing(request, call_next, path[len(pro.X402_PATH):], raw)
        if path.startswith(seller_report.X402_PATH):
            return await report_before_billing(request, call_next, unquote(path[len(seller_report.X402_PATH):]), raw)
        if path == posts.PATH or path.startswith(posts.PATH + "/"):
            return await posts_before_billing(request, call_next, path, raw)
        if path.lower().startswith(posts.PATH):
            # The payment layer matches /Posts as /posts; the router does not. Nothing to offer.
            return JSONResponse({"ok": False, "charged": False, "error": "no_such_path"}, status_code=404,
                                headers={"cache-control": "no-store"})
        if path == page_reader.PATH:
            return await read_before_billing(request, call_next, raw)
        if path.lower().startswith(page_reader.PATH):
            # /Read, /read/, /read/x: the payment layer might price the first; the router serves none
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

    async def read_before_billing(request, call_next, raw):
        """The paid page read. Bad input leaves here, unbilled, before any payment is asked for:
        no URL, a malformed one, a scheme that is not http(s), a port other than 80 or 443, a
        login in the URL, a host with no address, and above all a host that resolves to a
        private address. The host is resolved HERE, once; the handler connects to the address
        judged here, so nothing can change between the judgment and the connection."""
        if request.method != "GET":
            return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"},
                                status_code=405, headers={"allow": "GET"})
        url = query_url(request)
        try:
            page_reader.shape(url)                            # free, instant, no lookup, no slot needed
        except page_reader.Refused as r:
            return JSONResponse(r.body(), status_code=400, headers={"cache-control": "no-store"})
        refusal = unpriced(request, raw)
        if refusal is not None:
            return refusal
        if slots.locked():
            return JSONResponse({"ok": False, "charged": False, "error": "busy",
                                 "say": "too many unpaid requests at once; try again in a moment"},
                                status_code=503, headers={"cache-control": "no-store"})
        async with slots:
            try:
                # the name is looked up off the event loop; a slow resolver must not stall the server
                target = await run_in_threadpool(reader.judge, url)
            except page_reader.Refused as r:
                # a bad URL is the asker's 400; a lookup that is busy or too slow is ours (503, 504)
                return JSONResponse(r.body(), status_code=READ_FAILURES[r.error] if r.error in ("busy", "timeout") else 400,
                                    headers={"cache-control": "no-store"})
        request.state.read_target = target
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

    async def report_before_billing(request, call_next, host, raw):
        """The x402 door to the seller report. Everything that is not a report ready to hand over
        leaves here, unbilled: another method, a name that is not a hostname, a stale snapshot or
        window, a seller the registry or the window does not hold, a seller nobody paid."""
        if request.method != "GET":
            return JSONResponse({"ok": False, "charged": False, "error": "method_not_allowed"},
                                status_code=405, headers={"allow": "GET"})
        if not seller_report.valid_host(host):           # free, instant, no slot needed
            code, body = seller_report.report(host, None, max_age_days)
            return JSONResponse(body, status_code=code, headers={"cache-control": "no-store"})
        refusal = unpriced(request, raw)
        if refusal is not None:
            return refusal
        if slots.locked():
            return JSONResponse({"ok": False, "charged": False, "error": "busy",
                                 "say": "too many unpaid requests at once; try again in a moment"},
                                status_code=503, headers={"cache-control": "no-store"})
        async with slots:
            code, body = await run_in_threadpool(seller_report.report, host, None, max_age_days)
        if code != 200:
            return JSONResponse(body, status_code=code, headers={"cache-control": "no-store"})
        request.state.report = body
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
        out["read"] = {"GET " + page_reader.PATH + "?url=<url>": page_reader.PRICE,
                       "types": sorted(page_reader.TYPES), "max_mb": page_reader.MAX_BYTES // (1024 * 1024)}
        out["seller_reports"] = {"on": gate.sellers_enabled, "subscription": seller_report.PRICE,
                                 "key": seller_report.KEY_PATH + "<host>",
                                 "x402": {seller_report.X402_PATH + "<host>": seller_report.X402_PRICES["report"]},
                                 "about": "/sellers"}
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

    @app.get(WELL_KNOWN)
    async def well_known(request: Request):
        """The x402 discovery manifest (draft-hawkins-x402-dns-discovery): a host's own
        machine-readable answer to "does it speak x402, and what does it sell". Free."""
        if not public_url:                # never advertise addresses taken from a caller's Host header
            return JSONResponse({"ok": False, "error": "no_public_url",
                                 "say": "this host has no configured public address, so it publishes no manifest"},
                                status_code=404)
        return JSONResponse(manifest(public_url.rstrip("/"), info, posts_open), headers={"cache-control": "public, max-age=3600",
                                                      "access-control-allow-origin": "*"})

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

    @app.get(page_reader.PATH)
    async def read_route(request: Request,
                         url: str = Query(..., description="the page to read: http or https, port 80 or 443; "
                                                           "an HTML page, a text or markdown file, or a PDF")):
        # Reached only after the payment layer, with the target the pre-check judged. Any failure
        # answers non-2xx, so the SDK never settles the payment, and says charged: false.
        target = getattr(request.state, "read_target", None)
        if target is None:      # cannot happen while the pre-check stands; never read if it does
            return JSONResponse({"ok": False, "charged": False, "error": "not_prepared"}, status_code=500)
        try:
            body = await run_in_threadpool(reader.read, target)
        except page_reader.Refused as r:
            return JSONResponse(r.body(), status_code=READ_FAILURES.get(r.error, 502),
                                headers={"cache-control": "no-store"})
        except Exception as e:  # a reader bug is still an unsettled answer, never a 500 with a trace
            return JSONResponse({"ok": False, "charged": False, "error": "read_failed",
                                 "say": "the page could not be read: %s" % type(e).__name__},
                                status_code=502, headers={"cache-control": "no-store"})
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

    @app.get("/sellers")
    async def sellers_route():
        body = await run_in_threadpool(seller_report.describe, env, None, max_age_days)
        return JSONResponse(body, headers={"cache-control": "no-store"})

    @app.options(seller_report.KEY_PATH + "{host}")
    async def sellers_report_preflight(host: str):
        # The /sellers/ page on the Atlas's own site calls this from the viewer's browser.
        return Response(status_code=204, headers=REPORT_CORS)

    @app.get(seller_report.KEY_PATH + "{host}")
    async def sellers_report(request: Request, host: str):
        # Not an x402 route: the payment layer lets it pass, and the key is the gate. A Sellers key or
        # a Pro key opens it (pro.SELLERS); the key is never logged, echoed or kept.
        headers = dict(REPORT_CORS, **{"cache-control": "no-store"})
        page = host.lower().endswith(".html")
        name = host[:-5] if page else host
        if not seller_report.valid_host(name):
            code, body = seller_report.report(name, None, max_age_days)
            body.pop("charged", None)
            return JSONResponse(body, status_code=code, headers=headers)
        code, why = await run_in_threadpool(gate.check, request.headers.get(pro.HEADER), pro.SELLERS)
        if code != 200:
            if code == 401:
                headers["www-authenticate"] = pro.HEADER
            if code == 429:
                headers["retry-after"] = str(why["retry_after"])
            return JSONResponse(why, status_code=code, headers=headers)
        code, body = await run_in_threadpool(seller_report.report, name, None, max_age_days)
        if code != 200:
            body = dict(body)
            body.pop("charged", None)
            return JSONResponse(body, status_code=code, headers=headers)
        if page:
            text = await run_in_threadpool(seller_report.html, body)
            return Response(text, media_type="text/html; charset=utf-8", headers=dict(headers, **{
                "content-disposition": 'inline; filename="your-buyers-%s-%s.html"' % (body["host"], body["as_of"])}))
        return JSONResponse(body, headers=headers)

    @app.get(seller_report.X402_PATH + "{host}")
    async def x402_report(request: Request, host: str):
        # Reached only after the payment layer, and only with the report the pre-check prepared.
        body = getattr(request.state, "report", None)
        if body is None:      # cannot happen while the pre-check stands; never serve if it does
            return JSONResponse({"ok": False, "charged": False, "error": "not_prepared"}, status_code=500)
        return JSONResponse(body, headers={"cache-control": "no-store"})

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

    app.openapi = lambda: discovery_openapi(app)
    return app


WELL_KNOWN = "/.well-known/x402"
MANIFEST_UPDATED = "2026-10-10T00:00:00Z"      # change it when the paid routes or their prices change


def manifest(base, info=None, posts_open=False):
    """The /.well-known/x402 document: what this host sells over x402, at what price, with links.
    Prices come from the same constants the payment layer charges, so the two cannot disagree."""
    import pro
    info = info or {}
    res = lambda path, price, what, method="GET": {"url": base + path, "method": method, "price": price,
                                                  "description": what}
    resources = [
        res("/who/{target}", info.get("price") or PRICE, "a seller's report card, who actually paid it on Base, and its relationships "
                                    "with its buyers (came back, bought alongside, left for), with the evidence"),
        res("/watch/{wallet}", watch_service.PRICE, "what a wallet paid for over x402, and to whom"),
        res(seller_report.X402_PATH + "{host}", seller_report.X402_PRICES["report"],
            "Your buyers: a seller's full report on its own customers from its x402 payments on Base"),
        res(page_reader.PATH + "?url={url}", page_reader.PRICE,
            "a web page or a PDF as clean text (markdown): title, description, language and the readable text"),
    ] + [res(pro.X402_PATH + n, p, "the Atlas's newest window as a file: " + n) for n, p in pro.X402_PRICES.items()]
    if posts_open:
        resources.append(res(posts.PATH, posts.PRICE, "post to the Atlas's agent board", method="POST"))
    return {"x402Version": 2, "kind": "resource-server", "name": "Infoharmoni Atlas",
            "description": "The public record of agent commerce: who pays whom over x402 on Base, read off the "
                           "chain every day. A refusal is never charged.",
            "updated": MANIFEST_UPDATED, "docs": CONTACT["url"] + "/docs/", "contact": CONTACT["email"],
            "networks": info.get("networks") or ([info["network"]] if info.get("network") else []),
            "openapi": base + "/openapi.json", "resources": resources}


CONTACT = {"name": "Infoharmoni", "email": "ausrine@infoharmoni.com", "url": "https://atlas.infoharmoni.com"}
FALLBACK_TARGET = "stableenrich.dev"
FALLBACK_WALLET = "0x54e163e9b8edda194d83f46add921bfa5fc5f4e0"


def discovery_examples():
    """Real values a directory can probe with: the busiest x402 seller in the loaded window and
    its busiest payer, so the example request reaches the 402 instead of a free refusal."""
    try:
        _, chain = who_service.newest_chain()
        sellers = sorted((chain or {}).get("sellers", {}).values(), key=lambda s: -s.get("on_chain_payments_x402", 0))
        top = sellers[0]
        payer = (top.get("x402_top_payers") or [{}])[0].get("wallet")
        return top["host"], payer or FALLBACK_WALLET
    except (IndexError, KeyError, TypeError, AttributeError):
        return FALLBACK_TARGET, FALLBACK_WALLET


def report_example():
    """A real seller host whose report would be sold now, so a probe reaches the 402: the who
    example when the window holds a payment to it, else the busiest seller in the window."""
    target, _ = discovery_examples()
    try:
        _, win = who_service.relationships_window()
        if not win or not win.get("dates"):
            return target
        view = seller_report.relationships.for_host(win, target)
        if view and view["wallets"]:
            return target
        pick = seller_report.busiest(win, None)
        return pick[0] if pick else target
    except Exception:
        return target


def discovery_openapi(app):
    """/openapi.json in the shape x402 directories read (x402scan's discovery spec): the paid
    operations carry x-payment-info and a 402 response, every path parameter has a real example,
    and the free operations say so with an empty security list. Built fresh each time so the
    examples follow the newest window."""
    from fastapi.openapi.utils import get_openapi
    import pro
    doc = get_openapi(title="Infoharmoni Atlas: pay-per-call answers for agents", version="1",
                      description="Who actually pays whom in the x402 market on Base. Seller reports, "
                                  "agent spend reports, the daily files and agent posts, and a page reader "
                                  "(any web page or PDF as clean text), paid per call in USDC on Base over "
                                  "x402. Refusals are never charged.",
                      routes=app.routes)
    doc["info"]["contact"] = dict(CONTACT)
    target, wallet = discovery_examples()
    price = lambda a: {"mode": "fixed", "currency": "USD", "amount": a}
    paid = {
        ("get", "/who/{target}"): (price(PRICE.lstrip("$")), {"target": target}),
        ("get", "/watch/{wallet}"): (price(watch_service.PRICE.lstrip("$")), {"wallet": wallet}),
        ("post", posts.PATH): (price(posts.PRICE.lstrip("$")), {}),
        ("get", page_reader.PATH): (price(page_reader.PRICE.lstrip("$")), {"url": READ_EXAMPLE_URL}),
        ("get", seller_report.X402_PATH + "{host}"): (price(seller_report.X402_PRICES["report"].lstrip("$")),
                                                     {"host": report_example()}),
        ("get", pro.X402_PATH + "{name}"): ({"mode": "dynamic", "currency": "USD",
                                             "min": min(v.lstrip("$") for v in pro.X402_PRICES.values()),
                                             "max": max(v.lstrip("$") for v in pro.X402_PRICES.values())},
                                            {"name": "sellers.csv"}),
    }
    doc.setdefault("components", {})["securitySchemes"] = {
        "AtlasProKey": {"type": "apiKey", "in": "header", "name": "X-Atlas-Key",
                        "description": "the Atlas Pro license key from the Polar subscription"},
        "AtlasSellersKey": {"type": "apiKey", "in": "header", "name": "X-Atlas-Key",
                            "description": "the Atlas for Sellers license key from the Polar subscription; an "
                                           "Atlas Pro key opens the seller reports too"},
        "AtlasAdmin": {"type": "apiKey", "in": "header", "name": "X-Atlas-Admin"}}
    keyed = {("get", "/pro/export/{name}"): "AtlasProKey", ("get", "/pro/watch"): "AtlasProKey",
             ("get", seller_report.KEY_PATH + "{host}"): "AtlasSellersKey",
             ("post", posts.PATH + "/{pid}/hide"): "AtlasAdmin"}
    for path, ops in doc.get("paths", {}).items():
        for method, op in ops.items():
            terms = paid.get((method, path))
            if terms is None:
                scheme = keyed.get((method, path))
                op["security"] = [{scheme: []}] if scheme else []   # a key, or free: nothing to pay
                continue
            pricing, examples = terms
            op["x-payment-info"] = {"protocols": ["x402"], "price": pricing, "network": "base", "asset": "USDC"}
            op.setdefault("responses", {})["402"] = {"description": "Payment required: x402 terms in the "
                                                                    "PAYMENT-REQUIRED header, USDC on Base"}
            for prm in op.get("parameters", []):
                if prm.get("in") in ("path", "query") and prm.get("name") in examples:
                    prm["example"] = examples[prm["name"]]
                    prm.setdefault("schema", {})["example"] = examples[prm["name"]]
            if method == "post" and path == posts.PATH:
                op["requestBody"] = {"required": True, "content": {"application/json": {
                    "schema": {"type": "object", "required": ["about", "text"], "properties": {
                        "about": {"type": "object", "properties": {"kind": {"type": "string"}, "id": {"type": "string"}}},
                        "text": {"type": "string", "minLength": 1, "maxLength": 500},
                        "reply_to": {"type": "string"}}},
                    "example": {"about": {"kind": "seller", "id": target}, "text": "Fast answers; paid it twice today."}}}}
    return doc


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


# The /sellers/ page on the Atlas's own site asks for a report from the viewer's browser, key in the
# header, exactly as the /watch/ page asks /pro/watch.
REPORT_CORS = dict(WATCH_CORS)


def spend_watch_malformed(wallet, days):
    """True when /watch/<wallet> is refused on its shape alone: not exactly one Base address,
    or a bad days value. Such a request is answered without touching the store."""
    ws, why = watch_service.spend_watch.parse_wallets(wallet)
    return bool(why) or len(ws) != 1 or bool(watch_service.spend_watch.parse_days(days)[1])


# What a failed read answers with, after payment: never a 2xx, so the SDK never settles it.
READ_FAILURES = {"unreachable": 502, "timeout": 504, "too_large": 502, "too_many_redirects": 502,
                 "unsupported_type": 415, "empty_text": 422, "scanned_pdf": 422, "encrypted_pdf": 422,
                 "unreadable_pdf": 422, "pdf_not_installed": 503, "private_address": 502,
                 "busy": 503}


def query_url(request):
    """The ?url= of a request, read from the scope: the probe may have rewritten the query
    after the request object cached its own reading of it."""
    return (parse_qs(request.scope.get("query_string", b"").decode("latin-1")).get("url") or [None])[0]


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
    ap.add_argument("--sol-pay-to", default=os.environ.get("SELL_WHO_SOL_PAY_TO") or None,
                    help="a Solana address: every price can also be paid on Solana, in USDC, to it (mainnet only; "
                         "a receiving address, no key)")
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
    no = live_refusal(a.net, a.facilitator, a.pay_to, a.cdp_key_file, os.environ, sol_pay_to=a.sol_pay_to)
    if no:
        sys.exit("sell-who: refusing real money: %s" % no)
    if a.sol_pay_to and a.net != "mainnet":
        sys.exit("sell-who: --sol-pay-to is for mainnet only")
    if a.sol_pay_to and not sol_pay_to_ok(a.sol_pay_to):
        sys.exit("sell-who: --sol-pay-to is not a Solana address")
    if a.net == "mainnet":
        print("sell-who: LIVE on Base mainnet%s. payTo %s%s, price %s; Pro files per file: %s; seller report %s; "
              "page reader %s." % (" and Solana" if a.sol_pay_to else "", a.pay_to,
                                   (" (Solana %s)" % a.sol_pay_to) if a.sol_pay_to else "", a.price,
                                   ", ".join("%s %s" % (n, p) for n, p in pro.X402_PRICES.items()),
                                   seller_report.X402_PRICES["report"], page_reader.PRICE), flush=True)
    import uvicorn
    try:
        mw = x402_payment_middleware(a.pay_to, a.net, a.facilitator, a.cdp_key_file, a.price, sol_pay_to=a.sol_pay_to)
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
    gate = pro.Gate(os.environ.get("POLAR_ORG_ID") or None, os.environ.get("POLAR_BENEFIT_ID") or None,
                    sellers_benefit_id=os.environ.get("POLAR_SELLERS_BENEFIT_ID") or None)
    print("sell-who: Atlas Pro %s" % ("on" if gate.enabled else "off (POLAR_ORG_ID and POLAR_BENEFIT_ID are both needed)"), flush=True)
    print("sell-who: seller reports by key %s; per call over x402 at %s<host>, %s" % (
        "on" if gate.sellers_enabled else "off (POLAR_ORG_ID and POLAR_SELLERS_BENEFIT_ID or POLAR_BENEFIT_ID)",
        seller_report.X402_PATH, seller_report.X402_PRICES["report"]), flush=True)
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
    if a.sol_pay_to and not getattr(mw, "solana", False):
        print("sell-who: Solana is NOT on: the facilitator does not list it (or could not be asked). Base alone.", flush=True)
    app = build(mw, info={"network": NETWORKS[a.net], "pay_to": a.pay_to, "price": a.price,
                          "networks": [NETWORKS[a.net]] + ([SOLANA_MAINNET] if getattr(mw, "solana", False) else []),
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
