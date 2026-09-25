#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 507dd4a). Edit it there, not here.
"""buyer_pages_test.py — a page for every buyer wallet, from a synthetic rollup. No network.

    python3 buyer_pages_test.py

The rollup is made by whales.rollup itself from a handful of made-up transfers, so the
pages are tested against the shape the pipeline really writes. The tests that matter
most: no page ever says who holds a wallet, and none uses the word the lab has banned.
"""
import glob
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import buyer_pages as bp  # noqa: E402
import seller_pages as sp  # noqa: E402
import whales  # noqa: E402
import operator_pages_test as opt  # noqa: E402  (its store fixture)

EVIL_HOST = "<b>evil</b>.example"
AGENT = "0xAbCd" + "a1" * 18                  # mixed case: the page lives at the lowercase path
PLAIN = "0x" + "b2" * 20                      # two sellers over x402, and a plain transfer
NOX402 = "0x" + "b3" * 20                     # plain transfers only: no page
WA, WS, WW, WZ, WX, WE = ("0x" + c * 40 for c in "123456")


def store():
    """operator_pages_test's registry, plus a seller whose host name is markup."""
    d = opt.store()
    f = os.path.join(d, "market-2026-01-02.json")
    s = json.load(open(f))
    s["sellers"][EVIL_HOST] = opt.row(3, '<script>alert(7)</script> "quoted" & co')
    json.dump(s, open(f, "w"))
    return d


def rollup_file(d):
    sellers = {WA: ["alpha.aslan.example", "beta.aslan.example", "gamma.aslan.example"], WS: ["solo.example"],
               WW: ["one.ninety.workers.dev", "two.ninety.workers.dev"], WZ: ["gone.example"],   # gone: not in the registry snapshot
               WX: ["filler1.example"], WE: [EVIL_HOST]}
    e = lambda f, t, n, usdc, nx, ux: {"from": f, "to": t, "n": n, "usdc": usdc, "n_x402": nx, "usdc_x402": ux}
    edges = [e(AGENT, WA, 600, 45.0, 600, 45.0), e(AGENT, WS, 10, 0.1, 10, 0.1), e(AGENT, WZ, 5, 0.05, 5, 0.05),
             e(AGENT, WW, 1, 1000.0, 0, 0.0),
             e(PLAIN, WX, 9, 0.9, 9, 0.9), e(PLAIN, WE, 4, 0.4, 4, 0.4), e(PLAIN, WA, 2, 50.0, 0, 0.0),
             e(NOX402, WS, 1, 20.0, 0, 0.0)]
    snap = json.load(open(os.path.join(store(), "market-2026-01-02.json")))["sellers"]
    chain_of = {w: "Base" for w in (AGENT, PLAIN, NOX402, WA, WS, WW, WZ, WX, WE)}
    r = whales.rollup(edges, sellers, chain_of, 24, snap)
    r["dates"], r["as_of"] = ["2026-01-02"], "2026-01-02"
    p = os.path.join(d, "whales-2026-01-02.json")
    json.dump(r, open(p, "w"))
    return p, r


