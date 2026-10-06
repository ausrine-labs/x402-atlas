#!/usr/bin/env python3
# Copied from the Aušrinė lab (commit f04f064). Edit it there, not here.
"""atlas_mcp_test.py — the Atlas MCP server, spoken to over real JSON-RPC on
stdio as an agent client would, against a store we built and therefore know.
No network: ATLAS_STORE points at the fixture, so the server never fetches. The
data-source tests serve published folders from 127.0.0.1 and nowhere else.

    python3 atlas_mcp_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer, SimpleHTTPRequestHandler

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
        "buyers": [{"wallet": W_AGENT, "short": "0xb2b2…b2b2", "chain": "Base", "payments_x402": 350, "usdc_x402": 3.14,
                    "sellers_paid_x402": 3}],       # every agent is a buyer too, as whales.rollup writes it
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
    wallets = {S_WX: ["weather.example"], S_ENRICH: ["enrich.example"], S_SHARED: ["quiet.example", "busy.example"]}
    x = lambda f, t, n, u: {"from": f, "to": t, "n": n, "usdc": u, "n_x402": n, "usdc_x402": u}
    for day, edges in (("2026-01-01", [x(W_AGENT, S_ENRICH, 100, 1.0)]),
                       ("2026-01-02", [x(W_AGENT, S_ENRICH, 300, 3.0), x(W_AGENT, S_WX, 40, 0.08),
                                       x(W_ONE, S_WX, 1, 0.002)])):
        json.dump({"date": day, "hours": 24, "since_block": 1, "head": 2, "edges": edges, "sellers": wallets},
                  open(os.path.join(d, "flows-%s.json" % day), "w"))
    return d


STORE = fixture()


def talk(messages, store=None, env=None, args=()):
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    if env is None:
        env = dict(os.environ, ATLAS_STORE=store or STORE, ATLAS_SITE="https://atlas.test",
                   ATLAS_SELLER="https://seller.test")
    p = subprocess.run([sys.executable, SERVER] + list(args), input=payload, capture_output=True, text=True, timeout=60, env=env)
    out = []
    for line in p.stdout.splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out, p.stderr


def call(tool, args, store=None, env=None, argv=()):
    """One tool call. argv: the server's own flags (--full answers the whole record; the default is the switch)."""
    res, err = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}}],
                    store, env, argv)
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
        self.assertEqual(init["serverInfo"]["name"], "infoharmoni-atlas")
        self.assertEqual(init["serverInfo"]["title"], "Infoharmoni Atlas")
        self.assertIn("x402 market on Base", init["instructions"])
        tools = next(x for x in res if x.get("id") == 2)["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["market_today", "search", "seller", "operator", "agents_at_work", "compare",
                                                     "agent_spend", "posts"])
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
        self.assertEqual(d["busiest_by_x402"][0]["page"], "https://atlas.test/s/enrich.example/?via=mcp")
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
        self.assertEqual(d["operators"][0]["operator"], "busy.example")

    def test_nothing(self):
        d = call("search", {"query": "zzzz"})
        self.assertEqual(d["sellers"], [])
        self.assertEqual(call("search", {"query": " "})["error"], "say what you are looking for")


class Seller(unittest.TestCase):
    def test_card_with_chain(self):
        d = call("seller", {"name": "enrich.example"}, argv=["--full"])      # the whole record; the free tier: free_tier_test.py
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
        self.assertEqual(d["page"], "https://atlas.test/s/enrich.example/?via=mcp")

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
        self.assertEqual(d["operator"], "busy.example")                        # it took all ten payments
        self.assertEqual(d["hosts"], 2)
        self.assertEqual(d["x402_payments_newest_day"], 10)
        self.assertEqual(d["hosts_paid_newest_day"], 1)
        self.assertEqual(d["hosts_list"][0]["host"], "busy.example")
        self.assertEqual(d["page"], "https://atlas.test/o/quiet.example/?via=mcp")     # the address stays the usual domain, a tie to the first
        self.assertNotIn("verif", json.dumps(d).lower())

    def test_group_of_one_and_unknown(self):
        d = call("operator", {"name": "weather.example"})
        self.assertFalse(d["found"])
        self.assertIn("group of one", d["say"])
        d = call("operator", {"name": "nowhere.example"})
        self.assertFalse(d["found"])
        self.assertIn("not a host or operator", d["say"])


