#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit abfcd4a). Edit it there, not here.
"""front_door_test.py — the home page, from a synthetic store, rollup, flows day and Square. No network.

    python3 front_door_test.py
"""
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import front_door  # noqa: E402
import front_live  # noqa: E402
import seller_pages as sp  # noqa: E402
import operator_pages_test as opt  # noqa: E402  (its store and rollup fixtures)

SITE = "https://example.test/atlas"
STEM = "ver" + "if"
W = ["0x%040x" % (0xA0 + i) for i in range(30)]          # payer wallets
S1, S2, S3, S4 = ("0x" + c * 40 for c in "1234")           # seller wallets


def png(w=64, h=64):
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def edge(f, t, n, u):
    return {"from": f, "to": t, "n": n, "usdc": u, "n_x402": n, "usdc_x402": u}


def flows_dir():
    d = tempfile.mkdtemp()
    sellers = {S1: ["api.alpha.example", "alpha.example"], S2: ["beta.run.app", "beta.example"], S3: ["</script><b>x</b>.example"],
               S4: ["newcomer.example"]}
    old = {"date": "2026-01-01", "edges": [edge(W[0], S1, 5, 0.5), edge(W[1], S2, 2, 0.2), edge(W[2], S3, 1, 0.1)], "sellers": sellers}
    day = {"date": "2026-01-02", "sellers": sellers,
           "edges": [edge(W[0], S1, 900, 9.0), edge(W[1], S1, 40, 4.0), edge(W[2], S2, 300, 30.0), edge(W[3], S3, 7, 0.7),
                     edge(W[4], S4, 2, 2.0), {"from": W[5], "to": S1, "n": 3, "usdc": 3.0, "n_x402": 0, "usdc_x402": 0.0}]
                    + [edge(W[6], s, 1, 0.01) for s in (S1, S2, S3, S4)]
                    + [edge(W[7], "0x" + "%040x" % (0x500 + i), 1, 0.01) for i in range(3)]}       # not listed: left out
    # a wallet that bought from six listed sellers, and a robot that paid twenty
    extra = {("0x" + "%040x" % (0x900 + i)): ["shop%d.example" % i] for i in range(25)}
    day["sellers"].update(extra)
    old["sellers"] = dict(day["sellers"])
    ws = list(extra)
    day["edges"] += [edge(W[8], s, 1, 0.05) for s in ws[:6]] + [edge(W[9], s, 1, 0.01) for s in ws[:21]]
    for name, d_ in (("flows-2026-01-01.json", old), ("flows-2026-01-02.json", day)):
        with open(os.path.join(d, name), "w") as f:
            json.dump(d_, f)
    return d


SQUARE = {"members": [{"author": "mb:penny-agent", "at": "2026-01-02T03:04:05", "door": "Moltbook", "slug": "mb-penny-agent",
                       "has_page": True, "wallet_proven": True, "sells": "contracts for the APIs an agent depends on; we %sy each one" % STEM},
                      {"author": "sq:<b>bold</b>", "at": "2026-01-01T10:00:00", "door": "the Square's API", "sells": "<script>x</script>"}],
          "feed": [{"author": "sq:penny-agent", "at": "2026-01-02T05:00:00", "kind": "offer", "text": "Free first contract"}],
          "teams": [{"lead": "sq:penny-agent", "at": "2026-01-02T06:00:00", "name": "Pre-pay check", "members": [{}, {}, {}]}],
          "now": {"founding": {"left": 97}}}


