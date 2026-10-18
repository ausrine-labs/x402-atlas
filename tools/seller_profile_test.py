#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 699dff7). Edit it there, not here.
"""Tests for seller_profile.py: every seller gets one type by a fixed rule, and a page that gives advice first."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seller_profile as sp  # noqa: E402


def row(host="s.example", customers=20, returning=10, independent=10, robots=0, one=False, top=12.0):
    return {"host": host, "customers": customers, "returning": returning, "independent": independent,
            "robot_payers": robots, "one_payer_most": one, "top_payer_share_pct": top}


class Profiles(unittest.TestCase):
    def test_each_type_by_its_rule(self):
        self.assertEqual(sp.kind(row(customers=3)), "quiet")
        self.assertEqual(sp.kind(row(one=True, top=80)), "one big client")
        self.assertEqual(sp.kind(row(robots=20)), "router-fed")
        self.assertNotEqual(sp.kind(row(robots=10)), "router-fed")          # 10 robots of 30 buyers is a third
        self.assertEqual(sp.kind(row(returning=15, independent=1)), "closed loop")
        self.assertEqual(sp.kind(row(returning=8, independent=8)), "regulars")
        self.assertEqual(sp.kind(row(returning=2, independent=8)), "tries")
        self.assertEqual(sp.kind(row(returning=5, independent=2)), "mixed")
        self.assertEqual(set(sp.TYPES), {"quiet", "one big client", "router-fed", "closed loop", "regulars", "tries", "mixed"})

    def test_pages_give_the_numbers_three_priorities_and_one_offer(self):
        out = tempfile.mkdtemp()
        try:
            b = {"window": {"from": "2026-10-09", "to": "2026-10-15"},
                 "sellers": [row("a.example", returning=15, independent=1), row("0x" + "ab" * 20), row("<b>x</b>.example")]}
            ps = sp.build(out, b, "https://atlas.example")
            self.assertEqual(len(ps), 2)                                   # a bare wallet gets no profile
            with open(os.path.join(out, "profile", "a.example", "index.html")) as f:
                html = f.read()
            self.assertIn("Closed loop", html)
            self.assertIn("15 came back on another day", html)
            self.assertEqual(html.count("<li>"), 3)
            self.assertIn("Demand proof report", html)
            self.assertIn("A wallet is not a person", html)
            with open(os.path.join(out, "profile", "index.html")) as f:
                idx = f.read()
            self.assertIn("What kind of x402 seller are you?", idx)
            self.assertNotIn("<b>x</b>", idx)
            import json as _j
            with open(os.path.join(out, "profile", "profiles.json")) as f:
                doc = _j.load(f)
            self.assertEqual([s["type"] for s in doc["sellers"]], ["closed loop", "regulars"])
            self.assertIn("closed loop", doc["types"])
            b["sellers"] = [row("0x.example")]                             # a name that starts 0x is still a name
            self.assertEqual([p["host"] for p in sp.build(out, b, "https://atlas.example")], ["0x.example"])
            self.assertFalse(os.path.exists(os.path.join(out, "profile", "a.example")))   # gone from the Board, gone here
        finally:
            shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()