def naming_fixture():
    """Three groups: one host took most of the payments, payments spread, nothing paid."""
    d = tempfile.mkdtemp()
    hosts = ["a.lone.example", "b.lone.example", "earner.example", "c.even.example", "d.even.example", "odd.example",
             "e.idle.example", "f.idle.example", "quiet.other"]
    sellers = {h: {"calls": 10, "payers": 1, "sells": "things", "price_min": 0.01, "price_med": 0.01, "price_max": 0.01,
                   "take": 0.1, "chains": ["Base"], "endpoints": 1, "url": "https://%s/" % h, "wallets": []} for h in hosts}
    json.dump({"date": "2026-01-02", "endpoints": 9, "taken": 1.0, "sellers": sellers},
              open(os.path.join(d, "market-2026-01-02.json"), "w"))

    def paid(h, n):
        return {"host": h, "chain": "Base", "wallets": [], "category": "other", "on_chain_usdc": n / 100.0,
                "on_chain_payments": n, "on_chain_usdc_x402": n / 100.0, "on_chain_payments_x402": n,
                "x402_payer_wallets": 1, "x402_top_payers": [], "concentration": "spread"}
    whales = {"hours": 24, "classified": True, "as_of": "2026-01-03", "dates": ["2026-01-02"], "operators": {},
              "groups": [{"id": 0, "hosts": ["a.lone.example", "b.lone.example", "earner.example"], "wallets": 1},
                         {"id": 1, "hosts": ["c.even.example", "d.even.example", "odd.example"], "wallets": 2},
                         {"id": 2, "hosts": ["e.idle.example", "f.idle.example", "quiet.other"], "wallets": 1}],
              "totals": {}, "agents": [], "buyers": [],
              "sellers": [paid("earner.example", 90), paid("a.lone.example", 10),
                          paid("c.even.example", 40), paid("d.even.example", 30), paid("odd.example", 30)],
              "notes": []}
    json.dump(whales, open(os.path.join(d, "whales-2026-01-02.json"), "w"))
    return d


class Naming(unittest.TestCase):
    """The group's name follows the host that actually earned; its page address does not."""
    @classmethod
    def setUpClass(cls):
        cls.store = naming_fixture()

    def test_one_host_took_most_so_the_group_bears_its_name(self):
        d = call("operator", {"name": "a.lone.example"}, self.store)
        self.assertEqual(d["operator"], "earner.example")
        self.assertEqual(d["page"], "https://atlas.test/o/lone.example/?via=mcp")        # the stable address, not the earner's
        self.assertEqual(call("operator", {"name": "lone.example"}, self.store)["operator"], "earner.example")

    def test_spread_payments_keep_the_domain_name(self):
        d = call("operator", {"name": "odd.example"}, self.store)
        self.assertEqual(d["operator"], "even.example")
        self.assertEqual(d["page"], "https://atlas.test/o/even.example/?via=mcp")

    def test_no_payments_keep_the_domain_name(self):
        d = call("operator", {"name": "quiet.other"}, self.store)
        self.assertEqual(d["operator"], "idle.example")
        self.assertEqual(d["x402_payments_newest_day"], 0)


class Day(unittest.TestCase):
    """The rollup's day is the day it covers, the last of its dates, not the day it was built."""
    def store(self, dates):
        d = tempfile.mkdtemp()
        src = fixture()
        for f in os.listdir(src):
            if f.startswith("market-"):
                os.replace(os.path.join(src, f), os.path.join(d, f))
        w = json.load(open(os.path.join(src, "whales-2026-01-02.json")))
        if dates is None:
            del w["dates"]
        else:
            w["dates"] = dates
        json.dump(w, open(os.path.join(d, "whales-2026-01-03.json"), "w"))     # built on the 3rd
        return d

    def test_the_day_is_the_last_date_rolled_up(self):
        st = self.store(["2026-01-02"])
        d = call("market_today", {}, st)
        self.assertEqual(d["day"], "2026-01-02")
        self.assertEqual(d["dates"], ["2026-01-02"])
        self.assertEqual(call("seller", {"name": "enrich.example"}, st)["on_chain"]["day"], "2026-01-02")
        self.assertEqual(call("agents_at_work", {}, st)["day"], "2026-01-02")

    def test_without_dates_the_file_name_still_answers(self):
        d = call("market_today", {}, self.store(None))
        self.assertEqual(d["day"], "2026-01-03")
        self.assertEqual(d["dates"], [])


