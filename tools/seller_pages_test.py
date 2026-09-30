#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 54e8506). Edit it there, not here.
"""seller_pages_test.py — the public pages, from a synthetic store. No network.

    python3 seller_pages_test.py

The registry's text is written by strangers. The test that matters most is that
none of it can become markup or script on our site.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seller_pages as sp  # noqa: E402

EVIL = '<script>alert(1)</script><img src=x onerror=alert(2)> "quoted" & liquidation cluster heatmap verdict'


def row(calls, sells, price=0.02):
    return {"endpoints": 1, "calls": calls, "payers": 3, "take": calls * price, "chains": ["Base"],
            "wallets": ["0x" + "ab" * 20], "price_min": price, "price_med": price, "price_max": price,
            "sells": sells, "url": "https://x/"}


def store():
    d = tempfile.mkdtemp()
    for day, c in (("2026-01-01", 10), ("2026-01-02", 30)):
        sellers = {"evil.example": row(c, EVIL),
                   "rival.example:8443": row(5, "liquidation cluster heatmap for perps"),
                   "plain.example": row(1, "weather")}
        for i in range(60):          # a market big enough for rarity to mean something
            sellers["filler%d.example" % i] = row(2, "filler offering number %d about topic%d subject%d" % (i, i, i))
        with open(os.path.join(d, "market-%s.json" % day), "w") as f:
            json.dump({"date": day, "taken": day, "endpoints": len(sellers), "sellers": sellers}, f)
    return d


CLAIMS = {"rival.example:8443": {
    "description": 'We are <b>great</b><script>alert(3)</script> & "honest"',
    "logo": "https://cdn.example/logo.png",
    "links": [{"label": "Docs", "url": "https://docs.example/x"},
              {"label": "Evil", "url": "javascript:alert(4)"},
              {"label": "Plain http", "url": "http://insecure.example/"}],
    "claimed_on": "2026-01-02"}}


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        fd, cls.claims = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(CLAIMS, f)
        cls.r = sp.build(cls.out, store(), site="https://example.test/atlas", claims=cls.claims)

    def page(self, *parts):
        return open(os.path.join(self.out, *parts)).read()

    def test_one_page_per_seller_plus_index_and_claim(self):
        self.assertEqual(self.r["sellers"], 63)
        for s in ("evil.example", "rival.example-8443", "plain.example"):
            self.assertTrue(os.path.exists(os.path.join(self.out, "s", s, "index.html")), s)
        self.assertIn("polar", self.page("claim.html"))

    def test_stranger_text_never_becomes_markup(self):
        for parts in (("s", "evil.example", "index.html"), ("s", "rival.example-8443", "index.html"),
                      ("s", "index.html")):
            html = self.page(*parts)
            self.assertNotIn("<script>alert(1)", html, parts)
            self.assertNotIn("<img src=x", html, parts)
            self.assertIn("&lt;script&gt;alert(1)", html, parts)

    def test_the_search_index_is_data_not_markup_and_the_page_escapes_it(self):
        idx = json.loads(self.page("s", "index.json"))
        self.assertEqual(idx["as_of"], "2026-01-02")
        self.assertIn("replace(/[&<>\"']/g", self.page("s", "index.html"))     # client-side escape exists

    def test_numbers_and_replay(self):
        html = self.page("s", "evil.example", "index.html")
        self.assertIn("#1", html)
        self.assertIn("+200%", html)                   # 10 -> 30
        self.assertIn("rival.example-8443/", html)       # rivals link to their own pages
        self.assertIn("unclaimed page", html)

    def test_sitemap_lists_every_page(self):
        self.assertEqual(self.page("sitemap-sellers.xml").count("<loc>"), 65)     # home + the list + 63 sellers

    def test_rarity_decides_who_is_a_rival(self):
        html = self.page("s", "evil.example", "index.html")
        self.assertIn("rival.example-8443/", html)       # shares three rare words
        self.assertNotIn("filler1.example/", html)       # shares nothing that means anything
        self.assertNotIn("Selling something like", self.page("s", "plain.example", "index.html"))

    def test_the_paid_mark_claims_only_what_was_proved(self):
        claim = self.page("claim.html")
        self.assertIn("Claimed by owner", claim)
        self.assertIn("not an endorsement", claim)
        for parts in (("claim.html",), ("s", "evil.example", "index.html"), ("s", "index.html")):
            self.assertNotIn("Verified", self.page(*parts), parts)

    def test_the_mark_never_appears_without_its_disclaimer(self):
        import glob
        marked = 0
        for f in glob.glob(os.path.join(self.out, "s", "*", "index.html")):
            html = open(f).read()
            if 'class="tag mark"' in html:
                marked += 1
                i = html.index('class="tag mark"')
                self.assertIn("It is not an endorsement", html[i:i + 900], f)   # beside the mark, not pages away
                self.assertNotIn("unclaimed page", html, f)
                self.assertNotIn("Is this your service?", html, f)
            else:
                self.assertIn("unclaimed page", html, f)
        self.assertEqual(marked, 1)

    def test_a_paying_stranger_cannot_inject_either(self):
        html = self.page("s", "rival.example-8443", "index.html")
        self.assertIn("We are &lt;b&gt;great&lt;/b&gt;&lt;script&gt;alert(3)", html)
        self.assertNotIn("<script>alert(3)", html)
        self.assertIn('href="https://docs.example/x"', html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("http://insecure.example", html)
        self.assertIn('rel="nofollow ugc noopener"', html)

    def test_no_claims_file_means_no_marks(self):
        out = tempfile.mkdtemp()
        sp.build(out, store(), site="https://example.test/atlas", claims="/nonexistent/claims.json")
        self.assertNotIn('class="tag mark"', open(os.path.join(out, "s", "rival.example-8443", "index.html")).read())

    def test_the_paid_endpoint_is_described_as_live_and_a_cent(self):
        html = self.page("s", "evil.example", "index.html")
        self.assertIn("a cent a call", html)
        self.assertIn("A refusal is never charged", html)
        self.assertNotIn("not yet for sale", html)
        self.assertNotIn("not yet for sale", self.page("claim.html"))

    def test_the_pro_page_exists_and_names_what_it_sells(self):
        html = self.page("pro.html")
        self.assertIn('<p class="eyebrow">Atlas Pro</p>', html)
        self.assertIn("<h1>The whole record, as data, every morning.</h1>", html)
        self.assertIn("$49", html)
        self.assertIn("a month", html)
        self.assertIn('curl -H "X-Atlas-Key: YOUR-KEY" https://ausrine-who.onrender.com/pro/export/sellers.csv', html)
        import pro                                   # the service's own column lists: the page cannot drift from them
        for name, (_what, cols) in pro.EXPORTS.items():
            self.assertIn("/pro/export/%s" % name, html)
            for c in cols or []:
                self.assertIn("<code>%s</code>" % c, html)

    def test_the_pro_page_has_no_buy_link_while_buy_pro_is_empty(self):
        self.assertEqual(sp.BUY_PRO, "")
        html = self.page("pro.html")
        self.assertIn("The subscription opens soon.", html)
        self.assertNotIn("buy.polar.sh", html)
        self.assertNotIn('class="btn', html)
        self.assertNotIn("Subscribe</a>", html)

    def test_with_a_buy_link_the_pro_page_shows_the_button(self):
        out, real = tempfile.mkdtemp(), sp.BUY_PRO
        sp.BUY_PRO = "https://buy.polar.sh/polar_cl_test"
        try:
            sp.build(out, store(), site="https://example.test/atlas", claims="/nonexistent/claims.json")
        finally:
            sp.BUY_PRO = real
        html = open(os.path.join(out, "pro.html")).read()
        self.assertIn('<a class="btn buy" href="https://buy.polar.sh/polar_cl_test">Subscribe</a>', html)
        self.assertNotIn("opens soon", html)

    def test_the_pro_page_never_says_verified(self):
        import re
        self.assertEqual(re.findall(r"(?i)verif", self.page("pro.html")), [])

    def test_pro_is_in_the_nav_and_the_rooms(self):
        nav = '<a class="pro" href="https://example.test/atlas/pro.html">Pro</a>'
        self.assertIn(nav, self.page("s", "evil.example", "index.html"))
        self.assertIn('<a href="https://example.test/atlas/pro.html">Atlas Pro</a>', self.page("index.html"))
        self.assertIn(nav, self.page("pro.html"))

    def test_the_tell_us_link_opens_the_correction_form_with_the_page_named(self):
        self.assertIn('issues/new?template=correct.yml&amp;title=Correction:+evil.example', self.page("s", "evil.example", "index.html"))

    def test_endpoints_are_listed_when_the_snapshot_kept_them(self):
        d = tempfile.mkdtemp()
        st = store()
        snap = os.path.join(st, "market-2026-01-02.json")
        s = json.load(open(snap))
        s["sellers"]["plain.example"]["endpoints"] = 14
        s["sellers"]["plain.example"]["top_endpoints"] = [{"path": "/v1/rng", "calls": 900, "payers": 30, "price": 0.001, "network": "Base"},
                                                          {"path": "/v1/<b>x</b>", "calls": 5, "payers": 1, "price": 0.35, "network": "Solana"}]
        json.dump(s, open(snap, "w"))
        sp.build(d, st, site="https://example.test/atlas", claims="/nonexistent/claims.json")
        html = open(os.path.join(d, "s", "plain.example", "index.html")).read()
        self.assertIn("<h2>Endpoints</h2>", html)
        self.assertIn("<code>/v1/rng</code></td><td class=\"n\">900</td><td class=\"n\">30</td><td class=\"n\">$0.001</td><td>Base</td>", html)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
        self.assertIn("12 more endpoints not shown", html)
        self.assertNotIn("<h2>Endpoints</h2>", open(os.path.join(d, "s", "evil.example", "index.html")).read())

    def test_self_dealing_caveat_is_on_every_seller_page(self):
        self.assertIn("Self-dealing is not filtered", self.page("s", "plain.example", "index.html"))


def priced_store():
    """Rivals on one topic (four rare words shared by four sellers clears the rival scorer's
    bar): two at a single price, one spread across a dozen endpoints so that the going rate
    falls inside its range (the api.anchor-x402.com shape, 2026-09-23), one wholly under it."""
    d = tempfile.mkdtemp()
    sellers = {"anchor.example": dict(row(40, "verifiable randomness oracle with entropy proofs and anchored timestamps", 0.01),
                                      endpoints=12, price_min=0.001, price_max=0.35),
               "rng.example": row(400, "verifiable randomness oracle, entropy for agents", 0.005),
               "dice.example": row(300, "entropy dice: verifiable randomness oracle, cheap", 0.005),
               "spread.example": dict(row(50, "verifiable randomness oracle, entropy in two tiers", 0.001),
                                      endpoints=2, price_min=0.001, price_max=0.002)}
    for i in range(60):
        sellers["filler%d.example" % i] = row(2, "filler offering number %d about topic%d subject%d" % (i, i, i))
    with open(os.path.join(d, "market-2026-01-02.json"), "w") as f:
        json.dump({"date": "2026-01-02", "taken": "2026-01-02", "endpoints": len(sellers), "sellers": sellers}, f)
    return d


class Prices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        sp.build(cls.out, priced_store(), site="https://example.test/atlas", claims="/nonexistent/claims.json")

    def page(self, host):
        return open(os.path.join(self.out, "s", host, "index.html")).read()

    def test_a_seller_with_many_prices_shows_the_range_and_gets_no_single_verdict(self):
        html = self.page("anchor.example")
        self.assertIn("$0.001–$0.35", html)
        self.assertIn("across 12 endpoints", html)
        self.assertIn("no single over/under verdict is fair", html)
        self.assertNotIn("which is <b>over</b>", html)
        self.assertNotIn("median price per call", html)

    def test_a_single_price_seller_still_gets_its_verdict(self):
        self.assertIn("This seller charges $0.005, which is <b>at</b> it.", self.page("rng.example"))

    def test_a_range_wholly_under_says_so_for_every_endpoint(self):
        self.assertIn("charges $0.001–$0.002, which is <b>under</b> it on every endpoint", self.page("spread.example"))

    def test_rivals_are_listed_by_their_range(self):
        self.assertIn('<td class="n">$0.001–$0.35</td>', self.page("rng.example"))

    def test_the_caveat_travels_with_every_page(self):
        self.assertIn("only when it holds for every endpoint", self.page("dice.example"))


def whales_file(d):
    """A day's rollup as whales.py writes it, for four of the priced_store sellers."""
    W = ["0x" + c * 40 for c in "1234"]
    seller = lambda host, n, usdc, payers, top3, word, top, ops=1, others=(), other_usdc=0.0: {
        "host": host, "wallets": ["0x" + "e" * 40], "on_chain_payments_x402": n, "on_chain_usdc_x402": usdc,
        "on_chain_usdc": usdc + other_usdc, "x402_payer_wallets": payers, "x402_top3_share": top3, "concentration": word,
        "x402_top_payers": [{"wallet": w, "short": w[:6] + "…" + w[-4:], "payments": c} for w, c in top],
        "operator_hosts": ops, "operator_other_hosts": list(others)}
    data = {"classified": True, "hours": 24, "as_of": "2026-01-02", "sellers": [
        seller("anchor.example", 983, 9.83, 1, 100, "one payer", [(W[0], 983)], ops=3, others=["anchor-two.example", "anchor-three.example"]),
        seller("rng.example", 400, 4.0, 47, 85, "concentrated", [(W[0], 200), (W[1], 100), (W[2], 40)], other_usdc=1500.0),
        seller("dice.example", 30, 0.3, 25, 20, "spread", [(W[0], 3), (W[1], 2), (W[2], 1)]),
    ], "operators": {"anchor.example": {"hosts": 3, "others": ["anchor-two.example", "anchor-three.example"]},
                     "filler3.example": {"hosts": 91, "others": ["filler%d.example" % i for i in range(4, 16)]}}}
    p = os.path.join(d, "whales-2026-01-02.json")
    json.dump(data, open(p, "w"))
    return p


