#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f04f064). Edit it there, not here.
"""tiers.py — the one switch between the free tier and the whole record.

Vilija, 2026-10-05: the Atlas stops giving its paid tiers away ("I don't want to keep
it free, let's just see"). Her pricing of 2026-09-27 (site_pages.PRICING) says what is
free: today's market, every seller's basic card, the network map, the live feed, the
top 20 lists. Pro, $49 a month, holds every buyer wallet and every operator, the full
history, the full price benchmarks and the daily files. Until today the public site
showed nearly all of Pro for free. With FREE_TIER_ONLY the site matches the tiers:

    a seller page   keeps its basic card: name, what it sells, tags, the tiles, the price
                    line, its rivals, the replay, the claim box and the agent box. "Who
                    actually paid" keeps one summary line and loses the payer wallets and
                    their shares; "Relationships" keeps one line and loses the lists.
    /b/ and /o/     the index shows the top TOP and says how many more are in Pro; a page
                    is built for those TOP; every other address keeps one small page saying
                    the wallet or group is in the record and where to get it, at the same
                    canonical address, so an old link never meets a silent 404.
    /leaders/, /prices/, /where/
                    TOP rows a table and the headline figures stay; the rest is the locked line.
    the words       the basic record is free, the full record is paid; no seller can pay
                    to change its numbers or its place.

It is an experiment and must be reversible with one switch. FREE_TIER_ONLY = False here,
or --full on seller_pages.py, coverage_build.py and atlas_mcp.py, builds the old,
everything-public site, byte for byte (free_tier_test.py checks that against the tree
this was written on). --free builds the free tier whatever the constant says.

Locked data is not in the page at all: not in the HTML, not in inline JSON or script
data, not in a hidden element, not blurred with a style. What a page does not show, it
does not carry (free_tier_test.py looks for a known locked wallet in every built file).
The map and the live feed keep what they draw today.

Nothing here invents a price or changes one: the prices below are the ones the serving
code charges (x402/sell-who.py, x402/watch_service.py, x402/pro.py,
x402/seller_report.py), copied and tested equal. The MCP package ships this file, so it
imports nothing. Standard library only.
"""

import html

FREE_TIER_ONLY = True        # the switch
TOP = 20                     # "top 20 lists" are free (site_pages.PRICING)

# The prices, as the serving code charges them (free_tier_test.py checks each against its source).
WHO_PRICE = "$0.01"          # x402/sell-who.py PRICE: one seller's report card over x402
WATCH_PRICE = "$0.01"        # x402/watch_service.py PRICE: one wallet's watch report over x402
PRO_PRICE = "$49 a month"    # x402/pro.py PRICE: Atlas Pro
SELLERS_PRICE = "$29 a month"   # x402/seller_report.py PRICE: Atlas for Sellers, the "Your buyers" report
LICENCE_PRICE = "from $500 a month"   # site_pages.PRICING["institutions"]: a data licence, custom feeds

# The sentences the free tier puts where "free" and "never for sale" used to be.
PLACE = "No seller can pay to change its numbers or its place."
RECORD = "The basic record is free; the full record is paid."
WHAT_IS_FREE = ("Every seller’s basic card, today’s market, the map, the live feed and the top %d lists are free. "
                "The full record, every buyer wallet and every operator and the whole day as files, is Atlas Pro." % TOP)


def free(override=None):
    """The mode a build or a server runs in: the override when one was given (--full, --free,
    a test), else the switch."""
    return FREE_TIER_ONLY if override is None else bool(override)


def add_flags(ap):
    """--full and --free on a command line. from_args() turns them into free()'s override."""
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="build the whole record public, as before the free tier")
    g.add_argument("--free", action="store_true", help="build the free tier whatever tiers.FREE_TIER_ONLY says")
    return ap


def from_args(a):
    if getattr(a, "full", False):
        return False
    if getattr(a, "free", False):
        return True
    return None


def from_argv(argv):
    """The same two flags read off a bare argv (the MCP server has no parser of its own)."""
    if "--full" in argv:
        return False
    if "--free" in argv:
        return True
    return None


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


# The ways to the full record. Each is (what to call it, the price, where on the site).
# "who": one seller's report card over x402 (docs #who); "watch": one wallet's watch report
# over x402 (/watch/); "pro": Atlas Pro; "sellers": the seller's own "Your buyers" report.
WAYS = {
    "who": ("the %s check over x402" % WHO_PRICE, WHO_PRICE, "/docs/#who"),
    "watch": ("the %s check of one wallet over x402" % WATCH_PRICE, WATCH_PRICE, "/watch/"),
    "pro": ("Atlas Pro at %s" % PRO_PRICE, PRO_PRICE, "/pro.html"),
    "sellers": ("for the seller itself, the Your buyers report at %s" % SELLERS_PRICE, SELLERS_PRICE, "/sellers/"),
    "licence": ("a data licence for institutions, %s" % LICENCE_PRICE, LICENCE_PRICE, "/contact/"),
}
SELLER_WAYS = ("who", "pro", "sellers")
BUYER_WAYS = ("watch", "pro")
OPERATOR_WAYS = ("who", "pro")
LIST_WAYS = ("pro",)
LICENCE_WAYS = ("licence",)      # /where/: no daily file holds a country, so the way is a licence