class Agents(unittest.TestCase):
    def test_agents(self):
        d = call("agents_at_work", {"limit": 5})
        self.assertEqual(d["agents_3plus"], 1)
        self.assertEqual(d["agents"][0]["wallet"], W_AGENT)
        self.assertEqual(d["agents"][0]["sellers_paid_x402"], 3)
        self.assertEqual(d["agents"][0]["sellers"][0]["host"], "enrich.example")


class Compare(unittest.TestCase):
    def test_side_by_side_with_dates_and_operator(self):
        d = call("compare", {"hosts": ["enrich.example", "https://www.Busy.example/x", "weather.example"]})
        self.assertEqual([r["host"] for r in d["sellers"]], ["enrich.example", "busy.example", "weather.example"])
        self.assertEqual(d["unknown"], [])
        e, b, w = d["sellers"]
        self.assertEqual((e["x402_payments"], e["x402_usdc"], e["payer_wallets"], e["concentration"]),
                         (300, 3.0, 1, "one payer"))
        self.assertEqual((e["calls_30d_self_reported"], e["price"], e["category"]),
                         (4000, "$0.01", "people & company data"))
        self.assertEqual((w["price_min"], w["price_max"]), (0.001, 0.005))
        for r in d["sellers"]:
            self.assertEqual((r["registry_date"], r["chain_day"]), ("2026-01-02", "2026-01-02"), r["host"])
        self.assertEqual(b["operator"]["operator"], "busy.example")
        self.assertEqual(b["operator"]["hosts"], 2)
        self.assertEqual(b["operator"]["page"], "https://atlas.test/o/quiet.example/?via=mcp")
        self.assertIsNone(e["operator"]["operator"])
        self.assertEqual(e["operator"]["hosts"], 1)

    def test_an_unpaid_host_says_so(self):
        d = call("compare", {"hosts": ["quiet.example", "busy.example"]})
        q = d["sellers"][0]
        self.assertEqual((q["x402_payments"], q["payer_wallets"]), (0, 0))
        self.assertIn("no USDC", q["say"])

    def test_unknown_hosts_are_reported_never_guessed(self):
        d = call("compare", {"hosts": ["enrich.example", "enrich.exampl", "example"]})
        self.assertEqual([r["host"] for r in d["sellers"]], ["enrich.example"])
        self.assertEqual([u["host"] for u in d["unknown"]], ["enrich.exampl", "example"])
        for u in d["unknown"]:
            self.assertIn("nothing is guessed", u["say"])
            self.assertEqual(set(u), {"host", "say"})                    # no figure is invented for it

    def test_two_to_five_distinct_hosts(self):
        self.assertIn("two to five", call("compare", {"hosts": ["enrich.example"]})["error"])
        self.assertIn("two to five", call("compare", {"hosts": ["enrich.example", "ENRICH.example"]})["error"])
        six = ["a%d.example" % i for i in range(6)]
        self.assertIn("two to five", call("compare", {"hosts": six})["error"])
        self.assertIn("error", call("compare", {}))
        self.assertEqual(len(call("compare", {"hosts": "enrich.example, weather.example"})["sellers"]), 2)

    def test_all_unknown_offers_nothing(self):
        d = call("compare", {"hosts": ["a.nowhere", "b.nowhere"]})
        self.assertEqual(d["sellers"], [])
        self.assertNotIn("paid_next", d)


def urls(obj):
    """Every http(s) address anywhere in an answer."""
    if isinstance(obj, dict):
        return [u for v in obj.values() for u in urls(v)]
    if isinstance(obj, list):
        return [u for v in obj for u in urls(v)]
    if isinstance(obj, str) and obj.startswith(("http://", "https://")):
        return [obj]
    return []


ANSWERS = [("market_today", {}), ("search", {"query": "random"}), ("search", {"query": "forecast"}),
           ("seller", {"name": "enrich.example"}), ("operator", {"name": "busy.example"}),
           ("agents_at_work", {}), ("compare", {"hosts": ["enrich.example", "busy.example"]}),
           ("agent_spend", {"wallet": W_AGENT})]


