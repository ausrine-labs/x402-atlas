#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit c240cc7). Edit it there, not here.
"""map_page_test.py — the live map, from a synthetic day of flows. No network.

    python3 map_page_test.py

The flows are made up in chain_flows.py's shape and the rollup is made by
whales.rollup itself, so the map is tested against what the pipeline writes.
What matters most: only x402-settled money is drawn, every dot links to its
Atlas page, no dot is labelled with a name, and the cap is said out loud.
"""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map_page as mp  # noqa: E402
import seller_pages as sp  # noqa: E402
import whales  # noqa: E402

SITE = "https://example.test/atlas"
DAY = "2026-01-02"
AGENT = "0xAbCd" + "a1" * 18                  # mixed case: its page lives at the lowercase path
PLAIN = "0x" + "b2" * 20                      # x402 to two sellers, and a treasury move
GIFTER = "0x" + "b3" * 20                     # plain transfers only: never on the map
WA, WS, WG, WT, WE, WV = ("0x" + c * 40 for c in "123456")
EVIL_HOST = "<b>evil</b>.example"


def row(calls, sells, wallet):
    return {"endpoints": 1, "calls": calls, "payers": 3, "take": calls * 0.01, "chains": ["Base"],
            "wallets": [wallet], "price_min": 0.01, "price_med": 0.01, "price_max": 0.01,
            "sells": sells, "url": "https://x/"}


SNAP = {"alpha.example": row(900, "Company records by the call", WA),
        "rival.example:8443": row(50, "Price feed for perps", WS),
        "cards.example": row(3000, "Gift cards for USDC", WG),
        "vault.example": row(5, "Treasury", WT),
        EVIL_HOST: row(3, '<script>alert(7)</script> "quoted" & co', WE),
        "trustverify.example": row(40, "Verified company records, verifiably fresh", WV)}
SELLERS = {WA: ["alpha.example"], WS: ["rival.example:8443"], WG: ["cards.example"], WT: ["vault.example"],
           WE: [EVIL_HOST], WV: ["trustverify.example"]}


def e(f, t, n, usdc, nx, ux):
    return {"from": f, "to": t, "n": n, "usdc": usdc, "n_x402": nx, "usdc_x402": ux}


EDGES = [e(AGENT, WA, 600, 45.0, 600, 45.0), e(AGENT, WS, 12, 0.2, 10, 0.1), e(AGENT, WG, 1, 500.0, 0, 0.0),
         e(PLAIN, WS, 4, 0.4, 4, 0.4), e(PLAIN, WE, 1, 0.01, 1, 0.01), e(PLAIN, WV, 2, 0.02, 2, 0.02),
         e(PLAIN, WT, 2, 9000.0, 0, 0.0),
         e(GIFTER, WG, 3, 300.0, 0, 0.0)]


def write(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)
    return path


def day_store(edges=EDGES, sellers=SELLERS, snap=SNAP):
    """A flows store as flows_handoff.fetch leaves it, and a registry store for the radar."""
    fdir, rdir = tempfile.mkdtemp(), tempfile.mkdtemp()
    write(os.path.join(fdir, "flows-%s.json" % DAY),
          {"date": DAY, "hours": 24, "since_block": 1, "head": 2, "edges": edges, "sellers": sellers})
    chain_of = {w: "Base" for ed in edges for w in (ed["from"], ed["to"])}
    r = whales.rollup(edges, sellers, chain_of, 24, snap)
    r["dates"], r["as_of"] = [DAY], DAY
    wpath = write(os.path.join(fdir, "whales-%s.json" % DAY), r)
    write(os.path.join(rdir, "market-%s.json" % DAY), {"date": DAY, "taken": DAY, "endpoints": len(snap), "sellers": snap})
    return fdir, rdir, wpath


def read(*parts):
    with open(os.path.join(*parts)) as f:
        return f.read()