class Caveats(unittest.TestCase):
    def test_the_caveats_are_whales_notes_word_for_word(self):
        _p, r = rollup_file(tempfile.mkdtemp())
        for c in bp.CAVEATS:
            self.assertIn(c, r["notes"])


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.whales, cls.rollup = rollup_file(tempfile.mkdtemp())
        cls.r = sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent.json",
                         whales=cls.whales, operators="/nonexistent-operators.json")
        cls.agent = AGENT.lower()

    @staticmethod
    def read(path):
        with open(path) as f:
            return f.read()

    def page(self, *parts):
        return self.read(os.path.join(self.out, *parts))

    def test_the_fixture_is_what_whales_would_write(self):
        self.assertEqual([b["wallet"] for b in self.rollup["agents"]], [AGENT])
        self.assertEqual(len(self.rollup["buyers"]), 3)

    def test_a_page_for_every_wallet_with_an_x402_payment_and_none_for_the_rest(self):
        self.assertTrue(os.path.exists(os.path.join(self.out, "b", self.agent, "index.html")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "b", PLAIN, "index.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "b", NOX402)))
        self.assertNotIn(AGENT, os.listdir(os.path.join(self.out, "b")))            # never the mixed-case path
        self.assertEqual(len(glob.glob(os.path.join(self.out, "b", "*", "index.html"))), 2)

    def test_the_agent_page_says_what_the_chain_shows(self):
        html = self.page("b", self.agent, "index.html")
        self.assertIn("<h1><code>0xAbCd…a1a1</code></h1>", html)
        self.assertIn('href="https://basescan.org/address/%s"><code>%s</code></a> on Base' % (AGENT, AGENT), html)
        self.assertIn("2026-01-02 · 24 h on-chain", html)
        self.assertIn("This wallet paid three or more sellers in the window: an agent at work.", html)
        self.assertIn('<span class="tag">agent at work</span>', html)
        self.assertIn("<b>615</b><span>x402 payments, last 24 h</span>", html)
        self.assertIn("<b>$45.15</b><span>USDC, x402-settled</span>", html)
        self.assertIn("<b>$1,000</b><span>USDC that reached sellers by other means, not x402</span>", html)
        self.assertIn("<b>3</b><span>sellers paid over x402 (4 by any means)</span>", html)
        self.assertIn("<h2>What it bought</h2>", html)
        self.assertIn('<link rel="canonical" href="https://example.test/atlas/b/%s/">' % self.agent, html)

    def test_the_sellers_table_links_registry_hosts_busiest_first(self):
        html = self.page("b", self.agent, "index.html")
        alpha = html.index('href="https://example.test/atlas/s/alpha.aslan.example/">alpha.aslan.example</a>')
        solo = html.index('href="https://example.test/atlas/s/solo.example/">solo.example</a>')
        gone = html.index('<td class="h">gone.example</td>')                       # not in the registry: no link
        one = html.index('one.ninety.workers.dev</a>')
        self.assertLess(alpha, solo)
        self.assertLess(solo, gone)
        self.assertLess(gone, one)                                                 # no x402 payments: last
        self.assertIn('<td class="n">600</td><td class="n">$45.00</td><td class="n">$0.00</td>', html)
        self.assertNotIn("/s/gone.example/", html)

    def test_a_wallet_that_is_not_an_agent_is_not_called_one(self):
        html = self.page("b", PLAIN, "index.html")
        self.assertNotIn("an agent at work", html.split("<h2>How to read this</h2>")[0])
        self.assertNotIn('<span class="tag">agent at work</span>', html)
        self.assertIn("This wallet’s x402 payments reached 2 sellers in the window.", html)
        self.assertIn("<b>$50.00</b><span>USDC that reached sellers by other means", html)

    def test_stranger_text_cannot_become_markup(self):
        html = self.page("b", PLAIN, "index.html")
        self.assertNotIn("<b>evil</b>", html)
        self.assertIn("&lt;b&gt;evil&lt;/b&gt;.example</a>", html)
        self.assertNotIn("<script>alert(7)", html)

    def test_the_standing_caveats_are_on_every_page(self):
        for f in glob.glob(os.path.join(self.out, "b", "**", "index.html"), recursive=True):
            html = self.read(f)
            for c in bp.CAVEATS:
                self.assertIn(bp.esc(c), html, f)

    def test_no_page_uses_the_banned_word_or_names_a_holder(self):
        pages = glob.glob(os.path.join(self.out, "b", "**", "index.html"), recursive=True)
        pages += [os.path.join(self.out, "index.html"), os.path.join(self.out, "s", "alpha.aslan.example", "index.html")]
        self.assertEqual(len(pages), 5)
        for f in pages:
            html = self.read(f)
            # the front door's search script carries market.CATS regexes, one of which matches the word
            # in sellers' own descriptions; that is code, not page text, so scripts are left out
            text = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
            self.assertIsNone(re.search(r"verif", text, re.I), f)
            for claim in ("owned by", "operated by", "belongs to", "'s agent", "’s agent", "run by"):
                self.assertNotIn(claim, html, (f, claim))

    def test_the_list_puts_agents_first_with_counts(self):
        idx = self.page("b", "index.html")
        self.assertIn("<h2>Agents at work · 1</h2>", idx)
        self.assertIn("<h2>Every other buyer · 1</h2>", idx)
        self.assertIn("2 wallets. 1 of them paid three or more sellers", idx)
        self.assertLess(idx.index('/b/%s/"' % self.agent), idx.index('/b/%s/"' % PLAIN))
        self.assertLess(idx.index("Every other buyer"), idx.index('/b/%s/"' % PLAIN))
        self.assertNotIn(NOX402, idx)

    def test_the_search_index_has_one_row_per_wallet(self):
        rows = json.loads(self.page("b", "index.json"))["buyers"]
        self.assertEqual(rows, [{"wallet": self.agent, "x402": 615, "usdc_x402": 45.15, "sellers": 3, "agent": True},
                                {"wallet": PLAIN, "x402": 13, "usdc_x402": 1.3, "sellers": 2, "agent": False}])

    def test_seller_pages_link_named_payers_to_their_buyer_pages(self):
        html = self.page("s", "alpha.aslan.example", "index.html")
        self.assertIn('<a href="https://example.test/atlas/b/%s/"><code>0xAbCd…a1a1</code></a> 600' % self.agent, html)
        self.assertNotIn("basescan.org/address/%s" % AGENT, html)
        html = self.page("s", "filler1.example", "index.html")
        self.assertIn('href="https://example.test/atlas/b/%s/"' % PLAIN, html)

    def test_the_nav_and_the_front_door_point_at_the_buyers(self):
        self.assertIn('<a href="https://example.test/atlas/b/">buyers</a>', self.page("s", "solo.example", "index.html"))
        self.assertIn('<a href="https://example.test/atlas/b/">buyers</a>', self.page("b", PLAIN, "index.html"))
        door = self.page("index.html")
        self.assertIn('<a href="https://example.test/atlas/b/%s/"><code>0xAbCd…a1a1</code></a>' % self.agent, door)
        self.assertIn('<a href="https://example.test/atlas/b/">agents at work</a>: wallets paying 3+ sellers', door)
        self.assertIn('<a href="https://example.test/atlas/b/">Every buyer</a>', door)


class WhatItBought(unittest.TestCase):
    """'What it bought' reads the wallet's x402 payments only: one weather call outranks a hundred
    plain transfers to an analytics seller, which are not purchases and are not listed."""

    def test_categories_come_from_x402_payments(self):
        W, WWX, WAN = "0x" + "e7" * 20, "0x" + "e8" * 20, "0x" + "e9" * 20
        snap = {"wx.example": opt.row(5, "weather forecast for any city"),
                "chart.example": opt.row(5, "onchain analytics for tokens")}
        e = lambda f, t, n, usdc, nx, ux: {"from": f, "to": t, "n": n, "usdc": usdc, "n_x402": nx, "usdc_x402": ux}
        r = whales.rollup([e(W, WWX, 1, 0.01, 1, 0.01), e(W, WAN, 100, 500.0, 0, 0.0)],
                          {WWX: ["wx.example"], WAN: ["chart.example"]}, {W: "Base", WWX: "Base", WAN: "Base"}, 24, snap)
        b = next(b for b in r["buyers"] if b["wallet"] == W)
        self.assertEqual(b["categories"][0], "crypto & markets")          # the rollup's own list is weighted by all transfers
        out = tempfile.mkdtemp()
        bp.build(out, r, {h: {} for h in snap}, {}, "2026-01-02", 2, head="%(title)s", foot="")
        html = open(os.path.join(out, "b", W, "index.html")).read()
        line = re.search(r"<h2>What it bought</h2><p[^>]*>(.*?)</p>", html).group(1)
        self.assertEqual(line, "By category, most payments first: world data.")
        self.assertNotIn("crypto", line)


    def test_an_x402_purchase_behind_eight_bigger_transfers_still_counts(self):
        # the rollup keeps a wallet's eight sellers by USDC; a small x402 call can fall off that list
        W, WWX = "0x" + "f1" * 20, "0x" + "f2" * 20
        big = ["0x" + ("%02x" % (0x30 + i)) * 20 for i in range(9)]
        snap = {"wx.example": opt.row(5, "weather forecast for any city")}
        sellers = {WWX: ["wx.example"]}
        snap.update({"shop%d.example" % i: opt.row(5, "onchain analytics for tokens") for i in range(9)})
        sellers.update({w: ["shop%d.example" % i] for i, w in enumerate(big)})
        e = lambda f, t, n, usdc, nx, ux: {"from": f, "to": t, "n": n, "usdc": usdc, "n_x402": nx, "usdc_x402": ux}
        edges = [e(W, WWX, 1, 0.01, 1, 0.01)] + [e(W, w, 1, 1000.0, 0, 0.0) for w in big]
        r = whales.rollup(edges, sellers, {w: "Base" for w in [W, WWX] + big}, 24, snap)
        b = next(b for b in r["buyers"] if b["wallet"] == W)
        self.assertNotIn("wx.example", [s["host"] for s in b["sellers"]])   # cut from the eight
        self.assertEqual(b["categories_x402"], ["world data"])
        out = tempfile.mkdtemp()
        bp.build(out, r, {h: {} for h in snap}, {}, "2026-01-02", 2, head="%(title)s", foot="")
        html = open(os.path.join(out, "b", W, "index.html")).read()
        line = re.search(r"<h2>What it bought</h2><p[^>]*>(.*?)</p>", html).group(1)
        self.assertEqual(line, "By category, most payments first: world data.")


class NoBuyers(unittest.TestCase):
    """An older rollup without a buyers list: an empty room, and every link falls back to the explorer."""

    def test_old_rollups_still_build(self):
        out = tempfile.mkdtemp()
        sp.build(out, opt.store(), site="https://example.test/atlas", claims="/nonexistent.json",
                 whales=opt.whales(tempfile.mkdtemp()), operators="/nonexistent-operators.json")
        self.assertEqual(json.load(open(os.path.join(out, "b", "index.json")))["buyers"], [])
        html = open(os.path.join(out, "s", "alpha.aslan.example", "index.html")).read()
        self.assertIn('href="https://basescan.org/address/0xc1c1', html)
        self.assertNotIn("/b/0x", html)


if __name__ == "__main__":
    unittest.main(verbosity=1)