class AgentSpend(unittest.TestCase):
    def test_one_wallet_in_brief_and_the_full_report_is_the_paid_next(self):
        d = call("agent_spend", {"wallet": W_AGENT.upper().replace("0X", "0x")}, argv=["--full"])     # the whole record
        self.assertEqual((d["wallet"], d["dates"], d["x402_payments"], d["usdc"], d["sellers_paid"]),
                         (W_AGENT, ["2026-01-01", "2026-01-02"], 440, 4.08, 2))
        self.assertEqual([s["host"] for s in d["top_sellers"]], ["enrich.example", "weather.example"])
        self.assertEqual(d["top_sellers"][0]["page"], "https://atlas.test/s/enrich.example/?via=mcp")
        p = d["paid_next"]
        self.assertEqual((p["url"], p["price"], p["pay"]),
                         ("https://seller.test/watch/%s?via=mcp" % W_AGENT, "$0.01", "x402, USDC on Base"))
        for held_back in ("findings", "per_day", "going_rate", "paid_above_list", "status"):
            self.assertNotIn(held_back, list(d))                       # the brief, not the report

    def test_a_window_and_refusals(self):
        self.assertEqual(call("agent_spend", {"wallet": W_AGENT, "days": 1})["x402_payments"], 340)
        for args in ({"wallet": "0x12"}, {"wallet": ""}, {}, {"wallet": W_AGENT, "days": 30}):
            d = call("agent_spend", args)
            self.assertIn("error", d, args)
            self.assertNotIn("paid_next", d, args)
        d = call("agent_spend", {"wallet": "0x" + "77" * 20})
        self.assertEqual(d["x402_payments"], 0)
        self.assertNotIn("paid_next", d)                                 # the paid door would refuse it, free

    def test_no_flows_in_the_store_says_so(self):
        d = tempfile.mkdtemp()
        for f in os.listdir(STORE):
            if not f.startswith("flows-"):
                with open(os.path.join(STORE, f)) as a, open(os.path.join(d, f), "w") as b:
                    b.write(a.read())
        self.assertIn("error", call("agent_spend", {"wallet": W_AGENT}, store=d))


class PaidNext(unittest.TestCase):
    """One short field, plain facts, the right door for the answer's shape."""

    def test_one_seller_leads_to_the_who_card(self):
        for tool, args, host in (("seller", {"name": "enrich.example"}, "enrich.example"),
                                 ("search", {"query": "forecast"}, "weather.example")):
            p = call(tool, args)["paid_next"]
            self.assertEqual(p["url"], "https://seller.test/who/%s?via=mcp" % host, tool)
            self.assertEqual((p["price"], p["pay"]), ("$0.01", "x402, USDC on Base"), tool)

    def test_market_and_lists_lead_to_the_files(self):
        for (tool, args), first in zip([("market_today", {}), ("search", {"query": "random"}),
                                        ("operator", {"name": "busy.example"}), ("agents_at_work", {}),
                                        ("compare", {"hosts": ["enrich.example", "busy.example"]})],
                                       ["day.json", "sellers.csv", "operators.csv", "buyers.csv", "sellers.csv"]):
            p = call(tool, args)["paid_next"]
            self.assertEqual(list(p["files"])[0], first, tool)
            self.assertEqual({n: f["price"] for n, f in p["files"].items()},
                             {"sellers.csv": "$0.25", "buyers.csv": "$0.25", "operators.csv": "$0.25",
                              "day.json": "$1.00"}, tool)
            for n, f in p["files"].items():
                self.assertEqual(f["url"], "https://seller.test/x402/export/%s?via=mcp" % n, tool)
            self.assertNotIn("url", p)

    def test_refusals_and_empty_answers_offer_nothing(self):
        for tool, args in (("seller", {"name": "nowhere.example"}), ("seller", {"name": "example"}),
                           ("search", {"query": "zzzz"}), ("operator", {"name": "weather.example"}),
                           ("search", {"query": " "})):
            self.assertNotIn("paid_next", call(tool, args), (tool, args))

    def test_plain_never_pushy_never_more_true(self):
        banned = ("verified", "verif", "more accurate", "more true", "accurate", "complete picture", "real answer",
                  "only", "now", "!", "don't miss", "unlock", "premium", "best deal")
        for tool, args in ANSWERS:
            p = call(tool, args)["paid_next"]
            text = json.dumps(p).lower()
            for w in banned:
                self.assertNotIn(w, text, (tool, w))
            self.assertLess(len(p["what"]), 140, tool)

    def test_no_answer_says_verified_or_names_who_owns_a_wallet(self):
        for tool, args in ANSWERS:
            text = json.dumps(call(tool, args)).lower()
            self.assertNotIn("verified", text, tool)
            for w in ("belongs to", "owned by", "is operated by", "identity"):
                self.assertNotIn(w, text, (tool, w))