def _join(parts):
    return parts[0] if len(parts) == 1 else "%s and %s" % (", ".join(parts[:-1]), parts[-1])


def locked_html(what, site, ways=SELLER_WAYS):
    """The plain locked line under a trimmed section: what is behind it, and how to get it."""
    links = ['<a href="%s%s">%s</a>' % (esc(site), esc(WAYS[w][2]), esc(WAYS[w][0])) for w in ways]
    return ('<p class="locked"><b>In the full record:</b> %s. How to get it: %s.</p>'
            % (esc(what), _join(links)))


def locked_json(what, site, ways=SELLER_WAYS, link=lambda u: u):
    """The same, as one field for an answer a program reads. `link` decorates each address
    (the MCP server adds ?via=mcp)."""
    return {"what": what, "how": [{"name": WAYS[w][0], "price": WAYS[w][1], "url": link(site + WAYS[w][2])} for w in ways]}


def more_line(shown, total, what, site, ways=LIST_WAYS):
    """Under a cut list: how many rows are shown, how many more are in the full record."""
    if total <= shown:
        return ""
    return locked_html("%s more %s, past the %d shown" % ("{:,}".format(total - shown), what, shown), site, ways)


# The small page that stands where a buyer or operator page used to be.
def stub_page(kind, name, address, canon, site, head, foot, ctx, as_of, n_sellers, issue, explorer=None, hosts=None):
    """One page per address the free tier does not build: the wallet or group is in the
    record, and here is where to get it. kind: "wallet" or "group". Same canonical address
    as the page it stands for; told to search engines not to index it, since it says little."""
    import market
    if kind == "wallet":
        title = "%s — a buyer wallet in the record · %s" % (name, market.BRAND)
        desc = "Wallet %s made an x402 payment on Base in the window. Its page is in the full record. As of %s." % (name, as_of)
        crumbs = '<a href="%s/b/">Buyers</a> / %s' % (site, esc(name))
        h1 = "<h1><code>%s</code></h1>" % esc(name)
        said = ('<p class="sells">This wallet made an x402 payment to a seller on Base in the window, and it is in the '
                "record. Its page, with its payments, USDC, the sellers it paid and what it bought, is in the full record.</p>")
        ident = ('<p class="muted">Wallet <a rel="nofollow noopener" href="%s"><code>%s</code></a> on Base. A wallet is '
                 "not a person, and nothing here says who holds it.</p>" % (esc(explorer or "https://basescan.org/address/" + address), esc(address)))
        locked = locked_html("this wallet’s payments, USDC, the sellers it paid and what it bought", site, BUYER_WAYS)
        avatar = "buyer"
    else:
        title = "%s — a group of hosts paid into one wallet, in the record · %s" % (name, market.BRAND)
        desc = "%s: %s paid into one wallet. Its page is in the full record. As of %s." % (name, _s(hosts or 0, "x402 host"), as_of)
        crumbs = '<a href="%s/o/">Operators</a> / %s' % (site, esc(name))
        h1 = "<h1>%s</h1>" % esc(name)
        said = ('<p class="sells">%s paid into one wallet: usually one operator, sometimes a platform collecting for '
                "several. The group is in the record. Its page, with the hosts, what they were paid and who paid them, "
                "is in the full record.</p>" % esc(_s(hosts or 0, "host").capitalize()))
        ident = ""
        locked = locked_html("the hosts in this group, what they were paid over x402, and the wallets that paid them",
                             site, OPERATOR_WAYS)
        avatar = "seller"
    page = head % dict(ctx, title=esc(title), desc=esc(desc), canon=esc(canon))
    page = page.replace('<link rel="canonical"', '<meta name="robots" content="noindex,follow"><link rel="canonical"', 1)
    initials = ("".join(c for c in name if c.isalnum())[:2] or "·") if kind == "group" else (address[2:6] if address.startswith("0x") else "·")
    body = ('<main id="main"><p class="crumbs">%s</p><div class="ident"><span class="avatar %s" aria-hidden="true">%s</span>'
            '<div>%s%s</div></div><p><span class="tag">in the record</span><span class="tag">as of %s</span></p>%s%s</main>'
            % (crumbs, avatar, esc(initials), h1, ident, esc(_long_date(as_of)), said, locked))
    return page + body + foot % {"root": site, "issue": esc(issue), "as_of": esc(as_of), "n": "{:,}".format(n_sellers)}


def _s(n, word):
    return "%s %s" % ("{:,}".format(n), word if n == 1 else word + "s")


def _long_date(iso):
    import atlas_style
    return atlas_style.long_date(iso)
