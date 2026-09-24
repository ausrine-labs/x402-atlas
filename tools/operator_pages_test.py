#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 079001a). Edit it there, not here.
"""operator_pages_test.py — a page for every wallet group, from a synthetic rollup. No network.

    python3 operator_pages_test.py

The mark "Claimed by operator" may never be shown without the sentence that says
what it does not mean; that is the test that matters most, as with the seller mark.
"""
import glob
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operator_pages as op  # noqa: E402
import seller_pages as sp  # noqa: E402

EVIL = '<script>alert(9)</script> "quoted" & co'


def row(calls, sells, price=0.02):
    return {"endpoints": 1, "calls": calls, "payers": 3, "take": calls * price, "chains": ["Base"],
            "wallets": ["0x" + "ab" * 20], "price_min": price, "price_med": price, "price_max": price,
            "sells": sells, "url": "https://x/"}


def store():
    d = tempfile.mkdtemp()
    sellers = {"alpha.aslan.example": row(900, "onchain pulse for agents"), "beta.aslan.example": row(50, "crypto pulse"),
               "gamma.aslan.example": row(0, "wealth pulse"), "solo.example": row(20, "weather"),
               "one.ninety.workers.dev": row(5, "a worker"), "two.ninety.workers.dev": row(5, "another worker")}
    for i in range(60):
        sellers["filler%d.example" % i] = row(2, "filler offering number %d about topic%d subject%d" % (i, i, i))
    with open(os.path.join(d, "market-2026-01-02.json"), "w") as f:
        json.dump({"date": "2026-01-02", "taken": "2026-01-02", "endpoints": len(sellers), "sellers": sellers}, f)
    return d


def whales(d):
    W = "0x" + "c1" * 20
    data = {"classified": True, "hours": 24, "as_of": "2026-01-02",
            "sellers": [{"host": "alpha.aslan.example", "wallets": ["0x" + "ab" * 20], "on_chain_payments_x402": 600, "on_chain_usdc_x402": 45.0, "on_chain_usdc": 5045.0,
                         "x402_payer_wallets": 1, "x402_top3_share": 100, "concentration": "one payer",
                         "x402_top_payers": [{"wallet": W, "short": "0xc1c1…c1c1", "payments": 600}]},
                        {"host": "beta.aslan.example", "wallets": ["0x" + "ab" * 20], "on_chain_payments_x402": 69, "on_chain_usdc_x402": 3.9, "on_chain_usdc": 3.9,
                         "x402_payer_wallets": 2, "x402_top3_share": 100, "concentration": "concentrated",
                         "x402_top_payers": [{"wallet": W, "short": "0xc1c1…c1c1", "payments": 60}, {"wallet": "0x" + "d2" * 20, "short": "0xd2d2…d2d2", "payments": 9}]}],
            "operators": {"alpha.aslan.example": {"group": 0, "hosts": 3, "others": ["beta.aslan.example", "gamma.aslan.example"]},
                          "beta.aslan.example": {"group": 0, "hosts": 3, "others": ["alpha.aslan.example", "gamma.aslan.example"]},
                          "gamma.aslan.example": {"group": 0, "hosts": 3, "others": ["alpha.aslan.example", "beta.aslan.example"]},
                          "one.ninety.workers.dev": {"group": 1, "hosts": 2, "others": ["two.ninety.workers.dev"]},
                          "two.ninety.workers.dev": {"group": 1, "hosts": 2, "others": ["one.ninety.workers.dev"]}},
            "groups": [{"id": 0, "hosts": ["alpha.aslan.example", "beta.aslan.example", "gamma.aslan.example"], "wallets": 1},
                       {"id": 1, "hosts": ["one.ninety.workers.dev", "two.ninety.workers.dev"], "wallets": 1}]}
    p = os.path.join(d, "whales-2026-01-02.json")
    json.dump(data, open(p, "w"))
    return p


CLAIMED = {"The Aslan Group": {"hosts": ["beta.aslan.example"], "description": "We are <b>%s</b>" % EVIL,
                               "logo": "https://cdn.example/l.png",
                               "links": [{"label": "Site", "url": "https://aslan.example/"}, {"label": "Evil", "url": "javascript:alert(1)"}],
                               "claimed_on": "2026-01-02"}}