class Via(unittest.TestCase):
    def test_every_link_to_the_atlas_or_its_seller_carries_via_mcp(self):
        seen = 0
        for tool, args in ANSWERS:
            for u in urls(call(tool, args)):
                if u.startswith(("https://atlas.test", "https://seller.test")):
                    seen += 1
                    self.assertTrue(u.endswith("?via=mcp"), u)
                    self.assertEqual(u.count("via="), 1, u)
                else:
                    self.assertTrue(u.startswith("https://basescan.org/"), u)   # third-party explorer: untouched
        self.assertGreater(seen, 30)

    def test_the_tool_list_links_nowhere_untagged(self):
        res, _ = talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
        for u in urls(res[0]["result"]):
            self.assertIn("via=mcp", u)


# ---------------------------------------------------------------- where the data comes from

def big_snapshot(day, n=1000):
    """A snapshot the real fetcher accepts: it refuses one with fewer than 1000 sellers."""
    row = lambda i: {"calls": i, "payers": 1, "sells": "thing %d" % i, "price_min": 0.01, "price_med": 0.01,
                     "price_max": 0.01, "take": 0.01 * i, "chains": ["Base"], "endpoints": 1,
                     "url": "https://h%d.example/" % i, "wallets": []}
    sellers = {"h%d.example" % i: row(i) for i in range(n)}
    return {"date": day, "endpoints": n, "taken": 1.0, "sellers": sellers}


def published(root, name):
    """root/<name>/radar/ and root/<name>/flows/, laid out as the Atlas publishes them."""
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "x402"))
    import flows_handoff
    import snapshot_handoff
    src = tempfile.mkdtemp()
    json.dump(big_snapshot("2026-01-02"), open(os.path.join(src, "market-2026-01-02.json"), "w"))
    whales = json.load(open(os.path.join(STORE, "whales-2026-01-02.json")))
    whales["sellers"][0]["host"] = "h999.example"                      # a host this registry lists
    json.dump(whales, open(os.path.join(src, "whales-2026-01-02.json"), "w"))
    snapshot_handoff.publish(src, os.path.join(root, name, "radar"))
    flows_handoff.publish(src, os.path.join(root, name, "flows"))