class WhoActuallyPaid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        store = priced_store()
        snap = os.path.join(store, "market-2026-01-02.json")
        s = json.load(open(snap))
        s["sellers"]["spread.example"]["chains"] = ["Solana"]           # a seller the Base pull cannot see
        json.dump(s, open(snap, "w"))
        sp.build(cls.out, store, site="https://example.test/atlas", claims="/nonexistent/claims.json",
                 whales=whales_file(tempfile.mkdtemp()))

    def page(self, host):
        return open(os.path.join(self.out, "s", host, "index.html")).read()

    def test_one_payer_is_said_with_the_wallet_and_the_operator(self):
        html = self.page("anchor.example")
        self.assertIn('<span class="tag">one payer</span>', html)
        self.assertIn("<b>983 x402 payments</b> ($9.83)", html)
        self.assertIn("all of them from one wallet", html)
        self.assertIn('href="https://basescan.org/address/0x1111', html)
        self.assertIn("Payments to <b>3 hosts</b> land in this same wallet", html)
        self.assertIn("collecting for several: anchor-two.example, anchor-three.example.", html)

    def test_concentrated_names_the_busiest_three_and_the_money_that_was_not_a_call(self):
        html = self.page("rng.example")
        self.assertIn('<span class="tag">concentrated</span>', html)
        self.assertIn("from 47 wallets; the busiest three sent 85%", html)
        self.assertIn("Another $1,500 reached the same wallet by ordinary transfer, which is not a call being bought", html)
        self.assertNotIn("land in this same wallet", html)

    def test_spread_gets_the_facts_and_no_tag(self):
        html = self.page("dice.example")
        self.assertIn("from 25 wallets; the busiest three sent 20%", html)
        self.assertNotIn('<span class="tag">spread</span>', html)

    def test_no_payments_and_other_chains_are_said_plainly(self):
        self.assertIn("no x402 payment reached this seller", self.page("filler1.example"))
        self.assertIn("takes payment on Solana. The daily pull reads Base only", self.page("spread.example"))

    def test_an_unpaid_host_still_gets_its_operator(self):
        html = self.page("filler3.example")
        self.assertIn("no x402 payment reached this seller", html)
        self.assertIn("Payments to <b>91 hosts</b> land in this same wallet", html)
        self.assertIn("filler4.example", html)
        self.assertIn("and 84 more", html)

    def test_the_definition_travels_with_every_page(self):
        self.assertIn("facts about the payers, not verdicts on the seller", self.page("filler2.example"))

    def test_without_a_rollup_the_section_is_absent(self):
        out = tempfile.mkdtemp()
        sp.build(out, priced_store(), site="https://example.test/atlas", claims="/nonexistent/claims.json")
        self.assertNotIn("<h2>Who actually paid</h2>", open(os.path.join(out, "s", "rng.example", "index.html")).read())


