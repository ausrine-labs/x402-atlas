#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 54e8506). Edit it there, not here.
"""relationships_test.py — the relationship facts, from small windows written by hand. No network.

    python3 relationships_test.py

Every fact is checked against a window small enough to count on one's fingers, and each
edge case the real window will one day hand us: one day only, an empty folder, a wallet
that pays everyone, a seller with several hosts, a host with several wallets.
"""

import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relationships as rl  # noqa: E402

D = ["2026-01-0%d" % i for i in range(1, 9)]


def w(tag):
    """A wallet address from a short tag: w('s1') -> 0x7331...; distinct tags, distinct wallets."""
    h = tag.encode().hex()
    return "0x" + (h + "0" * 40)[:40]


def day_file(folder, day, pays, sellers, chain=None, extra_edges=()):
    """pays: [(buyer, seller_wallet, n_x402)]; sellers: {wallet: [hosts]} for that day."""
    edges = [{"from": b, "to": s, "n": n, "usdc": n * 0.01, "n_x402": n, "usdc_x402": n * 0.01} for b, s, n in pays]
    edges += list(extra_edges)
    d = {"date": day, "day": day, "hours": 24.0, "edges": edges, "sellers": sellers}
    if chain:
        d["chain"] = chain
    with open(os.path.join(folder, "flows-%s.json" % day), "w") as f:
        json.dump(d, f)


def window(days):
    """days: [(day, pays, sellers)] -> the computed window over a fresh folder."""
    folder = tempfile.mkdtemp()
    for day, pays, sellers in days:
        day_file(folder, day, pays, sellers)
    return rl.window(folder), folder


S, T, U, V = w("s"), w("t"), w("u"), w("v")
MAP = {S: ["s.example"], T: ["t.example"], U: ["u.example"], V: ["v.example"]}