class Redirecting(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/moved/"):
            self.send_response(301)
            self.send_header("Location", "https://elsewhere.test" + self.path)
            self.end_headers()
            return
        SimpleHTTPRequestHandler.do_GET(self)


class DataSource(unittest.TestCase):
    """The data branch first, the site second, both over the real fetchers, which refuse
    redirects. Served from 127.0.0.1 (plain http is allowed only there)."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        published(cls.root, "branch")
        published(cls.root, "site")
        published(cls.root, "bad")                  # a readable manifest over files that fail their checksums
        for part in ("radar", "flows"):
            d = os.path.join(cls.root, "bad", part)
            for f in os.listdir(d):
                if f.endswith(".gz"):
                    with open(os.path.join(d, f), "ab") as fh:
                        fh.write(b"corrupt")
        handler = lambda *a, **k: Redirecting(*a, directory=cls.root, **k)
        cls.httpd = HTTPServer(("127.0.0.1", 0), handler)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def env(self, data, site):
        e = {k: v for k, v in os.environ.items() if k != "ATLAS_STORE"}
        e.update(ATLAS_DATA=self.base + data, ATLAS_SITE=self.base + site, ATLAS_CACHE=tempfile.mkdtemp(),
                 ATLAS_SELLER="https://seller.test")
        return e

    def test_the_data_branch_is_read_first(self):
        d = call("market_today", {}, env=self.env("/branch", "/site"))
        self.assertEqual(d["problems"], [])
        self.assertEqual(d["data_from"], {"radar": self.base + "/branch/radar/", "flows": self.base + "/branch/flows/"})
        self.assertEqual(d["sellers_in_registry"], 1000)
        self.assertEqual(d["day"], "2026-01-02")
        self.assertEqual(d["busiest_by_x402"][0]["page"], self.base + "/site/s/h999.example/?via=mcp")  # pages stay site links

    def test_the_site_answers_when_the_branch_does_not(self):
        d = call("market_today", {}, env=self.env("/missing", "/site"))
        self.assertEqual(d["problems"], [])
        self.assertEqual(d["data_from"], {"radar": self.base + "/site/radar/", "flows": self.base + "/site/flows/"})
        self.assertEqual(d["x402_payments"], 350)

    def test_a_redirecting_site_is_refused_and_the_branch_still_serves(self):
        d = call("market_today", {}, env=self.env("/branch", "/moved"))
        self.assertEqual(d["problems"], [])
        self.assertTrue(d["data_from"]["radar"].startswith(self.base + "/branch/"))

    def test_a_branch_whose_every_file_is_rejected_falls_back_to_the_site(self):
        d = call("market_today", {}, env=self.env("/bad", "/site"))
        self.assertEqual(d["data_from"], {"radar": self.base + "/site/radar/", "flows": self.base + "/site/flows/"})
        self.assertEqual(d["x402_payments"], 350)

    def test_nothing_anywhere_says_where_it_tried(self):
        d = call("market_today", {}, env=self.env("/missing", "/moved"))
        self.assertFalse(d["available"])
        text = " ".join(d["problems"])
        self.assertIn("/missing/radar/", text)
        self.assertIn("/moved/flows/", text)
        self.assertIn("redirect", text)

    def test_a_store_offline_never_fetches(self):
        e = self.env("/branch", "/site")
        e["ATLAS_STORE"] = STORE
        d = call("market_today", {}, env=e)
        self.assertEqual(d["data_from"], {"store": STORE})
        self.assertEqual(d["sellers_in_registry"], 4)



class Packaging(unittest.TestCase):
    """mcp-package/pyproject.toml ships atlas_mcp and everything it imports from beside it,
    and names the console script the README tells people to run. No build, no network: the
    build was proven by hand (see the PR); this keeps the module list honest."""

    def setUp(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11")
        with open(os.path.join(HERE, "mcp-package", "pyproject.toml"), "rb") as f:
            self.p = tomllib.load(f)

    def local_imports(self, module):
        import ast
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            path = os.path.join(HERE, "x402", module + ".py")
        tree = ast.parse(open(path).read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                names.add(n.module.split(".")[0])
        return {x for x in names if os.path.exists(os.path.join(HERE, x + ".py"))
                or os.path.exists(os.path.join(HERE, "x402", x + ".py"))}

    def test_every_local_import_is_shipped(self):
        shipped = set(self.p["tool"]["setuptools"]["py-modules"])
        todo, seen = ["atlas_mcp"], set()
        while todo:
            m = todo.pop()
            if m in seen:
                continue
            seen.add(m)
            todo += sorted(self.local_imports(m))
        self.assertEqual(seen, shipped)

    def test_the_script_and_the_floor(self):
        proj = self.p["project"]
        self.assertEqual(proj["name"], "infoharmoni-atlas-mcp")
        # the new name, and the old one kept so installs from before the rename keep working
        self.assertEqual(proj["scripts"], {"infoharmoni-atlas-mcp": "atlas_mcp:main", "x402-atlas-mcp": "atlas_mcp:main"})
        self.assertEqual(proj["dependencies"], [])
        self.assertEqual(proj["requires-python"], ">=3.10")
        self.assertEqual(self.p["tool"]["setuptools"]["package-dir"], {"": "tools"})
        self.assertEqual(self.p["build-system"]["build-backend"], "setuptools.build_meta")

    def test_the_readme_names_every_client_and_never_says_verified(self):
        text = open(os.path.join(HERE, "mcp-package", "README.md")).read()
        line = "uvx --from git+https://github.com/ausrine-labs/x402-atlas infoharmoni-atlas-mcp"
        self.assertIn(line, text)
        self.assertIn("claude mcp add infoharmoni-atlas -- " + line, text)
        self.assertEqual(text.count('"infoharmoni-atlas": {'), 2)      # Desktop and Cursor
        self.assertIn("Claude Desktop", text)
        self.assertIn("Cursor", text)
        for doc in (text, open(SERVER).read()):
            self.assertNotIn("verified", doc.lower())


class Posts(unittest.TestCase):
    """The free posts tool reads the paid seller's GET /posts, over a local stand-in for it."""

    POSTS = [{"id": "p_0123456789abcdef", "author": W_AGENT, "about": {"kind": "seller", "id": "enrich.example"},
              "text": "fast", "reply_to": None, "time": "2026-01-03T10:00:00Z", "paid_it": True,
              "window": {"as_of": "2026-01-02"}}]

    @classmethod
    def setUpClass(cls):
        seen = cls.seen = []
        posts = cls.POSTS

        class H(SimpleHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                if self.path.startswith("/moved"):
                    self.send_response(302)
                    self.send_header("Location", "https://elsewhere.example/posts")
                    self.end_headers()
                    return
                data = json.dumps({"ok": True, "total": 1, "posts": posts, "note": "paid_it is a fact about one wallet"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        cls.httpd = HTTPServer(("127.0.0.1", 0), H)
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def env(self, seller=None):
        return dict(os.environ, ATLAS_STORE=STORE, ATLAS_SITE="https://atlas.test", ATLAS_SELLER=seller or self.base)

    def test_reads_posts_about_one_thing_and_says_what_posting_costs(self):
        d = call("posts", {"kind": "seller", "id": "Enrich.example", "limit": 5}, env=self.env())
        self.assertEqual(self.seen[-1], "/posts?about=seller:enrich.example&per_page=5&via=mcp")
        self.assertEqual(d["about"], {"kind": "seller", "id": "enrich.example"})
        self.assertEqual(d["posts"][0]["author"], W_AGENT)
        self.assertIs(d["posts"][0]["paid_it"], True)
        p = d["paid_next"]
        self.assertEqual((p["price"], p["method"], p["url"]), ("$0.01", "POST", self.base + "/posts?via=mcp"))
        self.assertEqual(p["body"]["about"], {"kind": "seller", "id": "enrich.example"})
        self.assertLess(len(p["what"]), 140)
        text = json.dumps(d).lower()
        for w in ("verified", "belongs to", "owned by", "is operated by", "identity"):
            self.assertNotIn(w, text)

    def test_plain_words_never_another_companys_terms(self):
        res, _ = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                       {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        d = call("posts", {"kind": "seller", "id": "enrich.example"}, env=self.env())
        text = (json.dumps(res) + json.dumps(d)).lower()
        for w in ("cosign", "co-sign", "karma", "submolt", "molt", "pick", "scout"):
            self.assertNotIn(w, text, w)

    def test_the_default_seller_is_named(self):
        # in-process, so nothing is fetched: only the offer is built
        code = ("import os, sys, json; os.environ.pop('ATLAS_SELLER', None); sys.path.insert(0, %r); "
                "import atlas_mcp; print(json.dumps(atlas_mcp.paid_post('market', 'base')))" % HERE)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                             env={k: v for k, v in os.environ.items() if k != "ATLAS_SELLER"})
        p = json.loads(out.stdout)
        self.assertEqual((p["method"], p["url"], p["price"]), ("POST", "https://ausrine-who.onrender.com/posts?via=mcp", "$0.01"))

    def test_bad_input_and_a_redirect_are_refused_without_an_offer(self):
        for args in ({"kind": "buyer", "id": "x"}, {"kind": "wallet", "id": "0x12"}, {"kind": "seller", "id": "a b"},
                     {"kind": "market", "id": "ethereum"}):
            d = call("posts", args, env=self.env())
            self.assertIn("error", d, args)
            self.assertNotIn("paid_next", d, args)
        d = call("posts", {"kind": "market", "id": "base"}, env=self.env(self.base + "/moved"))
        self.assertIn("error", d)
        self.assertNotIn("paid_next", d)


if __name__ == "__main__":
    unittest.main(verbosity=1)