def wallet(tag):
    return "0x" + (tag.encode().hex() + "0" * 40)[:40]


PLAIN, RIVAL, SHARED, NOPAGE = wallet("plain"), wallet("rival"), wallet("shared"), wallet("nopage")
FLOW_SELLERS = {PLAIN: ["plain.example"], RIVAL: ["rival.example:8443"], SHARED: ["evil.example", "filler1.example"],
                NOPAGE: ["<b>nopage</b>.example"]}


def flows_window(days=4):
    """A window of `days` flows files for store()'s sellers. plain.example: 12 buyers, 3 of them on
    two days; 3 of them also buy from rival; two leave it for the shared wallet, one comes from it;
    its last day has 10 buyers, 3 times its first."""
    d = tempfile.mkdtemp()
    ds = ["2026-01-0%d" % i for i in range(1, days + 1)]
    pays = {x: [] for x in ds}
    first = [wallet("p%d" % i) for i in range(3)]
    for b in first:                                          # day one: 3 buyers
        pays[ds[0]].append((b, PLAIN))
    if days >= 4:
        pays[ds[1]].append((wallet("p0"), PLAIN))            # p0 comes back on day two
        pays[ds[2]].append((wallet("p1"), SHARED))           # p1, p2 leave for the shared wallet
        pays[ds[3]].append((wallet("p2"), SHARED))
        pays[ds[0]].append((wallet("s0"), SHARED))           # s0 comes to plain from it
        pays[ds[3]].append((wallet("s0"), PLAIN))
        for i in range(9):                                   # the last day: 10 buyers, two of them back again
            pays[ds[3]].append((wallet("q%d" % i) if i > 1 else wallet("p%d" % (i + 3)), PLAIN))
        pays[ds[1]] += [(wallet("p3"), PLAIN), (wallet("p4"), PLAIN)]
        for b in (wallet("q2"), wallet("q3"), wallet("q4")):  # three of plain's buyers also paid rival
            pays[ds[3]].append((b, RIVAL))
        pays[ds[3]].append((wallet("q5"), NOPAGE))
    for x in ds:
        edges = [{"from": b, "to": s, "n": 1, "usdc": 0.01, "n_x402": 1, "usdc_x402": 0.01} for b, s in pays[x]]
        json.dump({"date": x, "day": x, "hours": 24.0, "edges": edges, "sellers": FLOW_SELLERS},
                  open(os.path.join(d, "flows-%s.json" % x), "w"))
    return d