def drawn(page):
    """The graph the page draws, read back out of its script."""
    m = re.search(r"const G=(.*?);\nconst PAL=", page, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


class Map(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fdir, rdir, cls.whales = day_store()
        cls.out = tempfile.mkdtemp()
        cls.r = sp.build(cls.out, rdir, site=SITE, claims="/nonexistent.json", whales=cls.whales,
                         operators="/nonexistent-operators.json")
        cls.page = read(cls.out, "map", "index.html")
        cls.graph = json.loads(read(cls.out, "map", "graph.json"))
        cls.nodes = {n["u"]: n for n in cls.graph["nodes"]}

    def test_the_page_and_its_data_exist(self):
        self.assertTrue(self.r["map"])
        self.assertIn("<canvas id=\"c\"></canvas>", self.page)
        self.assertIn('href="graph.json"', self.page)
        self.assertIn("%s/map/</loc>" % SITE, read(self.out, "sitemap-sellers.xml"))

    def test_the_lede_counts_x402_payments_wallets_and_sellers(self):
        # 600 + 10 + 4 + 1 + 2 x402 payments; AGENT and PLAIN paid; alpha, rival, evil and trustverify were paid
        self.assertIn("Yesterday on Base: 617 x402 payments between 2 wallets and 4 sellers. "
                      "Gold is a seller, pink a wallet that paid; a line is money.", self.page)
        self.assertEqual(self.graph["totals"]["payments"], 617)

    def test_house_header_and_footer(self):
        self.assertIn('<a href="%s/map/">the map</a>' % SITE, self.page)
        self.assertIn('<a href="%s/b/">buyers</a>' % SITE, self.page)
        self.assertIn("As of %s" % DAY, self.page)
        self.assertIn('<link rel="canonical" href="%s/map/">' % SITE, self.page)
        self.assertLess(self.page.index("<header"), self.page.index('<canvas id="c">'))
        self.assertLess(self.page.index('<canvas id="c">'), self.page.index("<footer"))

    def test_standing_caveats(self):
        self.assertIn("A wallet is not an agent. One operator can appear as many wallets", self.page)
        self.assertIn(mp.NO_NAMES, self.page)

    def test_non_x402_money_is_absent(self):
        blob = json.dumps(self.graph).lower()
        self.assertNotIn(GIFTER.lower()[2:], blob)
        for host in ("cards.example", "vault.example"):
            self.assertNotIn(host, blob)
            self.assertNotIn(host, self.page)
        rival = [l for l in self.graph["links"] if l["b"] == "rival.example:8443"]
        self.assertEqual(sorted(l["w"] for l in rival), [4, 10])      # the x402 part only, not 12
        self.assertAlmostEqual(self.graph["totals"]["usdc"], 45.53)

    def test_seller_nodes_link_to_seller_pages(self):
        for host in ("alpha.example", "rival.example:8443"):
            url = self.nodes[host]["url"]
            self.assertEqual(url, "%s/s/%s/" % (SITE, sp.slug(host)))
            self.assertTrue(os.path.exists(os.path.join(self.out, "s", sp.slug(host), "index.html")))

    def test_buyer_nodes_link_to_buyer_pages(self):
        for w in (AGENT, PLAIN):
            n = self.nodes[whales.short(w)]
            self.assertEqual(n["url"], "%s/b/%s/" % (SITE, w.lower()))
            self.assertTrue(os.path.exists(os.path.join(self.out, "b", w.lower(), "index.html")))

    def test_labels_are_hosts_and_short_wallets_never_names(self):
        for n in self.graph["nodes"]:
            self.assertEqual(n["n"], "")
            if n["k"] == "agent":
                self.assertEqual(n["u"], whales.short(n["wallet"][0]))
            else:
                self.assertTrue(n["u"] in SNAP or n["u"] == whales.short(WV), n["u"])
        for n in drawn(self.page)["nodes"]:
            self.assertNotIn(n["u"], (AGENT, PLAIN))

    def test_stranger_markup_stays_data(self):
        self.assertNotIn("<b>evil</b>", self.page)
        self.assertNotIn("<script>alert(7)", self.page)
        self.assertEqual(self.page.count("</script>"), 2)

    def test_every_line_drawn_when_under_the_cap(self):
        self.assertIn("Every line is drawn: 5 lines.", self.page)
        self.assertEqual(self.graph["drawn"]["left_out"], {"edges": 0, "wallets": 0, "sellers": 0})

    def test_the_page_script_escapes_quotes_and_refuses_odd_links(self):
        # a seller writes its own host and description; in an attribute a bare quote would end it
        self.assertIn('''const esc=s=>String(s).replace(/[&<>"']/g''', self.page)
        self.assertIn("const safeUrl=", self.page)
        self.assertIn("const prof=n=>safeUrl(", self.page)
        self.assertIn("href=\"'+esc(safeUrl(n.url))+'\"", self.page)

    def test_the_banned_word_is_absent(self):
        # a seller's own description and host use it; the map carries neither, only the link
        for text in (self.page, json.dumps(self.graph)):
            self.assertIsNone(re.search(r"verif", re.sub(r'"url": ?"[^"]*"', "", text), re.I))
        n = self.nodes[whales.short(WV)]
        self.assertEqual((n["url"], n["s"]), ("%s/s/trustverify.example/" % SITE, ""))


class Cap(unittest.TestCase):
    """405 wallets pay; the 400 busiest lines are drawn and the rest are named as left out."""

    @classmethod
    def setUpClass(cls):
        wallets = ["0x%040x" % (i + 1) for i in range(405)]
        edges = [e(w, WA, 1000 - i, 1.0, 1000 - i, 1.0) for i, w in enumerate(wallets)]
        edges.append(e(wallets[0], WG, 7, 70.0, 0, 0.0))                  # plain: neither drawn nor counted
        fdir, _rdir, wpath = day_store(edges)
        cls.out = tempfile.mkdtemp()
        cls.r = mp.build(cls.out, os.path.join(fdir, "flows-%s.json" % DAY), wpath, SNAP, SITE, DAY)
        cls.page = read(cls.out, "map", "index.html")
        cls.graph = json.loads(read(cls.out, "map", "graph.json"))
        cls.wallets = wallets

    def test_the_cap_is_honoured(self):
        g = drawn(self.page)
        self.assertEqual(len(g["links"]), mp.CAP)
        self.assertEqual(len([n for n in g["nodes"] if n["k"] == "agent"]), mp.CAP)
        kept = {n["u"] for n in g["nodes"]}
        self.assertIn(whales.short(self.wallets[0]), kept)             # the busiest stay
        self.assertNotIn(whales.short(self.wallets[-1]), kept)         # the quietest go

    def test_the_cap_is_reported(self):
        self.assertIn("Drawn: the 400 busiest lines of 405, by x402 payments. "
                      "Left out of the picture: 5 lines, 5 wallets and 0 sellers", self.page)
        self.assertEqual(self.graph["drawn"], {"cap": 400, "edges": 405, "drawn": 400,
                                               "left_out": {"edges": 5, "wallets": 5, "sellers": 0}})
        self.assertIn("between 405 wallets and 1 seller.", self.page)

    def test_graph_json_keeps_every_x402_line(self):
        self.assertEqual(len(self.graph["links"]), 405)
        self.assertNotIn("cards.example", json.dumps(self.graph))


class Wiring(unittest.TestCase):
    def test_no_flows_for_the_day_leaves_the_map_alone(self):
        fdir, rdir, wpath = day_store()
        os.remove(os.path.join(fdir, "flows-%s.json" % DAY))
        out = tempfile.mkdtemp()
        r = sp.build(out, rdir, site=SITE, claims="/nonexistent.json", whales=wpath, operators="/nonexistent-operators.json")
        self.assertIsNone(r["map"])
        self.assertFalse(os.path.exists(os.path.join(out, "map")))

    def test_flows_of_another_day_are_not_used(self):
        fdir, rdir, wpath = day_store()
        os.rename(os.path.join(fdir, "flows-%s.json" % DAY), os.path.join(fdir, "flows-2026-01-01.json"))
        out = tempfile.mkdtemp()
        r = sp.build(out, rdir, site=SITE, claims="/nonexistent.json", whales=wpath, operators="/nonexistent-operators.json")
        self.assertIsNone(r["map"])

    def test_the_rollup_named_for_the_build_day_finds_the_day_it_covers(self):
        # as the daily build publishes them: whales-<today>.json covers flows-<yesterday>.json
        fdir, rdir, wpath = day_store()
        r = json.load(open(wpath))
        r["as_of"], r["dates"] = "2026-01-03", [DAY]
        os.remove(wpath)
        wpath = write(os.path.join(fdir, "whales-2026-01-03.json"), r)
        out = tempfile.mkdtemp()
        got = sp.build(out, rdir, site=SITE, claims="/nonexistent.json", whales=wpath, operators="/nonexistent-operators.json")
        self.assertEqual(got["map"]["payments"], 617)

    def test_an_explicit_flows_path_is_used(self):
        fdir, rdir, wpath = day_store()
        other = tempfile.mkdtemp()
        path = os.path.join(other, "today.json")
        os.rename(os.path.join(fdir, "flows-%s.json" % DAY), path)
        out = tempfile.mkdtemp()
        r = sp.build(out, rdir, site=SITE, claims="/nonexistent.json", whales=wpath,
                     operators="/nonexistent-operators.json", flows=path)
        self.assertEqual(r["map"]["payments"], 617)

    def test_a_broken_flows_file_costs_the_map_not_the_site(self):
        fdir, rdir, wpath = day_store()
        with open(os.path.join(fdir, "flows-%s.json" % DAY), "w") as f:
            f.write("{not json")
        out = tempfile.mkdtemp()
        r = sp.build(out, rdir, site=SITE, claims="/nonexistent.json", whales=wpath, operators="/nonexistent-operators.json")
        self.assertIsNone(r["map"])
        self.assertTrue(os.path.exists(os.path.join(out, "s", "alpha.example", "index.html")))

    def test_no_rollup_no_map(self):
        _fdir, rdir, _wpath = day_store()
        out = tempfile.mkdtemp()
        r = sp.build(out, rdir, site=SITE, claims="/nonexistent.json")
        self.assertIsNone(r["map"])


if __name__ == "__main__":
    unittest.main()