class Names(unittest.TestCase):
    def test_registrable_and_group_name(self):
        self.assertEqual(op.registrable("onchainpulse.theaslangroupllc.com"), "theaslangroupllc.com")
        self.assertEqual(op.registrable("agent-memory.johntaylor1online.workers.dev"), "johntaylor1online.workers.dev")
        self.assertEqual(op.registrable("api.x.example:8443"), "x.example")
        self.assertEqual(op.group_name(["a.aslan.example", "b.aslan.example", "c.other.example"]), "aslan.example")

    def test_a_group_is_named_by_the_host_that_earned_when_one_took_half(self):
        hosts = ["a.aslan.example", "b.aslan.example", "earner.other"]
        paid = lambda **n: {"sellers": {h.replace("_", "."): {"on_chain_payments_x402": v} for h, v in n.items()}}
        self.assertEqual(op.naming(hosts, paid(earner_other=90, a_aslan_example=10)), ("earner.other", 90))
        self.assertEqual(op.naming(hosts, paid(earner_other=60, b_aslan_example=40)), ("earner.other", 60))
        # a busy subdomain of the group's own company keeps the company's name, and its page address
        self.assertEqual(op.naming(hosts, paid(a_aslan_example=90, earner_other=10)), ("aslan.example", None))
        self.assertEqual(op.naming(hosts, paid(earner_other=40, a_aslan_example=30, b_aslan_example=30)), ("aslan.example", None))
        self.assertEqual(op.naming(hosts, {"sellers": {}}), ("aslan.example", None))                        # nothing paid
        self.assertEqual(op.group_name(hosts, None), "aslan.example")
        # the rollup as published (a list) reads the same as load_chain's dict
        self.assertEqual(op.naming(hosts, {"sellers": [{"host": "earner.other", "on_chain_payments_x402": 7}]}), ("earner.other", 100))

    def test_the_disclaimer_is_unchanged(self):
        self.assertEqual(op.DISCLAIMER, "“Claimed by operator” means the operator proved control of the hosts the registry lists under "
                         "this wallet. It is not an endorsement, a safety check, or a judgement that any of these services "
                         "is good or real. The numbers on these pages are never for sale.")


class Unclaimed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.r = sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent.json",
                         whales=whales(tempfile.mkdtemp()), operators="/nonexistent-operators.json")

    def page(self, *parts):
        return open(os.path.join(self.out, *parts)).read()

    def test_a_page_per_group_named_and_listed(self):
        self.assertEqual(self.r["groups"], 2)
        self.assertTrue(os.path.exists(os.path.join(self.out, "o", "aslan.example", "index.html")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "o", "ninety.workers.dev", "index.html")))
        idx = self.page("o", "index.html")
        self.assertIn('href="https://example.test/atlas/o/aslan.example/">aslan.example</a>', idx)
        self.assertIn("2 groups hold 5 of the", idx)

    def test_the_group_page_sums_the_hosts_and_names_the_busiest_payers(self):
        html = self.page("o", "aslan.example", "index.html")
        self.assertIn("<h1>aslan.example</h1>", html)
        self.assertIn('<span class="tag">unclaimed group</span>', html)
        self.assertIn("<b>3</b><span>hosts paid into this wallet</span>", html)
        self.assertIn("<b>669</b><span>x402 payments", html)
        self.assertIn("<b>$48.90</b><span>USDC, x402-settled</span>", html)
        self.assertIn("<b>2</b><span>hosts that took an x402 payment</span>", html)
        self.assertIn("<b>950</b><span>self-reported calls, 30 days</span>", html)
        self.assertIn("<b>$5,000</b><span>reached the wallet by ordinary transfer, not a call</span>", html)
        self.assertIn("0xc1c1…c1c1</code></a> 660", html)                       # 600 + 60 across two hosts
        self.assertIn("Nobody has put a name on this group yet", html)
        self.assertIn("Name this group</a>", html)
        self.assertIn("reference_id=o%3Aaslan.example", html.replace("reference_id=o:aslan.example", "reference_id=o%3Aaslan.example"))
        self.assertNotIn('class="tag mark"', html)


    def test_the_hosts_table_links_every_host(self):
        html = self.page("o", "aslan.example", "index.html")
        for h in ("alpha.aslan.example", "beta.aslan.example", "gamma.aslan.example"):
            self.assertIn('href="https://example.test/atlas/s/%s/">%s</a>' % (h, h), html)
        self.assertIn("<td>one payer</td>", html)

    def test_a_group_nothing_paid_says_so(self):
        html = self.page("o", "ninety.workers.dev", "index.html")
        self.assertIn("No x402 payment reached any host of this group", html)
        self.assertIn("<b>$0</b><span>USDC", html)

    def test_the_host_page_links_to_its_group(self):
        html = self.page("s", "gamma.aslan.example", "index.html")
        self.assertIn('The group’s page: <a href="https://example.test/atlas/o/aslan.example/">aslan.example</a>', html)
        self.assertIn("operators</a>", html)                                          # the nav has the room

    def test_the_sitemap_lists_the_group_pages(self):
        sm = self.page("sitemap-sellers.xml")
        self.assertIn("<loc>https://example.test/atlas/o/</loc>", sm)
        self.assertIn("<loc>https://example.test/atlas/o/aslan.example/</loc>", sm)


class Earner(unittest.TestCase):
    """A host of another domain took most of the group's payments: the group is named for it, and says so."""
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        rollup = whales(tempfile.mkdtemp())
        d = json.load(open(rollup))
        g = next(g for g in d["groups"] if "alpha.aslan.example" in g["hosts"])
        g["hosts"].append("earner.other")
        d["sellers"].append(dict(d["sellers"][0], host="earner.other", on_chain_payments_x402=6000))
        json.dump(d, open(rollup, "w"))
        sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent.json",
                 whales=rollup, operators="/nonexistent-operators.json")

    def test_named_for_the_earner_and_says_so(self):
        html = open(os.path.join(self.out, "o", "earner.other", "index.html")).read()
        i = html.index("<h1>earner.other</h1>")
        self.assertIn("Named for the host that took", html[i:i + 400])
        self.assertIn("the registry lists 4 hosts under the same wallet.", html[i:i + 400])
        self.assertNotIn("Named for the host", open(os.path.join(self.out, "o", "ninety.workers.dev", "index.html")).read())