class Relationships(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent/claims.json",
                 flows_dir=flows_window())

    def page(self, host):
        return open(os.path.join(self.out, "s", sp.slug(host), "index.html")).read()

    def section(self, host):
        html = self.page(host)
        i = html.index("<h2>Relationships</h2>")
        return html[i:html.index("<h2>", i + 5)]

    def test_the_facts_are_plain_sentences_with_their_numbers(self):
        s = self.section("plain.example")
        self.assertIn("x402 payments on Base · 1 January 2026 – 4 January 2026 · 4 days", s)
        self.assertIn("<b>13 buyers</b> paid this seller over x402 on 3 of the window’s 4 days: 16 payments, $0.16.", s)
        self.assertIn("<b>3 of 13 buyers came back</b> on another day (23%).", s)
        self.assertIn("paid on 2 days (2 payments)", s)
        self.assertIn('Bought alongside: <a href="https://example.test/atlas/s/rival.example-8443/">rival.example:8443</a> '
                      "(3 shared buyers, 23% of this seller’s buyers)", s)
        self.assertIn('2 buyers left for <a href="https://example.test/atlas/s/evil.example/">evil.example</a> and 1 more host on its wallet', s)
        self.assertIn('1 buyer came from <a href="https://example.test/atlas/s/evil.example/">evil.example</a>', s)
        self.assertIn("only on 1 Jan 2026 – 2 Jan 2026 and started paying the other only on 3 Jan 2026 – 4 Jan 2026", s)
        self.assertIn("<b>Early buyers:</b> 5 wallets paid it on 1 Jan 2026 and 2 Jan 2026, before its daily buyers went "
                      "from 3 on the first day of the window to 10 on the last.", s)
        self.assertIn("a relationship is a pattern of payments, not a claim about who anyone is", s)

    def test_buyer_wallets_link_to_the_explorer_when_they_have_no_page(self):
        self.assertIn('href="https://basescan.org/address/%s"><code>0x7030…0000</code>' % wallet("p0"), self.section("plain.example"))

    def test_a_wallet_shared_by_several_hosts_says_whose_facts_these_are(self):
        s = self.section("evil.example")
        self.assertIn("This wallet also takes payment for filler1.example; the facts below are the wallet’s, across both hosts.", s)
        self.assertIn("paid this wallet over x402", s)
        self.assertEqual(s, self.section("filler1.example").replace("filler1.example", "evil.example")
                         .replace("for evil.example;", "for filler1.example;"))

    def test_a_host_with_no_page_is_named_not_linked_and_escaped(self):
        html = self.page("filler2.example")
        self.assertIn("not in the window’s sellers map", html)
        plain = self.section("plain.example")
        self.assertIn("<li>Bought alongside: &lt;b&gt;nopage&lt;/b&gt;.example (1 shared buyer, 8% of this seller’s buyers)</li>", plain)
        self.assertNotIn("<b>nopage</b>", plain)
        self.assertNotIn("/s/-b-nopage", plain)

    def test_a_seller_nobody_paid_and_a_seller_on_one_day(self):
        s = self.section("rival.example:8443")
        self.assertIn("Paid on 1 day of the window: came-back facts need 2 or more days.", s)
        self.assertNotIn("Left for: buyers who", s)

    def test_never_the_forbidden_word_nor_a_score(self):
        import re
        for h in ("plain.example", "evil.example", "rival.example:8443"):
            s = self.section(h)
            self.assertEqual(re.findall(r"(?i)verif|score|rank", s), [], h)

    def test_without_the_window_the_section_says_it_was_not_loaded(self):
        out = tempfile.mkdtemp()
        sp.build(out, store(), site="https://example.test/atlas", claims="/nonexistent/claims.json")
        html = open(os.path.join(out, "s", "plain.example", "index.html")).read()
        self.assertIn("<h2>Relationships</h2><p class=\"muted\">The on-chain window was not loaded for this build", html)
        self.assertNotIn("came back", html)

    def test_an_empty_window_folder_says_no_day_could_be_read(self):
        out = tempfile.mkdtemp()
        sp.build(out, store(), site="https://example.test/atlas", claims="/nonexistent/claims.json", flows_dir=tempfile.mkdtemp())
        self.assertIn("held no day that could be read", open(os.path.join(out, "s", "plain.example", "index.html")).read())

    def test_a_one_day_window(self):
        out = tempfile.mkdtemp()
        sp.build(out, store(), site="https://example.test/atlas", claims="/nonexistent/claims.json", flows_dir=flows_window(1))
        html = open(os.path.join(out, "s", "plain.example", "index.html")).read()
        self.assertIn("<b>3 buyers</b> paid this seller over x402 on 1 of the window’s 1 day", html)
        self.assertIn("came-back facts need 2 or more days", html)
        self.assertNotIn("Early buyers", html)


class Money(unittest.TestCase):
    def test_a_sub_cent_total_is_not_zero(self):
        self.assertEqual(sp.money(0.001), "$0.001")
        self.assertEqual(sp.money(0.0), "$0.00")
        self.assertEqual(sp.money(1.5), "$1.50")


class Cli(unittest.TestCase):
    def run_main(self, *args):
        seen = []
        real, argv = sp.build, sys.argv
        sp.build = lambda *a: seen.append(a) or {"sellers": 0, "groups": 0, "as_of": "", "out": ""}
        sys.argv = ["seller_pages.py", "--out", "o"] + list(args)
        try:
            sp.main()
        finally:
            sp.build, sys.argv = real, argv
        return seen[0]

    def test_flows_argument_reaches_build(self):
        a = self.run_main("--whales", "store/whales-2026-01-02.json", "--flows", "store/flows-2026-01-02.json")
        self.assertEqual(a[4:], ("store/whales-2026-01-02.json", None, "store/flows-2026-01-02.json", None))

    def test_flows_dir_argument_reaches_build(self):
        self.assertEqual(self.run_main("--flows-dir", "flows")[7], "flows")


if __name__ == "__main__":
    unittest.main(verbosity=1)