class TheFacts(unittest.TestCase):
    def test_buyers_came_back_and_days(self):
        b1, b2, b3 = w("b1"), w("b2"), w("b3")
        win, _ = window([(D[0], [(b1, S, 2), (b2, S, 1)], MAP),
                         (D[1], [(b1, S, 3), (b3, S, 1)], MAP),
                         (D[2], [(b3, S, 1)], MAP),
                         (D[3], [], MAP)])
        f = win["sellers"][S]
        self.assertEqual(win["dates"], D[:4])
        self.assertEqual(f["buyers"], {"count": 3, "payments": 8, "usdc": 0.08})
        self.assertEqual(f["came_back"], {"buyers": 2, "of": 3, "rate_pct": 66.7})
        self.assertEqual(f["days"], {"window": 4, "paid": 3, "paid_on": D[:3]})
        self.assertEqual(f["hosts"], ["s.example"])
        self.assertEqual(f["notes"], [])

    def test_only_x402_edges_to_that_days_sellers_count(self):
        b1, b2 = w("b1"), w("b2")
        plain = {"from": b2, "to": S, "n": 9, "usdc": 9.0, "n_x402": 0, "usdc_x402": 0.0}     # an ordinary transfer
        win, _ = window([(D[0], [(b1, T, 1)], {S: ["s.example"]}),          # T is not a seller on day one
                         (D[1], [], MAP)])
        self.assertNotIn(T, win["sellers"])
        folder = tempfile.mkdtemp()
        day_file(folder, D[0], [(b1, S, 1)], MAP, extra_edges=[plain])
        f = rl.window(folder)["sellers"][S]
        self.assertEqual((f["buyers"]["count"], f["buyers"]["payments"]), (1, 1))

    def test_loyal_is_days_then_payments_then_wallet_top_five(self):
        pays = {D[0]: [], D[1]: [], D[2]: []}
        for i in range(7):
            b = w("L%d" % i)
            for d in D[:1 + i % 3]:               # 1, 2 or 3 days
                pays[d].append((b, S, 10 - i))
        win, _ = window([(d, pays[d], MAP) for d in D[:3]])
        loyal = win["sellers"][S]["loyal"]
        self.assertEqual(len(loyal), rl.TOP)
        self.assertEqual([(x["days"], x["payments"]) for x in loyal],
                         [(3, 24), (3, 15), (2, 18), (2, 12), (1, 10)])
        self.assertEqual(loyal[0]["wallet"], w("L2"))

    def test_bought_alongside_counts_shared_buyers_and_their_share(self):
        pays = []
        for i in range(4):
            pays.append((w("a%d" % i), S, 1))
        for i in range(3):
            pays.append((w("a%d" % i), T, 1))         # three of S's four buyers also paid T
        pays.append((w("a0"), U, 1))                  # one also paid U
        win, _ = window([(D[0], pays, MAP)])
        along = win["sellers"][S]["bought_alongside"]
        self.assertEqual([(x["wallet"], x["hosts"], x["shared_buyers"], x["share_pct"]) for x in along["sellers"]],
                         [(T, ["t.example"], 3, 75.0), (U, ["u.example"], 1, 25.0)])
        self.assertEqual(along["busy_buyers_left_out"], 0)
        self.assertEqual([x["shared_buyers"] for x in win["sellers"][T]["bought_alongside"]["sellers"]], [3, 1])

    def test_a_buyer_paying_more_than_thirty_sellers_is_left_out_and_counted(self):
        many = {w("m%d" % i): ["m%d.example" % i] for i in range(31)}
        busy, calm, thirty = w("busy"), w("calm"), w("thirty")
        pays = [(busy, s, 1) for s in many] + [(busy, S, 1), (busy, T, 1)]           # 33 sellers: busy
        pays += [(thirty, s, 1) for s in list(many)[:28]] + [(thirty, S, 1), (thirty, T, 1)]   # exactly 30: kept
        pays += [(calm, S, 1), (calm, T, 1)]
        win, _ = window([(D[0], pays, dict(MAP, **many))])
        along = win["sellers"][S]["bought_alongside"]
        self.assertEqual(along["busy_buyers_left_out"], 1)
        self.assertEqual(along["sellers"][0], {"wallet": T, "hosts": ["t.example"], "hosts_total": 1,
                                               "shared_buyers": 2, "share_pct": 66.7})
        self.assertEqual(win["busy_buyers"], 1)
        self.assertEqual(win["sellers"][S]["buyers"]["count"], 3)            # still a buyer; only left out of pairs

    def test_switches_left_for_and_came_from(self):
        b1, b2, b3, b4 = w("b1"), w("b2"), w("b3"), w("b4")
        win, _ = window([(D[0], [(b1, S, 1), (b2, S, 1), (b3, S, 1), (b4, S, 1)], MAP),
                         (D[1], [(b1, S, 1), (b3, T, 1)], MAP),
                         (D[2], [(b1, T, 1), (b2, T, 1), (b3, T, 1), (b4, S, 1)], MAP),
                         (D[3], [(b2, U, 1), (b4, U, 1)], MAP)])
        self.assertEqual(win["halves"], {"first": D[:2], "second": D[2:4]})
        sw = win["sellers"][S]["switches"]
        # b1, b2 left S for T; b2 also for U; b3 had paid T in the first half: not a start; b4 kept paying S
        self.assertEqual([(x["wallet"], x["buyers"]) for x in sw["left_for"]], [(T, 2), (U, 1)])
        self.assertEqual(sw["came_from"], [])
        self.assertEqual([(x["wallet"], x["buyers"]) for x in win["sellers"][T]["switches"]["came_from"]], [(S, 2)])
        self.assertEqual([(x["wallet"], x["buyers"]) for x in win["sellers"][U]["switches"]["came_from"]], [(S, 1)])
        self.assertEqual(win["totals"]["switched_buyers"], 2)

    def test_with_an_odd_window_the_middle_day_is_in_neither_half(self):
        b1, b2 = w("b1"), w("b2")
        win, _ = window([(D[0], [(b1, S, 1), (b2, S, 1)], MAP),
                         (D[1], [], MAP),
                         (D[2], [(b2, T, 1)], MAP),                   # the middle day
                         (D[3], [(b1, T, 1)], MAP),
                         (D[4], [(b2, T, 1)], MAP)])
        self.assertEqual(win["halves"], {"first": D[:2], "second": D[3:5]})
        self.assertEqual([(x["wallet"], x["buyers"]) for x in win["sellers"][S]["switches"]["left_for"]], [(T, 1)])

    def test_busy_wallets_are_left_out_of_switches_too(self):
        many = {w("m%d" % i): ["m%d.example" % i] for i in range(31)}
        busy = w("busy")
        win, _ = window([(D[0], [(busy, S, 1)] + [(busy, m, 1) for m in many], dict(MAP, **many)),
                         (D[1], [], dict(MAP, **many)),
                         (D[2], [(busy, T, 1)], dict(MAP, **many)),
                         (D[3], [], dict(MAP, **many))])
        sw = win["sellers"][S]["switches"]
        self.assertEqual((sw["left_for"], sw["busy_buyers_left_out"]), ([], 1))

    def test_early_buyers_when_the_last_day_is_ten_and_three_times_the_first(self):
        first = [(w("e%d" % i), S, 1) for i in range(3)]
        second = [(w("f%d" % i), S, 1) for i in range(2)] + [(w("e0"), S, 1)]
        last = [(w("g%d" % i), S, 1) for i in range(10)]
        win, _ = window([(D[0], first, MAP), (D[1], second, MAP), (D[2], [], MAP), (D[3], last, MAP)])
        self.assertEqual(win["sellers"][S]["early_buyers"],
                         {"wallets": 5, "days": D[:2], "first_day_buyers": 3, "last_day_buyers": 10})

    def test_no_early_buyers_below_either_bar(self):
        nine = [(w("g%d" % i), S, 1) for i in range(9)]
        win, _ = window([(D[0], [(w("e0"), S, 1)], MAP), (D[1], [], MAP), (D[2], nine, MAP)])
        self.assertIsNone(win["sellers"][S]["early_buyers"])                  # 9 on the last day
        ten = [(w("g%d" % i), S, 1) for i in range(10)]
        four = [(w("e%d" % i), S, 1) for i in range(4)]
        win, _ = window([(D[0], four, MAP), (D[1], [], MAP), (D[2], ten, MAP)])
        self.assertIsNone(win["sellers"][S]["early_buyers"])                  # 10 is under 3 x 4
        win, _ = window([(D[0], [], MAP), (D[1], ten, MAP)])
        self.assertIsNone(win["sellers"][S]["early_buyers"])                  # two days: nothing comes before the last

    def test_exactly_three_times_the_first_day_is_enough(self):
        four = [(w("e%d" % i), S, 1) for i in range(4)]
        twelve = [(w("g%d" % i), S, 1) for i in range(12)]
        win, _ = window([(D[0], four, MAP), (D[1], [], MAP), (D[2], twelve, MAP)])
        self.assertEqual(win["sellers"][S]["early_buyers"]["wallets"], 4)

    def test_a_seller_new_in_the_window_has_early_buyers_from_its_second_day(self):
        ten = [(w("g%d" % i), S, 1) for i in range(12)]
        win, _ = window([(D[0], [], MAP), (D[1], [(w("x"), S, 1)], MAP), (D[2], ten, MAP)])
        self.assertEqual(win["sellers"][S]["early_buyers"]["wallets"], 1)


