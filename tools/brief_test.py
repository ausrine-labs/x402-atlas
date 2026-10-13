#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 83713b3). Edit it there, not here.
"""brief_test.py — the weekly brief, built from a window small enough to count by hand.

Four Base days (2026-01-01 to 2026-01-04: halves 1-2 and 3-4) and two Solana days. Every
expected number below is worked out in the comments beside the fixture. No network.

    python3 brief_test.py
"""
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import brief  # noqa: E402

STEM = "ver" + "if"                       # the word this shop never says, built so this file never says it either
OWNER_WORDS = ("belongs to", "owned by", "operated by", "is run by", "runs the wallet", "identity", "who is behind")

A, B, C, D, E = ("0x" + x * 20 for x in ("a1", "b2", "c3", "d4", "e5"))
R = "0x" + "f6" * 20                      # the robot: pays 21 sellers
U = "0x" + "99" * 20                      # not in any sellers map
S1, S2, S3, S4 = ("0x" + x * 20 for x in ("11", "22", "33", "44"))
T = ["0x%040x" % (0x100 + i) for i in range(20)]
DAYS = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
STEM_HOST = "c" + STEM + "y.example"      # a registry host holding the word: shown as "….example"

P1 = "SoLPayee1111111111111111111111111111111111"   # base58 is case-sensitive: never lowercased
P2 = "PaYee2222222222222222222222222222222222222"
X1, X2, X3, X4 = ("Xa%d" % i + "z" * 40 for i in range(1, 5))


def x(f, t, n, u, nx=None, ux=None):
    return {"from": f, "to": t, "n": n, "usdc": u, "n_x402": n if nx is None else nx, "usdc_x402": u if ux is None else ux}


SELLERS = dict({S1: ["one.example", "shared.example"], S2: ["two.example", "shared.example"], S3: [STEM_HOST],
                S4: ["four.example"]}, **{t: ["t%02d.example" % i] for i, t in enumerate(T)})

# Base. Totals: day 1 $65 (15 payments), day 2 $36 (16), day 3 $14 (13), day 4 $3.21 (24): $118.21, 68 payments.
#   S1 $95 = A 60+30+1, B 3+1   (A $91: 95.8%; largest edge A day 1 $60: 63.2% of S1, 50.8% of all)
#   S2 $18 = B 5+5, C 5, D 1, E 2   (B $10: 55.6%)
#   S3 $5 = C 1, A 3, D 1   (A $3: 60%, one edge)
#   S4 and T00..T19 $0.01 each, all from R (the robot: 21 sellers)
BASE = {
    "2026-01-01": [x(A, S1, 10, 60.0), x(B, S2, 5, 5.0)],
    "2026-01-02": [x(A, S1, 10, 30.0), x(C, S3, 1, 1.0), x(B, S2, 5, 5.0),
                   x(A, U, 1, 100.0)],                                   # to a wallet no sellers map lists: left out
    "2026-01-03": [x(B, S1, 2, 3.0), x(C, S2, 5, 5.0), x(D, S2, 1, 1.0), x(E, S2, 2, 2.0), x(A, S3, 3, 3.0)],
    "2026-01-04": [x(R, t, 1, 0.01) for t in T] + [x(R, S4, 1, 0.01), x(D, S3, 1, 1.0),
                                                    x("0x" + "A1" * 20, S1, 1, 1.0),    # A, spelled in capitals
                                                    x(B, S1, 1, 1.0),
                                                    x(D, S4, 3, 3.0, nx=0, ux=0.0)],    # not x402: left out
}
# Solana. Day 3 $910.50 (61 payments), one payment of $900 in it; day 4 $10 (60). P1 is listed, P2 is not.
SOL = {
    "2026-01-03": [x(X1, P1, 1, 900.0), x(X2, P1, 10, 10.0), x(X3, P2, 50, 0.5)],
    "2026-01-04": [x(X2, P1, 10, 4.0), x(X3, P2, 40, 4.0), x(X4, P2, 10, 2.0)],
}


