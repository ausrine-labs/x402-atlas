#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f23e999). Edit it there, not here.
"""receipts_page_test.py — /receipts/: our money in (from the chain, sorted three ways) and out (by hand). No network."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receipts_page as rp  # noqa: E402

US = "0x" + "aa" * 20
OWN = "0x" + "bb" * 20
ROBOT = "0x" + "cc" * 20
CUST = "0x" + "dd" * 20
TX = "0x" + "ef" * 32


def edge(f, t, n, u):
    return {"from": f, "to": t, "n": n, "usdc": u, "n_x402": n, "usdc_x402": u}


class Receipts(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.flows = os.path.join(self.d, "flows")
        os.makedirs(self.flows)
        self.data = os.path.join(self.d, "receipts.json")
        self.write({"seller_addresses": {"base": [US.upper().replace("0X", "0x")], "solana": ["SoLUs1111111111111111111111111111111111111"]}, "own_test_wallets": [OWN],
                    "card_sales": [], "card_sales_checked": "2026-10-16",
                    "out": [{"date": "2026-10-15", "amount_usdc": 1.001, "chain": "Base", "to": "an agent", "for": "a check", "tx": TX}]})
        day = [edge(CUST, US, 2, 0.002), edge(OWN, US, 1, 0.005), edge(ROBOT, US, 1, 0.001),
               {"from": CUST, "to": US, "n": 3, "usdc": 3.0, "n_x402": 0, "usdc_x402": 0.0}]          # not x402: left out
        day += [edge(ROBOT, "0x%040x" % i, 1, 0.001) for i in range(19)]                               # 20 sellers with us: a robot
        self.put("flows-2026-10-14.json", {"date": "2026-10-14", "hours": 24, "sellers": {}, "edges": day})
        self.put("flows-2026-10-13.json", {"date": "2026-10-13", "sellers": {}, "edges": [edge(CUST, "0x" + "ee" * 20, 1, 1.0)]})   # nothing for us
        self.put("flows-sol-2026-10-14.json", {"date": "2026-10-14", "chain": "solana", "hours": 18, "edges": [edge("SolBuyer", "SoLUs1111111111111111111111111111111111111", 1, 0.01)]})

    def tearDown(self):
        shutil.rmtree(self.d)

    def put(self, name, obj):
        with open(os.path.join(self.flows, name), "w") as f:
            json.dump(obj, f)

    def write(self, obj):
        with open(self.data, "w") as f:
            json.dump(obj, f)

    def build(self):
        out = os.path.join(self.d, "site")
        r = rp.build(out, self.data, self.flows, "https://atlas.example")
        with open(os.path.join(out, "receipts", "index.html"), encoding="utf-8") as f:
            return r, f.read()

    def test_payments_in_are_sorted_three_ways(self):
        days = rp.money_in(self.flows, rp.load(self.data))
        self.assertEqual(days["2026-10-14"]["customers"][:2], [3, 0.012])           # 2 on Base + 1 on Solana
        self.assertEqual(days["2026-10-14"]["ours"][:2], [1, 0.005])
        self.assertEqual(days["2026-10-14"]["robots"][:2], [1, 0.001])
        self.assertEqual(days["2026-10-13"], {})                                      # read, nothing for us
        with open(os.path.join(self.flows, "flows-2026-10-12.json"), "w") as f:
            f.write('{"date": "2026-10-12", "sellers": {}, "edges": [{"from": "%s", "to": "%s", "n_x402": Infinity, "usdc_x402": Infinity}]}' % (CUST, US))
        self.assertEqual(rp.money_in(self.flows, rp.load(self.data))["2026-10-12"], {})          # an infinite row is not money

    def test_the_page_says_what_came_in_and_went_out(self):
        r, page = self.build()
        self.assertEqual(r["days"], 2)
        self.assertIn("<dt>from customers, 13 Oct 2026 to 14 Oct 2026</dt><dd>$0.012</dd>", page)
        self.assertIn("<dd>$1.001</dd>", page)
        self.assertIn("None yet (Pro, seller statements and the Brief, checked 16 Oct 2026).", page)
        self.assertIn('href="https://basescan.org/tx/%s"' % TX, page)
        self.assertNotIn(CUST, page)                                                  # payers by role, never by wallet
        self.assertNotIn("<style>", page)
        self.assertIn('<tr><td>13 Oct 2026</td><td class="n">—</td><td class="n">—</td><td class="n">—</td></tr>', page)   # a quiet day read

    def test_an_unreadable_day_is_said_not_hidden(self):
        with open(os.path.join(self.flows, "flows-2026-10-12.json"), "w") as f:
            f.write("{not json")
        r, page = self.build()
        self.assertEqual(r["unread"], ["2026-10-12"])
        self.assertIn("Not counted: the day file for 12 Oct 2026 could not be read", page)
        self.put("flows-2026-10-11.json", {"date": "2026-10-11", "hours": 6, "sellers": {}, "edges": []})          # a partial day
        self.put("flows-2026-10-10.json", {"date": "2026-10-09", "sellers": {}, "edges": []})                     # its name and date disagree
        r, page = self.build()
        self.put("flows-sol-2026-10-09.json", {"date": "2026-10-09", "edges": []})                               # says no chain: a Base file misplaced
        r, page = self.build()
        self.assertEqual(r["unread"], ["2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12"])

    def test_a_bad_file_is_refused(self):
        for bad in ({"seller_addresses": {"base": ["nope"]}},
                    {"seller_addresses": {"base": [US]}, "out": [{"date": "2026-10-15", "chain": "Base", "amount_usdc": 1, "to": "x", "for": "y", "tx": "0x12"}]},
                    {"seller_addresses": {"base": [US]}, "card_sales": [{"date": "2026-10-15", "amount_usd": 49}]},
                    *({"seller_addresses": {"base": [US]}, "out": [{"date": "2026-10-15", "chain": "Base", "amount_usdc": v, "to": "x",
                                                                     "for": "y", "tx": TX}]} for v in (True, -1, float("nan"), float("inf"), 0)),
                    {"seller_addresses": {"base": [US]}, "out": [{"date": "2026-10-15", "chain": "Solana", "amount_usdc": 1, "to": "x", "for": "y"}]},
                    {"seller_addresses": {"base": [US], "solana": ["typo"]}}):
            self.write(bad)
            with self.assertRaises(ValueError):
                rp.load(self.data)

    def test_the_real_file_loads(self):
        r = rp.load()
        self.assertTrue(r["base"])
        self.assertEqual(len(r["out"]), 1)


if __name__ == "__main__":
    unittest.main()