class Spread(unittest.TestCase):
    """No host took half: the group keeps the domain its hosts share."""
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        rollup = whales(tempfile.mkdtemp())
        d = json.load(open(rollup))
        d["sellers"][0]["on_chain_payments_x402"] = 300
        d["sellers"][1]["on_chain_payments_x402"] = 250
        d["sellers"].append(dict(d["sellers"][1], host="gamma.aslan.example", on_chain_payments_x402=200))
        json.dump(d, open(rollup, "w"))
        sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent.json",
                 whales=rollup, operators="/nonexistent-operators.json")

    def test_the_domain_names_the_group(self):
        html = open(os.path.join(self.out, "o", "aslan.example", "index.html")).read()
        self.assertIn("<h1>aslan.example</h1>", html)
        self.assertNotIn("Named for the host", html)
        self.assertFalse(os.path.exists(os.path.join(self.out, "o", "alpha.aslan.example")))


class BuyerLinks(unittest.TestCase):
    """The busiest wallets link to their buyer pages when those pages exist, else to the explorer."""
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        rollup = whales(tempfile.mkdtemp())
        d = json.load(open(rollup))
        W = "0x" + "c1" * 20
        d["buyers"] = [{"wallet": W, "short": "0xc1c1…c1c1", "chain": "Base", "usdc": 48.0, "payments": 660, "usdc_x402": 48.0,
                        "payments_x402": 660, "sellers_paid": 2, "sellers_paid_x402": 2, "categories": ["other"],
                        "sellers": [{"host": "alpha.aslan.example", "payments": 600, "usdc": 45.0, "payments_x402": 600, "usdc_x402": 45.0}]}]
        json.dump(d, open(rollup, "w"))
        sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent.json",
                 whales=rollup, operators="/nonexistent-operators.json")
        cls.html = open(os.path.join(cls.out, "o", "aslan.example", "index.html")).read()

    def test_a_wallet_with_a_page_links_there(self):
        self.assertTrue(os.path.exists(os.path.join(self.out, "b", "0x" + "c1" * 20, "index.html")))
        self.assertIn('<a href="https://example.test/atlas/b/0x%s/"><code>0xc1c1…c1c1</code></a> 660' % ("c1" * 20), self.html)
        self.assertNotIn("basescan.org/address/0x" + "c1" * 20, self.html)

    def test_a_wallet_without_one_links_to_the_explorer(self):
        self.assertIn('href="https://basescan.org/address/0x%s"><code>0xd2d2…d2d2</code></a> 9' % ("d2" * 20), self.html)


class Claimed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        fd, cls.ops = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(CLAIMED, f)
        sp.build(cls.out, store(), site="https://example.test/atlas", claims="/nonexistent.json",
                 whales=whales(tempfile.mkdtemp()), operators=cls.ops)

    def page(self, *parts):
        return open(os.path.join(self.out, *parts)).read()

    def test_the_claimed_group_carries_its_name_mark_and_disclaimer_and_no_offer(self):
        html = self.page("o", "aslan.example", "index.html")
        self.assertIn("<h1>The Aslan Group</h1>", html)
        self.assertIn('<span class="tag mark">Claimed by operator</span>', html)
        i = html.index('class="tag mark"')
        self.assertIn("It is not an endorsement", html[i:i + 900])
        self.assertNotIn("Name this group", html)
        self.assertNotIn("unclaimed group", html)
        self.assertNotIn("Named for the host", html)                                # the operator’s name, not ours

    def test_a_paying_stranger_cannot_inject(self):
        html = self.page("o", "aslan.example", "index.html")
        self.assertIn("We are &lt;b&gt;&lt;script&gt;alert(9)", html)
        self.assertNotIn("<script>alert(9)", html)
        self.assertIn('href="https://aslan.example/"', html)
        self.assertNotIn("javascript:", html)

    def test_the_mark_never_appears_without_its_disclaimer_anywhere_under_o(self):
        marked = 0
        for f in glob.glob(os.path.join(self.out, "o", "**", "index.html"), recursive=True):
            html = open(f).read()
            if 'class="tag mark"' in html:
                marked += 1
                self.assertIn("It is not an endorsement", html, f)
        self.assertEqual(marked, 2)                                                 # the group page and the /o/ list

    def test_the_host_page_says_the_group_is_claimed_and_by_whom(self):
        html = self.page("s", "alpha.aslan.example", "index.html")
        self.assertIn("The group is claimed by its operator", html)
        self.assertIn('href="https://example.test/atlas/o/aslan.example/">The Aslan Group</a>', html)
        self.assertIn("it is not an endorsement", html)


if __name__ == "__main__":
    unittest.main(verbosity=1)