class Door(unittest.TestCase):
    """The whole site's build, as seller_pages writes it, in the free tier."""
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        store = opt.store()
        s = json.load(open(os.path.join(store, "market-2026-01-02.json")))
        old = dict(s, date="2026-01-01", sellers={h: r for h, r in s["sellers"].items() if h != "solo.example"})
        json.dump(old, open(os.path.join(store, "market-2026-01-01.json"), "w"))
        rollup = opt.whales(tempfile.mkdtemp())
        d = json.load(open(rollup))
        d["totals"] = {"payments_x402": 669, "usdc_x402": 48.9, "buyer_wallets_x402": 2, "agents_3plus": 1}
        d["buyers"] = [{"wallet": "0x" + "c1" * 20, "short": "0xc1c1…c1c1", "chain": "Base", "usdc": 48.0, "payments": 660,
                        "usdc_x402": 48.0, "payments_x402": 660, "sellers_paid": 3, "sellers_paid_x402": 3, "categories": ["other"],
                        "sellers": [{"host": "alpha.aslan.example", "payments": 600, "usdc": 45.0, "payments_x402": 600, "usdc_x402": 45.0}]}]
        json.dump(d, open(rollup, "w"))
        cls.r = sp.build(cls.out, store, site=SITE, claims="/nonexistent.json",
                         whales=rollup, operators="/nonexistent-operators.json", free=True)
        cls.html = open(os.path.join(cls.out, "index.html")).read()

    def test_the_door_says_what_the_atlas_offers(self):
        self.assertIn('<h1 id="h">See where AI agents spend. Know who to pay.</h1>', self.html)
        self.assertIn(front_door.PITCH, self.html)
        for name, _what, _price, url in front_door.OFFERS:
            self.assertIn('<a href="%s%s"><span class="on">%s</span>' % (SITE, url, name), self.html)
        self.assertIn("$0.001 a check, by API", self.html)
        self.assertIn("No seller can pay to change its numbers or its place.", self.html)      # the free tier's sentence
        self.assertNotIn("never for sale", self.html)

    def test_the_numbers_come_from_the_chain_and_link_to_their_rooms(self):
        self.assertIn("<dt>x402 payments</dt><dd>669</dd>", self.html)
        self.assertIn('<dd class="acc">$48.90</dd>', self.html)
        self.assertIn('<a href="%s/b/">agents at work</a>: wallets paying 3+ sellers</dt><dd>1</dd>' % SITE, self.html)
        self.assertIn('<a href="%s/o/">operators</a>' % SITE, self.html)

    def test_the_top_sellers_link_to_their_pages(self):
        self.assertIn("<h2>Top sellers, 2 Jan 2026</h2>", self.html)
        self.assertIn('<a href="%s/s/alpha.aslan.example/">alpha.aslan.example</a>' % SITE, self.html)
        self.assertEqual(self.r["door"]["leaders"], 2)                # fewer than three wide sellers: every seller paid

    def test_the_square_panel_never_says_zero_when_unread(self):
        side = self.html.split('<aside class="fp-side" id="square">')[1].split("</aside>")[0]
        self.assertIn('href="%s/square/join.md">Send your agent to join</a>' % SITE, side)
        self.assertNotIn("<b>0</b>", side)
        self.assertIn('href="%s/rails/">' % SITE, side)

    def test_no_flows_no_network_and_no_feed(self):
        self.assertEqual((self.r["door"]["network"], self.r["door"]["feed"]), (False, 0))
        self.assertNotIn('id="fp-data"', self.html)
        self.assertNotIn('<ol id="fp-feed">', self.html)

    def test_the_rooms_and_the_map_moved(self):
        self.assertIn('href="%s/map/">The map</a>' % SITE, self.html)
        self.assertIn("GET https://ausrine-who.onrender.com/who/", self.html)
        self.assertIn('<a class="brand" href="%s/">' % SITE, self.html)
        self.assertIn('<a href="%s/square/">The Square</a>' % SITE, self.html)          # the header says "The Square"
        sm = open(os.path.join(self.out, "sitemap-sellers.xml")).read()
        self.assertIn("<loc>%s/</loc>" % SITE, sm)

    def test_search_stays_where_the_header_lands(self):
        self.assertIn('<input id="q" type="search"', self.html)
        self.assertIn("/s/index.json", self.html)
        self.assertIn("/o/index.json", self.html)
        self.assertIn('data-q="AI inference"', self.html)
        self.assertIn("const CATS=[[", self.html)
        self.assertIn("if(WALLET.test(v)){await loadB();", self.html)
        self.assertIn("new URLSearchParams(location.search).get('q')", self.html)
        rows = json.load(open(os.path.join(self.out, "s", "index.json")))["sellers"]
        self.assertEqual(next(r for r in rows if r[0] == "alpha.aslan.example")[8], 600)


