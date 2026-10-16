#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit abfcd4a). Edit it there, not here.
"""rails_page_test.py — /rails/: the rails file is checked, the page is built from it, and the Atlas's
own numbers come from the flow files with the brief's rules. No network.

    python3 rails_page_test.py

The flow files are brief_test's fixture (four Base days, two Solana days), so every number checked
here is already worked out by hand in brief_test.py.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import atlas_style  # noqa: E402
import brief_test  # noqa: E402
import rails_page as rp  # noqa: E402

STEM = "ver" + "if"                       # the word this shop never says, built so this file never says it either
SITE = "https://example.test/atlas"


def rail(i, settles="chain", we_see="daily", **kw):
    r = {"id": "r%d" % i, "name": "Rail %d" % i, "by": "Runner %d" % i, "kind": "a kind", "who": "someone", "moves": "USDC",
         "settles": settles, "we_see": we_see,
         "claim": {"text": "a figure", "date": "2026-10-01", "source": "https://example.test/%d" % i, "self_reported": True},
         "changes": [{"date": "2026-10-15", "text": "On this page from today."}]}
    r.update(kw)
    return r


RAILS = [rail(1), rail(2, "mixed", "no"), rail(3, "off_chain", "no"), rail(4, "chain", "not_yet")]


class Load(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, rails=None, raw=None):
        p = os.path.join(self.d, "rails.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps({"rails": RAILS if rails is None else rails}))
        return p

    def refuses(self, rails=None, raw=None):
        with self.assertRaises(ValueError):
            rp.load(self.write(rails, raw))

    def test_the_real_file_loads_and_fills_every_zone(self):
        rails = rp.load()
        self.assertGreaterEqual(len(rails), 10)
        self.assertEqual({r["settles"] for r in rails}, set(rp.SETTLES))
        for r in rails:
            self.assertTrue(r["claim"]["source"].startswith("https://"), r["id"])

    def test_a_good_file_loads(self):
        self.assertEqual([r["id"] for r in rp.load(self.write())], ["r1", "r2", "r3", "r4"])

    def test_the_word_is_refused_anywhere_in_the_file(self):
        self.refuses([rail(1, kind="a " + STEM.upper() + "ied rail")])
        self.refuses([rail(1, claim={"text": "a list of " + STEM + "ied agents", "date": "2026-10-01",
                                     "source": "https://example.test/", "self_reported": True})])

    def test_a_missing_field_a_twin_or_an_empty_list_is_refused(self):
        r = rail(1)
        del r["who"]
        self.refuses([r])
        self.refuses([rail(1), rail(1)])
        self.refuses([])
        self.refuses(raw='{"rails": "none"}')
        for raw in ("[]", '"rails"', "null", '{"rails": ["a rail"]}', '{"rails": [{"id": "x"}]}'):
            self.refuses(raw=raw)                                   # never an AttributeError that stops the site
        r = rail(1)
        r["claim"] = "a figure"
        self.refuses([r])
        self.refuses([rail(1, changes="today")])
        self.refuses([rail(1, changes=["today"])])

    def test_who_runs_it_is_a_few_words(self):
        self.refuses([rail(1, by="")])
        self.refuses([rail(1, by="x" * 41)])
        self.refuses([rail(1, by=7)])
        self.assertEqual(rp.load(self.write([rail(1, by="Visa")]))[0]["by"], "Visa")

    def test_zones_and_sight_must_be_known(self):
        self.refuses([rail(1, settles="sideways")])
        self.refuses([rail(1, we_see="sometimes")])

    def test_the_atlas_reads_only_a_public_chain(self):
        self.refuses([rail(1, "off_chain", "daily")])
        self.refuses([rail(1, "mixed", "windows")])

    def test_a_claim_needs_an_https_source_a_date_text_and_whose_figure_it_is(self):
        for bad in ({"source": "http://example.test/"}, {"source": ""}, {"date": "15 Oct"}, {"date": "2026"},
                    {"date": "2026-13"}, {"date": "2026-02-30"}, {"date": "2026-00"},     # the shape alone is not a date
                    {"text": ""}, {"self_reported": "yes"}):
            r = rail(1)
            r["claim"] = dict(r["claim"], **bad)
            self.refuses([r])
        r = rail(1)
        r["claim"] = dict(r["claim"], date="2026-02")      # a month alone is enough
        self.assertEqual(len(rp.load(self.write([r]))), 1)

    def test_a_figure_is_short_and_labelled(self):
        def with_figure(**f):
            r = rail(1)
            r["claim"] = dict(r["claim"], **f)
            return [r]
        self.assertEqual(rp.load(self.write(with_figure(figure="$24.24M", figure_label="30 days")))[0]["claim"]["figure"],
                         "$24.24M")
        self.refuses(with_figure(figure="$24.24M"))                                  # no label
        self.refuses(with_figure(figure="", figure_label="x"))
        self.refuses(with_figure(figure="a figure far too long", figure_label="x"))
        self.refuses(with_figure(figure=24, figure_label="x"))

    def test_a_change_needs_a_date_and_a_text(self):
        self.refuses([rail(1, changes=[{"date": "2026-02-31", "text": "x"}])])
        self.refuses([rail(1, changes=[{"date": "", "text": "x"}])])
        self.refuses([rail(1, changes=[{"date": "2026-10-15", "text": ""}])])


class Measured(unittest.TestCase):
    def test_the_newest_seven_days_held(self):
        d = tempfile.mkdtemp()
        try:
            for day in ("2026-01-01", "2026-01-05", "2026-01-12"):
                brief_test.put(os.path.join(d, "flows-%s.json" % day), {"date": day, "edges": [], "sellers": {}})
            brief_test.put(os.path.join(d, "flows-sol-2026-01-20.json"), {"date": "2026-01-20", "edges": []})
            self.assertEqual(rp.window(d), ("2026-01-06", "2026-01-12"))     # Solana files don't move the window
            self.assertEqual(rp.window(d, days=30), ("2026-01-01", "2026-01-12"))
        finally:
            shutil.rmtree(d)
        self.assertIsNone(rp.window(tempfile.gettempdir() + "/no-such-rails-dir"))

    def test_the_brief_numbers(self):
        m = rp.measured(brief_test.FLOWS)
        self.assertEqual((m["from"], m["to"], m["days"]), ("2026-01-01", "2026-01-04", 4))
        self.assertEqual((m["base"]["usdc"], m["base"]["payments"], m["base"]["sellers"]), (118.21, 68, 24))
        self.assertEqual((m["solana"]["usdc"], m["solana"]["payments"], m["solana"]["days"]), (920.5, 121, 2))

    def test_the_range_is_the_days_that_could_be_read(self):
        d = brief_test.fixture()
        try:
            brief_test.put(os.path.join(d, "flows-2026-01-04.json"), "not json")      # the newest day, broken
            brief_test.put(os.path.join(d, "flows-2026-01-02.json"), "not json")      # a day in the middle, broken
            m = rp.measured(d)
            self.assertEqual((m["from"], m["to"], m["days"], m["missing"]), ("2026-01-01", "2026-01-03", 2, ["2026-01-02"]))
            self.assertIn("No file could be read for 2 Jan 2026: not counted.", rp.stats(m, RAILS))
            for day in ("2026-01-01", "2026-01-03"):
                brief_test.put(os.path.join(d, "flows-%s.json" % day), "not json")
            self.assertIsNone(rp.measured(d))                                         # nothing read: no numbers at all
        finally:
            shutil.rmtree(d)

    def test_no_files_no_numbers(self):
        self.assertIsNone(rp.measured(None))
        d = tempfile.mkdtemp()
        try:
            self.assertIsNone(rp.measured(d))
        finally:
            shutil.rmtree(d)


class Page(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.data = os.path.join(self.out, "rails.json")

    def tearDown(self):
        shutil.rmtree(self.out)

    def build(self, rails=RAILS, flows=None):
        with open(self.data, "w", encoding="utf-8") as f:
            json.dump({"rails": rails}, f)
        r = rp.build(os.path.join(self.out, "_site"), self.data, flows, SITE)
        with open(os.path.join(self.out, "_site", "rails", "index.html"), encoding="utf-8") as f:
            return r, f.read()

    def test_every_rail_in_its_group_with_what_the_atlas_sees(self):
        r, page = self.build()
        self.assertEqual(r["rails"], 4)
        self.assertIn("<h1>Where AI agents pay</h1>", page)
        self.assertIn('<link rel="stylesheet" href="%s/atlas.css">' % SITE, page)
        self.assertIn('<link rel="canonical" href="%s/rails/">' % SITE, page)
        self.assertIn("The numbers are never for sale.", page)            # the full footer unless told it is the free tier
        self.assertNotIn("<style>", page)                                  # its look is in the shared stylesheet
        self.assertIn(".rails .rtab{", atlas_style.CSS)
        groups = page.split('<table class="rtab">')[1].split("</table>")[0].split('<tr class="grp">')[1:]
        chain, mixed, off = groups
        self.assertIn('<th colspan="5">On a public chain <span>2</span></th>', chain)
        self.assertIn('<td><b>Rail 1</b><span>Runner 1</span></td>', chain)
        self.assertIn('<span class="rst see-yes"><i></i>Read daily</span>', chain)
        self.assertIn('<span class="rst see-not-yet"><i></i>Public, not read</span>', chain)
        self.assertIn("Both <span>1</span>", mixed)
        self.assertIn("Rail 2", mixed)
        self.assertIn("Inside card networks and companies <span>1</span>", off)
        self.assertIn('<span class="rst see-no"><i></i>Not visible</span>', off)
        self.assertNotIn("Rail 3", chain + mixed)

    def test_the_bar_counts_what_can_be_seen(self):
        _, page = self.build()
        self.assertIn('aria-label="1 rails read by the Atlas, 1 public but not read, 2 not visible"', page)
        bar = page.split('<div class="rbar"')[1].split("</div>")[0]
        self.assertEqual(re.findall(r'<span class="([a-z-]+)"', bar), ["see-yes", "see-not-yet", "see-no", "see-no"])
        self.assertIn("Read by the Atlas <b>1</b>", page)
        self.assertIn("<b>1<small>/4</small></b>", page)                    # rails the Atlas reads, in the strip

    def test_a_row_says_whose_figure_it_is_when_and_where_from(self):
        r1 = rail(1)
        r1["claim"] = dict(r1["claim"], figure="$24.24M", figure_label="in 30 days")
        r2 = rail(2, "mixed", "no")
        r2["claim"] = dict(r2["claim"], self_reported=False, date="2026-02")
        _, page = self.build([r1, r2])
        rows = page.split('<table class="rtab">')[1].split("</table>")[0].split("<tr><td>")[1:]
        self.assertIn('<td class="num rfig"><b>$24.24M</b><span>in 30 days</span></td>', rows[0])
        self.assertIn('<td class="rd"><a href="https://example.test/1" rel="nofollow noopener">1 Oct 2026</a>'
                      '<span>self-reported</span></td>', rows[0])
        self.assertIn("<span>third party</span>", rows[1])                     # a figure someone else counted
        self.assertIn(">Feb 2026</a>", rows[1])
        self.assertIn('<b class="rnone">&mdash;</b><span>no figures published</span>', rows[1])

    def test_without_flow_files_it_says_the_counts_come_later(self):
        r, page = self.build()
        self.assertIsNone(r["measured"])
        self.assertIn("The Atlas's own counts appear here when the daily files are read.", page)
        self.assertNotIn("payments</dt>", page)
        self.assertIn("<dt>rails the Atlas reads</dt>", page)

    def test_with_flow_files_the_counts_and_the_one_big_payment(self):
        r, page = self.build(flows=brief_test.FLOWS)
        st = page.split('<dl class="rkpi">')[1].split('<h2 class="rhead">')[0]
        self.assertIn('<dt>x402 on Base, 1 to 4 Jan 2026</dt><dd><b class="acc">$118</b></dd>', st)
        self.assertIn("<dt>payments</dt><dd><b>68</b></dd>", st)
        self.assertIn("<dt>sellers paid</dt><dd><b>24</b></dd>", st)
        self.assertIn("<dt>x402 on Solana, 2 days read</dt><dd><b>$920</b></dd>", st)
        self.assertIn("over 4 days. One payment was 50.8% of it; without it, $58.21.", st)
        self.assertIn("On Solana: One payment was 97.8% of it; without it, $20.50.", st)

    def test_a_window_across_months_names_both(self):
        self.assertEqual(rp._span({"from": "2026-09-28", "to": "2026-10-04"}), "28 Sep to 4 Oct 2026")
        self.assertEqual(rp._span({"from": "2026-10-08", "to": "2026-10-14"}), "8 to 14 Oct 2026")
        self.assertEqual(rp._span({"from": "2026-10-14", "to": "2026-10-14"}), "14 Oct 2026")

    def test_the_free_tier_gets_the_free_footer(self):
        with open(self.data, "w", encoding="utf-8") as f:
            json.dump({"rails": RAILS}, f)
        rp.build(os.path.join(self.out, "free"), self.data, None, SITE, free=True)
        with open(os.path.join(self.out, "free", "rails", "index.html"), encoding="utf-8") as f:
            self.assertNotIn("never for sale", f.read())

    def test_the_changes_stay_off_the_page(self):
        _, page = self.build([rail(1, changes=[{"date": "2026-10-08", "text": "a private note"}])])
        self.assertNotIn("a private note", page)
        self.assertNotIn(">Changes<", page)

    def test_text_never_becomes_markup(self):
        evil = rail(1, name="<b>bold</b>", kind="<script>alert(1)</script>", by="<i>x")
        evil["claim"] = dict(evil["claim"], source='https://example.test/"><script>x</script>')
        _, page = self.build([evil])
        self.assertNotIn("<b>bold</b>", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn('"><script>x</script>', page)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", page)
        self.assertNotIn("<i>x", page)

    def test_the_real_page_never_uses_the_word(self):
        out = os.path.join(self.out, "real")
        rp.build(out, flows_dir=brief_test.FLOWS, site=SITE)
        with open(os.path.join(out, "rails", "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertNotIn(STEM, page.lower())
        for r in rp.load():
            self.assertIn(rp.esc(r["name"]), page)

    def test_the_page_refuses_the_word_even_if_the_file_slipped_it_past(self):
        with self.assertRaises(ValueError):
            orig = rp.load
            try:
                rp.load = lambda path=None: [rail(1, name="un" + STEM + "ied")]
                rp.build(os.path.join(self.out, "x"), self.data, None, SITE)
            finally:
                rp.load = orig


class Nav(unittest.TestCase):
    def test_rails_is_in_the_explore_menu(self):
        panel = atlas_style.HEAD.split("<summary>Explore</summary>")[1].split("</details>")[0]
        self.assertIn('<a href="%(root)s/where/">Where</a><a href="%(root)s/rails/">Rails</a>', panel)


if __name__ == "__main__":
    unittest.main()
