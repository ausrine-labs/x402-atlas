#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit 04306cc). Edit it there, not here.
"""atlas_mcp_test.py — the Atlas MCP server, spoken to over real JSON-RPC on
stdio as an agent client would, against a store we built and therefore know.
No network: ATLAS_STORE points at the fixture, so the server never fetches.

    python3 atlas_mcp_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "atlas_mcp.py")
W_AGENT, W_ONE = "0x" + "b2" * 20, "0x" + "a1" * 20
S_WX, S_ENRICH, S_SHARED = "0x" + "c3" * 20, "0x" + "d4" * 20, "0x" + "f6" * 20


def fixture():
    d = tempfile.mkdtemp()
    sellers = {
        "weather.example": {"calls": 900, "payers": 300, "sells": "Current weather and a five day forecast for any city",
                            "price_min": 0.001, "price_med": 0.002, "price_max": 0.005, "take": 1.8, "chains": ["Base"],
                            "endpoints": 3, "url": "https://weather.example/x402", "wallets": [S_WX]},
        "enrich.example": {"calls": 4000, "payers": 50, "sells": "Enrich a person or company from an email address",
                           "price_min": 0.01, "price_med": 0.01, "price_max": 0.01, "take": 40.0, "chains": ["Base"],
                           "endpoints": 1, "url": "https://enrich.example/x402", "wallets": [S_ENRICH]},
        "quiet.example": {"calls": 2, "payers": 1, "sells": "Random numbers", "price_min": 0.001, "price_med": 0.001,
                          "price_max": 0.001, "take": 0.002, "chains": ["Base"], "endpoints": 1,
                          "url": "https://quiet.example/x", "wallets": [S_SHARED]},
        "busy.example": {"calls": 200, "payers": 20, "sells": "Random words", "price_min": 0.001, "price_med": 0.001,
                         "price_max": 0.001, "take": 0.2, "chains": ["Base"], "endpoints": 1,
                         "url": "https://busy.example/x", "wallets": [S_SHARED]},
    }
    for day in ("2026-01-01", "2026-01-02"):
        json.dump({"date": day, "endpoints": 6, "taken": 42.0, "sellers": sellers},
                  open(os.path.join(d, "market-%s.json" % day), "w"))
    whales = {
        "hours": 24, "classified": True, "as_of": "2026-01-03", "dates": ["2026-01-02"],
        "operators": {"quiet.example": {"group": "g1", "hosts": 2, "others": ["busy.example"]},
                      "busy.example": {"group": "g1", "hosts": 2, "others": ["quiet.example"]}},
        "groups": [{"id": "g1", "hosts": ["quiet.example", "busy.example"], "wallets": 1}],
        "totals": {"payments": 351, "usdc": 503.14, "payments_x402": 350, "usdc_x402": 3.14, "buyer_wallets": 2,
                   "buyer_wallets_x402": 2, "sellers_paid": 3, "sellers_known": 4, "operators_known": 3,
                   "operators_paid": 2, "sellers_one_payer": 1, "sellers_concentrated": 0, "agents_3plus": 1},
        "agents": [{"wallet": W_AGENT, "short": "0xb2b2…b2b2", "chain": "Base", "explorer": "https://basescan.org/address/" + W_AGENT,
                    "usdc": 3.14, "payments": 350, "sellers_paid": 3, "usdc_x402": 3.14, "payments_x402": 350,
                    "sellers_paid_x402": 3, "categories": ["people & company data", "world data", "other"],
                    "sellers": [{"host": "enrich.example", "payments": 300, "usdc": 3.0, "payments_x402": 300, "usdc_x402": 3.0},
                                {"host": "weather.example", "payments": 40, "usdc": 0.08, "payments_x402": 40, "usdc_x402": 0.08},
                                {"host": "busy.example", "payments": 10, "usdc": 0.01, "payments_x402": 10, "usdc_x402": 0.01}]}],
        "buyers": [],
        "sellers": [
            {"host": "enrich.example", "chain": "Base", "wallets": [S_ENRICH], "category": "people & company data",
             "on_chain_usdc": 503.0, "on_chain_payments": 301, "on_chain_usdc_x402": 3.0, "on_chain_payments_x402": 300,
             "on_chain_buyer_wallets": 2, "x402_payer_wallets": 1, "x402_top3_share": 100.0,
             "x402_top_payers": [{"wallet": W_AGENT, "payments": 300}], "concentration": "one payer",
             "operator_hosts": 1, "operator_wallets": 1, "operator_other_hosts": []},
            {"host": "weather.example", "chain": "Base", "wallets": [S_WX], "category": "world data",
             "on_chain_usdc": 0.08, "on_chain_payments": 40, "on_chain_usdc_x402": 0.08, "on_chain_payments_x402": 40,
             "on_chain_buyer_wallets": 1, "x402_payer_wallets": 1, "x402_top3_share": 100.0,
             "x402_top_payers": [{"wallet": W_AGENT, "payments": 40}], "concentration": "spread",
             "operator_hosts": 1, "operator_wallets": 1, "operator_other_hosts": []},
            {"host": "busy.example", "chain": "Base", "wallets": [S_SHARED], "category": "other",
             "on_chain_usdc": 0.01, "on_chain_payments": 10, "on_chain_usdc_x402": 0.01, "on_chain_payments_x402": 10,
             "on_chain_buyer_wallets": 1, "x402_payer_wallets": 1, "x402_top3_share": 100.0,
             "x402_top_payers": [{"wallet": W_AGENT, "payments": 10}], "concentration": "spread",
             "operator_hosts": 2, "operator_wallets": 1, "operator_other_hosts": ["quiet.example"]},
        ],
        "notes": [],
    }
    json.dump(whales, open(os.path.join(d, "whales-2026-01-02.json"), "w"))
    return d


STORE = fixture()


def talk(messages):
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    env = dict(os.environ, ATLAS_STORE=STORE, ATLAS_SITE="https://atlas.test")
    p = subprocess.run([sys.executable, SERVER], input=payload, capture_output=True, text=True, timeout=60, env=env)
    out = []
    for line in p.stdout.splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out, p.stderr


def call(tool, args):
    res, err = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}}])
    r = next(x for x in res if x.get("id") == 2)
    text = r["result"]["content"][0]["text"]
    if r["result"].get("isError"):
        raise AssertionError("server error: %s %s" % (text, err))
    return json.loads(text) if text.startswith("{") else text


class Wire(unittest.TestCase):
    def test_handshake_and_list(self):
        res, _ = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                       {"jsonrpc": "2.0", "method": "notifications/initialized"},
                       {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                       {"jsonrpc": "2.0", "id": 3, "method": "nope"}])
        init = next(x for x in res if x.get("id") == 1)["result"]
        self.assertEqual(init["serverInfo"]["name"], "x402-atlas")
        tools = next(x for x in res if x.get("id") == 2)["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["market_today", "search", "seller", "operator", "agents_at_work"])
        for t in tools:
            self.assertIn("inputSchema", t)
            self.assertNotIn("verif", t["description"].lower())
        self.assertEqual(next(x for x in res if x.get("id") == 3)["error"]["code"], -32601)

    def test_unknown_tool_is_text_not_crash(self):
        self.assertEqual(call("nothing", {}), "unknown tool: nothing")


class Market(unittest.TestCase):
    def test_totals_and_busiest(self):
        d = call("market_today", {})
        self.assertEqual(d["day"], "2026-01-02")
        self.assertEqual(d["x402_payments"], 350)
        self.assertEqual(d["sellers_in_registry"], 4)
        self.assertEqual(d["agents_3plus"], 1)
        self.assertEqual(d["usdc_by_other_means"], 500.0)
        self.assertEqual(d["busiest_by_x402"][0]["host"], "enrich.example")
        self.assertEqual(d["busiest_by_x402"][0]["page"], "https://atlas.test/s/enrich.example/")
        self.assertEqual(d["problems"], [])


class Search(unittest.TestCase):
    def test_by_word(self):
        d = call("search", {"query": "forecast"})
        self.assertEqual([s["host"] for s in d["sellers"]], ["weather.example"])
        self.assertEqual(d["sellers"][0]["matched_by"], "words")
        self.assertEqual(d["sellers"][0]["x402_payments_newest_day"], 40)
        self.assertEqual(d["sellers"][0]["price"], "$0.001–$0.005")

    def test_by_intent_ranks_real_payments_first(self):
        d = call("search", {"query": "enrich a person"})
        self.assertIn("people & company data", d["intent"])
        self.assertEqual(d["sellers"][0]["host"], "enrich.example")
        self.assertEqual(d["sellers"][0]["concentration"], "one payer")

    def test_random_finds_both_and_ranks_paid_first(self):
        d = call("search", {"query": "random"})
        self.assertEqual([s["host"] for s in d["sellers"]], ["busy.example", "quiet.example"])

    def test_operator_match_and_limit(self):
        d = call("search", {"query": "example", "limit": 2})
        self.assertEqual(len(d["sellers"]), 2)
        self.assertEqual(d["matched"], 4)
        self.assertEqual(d["operators"][0]["operator"], "quiet.example")

    def test_nothing(self):
        d = call("search", {"query": "zzzz"})
        self.assertEqual(d["sellers"], [])
        self.assertEqual(call("search", {"query": " "})["error"], "say what you are looking for")


class Seller(unittest.TestCase):
    def test_card_with_chain(self):
        d = call("seller", {"name": "enrich.example"})
        self.assertEqual(d["host"], "enrich.example")
        self.assertEqual(d["calls_30d"], 4000)
        self.assertEqual(d["rank_by_calls"], 1)
        self.assertEqual(len(d["replay"]), 2)
        oc = d["on_chain"]
        self.assertTrue(oc["available"])
        self.assertEqual(oc["x402_payments"], 300)
        self.assertEqual(oc["usdc_by_other_means"], 500.0)
        self.assertEqual(oc["concentration"], "one payer")
        self.assertEqual(oc["top_payers"][0]["wallet"], W_AGENT)
        self.assertEqual(d["page"], "https://atlas.test/s/enrich.example/")

    def test_by_wallet_and_operator_hosts(self):
        d = call("seller", {"name": S_SHARED.lower()})
        self.assertIn(d["host"], ("quiet.example", "busy.example"))
        self.assertEqual(d["on_chain"]["operator_hosts"], 2)

    def test_unpaid_seller_says_so(self):
        d = call("seller", {"name": "quiet.example"})
        self.assertEqual(d["on_chain"]["x402_payments"], 0)
        self.assertIn("no USDC", d["on_chain"]["say"])

    def test_unknown_and_ambiguous(self):
        d = call("seller", {"name": "nowhere.example"})
        self.assertFalse(d["found"])
        self.assertIn("not selling", d["say"])
        d = call("seller", {"name": "example"})
        self.assertTrue(d["ambiguous"])
        self.assertEqual(len(d["candidates"]), 4)


class Operator(unittest.TestCase):
    def test_by_host(self):
        d = call("operator", {"name": "busy.example"})
        self.assertEqual(d["operator"], "quiet.example")
        self.assertEqual(d["hosts"], 2)
        self.assertEqual(d["x402_payments_newest_day"], 10)
        self.assertEqual(d["hosts_paid_newest_day"], 1)
        self.assertEqual(d["hosts_list"][0]["host"], "busy.example")
        self.assertEqual(d["page"], "https://atlas.test/o/quiet.example/")
        self.assertNotIn("verif", json.dumps(d).lower())

    def test_group_of_one_and_unknown(self):
        d = call("operator", {"name": "weather.example"})
        self.assertFalse(d["found"])
        self.assertIn("group of one", d["say"])
        d = call("operator", {"name": "nowhere.example"})
        self.assertFalse(d["found"])
        self.assertIn("not a host or operator", d["say"])


class Agents(unittest.TestCase):
    def test_agents(self):
        d = call("agents_at_work", {"limit": 5})
        self.assertEqual(d["agents_3plus"], 1)
        self.assertEqual(d["agents"][0]["wallet"], W_AGENT)
        self.assertEqual(d["agents"][0]["sellers_paid_x402"], 3)
        self.assertEqual(d["agents"][0]["sellers"][0]["host"], "enrich.example")


if __name__ == "__main__":
    unittest.main(verbosity=1)