class Live(unittest.TestCase):
    """The moving parts, from a flows day and a Square written here."""
    @classmethod
    def setUpClass(cls):
        cls.fd = flows_dir()
        cls.day = os.path.join(cls.fd, "flows-2026-01-02.json")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fd)

    def build(self, named=None, icons=False, get=None, square=SQUARE):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        paid = [{"host": "alpha.example", "on_chain_payments_x402": 940, "on_chain_usdc_x402": 13.0, "x402_payer_wallets": 3}]
        chain = {"totals": {"payments_x402": 1}, "sellers": {"a": paid[0]}, "dates": ["2026-01-02"],
                 "buyers": [{"wallet": w} for w in (named or [])], "agents": []}
        head = "<html>%(title)s %(root)s"
        r = front_door.build(out, chain, {"alpha.example": {"calls": 1}}, [{}], {"root": SITE}, "2026-01-03", SITE, head, "</html>", "x", "API",
                             free=named is not None, flows=self.day, flows_dir=self.fd, square=square, icons=icons, get=get)
        with open(os.path.join(out, "index.html"), encoding="utf-8") as f:
            return r, f.read(), out

    def test_the_network_carries_no_wallet_address(self):
        net = front_live.network(self.day)
        self.assertEqual([n["host"] for n in net["nodes"] if n["kind"] == "s"][:3], ["beta.example", "alpha.example", "newcomer.example"])
        text = json.dumps(net)
        for w in W:
            self.assertNotIn(w, text)
        self.assertNotIn("api.alpha.example", text)                       # a seller is its own domain, never a platform's
        self.assertTrue(all(l["n"] > 0 for l in net["links"]))
        self.assertFalse(any(l["n"] == 3 for l in net["links"]))           # the payment that was not x402 is left out

    def test_the_data_cannot_close_its_script(self):
        _r, page, _o = self.build()
        data = page.split('<script type="application/json" id="fp-data">')[1].split("</script>")[0]
        self.assertIn("<\\/script><b>x<\\/b>.example", data)
        self.assertNotIn("<b>x</b>", page)

    def test_the_feed_mixes_the_square_and_the_chain(self):
        r, page, _o = self.build()
        feed = page.split('<ol id="fp-feed">')[1].split("</ol>")[0]
        kinds = re.findall(r'class="fp-chip c-([a-z]+)"', feed)
        self.assertEqual(kinds[:3], ["team", "paid", "paid"])               # one from the Square, then two from the chain
        self.assertIn("From Moltbook: contracts for the APIs an agent depends on; we %sy each one" % STEM, page)   # quoted as written
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", page)
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("Pre-pay check", feed)
        self.assertIn("2 Jan, 06:00 UTC · The Square", feed)
        pool = page.split('<template id="fp-pool">')[1].split("</template>")[0]
        self.assertIn("from 6 different sellers in one day", pool)
        self.assertNotIn("21 different sellers", pool)                     # a robot is not shown as a shopper
        self.assertIn("newcomer.example", pool)
        self.assertIn("paid for the first time this week ($2.01)", pool)      # $2.00 + the $0.01 from W6
        self.assertEqual(r["feed"], pool.count("<li>"))

    def test_a_quiet_week_before_still_names_the_first_paid(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        shutil.copy(self.day, d)
        with open(os.path.join(d, "flows-2026-01-01.json"), "w") as f:
            json.dump({"date": "2026-01-01", "edges": [], "sellers": {}}, f)
        new = [e for e in front_live.chain_events(os.path.join(d, "flows-2026-01-02.json"), d) if e["kind"] == "new"]
        self.assertEqual(len(new), 3)
        alone = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, alone)
        shutil.copy(self.day, alone)                                       # no window at all: nothing can be called new
        self.assertFalse([e for e in front_live.chain_events(os.path.join(alone, "flows-2026-01-02.json"), alone) if e["kind"] == "new"])

    def test_a_wallet_is_named_only_where_the_tier_allows(self):
        _r, page, _o = self.build(named=[])
        for w in W:
            self.assertNotIn(w[:6] + "…" + w[-4:], page)
        self.assertIn("<b>A wallet</b>", page)
        _r, page, _o = self.build(named=None)                                # the whole record: the busiest payer is named
        self.assertIn(W[0][:6] + "…" + W[0][-4:], page)

    def test_the_square_panel_counts_and_faces(self):
        _r, page, _o = self.build()
        side = page.split('<aside class="fp-side" id="square">')[1].split("</aside>")[0]
        self.assertIn("<div><b>2</b><span>agents</span></div><div><b>1</b><span>joined from Moltbook</span></div>", side)
        self.assertIn("<b>97</b><span>founding places left</span>", side)
        self.assertIn('<a href="%s/square/mb-penny-agent/">penny-agent</a>' % SITE, side)
        self.assertIn('class="m mb"', side)
        self.assertNotIn("<b>bold</b>", side)
        self.assertIn("Free to join · 97 founding places left", page)

    def test_icons_are_fetched_once_and_served_from_the_site(self):
        asked = []

        def get(url):
            asked.append(url)
            return png(16, 16) if "newcomer" in url else png()
        r, page, out = self.build(icons=True, get=get)
        self.assertTrue(all(u.startswith(front_live.ICON_URL.split("%s")[0]) for u in asked))
        self.assertTrue(os.path.exists(os.path.join(out, "icons", "alpha.example.png")))
        self.assertFalse(os.path.exists(os.path.join(out, "icons", "newcomer.example.png")))   # a 16-pixel placeholder is refused
        self.assertIn('src="%s/icons/alpha.example.png"' % SITE, page)
        self.assertNotIn("google.com", page)                                 # a visitor's browser never asks a third party
        self.assertGreaterEqual(r["icons"], 1)

    def test_icons_fail_quietly(self):
        def get(url):
            raise OSError("down")
        r, page, out = self.build(icons=True, get=get)
        self.assertEqual(r["icons"], 0)
        self.assertIn("Top sellers", page)

    def test_a_png_must_be_a_png(self):
        self.assertTrue(front_live._png_ok(png()))
        self.assertFalse(front_live._png_ok(png(16, 16)))
        self.assertFalse(front_live._png_ok(b"<html>not an image</html>" * 4))
        self.assertFalse(front_live._png_ok(png() + b"\x00" * front_live.ICON_MAX))
        self.assertEqual(front_live.icon_domain("api.bitrefill.com"), "bitrefill.com")
        self.assertEqual(front_live.icon_domain("shop.example.co.uk"), "example.co.uk")
        self.assertEqual(front_live.icon_file("x402.aispace.bot"), "aispace.bot.png")


if __name__ == "__main__":
    unittest.main(verbosity=1)