def put(path, obj):
    with open(path, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def fixture(base=BASE, sol=SOL, sellers=SELLERS):
    d = tempfile.mkdtemp()
    for day, edges in base.items():
        put(os.path.join(d, "flows-%s.json" % day), {"date": day, "day": day, "hours": 24, "edges": edges, "sellers": sellers})
    for day, edges in (sol or {}).items():
        put(os.path.join(d, "flows-sol-%s.json" % day),
            {"date": day, "day": day, "chain": "solana", "hours": 24, "edges": edges, "sellers": {P1: ["sol-one.example"]}})
    return d


FLOWS = fixture()
BRIEF = brief.build(FLOWS, DAYS[0], DAYS[-1], "https://atlas.test")
PAGE = brief.page(BRIEF, "https://atlas.test")


class Money(unittest.TestCase):
    def test_the_total_and_who_is_counted(self):
        t = BRIEF["money"]["total"]
        self.assertEqual((t["usdc"], t["payments"], t["sellers_paid"], t["payer_wallets"]), (118.21, 68, 24, 6))
        self.assertEqual(BRIEF["money"]["dates"], {"from": "2026-01-01", "to": "2026-01-04", "days": 4})
        self.assertEqual(BRIEF["method"]["base_left_out"], {"edges_to_unlisted_wallets": 1, "edges_not_in_shape": 0})

    def test_the_top_three_and_each_ones_largest_payer(self):
        m = BRIEF["money"]
        self.assertEqual((m["lead"]["sellers"], m["lead"]["usdc"], m["lead"]["share_pct"]), (3, 118.0, 99.8))
        rows = m["top_sellers"]
        self.assertEqual([r["wallet"] for r in rows[:3]], [S1, S2, S3])
        self.assertEqual([(r["usdc"], r["payments"], r["payers"], r["share_pct"]) for r in rows[:3]],
                         [(95.0, 24, 2, 80.4), (18.0, 18, 4, 15.2), (5.0, 5, 3, 4.2)])
        self.assertEqual([(r["largest_payer"]["wallet"], r["largest_payer"]["usdc"], r["largest_payer"]["share_pct"])
                          for r in rows[:3]], [(A, 91.0, 95.8), (B, 10.0, 55.6), (A, 3.0, 60.0)])
        self.assertEqual(rows[0]["largest_payer"]["payments"], 21)            # the capitalised A is the same wallet
        self.assertEqual(rows[0]["days_paid"], 4)
        # ties at $0.01 go by wallet: the twenty T wallets sort before S4
        self.assertEqual([r["wallet"] for r in rows[3:]], T[:7])
        self.assertEqual(len(rows), brief.TOP)
        self.assertEqual(m["top_sellers_over_half_one_payer"], 10)

    def test_a_seller_is_named_by_its_most_particular_host(self):
        r = BRIEF["money"]["top_sellers"][0]
        self.assertEqual((r["hosts"], r["hosts_total"]), (["one.example", "shared.example"], 2))

    def test_a_host_holding_the_word_is_shown_without_it_and_the_wallet_stays_exact(self):
        r = BRIEF["money"]["top_sellers"][2]
        self.assertEqual((r["wallet"], r["hosts"]), (S3, ["….example"]))
        self.assertIn("….example", PAGE)


class LargestEdge(unittest.TestCase):
    def test_every_total_carries_its_largest_edge(self):
        le = BRIEF["money"]["total"]["largest_edge"]
        self.assertEqual(le, {"date": "2026-01-01", "from": A, "to": S1, "usdc": 60.0, "payments": 10, "share_pct": 50.8,
                              "over_half": True, "usdc_without_it": 58.21})
        self.assertEqual(BRIEF["money"]["lead"]["largest_edge"]["share_pct"], 50.8)        # 60 of 118
        self.assertFalse(BRIEF["money"]["top_sellers"][1]["largest_edge"]["over_half"])    # 5 of 18
        self.assertEqual(BRIEF["robots"]["largest_edge"]["share_pct"], 4.8)                # 0.01 of 0.21

    def test_exactly_half_is_not_more_than_half(self):
        first = BRIEF["growth"]["many_wallets"][0]["first"]                               # S2, days 1-2: $5 and $5
        self.assertEqual((first["usdc"], first["largest_edge"]["share_pct"], first["largest_edge"]["over_half"]),
                         (10.0, 50.0, False))

    def test_the_totals_over_half_are_listed_for_an_agent(self):
        where = [x["where"] for x in BRIEF["over_half_totals"]]
        for w in ("money.total", "money.lead", "money.top_sellers[0]", "money.top_sellers[2]", "growth.market.first",
                  "growth.many_wallets[0].second", "growth.one_wallet[0].first", "solana.days[2026-01-03]",
                  "solana.total", "solana.top_payees[0]", "solana.top_payees[1]"):
            self.assertIn(w, where)
        for w in ("money.top_sellers[1]", "robots", "growth.market.second", "growth.many_wallets[0].first",
                  "solana.days[2026-01-04]"):
            self.assertNotIn(w, where)

    def test_the_page_says_so_beside_the_total(self):
        first_tile = re.search(r'<div class="tile"><b>\$118</b>(.*?)</div>', PAGE, re.S).group(1)
        self.assertIn("one edge", first_tile)
        self.assertIn("50.8% of this total", first_tile)
        self.assertIn("Without it, $58.21.", first_tile)
        line = re.search(r"<p>\$118\.21 in 68 payments reached 24 sellers.*?</p>", PAGE, re.S).group(0)
        self.assertIn("one edge", line)
        robots = re.search(r"<h3[^>]*>Robot wallets</h3>\s*<p>(.*?)</p>", PAGE, re.S).group(1)
        self.assertNotIn("one edge", robots)                                           # 4.8%: nothing to say

    def test_a_share_short_of_the_whole_never_reads_as_all(self):
        self.assertEqual(brief.pct(99999, 100000), 99.9)
        self.assertEqual(brief.pct(5, 5), 100.0)
        self.assertEqual(brief.pct(1, 3), 33.3)
        self.assertIsNone(brief.pct(1, 0))

    def test_a_part_above_nothing_never_reads_as_none(self):
        self.assertEqual(brief.pct(1, 11821), 0.0085)                 # $0.01 of $118.21
        self.assertEqual(brief.pct(0, 5), 0.0)
        self.assertEqual(brief.pct_words(0.0085), "under 0.1%")
        self.assertEqual(BRIEF["money"]["top_sellers"][3]["share_pct"], 0.0085)
        self.assertNotIn('<td class="n">0%</td>', PAGE)


class Concentration(unittest.TestCase):
    def test_over_the_window(self):
        c = BRIEF["concentration"]
        self.assertEqual((c["sellers_paid"], c["one_payer"], c["one_payer_pct"], c["one_payer_is_robot"], c["median_payers"]),
                         (24, 21, 87.5, 21, 1))
        self.assertEqual([b["sellers"] for b in c["payers_buckets"]], [21, 3, 0, 0])

    def test_on_the_last_day(self):
        ld = BRIEF["concentration"]["last_day"]
        self.assertEqual((ld["date"], ld["sellers_paid"], ld["one_payer"], ld["median_payers"]), ("2026-01-04", 23, 22, 1))

    def test_the_median_of_an_even_count(self):
        b = brief.build(fixture({"2026-01-01": [x(A, S1, 1, 1.0), x(A, S2, 1, 1.0), x(B, S2, 1, 1.0),
                                                x(C, S2, 1, 1.0), x(A, S3, 1, 1.0), x(B, S3, 1, 1.0)]}, sol=None),
                        "2026-01-01", "2026-01-01")
        self.assertEqual(b["concentration"]["median_payers"], 2)                     # 1, 2, 3
        b = brief.build(fixture({"2026-01-01": [x(A, S1, 1, 1.0), x(A, S2, 1, 1.0), x(B, S2, 1, 1.0)]}, sol=None),
                        "2026-01-01", "2026-01-01")
        self.assertEqual(b["concentration"]["median_payers"], 1.5)                   # 1, 2


class Robots(unittest.TestCase):
    def test_the_robot_and_what_it_sent(self):
        r = BRIEF["robots"]
        self.assertEqual((r["min_sellers"], r["wallets"], r["usdc"], r["payments"], r["share_pct"], r["sellers_reached"],
                          r["sellers_reached_pct"]), (20, 1, 0.21, 21, 0.2, 21, 87.5))
        self.assertEqual(r["top"], [{"wallet": R, "sellers_paid": 21, "usdc": 0.21, "payments": 21}])

    def test_twenty_sellers_is_a_robot_and_nineteen_is_not(self):
        for n, robots in ((19, 0), (20, 1)):
            ss = {t: ["t.example"] for t in T}
            b = brief.build(fixture({"2026-01-01": [x(R, t, 1, 0.01) for t in T[:n]]}, sol=None, sellers=ss),
                            "2026-01-01", "2026-01-01")
            self.assertEqual(b["robots"]["wallets"], robots, n)


class Growth(unittest.TestCase):
    def test_the_halves_and_money_a_day(self):
        g = BRIEF["growth"]
        self.assertTrue(g["available"])
        self.assertEqual(g["halves"], {"first": DAYS[:2], "second": DAYS[2:]})
        mk = g["market"]
        self.assertEqual((mk["first"]["usdc"], mk["first"]["payments"], mk["first"]["usdc_per_day"], mk["first"]["payments_per_day"]),
                         (101.0, 31, 50.5, 15.5))
        self.assertEqual((mk["second"]["usdc"], mk["second"]["payments"], mk["second"]["usdc_per_day"], mk["second"]["payments_per_day"]),
                         (17.21, 37, 8.605, 18.5))
        self.assertEqual((mk["usdc_per_day_change_pct"], mk["payments_per_day_change_pct"]), (-83.0, 19.4))

    def test_many_wallets_one_wallet_and_the_robot_wave(self):
        g = BRIEF["growth"]
        self.assertEqual((g["grew"], g["many_wallets_count"], g["one_wallet_count"], g["robot_wave_count"]), (3, 1, 2, 21))
        m = g["many_wallets"][0]                                   # S2: B, then C D E
        self.assertEqual((m["wallet"], m["gain"], m["new_wallets"], m["first"]["payers"], m["second"]["payers"]), (S2, 2, 3, 1, 3))
        self.assertEqual((m["first"]["usdc"], m["second"]["usdc"]), (10.0, 8.0))
        lp = m["second"]["largest_payer"]
        self.assertEqual((lp["wallet"], lp["usdc"], lp["share_pct"], lp["over_half"]), (C, 5.0, 62.5, True))
        self.assertEqual(g["many_wallets_money_mostly_one_wallet"], 1)
        one = g["one_wallet"]                                      # S1 ($5 in the second half) before S3 ($4)
        self.assertEqual([(o["wallet"], o["gain"], o["first"]["payers"], o["second"]["payers"], o["second"]["usdc"]) for o in one],
                         [(S1, 1, 1, 2, 5.0), (S3, 1, 1, 2, 4.0)])
        self.assertEqual(one[1]["new_wallets"], 2)                 # C left, A and D came

    def test_an_odd_window_leaves_its_middle_day_out_of_both_halves(self):
        b = brief.build(fixture({d: BASE[d] for d in DAYS[:3]}, sol=None), DAYS[0], DAYS[2])
        self.assertEqual(b["growth"]["halves"], {"first": [DAYS[0]], "second": [DAYS[2]]})

    def test_one_day_has_no_halves(self):
        b = brief.build(fixture({DAYS[0]: BASE[DAYS[0]]}, sol=None), DAYS[0], DAYS[0])
        self.assertFalse(b["growth"]["available"])
        self.assertIn("needs 2 or more days", brief.page(b))


class Solana(unittest.TestCase):
    def test_days_and_totals(self):
        s = BRIEF["solana"]
        self.assertEqual(s["dates"], {"from": "2026-01-03", "to": "2026-01-04", "days": 2})
        self.assertEqual([(d["date"], d["usdc"], d["payments"], d["payers"], d["payees"]) for d in s["days"]],
                         [("2026-01-03", 910.5, 61, 3, 2), ("2026-01-04", 10.0, 60, 3, 2)])
        d3, d4 = (d["largest_edge"] for d in s["days"])
        self.assertEqual((d3["from"], d3["usdc"], d3["payments"], d3["share_pct"], d3["over_half"], d3["usdc_without_it"]),
                         (X1, 900.0, 1, 98.8, True, 10.5))
        self.assertEqual((d4["from"], d4["to"], d4["share_pct"], d4["over_half"]), (X3, P2, 40.0, False))   # a tie: more payments wins
        t = s["total"]
        self.assertEqual((t["usdc"], t["payments"], t["payers"], t["payees"], t["largest_edge"]["share_pct"]), (920.5, 121, 4, 2, 97.8))

    def test_top_payees_keep_their_case_and_say_whether_listed(self):
        p1, p2 = BRIEF["solana"]["top_payees"]
        self.assertEqual((p1["wallet"], p1["listed"], p1["hosts"], p1["usdc"], p1["payments"], p1["payers"], p1["share_pct"]),
                         (P1, True, ["sol-one.example"], 914.0, 21, 2, 99.3))
        self.assertEqual((p1["largest_payer"]["wallet"], p1["largest_payer"]["share_pct"]), (X1, 98.5))
        self.assertEqual((p2["wallet"], p2["listed"], p2["hosts"], p2["usdc"], p2["payments"], p2["share_pct"]),
                         (P2, False, [], 6.5, 100, 0.7))
        self.assertEqual((p2["largest_payer"]["wallet"], p2["largest_payer"]["usdc"], p2["largest_payer"]["share_pct"]), (X3, 4.5, 69.2))
        self.assertIn("SoLPay…1111", PAGE)

    def test_no_solana_files_no_solana_part(self):
        b = brief.build(fixture(sol=None), DAYS[0], DAYS[-1])
        self.assertIsNone(b["solana"])
        self.assertEqual(b["chains"], ["Base"])
        self.assertIn("No Solana file for these days.", brief.page(b))
        self.assertFalse([m for m in b["what_it_means"] if m["rule"].startswith("solana")])


class WhatItMeans(unittest.TestCase):
    def test_fixed_rules_from_the_numbers(self):
        rules = [m["rule"] for m in BRIEF["what_it_means"]]
        self.assertEqual(rules, ["money_in_few_hands", "top_seller_payer", "one_payer_sellers", "growth_wallets", "pace", "robots",
                                 "one_edge_totals", "solana_one_edge", "solana_total"])
        says = {m["rule"]: m["says"] for m in BRIEF["what_it_means"]}
        self.assertEqual(says["money_in_few_hands"], "Three sellers took 99.8% of the money. Most of any total here is theirs.")
        self.assertEqual(says["top_seller_payer"], "The biggest seller, one.example, took 95.8% of its $95.00 from one wallet. Its "
                                                   "income rests on one payer. 10 of the top 10 sellers took more than half their "
                                                   "money from one wallet.")
        self.assertEqual(says["one_payer_sellers"], "Most sellers have one paying wallet: on 4 Jan 2026, 22 of the 23 sellers paid "
                                                    "had just one.")
        self.assertTrue(says["growth_wallets"].startswith("From 1–2 Jan 2026 to 3–4 Jan 2026, 1 seller gained two or more paying "
                                                          "wallets and 2 gained exactly one; 21 more grew only by robot wallets."))
        self.assertEqual(says["pace"], "Money a day on Base went from $50.50 (1–2 Jan 2026) to $8.61 (3–4 Jan 2026): −83%.")
        self.assertIn("1 robot wallet (each paid 20 or more sellers) sent 0.2% of the money and paid 21 of the 24 sellers.",
                      says["robots"])
        self.assertIn("all x402 money on Base", says["one_edge_totals"])
        self.assertEqual(says["solana_one_edge"], "On Solana, one edge ($900.00 in 1 payment) was 98.8% of 3 Jan 2026's $910.50. "
                                                  "Without it, $10.50.")
        for m in BRIEF["what_it_means"]:
            self.assertIsInstance(m["numbers"], dict)

    def test_the_spread_case_says_so(self):
        b = brief.build(fixture({"2026-01-01": [x(A, t, 1, 1.0) for t in T[:6]]}, sol=None,
                                sellers={t: ["t.example"] for t in T}), "2026-01-01", "2026-01-01")
        says = {m["rule"]: m["says"] for m in b["what_it_means"]}
        self.assertEqual(says["money_in_few_hands"], "The top three sellers took 50% of the money; the rest is spread wider.")

    def test_a_quiet_window(self):
        b = brief.build(fixture({"2026-01-01": [x(A, U, 1, 1.0)]}, sol=None), "2026-01-01", "2026-01-01")
        self.assertEqual([m["rule"] for m in b["what_it_means"]], ["quiet"])
        brief.page(b)                                              # and the page still builds


class SparseWindows(unittest.TestCase):
    def test_quiet_on_base_still_says_what_happened_on_solana(self):
        b = brief.build(fixture({"2026-01-03": [x(A, U, 1, 1.0)]}, sol={"2026-01-03": SOL["2026-01-03"]}),
                        "2026-01-03", "2026-01-03")
        rules = [m["rule"] for m in b["what_it_means"]]
        self.assertEqual(rules[0], "quiet")
        self.assertIn("solana_total", rules)
        self.assertIn("solana_one_edge", rules)
        self.assertNotIn("Three of them took", brief.page(b))

    def test_a_payee_listed_with_no_host_is_still_listed(self):
        d = fixture({"2026-01-03": [x(A, T[0], 1, 1.0)]}, sol=None)
        put(os.path.join(d, "flows-sol-2026-01-03.json"),
            {"date": "2026-01-03", "day": "2026-01-03", "chain": "solana", "hours": 24,
             "edges": [x(X1, P1, 1, 5.0), x(X2, P2, 1, 4.0)], "sellers": {P1: [], P2: ["named.example"]}})
        b = brief.build(d, "2026-01-03", "2026-01-03")
        listed = {p["wallet"]: p["listed"] for p in b["solana"]["top_payees"]}
        self.assertEqual(listed, {P1: True, P2: True})

    def test_fewer_than_three_sellers_are_not_called_three(self):
        one = brief.build(fixture({"2026-01-01": [x(A, T[0], 1, 1.0)]}, sol=None, sellers={T[0]: ["t.example"]}),
                          "2026-01-01", "2026-01-01")
        page = brief.page(one)
        self.assertEqual(one["money"]["lead"]["sellers"], 1)
        self.assertNotIn("Three", page.split("<h1>")[1].split("</p>")[0])
        self.assertNotIn("Three of them", page)
        says = {m["rule"]: m["says"] for m in one["what_it_means"]}
        self.assertTrue(says["money_in_few_hands"].startswith("One seller took"), says["money_in_few_hands"])
        two = brief.build(fixture({"2026-01-01": [x(A, T[0], 1, 1.0), x(A, T[1], 1, 1.0)]}, sol=None,
                                  sellers={T[0]: ["t.example"], T[1]: ["u.example"]}), "2026-01-01", "2026-01-01")
        self.assertEqual(two["money"]["lead"]["sellers"], 2)
        self.assertNotIn("Three of them", brief.page(two))


class TheFiles(unittest.TestCase):
    def test_method_caveats_and_files_read(self):
        me = BRIEF["method"]
        self.assertEqual(me["model_calls"], 0)
        self.assertEqual([f["name"] for f in me["files"]], ["flows-2026-01-01.json", "flows-2026-01-02.json", "flows-2026-01-03.json",
                                                            "flows-sol-2026-01-03.json", "flows-2026-01-04.json",
                                                            "flows-sol-2026-01-04.json"])
        self.assertTrue(all(re.match(r"^[0-9a-f]{64}$", f["sha256"]) for f in me["files"]))
        self.assertIn("20 or more different sellers", me["robot"])
        cav = " ".join(BRIEF["caveats"])
        for w in ("A wallet is not a person", "x402 only", "Base unless marked Solana"):
            self.assertIn(w, cav)
        self.assertEqual((BRIEF["kind"], BRIEF["version"]), ("x402-market-brief", 1))
        self.assertEqual(BRIEF["page"], "https://atlas.test/brief/2026-01-01-to-2026-01-04/")
        self.assertEqual(BRIEF["json"], "https://atlas.test/brief/2026-01-01-to-2026-01-04/brief.json")

    def test_missing_and_bad_days_are_named(self):
        d = fixture({DAYS[0]: BASE[DAYS[0]], DAYS[2]: BASE[DAYS[2]]}, sol=None)
        put(os.path.join(d, "flows-2026-01-04.json"), "{not json")
        put(os.path.join(d, "flows-2026-01-02.json"), {"date": "2026-01-09", "edges": [], "sellers": {}})
        b = brief.build(d, DAYS[0], DAYS[-1])
        self.assertEqual(b["window"]["days"], [DAYS[0], DAYS[2]])
        self.assertEqual(b["window"]["days_missing"], [DAYS[1], DAYS[3]])
        self.assertEqual(len(b["problems"]), 2)
        self.assertIn("2026-01-02, 2026-01-04", " ".join(b["caveats"]))

    def test_a_solana_name_on_a_base_file_is_refused(self):
        d = fixture({DAYS[0]: BASE[DAYS[0]]}, sol=None)
        put(os.path.join(d, "flows-sol-%s.json" % DAYS[0]), {"date": DAYS[0], "chain": "base", "edges": [], "sellers": {}})
        b = brief.build(d, DAYS[0], DAYS[0])
        self.assertIsNone(b["solana"])
        self.assertIn("its name says solana", b["problems"][0])

    def test_the_same_files_give_the_same_bytes(self):
        a = brief.build(FLOWS, DAYS[0], DAYS[-1], "https://atlas.test")
        self.assertEqual(brief.dumps(a), brief.dumps(BRIEF))
        self.assertEqual(brief.page(a, "https://atlas.test"), PAGE)

    def test_the_page_wears_the_atlas_look(self):
        self.assertTrue(PAGE.startswith("<!doctype html>"))
        self.assertIn('<link rel="stylesheet" href="https://atlas.test/atlas.css">', PAGE)
        self.assertIn('<header class="site">', PAGE)
        self.assertIn('<footer class="site">', PAGE)
        self.assertIn('<meta name="color-scheme" content="light">', PAGE)
        self.assertNotRegex(PAGE, r"prefers-color-scheme:\s*dark")
        self.assertIn('<link rel="canonical" href="https://atlas.test/brief/2026-01-01-to-2026-01-04/">', PAGE)
        self.assertIn('<a href="brief.json">brief.json</a>', PAGE)
        self.assertIn("Built from the daily files of 1 to 4 January 2026", PAGE)
        self.assertNotIn("rebuilt when the daily scan runs", PAGE)
        for h in ("1. Where the money went", "2. Concentration", "3. Growth", "4. Solana", "5. What it means", "Method", "Caveats"):
            self.assertIn("<h2>%s</h2>" % h, PAGE)
        self.assertIsNone(re.search(r"x402[\s_]+atlas", PAGE, re.I))

    def test_never_the_word_and_never_who_holds_a_wallet(self):
        for name, text in (("page", PAGE), ("json", brief.dumps(BRIEF))):
            self.assertNotIn(STEM, text.lower(), name)
            for w in OWNER_WORDS:
                self.assertNotIn(w, text.lower(), (name, w))
        for f in ("brief.py", "brief_test.py"):
            self.assertNotIn(STEM, read(os.path.join(HERE, f)).lower(), f)


class Command(unittest.TestCase):
    def run_main(self, *argv):
        out = []
        with mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a))):
            brief.main(list(argv))
        return out

    def test_writes_the_folder_and_latest(self):
        out = tempfile.mkdtemp()
        said = self.run_main("--flows-dir", FLOWS, "--from", DAYS[0], "--to", DAYS[-1], "--out", out, "--site", "https://atlas.test")
        folder = os.path.join(out, "2026-01-01-to-2026-01-04")
        self.assertEqual(read(os.path.join(folder, "brief.json")), brief.dumps(BRIEF))
        self.assertEqual(read(os.path.join(folder, "index.html")), PAGE)
        self.assertEqual(read(os.path.join(out, "latest.json")), brief.dumps(BRIEF))
        self.assertTrue(said[0].startswith("brief 2026-01-01 to 2026-01-04: $118.21 to 24 sellers, top three 99.8%"))

    def test_an_older_brief_never_replaces_a_newer_latest(self):
        out = tempfile.mkdtemp()
        self.run_main("--flows-dir", FLOWS, "--from", DAYS[0], "--to", DAYS[-1], "--out", out)
        self.run_main("--flows-dir", FLOWS, "--from", DAYS[0], "--to", DAYS[1], "--out", out)
        self.assertEqual(json.loads(read(os.path.join(out, "latest.json")))["window"]["to"], DAYS[-1])
        self.assertTrue(os.path.exists(os.path.join(out, "2026-01-01-to-2026-01-02", "brief.json")))

    def test_refusals(self):
        with mock.patch("sys.stderr"):
            for argv in (["--flows-dir", FLOWS, "--from", DAYS[1], "--to", DAYS[0]],
                         ["--flows-dir", FLOWS, "--from", "2026-01-01", "--to", "2026-03-01"],
                         ["--flows-dir", FLOWS, "--from", "Jan 1", "--to", DAYS[0]]):
                with self.assertRaises(SystemExit):
                    brief.main(argv + ["--out", tempfile.mkdtemp()])
        with self.assertRaises(SystemExit) as e:
            brief.main(["--flows-dir", tempfile.mkdtemp(), "--from", DAYS[0], "--to", DAYS[0], "--out", tempfile.mkdtemp()])
        self.assertIn("no Base flows", str(e.exception.code))


@unittest.skipUnless(os.environ.get("BRIEF_REAL_FLOWS"), "set BRIEF_REAL_FLOWS to a folder holding the 3-10 Oct 2026 files")
class TheHandWrittenBrief(unittest.TestCase):
    """The first brief, 3 to 10 Oct 2026, was counted by hand. The public files say the same."""

    def test_3_to_10_october(self):
        b = brief.build(os.environ["BRIEF_REAL_FLOWS"], "2026-10-03", "2026-10-10")
        m = b["money"]
        self.assertEqual(round(m["total"]["usdc"]), 15716)
        self.assertEqual(m["lead"]["share_pct"], 62.0)
        top = m["top_sellers"][0]
        self.assertEqual((round(top["usdc"]), top["largest_payer"]["share_pct"]), (4772, 99.9))
        ld = b["concentration"]["last_day"]
        self.assertEqual((ld["one_payer"], ld["sellers_paid"]), (306, 496))
        self.assertEqual((b["robots"]["wallets"], round(b["robots"]["usdc"])), (25, 628))


if __name__ == "__main__":
    unittest.main()