class EdgeCases(unittest.TestCase):
    def test_one_day_only(self):
        b1, b2 = w("b1"), w("b2")
        win, _ = window([(D[0], [(b1, S, 1), (b2, S, 1), (b1, T, 1)], MAP)])
        f = win["sellers"][S]
        self.assertEqual(win["halves"], {"first": [], "second": []})
        self.assertEqual((f["came_back"]["buyers"], f["switches"]["left_for"], f["switches"]["came_from"]), (0, [], []))
        self.assertEqual(len(f["notes"]), 1)
        self.assertIn("need 2 or more days", f["notes"][0])
        self.assertEqual(f["bought_alongside"]["sellers"][0]["wallet"], T)     # still a fact on one day
        self.assertIsNone(f["early_buyers"])

    def test_a_seller_paid_on_one_day_of_a_longer_window_gets_the_note(self):
        win, _ = window([(D[0], [(w("b1"), S, 1)], MAP), (D[1], [(w("b1"), T, 1)], MAP), (D[2], [(w("b1"), T, 1)], MAP)])
        self.assertIn("paid on 1 day", win["sellers"][S]["notes"][0])
        self.assertEqual(win["sellers"][T]["notes"], [])

    def test_empty_window(self):
        for folder in (tempfile.mkdtemp(), "/nonexistent/flows", None):
            win = rl.window(folder)
            self.assertEqual((win["dates"], win["sellers"], win["hosts"], win["problems"]), ([], {}, {}, []))
            self.assertIsNone(rl.for_host(win, "s.example"))
            self.assertEqual(rl.files_key(folder), ())

    def test_a_seller_with_several_hosts_is_one_wallet(self):
        shared = {S: ["b.example", "a.example"], T: ["t.example"]}
        win, _ = window([(D[0], [(w("b1"), S, 1), (w("b1"), T, 1)], shared)])
        a, b = rl.for_host(win, "a.example"), rl.for_host(win, "B.EXAMPLE")
        self.assertEqual(a["wallets"], b["wallets"])
        f = a["wallets"][0]
        self.assertEqual((f["wallet"], f["hosts"], f["hosts_total"]), (S, ["a.example", "b.example"], 2))
        self.assertEqual(win["sellers"][T]["bought_alongside"]["sellers"][0]["hosts"], ["a.example", "b.example"])

    def test_a_host_on_several_wallets_gets_each_most_buyers_first(self):
        m = {S: ["hub.example", "s.example"], T: ["hub.example"], U: ["u.example"]}
        win, _ = window([(D[0], [(w("b1"), S, 1), (w("b2"), T, 1), (w("b3"), T, 1)], m)])
        v = rl.for_host(win, "hub.example")
        self.assertEqual([f["wallet"] for f in v["wallets"]], [T, S])
        self.assertEqual(v["unpaid_wallets"], [])
        # a host listed on many wallets names none of them well: the particular host comes first
        self.assertEqual(win["sellers"][S]["hosts"], ["s.example", "hub.example"])
        self.assertEqual(rl.for_host(win, "u.example"), {"host": "u.example", "wallets": [], "unpaid_wallets": [U]})
        self.assertIsNone(rl.for_host(win, "nobody.example"))

    def test_hosts_are_capped_and_counted(self):
        m = {S: ["h%02d.example" % i for i in range(20)]}
        win, _ = window([(D[0], [(w("b1"), S, 1)], m)])
        f = win["sellers"][S]
        self.assertEqual((len(f["hosts"]), f["hosts_total"]), (rl.OWN_HOSTS, 20))
        self.assertEqual(len(win["wallet_hosts"][S]), 20)

    def test_bad_files_and_bad_edges_are_left_out_and_named(self):
        folder = tempfile.mkdtemp()
        day_file(folder, D[0], [(w("b1"), S, 1)], MAP)
        day_file(folder, D[1], [(w("b1"), S, 1)], MAP, extra_edges=[{"from": None, "to": S, "n_x402": 1},
                                                                    {"from": w("b2"), "to": S, "n_x402": "7"}, "junk"])
        day_file(folder, D[2], [(w("b9"), S, 1)], MAP, chain="solana")          # another chain: not this window
        with open(os.path.join(folder, "flows-%s.json" % D[3]), "w") as f:
            f.write("{not json")
        with open(os.path.join(folder, "flows-%s.json" % D[4]), "w") as f:
            json.dump({"date": D[0], "edges": [], "sellers": {}}, f)          # says another day
        win = rl.window(folder)
        self.assertEqual(win["dates"], D[:2])
        self.assertEqual(win["sellers"][S]["buyers"]["count"], 1)
        self.assertEqual(win["sellers"][S]["came_back"]["buyers"], 1)
        text = " ".join(win["problems"])
        self.assertIn("flows-%s.json could not be read" % D[3], text)
        self.assertIn("flows-%s.json says it is" % D[4], text)
        self.assertIn("3 edges", text)

    def test_only_the_newest_eight_days_are_the_window(self):
        folder = tempfile.mkdtemp()
        days = ["2026-01-%02d" % i for i in range(1, 11)]
        for d in days:
            day_file(folder, d, [(w("b1"), S, 1)], MAP)
        win = rl.window(folder)
        self.assertEqual(win["dates"], days[-rl.MAX_DAYS:])
        self.assertEqual(win["sellers"][S]["days"]["paid"], rl.MAX_DAYS)

    def test_the_key_changes_with_a_new_day(self):
        win, folder = window([(D[0], [(w("b1"), S, 1)], MAP)])
        k1 = rl.files_key(folder)
        self.assertEqual(k1, win["key"])
        day_file(folder, D[1], [(w("b1"), S, 1)], MAP)
        self.assertNotEqual(rl.files_key(folder), k1)

    def test_deterministic_and_plain_json(self):
        days = [(D[i], [(w("b%d" % j), [S, T, U, V][(i + j) % 4], 1 + j) for j in range(9)], MAP) for i in range(4)]
        a, _ = window(days)
        b, _ = window(days)
        for x in (a, b):
            x.pop("key")
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_our_own_words_and_never_the_forbidden_one(self):
        with open(rl.__file__) as f:
            src = f.read()
        self.assertIsNone(re.search(r"(?i)verif", src))
        for word in ("retention", "churn", "cohort", "score", "rank"):
            self.assertNotIn(word, src.lower(), word)
        self.assertIn("a wallet is not an agent", rl.MEANS.lower())


class PlainWords(unittest.TestCase):
    def test_sentences_show_the_numbers(self):
        b = [w("b%d" % i) for i in range(3)]
        win, _ = window([(D[0], [(b[0], S, 1), (b[1], S, 1), (b[0], T, 1)], MAP),
                         (D[1], [(b[0], S, 1)], MAP),
                         (D[2], [(b[1], U, 1)], MAP),
                         (D[3], [], MAP)])
        text = "\n".join(rl.sentences(win["sellers"][S]))
        self.assertIn("2 buyers paid it on 2 of the window's 4 days", text)
        self.assertIn("1 of 2 buyers came back on another day (50%)", text)
        self.assertIn("bought alongside: t.example (1 shared buyer, 50% of its buyers)", text)
        self.assertIn("1 buyer left for u.example", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
