#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f00a5fb). Edit it there, not here.
"""board_test.py — The Board, on a week small enough to count by hand.

Seven days, 2026-01-01 to 2026-01-07. Sellers (payTo wallets) and the hosts on them:

    0xs1  a.example   "Weather forecast for any city"
    0xs2  b.example   "Search the web, <b>fast</b> & cheap"
    0xs3  c.example   a description holding the word the Atlas never says
    0xf01..0xf19      fillerNN.example, not in the registry

Payments, all x402 unless said:

    0xa  -> s1  days 1 and 2, $1 each       customer, returning
    0xb  -> s1  days 1 and 3, $1 each       customer, returning
    0xc  -> s1  day 1, $1                   customer
    0xr  -> s1  day 4, $1; f01..f19 $0.01   a robot: 20 sellers. Not a customer; its money counts
    0xz  -> s1  day 5, $7, n_x402 0         not x402: not counted at all
    0xd  -> s2  day 1, $10                  customer, over half of s2's money
    0xe, 0xf, 0xg -> s2  day 2, $1 each     customers
    0xq  -> s2 day 3 $1; f01..f18 $0.01     19 sellers, one short of a robot: a customer
    0xh  -> s3  days 6 and 7, $2 each       customer, returning
    0xa  -> 0xnot  day 1, $50               not in the sellers map: not counted

Counted by hand:

    s1   3 customers, 2 returning, $6, top payer $2 of $6 = 33.3%       unmarked
    f01..f18  1 customer (q), 0 returning, $0.02, top payer 50%         unmarked: half is not over half
    f19  paid only by the robot: no customer, left off
    s3   1 customer, 1 returning, $4, top payer 100%                    marked
    s2   5 customers, 0 returning, $14, top payer $10 = 71.4%           marked

Order: s1, f01..f18, then the marked: s3 (1 returning) before s2 (0), though s2 has the
most customers of all.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board  # noqa: E402

DATES = ["2026-01-0%d" % i for i in range(1, 8)]
FILLERS = ["0xf%02d" % i for i in range(1, 20)]
HOSTS = {"0xs1": ["a.example"], "0xs2": ["b.example"], "0xs3": ["c.example"]}
HOSTS.update({w: ["filler%s.example" % w[3:]] for w in FILLERS})
SNAPSHOT = {
    "a.example": {"sells": "Weather forecast for any city", "url": "https://a.example/forecast",
                  "price_min": 0.01, "price_med": 0.01, "price_max": 0.01, "calls": 5},
    "b.example": {"sells": "Search the web, <b>fast</b> & cheap", "url": "https://b.example/search",
                  "price_min": 0.001, "price_med": 0.002, "price_max": 0.005, "calls": 900},
    "c.example": {"sells": "Ver" + "ified weather alerts", "url": "https://c.example/alerts",
                  "price_min": 0.05, "price_med": 0.05, "price_max": 0.05, "calls": 1},
}


def e(frm, to, usdc, n=1, x402=True):
    return {"from": frm, "to": to, "n": n, "usdc": usdc, "n_x402": n if x402 else 0, "usdc_x402": usdc if x402 else 0}


# day number (1-7) -> edges
EDGES = {
    1: [e("0xa", "0xs1", 1), e("0xb", "0xs1", 1), e("0xc", "0xs1", 1), e("0xd", "0xs2", 10), e("0xa", "0xnot", 50)],
    2: [e("0xa", "0xs1", 1), e("0xe", "0xs2", 1), e("0xf", "0xs2", 1), e("0xg", "0xs2", 1)],
    3: [e("0xb", "0xs1", 1), e("0xq", "0xs2", 1)] + [e("0xq", w, 0.01) for w in FILLERS[:18]],
    4: [e("0xr", "0xs1", 1)] + [e("0xr", w, 0.01) for w in FILLERS],
    5: [e("0xz", "0xs1", 7, x402=False)],
    6: [e("0xh", "0xs3", 2)],
    7: [e("0xh", "0xs3", 2)],
}


def write_week(folder, days=range(1, 8)):
    for i in days:
        d = {"date": DATES[i - 1], "hours": 24, "edges": EDGES[i], "sellers": HOSTS}
        with open(os.path.join(folder, "flows-%s.json" % DATES[i - 1]), "w") as f:
            json.dump(d, f)
    return folder


class Shape(unittest.TestCase):
    def test_each_word_by_its_rule(self):
        self.assertEqual(board.shape([10, 10, 10, 10, 10, 10, 10.9]), "flat")
        self.assertEqual(board.shape([10, 10, 10, 10, 10, 10, 11.1]), "uneven")       # 11% off the median
        self.assertEqual(board.shape([1, 1, 1, 1, 1, 1, 1]), "uneven")                # median not above $1
        self.assertEqual(board.shape([0, 0, 0, 50, 1, 1, 1]), "spike")                # 50 of 53
        self.assertEqual(board.shape([30, 30, 30, 30, 30, 1, 1]), "gone quiet")       # 1 < 5% of 30, an earlier $30
        self.assertEqual(board.shape([19, 19, 19, 19, 19, 0.5, 0.5]), "uneven")       # never a $20 day
        self.assertEqual(board.shape([5, 5, 5, 5, 6, 7, 8]), "ramping")
        self.assertEqual(board.shape([5, 5, 5, 5, 6, 7, 7]), "uneven")                # the last day is not higher
        self.assertEqual(board.shape([3, 3, 3, 3, 4, 5, 6]), "ramping")

    def test_first_rule_that_fits_wins(self):
        # a spike that is also gone quiet afterwards is a spike
        self.assertEqual(board.shape([0, 0, 100, 0, 0, 0, 0]), "spike")

    def test_no_word_without_a_whole_week_or_without_money(self):
        self.assertIsNone(board.shape([1, 2, None, 4, 5, 6, 7]))
        self.assertIsNone(board.shape([0] * 7))
        self.assertIsNone(board.shape([]))


class Week(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = write_week(tempfile.mkdtemp())
        cls.b = board.compute(cls.dir, SNAPSHOT)
        cls.by = {r["host"]: r for r in cls.b["sellers"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_window_is_the_seven_days(self):
        self.assertEqual(self.b["window"]["from"], "2026-01-01")
        self.assertEqual(self.b["window"]["to"], "2026-01-07")
        self.assertEqual(self.b["window"]["days"], 7)
        self.assertEqual(self.b["problems"], [])

    def test_the_robot_is_found_and_the_19_seller_wallet_is_not_one(self):
        self.assertEqual(self.b["robots"]["wallets"], 1)                 # 0xr paid s1 + 19 fillers = 20

    def test_s1_customers_returning_money(self):
        r = self.by["a.example"]
        self.assertEqual(r["customers"], 3)                              # a, b, c; not r (robot), not z (not x402)
        self.assertEqual(r["returning"], 2)                              # a (days 1, 2), b (days 1, 3)
        self.assertEqual(r["robot_payers"], 1)
        self.assertEqual(r["usdc"], 6.0)                                 # a 2 + b 2 + c 1 + r 1
        self.assertEqual(r["payments"], 6)
        self.assertEqual(r["daily_usdc"], [3.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
        self.assertEqual(r["top_payer_share_pct"], 33.3)                 # a or b: $2 of $6
        self.assertFalse(r["one_payer_most"])
        self.assertEqual(r["shape"], "uneven")                           # $3 of $6 is half, not over half
        self.assertEqual(r["wallet"], "0xs1")

    def test_exactly_half_from_one_payer_is_not_marked(self):
        r = self.by["filler01.example"]
        self.assertEqual((r["customers"], r["returning"], r["usdc"]), (1, 0, 0.02))
        self.assertEqual(r["top_payer_share_pct"], 50.0)
        self.assertFalse(r["one_payer_most"])

    def test_s2_one_payer_is_most_of_it(self):
        r = self.by["b.example"]
        self.assertEqual(r["customers"], 5)                              # d, e, f, g, q (19 sellers: still a customer)
        self.assertEqual(r["returning"], 0)
        self.assertEqual(r["usdc"], 14.0)
        self.assertEqual(r["top_payer_share_pct"], 71.4)                 # d: $10 of $14
        self.assertTrue(r["one_payer_most"])
        self.assertEqual(r["daily_usdc"], [10.0, 3.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(r["shape"], "spike")                            # 10 of 14

    def test_s3_one_customer_twice(self):
        r = self.by["c.example"]
        self.assertEqual((r["customers"], r["returning"], r["usdc"]), (1, 1, 4.0))
        self.assertEqual(r["top_payer_share_pct"], 100.0)
        self.assertTrue(r["one_payer_most"])

    def test_rank_by_returning_then_customers_marked_last(self):
        fill = ["filler%02d.example" % i for i in range(1, 19)]
        self.assertEqual([r["host"] for r in self.b["sellers"]], ["a.example"] + fill + ["c.example", "b.example"])
        self.assertEqual([r["rank"] for r in self.b["sellers"]], list(range(1, 22)))
        self.assertEqual(self.b["one_payer_most"], 2)
        flags = [r["one_payer_most"] for r in self.b["sellers"]]
        self.assertEqual(flags, sorted(flags))                           # every marked row after every unmarked one

    def test_a_seller_paid_only_by_robots_is_left_off(self):
        self.assertEqual(self.b["sellers_ranked"], 21)
        self.assertNotIn("filler19.example", self.by)

    def test_categories_from_the_registry_text(self):
        self.assertEqual(self.by["a.example"]["category"], "world data")
        self.assertEqual(self.by["b.example"]["category"], "search & web")
        self.assertEqual(self.by["c.example"]["category"], "trust & agent infra")
        self.assertEqual(self.by["filler01.example"]["category"], "other")       # not in the registry: from its host
        self.assertEqual(self.by["a.example"]["category_rank"], 1)
        self.assertEqual(self.by["filler02.example"]["category_rank"], 2)
        self.assertEqual(set(self.b["categories"]), {r["category"] for r in self.b["sellers"]})

    def test_price_from_the_registry(self):
        self.assertEqual(self.by["a.example"]["price"], "$0.01")
        self.assertEqual(self.by["b.example"]["price"], "$0.001–$0.005")

    def test_reason_line(self):
        self.assertEqual(self.by["a.example"]["reason"], "2 returning customers of 3, no single payer over 40%")
        self.assertEqual(self.by["c.example"]["reason"], "1 returning customer of 1; one payer sent 100% of its money")
        self.assertEqual(self.by["b.example"]["reason"], "0 returning customers of 5; one payer sent 71.4% of its money")
        self.assertEqual(board.reason({"returning": 31, "customers": 40, "top_payer_share_pct": 17.3,
                                       "one_payer_most": False}),
                         "31 returning customers of 40, no single payer over 20%")
        self.assertEqual(board.reason({"returning": 1, "customers": 9, "top_payer_share_pct": 2.1,
                                       "one_payer_most": False}),
                         "1 returning customer of 9, no single payer over 10%")


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = write_week(tempfile.mkdtemp())
        cls.out = tempfile.mkdtemp()
        cls.b = board.build(cls.out, cls.dir, SNAPSHOT, "https://atlas.example", "2026-01-07", n=3)
        cls.html = open(os.path.join(cls.out, "board", "index.html")).read()
        cls.raw = open(os.path.join(cls.out, "board", "board.json")).read()
        cls.json = json.loads(cls.raw)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)
        shutil.rmtree(cls.out)

    def test_the_page_in_the_atlas_look(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertIn('<link rel="stylesheet" href="https://atlas.example/atlas.css">', self.html)
        self.assertIn('<a href="https://atlas.example/map/">Map</a><a href="https://atlas.example/board/">Board</a>', self.html)
        self.assertIn('<footer class="site">', self.html)
        self.assertNotIn("<style>", self.html)
        self.assertIn('<link rel="canonical" href="https://atlas.example/board/">', self.html)

    def test_rows_link_the_seller_page_and_escape_the_registry_text(self):
        self.assertIn('<a href="https://atlas.example/s/a.example/">a.example</a>', self.html)
        self.assertIn("Search the web, &lt;b&gt;fast&lt;/b&gt; &amp; cheap", self.html)
        self.assertNotIn("<b>fast</b>", self.html)

    def test_the_mark_and_the_numbers_are_on_the_page(self):
        # once in the key, then s3 and s2 in the top list and once each in their category's list
        self.assertEqual(self.html.count('<span class="pill one-payer">one payer is most of it</span>'), 1 + 2 + 2)
        # b.example's row: price, customers, returning, top payer, the 7 days, the shape
        self.assertIn('<td>$0.001–$0.005</td><td class="n">5</td><td class="n">0</td><td class="n">71.4%</td>'
                      '<td class="days">10.00 3.00 1.00 0.00 0.00 0.00 0.00</td><td class="shape">spike</td>', self.html)

    def test_a_section_per_category(self):
        for c in self.json["categories"]:
            self.assertIn('id="%s"' % board.slug(c), self.html)

    def test_json_has_the_same_numbers_with_absolute_links(self):
        self.assertEqual(self.json["kind"], "x402-board")
        rows = {r["host"]: r for r in self.json["sellers"]}
        self.assertEqual(rows["a.example"]["page"], "https://atlas.example/s/a.example/")
        self.assertEqual((rows["a.example"]["customers"], rows["a.example"]["returning"]), (3, 2))
        self.assertEqual(self.json["page"], "https://atlas.example/board/")
        self.assertEqual(self.json["json"], "https://atlas.example/board/board.json")

    def test_never_the_word_and_never_who_holds_a_wallet(self):
        for text in (self.html, self.raw):
            self.assertNotIn("ver" + "if", text.lower())
            for w in ("belongs to", "owned by", "is operated by", "identity"):
                self.assertNotIn(w, text.lower())

    def test_same_files_same_bytes(self):
        out = tempfile.mkdtemp()
        try:
            board.build(out, self.dir, SNAPSHOT, "https://atlas.example", "2026-01-07", n=3)
            self.assertEqual(open(os.path.join(out, "board", "board.json")).read(), self.raw)
            self.assertEqual(open(os.path.join(out, "board", "index.html")).read(), self.html)
        finally:
            shutil.rmtree(out)


class Gaps(unittest.TestCase):
    def test_no_flows_no_board_nothing_written(self):
        out, empty = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            self.assertIsNone(board.build(out, empty, SNAPSHOT))
            self.assertIsNone(board.build(out, os.path.join(empty, "absent"), SNAPSHOT))
            self.assertFalse(os.path.exists(os.path.join(out, "board")))
        finally:
            shutil.rmtree(out)
            shutil.rmtree(empty)

    def test_a_missing_day_is_named_and_has_no_shape(self):
        d = write_week(tempfile.mkdtemp(), days=[1, 2, 3, 4, 6, 7])
        try:
            b = board.compute(d, SNAPSHOT)
            self.assertEqual(b["problems"], ["no flows file for 2026-01-05"])
            r = next(r for r in b["sellers"] if r["host"] == "a.example")
            self.assertEqual(r["daily_usdc"], [3.0, 1.0, 1.0, 1.0, None, 0.0, 0.0])
            self.assertIsNone(r["shape"])
        finally:
            shutil.rmtree(d)

    def test_only_the_newest_seven_days(self):
        d = write_week(tempfile.mkdtemp())
        try:
            with open(os.path.join(d, "flows-2025-12-31.json"), "w") as f:
                json.dump({"date": "2025-12-31", "edges": [e("0xx", "0xs3", 99)], "sellers": HOSTS}, f)
            b = board.compute(d, SNAPSHOT)
            self.assertEqual(b["window"]["from"], "2026-01-01")
            self.assertEqual(next(r for r in b["sellers"] if r["host"] == "c.example")["customers"], 1)
        finally:
            shutil.rmtree(d)

    def test_without_a_snapshot_rows_still_rank(self):
        d = write_week(tempfile.mkdtemp())
        try:
            b = board.compute(d, {})
            self.assertEqual([r["host"] for r in b["sellers"]][-3:], ["filler18.example", "c.example", "b.example"])
            self.assertIsNone(b["sellers"][0]["price"])
        finally:
            shutil.rmtree(d)

    def test_the_site_build_without_flows_writes_a_placeholder_only(self):
        import seller_pages
        out = tempfile.mkdtemp()
        try:
            self.assertFalse(seller_pages.build_board(out, None, SNAPSHOT, "2026-01-07"))
            self.assertFalse(seller_pages.build_board(out, tempfile.mkdtemp(), SNAPSHOT, "2026-01-07"))
            # no ranking, but the nav's /board/ link still lands on a page
            self.assertFalse(os.path.exists(os.path.join(out, "board", "board.json")))
            with open(os.path.join(out, "board", "index.html")) as f:
                self.assertIn("no week of payments to rank", f.read())
            d = write_week(tempfile.mkdtemp())
            self.assertTrue(seller_pages.build_board(out, d, SNAPSHOT, "2026-01-07", n=3))
            self.assertTrue(os.path.exists(os.path.join(out, "board", "board.json")))
            with open(os.path.join(out, "board", "index.html")) as f:
                self.assertNotIn("no week of payments to rank", f.read())
            # a later empty build leaves the real Board as it was
            self.assertFalse(seller_pages.build_board(out, None, SNAPSHOT, "2026-01-08"))
            with open(os.path.join(out, "board", "index.html")) as f:
                self.assertNotIn("no week of payments to rank", f.read())
            shutil.rmtree(d)
        finally:
            shutil.rmtree(out)


class FreeTier(unittest.TestCase):
    def test_top_cuts_the_page_and_the_json_alike(self):
        import json as _j
        d, out = write_week(tempfile.mkdtemp()), tempfile.mkdtemp()
        try:
            full = board.compute(d, SNAPSHOT)
            n_all = len(full["sellers"])
            self.assertGreater(n_all, 3)
            b = board.build(out, d, SNAPSHOT, "https://example.test", "2026-01-07", top=3)
            self.assertEqual(len(b["sellers"]), 3)
            self.assertEqual(b["ranked_total"], n_all)
            with open(os.path.join(out, "board", "board.json")) as f:
                j = _j.load(f)
            self.assertEqual([r["wallet"] for r in j["sellers"]], [r["wallet"] for r in full["sellers"][:3]])
            self.assertIn("locked", j)
            with open(os.path.join(out, "board", "index.html")) as f:
                page = f.read()
            self.assertIn("%d more ranked sellers" % (n_all - 3), page)
            for r in full["sellers"][3:]:      # a cut seller is in neither file
                self.assertNotIn(r["wallet"], page)
                self.assertNotIn(r["wallet"], _j.dumps(j))
        finally:
            shutil.rmtree(d)
            shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()
